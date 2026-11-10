"""Subscription lifecycle, Stripe checkout (mocked HTTP), signed idempotent webhooks, entitlements and history."""

import datetime as dt
import hashlib
import hmac
import json
import time
from urllib.parse import parse_qs

import pytest
import respx
from httpx import Response
from sqlalchemy import func, select

from app import plans as plans_module
from app.config import Settings
from app.models import AuditLog, BillingEvent, Notification, Payment, Subscription, utcnow
from app.services import billing
from tests.conftest import make_client

STRIPE = "https://api.stripe.com"
WEBHOOK_SECRET = "whsec_test_secret"
PERIOD_START = int(time.time())
PERIOD_END = PERIOD_START + 365 * 86400


@pytest.fixture
def stripe(settings, monkeypatch):
    monkeypatch.setattr(settings, "billing_provider", "stripe")
    monkeypatch.setattr(settings, "stripe_secret_key", "sk_test_abc123")
    monkeypatch.setattr(settings, "stripe_webhook_secret", WEBHOOK_SECRET)
    monkeypatch.setattr(settings, "allow_self_serve_plan_change", False)
    return settings


def signed(event: dict, secret: str = WEBHOOK_SECRET, timestamp: int | None = None) -> tuple[bytes, dict]:
    payload = json.dumps(event).encode()
    ts = timestamp or int(time.time())
    signature = hmac.new(secret.encode(), f"{ts}.".encode() + payload, hashlib.sha256).hexdigest()
    return payload, {"Stripe-Signature": f"t={ts},v1={signature}", "Content-Type": "application/json"}


async def deliver(event: dict, **kwargs) -> Response:
    payload, headers = signed(event, **kwargs)
    async with make_client() as provider:  # no session, no CSRF token: authenticity is the signature
        return await provider.post("/api/v1/billing/webhooks/stripe", content=payload, headers=headers)


def event(event_id: str, kind: str, obj: dict) -> dict:
    return {"id": event_id, "type": kind, "livemode": False, "data": {"object": obj}}


def subscription_obj(org_id: int, status: str = "active", plan: str = "pro", interval: str = "year", cancel: bool = False, sub_id: str = "sub_1") -> dict:
    return {"id": sub_id, "customer": "cus_1", "status": status, "cancel_at_period_end": cancel, "current_period_start": PERIOD_START, "current_period_end": PERIOD_END,
            "metadata": {"organisation_id": str(org_id), "plan": plan, "interval": interval}}


def invoice_obj(org_id: int, invoice_id: str = "in_1", amount: int = 19000, paid: bool = True) -> dict:
    return {"id": invoice_id, "customer": "cus_1", "subscription": "sub_1", "charge": "ch_1", "currency": "gbp", "amount_paid": amount if paid else 0, "amount_due": amount,
            "hosted_invoice_url": "https://invoice.stripe.com/i/test", "status_transitions": {"paid_at": PERIOD_START if paid else None},
            "subscription_details": {"metadata": {"organisation_id": str(org_id), "plan": "pro", "interval": "year"}},
            "lines": {"data": [{"description": "Signal Atlas Pro (annual)", "period": {"start": PERIOD_START, "end": PERIOD_END}}]}}


async def activate_pro(client) -> int:
    org_id = client.me["organisation"]["id"]
    session = {"id": "cs_1", "mode": "subscription", "payment_status": "paid", "customer": "cus_1", "subscription": "sub_1", "client_reference_id": str(org_id),
               "metadata": {"organisation_id": str(org_id), "plan": "pro", "interval": "year"}}
    assert (await deliver(event("evt_checkout", "checkout.session.completed", session))).json() == {"status": "processed"}
    assert (await deliver(event("evt_sub_created", "customer.subscription.created", subscription_obj(org_id)))).status_code == 200
    assert (await deliver(event("evt_invoice_paid", "invoice.paid", invoice_obj(org_id)))).status_code == 200
    return org_id


# ----------------------------------------------------------------------------- plans and configuration


def test_prices_and_limits_are_centralised_and_overridable():
    pro, business = plans_module.get_plan("pro"), plans_module.get_plan("business")
    assert (pro.price_minor("month"), pro.price_minor("year"), business.price_minor("month"), business.price_minor("year")) == (1900, 19000, 4900, 49000)
    assert plans_module.get_plan("enterprise").price_minor("month") is None and plans_module.get_plan("professional").key == "business"  # legacy key
    assert plans_module.get_plan("unknown").key == "free" and plans_module.PLAN_ORDER == ["free", "pro", "business", "enterprise"]
    overridden = plans_module._plans(json.dumps({"pro": {"price_gbp_month": 25, "reports_per_month": 40, "key": "hacked"}}))
    assert (overridden["pro"].price_gbp_month, overridden["pro"].reports_per_month, overridden["pro"].key) == (25, 40, "pro")
    assert overridden["business"].price_gbp_month == 49


def test_live_stripe_keys_are_refused_by_configuration():
    with pytest.raises(ValueError, match="test-mode key"):
        Settings(stripe_secret_key="sk_live_" + "x" * 24)
    assert Settings(billing_provider="stripe", stripe_secret_key="sk_test_ok").stripe_test_mode is True


# ----------------------------------------------------------------------------- checkout


async def test_checkout_creates_hosted_session_with_central_price_and_metadata(client, stripe, db):
    with respx.mock(assert_all_called=True) as mock:
        route = mock.post(f"{STRIPE}/v1/checkout/sessions").mock(return_value=Response(200, json={"id": "cs_test_1", "url": "https://checkout.stripe.com/c/pay/cs_test_1"}))
        resp = await client.post("/api/v1/billing/checkout", json={"plan": "business", "interval": "year"})
    assert resp.status_code == 200
    assert resp.json() == {"status": "redirect", "checkout_url": "https://checkout.stripe.com/c/pay/cs_test_1", "test_mode": True}
    request = route.calls.last.request
    form = {k: v[0] for k, v in parse_qs(request.content.decode()).items()}
    org_id = str(client.me["organisation"]["id"])
    assert request.headers["authorization"] == "Bearer sk_test_abc123"
    assert form["mode"] == "subscription" and form["customer_email"] == "owner-a@example.com" and form["client_reference_id"] == org_id
    assert form["line_items[0][price_data][unit_amount]"] == "49000" and form["line_items[0][price_data][currency]"] == "gbp"
    assert form["line_items[0][price_data][recurring][interval]"] == "year"
    assert form["subscription_data[metadata][plan]"] == "business" and form["subscription_data[metadata][organisation_id]"] == org_id
    assert "/settings?tab=billing&checkout=success" in form["success_url"]
    # starting checkout grants nothing: entitlements only change when the provider confirms payment
    sub = (await client.get("/api/v1/billing/subscription")).json()
    assert sub["plan"]["key"] == "free" and sub["billing"]["checkout_available"] is True and sub["billing"]["test_mode"] is True
    assert (await client.post("/api/v1/api-keys", json={"name": "CI"})).status_code == 402


async def test_checkout_reports_provider_errors_and_is_owner_only(client, other_client, stripe):
    with respx.mock() as mock:
        mock.post(f"{STRIPE}/v1/checkout/sessions").mock(return_value=Response(401, json={"error": {"type": "invalid_request_error", "message": "Invalid API Key provided"}}))
        failed = await client.post("/api/v1/billing/checkout", json={"plan": "pro"})
    assert failed.status_code == 502 and failed.json()["error"]["code"] == "billing_provider_error"
    async with make_client() as anonymous:
        assert (await anonymous.post("/api/v1/billing/checkout", json={"plan": "pro"})).status_code == 401


# ----------------------------------------------------------------------------- webhooks


async def test_webhook_rejects_bad_signatures_and_stale_timestamps(client, stripe, db):
    org_id = client.me["organisation"]["id"]
    evt = event("evt_bad", "customer.subscription.created", subscription_obj(org_id))
    wrong_secret = await deliver(evt, secret="whsec_attacker")
    stale = await deliver(evt, timestamp=int(time.time()) - 3600)
    async with make_client() as provider:
        unsigned = await provider.post("/api/v1/billing/webhooks/stripe", content=json.dumps(evt).encode())
        payload, headers = signed(evt)
        tampered = await provider.post("/api/v1/billing/webhooks/stripe", content=payload.replace(b"pro", b"business"), headers=headers)
    for resp in (wrong_secret, stale, unsigned, tampered):
        assert resp.status_code == 400 and resp.json()["error"]["code"] == "invalid_signature"
    assert await db.scalar(select(func.count()).select_from(BillingEvent)) == 0
    assert (await client.get("/api/v1/billing/subscription")).json()["plan"]["key"] == "free"


async def test_paid_checkout_activates_plan_and_unlocks_entitlements_idempotently(client, stripe, db):
    org_id = await activate_pro(client)
    sub = (await client.get("/api/v1/billing/subscription")).json()
    assert (sub["plan"]["key"], sub["status"], sub["billing_interval"], sub["provider"], sub["manageable"]) == ("pro", "active", "year", "stripe", True)
    assert sub["current_period_end"].startswith(dt.datetime.fromtimestamp(PERIOD_END, dt.UTC).date().isoformat())
    assert (await client.post("/api/v1/api-keys", json={"name": "CI"})).status_code == 201  # premium entitlement now granted server-side

    # replaying the same events (Stripe retries) changes nothing
    for evt_id, kind, obj in (("evt_checkout", "checkout.session.completed", {}), ("evt_invoice_paid", "invoice.paid", invoice_obj(org_id))):
        assert (await deliver(event(evt_id, kind, obj))).json() == {"status": "duplicate"}
    # a *different* event for the same invoice must not double-count the payment
    assert (await deliver(event("evt_invoice_paid_again", "invoice.paid", invoice_obj(org_id)))).json() == {"status": "processed"}
    history = (await client.get("/api/v1/billing/payments")).json()["items"]
    assert len(history) == 1
    assert (history[0]["amount_minor"], history[0]["currency"], history[0]["status"], history[0]["plan"], history[0]["billing_interval"]) == (19000, "GBP", "succeeded", "pro", "year")
    assert history[0]["receipt_url"] == "https://invoice.stripe.com/i/test"
    assert await db.scalar(select(func.count()).select_from(BillingEvent)) == 4
    assert "subscription.activated" in set((await db.scalars(select(AuditLog.action))).all())


async def test_failed_renewal_enters_grace_then_expires_and_recovers_on_payment(client, stripe, db):
    org_id = await activate_pro(client)
    failed = await deliver(event("evt_fail", "invoice.payment_failed", invoice_obj(org_id, invoice_id="in_2", paid=False)))
    assert failed.json() == {"status": "processed"}
    sub = (await client.get("/api/v1/billing/subscription")).json()
    assert sub["status"] == "past_due" and sub["plan"]["key"] == "pro" and sub["grace_until"] is not None  # access kept during grace
    note = await db.scalar(select(Notification).where(Notification.kind == "billing"))
    assert note.organisation_id == org_id and "Payment failed" in note.title
    history = {p["status"] for p in (await client.get("/api/v1/billing/payments")).json()["items"]}
    assert history == {"succeeded", "failed"}

    row = await db.scalar(select(Subscription).where(Subscription.organisation_id == org_id))
    row.grace_until = utcnow() - dt.timedelta(hours=1)  # the grace period runs out
    await db.commit()
    expired = (await client.get("/api/v1/billing/subscription")).json()
    assert expired["status"] == "past_due" and expired["plan"]["key"] == "free" and expired["subscribed_plan"]["key"] == "pro"
    assert (await client.post("/api/v1/api-keys", json={"name": "blocked"})).status_code == 402

    recovered = await deliver(event("evt_recover", "invoice.paid", invoice_obj(org_id, invoice_id="in_2")))
    assert recovered.json() == {"status": "processed"}
    sub = (await client.get("/api/v1/billing/subscription")).json()
    assert (sub["status"], sub["plan"]["key"], sub["grace_until"]) == ("active", "pro", None)
    assert len((await client.get("/api/v1/billing/payments")).json()["items"]) == 2  # the failed invoice became a paid one, not a third row


async def test_cancel_keeps_access_until_period_end_then_downgrades(client, stripe, db):
    org_id = await activate_pro(client)
    with respx.mock(assert_all_called=True) as mock:
        route = mock.post(f"{STRIPE}/v1/subscriptions/sub_1").mock(return_value=Response(200, json=subscription_obj(org_id, cancel=True)))
        cancelled = await client.post("/api/v1/billing/cancel")
    assert parse_qs(route.calls.last.request.content.decode()) == {"cancel_at_period_end": ["true"]}
    assert cancelled.json()["status"] == "cancelled" and cancelled.json()["cancel_at_period_end"] is True
    sub = (await client.get("/api/v1/billing/subscription")).json()
    assert sub["status"] == "cancelled" and sub["plan"]["key"] == "pro"  # paid period is honoured

    with respx.mock() as mock:
        mock.post(f"{STRIPE}/v1/subscriptions/sub_1").mock(return_value=Response(200, json=subscription_obj(org_id)))
        assert (await client.post("/api/v1/billing/resume")).json()["status"] == "active"

    # the provider confirms a scheduled cancellation, then the subscription ends
    assert (await deliver(event("evt_cancel_flag", "customer.subscription.updated", subscription_obj(org_id, cancel=True)))).status_code == 200
    assert (await client.get("/api/v1/billing/subscription")).json()["status"] == "cancelled"
    assert (await deliver(event("evt_deleted", "customer.subscription.deleted", subscription_obj(org_id, status="canceled")))).json() == {"status": "processed"}
    ended = (await client.get("/api/v1/billing/subscription")).json()
    assert (ended["status"], ended["plan"]["key"], ended["manageable"]) == ("expired", "free", False)
    assert (await client.post("/api/v1/billing/cancel")).status_code == 400
    assert {"subscription.cancel_scheduled", "subscription.resumed", "subscription.expired"} <= set((await db.scalars(select(AuditLog.action))).all())


async def test_cancelled_subscription_past_its_period_grants_no_access(client, stripe, db):
    org_id = await activate_pro(client)
    row = await db.scalar(select(Subscription).where(Subscription.organisation_id == org_id))
    row.status, row.cancel_at_period_end, row.current_period_end = "cancelled", True, utcnow() - dt.timedelta(days=1)
    await db.commit()
    assert billing.effective_plan_key(row) == "free"
    assert (await client.get("/api/v1/billing/subscription")).json()["plan"]["key"] == "free"
    row.status, row.current_period_end = "active", utcnow() - dt.timedelta(days=30)  # renewal webhook never arrived
    assert billing.effective_plan_key(row) == "free"
    row.current_period_end = utcnow() - dt.timedelta(days=2)  # inside the grace window
    assert billing.effective_plan_key(row) == "pro"


async def test_refunds_are_recorded_against_the_payment(client, stripe, db):
    org_id = await activate_pro(client)
    partial = await deliver(event("evt_refund_1", "charge.refunded", {"id": "ch_1", "invoice": "in_1", "amount_refunded": 5000}))
    assert partial.json() == {"status": "processed"}
    payment = (await client.get("/api/v1/billing/payments")).json()["items"][0]
    assert (payment["status"], payment["refunded_minor"]) == ("partially_refunded", 5000)
    await deliver(event("evt_refund_2", "charge.refunded", {"id": "ch_1", "invoice": "in_1", "amount_refunded": 19000}))
    assert (await client.get("/api/v1/billing/payments")).json()["items"][0]["status"] == "refunded"
    assert (await deliver(event("evt_refund_x", "charge.refunded", {"id": "ch_unknown", "amount_refunded": 1}))).json() == {"status": "unknown_payment"}
    row = await db.scalar(select(Payment))
    assert row.organisation_id == org_id and "payment.refunded" in set((await db.scalars(select(AuditLog.action))).all())


async def test_billing_data_is_isolated_between_organisations(client, other_client, stripe):
    await activate_pro(client)
    theirs = (await other_client.get("/api/v1/billing/subscription")).json()
    assert theirs["plan"]["key"] == "free" and theirs["status"] == "active"
    assert (await other_client.get("/api/v1/billing/payments")).json() == {"items": []}
    assert (await other_client.post("/api/v1/billing/cancel")).status_code == 400
    assert (await other_client.post("/api/v1/api-keys", json={"name": "x"})).status_code == 402


async def test_unknown_or_live_events_are_acknowledged_without_effect(client, stripe, db):
    unknown_org = await deliver(event("evt_unknown", "customer.subscription.created", subscription_obj(999_999, sub_id="sub_x") | {"customer": "cus_x"}))
    assert unknown_org.status_code == 200 and unknown_org.json() == {"status": "unknown_organisation"}
    assert (await deliver(event("evt_other", "customer.created", {"id": "cus_9"}))).json() == {"status": "ignored"}
    live = event("evt_live", "customer.subscription.created", subscription_obj(client.me["organisation"]["id"])) | {"livemode": True}
    assert (await deliver(live)).json()["status"] == "ignored"  # live-mode events are never applied
    assert (await client.get("/api/v1/billing/subscription")).json()["plan"]["key"] == "free"


async def test_webhook_and_portal_report_missing_configuration(client, settings, monkeypatch):
    monkeypatch.setattr(settings, "allow_self_serve_plan_change", False)
    payload, headers = signed(event("evt_1", "invoice.paid", {}))
    async with make_client() as provider:
        resp = await provider.post("/api/v1/billing/webhooks/stripe", content=payload, headers=headers)
    assert resp.status_code == 503 and resp.json()["error"]["code"] == "billing_not_configured"
    assert (await client.post("/api/v1/billing/portal")).json()["error"]["code"] == "billing_not_configured"
    integrations = {i["key"]: i for i in (await client.get("/api/v1/settings/organisation")).json()["integrations"]}
    assert integrations["billing"]["configured"] is False and integrations["email"]["configured"] is False


def test_signature_verification_unit():
    payload = b'{"id":"evt_1"}'
    ts = 1_800_000_000
    good = hmac.new(b"whsec_x", f"{ts}.".encode() + payload, hashlib.sha256).hexdigest()
    assert billing.verify_stripe_signature(payload, f"t={ts},v1=deadbeef,v1={good}", "whsec_x", now=ts + 10) == {"id": "evt_1"}  # any valid v1 (key rotation)
    for header in (None, "", "v1=" + good, f"t={ts}", f"t=abc,v1={good}", f"t={ts},v0={good}"):
        with pytest.raises(billing.BillingError):
            billing.verify_stripe_signature(payload, header, "whsec_x", now=ts)
    with pytest.raises(billing.BillingError):
        billing.verify_stripe_signature(payload, f"t={ts},v1={good}", "whsec_x", now=ts + 301)


def test_stripe_form_encoding():
    assert billing._flatten({"a": {"b": 1}, "c": [{"d": True}], "e": None, "f": "x"}) == {"a[b]": "1", "c[0][d]": "true", "f": "x"}
