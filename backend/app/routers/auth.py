"""Email/password authentication, sessions, profile and read-only GitHub OAuth."""

import datetime as dt
import re
import secrets
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app import ratelimit
from app.config import get_settings
from app.database import get_db
from app.deps import Principal, client_ip, get_session_principal
from app.logging_config import get_logger
from app.models import (
    GitHubAccount,
    Membership,
    Organisation,
    Role,
    Subscription,
    User,
    UserSession,
    Watchlist,
    utcnow,
)
from app.schemas import (
    ChangePasswordIn,
    LoginIn,
    PasswordResetConfirmIn,
    PasswordResetRequestIn,
    ProfileUpdateIn,
    RegisterIn,
    TokenIn,
)
from app.security import (
    decrypt_secret,
    encrypt_secret,
    hash_password,
    hash_token,
    needs_rehash,
    new_token,
    sign,
    unsign,
    verify_password,
)
from app.services import account_tokens
from app.services.usage import audit, org_plan

router = APIRouter(prefix="/auth", tags=["auth"])
log = get_logger("auth")

OAUTH_STATE_COOKIE = "sa_oauth_state"
MAX_FAILED_LOGINS = 5
LOCK_MINUTES = 15
_DUMMY_HASH = hash_password("timing-equaliser-not-a-real-password")


def _slugify(name: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:50] or "workspace"
    return f"{base}-{secrets.token_hex(3)}"


def _set_session_cookies(response: Response, token: str, csrf: str) -> None:
    settings = get_settings()
    max_age = settings.session_ttl_hours * 3600
    response.set_cookie(settings.session_cookie_name, token, max_age=max_age, httponly=True, secure=bool(settings.cookie_secure), samesite="lax", path="/")
    # Readable by the frontend so it can echo it in X-CSRF-Token (double-submit, verified against the session row).
    response.set_cookie(settings.csrf_cookie_name, csrf, max_age=max_age, httponly=False, secure=bool(settings.cookie_secure), samesite="lax", path="/")


def _clear_session_cookies(response: Response) -> None:
    settings = get_settings()
    response.delete_cookie(settings.session_cookie_name, path="/")
    response.delete_cookie(settings.csrf_cookie_name, path="/")


async def create_session(db: AsyncSession, user: User, organisation_id: int, request: Request, response: Response) -> UserSession:
    token, csrf = new_token(32), new_token(24)
    session = UserSession(
        user_id=user.id, organisation_id=organisation_id, token_hash=hash_token(token), csrf_token=csrf, ip_address=client_ip(request),
        user_agent=(request.headers.get("user-agent") or "")[:400],
        expires_at=utcnow() + dt.timedelta(hours=get_settings().session_ttl_hours))
    db.add(session)
    user.last_login_at = utcnow()
    await db.flush()
    _set_session_cookies(response, token, csrf)
    return session


async def create_user_with_workspace(db: AsyncSession, email: str, full_name: str, password_hash: str | None, organisation_name: str | None) -> tuple[User, Organisation]:
    user = User(email=email.lower(), password_hash=password_hash, full_name=full_name)
    org_name = organisation_name or f"{full_name.split()[0] if full_name.strip() else 'My'}'s workspace"
    org = Organisation(name=org_name, slug=_slugify(org_name))
    db.add_all([user, org])
    await db.flush()
    db.add(Membership(user_id=user.id, organisation_id=org.id, role=Role.OWNER.value))
    db.add(Subscription(organisation_id=org.id, plan="free", status="active", provider="manual"))
    db.add(Watchlist(organisation_id=org.id, created_by=user.id, name="My watchlist", description="Saved repositories and opportunities"))
    await db.flush()
    return user, org


async def me_payload(db: AsyncSession, user: User, organisation_id: int, role: str, csrf: str) -> dict:
    org = await db.get(Organisation, organisation_id)
    plan = await org_plan(db, organisation_id)
    account = await db.scalar(select(GitHubAccount).where(GitHubAccount.user_id == user.id))
    return {
        "user": {"id": user.id, "email": user.email, "full_name": user.full_name, "job_title": user.job_title, "has_password": bool(user.password_hash),
                 "created_at": user.created_at.isoformat(), "email_verified": user.email_verified_at is not None},
        "email": {"verification_required": get_settings().email_verification_required, "delivery_configured": get_settings().email_delivery_configured},
        "organisation": {"id": org.id, "name": org.name, "slug": org.slug},
        "role": role,
        "plan": plan.to_dict(),
        "csrf_token": csrf,
        # The OAuth token itself is never serialised.
        "github": {"connected": account is not None, "login": account.login if account else None, "avatar_url": account.avatar_url if account else None,
                   "scopes": account.scopes if account else None, "oauth_configured": get_settings().github_oauth_configured},
    }


@router.get("/providers", summary="Which sign-in methods are available on this instance")
async def providers() -> dict:
    settings = get_settings()
    return {"email_password": True, "github_oauth": settings.github_oauth_configured, "registration_open": settings.allow_registration,
            "email_delivery": settings.email_delivery_configured,
            "github_scopes": settings.github_oauth_scopes if settings.github_oauth_configured else None}


@router.post("/register", status_code=201, summary="Create an account and workspace")
async def register(body: RegisterIn, request: Request, response: Response, db: AsyncSession = Depends(get_db)) -> dict:
    settings = get_settings()
    if not settings.allow_registration:
        raise HTTPException(status_code=403, detail={"code": "registration_closed", "message": "Registration is currently closed."})
    allowed, retry = await ratelimit.hit(f"register:{client_ip(request)}", 10, 3600)
    if not allowed:
        raise HTTPException(status_code=429, detail={"code": "rate_limited", "message": "Too many sign-up attempts. Try again later."}, headers={"Retry-After": str(retry)})
    email = body.email.lower()
    if await db.scalar(select(User.id).where(func.lower(User.email) == email)):
        raise HTTPException(status_code=409, detail={"code": "email_taken", "message": "An account with this email already exists."})
    user, org = await create_user_with_workspace(db, email, body.full_name.strip(), hash_password(body.password), body.organisation_name)
    session = await create_session(db, user, org.id, request, response)
    await audit(db, "user.registered", organisation_id=org.id, user_id=user.id, ip=client_ip(request))
    delivery = await account_tokens.send_verification(db, user, client_ip(request))
    await db.commit()
    return dict(await me_payload(db, user, org.id, Role.OWNER.value, session.csrf_token), verification_email=delivery)


@router.post("/login", summary="Sign in with email and password")
async def login(body: LoginIn, request: Request, response: Response, db: AsyncSession = Depends(get_db)) -> dict:
    ip = client_ip(request)
    allowed, retry = await ratelimit.hit(f"login:{ip}", 20, 60)
    if not allowed:
        raise HTTPException(status_code=429, detail={"code": "rate_limited", "message": "Too many sign-in attempts. Try again shortly."}, headers={"Retry-After": str(retry)})
    invalid = HTTPException(status_code=401, detail={"code": "invalid_credentials", "message": "Invalid email or password."})
    user = await db.scalar(select(User).where(func.lower(User.email) == body.email.lower()))
    if user is None:
        verify_password(body.password, _DUMMY_HASH)  # equalise timing so unknown emails are not detectable
        raise invalid
    now = utcnow()
    if user.locked_until and user.locked_until > now:
        raise HTTPException(status_code=423, detail={"code": "account_locked", "message": "Too many failed attempts. Try again in a few minutes."})
    if not user.is_active or not verify_password(body.password, user.password_hash):
        user.failed_logins += 1
        if user.failed_logins >= MAX_FAILED_LOGINS:
            user.locked_until = now + dt.timedelta(minutes=LOCK_MINUTES)
            user.failed_logins = 0
        await audit(db, "user.login_failed", user_id=user.id, ip=ip)
        await db.commit()
        raise invalid
    user.failed_logins, user.locked_until = 0, None
    if user.password_hash and needs_rehash(user.password_hash):
        user.password_hash = hash_password(body.password)
    membership = await db.scalar(select(Membership).where(Membership.user_id == user.id).order_by(Membership.id))
    if membership is None:
        raise HTTPException(status_code=403, detail={"code": "no_membership", "message": "This account has no workspace."})
    session = await create_session(db, user, membership.organisation_id, request, response)
    await audit(db, "user.login", organisation_id=membership.organisation_id, user_id=user.id, ip=ip)
    await db.commit()
    return await me_payload(db, user, membership.organisation_id, membership.role, session.csrf_token)


@router.post("/logout", status_code=204, summary="End the current session")
async def logout(response: Response, principal: Principal = Depends(get_session_principal), db: AsyncSession = Depends(get_db)) -> None:
    principal.session.revoked_at = utcnow()
    await db.merge(principal.session)
    await db.commit()
    _clear_session_cookies(response)


@router.get("/me", summary="Current user, workspace, plan and CSRF token")
async def me(principal: Principal = Depends(get_session_principal), db: AsyncSession = Depends(get_db)) -> dict:
    return await me_payload(db, principal.user, principal.organisation_id, principal.role, principal.session.csrf_token)


@router.patch("/me", summary="Update profile")
async def update_me(body: ProfileUpdateIn, principal: Principal = Depends(get_session_principal), db: AsyncSession = Depends(get_db)) -> dict:
    user = await db.get(User, principal.user.id)
    if body.full_name is not None:
        user.full_name = body.full_name.strip()
    if body.job_title is not None:
        user.job_title = body.job_title.strip() or None
    await db.commit()
    return await me_payload(db, user, principal.organisation_id, principal.role, principal.session.csrf_token)


@router.post("/change-password", status_code=204, summary="Change password and sign out other sessions")
async def change_password(body: ChangePasswordIn, request: Request, principal: Principal = Depends(get_session_principal), db: AsyncSession = Depends(get_db)) -> None:
    user = await db.get(User, principal.user.id)
    if user.password_hash and not verify_password(body.current_password, user.password_hash):
        raise HTTPException(status_code=400, detail={"code": "wrong_password", "message": "Current password is incorrect."})
    user.password_hash = hash_password(body.new_password)
    await db.execute(update(UserSession).where(UserSession.user_id == user.id, UserSession.id != principal.session.id, UserSession.revoked_at.is_(None)).values(revoked_at=utcnow()))
    await audit(db, "user.password_changed", organisation_id=principal.organisation_id, user_id=user.id, ip=client_ip(request))
    await db.commit()


@router.post("/logout-all", status_code=204, summary="Sign out every session, including this one")
async def logout_all(response: Response, principal: Principal = Depends(get_session_principal), db: AsyncSession = Depends(get_db)) -> None:
    await db.execute(update(UserSession).where(UserSession.user_id == principal.user.id, UserSession.revoked_at.is_(None)).values(revoked_at=utcnow()))
    await audit(db, "user.logout_all", organisation_id=principal.organisation_id, user_id=principal.user.id)
    await db.commit()
    _clear_session_cookies(response)


# ----------------------------------------------------------------------------- e-mail verification and password reset


@router.post("/verify-email/request", status_code=202, summary="Send (or resend) the verification e-mail")
async def request_verification(request: Request, principal: Principal = Depends(get_session_principal), db: AsyncSession = Depends(get_db)) -> dict:
    user = await db.get(User, principal.user.id)
    if user.email_verified_at is not None:
        return {"status": "already_verified"}
    allowed, retry = await ratelimit.hit(f"verify:{user.id}", 3, 3600)
    if not allowed:
        raise HTTPException(status_code=429, detail={"code": "rate_limited", "message": "Verification email already sent. Please wait before requesting another."}, headers={"Retry-After": str(retry)})
    delivery = await account_tokens.send_verification(db, user, client_ip(request))
    await audit(db, "user.verification_requested", organisation_id=principal.organisation_id, user_id=user.id, details={"delivery": delivery}, ip=client_ip(request))
    await db.commit()
    return {"status": delivery, "delivery_configured": get_settings().email_delivery_configured,
            "message": {"sent": "Verification email sent.", "logged_dev": "Development mode: the verification link was written to the API log.",
                        "captured": "Captured (test mode).", "failed": "The email provider rejected the message. Try again later.",
                        "not_configured": "Email delivery is not configured on this instance, so no message was sent."}[delivery]}


@router.post("/verify-email/confirm", summary="Confirm an e-mail address with a single-use token")
async def confirm_verification(body: TokenIn, request: Request, db: AsyncSession = Depends(get_db)) -> dict:
    allowed, retry = await ratelimit.hit(f"verify-confirm:{client_ip(request)}", 20, 600)
    if not allowed:
        raise HTTPException(status_code=429, detail={"code": "rate_limited", "message": "Too many attempts."}, headers={"Retry-After": str(retry)})
    user = await account_tokens.consume_token(db, body.token, account_tokens.VERIFY)
    if user is None:
        await db.commit()
        raise HTTPException(status_code=400, detail={"code": "invalid_token", "message": "This verification link is invalid, has expired or was already used."})
    user.email_verified_at = user.email_verified_at or utcnow()
    await audit(db, "user.email_verified", user_id=user.id, ip=client_ip(request))
    await db.commit()
    return {"status": "verified"}


RESET_RESPONSE = {"status": "accepted", "message": "If an account exists for that address, a password-reset link has been sent."}


@router.post("/password-reset/request", status_code=202, summary="Request a password-reset link (response never reveals whether the account exists)")
async def request_password_reset(body: PasswordResetRequestIn, request: Request, db: AsyncSession = Depends(get_db)) -> dict:
    ip, email = client_ip(request), body.email.lower()
    ip_ok, retry = await ratelimit.hit(f"reset-ip:{ip}", 5, 3600)
    if not ip_ok:
        raise HTTPException(status_code=429, detail={"code": "rate_limited", "message": "Too many reset requests. Try again later."}, headers={"Retry-After": str(retry)})
    email_ok, _ = await ratelimit.hit(f"reset-email:{email}", 3, 3600)
    user = await db.scalar(select(User).where(func.lower(User.email) == email))
    if email_ok and user is not None and user.is_active:
        delivery = await account_tokens.send_password_reset(db, user, ip)
        await audit(db, "user.password_reset_requested", user_id=user.id, details={"delivery": delivery}, ip=ip)
        await db.commit()
    return dict(RESET_RESPONSE, delivery_configured=get_settings().email_delivery_configured)


@router.post("/password-reset/confirm", summary="Set a new password with a single-use token; signs out every session")
async def confirm_password_reset(body: PasswordResetConfirmIn, request: Request, response: Response, db: AsyncSession = Depends(get_db)) -> dict:
    allowed, retry = await ratelimit.hit(f"reset-confirm:{client_ip(request)}", 10, 600)
    if not allowed:
        raise HTTPException(status_code=429, detail={"code": "rate_limited", "message": "Too many attempts."}, headers={"Retry-After": str(retry)})
    user = await account_tokens.consume_token(db, body.token, account_tokens.RESET)
    if user is None:
        await db.commit()
        raise HTTPException(status_code=400, detail={"code": "invalid_token", "message": "This reset link is invalid, has expired or was already used."})
    user.password_hash = hash_password(body.new_password)
    user.failed_logins, user.locked_until = 0, None
    user.email_verified_at = user.email_verified_at or utcnow()  # receiving the link proves control of the address
    await db.execute(update(UserSession).where(UserSession.user_id == user.id, UserSession.revoked_at.is_(None)).values(revoked_at=utcnow()))
    await audit(db, "user.password_reset", user_id=user.id, ip=client_ip(request))
    await db.commit()
    _clear_session_cookies(response)
    return {"status": "password_reset", "message": "Password updated. Sign in with your new password."}


# ----------------------------------------------------------------------------- GitHub OAuth (read-only)


def _oauth_not_configured() -> HTTPException:
    return HTTPException(status_code=503, detail={
        "code": "github_oauth_not_configured",
        "message": "GitHub OAuth is not configured. Set GITHUB_OAUTH_CLIENT_ID and GITHUB_OAUTH_CLIENT_SECRET (see DEPLOYMENT.md).",
    })


@router.get("/github/start", summary="Begin GitHub OAuth (identity scopes only; no repository write access)")
async def github_start(request: Request, mode: str = "connect") -> RedirectResponse:
    settings = get_settings()
    if not settings.github_oauth_configured:
        raise _oauth_not_configured()
    if mode not in ("connect", "login"):
        raise HTTPException(status_code=400, detail={"code": "bad_mode", "message": "mode must be connect or login"})
    state = new_token(24)
    params = {"client_id": settings.github_oauth_client_id, "redirect_uri": settings.oauth_redirect_url, "scope": settings.github_oauth_scopes,
              "state": state, "allow_signup": "true"}
    response = RedirectResponse(f"https://github.com/login/oauth/authorize?{urlencode(params)}", status_code=302)
    response.set_cookie(OAUTH_STATE_COOKIE, sign(f"{state}:{mode}"), max_age=600, httponly=True, secure=bool(settings.cookie_secure), samesite="lax", path="/")
    return response


async def _exchange_code(code: str) -> tuple[str, str]:
    settings = get_settings()
    async with httpx.AsyncClient(timeout=15.0) as http:
        resp = await http.post("https://github.com/login/oauth/access_token", headers={"Accept": "application/json"},
                               data={"client_id": settings.github_oauth_client_id, "client_secret": settings.github_oauth_client_secret,
                                     "code": code, "redirect_uri": settings.oauth_redirect_url})
    data = resp.json() if resp.status_code == 200 else {}
    token = data.get("access_token")
    if not token:
        raise HTTPException(status_code=400, detail={"code": "oauth_exchange_failed", "message": "GitHub did not return an access token."})
    return token, data.get("scope", "")


async def _github_identity(token: str) -> tuple[dict, str | None]:
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}
    async with httpx.AsyncClient(timeout=15.0, base_url=get_settings().github_api_url) as http:
        profile = (await http.get("/user", headers=headers)).json()
        email = None
        emails = await http.get("/user/emails", headers=headers)
        if emails.status_code == 200:
            for item in emails.json():
                if item.get("primary") and item.get("verified"):
                    email = item.get("email")
    return profile, email


def _frontend_redirect(path: str) -> RedirectResponse:
    response = RedirectResponse(f"{get_settings().frontend_url.rstrip('/')}{path}", status_code=302)
    response.delete_cookie(OAUTH_STATE_COOKIE, path="/")
    return response


@router.get("/github/callback", include_in_schema=False)
async def github_callback(request: Request, code: str | None = None, state: str | None = None, error: str | None = None,
                          db: AsyncSession = Depends(get_db)) -> RedirectResponse:
    settings = get_settings()
    if not settings.github_oauth_configured:
        raise _oauth_not_configured()
    stored = unsign(request.cookies.get(OAUTH_STATE_COOKIE, ""))
    if error or not code or not state or not stored:
        return _frontend_redirect("/login?error=github_cancelled")
    expected_state, _, mode = stored.partition(":")
    if not secrets.compare_digest(expected_state, state):
        return _frontend_redirect("/login?error=github_state_mismatch")
    token, scopes = await _exchange_code(code)
    profile, email = await _github_identity(token)
    github_id, login = profile.get("id"), profile.get("login")
    if not github_id or not login:
        return _frontend_redirect("/login?error=github_profile_unavailable")
    linked = await db.scalar(select(GitHubAccount).where(GitHubAccount.github_user_id == github_id))

    session_token = request.cookies.get(settings.session_cookie_name)
    current_session = None
    if session_token:
        current_session = await db.scalar(select(UserSession).where(UserSession.token_hash == hash_token(session_token), UserSession.revoked_at.is_(None), UserSession.expires_at > utcnow()))

    if mode == "connect":
        if current_session is None:
            return _frontend_redirect("/login?error=session_expired")
        if linked and linked.user_id != current_session.user_id:
            return _frontend_redirect("/settings?github=already_linked")
        account = linked or await db.scalar(select(GitHubAccount).where(GitHubAccount.user_id == current_session.user_id))
        if account is None:
            account = GitHubAccount(user_id=current_session.user_id, github_user_id=github_id, login=login, access_token_encrypted="")
            db.add(account)
        account.github_user_id, account.login, account.avatar_url = github_id, login, profile.get("avatar_url")
        account.access_token_encrypted, account.scopes, account.connected_at = encrypt_secret(token), scopes, utcnow()
        await audit(db, "github.connected", organisation_id=current_session.organisation_id, user_id=current_session.user_id, details={"login": login, "scopes": scopes}, ip=client_ip(request))
        await db.commit()
        return _frontend_redirect("/settings?github=connected")

    # mode == "login"
    if linked:
        user = await db.get(User, linked.user_id)
        linked.access_token_encrypted, linked.scopes, linked.login = encrypt_secret(token), scopes, login
    else:
        if not email:
            return _frontend_redirect("/login?error=github_email_unverified")
        if await db.scalar(select(User.id).where(func.lower(User.email) == email.lower())):
            # Never auto-link to an existing password account: sign in first, then connect from Settings.
            return _frontend_redirect("/login?error=account_exists")
        if not settings.allow_registration:
            return _frontend_redirect("/login?error=registration_closed")
        user, _org = await create_user_with_workspace(db, email, profile.get("name") or login, None, None)
        user.email_verified_at = utcnow()  # GitHub confirmed this as the verified primary address
        db.add(GitHubAccount(user_id=user.id, github_user_id=github_id, login=login, avatar_url=profile.get("avatar_url"),
                             access_token_encrypted=encrypt_secret(token), scopes=scopes))
    if user is None or not user.is_active:
        return _frontend_redirect("/login?error=account_disabled")
    membership = await db.scalar(select(Membership).where(Membership.user_id == user.id).order_by(Membership.id))
    response = _frontend_redirect("/overview")
    await create_session(db, user, membership.organisation_id, request, response)
    await audit(db, "user.login_github", organisation_id=membership.organisation_id, user_id=user.id, ip=client_ip(request))
    await db.commit()
    return response


@router.delete("/github", status_code=204, summary="Disconnect GitHub and delete the stored token")
async def github_disconnect(request: Request, principal: Principal = Depends(get_session_principal), db: AsyncSession = Depends(get_db)) -> None:
    account = await db.scalar(select(GitHubAccount).where(GitHubAccount.user_id == principal.user.id))
    if account is None:
        return
    user = await db.get(User, principal.user.id)
    if not user.password_hash:
        raise HTTPException(status_code=400, detail={"code": "password_required", "message": "Set a password before disconnecting GitHub, or you will be locked out."})
    settings = get_settings()
    token = decrypt_secret(account.access_token_encrypted)
    if token and settings.github_oauth_configured:
        try:  # best-effort revocation of the grant at GitHub
            async with httpx.AsyncClient(timeout=10.0, base_url=settings.github_api_url) as http:
                await http.request("DELETE", f"/applications/{settings.github_oauth_client_id}/grant",
                                   auth=(settings.github_oauth_client_id, settings.github_oauth_client_secret), json={"access_token": token})
        except httpx.HTTPError:
            log.warning("github_grant_revocation_failed", user_id=user.id)
    await db.delete(account)
    await audit(db, "github.disconnected", organisation_id=principal.organisation_id, user_id=user.id, ip=client_ip(request))
    await db.commit()
