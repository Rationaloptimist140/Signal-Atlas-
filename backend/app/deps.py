"""Authentication, authorisation, CSRF and rate-limit dependencies."""

from dataclasses import dataclass

from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import ratelimit
from app.config import get_settings
from app.database import get_db
from app.models import ROLE_RANK, ApiKey, Membership, Role, User, UserSession, utcnow
from app.security import constant_time_equals, hash_token
from app.services.usage import org_plan, record_usage, upgrade_required

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


@dataclass
class Principal:
    organisation_id: int
    role: str
    via: str  # "session" | "api_key"
    user: User | None = None
    session: UserSession | None = None
    api_key: ApiKey | None = None

    @property
    def user_id(self) -> int | None:
        return self.user.id if self.user else (self.api_key.created_by if self.api_key else None)


def client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()[:64]
    return (request.client.host if request.client else "unknown")[:64]


def _extract_api_key(request: Request) -> str | None:
    key = request.headers.get("x-api-key")
    if key:
        return key.strip()
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return None


async def _too_many(retry_after: int) -> HTTPException:
    return HTTPException(status_code=429, detail={"code": "rate_limited", "message": "Too many requests. Slow down and retry shortly."},
                         headers={"Retry-After": str(retry_after)})


async def _principal_from_api_key(request: Request, db: AsyncSession, raw_key: str) -> Principal:
    key = await db.scalar(select(ApiKey).where(ApiKey.key_hash == hash_token(raw_key)))
    if key is None or key.revoked_at is not None:
        raise HTTPException(status_code=401, detail={"code": "invalid_api_key", "message": "API key is invalid or revoked."})
    plan = await org_plan(db, key.organisation_id)
    if plan.api_requests_per_month == 0:
        raise upgrade_required(plan, "api_access", "API access is not included in your current plan.")
    if request.method not in SAFE_METHODS and "write" not in key.scopes.split():
        raise HTTPException(status_code=403, detail={"code": "read_only_key", "message": "This API key is read-only."})
    allowed, retry = await ratelimit.hit(f"key:{key.id}", plan.api_rate_per_minute)
    if not allowed:
        raise await _too_many(retry)
    used = await record_usage(db, key.organisation_id, "api_requests")
    if plan.api_requests_per_month is not None and used > plan.api_requests_per_month:
        await db.commit()
        raise upgrade_required(plan, "api_requests", f"Monthly API quota of {plan.api_requests_per_month:,} requests reached.", plan.api_requests_per_month, used)
    key.last_used_at = utcnow()
    await db.commit()
    return Principal(organisation_id=key.organisation_id, role=Role.ANALYST.value, via="api_key", api_key=key)


async def _principal_from_session(request: Request, db: AsyncSession, token: str) -> Principal:
    settings = get_settings()
    session = await db.scalar(select(UserSession).where(UserSession.token_hash == hash_token(token)))
    now = utcnow()
    if session is None or session.revoked_at is not None or session.expires_at <= now:
        raise HTTPException(status_code=401, detail={"code": "not_authenticated", "message": "Your session has expired. Please sign in again."})
    user = await db.get(User, session.user_id)
    if user is None or not user.is_active:
        raise HTTPException(status_code=401, detail={"code": "not_authenticated", "message": "Account is disabled."})
    membership = await db.scalar(select(Membership).where(Membership.user_id == user.id, Membership.organisation_id == session.organisation_id))
    if membership is None:
        raise HTTPException(status_code=403, detail={"code": "no_membership", "message": "You no longer belong to this organisation."})
    if request.method not in SAFE_METHODS:
        header = request.headers.get("x-csrf-token", "")
        if not header or not constant_time_equals(header, session.csrf_token):
            raise HTTPException(status_code=403, detail={"code": "csrf_failed", "message": "Missing or invalid CSRF token."})
    allowed, retry = await ratelimit.hit(f"session:{session.id}", settings.rate_limit_per_minute)
    if not allowed:
        raise await _too_many(retry)
    return Principal(organisation_id=session.organisation_id, role=membership.role, via="session", user=user, session=session)


async def get_principal(request: Request, db: AsyncSession = Depends(get_db)) -> Principal:
    """Resolve the caller from an API key (header) or a session cookie. API keys win when both are sent."""
    raw_key = _extract_api_key(request)
    if raw_key:
        return await _principal_from_api_key(request, db, raw_key)
    token = request.cookies.get(get_settings().session_cookie_name)
    if token:
        return await _principal_from_session(request, db, token)
    raise HTTPException(status_code=401, detail={"code": "not_authenticated", "message": "Authentication required."})


async def get_session_principal(principal: Principal = Depends(get_principal)) -> Principal:
    """Account-management endpoints are never reachable with an API key."""
    if principal.via != "session":
        raise HTTPException(status_code=403, detail={"code": "session_required", "message": "This endpoint requires an interactive session."})
    return principal


def require_role(minimum: Role, *, session_only: bool = False):
    async def dependency(principal: Principal = Depends(get_session_principal if session_only else get_principal)) -> Principal:
        if ROLE_RANK[Role(principal.role)] < ROLE_RANK[minimum]:
            raise HTTPException(status_code=403, detail={"code": "insufficient_role", "message": f"Requires the {minimum.value} role or higher."})
        return principal
    return dependency


require_analyst = require_role(Role.ANALYST)
require_admin = require_role(Role.ADMIN, session_only=True)
require_owner = require_role(Role.OWNER, session_only=True)


async def require_platform_admin(principal: Principal = Depends(require_admin)) -> Principal:
    """Instance-wide tools (demo fixtures, discovery, recompute) affect data shared by all tenants.

    In production only e-mails listed in PLATFORM_ADMIN_EMAILS may use them; in development any workspace admin can.
    """
    settings = get_settings()
    if settings.app_env == "production" and (principal.user is None or principal.user.email.lower() not in settings.platform_admins):
        raise HTTPException(status_code=403, detail={"code": "platform_admin_required", "message": "This action is restricted to platform administrators."})
    return principal
