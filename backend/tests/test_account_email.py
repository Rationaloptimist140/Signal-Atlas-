"""E-mail verification, the soft gate, password reset and the mailer."""

import datetime as dt

import respx
from httpx import Response
from sqlalchemy import select

from app.config import Settings
from app.models import AuditLog, EmailToken, User, utcnow
from app.security import hash_token
from app.services.mailer import ConsoleMailer, ResendMailer, password_reset_email, verification_email
from tests.conftest import PASSWORD, last_token, make_client, register

NEW_PASSWORD = "Br4ndNewPassw0rd"


async def test_registration_sends_verification_and_soft_gate_blocks_premium_actions(anon, demo_data, db):
    data = await register(anon, "new@example.com", "Nia New", verify=False)
    assert data["user"]["email_verified"] is False and data["verification_email"] == "captured"
    message = ConsoleMailer.outbox[-1]
    assert message.to == "new@example.com" and message.kind == "verify_email"
    assert "/verify-email?token=" in message.action_url and message.action_url in message.text and "Confirm email address" in message.html
    raw = last_token("verify_email")
    stored = await db.scalar(select(EmailToken))
    assert stored.token_hash == hash_token(raw) and raw not in stored.token_hash  # only a hash is stored
    assert dt.timedelta(hours=23) < stored.expires_at - utcnow() <= dt.timedelta(hours=24)

    # unverified users can sign in and browse...
    assert (await anon.get("/api/v1/opportunities")).status_code == 200
    assert (await anon.get("/api/v1/dashboard")).status_code == 200
    repo_id = (await anon.get("/api/v1/repositories?page_size=1")).json()["items"][0]["id"]
    assert (await anon.post("/api/v1/watchlists", json={"name": "Allowed"})).status_code == 201
    # ...but premium and live operations are refused by the backend
    await anon.post("/api/v1/billing/checkout", json={"plan": "pro"})
    for call in (anon.post("/api/v1/reports/generate", json={"report_type": "repository", "subject_id": repo_id}),
                 anon.post("/api/v1/api-keys", json={"name": "CI"}),
                 anon.get("/api/v1/repositories/github-search?q=rocket"),
                 anon.post("/api/v1/repositories/track", json={"full_name": "acme/rocket"})):
        resp = await call
        assert resp.status_code == 403 and resp.json()["error"]["code"] == "email_verification_required", resp.text

    assert (await anon.post("/api/v1/auth/verify-email/confirm", json={"token": raw})).json() == {"status": "verified"}
    assert (await anon.get("/api/v1/auth/me")).json()["user"]["email_verified"] is True
    assert (await anon.post("/api/v1/reports/generate", json={"report_type": "repository", "subject_id": repo_id})).status_code == 201
    assert (await anon.post("/api/v1/api-keys", json={"name": "CI"})).status_code == 201
    reused = await anon.post("/api/v1/auth/verify-email/confirm", json={"token": raw})
    assert reused.status_code == 400 and reused.json()["error"]["code"] == "invalid_token"  # single use
    assert "user.email_verified" in set((await db.scalars(select(AuditLog.action))).all())


async def test_verification_tokens_expire_and_are_replaced_on_resend(anon, db):
    await register(anon, "exp@example.com", verify=False)
    first = last_token("verify_email")
    resend = await anon.post("/api/v1/auth/verify-email/request")
    assert resend.status_code == 202 and resend.json()["delivery_configured"] is False
    second = last_token("verify_email")
    assert second != first
    assert (await anon.post("/api/v1/auth/verify-email/confirm", json={"token": first})).status_code == 400  # superseded
    token = await db.scalar(select(EmailToken).where(EmailToken.token_hash == hash_token(second)))
    token.expires_at = utcnow() - dt.timedelta(seconds=1)
    await db.commit()
    assert (await anon.post("/api/v1/auth/verify-email/confirm", json={"token": second})).status_code == 400  # expired
    assert (await anon.post("/api/v1/auth/verify-email/confirm", json={"token": "x" * 40})).status_code == 400
    # a password-reset token cannot be used to verify an address
    await anon.post("/api/v1/auth/password-reset/request", json={"email": "exp@example.com"})
    assert (await anon.post("/api/v1/auth/verify-email/confirm", json={"token": last_token("password_reset")})).status_code == 400


async def test_verification_resend_is_rate_limited(anon):
    await register(anon, "rl@example.com", verify=False)
    statuses = [(await anon.post("/api/v1/auth/verify-email/request")).status_code for _ in range(4)]
    assert statuses == [202, 202, 202, 429]
    assert len([m for m in ConsoleMailer.outbox if m.kind == "verify_email"]) == 4  # registration + three resends


async def test_password_reset_flow_is_generic_single_use_and_revokes_sessions(client, db):
    async with make_client() as second:
        login = await second.post("/api/v1/auth/login", json={"email": "owner-a@example.com", "password": PASSWORD})
        assert login.status_code == 200
        async with make_client() as visitor:
            unknown = await visitor.post("/api/v1/auth/password-reset/request", json={"email": "nobody@example.com"})
            known = await visitor.post("/api/v1/auth/password-reset/request", json={"email": "OWNER-A@example.com"})
            assert unknown.status_code == known.status_code == 202 and unknown.json() == known.json()  # no account enumeration
            assert [m.to for m in ConsoleMailer.outbox if m.kind == "password_reset"] == ["owner-a@example.com"]
            raw = last_token("password_reset")
            stored = await db.scalar(select(EmailToken).where(EmailToken.purpose == "password_reset"))
            assert dt.timedelta(minutes=29) < stored.expires_at - utcnow() <= dt.timedelta(minutes=30)

            weak = await visitor.post("/api/v1/auth/password-reset/confirm", json={"token": raw, "new_password": "alllowercase"})
            assert weak.status_code == 422
            done = await visitor.post("/api/v1/auth/password-reset/confirm", json={"token": raw, "new_password": NEW_PASSWORD})
            assert done.status_code == 200 and done.json()["status"] == "password_reset"
            replay = await visitor.post("/api/v1/auth/password-reset/confirm", json={"token": raw, "new_password": "An0therPassw0rd"})
            assert replay.status_code == 400 and replay.json()["error"]["code"] == "invalid_token"
            assert (await visitor.post("/api/v1/auth/login", json={"email": "owner-a@example.com", "password": PASSWORD})).status_code == 401
            assert (await visitor.post("/api/v1/auth/login", json={"email": "owner-a@example.com", "password": NEW_PASSWORD})).status_code == 200
        # every session that existed before the reset is revoked
        assert (await second.get("/api/v1/auth/me")).status_code == 401
        assert (await client.get("/api/v1/auth/me")).status_code == 401
    actions = set((await db.scalars(select(AuditLog.action))).all())
    assert {"user.password_reset_requested", "user.password_reset"} <= actions


async def test_password_reset_tokens_expire_and_clear_lockout(client, db):
    async with make_client() as visitor:
        for _ in range(5):
            await visitor.post("/api/v1/auth/login", json={"email": "owner-a@example.com", "password": "Wrong-password1"})
        assert (await visitor.post("/api/v1/auth/login", json={"email": "owner-a@example.com", "password": PASSWORD})).status_code == 423
        await visitor.post("/api/v1/auth/password-reset/request", json={"email": "owner-a@example.com"})
        expired = last_token("password_reset")
        token = await db.scalar(select(EmailToken).where(EmailToken.token_hash == hash_token(expired)))
        token.expires_at = utcnow() - dt.timedelta(minutes=1)
        await db.commit()
        assert (await visitor.post("/api/v1/auth/password-reset/confirm", json={"token": expired, "new_password": NEW_PASSWORD})).status_code == 400
        await visitor.post("/api/v1/auth/password-reset/request", json={"email": "owner-a@example.com"})
        ok = await visitor.post("/api/v1/auth/password-reset/confirm", json={"token": last_token("password_reset"), "new_password": NEW_PASSWORD})
        assert ok.status_code == 200
        assert (await visitor.post("/api/v1/auth/login", json={"email": "owner-a@example.com", "password": NEW_PASSWORD})).status_code == 200  # lock cleared


async def test_password_reset_requests_are_rate_limited_per_address_without_revealing_it(client):
    async with make_client() as visitor:
        bodies = [(await visitor.post("/api/v1/auth/password-reset/request", json={"email": "owner-a@example.com"})) for _ in range(4)]
        assert [b.status_code for b in bodies] == [202] * 4 and len({b.text for b in bodies}) == 1
        assert len([m for m in ConsoleMailer.outbox if m.kind == "password_reset"]) == 3  # the fourth was silently dropped
        assert (await visitor.post("/api/v1/auth/password-reset/request", json={"email": "other@example.com"})).status_code == 202
        limited = await visitor.post("/api/v1/auth/password-reset/request", json={"email": "third@example.com"})
        assert limited.status_code == 429  # per-IP ceiling


async def test_logout_all_revokes_every_session(client):
    async with make_client() as second:
        await second.post("/api/v1/auth/login", json={"email": "owner-a@example.com", "password": PASSWORD})
        assert (await client.post("/api/v1/auth/logout-all")).status_code == 204
        assert (await second.get("/api/v1/auth/me")).status_code == 401 and (await client.get("/api/v1/auth/me")).status_code == 401


async def test_resend_adapter_sends_html_and_text_and_survives_provider_errors():
    settings = Settings(email_provider="resend", resend_api_key="re_test_key", email_from="Signal Atlas <no-reply@mail.example.org>", email_reply_to="help@example.org")
    assert settings.email_delivery_configured
    message = verification_email("user@example.com", "Uma", "https://app.example.org/verify-email?token=abc123abc123abc123abc123", 24)
    with respx.mock(assert_all_called=True) as mock:
        route = mock.post("https://api.resend.com/emails").mock(return_value=Response(200, json={"id": "email_1"}))
        assert await ResendMailer(settings).send(message) == "sent"
    request = route.calls.last.request
    import json
    body = json.loads(request.content)
    assert request.headers["authorization"] == "Bearer re_test_key"
    assert body["from"] == "Signal Atlas <no-reply@mail.example.org>" and body["to"] == ["user@example.com"] and body["reply_to"] == "help@example.org"
    assert "token=abc123" in body["text"] and "token=abc123" in body["html"] and "expires in 24 hours" in body["text"]
    with respx.mock() as mock:
        mock.post("https://api.resend.com/emails").mock(return_value=Response(422, json={"message": "domain not verified"}))
        assert await ResendMailer(settings).send(message) == "failed"  # reported, never raised into the request
    reset = password_reset_email("user@example.com", "https://app.example.org/reset-password?token=zzz", 30)
    assert "expires in 30 minutes" in reset.text and "<script" not in verification_email("u@example.com", "<script>x</script>", "https://a/b", 24).html


async def test_unconfigured_mailer_never_prints_tokens_in_production(capsys):
    token_url = "https://app.example.org/reset-password?token=SUPERSECRETTOKEN1234567890"
    message = password_reset_email("user@example.com", token_url, 30)
    production = Settings(app_env="production", secret_key="p" * 48, allow_self_serve_plan_change=False)
    assert await ConsoleMailer(production).send(message) == "not_configured"
    assert "SUPERSECRETTOKEN" not in capsys.readouterr().out
    development = Settings(app_env="development")
    assert await ConsoleMailer(development).send(message) == "logged_dev"
    assert "SUPERSECRETTOKEN" in capsys.readouterr().out  # local development convenience only


async def test_gate_can_be_disabled_and_reports_missing_delivery(anon, demo_data, settings, monkeypatch, db):
    await register(anon, "gate@example.com", verify=False)
    me = (await anon.get("/api/v1/auth/me")).json()
    assert me["email"] == {"verification_required": True, "delivery_configured": False}
    repo_id = (await anon.get("/api/v1/repositories?page_size=1")).json()["items"][0]["id"]
    blocked = await anon.post("/api/v1/reports/generate", json={"report_type": "repository", "subject_id": repo_id})
    assert blocked.json()["error"]["email_delivery_configured"] is False
    monkeypatch.setattr(settings, "email_verification_required", False)
    assert (await anon.post("/api/v1/reports/generate", json={"report_type": "repository", "subject_id": repo_id})).status_code == 201
    user = await db.scalar(select(User).where(User.email == "gate@example.com"))
    assert user.email_verified_at is None
