"""Production hardening: configuration guards, rate limiting backends, proxy handling, CSP, provider checks, billing sync."""

import datetime as dt
import json
import os
import time
from types import SimpleNamespace
from urllib.parse import parse_qs

import fakeredis.aioredis
import pytest
import respx
from httpx import Response
from sqlalchemy import select

from app import ratelimit
from app.config import Settings
from app.deps import client_ip
from app.models import AuditLog, EmailToken, Payment, Subscription, utcnow
from app.services import billing, doctor, jobs
from app.services.mailer import ConsoleMailer, ResendMailer, account_exists_email, verification_email
from tests.conftest import PASSWORD, make_client, production_settings
from tests.test_billing import STRIPE, activate_pro, deliver, event, invoice_obj, subscription_obj

# ----------------------------------------------------------------------------- configuration guards


def test_valid_production_configuration_is_accepted():
    settings = production_settings()
    assert settings.cookie_secure is True and settings.rate_limit_uses_redis and settings.database_url.startswith("postgresql+asyncpg://")
    assert production_settings(redis_url=None, rate_limit_backend="memory").rate_limit_uses_redis is False  # explicit single-instance choice


@pytest.mark.parametrize(("override", "expected"), [
    ({"secret_key": "dev-only-insecure-secret-change-me"}, "SECRET_KEY"),
    ({"secret_key": "short"}, "SECRET_KEY"),
    ({"database_url": "sqlite+aiosqlite:///./signal_atlas.db"}, "PostgreSQL"),
    ({"frontend_url": "http://atlas.example.org"}, "https://"),
    ({"cors_origins": "https://atlas.example.org,http://localhost:3000"}, "localhost"),
    ({"cookie_secure": False}, "COOKIE_SECURE"),
    ({"allow_self_serve_plan_change": True}, "ALLOW_SELF_SERVE_PLAN_CHANGE"),
    ({"seed_demo_data": True}, "SEED_DEMO_DATA"),
    ({"redis_url": None}, "REDIS_URL"),
    ({"stripe_secret_key": "sk_live_" + "x" * 24}, "test-mode key"),
])
def test_unsafe_production_configuration_is_refused(override, expected):
    with pytest.raises(ValueError, match=expected):
        production_settings(**override)


def test_redis_backend_requires_a_url():
    with pytest.raises(ValueError, match="REDIS_URL"):
        Settings(rate_limit_backend="redis")


# ----------------------------------------------------------------------------- client address behind proxies


def _request(xff: str | None, peer: str = "10.0.0.9"):
    return SimpleNamespace(headers={"x-forwarded-for": xff} if xff else {}, client=SimpleNamespace(host=peer))


def test_client_ip_ignores_forged_forwarded_for_entries(settings, monkeypatch):
    monkeypatch.setattr(settings, "trusted_proxy_hops", 2)  # platform edge + Next.js proxy
    assert client_ip(_request("203.0.113.7, 10.1.1.1")) == "203.0.113.7"
    assert client_ip(_request("6.6.6.6, 203.0.113.7, 10.1.1.1")) == "203.0.113.7"  # a client-supplied first entry is never trusted
    assert client_ip(_request("203.0.113.7")) == "203.0.113.7"
    monkeypatch.setattr(settings, "trusted_proxy_hops", 1)
    assert client_ip(_request("6.6.6.6, 203.0.113.7")) == "203.0.113.7"
    monkeypatch.setattr(settings, "trusted_proxy_hops", 0)
    assert client_ip(_request("6.6.6.6")) == "10.0.0.9"  # no trusted proxy: only the socket address counts
    assert client_ip(_request(None)) == "10.0.0.9"


async def test_forged_header_cannot_evade_the_login_rate_limit(anon, settings, monkeypatch):
    monkeypatch.setattr(settings, "trusted_proxy_hops", 1)
    statuses = []
    for attempt in range(22):
        resp = await anon.post("/api/v1/auth/login", json={"email": f"nobody{attempt}@example.com", "password": PASSWORD},
                               headers={"X-Forwarded-For": f"198.51.100.{attempt}, 203.0.113.50"})  # attacker rotates the forged entry
        statuses.append(resp.status_code)
    assert statuses[:20] == [401] * 20 and statuses[20:] == [429, 429]


# ----------------------------------------------------------------------------- rate limiting backends


async def _exercise_limiter():
    results = [await ratelimit.hit("unit:key", 3, 60, sensitive=True) for _ in range(5)]
    assert [allowed for allowed, _ in results] == [True, True, True, False, False]
    assert all(1 <= retry <= 60 for _, retry in results)
    assert (await ratelimit.hit("unit:other", 3, 60))[0] is True  # keys are independent


async def test_memory_limiter():
    await _exercise_limiter()
    assert await ratelimit.status() == {"backend": "memory", "healthy": True, "shared": False}


async def test_redis_limiter_with_in_process_fake(settings, monkeypatch):
    fake = fakeredis.aioredis.FakeRedis()
    monkeypatch.setattr(settings, "rate_limit_backend", "redis")
    monkeypatch.setattr(settings, "redis_url", "redis://fake:6379/0")
    monkeypatch.setattr(ratelimit, "_client", lambda: fake)
    await _exercise_limiter()
    keys = [k.decode() for k in await fake.keys("sa:rl:*")]
    ttls = [await fake.ttl(k) for k in keys]
    assert len(keys) == 2 and all(0 < ttl <= 61 for ttl in ttls)  # counters expire on their own
    assert not ratelimit._windows  # nothing was counted in process memory
    assert (await ratelimit.status())["backend"] == "redis"


@pytest.mark.skipif(not os.environ.get("TEST_REDIS_URL"), reason="set TEST_REDIS_URL to run against a real Redis server")
async def test_redis_limiter_against_a_real_server(client, settings, monkeypatch):
    monkeypatch.setattr(settings, "rate_limit_backend", "redis")
    monkeypatch.setattr(settings, "redis_url", os.environ["TEST_REDIS_URL"])
    await ratelimit._client().flushdb()
    await _exercise_limiter()
    assert await ratelimit.status() == {"backend": "redis", "healthy": True, "shared": True}
    # a second "instance" (fresh process state, same Redis) sees the same counters
    ratelimit._windows.clear()
    assert (await ratelimit.hit("unit:key", 3, 60))[0] is False
    ready = await client.get("/health/ready")
    assert ready.status_code == 200 and ready.json()["rate_limiting"]["backend"] == "redis"
    async with make_client() as visitor:
        codes = [(await visitor.post("/api/v1/auth/login", json={"email": "nobody@example.com", "password": PASSWORD})).status_code for _ in range(21)]
    assert codes == [401] * 20 + [429]
    await ratelimit._client().flushdb()
    await ratelimit._client().aclose()


async def test_unreachable_redis_fails_closed_for_sensitive_actions_only(client, demo_data, settings, monkeypatch):
    monkeypatch.setattr(settings, "rate_limit_backend", "redis")
    monkeypatch.setattr(settings, "redis_url", "redis://127.0.0.1:1/0")  # nothing listens here
    async with make_client() as visitor:
        for call in (visitor.post("/api/v1/auth/login", json={"email": "owner-a@example.com", "password": PASSWORD}),
                     visitor.post("/api/v1/auth/register", json={"email": "x@example.com", "password": PASSWORD, "full_name": "X"}),
                     visitor.post("/api/v1/auth/password-reset/request", json={"email": "owner-a@example.com"})):
            resp = await call
            assert resp.status_code == 503 and resp.json()["error"]["code"] == "temporarily_unavailable" and resp.headers["retry-after"] == "10"
        assert (await visitor.get("/api/v1/billing/plans")).status_code == 200  # public reads degrade to the per-process limiter
    assert (await client.get("/api/v1/opportunities")).status_code == 200  # signed-in browsing keeps working
    assert (await client.post("/api/v1/auth/change-password", json={"current_password": PASSWORD, "new_password": "An0therStrongPass"})).status_code == 503
    assert ratelimit._windows  # the fallback limiter is still counting
    ready = await client.get("/health/ready")
    assert ready.status_code == 503 and ready.json() == {"status": "unavailable", "database": True, "rate_limiting": {"backend": "redis", "healthy": False, "shared": True}}
    assert ConsoleMailer.outbox == [] or all(m.to != "x@example.com" for m in ConsoleMailer.outbox)  # the refused sign-up created nothing


async def test_public_and_sensitive_endpoints_are_rate_limited(client):
    async with make_client() as visitor:
        codes = [(await visitor.get("/api/v1/billing/plans")).status_code for _ in range(121)]
    assert codes[:120] == [200] * 120 and codes[120] == 429
    attempts = [(await client.post("/api/v1/auth/change-password", json={"current_password": "wrong", "new_password": "An0therStrongPass"})).status_code for _ in range(6)]
    assert attempts == [400] * 5 + [429]


# ----------------------------------------------------------------------------- response headers


async def test_api_responses_carry_a_locked_down_content_security_policy(anon):
    resp = await anon.get("/health")
    assert resp.headers["content-security-policy"] == "default-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'"
    assert resp.headers["permissions-policy"] == "camera=(), microphone=(), geolocation=()"
    docs = await anon.get("/api/docs")
    policy = docs.headers["content-security-policy"]
    assert docs.status_code == 200 and "https://cdn.jsdelivr.net" in policy and "default-src 'none'" in policy and "frame-ancestors 'none'" in policy
    assert "unsafe-eval" not in policy and "*" not in policy.replace("https://", "")


# ----------------------------------------------------------------------------- mailer delivery handling


async def test_resend_retries_transient_failures_once_with_the_same_idempotency_key():
    settings = Settings(email_provider="resend", resend_api_key="re_test_key", email_from="Signal Atlas <no-reply@mail.example.net>")
    mailer = ResendMailer(settings)
    mailer.retry_delay = 0
    message = verification_email("user@example.com", "Uma", "https://app.example.net/verify-email#token=abc", 24)
    with respx.mock() as mock:
        route = mock.post("https://api.resend.com/emails").mock(side_effect=[Response(503), Response(200, json={"id": "email_1"})])
        assert await mailer.send(message) == "sent"
        keys = {call.request.headers["idempotency-key"] for call in route.calls}
        assert route.call_count == 2 and len(keys) == 1
    with respx.mock() as mock:
        route = mock.post("https://api.resend.com/emails").mock(return_value=Response(500))
        assert await mailer.send(message) == "failed" and route.call_count == 2  # gives up after one retry
    with respx.mock() as mock:
        route = mock.post("https://api.resend.com/emails").mock(return_value=Response(403, json={"message": "domain is not verified"}))
        assert await mailer.send(message) == "failed" and route.call_count == 1  # permanent errors are not retried
    notice = account_exists_email("user@example.com", "https://app.example.net/login")
    assert notice.kind == "account_exists" and "already exists" in notice.text and "token" not in notice.text.lower()


async def test_housekeeping_removes_old_email_tokens(client, db):
    await client.post("/api/v1/auth/verify-email/request")
    old = EmailToken(user_id=client.me["user"]["id"], purpose="password_reset", token_hash="f" * 64, expires_at=utcnow() - dt.timedelta(days=8))
    db.add(old)
    await db.commit()
    result = await jobs.HANDLERS["retention_cleanup"](db, {})
    assert result["email_tokens"] == 1 and await db.scalar(select(EmailToken).where(EmailToken.token_hash == "f" * 64)) is None


# ----------------------------------------------------------------------------- provider checks (doctor)


def _doctor_transport(resend_domains=None, resend_status=200, stripe_ok=True, endpoints=None):
    def handler(request):
        url = str(request.url)
        if url == "https://api.resend.com/domains":
            return Response(resend_status, json={"data": resend_domains or []} if resend_status == 200 else {"message": "This API key is restricted to only send emails"})
        if url == "https://api.resend.com/emails":
            return Response(200, json={"id": "email_test"})
        if url.endswith("/v1/balance"):
            return Response(200 if stripe_ok else 401, json={"livemode": False})
        if "/v1/webhook_endpoints" in url:
            return Response(200, json={"data": endpoints or []})
        if url.endswith("/rate_limit"):
            return Response(200, json={"resources": {"core": {"limit": 5000 if "authorization" in request.headers else 60}}})
        return Response(404)
    import httpx
    return httpx.MockTransport(handler)


async def test_doctor_reports_unconfigured_integrations_without_failing(engine):
    checks = {c.name: c for c in await doctor.run_checks(transport=_doctor_transport())}
    assert checks["email"].status == checks["payments"].status == checks["github"].status == doctor.WARN
    assert "accounts cannot be verified" in checks["email"].detail and "60 requests/hour" in checks["github"].detail
    assert checks["rate limiting"].status == doctor.WARN and checks["database"].status in (doctor.PASS, doctor.WARN, doctor.FAIL)


async def test_doctor_checks_resend_domain_and_sends_a_test_message(settings, monkeypatch):
    monkeypatch.setattr(settings, "email_provider", "resend")
    monkeypatch.setattr(settings, "resend_api_key", "re_secret_value_1234567890")
    monkeypatch.setattr(settings, "email_from", "Signal Atlas <no-reply@mail.flanuer.com>")
    pending = await doctor.check_email(settings, None, _doctor_transport([{"name": "mail.flanuer.com", "status": "pending"}]))
    assert [(c.name, c.status) for c in pending] == [("email domain", doctor.FAIL)] and "'pending'" in pending[0].detail
    missing = await doctor.check_email(settings, None, _doctor_transport([{"name": "other.example.net", "status": "verified"}]))
    assert missing[0].status == doctor.FAIL and "not added to this Resend account" in missing[0].detail
    verified = await doctor.check_email(settings, "owner@example.net", _doctor_transport([{"name": "mail.flanuer.com", "status": "verified"}]))
    assert [(c.name, c.status) for c in verified] == [("email domain", doctor.PASS), ("email test message", doctor.PASS)]
    send_only = await doctor.check_email(settings, None, _doctor_transport(resend_status=401))
    assert send_only[0].status == doctor.WARN and "send-only" in send_only[0].detail
    assert not any("re_secret_value" in c.line() for c in [*pending, *missing, *verified, *send_only])  # secrets are never printed
    monkeypatch.setattr(settings, "email_from", "Signal Atlas <no-reply@mail.example.com>")
    placeholder = await doctor.check_email(settings, None, _doctor_transport())
    assert placeholder[0].name == "email sender" and placeholder[0].status == doctor.FAIL


async def test_doctor_checks_stripe_key_and_webhook_endpoint(settings, monkeypatch):
    monkeypatch.setattr(settings, "billing_provider", "stripe")
    monkeypatch.setattr(settings, "stripe_secret_key", "sk_test_secret_value_123")
    monkeypatch.setattr(settings, "stripe_webhook_secret", "whsec_x")
    monkeypatch.setattr(settings, "frontend_url", "https://atlas.example.org")
    url = "https://atlas.example.org/api/v1/billing/webhooks/stripe"
    none = {c.name: c for c in await doctor.check_stripe(settings, _doctor_transport())}
    assert none["payments mode"].status == doctor.PASS and none["payments provider"].status == doctor.PASS
    assert none["payments webhook endpoint"].status == doctor.FAIL and url in none["payments webhook endpoint"].detail
    partial = {c.name: c for c in await doctor.check_stripe(settings, _doctor_transport(endpoints=[{"url": url, "status": "enabled", "enabled_events": ["invoice.paid"]}]))}
    assert partial["payments webhook endpoint"].status == doctor.FAIL and "checkout.session.completed" in partial["payments webhook endpoint"].detail
    full = {c.name: c for c in await doctor.check_stripe(settings, _doctor_transport(endpoints=[{"url": url, "status": "enabled", "enabled_events": list(billing.REQUIRED_STRIPE_EVENTS)}]))}
    assert full["payments webhook endpoint"].status == doctor.PASS
    rejected = await doctor.check_stripe(settings, _doctor_transport(stripe_ok=False))
    assert rejected[-1].status == doctor.FAIL and "rejected the API key" in rejected[-1].detail
    assert not any("secret_value" in c.line() for c in [*none.values(), *partial.values(), *full.values(), *rejected])


# ----------------------------------------------------------------------------- billing: sync, newer Stripe payloads, housekeeping


@pytest.fixture
def stripe(settings, monkeypatch):
    monkeypatch.setattr(settings, "billing_provider", "stripe")
    monkeypatch.setattr(settings, "stripe_secret_key", "sk_test_abc123")
    monkeypatch.setattr(settings, "stripe_webhook_secret", "whsec_test_secret")
    monkeypatch.setattr(settings, "allow_self_serve_plan_change", False)
    return settings


async def test_checkout_return_url_carries_the_session_id_placeholder(client, stripe):
    with respx.mock() as mock:
        route = mock.post(f"{STRIPE}/v1/checkout/sessions").mock(return_value=Response(200, json={"id": "cs_test_1", "url": "https://checkout.stripe.com/c/pay/cs_test_1"}))
        await client.post("/api/v1/billing/checkout", json={"plan": "pro"})
    form = {k: v[0] for k, v in parse_qs(route.calls.last.request.content.decode()).items()}
    assert form["success_url"].endswith("/settings?tab=billing&checkout=success&session_id={CHECKOUT_SESSION_ID}")
    assert form["cancel_url"].endswith("/settings?tab=billing&checkout=cancelled")


async def test_sync_after_checkout_activates_without_waiting_for_the_webhook(client, other_client, stripe):
    org_id = client.me["organisation"]["id"]
    session = {"id": "cs_test_ok", "mode": "subscription", "status": "complete", "payment_status": "paid", "customer": "cus_1", "subscription": "sub_1",
               "client_reference_id": str(org_id), "metadata": {"organisation_id": str(org_id), "plan": "business", "interval": "month"}}
    remote_sub = subscription_obj(org_id, plan="business", interval="month")
    with respx.mock(assert_all_called=True) as mock:
        mock.get(f"{STRIPE}/v1/checkout/sessions/cs_test_ok").mock(return_value=Response(200, json=session))
        mock.get(f"{STRIPE}/v1/subscriptions/sub_1").mock(return_value=Response(200, json=remote_sub))
        synced = await client.post("/api/v1/billing/sync", json={"session_id": "cs_test_ok"})
    assert synced.status_code == 200 and synced.json() == {"outcome": "processed", "status": "active", "plan": "business"}
    sub = (await client.get("/api/v1/billing/subscription")).json()
    assert (sub["plan"]["key"], sub["billing_interval"], sub["manageable"]) == ("business", "month", True)
    # another workspace cannot claim someone else's checkout session
    with respx.mock() as mock:
        mock.get(f"{STRIPE}/v1/checkout/sessions/cs_test_ok").mock(return_value=Response(200, json=session))
        stolen = await other_client.post("/api/v1/billing/sync", json={"session_id": "cs_test_ok"})
    assert stolen.status_code == 404 and (await other_client.get("/api/v1/billing/subscription")).json()["plan"]["key"] == "free"
    assert (await client.post("/api/v1/billing/sync", json={"session_id": "../v1/customers"})).status_code == 422  # ids are validated, never interpolated blindly


async def test_sync_picks_up_a_cancellation_whose_webhook_was_missed(client, stripe):
    org_id = await activate_pro(client)
    with respx.mock() as mock:
        mock.get(f"{STRIPE}/v1/subscriptions/sub_1").mock(return_value=Response(200, json=subscription_obj(org_id, status="canceled")))
        result = await client.post("/api/v1/billing/sync", json={})
    assert result.json() == {"outcome": "processed", "status": "expired", "plan": "free"}


async def test_unpaid_or_open_checkout_grants_nothing(client, stripe):
    org_id = client.me["organisation"]["id"]
    open_session = {"id": "cs_test_open", "mode": "subscription", "status": "open", "payment_status": "unpaid", "client_reference_id": str(org_id), "metadata": {"plan": "pro"}}
    with respx.mock() as mock:
        mock.get(f"{STRIPE}/v1/checkout/sessions/cs_test_open").mock(return_value=Response(200, json=open_session))
        result = await client.post("/api/v1/billing/sync", json={"session_id": "cs_test_open"})
    assert result.json() == {"outcome": "unchanged", "status": "active", "plan": "free"}


async def test_newer_stripe_payload_shapes_are_understood(client, stripe, db):
    """API versions from 2025-03-31 move the period to subscription items and drop charge/invoice cross-references."""
    org_id = client.me["organisation"]["id"]
    start, end = int(time.time()), int(time.time()) + 30 * 86400
    sub_obj = {"id": "sub_new", "customer": "cus_new", "status": "active", "cancel_at_period_end": False, "metadata": {"organisation_id": str(org_id), "plan": "pro", "interval": "month"},
               "items": {"data": [{"current_period_start": start, "current_period_end": end}]}}
    invoice = {"id": "in_new", "customer": "cus_new", "currency": "gbp", "amount_paid": 1900, "amount_due": 1900, "status_transitions": {"paid_at": start},
               "parent": {"subscription_details": {"subscription": "sub_new", "metadata": {"organisation_id": str(org_id), "plan": "pro", "interval": "month"}}},
               "lines": {"data": [{"description": "Signal Atlas Pro (monthly)", "period": {"start": start, "end": end}}]}}
    assert (await deliver(event("evt_n1", "customer.subscription.created", sub_obj))).json() == {"status": "processed"}
    assert (await deliver(event("evt_n2", "invoice.paid", invoice))).json() == {"status": "processed"}
    sub = (await client.get("/api/v1/billing/subscription")).json()
    assert sub["plan"]["key"] == "pro" and sub["current_period_end"].startswith(dt.datetime.fromtimestamp(end, dt.UTC).date().isoformat())
    linked = await deliver(event("evt_n3", "invoice_payment.paid", {"id": "inpay_1", "invoice": "in_new", "payment": {"type": "payment_intent", "payment_intent": "pi_new"}}))
    assert linked.json() == {"status": "processed"}
    refund = await deliver(event("evt_n4", "charge.refunded", {"id": "ch_new", "payment_intent": "pi_new", "customer": "cus_new", "amount": 1900, "amount_refunded": 1900}))
    assert refund.json() == {"status": "processed"}
    payment = await db.scalar(select(Payment).where(Payment.provider_payment_id == "in_new"))
    assert (payment.status, payment.refunded_minor, payment.organisation_id) == ("refunded", 1900, org_id)


async def test_refund_falls_back_to_customer_and_amount_when_no_reference_is_sent(client, stripe):
    org_id = await activate_pro(client)
    bare = await deliver(event("evt_bare", "charge.refunded", {"id": "ch_unlinked", "customer": "cus_1", "amount": 19000, "amount_refunded": 19000}))
    assert bare.json() == {"status": "processed"}
    assert (await client.get("/api/v1/billing/payments")).json()["items"][0]["status"] == "refunded"
    other_amount = await deliver(event("evt_bare2", "charge.refunded", {"id": "ch_other", "customer": "cus_1", "amount": 555, "amount_refunded": 555}))
    assert other_amount.json() == {"status": "unknown_payment"} and org_id


async def test_housekeeping_expires_lapsed_subscriptions(client, stripe, db):
    org_id = await activate_pro(client)
    await deliver(event("evt_fail", "invoice.payment_failed", invoice_obj(org_id, invoice_id="in_2", paid=False)))
    row = await db.scalar(select(Subscription).where(Subscription.organisation_id == org_id))
    assert await billing.expire_lapsed(db) == 0  # still inside the grace period
    row.grace_until = utcnow() - dt.timedelta(minutes=1)
    await db.commit()
    assert await billing.expire_lapsed(db) == 1
    await db.refresh(row)
    assert (row.status, row.plan) == ("expired", "free")
    assert "subscription.expired" in set((await db.scalars(select(AuditLog.action))).all())
    assert json.dumps((await client.get("/api/v1/billing/subscription")).json()["status"]) == '"expired"'
