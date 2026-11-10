"""Provider-independent transactional e-mail.

* ``console`` (default) never delivers. In development it writes the action link to the local
  log so flows can be exercised; in production it logs only that delivery is not configured.
* ``resend`` delivers through the Resend HTTPS API (works on hosts that block SMTP).

Add a provider by implementing ``send``. Tokens are never logged in production.
"""

import html
from dataclasses import dataclass
from typing import Protocol

import httpx

from app.config import Settings, get_settings
from app.logging_config import get_logger

log = get_logger("mailer")


@dataclass
class EmailMessage:
    to: str
    subject: str
    text: str
    html: str
    kind: str  # verify_email | password_reset
    action_url: str | None = None


class Mailer(Protocol):
    name: str
    delivers: bool

    async def send(self, message: EmailMessage) -> str: ...


class ConsoleMailer:
    """Non-delivering mailer. ``outbox`` keeps messages in memory for tests only."""

    name = "console"
    delivers = False
    outbox: list[EmailMessage] = []

    def __init__(self, settings: Settings):
        self._env = settings.app_env

    async def send(self, message: EmailMessage) -> str:
        if self._env == "test":
            ConsoleMailer.outbox.append(message)
            return "captured"
        if self._env == "development":
            # Local convenience only: the link appears in the developer's own terminal.
            print(f"[dev-mail] {message.kind} for {message.to}: {message.action_url}", flush=True)  # noqa: T201
            return "logged_dev"
        log.warning("email_not_sent", reason="email provider not configured", kind=message.kind)
        return "not_configured"


class ResendMailer:
    name = "resend"
    delivers = True

    def __init__(self, settings: Settings, transport: httpx.AsyncBaseTransport | None = None):
        self._key = settings.resend_api_key or ""
        self._from = settings.email_from
        self._reply_to = settings.email_reply_to
        self._transport = transport

    async def send(self, message: EmailMessage) -> str:
        payload: dict = {"from": self._from, "to": [message.to], "subject": message.subject, "text": message.text, "html": message.html}
        if self._reply_to:
            payload["reply_to"] = self._reply_to
        try:
            async with httpx.AsyncClient(timeout=15.0, transport=self._transport) as http:
                resp = await http.post("https://api.resend.com/emails", headers={"Authorization": f"Bearer {self._key}"}, json=payload)
        except httpx.HTTPError as exc:
            log.error("email_send_failed", provider="resend", kind=message.kind, error=type(exc).__name__)
            return "failed"
        if resp.status_code >= 300:
            log.error("email_send_failed", provider="resend", kind=message.kind, status=resp.status_code)
            return "failed"
        log.info("email_sent", provider="resend", kind=message.kind)
        return "sent"


def get_mailer(settings: Settings | None = None) -> Mailer:
    settings = settings or get_settings()
    if settings.email_delivery_configured:
        return ResendMailer(settings)
    return ConsoleMailer(settings)


# ----------------------------------------------------------------------------- templates

_HTML = """<!doctype html><html><body style="margin:0;background:#080B14;font-family:Inter,Arial,sans-serif;color:#F8FAFC">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr><td align="center" style="padding:40px 16px">
<table role="presentation" width="520" cellpadding="0" cellspacing="0" style="max-width:520px;background:#141C2D;border:1px solid #26314A;border-radius:14px">
<tr><td style="padding:32px">
<p style="margin:0 0 24px;font-size:12px;letter-spacing:3px;color:#A78BFA;font-weight:700">SIGNAL ATLAS</p>
<h1 style="margin:0 0 12px;font-size:20px;color:#F8FAFC">{heading}</h1>
<p style="margin:0 0 24px;font-size:14px;line-height:22px;color:#94A3B8">{intro}</p>
<p style="margin:0 0 24px"><a href="{url}" style="display:inline-block;background:#8B5CF6;color:#ffffff;text-decoration:none;font-weight:600;font-size:14px;padding:12px 20px;border-radius:8px">{button}</a></p>
<p style="margin:0 0 8px;font-size:12px;line-height:18px;color:#64748B">{expiry} If the button does not work, copy this link into your browser:</p>
<p style="margin:0 0 24px;font-size:12px;line-height:18px;word-break:break-all;color:#22D3EE">{url}</p>
<p style="margin:0;font-size:12px;line-height:18px;color:#64748B">{footer}</p>
</td></tr></table></td></tr></table></body></html>"""


def _render(to: str, kind: str, subject: str, heading: str, intro: str, button: str, expiry: str, footer: str, url: str) -> EmailMessage:
    text = f"{heading}\n\n{intro}\n\n{button}: {url}\n\n{expiry}\n{footer}\n\n- Signal Atlas"
    body = _HTML.format(heading=html.escape(heading), intro=html.escape(intro), button=html.escape(button), expiry=html.escape(expiry),
                        footer=html.escape(footer), url=html.escape(url, quote=True))
    return EmailMessage(to=to, subject=subject, text=text, html=body, kind=kind, action_url=url)


def verification_email(to: str, name: str, url: str, hours: int) -> EmailMessage:
    return _render(to, "verify_email", "Confirm your email address for Signal Atlas", f"Confirm your email, {name or 'there'}",
                   "Confirm this address to unlock report generation, API keys and live GitHub requests.", "Confirm email address",
                   f"This link expires in {hours} hours and can be used once.", "If you did not create a Signal Atlas account, you can ignore this email.", url)


def password_reset_email(to: str, url: str, minutes: int) -> EmailMessage:
    return _render(to, "password_reset", "Reset your Signal Atlas password", "Reset your password",
                   "We received a request to reset the password for this account.", "Choose a new password",
                   f"This link expires in {minutes} minutes and can be used once.",
                   "If you did not request this, ignore this email: your password stays unchanged.", url)
