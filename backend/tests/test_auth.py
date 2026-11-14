import respx
from httpx import Response
from sqlalchemy import select

from app.config import get_settings
from app.models import AuditLog, GitHubAccount, User, UserSession
from app.security import decrypt_secret
from tests.conftest import PASSWORD, make_client, register


async def test_register_creates_workspace_session_and_default_watchlist(anon):
    data = await register(anon, "New.User@Example.com", "New User", "Acme Research")
    assert data["user"]["email"] == "new.user@example.com"
    assert data["organisation"]["name"] == "Acme Research" and data["role"] == "owner" and data["plan"]["key"] == "free"
    assert "password" not in str(data).lower().replace("has_password", "")
    me = await anon.get("/api/v1/auth/me")
    assert me.status_code == 200 and me.json()["user"]["full_name"] == "New User"
    watchlists = (await anon.get("/api/v1/watchlists")).json()
    assert [w["name"] for w in watchlists["items"]] == ["My watchlist"]


async def test_session_cookie_is_httponly_and_password_is_hashed(anon, db):
    signup = await anon.post("/api/v1/auth/register", json={"email": "c@example.com", "password": PASSWORD, "full_name": "C"})
    assert signup.status_code == 202 and not signup.headers.get_list("set-cookie")  # signing up never creates a session
    resp = await anon.post("/api/v1/auth/login", json={"email": "c@example.com", "password": PASSWORD})
    cookies = resp.headers.get_list("set-cookie")
    session_cookie = next(c for c in cookies if c.startswith("sa_session="))
    assert "HttpOnly" in session_cookie and "SameSite=lax" in session_cookie
    user = await db.scalar(select(User).where(User.email == "c@example.com"))
    assert user.password_hash.startswith("$argon2") and PASSWORD not in user.password_hash
    session = await db.scalar(select(UserSession).where(UserSession.user_id == user.id))
    assert session.token_hash not in session_cookie  # only a hash of the session token is stored


async def test_register_validation(anon):
    weak = await anon.post("/api/v1/auth/register", json={"email": "a@example.com", "password": "alllowercase", "full_name": "A"})
    assert weak.status_code == 422 and weak.json()["error"]["code"] == "validation_error"
    short = await anon.post("/api/v1/auth/register", json={"email": "a@example.com", "password": "Sh0rt", "full_name": "A"})
    assert short.status_code == 422
    bad_email = await anon.post("/api/v1/auth/register", json={"email": "not-an-email", "password": PASSWORD, "full_name": "A"})
    assert bad_email.status_code == 422


async def test_registration_does_not_reveal_whether_an_email_is_registered(client, anon, db):
    """The response for an existing address is identical to a new one; the owner is told by e-mail instead."""
    from app.services.mailer import ConsoleMailer

    ConsoleMailer.outbox.clear()
    fresh = await anon.post("/api/v1/auth/register", json={"email": "brand-new@example.com", "password": PASSWORD, "full_name": "New"})
    taken = await anon.post("/api/v1/auth/register", json={"email": "OWNER-A@example.com", "password": "An0therPassw0rd", "full_name": "Impostor"})
    assert fresh.status_code == taken.status_code == 202 and fresh.json() == taken.json()
    assert not fresh.headers.get_list("set-cookie") and not taken.headers.get_list("set-cookie")
    assert set(fresh.headers) == set(taken.headers)
    kinds = {m.to: m.kind for m in ConsoleMailer.outbox}
    assert kinds == {"brand-new@example.com": "verify_email", "owner-a@example.com": "account_exists"}
    notice = next(m for m in ConsoleMailer.outbox if m.kind == "account_exists")
    assert "token=" not in notice.text and notice.action_url.endswith("/login")
    # the existing account is untouched: old password works, the impostor's does not, no second account exists
    assert (await anon.post("/api/v1/auth/login", json={"email": "owner-a@example.com", "password": "An0therPassw0rd"})).status_code == 401
    assert (await anon.post("/api/v1/auth/login", json={"email": "owner-a@example.com", "password": PASSWORD})).status_code == 200
    assert len((await db.scalars(select(User).where(User.email == "owner-a@example.com"))).all()) == 1
    assert "user.register_existing_email" in set((await db.scalars(select(AuditLog.action))).all())
    # repeated attempts cannot be used to flood the owner's inbox
    for _ in range(4):
        await anon.post("/api/v1/auth/register", json={"email": "owner-a@example.com", "password": PASSWORD, "full_name": "X"})
    assert len([m for m in ConsoleMailer.outbox if m.kind == "account_exists"]) == 3


async def test_hard_gate_makes_sign_up_probing_impossible(anon, settings, monkeypatch):
    """With LOGIN_REQUIRES_VERIFIED_EMAIL, register-then-login gives the same answer for new and existing addresses."""
    from tests.conftest import last_token

    monkeypatch.setattr(settings, "login_requires_verified_email", True)
    await anon.post("/api/v1/auth/register", json={"email": "probe@example.com", "password": PASSWORD, "full_name": "Probe"})
    unverified = await anon.post("/api/v1/auth/login", json={"email": "probe@example.com", "password": PASSWORD})
    wrong = await anon.post("/api/v1/auth/login", json={"email": "probe@example.com", "password": "Wrong-password1"})
    unknown = await anon.post("/api/v1/auth/login", json={"email": "nobody@example.com", "password": PASSWORD})
    assert unverified.status_code == wrong.status_code == unknown.status_code == 401
    assert unverified.json() == wrong.json() == unknown.json()
    assert "not been confirmed" in unverified.json()["error"]["message"]
    resend = await anon.post("/api/v1/auth/verify-email/resend", json={"email": "probe@example.com"})
    ghost = await anon.post("/api/v1/auth/verify-email/resend", json={"email": "nobody@example.com"})
    assert resend.status_code == ghost.status_code == 202 and resend.json() == ghost.json()
    assert (await anon.post("/api/v1/auth/verify-email/confirm", json={"token": last_token("verify_email", "probe@example.com")})).status_code == 200
    assert (await anon.post("/api/v1/auth/login", json={"email": "probe@example.com", "password": PASSWORD})).status_code == 200


async def test_login_logout_cycle(client):
    async with make_client() as fresh:
        bad = await fresh.post("/api/v1/auth/login", json={"email": "owner-a@example.com", "password": "Wrong-password1"})
        assert bad.status_code == 401 and bad.json()["error"]["code"] == "invalid_credentials"
        unknown = await fresh.post("/api/v1/auth/login", json={"email": "nobody@example.com", "password": PASSWORD})
        assert unknown.status_code == 401 and unknown.json() == bad.json()  # no user enumeration
        ok = await fresh.post("/api/v1/auth/login", json={"email": "owner-a@example.com", "password": PASSWORD})
        assert ok.status_code == 200
        fresh.csrf = ok.json()["csrf_token"]
        assert (await fresh.get("/api/v1/auth/me")).status_code == 200
        assert (await fresh.post("/api/v1/auth/logout")).status_code == 204
        fresh.cookies.set("sa_session", ok.cookies.get("sa_session"))  # replaying the old cookie must fail
        assert (await fresh.get("/api/v1/auth/me")).status_code == 401


async def test_account_locks_after_repeated_failures(client, db):
    async with make_client() as fresh:
        for _ in range(5):
            resp = await fresh.post("/api/v1/auth/login", json={"email": "owner-a@example.com", "password": "Wrong-password1"})
            assert resp.status_code == 401
        locked = await fresh.post("/api/v1/auth/login", json={"email": "owner-a@example.com", "password": PASSWORD})
        assert locked.status_code == 423
    failures = (await db.scalars(select(AuditLog).where(AuditLog.action == "user.login_failed"))).all()
    assert len(failures) == 5


async def test_unauthenticated_requests_rejected(anon):
    for path in ("/api/v1/dashboard", "/api/v1/repositories", "/api/v1/opportunities", "/api/v1/watchlists", "/api/v1/auth/me", "/api/v1/api-keys"):
        resp = await anon.get(path)
        assert resp.status_code == 401, path
        assert resp.json()["error"]["code"] == "not_authenticated"


async def test_csrf_token_required_for_state_changes(client):
    csrf, client.csrf = client.csrf, None
    missing = await client.post("/api/v1/watchlists", json={"name": "No CSRF"})
    assert missing.status_code == 403 and missing.json()["error"]["code"] == "csrf_failed"
    wrong = await client.post("/api/v1/watchlists", json={"name": "Bad CSRF"}, headers={"X-CSRF-Token": "forged"})
    assert wrong.status_code == 403
    client.csrf = csrf
    assert (await client.post("/api/v1/watchlists", json={"name": "With CSRF"})).status_code == 201


async def test_profile_update_and_password_change_revokes_other_sessions(client):
    updated = await client.patch("/api/v1/auth/me", json={"full_name": "Alice Renamed", "job_title": "Analyst"})
    assert updated.json()["user"]["full_name"] == "Alice Renamed" and updated.json()["user"]["job_title"] == "Analyst"
    async with make_client() as second:
        login = await second.post("/api/v1/auth/login", json={"email": "owner-a@example.com", "password": PASSWORD})
        second.csrf = login.json()["csrf_token"]
        wrong = await client.post("/api/v1/auth/change-password", json={"current_password": "nope", "new_password": "An0therStrongPass"})
        assert wrong.status_code == 400
        changed = await client.post("/api/v1/auth/change-password", json={"current_password": PASSWORD, "new_password": "An0therStrongPass"})
        assert changed.status_code == 204
        assert (await second.get("/api/v1/auth/me")).status_code == 401  # other session revoked
        assert (await client.get("/api/v1/auth/me")).status_code == 200  # current session kept
    async with make_client() as third:
        assert (await third.post("/api/v1/auth/login", json={"email": "owner-a@example.com", "password": PASSWORD})).status_code == 401
        assert (await third.post("/api/v1/auth/login", json={"email": "owner-a@example.com", "password": "An0therStrongPass"})).status_code == 200


async def test_github_oauth_reports_setup_requirement_when_unconfigured(client):
    resp = await client.get("/api/v1/auth/github/start")
    assert resp.status_code == 503 and resp.json()["error"]["code"] == "github_oauth_not_configured"
    assert (await client.get("/api/v1/auth/me")).json()["github"] == {"connected": False, "login": None, "avatar_url": None, "scopes": None, "oauth_configured": False}


async def test_github_oauth_connect_flow_stores_encrypted_read_only_token(client, db, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "github_oauth_client_id", "client-id")
    monkeypatch.setattr(settings, "github_oauth_client_secret", "client-secret")
    start = await client.get("/api/v1/auth/github/start?mode=connect")
    assert start.status_code == 302
    location = start.headers["location"]
    assert location.startswith("https://github.com/login/oauth/authorize?") and "scope=read%3Auser+user%3Aemail" in location
    assert "repo" not in location.split("scope=")[1].split("&")[0]  # never requests repository scopes
    state = location.split("state=")[1].split("&")[0]

    forged = await client.get("/api/v1/auth/github/callback?code=abc&state=forged")
    assert forged.status_code == 302 and "github_state_mismatch" in forged.headers["location"]

    start = await client.get("/api/v1/auth/github/start?mode=connect")
    state = start.headers["location"].split("state=")[1].split("&")[0]
    token = "gho_" + "t0Ken" * 7
    with respx.mock(assert_all_called=True) as mock:
        mock.post("https://github.com/login/oauth/access_token").mock(return_value=Response(200, json={"access_token": token, "scope": "read:user,user:email"}))
        mock.get("https://api.github.com/user").mock(return_value=Response(200, json={"id": 4242, "login": "octo-alice", "avatar_url": "https://avatars.example/1"}))
        mock.get("https://api.github.com/user/emails").mock(return_value=Response(200, json=[{"email": "a@example.com", "primary": True, "verified": True}]))
        callback = await client.get(f"/api/v1/auth/github/callback?code=abc&state={state}")
    assert callback.status_code == 302 and callback.headers["location"].endswith("/settings?github=connected")

    account = await db.scalar(select(GitHubAccount))
    assert account.login == "octo-alice" and token not in account.access_token_encrypted
    assert decrypt_secret(account.access_token_encrypted) == token
    me = await client.get("/api/v1/auth/me")
    assert me.json()["github"]["connected"] is True and me.json()["github"]["login"] == "octo-alice"
    assert token not in me.text  # the token is never serialised to the browser

    with respx.mock(assert_all_called=True) as mock:  # disconnect revokes the grant at GitHub (best effort)
        mock.delete("https://api.github.com/applications/client-id/grant").mock(return_value=Response(204))
        assert (await client.delete("/api/v1/auth/github")).status_code == 204
    assert (await client.get("/api/v1/auth/me")).json()["github"]["connected"] is False
