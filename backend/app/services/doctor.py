"""Configuration and connectivity checks: ``python -m app.cli doctor``.

Run it on the deployed API service (or locally with the same environment) to see which integrations
are configured and whether the providers accept the credentials. It never prints secret values.
"""

from dataclasses import dataclass
from email.utils import parseaddr

import httpx
from sqlalchemy import text

from app import ratelimit
from app.config import Settings, get_settings
from app.database import get_sessionmaker
from app.services import mailer
from app.services.billing import REQUIRED_STRIPE_EVENTS, WEBHOOK_PATH

PASS, WARN, FAIL = "PASS", "WARN", "FAIL"


@dataclass
class Check:
    name: str
    status: str
    detail: str

    def line(self) -> str:
        return f"[{self.status}] {self.name}: {self.detail}"


def migration_head() -> str | None:
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    try:
        return ScriptDirectory.from_config(Config("alembic.ini")).get_current_head()
    except Exception:  # noqa: BLE001 - not run from the backend directory
        return None


async def check_database(settings: Settings) -> Check:
    try:
        async with get_sessionmaker()() as session:
            await session.execute(text("SELECT 1"))
            try:
                current = (await session.execute(text("SELECT version_num FROM alembic_version"))).scalar()
            except Exception:  # noqa: BLE001
                return Check("database", FAIL, "connected, but no migrations have been applied (run: alembic upgrade head)")
    except Exception as exc:  # noqa: BLE001
        return Check("database", FAIL, f"cannot connect ({type(exc).__name__})")
    head = migration_head()
    engine = "SQLite (development only)" if settings.is_sqlite else "PostgreSQL"
    if head and current != head:
        return Check("database", FAIL, f"{engine} connected; schema at {current}, code expects {head} (run: alembic upgrade head)")
    return Check("database", WARN if settings.is_sqlite else PASS, f"{engine} connected; migrations at {current}")


async def check_rate_limiting(settings: Settings) -> Check:
    state = await ratelimit.status()
    if state["backend"] == "redis":
        return Check("rate limiting", PASS if state["healthy"] else FAIL, "Redis reachable (shared across instances)" if state["healthy"] else "Redis is configured but unreachable; sensitive endpoints will return 503")
    return Check("rate limiting", WARN, "in-memory limiter: correct for exactly one API instance; set REDIS_URL before scaling out")


async def check_email(settings: Settings, send_to: str | None, transport: httpx.AsyncBaseTransport | None = None) -> list[Check]:
    if not settings.email_delivery_configured:
        return [Check("email", WARN, "not configured: no email is sent and accounts cannot be verified (set EMAIL_PROVIDER=resend, RESEND_API_KEY, EMAIL_FROM)")]
    sender = parseaddr(settings.email_from)[1]
    domain = sender.rpartition("@")[2].lower()
    checks: list[Check] = []
    if not domain or domain.endswith(("example.com", "example.org")):
        checks.append(Check("email sender", FAIL, f"EMAIL_FROM uses a placeholder address ({sender or 'unparseable'})"))
    try:
        async with httpx.AsyncClient(timeout=15.0, transport=transport) as http:
            resp = await http.get("https://api.resend.com/domains", headers={"Authorization": f"Bearer {settings.resend_api_key}"})
    except httpx.HTTPError as exc:
        return [*checks, Check("email provider", FAIL, f"Resend could not be reached ({type(exc).__name__})")]
    if resp.status_code == 200:
        domains = {d.get("name", "").lower(): d.get("status") for d in (resp.json().get("data") or [])}
        if domain in domains:
            verified = domains[domain] == "verified"
            checks.append(Check("email domain", PASS if verified else FAIL, f"{domain} is '{domains[domain]}' at Resend" + ("" if verified else " - add the DNS records shown in the Resend dashboard")))
        else:
            checks.append(Check("email domain", FAIL, f"{domain} is not added to this Resend account (domains present: {', '.join(sorted(domains)) or 'none'})"))
    elif resp.status_code in (401, 403) and "restricted" in resp.text.lower():
        checks.append(Check("email domain", WARN, "the API key is send-only, so domain verification cannot be read; use --send-test-email to test delivery"))
    else:
        return [*checks, Check("email provider", FAIL, f"Resend rejected the API key (HTTP {resp.status_code})")]
    if send_to:
        result = await mailer.ResendMailer(settings, transport=transport).send(mailer.test_email(send_to, settings.frontend_url))
        checks.append(Check("email test message", PASS if result == "sent" else FAIL,
                            f"accepted by Resend for {send_to}; confirm it arrives in the inbox (check spam)" if result == "sent" else "Resend refused the message (see the API log for the status code)"))
    return checks


async def check_stripe(settings: Settings, transport: httpx.AsyncBaseTransport | None = None) -> list[Check]:
    if not settings.stripe_configured:
        return [Check("payments", WARN, "not configured: plans cannot be purchased (set BILLING_PROVIDER=stripe, STRIPE_SECRET_KEY, STRIPE_WEBHOOK_SECRET)")]
    checks = [Check("payments mode", PASS if settings.stripe_test_mode else FAIL, "Stripe test mode" if settings.stripe_test_mode else "a LIVE Stripe key is configured")]
    auth = {"Authorization": f"Bearer {settings.stripe_secret_key}"}
    try:
        async with httpx.AsyncClient(timeout=15.0, transport=transport, base_url=settings.stripe_api_url) as http:
            balance = await http.get("/v1/balance", headers=auth)
            endpoints = await http.get("/v1/webhook_endpoints", headers=auth, params={"limit": 100}) if balance.status_code == 200 else None
    except httpx.HTTPError as exc:
        return [*checks, Check("payments provider", FAIL, f"Stripe could not be reached ({type(exc).__name__})")]
    if balance.status_code != 200:
        return [*checks, Check("payments provider", FAIL, f"Stripe rejected the API key (HTTP {balance.status_code})")]
    checks.append(Check("payments provider", PASS, "Stripe accepted the API key"))
    if not settings.stripe_webhook_secret:
        checks.append(Check("payments webhook secret", FAIL, "STRIPE_WEBHOOK_SECRET is not set: payments would never activate a plan"))
    expected_url = f"{settings.frontend_url.rstrip('/')}{WEBHOOK_PATH}"
    if endpoints is not None and endpoints.status_code == 200:
        match = next((e for e in endpoints.json().get("data", []) if e.get("url") == expected_url), None)
        if match is None:
            checks.append(Check("payments webhook endpoint", FAIL, f"no Stripe webhook endpoint points at {expected_url}"))
        else:
            events = set(match.get("enabled_events") or [])
            missing = [] if "*" in events else sorted(set(REQUIRED_STRIPE_EVENTS) - events)
            state = match.get("status")
            checks.append(Check("payments webhook endpoint", PASS if not missing and state == "enabled" else FAIL,
                                f"{expected_url} is {state}" + (f"; missing events: {', '.join(missing)}" if missing else "; all required events enabled")))
    else:
        checks.append(Check("payments webhook endpoint", WARN, "could not list webhook endpoints with this key (restricted key?); check the endpoint in the Stripe dashboard"))
    return checks


async def check_github(settings: Settings, transport: httpx.AsyncBaseTransport | None = None) -> Check:
    headers = {"Accept": "application/vnd.github+json", **({"Authorization": f"Bearer {settings.github_token}"} if settings.github_token else {})}
    try:
        async with httpx.AsyncClient(timeout=15.0, transport=transport, base_url=settings.github_api_url) as http:
            resp = await http.get("/rate_limit", headers=headers)
    except httpx.HTTPError as exc:
        return Check("github", FAIL, f"GitHub API could not be reached ({type(exc).__name__})")
    if resp.status_code != 200:
        return Check("github", FAIL, f"GitHub rejected the request (HTTP {resp.status_code}); check GITHUB_TOKEN")
    limit = (resp.json().get("resources") or {}).get("core", {}).get("limit")
    return Check("github", PASS if settings.github_token else WARN, f"{limit} requests/hour" + ("" if settings.github_token else " (anonymous; set GITHUB_TOKEN for 5,000/hour and issue/PR totals)"))


async def run_checks(send_test_email_to: str | None = None, transport: httpx.AsyncBaseTransport | None = None) -> list[Check]:
    settings = get_settings()
    checks = [Check("environment", PASS if settings.app_env == "production" else WARN,
                    f"APP_ENV={settings.app_env}" + ("; production safety checks passed" if settings.app_env == "production" else " (production safety checks only run with APP_ENV=production)"))]
    checks.append(await check_database(settings))
    checks.append(await check_rate_limiting(settings))
    checks += await check_email(settings, send_test_email_to, transport)
    checks += await check_stripe(settings, transport)
    checks.append(await check_github(settings, transport))
    checks.append(Check("github sign-in", PASS if settings.github_oauth_configured else WARN, "OAuth app configured" if settings.github_oauth_configured else "not configured (email sign-in only)"))
    checks.append(Check("ai enrichment", PASS if settings.llm_configured else WARN, f"provider {settings.llm_provider}" if settings.llm_configured else "not configured (reports use the rules engine)"))
    return checks
