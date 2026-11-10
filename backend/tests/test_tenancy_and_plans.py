"""Tenant isolation, role checks, watchlists, competitors, API keys, entitlements and usage metering."""

from sqlalchemy import select

from app.models import ApiKey, Membership, Notification, Opportunity, Repository, User
from app.security import hash_password
from tests.conftest import PASSWORD, make_client


async def _repo_id(db, name="demo-labs/lumen-agents") -> int:
    return await db.scalar(select(Repository.id).where(Repository.full_name == name))


async def test_watchlists_are_isolated_between_organisations(client, other_client, demo_data, db):
    repo_id = await _repo_id(db)
    watchlist_id = (await client.get("/api/v1/watchlists")).json()["items"][0]["id"]
    saved = await client.post(f"/api/v1/watchlists/{watchlist_id}/items", json={"item_type": "repository", "item_id": repo_id, "note": "confidential thesis"})
    assert saved.status_code == 201 and saved.json()["created"] is True
    again = await client.post(f"/api/v1/watchlists/{watchlist_id}/items", json={"item_type": "repository", "item_id": repo_id})
    assert again.json()["created"] is False  # idempotent

    mine = (await client.get("/api/v1/watchlists")).json()
    assert mine["used"] == 1 and mine["items"][0]["items"][0]["title"] == "demo-labs/lumen-agents"
    assert (await client.get("/api/v1/watchlists/saved?item_type=repository")).json()["saved"].keys() == {str(repo_id)}

    theirs = (await other_client.get("/api/v1/watchlists")).json()
    assert theirs["used"] == 0 and "confidential thesis" not in str(theirs)
    assert (await other_client.get("/api/v1/watchlists/saved?item_type=repository")).json()["saved"] == {}
    # Org B cannot write to, or delete, Org A's watchlist - and gets 404 rather than a hint that it exists
    assert (await other_client.post(f"/api/v1/watchlists/{watchlist_id}/items", json={"item_type": "repository", "item_id": repo_id})).status_code == 404
    assert (await other_client.delete(f"/api/v1/watchlists/{watchlist_id}")).status_code == 404
    item_id = mine["items"][0]["items"][0]["id"]
    assert (await other_client.delete(f"/api/v1/watchlists/{watchlist_id}/items/{item_id}")).status_code == 404
    assert (await client.get("/api/v1/watchlists")).json()["used"] == 1

    assert (await client.delete(f"/api/v1/watchlists/{watchlist_id}/items/{item_id}")).status_code == 204
    assert (await client.get("/api/v1/watchlists")).json()["used"] == 0


async def test_save_opportunity_and_developer(client, demo_data, db):
    watchlist_id = (await client.get("/api/v1/watchlists")).json()["items"][0]["id"]
    opportunity_id = await db.scalar(select(Opportunity.id).limit(1))
    developer_id = (await client.get("/api/v1/developers?page_size=1")).json()["items"][0]["id"]
    for item_type, item_id in (("opportunity", opportunity_id), ("developer", developer_id)):
        assert (await client.post(f"/api/v1/watchlists/{watchlist_id}/items", json={"item_type": item_type, "item_id": item_id})).status_code == 201
    items = (await client.get("/api/v1/watchlists")).json()["items"][0]["items"]
    assert {i["item_type"] for i in items} == {"opportunity", "developer"} and all(i["available"] and i["link"] for i in items)
    assert (await client.post(f"/api/v1/watchlists/{watchlist_id}/items", json={"item_type": "repository", "item_id": 999999})).status_code == 404
    assert (await client.post(f"/api/v1/watchlists/{watchlist_id}/items", json={"item_type": "planet", "item_id": 1})).status_code == 422


async def test_competitors_are_isolated_and_limited_by_plan(client, other_client, demo_data, db):
    repo_id = await _repo_id(db, "demo-dev/tracepilot")
    created = await client.post("/api/v1/competitors", json={"name": "TracePilot Inc", "website": "https://example.com", "repository_ids": [repo_id]})
    assert created.status_code == 201
    competitor_id = created.json()["id"]

    listing = (await client.get("/api/v1/competitors")).json()
    assert listing["used"] == 1 and listing["limit"] == 1 and listing["items"][0]["repository_count"] == 1
    detail = (await client.get(f"/api/v1/competitors/{competitor_id}")).json()
    assert detail["comparison"][0]["full_name"] == "demo-dev/tracepilot" and detail["comparison"][0]["stars_30d_change"] > 0
    assert detail["changes"] and detail["changes"][0]["event_type"] == "release"

    # the free plan allows one competitor: the second attempt returns a structured upgrade prompt
    limited = await client.post("/api/v1/competitors", json={"name": "Second"})
    assert limited.status_code == 402
    error = limited.json()["error"]
    assert error["code"] == "upgrade_required" and error["current_plan"] == "free" and error["suggested_plan"] == "pro" and error["limit"] == 1

    assert (await other_client.get("/api/v1/competitors")).json()["items"] == []
    for call in (other_client.get(f"/api/v1/competitors/{competitor_id}"), other_client.patch(f"/api/v1/competitors/{competitor_id}", json={"name": "Hijacked"}),
                 other_client.delete(f"/api/v1/competitors/{competitor_id}"),
                 other_client.post(f"/api/v1/competitors/{competitor_id}/repositories", json={"repository_id": repo_id})):
        assert (await call).status_code == 404
    hijack = await other_client.post("/api/v1/reports/generate", json={"report_type": "competitor", "subject_id": competitor_id})
    assert hijack.status_code == 404  # cannot generate a report about another tenant's competitor

    bad_url = await client.post("/api/v1/competitors", json={"name": "X", "website": "javascript:alert(1)"})
    assert bad_url.status_code == 422
    assert (await client.delete(f"/api/v1/competitors/{competitor_id}")).status_code == 204
    assert (await client.get("/api/v1/competitors")).json()["used"] == 0


async def test_reports_are_isolated_between_organisations(client, other_client, demo_data, db):
    report = (await client.post("/api/v1/reports/generate", json={"report_type": "repository", "subject_id": await _repo_id(db)})).json()
    assert (await client.get(f"/api/v1/reports/{report['id']}")).status_code == 200
    assert (await other_client.get(f"/api/v1/reports/{report['id']}")).status_code == 404
    assert (await other_client.delete(f"/api/v1/reports/{report['id']}")).status_code == 404
    assert (await other_client.get("/api/v1/reports")).json()["total"] == 0
    assert (await client.get("/api/v1/reports")).json()["total"] == 1


async def test_notifications_are_isolated(client, other_client, db):
    db.add(Notification(organisation_id=client.me["organisation"]["id"], kind="release", title="Private to org A", link="/repositories/1"))
    await db.commit()
    mine = (await client.get("/api/v1/notifications")).json()
    assert mine["unread"] == 1 and mine["items"][0]["title"] == "Private to org A"
    assert (await other_client.get("/api/v1/notifications")).json() == {"items": [], "unread": 0}
    assert (await other_client.post(f"/api/v1/notifications/{mine['items'][0]['id']}/read")).status_code == 404
    assert (await client.post("/api/v1/notifications/read-all")).status_code == 204
    assert (await client.get("/api/v1/notifications")).json()["unread"] == 0


async def test_viewer_role_is_read_only(client, demo_data, db):
    viewer = User(email="viewer@example.com", password_hash=hash_password(PASSWORD), full_name="Vera Viewer")
    db.add(viewer)
    await db.flush()
    db.add(Membership(user_id=viewer.id, organisation_id=client.me["organisation"]["id"], role="viewer"))
    await db.commit()
    async with make_client() as v:
        login = await v.post("/api/v1/auth/login", json={"email": "viewer@example.com", "password": PASSWORD})
        v.csrf = login.json()["csrf_token"]
        assert login.json()["role"] == "viewer"
        assert (await v.get("/api/v1/opportunities")).status_code == 200
        for call in (v.post("/api/v1/watchlists", json={"name": "Nope"}), v.post("/api/v1/competitors", json={"name": "Nope"}),
                     v.post("/api/v1/reports/generate", json={"report_type": "repository", "subject_id": 1}),
                     v.post("/api/v1/api-keys", json={"name": "Nope"}), v.put("/api/v1/settings/scoring", json={"weights": {}}),
                     v.post("/api/v1/billing/checkout", json={"plan": "pro"}), v.post("/api/v1/system/demo/load")):
            resp = await call
            assert resp.status_code == 403 and resp.json()["error"]["code"] == "insufficient_role"


async def test_api_keys_require_paid_plan_then_authenticate_and_meter_usage(client, other_client, demo_data, db):
    denied = await client.post("/api/v1/api-keys", json={"name": "CI"})
    assert denied.status_code == 402 and denied.json()["error"]["feature"] == "api_access"
    assert (await client.post("/api/v1/billing/checkout", json={"plan": "pro"})).json()["status"] == "changed"

    created = (await client.post("/api/v1/api-keys", json={"name": "CI"})).json()
    key = created["key"]
    assert key.startswith("sa_live_") and created["prefix"] in key
    stored = await db.scalar(select(ApiKey))
    assert key not in (stored.key_hash, stored.prefix) and len(stored.key_hash) == 64  # only a hash is stored
    listing = (await client.get("/api/v1/api-keys")).json()
    assert "key" not in listing["items"][0] and listing["items"][0]["prefix"] == created["prefix"]

    async with make_client() as api:
        ok = await api.get("/api/v1/opportunities?page_size=2", headers={"X-API-Key": key})
        assert ok.status_code == 200 and len(ok.json()["items"]) == 2
        bearer = await api.get("/api/v1/dashboard", headers={"Authorization": f"Bearer {key}"})
        assert bearer.status_code == 200
        assert (await api.get("/api/v1/dashboard", headers={"X-API-Key": "sa_live_deadbeef_invalid"})).status_code == 401
        # read-only keys cannot change state, and never reach account management
        assert (await api.post("/api/v1/watchlists", json={"name": "x"}, headers={"X-API-Key": key})).json()["error"]["code"] == "read_only_key"
        assert (await api.get("/api/v1/api-keys", headers={"X-API-Key": key})).json()["error"]["code"] == "session_required"
        assert (await api.get("/api/v1/auth/me", headers={"X-API-Key": key})).status_code == 403
    assert (await client.get("/api/v1/api-keys")).json()["requests_this_month"] == 4  # accepted key requests are metered; the rejected write is not

    # tenant isolation for keys
    assert (await other_client.delete(f"/api/v1/api-keys/{created['id']}")).status_code in (403, 404)
    assert (await client.delete(f"/api/v1/api-keys/{created['id']}")).status_code == 204
    async with make_client() as api:
        assert (await api.get("/api/v1/dashboard", headers={"X-API-Key": key})).status_code == 401  # revoked


async def test_api_key_rate_limit(client, demo_data):
    await client.post("/api/v1/billing/checkout", json={"plan": "pro"})
    key = (await client.post("/api/v1/api-keys", json={"name": "burst"})).json()["key"]
    async with make_client() as api:
        statuses = [(await api.get("/health/ready")).status_code]  # unauthenticated endpoint is unaffected
        for _ in range(61):
            statuses.append((await api.get("/api/v1/billing/plans", headers={"X-API-Key": key})).status_code)
        limited = [(await api.get("/api/v1/trends", headers={"X-API-Key": key})) for _ in range(62)]
    assert limited[59].status_code == 200 and limited[60].status_code == 429
    assert limited[60].headers["retry-after"] and limited[60].json()["error"]["code"] == "rate_limited"


async def test_custom_scoring_weights_gated_and_applied(client, other_client, demo_data, db):
    gated = await client.put("/api/v1/settings/scoring", json={"weights": {}})
    assert gated.status_code == 402 and gated.json()["error"]["feature"] == "custom_scoring_weights"
    await client.post("/api/v1/billing/checkout", json={"plan": "professional"})
    invalid = await client.put("/api/v1/settings/scoring", json={"weights": {"development_momentum": 100}})
    assert invalid.status_code == 422 and invalid.json()["error"]["code"] == "invalid_weights"

    repo_id = await _repo_id(db)
    before = (await client.get(f"/api/v1/repositories/{repo_id}/score")).json()
    weights = dict.fromkeys(before["weights"], 0) | {"developer_adoption": 100}
    assert (await client.put("/api/v1/settings/scoring", json={"weights": weights})).status_code == 200
    after = (await client.get(f"/api/v1/repositories/{repo_id}/score")).json()
    adoption = next(m["score"] for m in after["metrics"] if m["key"] == "developer_adoption")
    assert after["custom_weights"] is True and after["total"] == adoption and after["default_total"] == before["total"]
    assert [m["score"] for m in after["metrics"]] == [m["score"] for m in before["metrics"]]  # evidence unchanged, only weighting

    # another organisation still sees default weighting
    theirs = (await other_client.get(f"/api/v1/repositories/{repo_id}/score")).json()
    assert theirs["custom_weights"] is False and theirs["total"] == before["total"]
    assert (await client.delete("/api/v1/settings/scoring")).status_code == 204
    assert (await client.get(f"/api/v1/repositories/{repo_id}/score")).json()["total"] == before["total"]


async def test_billing_is_not_live_and_usage_is_reported(client, anon, settings, monkeypatch):
    plans = (await anon.get("/api/v1/billing/plans")).json()
    assert [(p["key"], p["price_gbp_month"]) for p in plans["plans"]] == [("free", 0), ("pro", 19), ("professional", 49), ("business", 149), ("enterprise", None)]
    assert plans["payments_live"] is False
    sub = (await client.get("/api/v1/billing/subscription")).json()
    assert sub["plan"]["key"] == "free" and sub["billing"]["payments_live"] is False
    assert {u["key"] for u in sub["usage"]} == {"reports", "live_syncs", "api_requests", "watchlist_items", "competitors"}
    monkeypatch.setattr(settings, "allow_self_serve_plan_change", False)
    blocked = await client.post("/api/v1/billing/checkout", json={"plan": "pro"})
    assert blocked.status_code == 501 and blocked.json()["error"]["code"] == "billing_not_configured"
    assert (await client.post("/api/v1/billing/checkout", json={"plan": "enterprise"})).status_code == 422


async def test_platform_tools_restricted_in_production(client, settings, monkeypatch):
    monkeypatch.setattr(settings, "app_env", "production")
    assert (await client.post("/api/v1/system/demo/load")).json()["error"]["code"] == "platform_admin_required"
    monkeypatch.setattr(settings, "platform_admin_emails", "owner-a@example.com")
    assert (await client.get("/api/v1/system/status")).status_code == 200


async def test_settings_report_integration_setup_requirements(client):
    data = (await client.get("/api/v1/settings/organisation")).json()
    integrations = {i["key"]: i for i in data["integrations"]}
    assert all(not i["configured"] for i in integrations.values())
    assert integrations["github_oauth"]["env"] == ["GITHUB_OAUTH_CLIENT_ID", "GITHUB_OAUTH_CLIENT_SECRET"] and "never repository write" in integrations["github_oauth"]["detail"]
    assert data["members"] == [{"id": client.me["user"]["id"], "email": "owner-a@example.com", "full_name": "Alice Owner", "role": "owner"}]
    audit = (await client.get("/api/v1/settings/audit-log")).json()
    assert "user.registered" in {a["action"] for a in audit["items"]}
