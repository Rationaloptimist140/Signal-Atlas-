"""Workspace administration: API keys, billing/plans, usage, scoring weights, members, system tools."""

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_db
from app.deps import (
    Principal,
    client_ip,
    get_session_principal,
    require_admin,
    require_owner,
    require_platform_admin,
)
from app.models import (
    ApiKey,
    AuditLog,
    DataSource,
    Job,
    Membership,
    Organisation,
    Repository,
    ScoringConfig,
    User,
    utcnow,
)
from app.plans import PLAN_ORDER, PLANS
from app.schemas import ApiKeyIn, OrganisationUpdateIn, PlanChangeIn, WeightsIn
from app.security import generate_api_key
from app.services import demo, jobs
from app.services.intelligence import get_weights
from app.services.scoring import DEFAULT_WEIGHTS, METRIC_LABELS, validate_weights
from app.services.usage import (
    audit,
    enforce_count_limit,
    get_subscription,
    get_usage,
    org_plan,
    upgrade_required,
)

router = APIRouter(tags=["account"])


# ----------------------------------------------------------------------------- API keys


@router.get("/api-keys", summary="List API keys (secrets are never returned)")
async def list_api_keys(principal: Principal = Depends(get_session_principal), db: AsyncSession = Depends(get_db)) -> dict:
    keys = (await db.scalars(select(ApiKey).where(ApiKey.organisation_id == principal.organisation_id).order_by(ApiKey.created_at.desc()))).all()
    plan = await org_plan(db, principal.organisation_id)
    return {
        "items": [{"id": k.id, "name": k.name, "prefix": k.prefix, "scopes": k.scopes, "created_at": k.created_at, "last_used_at": k.last_used_at, "revoked": k.revoked_at is not None} for k in keys],
        "limit": plan.api_keys, "api_access": (plan.api_requests_per_month or 0) > 0 or plan.api_requests_per_month is None,
        "requests_this_month": await get_usage(db, principal.organisation_id, "api_requests"), "requests_limit": plan.api_requests_per_month,
        "rate_per_minute": plan.api_rate_per_minute,
    }


@router.post("/api-keys", status_code=201, summary="Create an API key (shown once)")
async def create_api_key(body: ApiKeyIn, request: Request, principal: Principal = Depends(require_admin), db: AsyncSession = Depends(get_db)) -> dict:
    plan = await org_plan(db, principal.organisation_id)
    if plan.api_keys == 0:
        raise upgrade_required(plan, "api_access", "API access starts on the Pro plan.")
    active = int(await db.scalar(select(func.count()).select_from(ApiKey).where(ApiKey.organisation_id == principal.organisation_id, ApiKey.revoked_at.is_(None))) or 0)
    enforce_count_limit(plan, "api_keys", active, "active API keys")
    full, prefix, key_hash = generate_api_key()
    key = ApiKey(organisation_id=principal.organisation_id, created_by=principal.user_id, name=body.name.strip(), prefix=prefix, key_hash=key_hash, scopes=body.scopes)
    db.add(key)
    await db.flush()
    await audit(db, "api_key.created", organisation_id=principal.organisation_id, user_id=principal.user_id, target_type="api_key", target_id=key.id, ip=client_ip(request))
    await db.commit()
    return {"id": key.id, "name": key.name, "prefix": prefix, "scopes": key.scopes, "key": full,
            "warning": "Copy this key now. It is stored only as a hash and cannot be shown again."}


@router.delete("/api-keys/{key_id}", status_code=204, summary="Revoke an API key")
async def revoke_api_key(key_id: int, request: Request, principal: Principal = Depends(require_admin), db: AsyncSession = Depends(get_db)) -> None:
    key = await db.scalar(select(ApiKey).where(ApiKey.id == key_id, ApiKey.organisation_id == principal.organisation_id))
    if key is None:
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": "API key not found."})
    key.revoked_at = key.revoked_at or utcnow()
    await audit(db, "api_key.revoked", organisation_id=principal.organisation_id, user_id=principal.user_id, target_type="api_key", target_id=key.id, ip=client_ip(request))
    await db.commit()


# ----------------------------------------------------------------------------- billing


@router.get("/billing/plans", summary="Plans and entitlements (proposed pricing, payments not live)")
async def plans() -> dict:
    return {"plans": [PLANS[k].to_dict() for k in PLAN_ORDER], "currency": "GBP",
            "payments_live": False, "note": "Pricing is a proposal under validation. No payment provider is activated."}


@router.get("/billing/subscription", summary="Current subscription and usage against limits")
async def subscription(principal: Principal = Depends(get_session_principal), db: AsyncSession = Depends(get_db)) -> dict:
    from app.models import Competitor, WatchlistItem

    sub = await get_subscription(db, principal.organisation_id)
    plan = await org_plan(db, principal.organisation_id)
    await db.commit()
    settings = get_settings()

    async def count(model, *cond) -> int:
        return int(await db.scalar(select(func.count()).select_from(model).where(*cond)) or 0)

    return {
        "plan": plan.to_dict(), "status": sub.status, "provider": sub.provider, "current_period_end": sub.current_period_end,
        "usage": [
            {"key": "reports", "label": "Reports this month", "used": await get_usage(db, principal.organisation_id, "reports"), "limit": plan.reports_per_month},
            {"key": "live_syncs", "label": "Live GitHub requests this month", "used": await get_usage(db, principal.organisation_id, "live_syncs"), "limit": plan.live_syncs_per_month},
            {"key": "api_requests", "label": "API requests this month", "used": await get_usage(db, principal.organisation_id, "api_requests"), "limit": plan.api_requests_per_month},
            {"key": "watchlist_items", "label": "Saved items", "used": await count(WatchlistItem, WatchlistItem.organisation_id == principal.organisation_id), "limit": plan.watchlist_items},
            {"key": "competitors", "label": "Competitors", "used": await count(Competitor, Competitor.organisation_id == principal.organisation_id), "limit": plan.competitors},
        ],
        "billing": {"payments_live": False, "provider": settings.billing_provider, "self_serve_plan_change": settings.allow_self_serve_plan_change,
                    "message": "Live payments are not activated. Plan changes are applied manually while pricing is validated."},
    }


@router.post("/billing/checkout", summary="Start a plan change (payments are not live)")
async def checkout(body: PlanChangeIn, request: Request, principal: Principal = Depends(require_owner), db: AsyncSession = Depends(get_db)) -> dict:
    settings = get_settings()
    if not settings.allow_self_serve_plan_change:
        raise HTTPException(status_code=501, detail={
            "code": "billing_not_configured",
            "message": "Online checkout is not activated yet. Pricing is being validated; contact the Signal Atlas team to change plan."})
    sub = await get_subscription(db, principal.organisation_id)
    previous, sub.plan, sub.status, sub.provider = sub.plan, body.plan, "active", "manual"
    await audit(db, "subscription.changed", organisation_id=principal.organisation_id, user_id=principal.user_id, details={"from": previous, "to": body.plan, "mode": "development"}, ip=client_ip(request))
    await db.commit()
    return {"status": "changed", "plan": PLANS[body.plan].to_dict(), "note": "Development mode: plan switched without payment."}


# ----------------------------------------------------------------------------- settings


@router.get("/settings/scoring", summary="Scoring weights for your organisation")
async def get_scoring(principal: Principal = Depends(get_session_principal), db: AsyncSession = Depends(get_db)) -> dict:
    weights = await get_weights(db, principal.organisation_id)
    plan = await org_plan(db, principal.organisation_id)
    return {"weights": weights, "defaults": DEFAULT_WEIGHTS, "labels": METRIC_LABELS, "custom": weights != DEFAULT_WEIGHTS, "editable": plan.custom_scoring_weights}


@router.put("/settings/scoring", summary="Set custom scoring weights (must sum to 100)")
async def put_scoring(body: WeightsIn, principal: Principal = Depends(require_admin), db: AsyncSession = Depends(get_db)) -> dict:
    plan = await org_plan(db, principal.organisation_id)
    if not plan.custom_scoring_weights:
        raise upgrade_required(plan, "custom_scoring_weights", "Custom scoring weights are available on the Professional plan and above.")
    try:
        weights = validate_weights(body.weights)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail={"code": "invalid_weights", "message": str(exc)}) from exc
    config = await db.scalar(select(ScoringConfig).where(ScoringConfig.organisation_id == principal.organisation_id))
    if config is None:
        config = ScoringConfig(organisation_id=principal.organisation_id, weights=weights)
        db.add(config)
    config.weights = weights
    await audit(db, "scoring.weights_changed", organisation_id=principal.organisation_id, user_id=principal.user_id, details={"weights": weights})
    await db.commit()
    return {"weights": weights, "custom": weights != DEFAULT_WEIGHTS}


@router.delete("/settings/scoring", status_code=204, summary="Reset scoring weights to defaults")
async def reset_scoring(principal: Principal = Depends(require_admin), db: AsyncSession = Depends(get_db)) -> None:
    config = await db.scalar(select(ScoringConfig).where(ScoringConfig.organisation_id == principal.organisation_id))
    if config:
        await db.delete(config)
        await db.commit()


@router.get("/settings/organisation", summary="Workspace, members and integration status")
async def organisation(principal: Principal = Depends(get_session_principal), db: AsyncSession = Depends(get_db)) -> dict:
    org = await db.get(Organisation, principal.organisation_id)
    members = (await db.execute(select(User.id, User.email, User.full_name, Membership.role).join(Membership, Membership.user_id == User.id)
                                .where(Membership.organisation_id == principal.organisation_id).order_by(Membership.id))).all()
    settings = get_settings()
    return {
        "organisation": {"id": org.id, "name": org.name, "slug": org.slug, "created_at": org.created_at},
        "members": [{"id": i, "email": e, "full_name": n, "role": r} for i, e, n, r in members],
        "integrations": [
            {"key": "github_token", "name": "GitHub server token", "configured": bool(settings.github_token),
             "detail": "Raises the GitHub API limit from 60 to 5,000 requests/hour and enables issue/PR totals. A token with no scopes is sufficient (public data only).", "env": ["GITHUB_TOKEN"]},
            {"key": "github_oauth", "name": "GitHub OAuth (sign in / connect account)", "configured": settings.github_oauth_configured,
             "detail": f"Requests identity scopes only ({settings.github_oauth_scopes}); never repository write access.", "env": ["GITHUB_OAUTH_CLIENT_ID", "GITHUB_OAUTH_CLIENT_SECRET"]},
            {"key": "llm", "name": "AI enrichment provider", "configured": settings.llm_configured,
             "detail": f"Provider: {settings.llm_provider}. Reports use the deterministic rules engine when no provider is configured.", "env": ["LLM_PROVIDER", "ANTHROPIC_API_KEY or OPENAI_API_KEY"]},
            {"key": "redis", "name": "Redis (shared rate limiting)", "configured": bool(settings.redis_url),
             "detail": "Optional. Only needed when running more than one API instance.", "env": ["REDIS_URL"]},
            {"key": "billing", "name": "Payment provider", "configured": False, "detail": "Intentionally not activated until pricing is validated.", "env": []},
        ],
    }


@router.patch("/settings/organisation", summary="Rename the workspace")
async def update_organisation(body: OrganisationUpdateIn, principal: Principal = Depends(require_admin), db: AsyncSession = Depends(get_db)) -> dict:
    org = await db.get(Organisation, principal.organisation_id)
    org.name = body.name.strip()
    await db.commit()
    return {"id": org.id, "name": org.name}


@router.get("/settings/audit-log", summary="Recent security-relevant events in your workspace")
async def audit_log(principal: Principal = Depends(require_admin), db: AsyncSession = Depends(get_db)) -> dict:
    rows = (await db.scalars(select(AuditLog).where(AuditLog.organisation_id == principal.organisation_id).order_by(AuditLog.created_at.desc()).limit(100))).all()
    return {"items": [{"id": a.id, "action": a.action, "user_id": a.user_id, "target_type": a.target_type, "target_id": a.target_id, "details": a.details, "created_at": a.created_at} for a in rows]}


# ----------------------------------------------------------------------------- system tools


@router.get("/system/status", summary="Data and job status for this instance")
async def system_status(principal: Principal = Depends(require_platform_admin), db: AsyncSession = Depends(get_db)) -> dict:
    job_counts = dict((await db.execute(select(Job.status, func.count()).group_by(Job.status))).all())
    live = int(await db.scalar(select(func.count()).select_from(Repository).where(Repository.data_source == DataSource.LIVE.value)) or 0)
    demo_count = int(await db.scalar(select(func.count()).select_from(Repository).where(Repository.data_source == DataSource.DEMO.value)) or 0)
    recent = (await db.scalars(select(Job).order_by(Job.id.desc()).limit(15))).all()
    return {"jobs": {s: job_counts.get(s, 0) for s in ("queued", "running", "succeeded", "failed")}, "live_repositories": live, "demo_repositories": demo_count,
            "jobs_inline": get_settings().jobs_inline,
            "recent_jobs": [{"id": j.id, "job_type": j.job_type, "status": j.status, "attempts": j.attempts, "run_after": j.run_after, "finished_at": j.finished_at, "last_error": j.last_error} for j in recent]}


@router.post("/system/demo/load", summary="Load fictional demonstration fixtures")
async def load_demo(principal: Principal = Depends(require_platform_admin), db: AsyncSession = Depends(get_db)) -> dict:
    summary = await demo.load_demo(db)
    await audit(db, "system.demo_loaded", organisation_id=principal.organisation_id, user_id=principal.user_id, details=summary)
    await db.commit()
    return dict(summary, data_source=DataSource.DEMO.value)


@router.delete("/system/demo", summary="Remove all demonstration fixtures")
async def clear_demo(principal: Principal = Depends(require_platform_admin), db: AsyncSession = Depends(get_db)) -> dict:
    removed = await demo.clear_demo(db)
    await audit(db, "system.demo_cleared", organisation_id=principal.organisation_id, user_id=principal.user_id, details={"repositories": removed})
    await db.commit()
    return {"removed_repositories": removed}


@router.post("/system/discover", status_code=202, summary="Queue the curated live GitHub discovery run")
async def discover(principal: Principal = Depends(require_platform_admin), db: AsyncSession = Depends(get_db)) -> dict:
    job = await jobs.enqueue_and_maybe_run(db, "discover_all", {"user_id": principal.user_id}, dedupe_key="recurring:discover_all")
    return {"job_id": job.id, "status": job.status, "message": "Discovery queued. A running worker is required (python -m app.worker)." if job.status == "queued" else "Discovery started."}


@router.post("/system/recompute", status_code=202, summary="Recompute scores, opportunities and trend signals")
async def recompute(principal: Principal = Depends(require_platform_admin), db: AsyncSession = Depends(get_db)) -> dict:
    job = await jobs.enqueue_and_maybe_run(db, "recompute_intelligence", {}, dedupe_key="recompute")
    return {"job_id": job.id, "status": job.status}
