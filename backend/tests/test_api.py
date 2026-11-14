"""API tests over the demonstration fixtures (clearly labelled fictional data)."""

from sqlalchemy import select

from app.models import Repository


async def test_dashboard_empty_state_never_invents_numbers(client):
    data = (await client.get("/api/v1/dashboard")).json()
    assert data["provenance"]["mode"] == "empty"
    assert set(data["summary"].values()) == {0}
    assert data["signals"] == [] and data["top_opportunities"] == []


async def test_dashboard_labels_demo_data(client, demo_data):
    data = (await client.get("/api/v1/dashboard")).json()
    assert data["provenance"]["mode"] == "demo" and "fictional" in data["provenance"]["message"]
    assert data["summary"]["repositories_monitored"] == demo_data["repositories"] == data["provenance"]["demo_repositories"]
    assert data["provenance"]["live_repositories"] == 0
    assert data["summary"]["opportunities_discovered"] > 0 and data["summary"]["developers_analysed"] == 36
    assert all(s["data_source"] == "demo_fixture" for s in data["signals"])
    assert all(o["data_source"] == "demo_fixture" for o in data["top_opportunities"])
    scores = [o["score"] for o in data["top_opportunities"]]
    assert scores == sorted(scores, reverse=True)


async def test_live_source_hides_demo_fixtures(client, demo_data):
    live = (await client.get("/api/v1/repositories?source=live")).json()
    assert live["total"] == 0
    demo = (await client.get("/api/v1/repositories?source=demo")).json()
    assert demo["total"] == 27 and all(item["data_source"] == "demo_fixture" and item["html_url"] is None for item in demo["items"])


async def test_repository_search_filters_and_sorting(client, demo_data):
    by_category = (await client.get("/api/v1/repositories?category=cybersecurity")).json()
    assert by_category["total"] == 3 and {i["category"] for i in by_category["items"]} == {"cybersecurity"}
    rust = (await client.get("/api/v1/repositories?language=rust&sort=stars")).json()
    stars = [i["stars"] for i in rust["items"]]
    assert stars == sorted(stars, reverse=True) and all(i["primary_language"] == "Rust" for i in rust["items"])
    search = (await client.get("/api/v1/repositories?q=vector")).json()
    assert [i["full_name"] for i in search["items"]] == ["demo-labs/vectorloom"]
    no_licence = (await client.get("/api/v1/repositories?license=none")).json()
    assert [i["full_name"] for i in no_licence["items"]] == ["demo-biz/cartwright"]
    by_tech = (await client.get("/api/v1/repositories?technology=ai-agents")).json()
    assert {"demo-labs/lumen-agents", "demo-auto/crawlkit"} <= {i["full_name"] for i in by_tech["items"]}
    by_score = (await client.get("/api/v1/repositories?sort=score&page_size=5")).json()
    scores = [i["score"] for i in by_score["items"]]
    assert len(scores) == 5 and scores == sorted(scores, reverse=True)
    page2 = (await client.get("/api/v1/repositories?page=2&page_size=10")).json()
    assert len(page2["items"]) == 10 and page2["page"] == 2
    assert (await client.get("/api/v1/repositories?page_size=1000")).status_code == 422


async def test_like_wildcards_in_search_are_escaped(client, demo_data):
    assert (await client.get("/api/v1/repositories", params={"q": "%"})).json()["total"] == 0
    assert (await client.get("/api/v1/repositories", params={"q": "_"})).json()["total"] == 0
    injection = await client.get("/api/v1/repositories", params={"q": "'; DROP TABLE repositories; --"})
    assert injection.status_code == 200 and injection.json()["total"] == 0
    assert (await client.get("/api/v1/repositories")).json()["total"] == 27


async def test_facets(client, demo_data):
    facets = (await client.get("/api/v1/repositories/facets")).json()
    assert len(facets["categories"]) == 9 and all(c["count"] == 3 for c in facets["categories"])
    assert {"value": "Go", "count": 9} in facets["languages"]


async def test_repository_detail_sections(client, demo_data, db):
    repo = await db.scalar(select(Repository).where(Repository.full_name == "demo-labs/lumen-agents"))
    detail = (await client.get(f"/api/v1/repositories/{repo.id}")).json()
    assert detail["provenance"]["is_demo"] is True and detail["repository"]["full_name"] == "demo-labs/lumen-agents"
    assert detail["category_label"] == "AI & Machine Learning"
    assert all(t["basis"] == "inferred" for t in detail["technologies"]) and "llm" in {t["slug"] for t in detail["technologies"]}
    assert detail["licence"]["spdx"] == "MIT" and "not legal advice" in detail["licence"]["note"]
    assert detail["score"]["total"] > 0 and len(detail["score"]["metrics"]) == 7

    activity = (await client.get(f"/api/v1/repositories/{repo.id}/activity")).json()
    assert len(activity["commit_activity"]) == 26 and len(activity["snapshots"]) == 36
    contributors = (await client.get(f"/api/v1/repositories/{repo.id}/contributors")).json()
    assert contributors["contributors"] and 0 < contributors["top_contributor_share"] <= 1
    deps = (await client.get(f"/api/v1/repositories/{repo.id}/dependencies")).json()
    assert deps["analysed"] is True and all(d["ecosystem"] == "pypi" for d in deps["dependencies"])
    forks = (await client.get(f"/api/v1/repositories/{repo.id}/forks")).json()
    assert forks["forks"] and forks["is_fork"] is False
    releases = (await client.get(f"/api/v1/repositories/{repo.id}/releases")).json()
    assert len(releases["releases"]) >= 5
    score = (await client.get(f"/api/v1/repositories/{repo.id}/score")).json()
    assert score["history"] and score["weights"]["commercial_potential"] == 20

    assert (await client.get("/api/v1/repositories/999999")).status_code == 404
    sync = await client.post(f"/api/v1/repositories/{repo.id}/sync")
    assert sync.status_code == 400 and sync.json()["error"]["code"] == "demo_fixture"  # fixtures are never synced with GitHub


async def test_developers_distinguish_public_data_from_inference(client, demo_data):
    listing = (await client.get("/api/v1/developers?page_size=5")).json()
    assert listing["total"] == 36 and listing["items"][0]["tracked_contributions"] >= listing["items"][-1]["tracked_contributions"]
    dev_id = listing["items"][0]["id"]
    profile = (await client.get(f"/api/v1/developers/{dev_id}")).json()
    assert profile["public_profile"]["basis"] == "public_data"
    assert profile["inferred"]["basis"] == "inferred_analysis" and profile["collaboration_network"]["basis"] == "inferred_analysis"
    assert "not a measure of technical ability" in profile["influence_indicators"]["disclaimer"]
    assert "email" not in profile["public_profile"]["developer"]
    assert profile["contribution_activity"]["repositories"]
    assert (await client.get("/api/v1/developers/999999")).status_code == 404
    assert (await client.get("/api/v1/developers?q=demo-dev-07")).json()["total"] == 1


async def test_trends_windows_and_evidence(client, demo_data):
    trends = (await client.get("/api/v1/trends")).json()
    types = {s["signal_type"] for s in trends["items"]}
    assert {"star_surge", "breakout_new_project", "commit_acceleration"} <= types or {"unusual_growth", "breakout_new_project", "commit_acceleration"} <= types
    assert set(trends["counts_by_window"]) == {"daily", "weekly", "monthly"} and trends["counts_by_window"]["weekly"] > 0
    for signal in trends["items"]:
        assert signal["evidence"] and signal["confidence"] in ("low", "medium", "high") and signal["data_source"] == "demo_fixture"
        assert 0 <= signal["strength"] <= 100
    weekly = (await client.get("/api/v1/trends?window=weekly")).json()
    assert weekly["items"] and all(s["time_window"] == "weekly" for s in weekly["items"])
    surging = (await client.get("/api/v1/trends?signal_type=breakout_new_project")).json()
    assert {s["repository_full_name"] for s in surging["items"]} == {"demo-ai/promptforge", "demo-auto/crawlkit"}
    assert (await client.get("/api/v1/trends?window=yearly")).status_code == 422


async def test_momentum_series(client, demo_data):
    data = (await client.get("/api/v1/trends/momentum")).json()
    assert len(data["categories"]) == 9
    assert len(data["developer_activity"]["series"]) >= 20
    growth = data["repository_growth"]
    assert growth["has_history"] and growth["cohort_size"] == 27
    assert all(value == 0 for key, value in growth["series"][0].items() if key != "date")  # indexed to the first day
    assert sum(c["repositories"] for c in data["technology_adoption"]) == 27


async def test_opportunities_ranked_with_labelled_hypotheses(client, demo_data):
    listing = (await client.get("/api/v1/opportunities")).json()
    scores = [o["score"] for o in listing["items"]]
    assert listing["total"] >= 20 and scores == sorted(scores, reverse=True)
    assert all(len(o["metrics"]) == 7 for o in listing["items"])
    filtered = (await client.get("/api/v1/opportunities?category=fintech&min_score=1")).json()
    assert filtered["items"] and all(o["category"] == "fintech" for o in filtered["items"])
    low_risk = (await client.get("/api/v1/opportunities?risk=low")).json()
    assert all(o["risk_level"] == "low" for o in low_risk["items"])

    detail = (await client.get(f"/api/v1/opportunities/{listing['items'][0]['id']}")).json()
    analysis = detail["analysis"]
    assert detail["validation_status"] == "unvalidated"
    assert all(item["basis"] == "hypothesis" for item in analysis["target_customers"] + analysis["monetisation"] + analysis["commercial_applications"])
    assert any(item["basis"] == "verified_fact" for item in analysis["demand_indicators"])
    assert analysis["recommended_action"]["key"] in ("investigate", "monitor", "deprioritise")
    assert "not evidence of commercial demand" in analysis["disclaimer"]
    assert analysis["licensing_risks"] and analysis["recommended_next_steps"]
    assert (await client.get("/api/v1/opportunities/999999")).status_code == 404


async def test_source_available_licence_is_flagged_high_risk(client, demo_data, db):
    repo = await db.scalar(select(Repository).where(Repository.full_name == "demo-auto/flowmill"))
    opportunity_id = (await client.get(f"/api/v1/repositories/{repo.id}")).json()["opportunity_id"]
    analysis = (await client.get(f"/api/v1/opportunities/{opportunity_id}")).json()["analysis"]
    assert analysis["licensing_risks"][0]["severity"] == "high" and "source-available" in analysis["licensing_risks"][0]["text"]


async def test_technologies_ecosystem_and_search(client, demo_data):
    techs = (await client.get("/api/v1/technologies")).json()
    by_slug = {t["slug"]: t for t in techs["items"]}
    assert by_slug["ai-agents"]["repositories"] >= 2 and by_slug["ai-agents"]["frontier"] is True
    detail = (await client.get("/api/v1/technologies/databases")).json()
    assert "demo-data/tidepool-db" in {r["full_name"] for r in detail["top_repositories"]}
    assert (await client.get("/api/v1/technologies/nope")).status_code == 404

    graph = (await client.get("/api/v1/ecosystem/graph?limit=27")).json()
    kinds = {n["type"] for n in graph["nodes"]}
    assert {"repository", "technology", "company", "developer", "dependency"} <= kinds
    ids = {n["id"] for n in graph["nodes"]}
    assert all(e["source"] in ids and e["target"] in ids for e in graph["edges"])

    found = (await client.get("/api/v1/search?q=lumen")).json()
    assert found["repositories"][0]["title"] == "demo-labs/lumen-agents" and found["opportunities"]
    assert (await client.get("/api/v1/search?q=a")).status_code == 422


async def test_demo_fixtures_can_be_cleared(client, demo_data):
    removed = (await client.delete("/api/v1/system/demo")).json()
    assert removed["removed_repositories"] == 27
    data = (await client.get("/api/v1/dashboard")).json()
    assert data["provenance"]["mode"] == "empty" and data["summary"]["developers_analysed"] == 0
    assert (await client.get("/api/v1/trends")).json()["items"] == []


async def test_health_and_openapi(anon):
    assert (await anon.get("/health")).json()["status"] == "ok"
    assert (await anon.get("/health/ready")).json() == {"status": "ready", "database": True, "rate_limiting": {"backend": "memory", "healthy": True, "shared": False}}
    spec = (await anon.get("/api/openapi.json")).json()
    for path in ("/api/v1/repositories", "/api/v1/repositories/{repository_id}", "/api/v1/developers", "/api/v1/developers/{developer_id}", "/api/v1/trends",
                 "/api/v1/opportunities", "/api/v1/opportunities/{opportunity_id}", "/api/v1/reports/generate", "/api/v1/competitors", "/api/v1/watchlists", "/api/v1/dashboard"):
        assert path in spec["paths"], path
    resp = await anon.get("/health")
    assert resp.headers["x-content-type-options"] == "nosniff" and resp.headers["x-frame-options"] == "DENY" and resp.headers["x-request-id"]
