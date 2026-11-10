"""Plans, subscription management, hosted checkout, payment history and provider webhooks."""

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_db
from app.deps import Principal, client_ip, get_session_principal, require_owner
from app.models import Competitor, Organisation, Payment, User, WatchlistItem, utcnow
from app.plans import PLAN_ORDER, all_plans, get_plan
from app.schemas import CheckoutIn
from app.services import billing
from app.services.usage import audit, get_subscription, get_usage, org_plan

router = APIRouter(prefix="/billing", tags=["billing"])


def _billing_state() -> dict:
    settings = get_settings()
    configured = settings.stripe_configured
    return {
        "provider": settings.billing_provider,
        "checkout_available": configured,
        "webhooks_configured": configured and bool(settings.stripe_webhook_secret),
        "test_mode": settings.stripe_test_mode if configured else None,
        "payments_live": bool(configured and settings.allow_live_payments and not settings.stripe_test_mode),
        "self_serve_plan_change": settings.allow_self_serve_plan_change,
        "currency": settings.billing_currency.upper(),
        "grace_days": settings.billing_grace_days,
        "message": ("Card checkout runs in Stripe test mode: no real money is taken." if configured and settings.stripe_test_mode
                    else "Card payments are not configured on this instance yet, so plans cannot be purchased online." if not configured
                    else "Card payments are enabled."),
    }


def _raise(exc: billing.BillingError):
    raise HTTPException(status_code=exc.status, detail={"code": exc.code, "message": str(exc)}) from exc


@router.get("/plans", summary="Plans, prices and entitlements (public)")
async def plans() -> dict:
    catalogue = all_plans()
    return {"plans": [catalogue[k].to_dict() for k in PLAN_ORDER], "intervals": ["month", "year"], "billing": _billing_state(),
            "note": "Prices are initial and may change. Annual billing is charged once per year."}


@router.get("/subscription", summary="Current subscription, entitlements in force and usage against limits")
async def subscription(principal: Principal = Depends(get_session_principal), db: AsyncSession = Depends(get_db)) -> dict:
    sub = await get_subscription(db, principal.organisation_id)
    plan = await org_plan(db, principal.organisation_id)
    await db.commit()

    async def count(model, *cond) -> int:
        return int(await db.scalar(select(func.count()).select_from(model).where(*cond)) or 0)

    org = principal.organisation_id
    return {
        "plan": plan.to_dict(),  # the plan whose limits apply right now
        "subscribed_plan": get_plan(sub.plan).to_dict(),
        "status": sub.status, "billing_interval": sub.billing_interval, "provider": sub.provider,
        "current_period_start": sub.current_period_start, "current_period_end": sub.current_period_end,
        "cancel_at_period_end": sub.cancel_at_period_end, "cancelled_at": sub.cancelled_at, "grace_until": sub.grace_until,
        "manageable": sub.provider == "stripe" and bool(sub.provider_subscription_id),
        "usage": [
            {"key": "reports", "label": "AI reports this month", "used": await get_usage(db, org, "reports"), "limit": plan.reports_per_month},
            {"key": "api_requests", "label": "API calls this month", "used": await get_usage(db, org, "api_requests"), "limit": plan.api_requests_per_month},
            {"key": "live_syncs", "label": "Live GitHub requests this month", "used": await get_usage(db, org, "live_syncs"), "limit": plan.live_syncs_per_month},
            {"key": "watchlist_items", "label": "Watched items", "used": await count(WatchlistItem, WatchlistItem.organisation_id == org), "limit": plan.watchlist_items},
            {"key": "competitors", "label": "Competitors monitored", "used": await count(Competitor, Competitor.organisation_id == org), "limit": plan.competitors},
        ],
        "billing": _billing_state(),
    }


@router.post("/checkout", summary="Start hosted card checkout for a plan (owner only)")
async def checkout(body: CheckoutIn, request: Request, principal: Principal = Depends(require_owner), db: AsyncSession = Depends(get_db)) -> dict:
    settings = get_settings()
    sub = await get_subscription(db, principal.organisation_id)
    plan = get_plan(body.plan)
    if settings.stripe_configured:
        if sub.provider == "stripe" and sub.provider_subscription_id and sub.status in ("active", "cancelled", "past_due"):
            raise HTTPException(status_code=409, detail={"code": "already_subscribed", "message": "You already have a card subscription. Use Manage billing to change or cancel it."})
        org = await db.get(Organisation, principal.organisation_id)
        user = await db.get(User, principal.user.id)
        base = settings.frontend_url.rstrip("/")
        try:
            session = await billing.StripeProvider().create_checkout(org, user, sub, plan, body.interval, f"{base}/settings?tab=billing&checkout=success", f"{base}/settings?tab=billing&checkout=cancelled")
        except billing.BillingError as exc:
            _raise(exc)
        if sub.status in ("expired", "pending") or sub.plan == "free":
            sub.pending_plan = plan.key
        await audit(db, "billing.checkout_started", organisation_id=principal.organisation_id, user_id=principal.user_id, details={"plan": plan.key, "interval": body.interval}, ip=client_ip(request))
        await db.commit()
        return {"status": "redirect", "checkout_url": session.url, "test_mode": settings.stripe_test_mode}
    if settings.allow_self_serve_plan_change:  # development/test only; refused in production by configuration
        await billing.activate(db, sub, plan=plan.key, interval=body.interval, provider="manual", customer_id=None, subscription_id=None, period_start=utcnow(), period_end=None)
        await db.commit()
        return {"status": "changed", "plan": plan.to_dict(), "note": "Development mode: plan switched without payment."}
    raise HTTPException(status_code=503, detail={"code": "billing_not_configured", "message": "Card payments are not configured on this instance yet. No charge was made."})


async def _set_cancel(db: AsyncSession, principal: Principal, cancel: bool, request: Request) -> dict:
    sub = await get_subscription(db, principal.organisation_id)
    if sub.provider == "stripe" and sub.provider_subscription_id:
        try:
            result = await billing.StripeProvider().set_cancel_at_period_end(sub, cancel)
        except billing.BillingError as exc:
            _raise(exc)
        start, end = billing._period(result)
        sub.current_period_end = end or sub.current_period_end
        sub.current_period_start = start or sub.current_period_start
    elif sub.provider == "manual" and sub.plan != "free" and get_settings().allow_self_serve_plan_change:
        if cancel:
            await billing.end_subscription(db, sub, "cancelled in development mode")
            await db.commit()
            return {"status": sub.status, "plan": sub.plan}
    else:
        raise HTTPException(status_code=400, detail={"code": "no_subscription", "message": "There is no paid subscription to change."})
    sub.cancel_at_period_end = cancel
    sub.status = "cancelled" if cancel else "active"
    sub.cancelled_at = utcnow() if cancel else None
    await audit(db, "subscription.cancel_scheduled" if cancel else "subscription.resumed", organisation_id=principal.organisation_id, user_id=principal.user_id, ip=client_ip(request))
    await db.commit()
    return {"status": sub.status, "cancel_at_period_end": sub.cancel_at_period_end, "access_until": sub.current_period_end}


@router.post("/cancel", summary="Cancel at the end of the paid period (access continues until then)")
async def cancel(request: Request, principal: Principal = Depends(require_owner), db: AsyncSession = Depends(get_db)) -> dict:
    return await _set_cancel(db, principal, True, request)


@router.post("/resume", summary="Undo a scheduled cancellation")
async def resume(request: Request, principal: Principal = Depends(require_owner), db: AsyncSession = Depends(get_db)) -> dict:
    return await _set_cancel(db, principal, False, request)


@router.post("/portal", summary="Open the provider's billing portal (update card, invoices)")
async def portal(principal: Principal = Depends(require_owner), db: AsyncSession = Depends(get_db)) -> dict:
    sub = await get_subscription(db, principal.organisation_id)
    try:
        url = await billing.StripeProvider().portal_url(sub, f"{get_settings().frontend_url.rstrip('/')}/settings?tab=billing")
    except billing.BillingError as exc:
        _raise(exc)
    return {"url": url}


@router.get("/payments", summary="Payment history for your organisation")
async def payments(principal: Principal = Depends(get_session_principal), db: AsyncSession = Depends(get_db)) -> dict:
    rows = (await db.scalars(select(Payment).where(Payment.organisation_id == principal.organisation_id).order_by(Payment.created_at.desc()).limit(100))).all()
    return {"items": [{"id": p.id, "amount_minor": p.amount_minor, "refunded_minor": p.refunded_minor, "currency": p.currency.upper(), "status": p.status, "plan": p.plan,
                       "billing_interval": p.billing_interval, "description": p.description, "receipt_url": p.receipt_url, "paid_at": p.paid_at, "created_at": p.created_at} for p in rows]}


@router.post("/webhooks/stripe", include_in_schema=False)
async def stripe_webhook(request: Request, db: AsyncSession = Depends(get_db)) -> dict:
    """Signature-verified, idempotent. No session or CSRF: authenticity comes from the HMAC signature."""
    payload = await request.body()
    try:
        return await billing.process_stripe_webhook(db, payload, request.headers.get("stripe-signature"))
    except billing.BillingError as exc:
        _raise(exc)
