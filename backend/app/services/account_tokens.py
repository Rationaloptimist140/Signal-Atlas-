"""Single-use, hashed, expiring tokens for e-mail verification and password reset."""

import datetime as dt

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import EmailToken, User, utcnow
from app.security import hash_token, new_token
from app.services import mailer

VERIFY, RESET = "verify_email", "password_reset"


async def issue_token(session: AsyncSession, user: User, purpose: str, ip: str | None = None) -> str:
    """Create a token, invalidating any earlier unused token of the same purpose. Returns the raw token (never stored)."""
    settings = get_settings()
    now = utcnow()
    await session.execute(update(EmailToken).where(EmailToken.user_id == user.id, EmailToken.purpose == purpose, EmailToken.used_at.is_(None)).values(used_at=now))
    ttl = dt.timedelta(hours=settings.verification_token_hours) if purpose == VERIFY else dt.timedelta(minutes=settings.password_reset_token_minutes)
    raw = new_token(32)
    session.add(EmailToken(user_id=user.id, purpose=purpose, token_hash=hash_token(raw), expires_at=now + ttl, ip_address=ip))
    await session.flush()
    return raw


async def consume_token(session: AsyncSession, raw: str, purpose: str) -> User | None:
    """Validate and burn a token. Returns the user, or None if the token is unknown, used, expired or for another purpose."""
    token = await session.scalar(select(EmailToken).where(EmailToken.token_hash == hash_token(raw), EmailToken.purpose == purpose))
    now = utcnow()
    if token is None or token.used_at is not None or token.expires_at <= now:
        return None
    token.used_at = now
    user = await session.get(User, token.user_id)
    return user if user and user.is_active else None


async def send_verification(session: AsyncSession, user: User, ip: str | None = None) -> str:
    settings = get_settings()
    raw = await issue_token(session, user, VERIFY, ip)
    url = f"{settings.frontend_url.rstrip('/')}/verify-email?token={raw}"
    return await mailer.get_mailer().send(mailer.verification_email(user.email, user.full_name.split(" ")[0] if user.full_name else "", url, settings.verification_token_hours))


async def send_password_reset(session: AsyncSession, user: User, ip: str | None = None) -> str:
    settings = get_settings()
    raw = await issue_token(session, user, RESET, ip)
    url = f"{settings.frontend_url.rstrip('/')}/reset-password?token={raw}"
    return await mailer.get_mailer().send(mailer.password_reset_email(user.email, url, settings.password_reset_token_minutes))
