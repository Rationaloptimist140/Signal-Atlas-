"""GitHub ingestion (mocked HTTP), change detection, rate limits and the job queue."""

import datetime as dt
import time

import pytest
import respx
from httpx import Response
from sqlalchemy import func, select

from app.models import (
    ChangeEvent,
    CommitActivity,
    Contributor,
    Dependency,
    DeveloperProfile,
    ForkRelationship,
    Job,
    Notification,
    Opportunity,
    OpportunityScore,
    Release,
    Repository,
    RepositoryLanguage,
    RepositorySnapshot,
    TrendSignal,
    utcnow,
)
from app.services import ingestion, intelligence, jobs, trends
from app.services.github_client import GitHubClient, GitHubRateLimited

API = "https://api.github.com"
NOW = utcnow()


def iso(days_ago: int) -> str:
    return (NOW - dt.timedelta(days=days_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")


def repo_payload(**overrides) -> dict:
    data = {
        "id": 9001, "full_name": "acme/rocket", "name": "rocket", "owner": {"login": "acme", "type": "Organization"},
        "description": "Workflow automation engine for platform teams", "html_url": "https://github.com/acme/rocket", "homepage": "https://rocket.example",
        "language": "Python", "license": {"spdx_id": "Apache-2.0", "name": "Apache License 2.0"}, "topics": ["workflow-automation", "self-hosted"],
        "stargazers_count": 4200, "forks_count": 310, "subscribers_count": 88, "open_issues_count": 57, "size": 2048, "fork": False, "archived": False,
        "default_branch": "main", "created_at": iso(400), "pushed_at": iso(1), "updated_at": iso(0),
    }
    data.update(overrides)
    return data


def mock_full_sync(mock, *, releases, package_json, etag='"v1"', repo=None, commit_status=200):
    mock.get(f"{API}/repos/acme/rocket").mock(return_value=Response(200, json=repo or repo_payload(), headers={"etag": etag}))
    mock.get(f"{API}/repos/acme/rocket/languages").mock(return_value=Response(200, json={"Python": 90000, "Shell": 1000}))
    contributors = [{"login": "alice", "id": 1, "type": "User", "contributions": 300, "avatar_url": "https://a/1", "html_url": "https://github.com/alice"},
                    {"login": "bob", "id": 2, "type": "User", "contributions": 100},
                    {"login": "dependabot[bot]", "id": 3, "type": "Bot", "contributions": 500}]
    mock.get(f"{API}/repos/acme/rocket/contributors", params={"per_page": "30"}).mock(return_value=Response(200, json=contributors))
    mock.get(f"{API}/repos/acme/rocket/contributors", params={"per_page": "1", "anon": "true"}).mock(
        return_value=Response(200, json=contributors[:1], headers={"link": f'<{API}/x?per_page=1&anon=true&page=2>; rel="next", <{API}/x?per_page=1&anon=true&page=47>; rel="last"'}))
    mock.get(f"{API}/repos/acme/rocket/releases").mock(return_value=Response(200, json=releases))
    week = int(time.time()) // 604800 * 604800
    weeks = [{"week": week - 604800 * (19 - i), "total": 5 if i < 16 else 40} for i in range(20)]
    mock.get(f"{API}/repos/acme/rocket/stats/commit_activity").mock(return_value=Response(commit_status, json=weeks if commit_status == 200 else {}))
    mock.get(f"{API}/repos/acme/rocket/forks").mock(return_value=Response(200, json=[{"full_name": "zed/rocket", "html_url": "https://github.com/zed/rocket", "stargazers_count": 12, "pushed_at": iso(3), "created_at": iso(50)}]))
    mock.get(f"{API}/repos/acme/rocket/contents/").mock(return_value=Response(200, json=[{"name": "package.json", "type": "file"}, {"name": "src", "type": "dir"}]))
    import base64
    import json
    mock.get(f"{API}/repos/acme/rocket/contents/package.json").mock(
        return_value=Response(200, json={"encoding": "base64", "size": 100, "content": base64.b64encode(json.dumps(package_json).encode()).decode()}))


def release(tag: str, days_ago: int) -> dict:
    return {"tag_name": tag, "name": f"Rocket {tag}", "published_at": iso(days_ago), "prerelease": False, "draft": False, "html_url": f"https://github.com/acme/rocket/releases/tag/{tag}", "body": "Notes"}


async def test_discovery_upserts_search_results_with_snapshot_and_classification(db):
    with respx.mock(assert_all_called=True) as mock:
        route = mock.get(f"{API}/search/repositories").mock(return_value=Response(200, json={"total_count": 2, "items": [
            repo_payload(), repo_payload(id=9002, full_name="acme/vault", name="vault", topics=["security", "secrets-management"], description="Secrets manager", license=None)]},
            headers={"x-ratelimit-remaining": "9", "x-ratelimit-limit": "10", "x-ratelimit-reset": "0"}))
        async with GitHubClient() as client:
            repos, total = await ingestion.discover_repositories(db, client, "topic:automation stars:>500")
            assert client.rate["remaining"] == 9 and not client.authenticated
        request = route.calls.last.request
        assert request.headers["x-github-api-version"] == "2022-11-28" and "authorization" not in request.headers
        # a second identical discovery must update, not duplicate
        async with GitHubClient() as client:
            await ingestion.discover_repositories(db, client, "topic:automation stars:>500")
    assert total == 2 and [r.full_name for r in repos] == ["acme/rocket", "acme/vault"]
    assert await db.scalar(select(func.count()).select_from(Repository)) == 2
    assert await db.scalar(select(func.count()).select_from(RepositorySnapshot)) == 2  # one snapshot per repo per day
    rocket = await db.scalar(select(Repository).where(Repository.full_name == "acme/rocket"))
    assert (rocket.data_source, rocket.sync_level, rocket.category, rocket.license_spdx) == ("live_github", "search", "automation", "Apache-2.0")
    assert rocket.watchers is None  # the search API does not expose subscribers; never substituted with stars
    vault = await db.scalar(select(Repository).where(Repository.full_name == "acme/vault"))
    assert vault.category == "cybersecurity" and vault.license_spdx is None


async def test_full_sync_then_incremental_change_detection(db):
    with respx.mock() as mock:
        mock_full_sync(mock, releases=[release("v1.0.0", 30)], package_json={"dependencies": {"react": "^19"}, "devDependencies": {"vitest": "2"}})
        async with GitHubClient() as client:
            repo = await ingestion.track_repository(db, client, "acme/rocket")
            summary = await ingestion.full_sync_repository(db, client, repo)
    assert summary["status"] == "synced"
    assert (repo.sync_level, repo.watchers, repo.contributors_count, repo.etag) == ("full", 88, 47, '"v1"')
    assert any("issue_and_pr_totals" in m for m in repo.missing_data)  # no token -> closed issue totals honestly reported missing
    assert repo.closed_issues is None and repo.merged_prs is None
    assert await db.scalar(select(func.count()).select_from(RepositoryLanguage).where(RepositoryLanguage.repository_id == repo.id)) == 2
    assert await db.scalar(select(func.count()).select_from(CommitActivity)) == 20
    assert await db.scalar(select(func.count()).select_from(ForkRelationship)) == 1
    logins = set((await db.scalars(select(DeveloperProfile.login))).all())
    assert logins == {"alice", "bob"}  # bots are excluded
    assert {(d.package_name, d.dep_type) for d in (await db.scalars(select(Dependency))).all()} == {("react", "runtime"), ("vitest", "dev")}
    assert await db.scalar(select(func.count()).select_from(ChangeEvent)) == 0  # first sync establishes the baseline; history is not "news"

    summary = await intelligence.recompute_intelligence(db, [repo.id])
    assert summary == {"repositories_scored": 1, "opportunities": 1}
    score = await db.scalar(select(OpportunityScore).where(OpportunityScore.repository_id == repo.id))
    by_key = {m["key"]: m for m in score.metrics}
    assert by_key["development_momentum"]["score"] > 60 and by_key["competitive_positioning"]["score"] is None
    opportunity = await db.scalar(select(Opportunity))
    assert opportunity.data_source == "live_github" and opportunity.analysis["demand_indicators"][0]["source_url"] == "https://github.com/acme/rocket"
    await trends.detect_trends(db)
    signal = await db.scalar(select(TrendSignal).where(TrendSignal.signal_type == "commit_acceleration"))
    assert signal is not None and signal.data_source == "live_github" and signal.evidence[0]["source_url"].endswith("/graphs/commit-activity")

    # --- second sync: new release, dependency swap, language change
    with respx.mock() as mock:
        mock_full_sync(mock, releases=[release("v1.1.0", 0), release("v1.0.0", 30)], package_json={"dependencies": {"vue": "^3"}, "devDependencies": {"vitest": "2"}},
                       etag='"v2"', repo=repo_payload(language="Rust", stargazers_count=4300))
        async with GitHubClient() as client:
            await ingestion.full_sync_repository(db, client, repo)
    events = {e.event_type: e for e in (await db.scalars(select(ChangeEvent))).all()}
    assert set(events) == {"release", "dependency_change", "stack_change"}
    assert events["release"].title == "acme/rocket released v1.1.0" and events["release"].evidence_url.endswith("/v1.1.0")
    assert events["dependency_change"].details == {"added": ["vue"], "removed": ["react"]}
    assert events["stack_change"].details == {"from": "Python", "to": "Rust"}
    assert await db.scalar(select(func.count()).select_from(Release)) == 2 and repo.stars == 4300

    # --- third sync: unchanged (ETag) -> one conditional request, no sub-resource calls
    with respx.mock(assert_all_called=True) as mock:
        route = mock.get(f"{API}/repos/acme/rocket").mock(return_value=Response(304))
        async with GitHubClient() as client:
            summary = await ingestion.full_sync_repository(db, client, repo)
            assert client.requests_made == 1
        assert route.calls.last.request.headers["if-none-match"] == '"v2"'
    assert summary["status"] == "unchanged"


async def test_commit_stats_still_computing_is_reported_missing(db):
    with respx.mock() as mock:
        mock_full_sync(mock, releases=[], package_json={}, commit_status=202)
        async with GitHubClient() as client:
            client._sleep = _no_sleep
            repo = await ingestion.track_repository(db, client, "acme/rocket")
            await ingestion.full_sync_repository(db, client, repo)
    assert any(m.startswith("commit_activity") for m in repo.missing_data)
    assert await db.scalar(select(func.count()).select_from(CommitActivity)) == 0


async def _no_sleep(_seconds):
    return None


async def test_client_sends_token_only_in_header_and_uses_graphql_totals(db):
    with respx.mock() as mock:
        mock_full_sync(mock, releases=[], package_json={})
        graphql = mock.post(f"{API}/graphql").mock(return_value=Response(200, json={"data": {"repository": {
            "openIssues": {"totalCount": 40}, "closedIssues": {"totalCount": 900}, "openPRs": {"totalCount": 9}, "mergedPRs": {"totalCount": 1200}, "watchers": {"totalCount": 88}}}}))
        async with GitHubClient("test-token-value") as client:
            repo = await ingestion.track_repository(db, client, "acme/rocket")
            await ingestion.full_sync_repository(db, client, repo)
        assert graphql.calls.last.request.headers["authorization"] == "Bearer test-token-value"
        assert all("test-token-value" not in str(call.request.url) for call in mock.calls)
    assert (repo.open_issues, repo.closed_issues, repo.open_prs, repo.merged_prs) == (40, 900, 9, 1200)
    assert not any("issue_and_pr_totals" in m for m in repo.missing_data)


async def test_rate_limit_raises_and_blocks_further_calls_until_reset(db):
    reset = int(time.time()) + 1800
    with respx.mock() as mock:
        route = mock.get(f"{API}/search/repositories").mock(return_value=Response(403, json={"message": "API rate limit exceeded"},
                                                                                  headers={"x-ratelimit-remaining": "0", "x-ratelimit-reset": str(reset)}))
        async with GitHubClient() as client:
            with pytest.raises(GitHubRateLimited) as info:
                await client.search_repositories("x")
            assert abs(info.value.reset_at.timestamp() - reset) < 5
            with pytest.raises(GitHubRateLimited):
                await client.search_repositories("y")  # short-circuited locally
        assert route.call_count == 1  # we do not hammer GitHub while limited


async def test_github_search_endpoint_surfaces_rate_limit_and_live_results(client):
    with respx.mock() as mock:
        mock.get(f"{API}/search/repositories").mock(return_value=Response(200, json={"total_count": 1, "items": [repo_payload()]}))
        ok = await client.get("/api/v1/repositories/github-search?q=rocket")
    body = ok.json()
    assert ok.status_code == 200 and body["data_source"] == "live_github" and body["authenticated_request"] is False
    assert body["items"][0]["full_name"] == "acme/rocket" and body["items"][0]["score"] is not None
    dashboard = (await client.get("/api/v1/dashboard")).json()
    assert dashboard["provenance"]["mode"] == "live" and dashboard["summary"]["repositories_monitored"] == 1
    with respx.mock() as mock:
        mock.get(f"{API}/search/repositories").mock(return_value=Response(429, json={}, headers={"retry-after": "120"}))
        limited = await client.get("/api/v1/repositories/github-search?q=other")
    assert limited.status_code == 503 and limited.json()["error"]["code"] == "github_rate_limited"
    usage = {u["key"]: u["used"] for u in (await client.get("/api/v1/billing/subscription")).json()["usage"]}
    assert usage["live_syncs"] == 1  # only the successful live request is metered


async def test_live_data_takes_precedence_over_demo_in_auto_mode(client, demo_data):
    with respx.mock() as mock:
        mock.get(f"{API}/search/repositories").mock(return_value=Response(200, json={"total_count": 1, "items": [repo_payload()]}))
        await client.get("/api/v1/repositories/github-search?q=rocket")
    auto = (await client.get("/api/v1/repositories")).json()
    assert auto["total"] == 1 and auto["items"][0]["data_source"] == "live_github"
    assert (await client.get("/api/v1/repositories?source=demo")).json()["total"] == 27
    assert (await client.get("/api/v1/repositories?source=all")).json()["total"] == 28


async def test_track_and_watch_triggers_sync_and_notifications(client, db):
    with respx.mock() as mock:
        mock_full_sync(mock, releases=[release("v1.0.0", 30)], package_json={"dependencies": {"react": "^19"}})
        tracked = await client.post("/api/v1/repositories/track", json={"full_name": "acme/rocket"})
        assert tracked.status_code == 201
        repo_id = tracked.json()["id"]
        watchlist_id = (await client.get("/api/v1/watchlists")).json()["items"][0]["id"]
        await client.post(f"/api/v1/watchlists/{watchlist_id}/items", json={"item_type": "repository", "item_id": repo_id})
    detail = (await client.get(f"/api/v1/repositories/{repo_id}")).json()
    assert detail["repository"]["sync_level"] == "full" and detail["provenance"]["is_demo"] is False
    assert detail["repository"]["html_url"] == "https://github.com/acme/rocket"
    with respx.mock() as mock:
        mock_full_sync(mock, releases=[release("v2.0.0", 0), release("v1.0.0", 30)], package_json={"dependencies": {"react": "^19"}}, etag='"v2"', repo=repo_payload(stargazers_count=4250))
        sync = await client.post(f"/api/v1/repositories/{repo_id}/sync")
    assert sync.status_code == 202 and sync.json()["status"] == "succeeded"
    notes = (await client.get("/api/v1/notifications")).json()
    assert notes["unread"] == 1 and notes["items"][0]["title"] == "acme/rocket released v2.0.0" and notes["items"][0]["link"] == f"/repositories/{repo_id}"
    assert await db.scalar(select(func.count()).select_from(Notification)) == 1
    bad = await client.post("/api/v1/repositories/track", json={"full_name": "not a repo name"})
    assert bad.status_code == 422
    with respx.mock() as mock:
        mock.get(f"{API}/repos/acme/ghost").mock(return_value=Response(404, json={}))
        assert (await client.post("/api/v1/repositories/track", json={"full_name": "acme/ghost"})).status_code == 404


# ----------------------------------------------------------------------------- job queue


async def test_job_dedupe_retry_backoff_and_failure(db, monkeypatch):
    attempts = []

    async def flaky(_session, payload):
        attempts.append(payload["n"])
        raise RuntimeError("boom")

    monkeypatch.setitem(jobs.HANDLERS, "flaky", flaky)
    first = await jobs.enqueue(db, "flaky", {"n": 1}, dedupe_key="same", max_attempts=2)
    second = await jobs.enqueue(db, "flaky", {"n": 2}, dedupe_key="same", max_attempts=2)
    await db.commit()
    assert first.id == second.id  # deduplicated while pending
    assert await jobs.run_pending(db) == 1
    job = await db.get(Job, first.id)
    assert (job.status, job.attempts) == ("queued", 1) and "RuntimeError: boom" in job.last_error
    assert job.run_after > utcnow() + dt.timedelta(seconds=20)  # exponential backoff
    assert await jobs.run_pending(db) == 0  # not due yet
    job.run_after = utcnow() - dt.timedelta(seconds=1)
    await db.commit()
    await jobs.run_pending(db)
    job = await db.get(Job, first.id)
    assert (job.status, job.attempts) == ("failed", 2) and job.finished_at is not None and attempts == [1, 1]
    with pytest.raises(ValueError):
        await jobs.enqueue(db, "does-not-exist")


async def test_rate_limited_job_is_deferred_without_consuming_an_attempt(db, monkeypatch):
    reset = utcnow() + dt.timedelta(minutes=30)

    async def limited(_session, _payload):
        raise GitHubRateLimited(reset)

    monkeypatch.setitem(jobs.HANDLERS, "limited", limited)
    job = await jobs.enqueue(db, "limited", {})
    await db.commit()
    await jobs.run_pending(db)
    job = await db.get(Job, job.id)
    assert (job.status, job.attempts) == ("queued", 0) and job.run_after >= reset and "rate limit" in job.last_error


async def test_recurring_jobs_are_scheduled_once(db):
    assert await jobs.schedule_recurring(db) == 5
    assert await jobs.schedule_recurring(db) == 0
    types = set((await db.scalars(select(Job.job_type))).all())
    assert types == {"monitor_watched", "deepen_top_repositories", "recompute_intelligence", "retention_cleanup", "discover_all"}


async def test_deepen_job_queues_full_syncs_for_search_level_repositories(db):
    for i in range(6):
        db.add(Repository(full_name=f"org/repo{i}", owner_login="org", name=f"repo{i}", stars=1000 - i, forks=1, topics=[], missing_data=[], sync_level="search" if i else "full"))
    await db.commit()
    result = await jobs.HANDLERS["deepen_top_repositories"](db, {})
    assert result == {"queued": 4}  # small batch without a GitHub token, to stay inside the anonymous quota
    queued = (await db.scalars(select(Job).where(Job.job_type == "sync_repository"))).all()
    names = {(await db.get(Repository, j.payload["repository_id"])).full_name for j in queued}
    assert names == {"org/repo1", "org/repo2", "org/repo3", "org/repo4"}  # most-starred first; already-synced repo0 skipped


async def test_retention_cleanup_removes_old_snapshots(db, demo_data):
    repo_id = await db.scalar(select(Repository.id).limit(1))
    db.add(RepositorySnapshot(repository_id=repo_id, captured_on=(utcnow() - dt.timedelta(days=900)).date(), stars=1, forks=1))
    await db.commit()
    before = await db.scalar(select(func.count()).select_from(RepositorySnapshot))
    result = await jobs.HANDLERS["retention_cleanup"](db, {})
    assert result["snapshots"] == 1 and await db.scalar(select(func.count()).select_from(RepositorySnapshot)) == before - 1


async def test_contributor_links_power_developer_profiles(db):
    with respx.mock() as mock:
        mock_full_sync(mock, releases=[], package_json={})
        mock.get(f"{API}/users/alice").mock(return_value=Response(200, json={"id": 1, "login": "alice", "type": "User", "name": "Alice A", "company": "Acme", "followers": 321,
                                                                            "public_repos": 12, "created_at": iso(900), "email": "alice@private.example", "html_url": "https://github.com/alice"}))
        async with GitHubClient() as client:
            repo = await ingestion.track_repository(db, client, "acme/rocket")
            await ingestion.full_sync_repository(db, client, repo)
            dev = await db.scalar(select(DeveloperProfile).where(DeveloperProfile.login == "alice"))
            await ingestion.sync_developer(db, client, dev)
    assert (dev.sync_level, dev.name, dev.followers) == ("full", "Alice A", 321)
    assert not hasattr(dev, "email")  # e-mail addresses are never stored, even when GitHub returns one
    link = await db.scalar(select(Contributor).where(Contributor.developer_id == dev.id))
    assert link.contributions == 300


async def test_release_burst_requires_a_known_baseline(db):
    """A capped release list that sits entirely inside the window proves nothing about the baseline."""
    now = utcnow()
    capped = Repository(full_name="fast/shipper", owner_login="fast", name="shipper", stars=900, forks=10, topics=[], missing_data=[], sync_level="full", created_at_github=now - dt.timedelta(days=900))
    bursty = Repository(full_name="calm/then-busy", owner_login="calm", name="then-busy", stars=900, forks=10, topics=[], missing_data=[], sync_level="full", created_at_github=now - dt.timedelta(days=900))
    db.add_all([capped, bursty])
    await db.flush()
    for i in range(100):  # 100 = the fetch cap, all within 20 days: baseline unknown
        db.add(Release(repository_id=capped.id, tag_name=f"v0.{i}", published_at=now - dt.timedelta(hours=4 * i + 1)))
    for i, days in enumerate([1, 3, 6, 9, 12, 100]):  # five recent releases against one in the prior 90 days
        db.add(Release(repository_id=bursty.id, tag_name=f"v1.{i}", published_at=now - dt.timedelta(days=days)))
    await db.commit()
    await trends.detect_trends(db)
    bursts = {s.repository_id for s in (await db.scalars(select(TrendSignal).where(TrendSignal.signal_type == "release_burst"))).all()}
    assert bursts == {bursty.id}
