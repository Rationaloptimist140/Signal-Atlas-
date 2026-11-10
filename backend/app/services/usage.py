"""Subscription entitlements, usage metering and audit logging."""

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuditLog, Subscription, UsageRecord, utcnow
from app.plans import Plan, get_plan, next_plan


def current_period() -> str:
    now = utcnow()
    return f"{now.year}-{now.month:02d}"


async def get_subscription(session: AsyncSession, organisation_id: int) -> Subscription:
    sub = await session.scalar(select(Subscription).where(Subscription.organisation_id == organisation_id))
    if sub is None:
        sub = Subscription(organisation_id=organisation_id, plan="free", status="active", provider="manual")
        session.add(sub)
        await session.flush()
    return sub


async def org_plan(session: AsyncSession, organisation_id: int) -> Plan:
    sub = await get_subscription(session, organisation_id)
    return get_plan(sub.plan if sub.status in ("active", "trialing") else "free")


async def get_usage(session: AsyncSession, organisation_id: int, metric: str) -> int:
    row = await session.scalar(select(UsageRecord).where(
        UsageRecord.organisation_id == organisation_id, UsageRecord.metric == metric, UsageRecord.period == current_period()))
    return row.quantity if row else 0


async def record_usage(session: AsyncSession, organisation_id: int, metric: str, quantity: int = 1) -> int:
    period = current_period()
    row = await session.scalar(select(UsageRecord).where(
        UsageRecord.organisation_id == organisation_id, UsageRecord.metric == metric, UsageRecord.period == period))
    if row is None:
        row = UsageRecord(organisation_id=organisation_id, metric=metric, period=period, quantity=0)
        session.add(row)
    row.quantity += quantity
    row.updated_at = utcnow()
    await session.flush()
    return row.quantity


def upgrade_required(plan: Plan, feature: str, message: str, limit: int | None = None, used: int | None = None) -> HTTPException:
    """HTTP 402 with a machine-readable payload the UI turns into an upgrade prompt."""
    return HTTPException(status_code=402, detail={
        "code": "upgrade_required", "feature": feature, "message": message, "current_plan": plan.key,
        "suggested_plan": next_plan(plan.key), "limit": limit, "used": used,
    })


async def enforce_monthly_limit(session: AsyncSession, organisation_id: int, metric: str, plan_field: str, label: str) -> Plan:
    plan = await org_plan(session, organisation_id)
    limit = getattr(plan, plan_field)
    if limit is not None:
        used = await get_usage(session, organisation_id, metric)
        if used >= limit:
            raise upgrade_required(plan, metric, f"Your {plan.name} plan includes {limit} {label} per month and you have used {used}.", limit, used)
    return plan


def enforce_count_limit(plan: Plan, plan_field: str, current: int, label: str) -> None:
    limit = getattr(plan, plan_field)
    if limit is not None and current >= limit:
        raise upgrade_required(plan, plan_field, f"Your {plan.name} plan allows {limit} {label}.", limit, current)


async def audit(session: AsyncSession, action: str, *, organisation_id: int | None = None, user_id: int | None = None,
                target_type: str | None = None, target_id: str | int | None = None, details: dict | None = None, ip: str | None = None) -> None:
    session.add(AuditLog(organisation_id=organisation_id, user_id=user_id, action=action, target_type=target_type,
                         target_id=str(target_id) if target_id is not None else None, details=details or {}, ip_address=ip))
