"""Subscription lifecycle and payment-provider integration.

The lifecycle functions (``activate``, ``mark_past_due``, ``end_subscription``, ``record_payment`` ...)
are provider-neutral. A provider only has to (1) start a hosted checkout, (2) cancel/resume, and
(3) translate its webhook events into those lifecycle calls. Stripe is the first provider; it is
called over HTTPS without an SDK. Live keys are refused by configuration in this release.

States: pending -> active -> (past_due -> active | expired) | (cancelled -> expired)
* ``cancelled``: the customer cancelled; access continues until ``current_period_end``.
* ``past_due``: a renewal failed; access continues until ``grace_until`` (BILLING_GRACE_DAYS).
* ``expired``: no paid access; the organisation is on the Free plan's limits.
"""

import datetime as dt
import hashlib
import hmac
import json
import time
from dataclasses import dataclass

import httpx
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.logging_config import get_logger
from app.models import BillingEvent, Notification, Organisation, Payment, Subscription, User, utcnow
from app.plans import INTERVALS, Plan
from app.services.usage import audit, get_subscription

log = get_logger("billing")

WEBHOOK_TOLERANCE_SECONDS = 300


class BillingError(Exception):
    def __init__(self, message: str, status: int = 400, code: str = "billing_error"):
        super().__init__(message)
        self.status = status
        self.code = code


# ----------------------------------------------------------------------------- lifecycle (provider neutral)


def _ts(value) -> dt.datetime | None:
    return dt.datetime.fromtimestamp(int(value), dt.UTC) if value else None


async def activate(session: AsyncSession, sub: Subscription, *, plan: str, interval: str | None, provider: str, customer_id: str | None,
                   subscription_id: str | None, period_start: dt.datetime | None, period_end: dt.datetime | None, cancel_at_period_end: bool = False) -> None:
    previous = (sub.plan, sub.status)
    sub.plan, sub.billing_interval, sub.provider = plan, interval, provider
    sub.provider_customer_id = customer_id or sub.provider_customer_id
    sub.provider_subscription_id = subscription_id or sub.provider_subscription_id
    sub.current_period_start = period_start or sub.current_period_start
    sub.current_period_end = period_end or sub.current_period_end
    sub.cancel_at_period_end = cancel_at_period_end
    sub.status = "cancelled" if cancel_at_period_end else "active"
    sub.cancelled_at = (sub.cancelled_at or utcnow()) if cancel_at_period_end else None
    sub.grace_until, sub.pending_plan = None, None
    if previous != (sub.plan, sub.status):
        await audit(session, "subscription.activated" if not cancel_at_period_end else "subscription.cancel_scheduled", organisation_id=sub.organisation_id,
                    details={"plan": plan, "interval": interval, "provider": provider, "from": list(previous)})


async def mark_past_due(session: AsyncSession, sub: Subscription) -> None:
    if sub.status != "past_due":
        sub.status = "past_due"
        sub.grace_until = utcnow() + dt.timedelta(days=get_settings().billing_grace_days)
        session.add(Notification(organisation_id=sub.organisation_id, kind="billing", title="Payment failed - update your card to keep your plan",
                                 body=f"Access continues until {sub.grace_until.date().isoformat()}.", link="/settings?tab=billing"))
        await audit(session, "subscription.past_due", organisation_id=sub.organisation_id, details={"plan": sub.plan, "grace_until": sub.grace_until.isoformat()})


async def end_subscription(session: AsyncSession, sub: Subscription, reason: str) -> None:
    if sub.status != "expired":
        await audit(session, "subscription.expired", organisation_id=sub.organisation_id, details={"plan": sub.plan, "reason": reason})
    sub.status, sub.plan, sub.billing_interval = "expired", "free", None
    sub.cancel_at_period_end, sub.grace_until, sub.pending_plan, sub.provider_subscription_id = False, None, None, None


async def record_payment(session: AsyncSession, organisation_id: int, *, provider: str, payment_id: str, charge_id: str | None, amount_minor: int, currency: str,
                         status: str, plan: str | None, interval: str | None, description: str | None, receipt_url: str | None, paid_at: dt.datetime | None) -> Payment:
    payment = await session.scalar(select(Payment).where(Payment.provider == provider, Payment.provider_payment_id == payment_id))
    if payment is None:
        payment = Payment(organisation_id=organisation_id, provider=provider, provider_payment_id=payment_id, amount_minor=amount_minor, currency=currency, status=status)
        session.add(payment)
    payment.provider_charge_id = charge_id or payment.provider_charge_id
    payment.amount_minor, payment.currency = amount_minor, currency.lower()
    if payment.status not in ("refunded", "partially_refunded"):
        payment.status = status
    payment.plan, payment.billing_interval = plan or payment.plan, interval or payment.billing_interval
    payment.description, payment.receipt_url, payment.paid_at = description or payment.description, receipt_url or payment.receipt_url, paid_at or payment.paid_at
    return payment


def effective_plan_key(sub: Subscription, now: dt.datetime | None = None) -> str:
    """The plan whose limits apply *right now*, taking cancellation, grace and expiry into account."""
    now = now or utcnow()
    grace = dt.timedelta(days=get_settings().billing_grace_days)
    if sub.status == "active":
        # Provider-managed subscriptions are renewed by webhooks; tolerate a late webhook for the grace period only.
        if sub.provider != "manual" and sub.current_period_end and now > sub.current_period_end + grace:
            return "free"
        return sub.plan
    if sub.status == "cancelled":
        return sub.plan if (sub.current_period_end is None or now <= sub.current_period_end) else "free"
    if sub.status == "past_due":
        return sub.plan if (sub.grace_until and now <= sub.grace_until) else "free"
    return "free"  # pending, expired


# ----------------------------------------------------------------------------- Stripe


@dataclass
class CheckoutSession:
    url: str
    session_id: str


def _flatten(data: dict, prefix: str = "") -> dict[str, str]:
    """Stripe's form encoding: {"a": {"b": 1}, "c": [{"d": 2}]} -> {"a[b]": "1", "c[0][d]": "2"}."""
    out: dict[str, str] = {}
    for key, value in data.items():
        name = f"{prefix}[{key}]" if prefix else str(key)
        if isinstance(value, dict):
            out.update(_flatten(value, name))
        elif isinstance(value, list):
            for index, item in enumerate(value):
                out.update(_flatten(item, f"{name}[{index}]") if isinstance(item, dict) else {f"{name}[{index}]": str(item)})
        elif value is not None:
            out[name] = "true" if value is True else "false" if value is False else str(value)
    return out


class StripeProvider:
    name = "stripe"

    def __init__(self, transport: httpx.AsyncBaseTransport | None = None):
        settings = get_settings()
        if not settings.stripe_configured:
            raise BillingError("Card payments are not configured on this instance. Set BILLING_PROVIDER=stripe and STRIPE_SECRET_KEY (test mode).", 503, "billing_not_configured")
        self._key = settings.stripe_secret_key or ""
        self._base = settings.stripe_api_url.rstrip("/")
        self._transport = transport

    async def _post(self, path: str, data: dict, idempotency_key: str | None = None) -> dict:
        headers = {"Authorization": f"Bearer {self._key}"}
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        try:
            async with httpx.AsyncClient(timeout=20.0, transport=self._transport) as http:
                resp = await http.post(f"{self._base}{path}", headers=headers, data=_flatten(data))
        except httpx.HTTPError as exc:
            raise BillingError("The payment provider could not be reached. Please try again.", 502, "billing_provider_unavailable") from exc
        body = resp.json() if resp.content else {}
        if resp.status_code >= 300:
            log.error("stripe_error", path=path, status=resp.status_code, error_type=(body.get("error") or {}).get("type"))
            raise BillingError((body.get("error") or {}).get("message") or "The payment provider rejected the request.", 502, "billing_provider_error")
        return body

    async def create_checkout(self, org: Organisation, user: User, sub: Subscription, plan: Plan, interval: str, success_url: str, cancel_url: str) -> CheckoutSession:
        amount = plan.price_minor(interval)
        if not plan.purchasable or not amount:
            raise BillingError(f"The {plan.name} plan cannot be purchased online.", 400, "plan_not_purchasable")
        metadata = {"organisation_id": org.id, "plan": plan.key, "interval": interval}
        data: dict = {
            "mode": "subscription",
            "success_url": success_url,
            "cancel_url": cancel_url,
            "client_reference_id": str(org.id),
            "metadata": metadata,
            "subscription_data": {"metadata": metadata},
            "line_items": [{
                "quantity": 1,
                "price_data": {
                    "currency": get_settings().billing_currency,
                    "unit_amount": amount,
                    "recurring": {"interval": interval},
                    "product_data": {"name": f"Signal Atlas {plan.name} ({'annual' if interval == 'year' else 'monthly'})"},
                },
            }],
        }
        if sub.provider == "stripe" and sub.provider_customer_id:
            data["customer"] = sub.provider_customer_id
        else:
            data["customer_email"] = user.email
        result = await self._post("/v1/checkout/sessions", data)
        return CheckoutSession(url=result["url"], session_id=result["id"])

    async def set_cancel_at_period_end(self, sub: Subscription, cancel: bool) -> dict:
        if not sub.provider_subscription_id:
            raise BillingError("There is no active card subscription to change.", 400, "no_subscription")
        return await self._post(f"/v1/subscriptions/{sub.provider_subscription_id}", {"cancel_at_period_end": cancel})

    async def portal_url(self, sub: Subscription, return_url: str) -> str:
        if not sub.provider_customer_id:
            raise BillingError("No billing account exists yet. Subscribe to a plan first.", 400, "no_customer")
        return (await self._post("/v1/billing_portal/sessions", {"customer": sub.provider_customer_id, "return_url": return_url}))["url"]


def verify_stripe_signature(payload: bytes, header: str | None, secret: str, now: float | None = None) -> dict:
    """Verify a ``Stripe-Signature`` header (HMAC-SHA256 over ``{timestamp}.{payload}``) and return the event."""
    if not header:
        raise BillingError("Missing signature.", 400, "invalid_signature")
    parts: dict[str, list[str]] = {}
    for item in header.split(","):
        key, _, value = item.strip().partition("=")
        parts.setdefault(key, []).append(value)
    timestamp = (parts.get("t") or [""])[0]
    if not timestamp.isdigit() or not parts.get("v1"):
        raise BillingError("Malformed signature.", 400, "invalid_signature")
    expected = hmac.new(secret.encode(), f"{timestamp}.".encode() + payload, hashlib.sha256).hexdigest()
    if not any(hmac.compare_digest(expected, candidate) for candidate in parts["v1"]):
        raise BillingError("Signature mismatch.", 400, "invalid_signature")
    if abs((now if now is not None else time.time()) - int(timestamp)) > WEBHOOK_TOLERANCE_SECONDS:
        raise BillingError("Signature timestamp outside tolerance.", 400, "invalid_signature")
    try:
        return json.loads(payload)
    except ValueError as exc:
        raise BillingError("Invalid payload.", 400, "invalid_payload") from exc


def _stripe_status(obj: dict) -> str:
    return {"active": "active", "trialing": "active", "past_due": "past_due", "unpaid": "past_due", "canceled": "expired",
            "incomplete": "pending", "incomplete_expired": "expired", "paused": "past_due"}.get(obj.get("status", ""), "pending")


def _period(obj: dict) -> tuple[dt.datetime | None, dt.datetime | None]:
    # Newer Stripe API versions report the period on the subscription item rather than the subscription.
    item = ((obj.get("items") or {}).get("data") or [{}])[0]
    return _ts(obj.get("current_period_start") or item.get("current_period_start")), _ts(obj.get("current_period_end") or item.get("current_period_end"))


async def _find_subscription(session: AsyncSession, *, organisation_id=None, customer_id=None, subscription_id=None) -> Subscription | None:
    if organisation_id:
        try:
            org = await session.get(Organisation, int(organisation_id))
        except (TypeError, ValueError):
            org = None
        if org:
            return await get_subscription(session, org.id)
    if subscription_id:
        found = await session.scalar(select(Subscription).where(Subscription.provider_subscription_id == subscription_id))
        if found:
            return found
    if customer_id:
        return await session.scalar(select(Subscription).where(Subscription.provider_customer_id == customer_id))
    return None


async def apply_stripe_event(session: AsyncSession, event: dict) -> tuple[str, int | None]:
    """Translate one verified Stripe event into lifecycle calls. Returns ``(outcome, organisation_id)``."""
    kind = event.get("type", "")
    obj = (event.get("data") or {}).get("object") or {}
    meta = obj.get("metadata") or {}

    if kind == "checkout.session.completed":
        if obj.get("mode") != "subscription":
            return "ignored", None
        sub = await _find_subscription(session, organisation_id=meta.get("organisation_id") or obj.get("client_reference_id"))
        if sub is None:
            return "unknown_organisation", None
        sub.provider, sub.provider_customer_id, sub.provider_subscription_id = "stripe", obj.get("customer"), obj.get("subscription")
        if obj.get("payment_status") in ("paid", "no_payment_required") and meta.get("plan") in ("pro", "business"):
            await activate(session, sub, plan=meta["plan"], interval=meta.get("interval") if meta.get("interval") in INTERVALS else None, provider="stripe",
                           customer_id=obj.get("customer"), subscription_id=obj.get("subscription"), period_start=utcnow(), period_end=None)
        return "processed", sub.organisation_id

    if kind in ("customer.subscription.created", "customer.subscription.updated"):
        sub = await _find_subscription(session, organisation_id=meta.get("organisation_id"), subscription_id=obj.get("id"), customer_id=obj.get("customer"))
        if sub is None:
            return "unknown_organisation", None
        if sub.provider_subscription_id and sub.provider_subscription_id != obj.get("id") and sub.status in ("active", "cancelled", "past_due"):
            return "ignored_other_subscription", sub.organisation_id
        status = _stripe_status(obj)
        start, end = _period(obj)
        plan = meta.get("plan") if meta.get("plan") in ("pro", "business") else sub.plan
        interval = meta.get("interval") if meta.get("interval") in INTERVALS else sub.billing_interval
        if status == "active":
            await activate(session, sub, plan=plan, interval=interval, provider="stripe", customer_id=obj.get("customer"), subscription_id=obj.get("id"),
                           period_start=start, period_end=end, cancel_at_period_end=bool(obj.get("cancel_at_period_end")))
        elif status == "past_due":
            sub.plan, sub.billing_interval, sub.provider, sub.provider_subscription_id = plan, interval, "stripe", obj.get("id")
            sub.current_period_start, sub.current_period_end = start or sub.current_period_start, end or sub.current_period_end
            await mark_past_due(session, sub)
        elif status == "expired":
            await end_subscription(session, sub, "provider reported the subscription as ended")
        return "processed", sub.organisation_id

    if kind == "customer.subscription.deleted":
        sub = await _find_subscription(session, subscription_id=obj.get("id"), customer_id=obj.get("customer"))
        if sub is None:
            return "unknown_organisation", None
        if sub.provider_subscription_id in (None, obj.get("id")):
            await end_subscription(session, sub, "subscription ended at the provider")
        return "processed", sub.organisation_id

    if kind in ("invoice.paid", "invoice.payment_failed"):
        parent = (obj.get("parent") or {}).get("subscription_details") or {}
        sub_id = obj.get("subscription") or parent.get("subscription")
        invoice_meta = (obj.get("subscription_details") or {}).get("metadata") or parent.get("metadata") or {}
        sub = await _find_subscription(session, organisation_id=invoice_meta.get("organisation_id"), subscription_id=sub_id, customer_id=obj.get("customer"))
        if sub is None:
            return "unknown_organisation", None
        paid = kind == "invoice.paid"
        line = ((obj.get("lines") or {}).get("data") or [{}])[0]
        await record_payment(
            session, sub.organisation_id, provider="stripe", payment_id=obj["id"], charge_id=obj.get("charge"),
            amount_minor=int(obj.get("amount_paid") if paid else obj.get("amount_due") or 0), currency=obj.get("currency") or "gbp",
            status="succeeded" if paid else "failed", plan=invoice_meta.get("plan") or sub.pending_plan or sub.plan, interval=invoice_meta.get("interval") or sub.billing_interval,
            description=line.get("description") or obj.get("description"), receipt_url=obj.get("hosted_invoice_url"),
            paid_at=_ts((obj.get("status_transitions") or {}).get("paid_at")) or (utcnow() if paid else None))
        if paid:
            period = line.get("period") or {}
            if sub.status in ("past_due", "pending") and sub.plan in ("pro", "business"):
                sub.status, sub.grace_until = "active", None
                await audit(session, "subscription.renewed", organisation_id=sub.organisation_id, details={"plan": sub.plan})
            if period.get("end"):
                sub.current_period_start, sub.current_period_end = _ts(period.get("start")), _ts(period.get("end"))
        elif sub.plan in ("pro", "business"):
            await mark_past_due(session, sub)
        return "processed", sub.organisation_id

    if kind == "charge.refunded":
        payment = None
        if obj.get("invoice"):
            payment = await session.scalar(select(Payment).where(Payment.provider == "stripe", Payment.provider_payment_id == obj["invoice"]))
        if payment is None and obj.get("id"):
            payment = await session.scalar(select(Payment).where(Payment.provider == "stripe", Payment.provider_charge_id == obj["id"]))
        if payment is None:
            return "unknown_payment", None
        payment.refunded_minor = int(obj.get("amount_refunded") or 0)
        payment.status = "refunded" if payment.refunded_minor >= payment.amount_minor else "partially_refunded"
        await audit(session, "payment.refunded", organisation_id=payment.organisation_id, target_type="payment", target_id=payment.id,
                    details={"refunded_minor": payment.refunded_minor, "amount_minor": payment.amount_minor})
        return "processed", payment.organisation_id

    return "ignored", None


async def process_stripe_webhook(session: AsyncSession, payload: bytes, signature: str | None) -> dict:
    """Verify, de-duplicate and apply a Stripe webhook. Safe to call repeatedly with the same event."""
    settings = get_settings()
    if not settings.stripe_webhook_secret:
        raise BillingError("Webhook secret is not configured.", 503, "billing_not_configured")
    event = verify_stripe_signature(payload, signature, settings.stripe_webhook_secret)
    event_id = event.get("id")
    if not event_id:
        raise BillingError("Event has no id.", 400, "invalid_payload")
    if event.get("livemode") and not settings.allow_live_payments:
        return {"status": "ignored", "reason": "live-mode events are not accepted"}
    if await session.scalar(select(BillingEvent.id).where(BillingEvent.provider == "stripe", BillingEvent.event_id == event_id)):
        return {"status": "duplicate"}
    ledger = BillingEvent(provider="stripe", event_id=event_id, event_type=event.get("type", "")[:80])
    session.add(ledger)
    try:
        await session.flush()  # the unique constraint makes concurrent deliveries of the same event collide here
    except IntegrityError:
        await session.rollback()
        return {"status": "duplicate"}
    outcome, organisation_id = await apply_stripe_event(session, event)
    ledger.outcome, ledger.organisation_id = outcome, organisation_id
    await session.commit()
    log.info("billing_webhook", event_type=event.get("type"), outcome=outcome)
    return {"status": outcome}
