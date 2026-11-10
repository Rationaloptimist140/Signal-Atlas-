"""Incremental ingestion of public GitHub data.

Two levels keep API usage low:

* ``search`` - one Search API call upserts up to 100 repositories with headline metadata.
* ``full``   - ~8-10 calls enrich a single repository (languages, contributors, releases,
  commit activity, forks, manifests, GraphQL totals). ETags skip unchanged repositories.
"""

import datetime as dt

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.logging_config import get_logger
from app.models import (
    ChangeEvent,
    CommitActivity,
    Contributor,
    DataSource,
    Dependency,
    DeveloperProfile,
    ForkRelationship,
    Language,
    Release,
    Repository,
    RepositoryLanguage,
    RepositorySnapshot,
    RepositoryTechnology,
    Technology,
    utcnow,
)
from app.services.github_client import GitHubClient, GitHubError, GitHubNotFound, GitHubRateLimited, parse_dt
from app.services.manifests import MANIFEST_FILES, parse_manifest
from app.services.scoring import RELEASE_FETCH_LIMIT
from app.taxonomy import TECHNOLOGIES, classify, primary_category

log = get_logger("ingestion")

# Curated, category-balanced discovery queries (public search; recently active projects only).
DISCOVERY_QUERIES: list[tuple[str, str]] = [
    ("ai-ml", "topic:llm stars:>500 pushed:>{recent}"),
    ("ai-ml", "topic:ai-agents stars:>300 pushed:>{recent}"),
    ("ai-ml", "topic:machine-learning created:>{year_ago} stars:>300"),
    ("developer-infrastructure", "topic:developer-tools stars:>500 pushed:>{recent}"),
    ("cybersecurity", "topic:security stars:>500 pushed:>{recent}"),
    ("data-infrastructure", "topic:database stars:>500 pushed:>{recent}"),
    ("cloud-computing", "topic:kubernetes stars:>500 pushed:>{recent}"),
    ("automation", "topic:automation stars:>500 pushed:>{recent}"),
    ("fintech", "topic:fintech stars:>100 pushed:>{recent}"),
    ("blockchain", "topic:blockchain stars:>500 pushed:>{recent}"),
    ("enterprise-software", "topic:self-hosted stars:>500 pushed:>{recent}"),
    ("emerging", "created:>{quarter_ago} stars:>500"),
]


def render_query(template: str, now: dt.datetime | None = None) -> str:
    now = now or utcnow()
    return template.format(
        recent=(now - dt.timedelta(days=30)).date().isoformat(),
        quarter_ago=(now - dt.timedelta(days=90)).date().isoformat(),
        year_ago=(now - dt.timedelta(days=365)).date().isoformat(),
    )


# --------------------------------------------------------------------------- upserts


async def ensure_technologies(session: AsyncSession) -> dict[str, Technology]:
    existing = {t.slug: t for t in (await session.scalars(select(Technology))).all()}
    for slug, (name, category, _kw) in TECHNOLOGIES.items():
        if slug not in existing:
            tech = Technology(slug=slug, name=name, category=category)
            session.add(tech)
            existing[slug] = tech
    await session.flush()
    return existing


async def apply_classification(session: AsyncSession, repo: Repository) -> None:
    techs = await ensure_technologies(session)
    matches = classify(repo.name, repo.description, repo.topics or [])
    repo.category = primary_category(matches)
    current = {
        rt.technology_id: rt
        for rt in (await session.scalars(select(RepositoryTechnology).where(RepositoryTechnology.repository_id == repo.id))).all()
    }
    wanted: set[int] = set()
    for match in matches[:8]:
        tech_id = techs[match.slug].id
        wanted.add(tech_id)
        if tech_id in current:
            current[tech_id].confidence = match.confidence
            current[tech_id].method = f"keyword:{match.matched_on}"
        else:
            session.add(RepositoryTechnology(repository_id=repo.id, technology_id=tech_id, confidence=match.confidence, method=f"keyword:{match.matched_on}"))
    for tech_id, row in current.items():
        if tech_id not in wanted:
            await session.delete(row)


async def record_snapshot(session: AsyncSession, repo: Repository, on: dt.date | None = None) -> RepositorySnapshot:
    day = on or utcnow().date()
    snap = await session.scalar(select(RepositorySnapshot).where(RepositorySnapshot.repository_id == repo.id, RepositorySnapshot.captured_on == day))
    if snap is None:
        snap = RepositorySnapshot(repository_id=repo.id, captured_on=day, stars=repo.stars, forks=repo.forks)
        session.add(snap)
    snap.stars, snap.forks = repo.stars, repo.forks
    snap.watchers, snap.open_issues, snap.contributors_count = repo.watchers, repo.open_issues, repo.contributors_count
    snap.captured_at = utcnow()
    return snap


def _apply_repo_fields(repo: Repository, data: dict, *, full: bool) -> None:
    owner = data.get("owner") or {}
    licence = data.get("license") or {}
    repo.github_id = data.get("id")
    repo.full_name = data["full_name"]
    repo.owner_login = owner.get("login") or data["full_name"].split("/")[0]
    repo.owner_type = owner.get("type")
    repo.name = data.get("name") or data["full_name"].split("/")[-1]
    repo.description = data.get("description")
    repo.html_url = data.get("html_url")
    repo.homepage = data.get("homepage") or None
    repo.primary_language = data.get("language")
    spdx = licence.get("spdx_id")
    repo.license_spdx = spdx if spdx and spdx != "NOASSERTION" else None
    repo.license_name = licence.get("name")
    repo.topics = list(data.get("topics") or [])
    repo.stars = int(data.get("stargazers_count") or 0)
    repo.forks = int(data.get("forks_count") or 0)
    repo.size_kb = data.get("size")
    repo.is_fork = bool(data.get("fork"))
    repo.archived = bool(data.get("archived"))
    repo.default_branch = data.get("default_branch")
    repo.created_at_github = parse_dt(data.get("created_at"))
    repo.pushed_at_github = parse_dt(data.get("pushed_at"))
    repo.updated_at_github = parse_dt(data.get("updated_at"))
    repo.data_source = DataSource.LIVE.value
    if full:
        # subscribers_count is the true "watching" figure and only appears on the single-repo endpoint.
        repo.watchers = data.get("subscribers_count")
        repo.open_issues = data.get("open_issues_count")  # GitHub counts open issues + open PRs here
        parent, source = data.get("parent") or {}, data.get("source") or {}
        repo.parent_full_name = parent.get("full_name")
        repo.source_full_name = source.get("full_name")
    elif repo.open_issues is None:
        repo.open_issues = data.get("open_issues_count")


async def upsert_repository(session: AsyncSession, data: dict, *, full: bool = False) -> Repository:
    """Create or update a repository from a GitHub REST payload and snapshot today's figures."""
    repo = None
    if data.get("id"):
        repo = await session.scalar(select(Repository).where(Repository.github_id == data["id"]))
    if repo is None:
        repo = await session.scalar(select(Repository).where(func.lower(Repository.full_name) == data["full_name"].lower()))
    if repo is None:
        repo = Repository(full_name=data["full_name"], owner_login="", name="", sync_level="search", missing_data=[])
        session.add(repo)
    _apply_repo_fields(repo, data, full=full)
    repo.last_synced_at = utcnow()
    await session.flush()
    await apply_classification(session, repo)
    await record_snapshot(session, repo)
    return repo


async def discover_repositories(session: AsyncSession, client: GitHubClient, query: str, *, per_page: int = 30,
                                sort: str | None = "stars", page: int = 1) -> tuple[list[Repository], int]:
    """Run one GitHub search and upsert the results at ``search`` level."""
    payload = await client.search_repositories(query, sort=sort, per_page=per_page, page=page)
    repos = [await upsert_repository(session, item) for item in payload.get("items", [])]
    await session.commit()
    log.info("discovery_complete", query=query, found=len(repos), total=payload.get("total_count"))
    return repos, int(payload.get("total_count") or 0)


async def upsert_developer_stub(session: AsyncSession, data: dict) -> DeveloperProfile | None:
    login = data.get("login")
    if not login or data.get("type") == "Bot" or login.endswith("[bot]"):
        return None
    dev = await session.scalar(select(DeveloperProfile).where(func.lower(DeveloperProfile.login) == login.lower()))
    if dev is None:
        dev = DeveloperProfile(login=login, sync_level="stub", inferred={})
        session.add(dev)
    dev.github_id = data.get("id") or dev.github_id
    dev.avatar_url = data.get("avatar_url") or dev.avatar_url
    dev.html_url = data.get("html_url") or dev.html_url
    dev.account_type = data.get("type") or dev.account_type or "User"
    dev.data_source = DataSource.LIVE.value
    await session.flush()
    return dev


# --------------------------------------------------------------------------- full sync


async def _add_event(session: AsyncSession, repo: Repository, event_type: str, key: str, title: str, details: dict,
                     url: str | None = None, occurred_at: dt.datetime | None = None) -> None:
    dedupe = f"{repo.id}:{event_type}:{key}"[:300]
    if await session.scalar(select(ChangeEvent.id).where(ChangeEvent.dedupe_key == dedupe)):
        return
    session.add(ChangeEvent(dedupe_key=dedupe, repository_id=repo.id, event_type=event_type, title=title[:300], details=details,
                            evidence_url=url, data_source=repo.data_source, occurred_at=occurred_at or utcnow()))


async def _sync_languages(session: AsyncSession, client: GitHubClient, repo: Repository) -> None:
    langs = await client.get_languages(repo.full_name)
    await session.execute(delete(RepositoryLanguage).where(RepositoryLanguage.repository_id == repo.id))
    for name, size in langs.items():
        lang = await session.scalar(select(Language).where(Language.name == name))
        if lang is None:
            lang = Language(name=name)
            session.add(lang)
            await session.flush()
        session.add(RepositoryLanguage(repository_id=repo.id, language_id=lang.id, byte_count=int(size)))


async def _sync_contributors(session: AsyncSession, client: GitHubClient, repo: Repository) -> None:
    contributors = await client.get_contributors(repo.full_name, per_page=30)
    total = await client.count_contributors(repo.full_name)
    repo.contributors_count = total if total is not None else (len(contributors) if len(contributors) < 30 else None)
    existing = {c.developer_id: c for c in (await session.scalars(select(Contributor).where(Contributor.repository_id == repo.id))).all()}
    for item in contributors:
        dev = await upsert_developer_stub(session, item)
        if dev is None:
            continue
        row = existing.get(dev.id)
        if row is None:
            session.add(Contributor(repository_id=repo.id, developer_id=dev.id, contributions=int(item.get("contributions") or 0)))
        else:
            row.contributions = int(item.get("contributions") or 0)


async def _sync_releases(session: AsyncSession, client: GitHubClient, repo: Repository, first_full_sync: bool) -> None:
    releases = await client.get_releases(repo.full_name, per_page=RELEASE_FETCH_LIMIT)
    known = {r.tag_name for r in (await session.scalars(select(Release).where(Release.repository_id == repo.id))).all()}
    for item in releases:
        tag = (item.get("tag_name") or "")[:200]
        if not tag or item.get("draft") or tag in known:
            continue
        published = parse_dt(item.get("published_at"))
        session.add(Release(repository_id=repo.id, tag_name=tag, name=(item.get("name") or None), published_at=published,
                            prerelease=bool(item.get("prerelease")), html_url=item.get("html_url"),
                            body_excerpt=(item.get("body") or "")[:1500] or None))
        known.add(tag)
        # Only releases that appear *after* we started watching count as change events.
        if not first_full_sync:
            await _add_event(session, repo, "release", tag, f"{repo.full_name} released {tag}",
                             {"tag": tag, "name": item.get("name"), "prerelease": bool(item.get("prerelease")),
                              "notes_excerpt": (item.get("body") or "")[:600]}, item.get("html_url"), published)


async def _sync_commit_activity(session: AsyncSession, client: GitHubClient, repo: Repository, missing: list[str]) -> None:
    weeks = await client.get_commit_activity(repo.full_name)
    if weeks is None:
        missing.append("commit_activity: GitHub is still computing statistics; retried on the next sync")
        return
    existing = {c.week_start: c for c in (await session.scalars(select(CommitActivity).where(CommitActivity.repository_id == repo.id))).all()}
    for week in weeks:
        start = dt.datetime.fromtimestamp(int(week["week"]), dt.UTC).date()
        row = existing.get(start)
        if row is None:
            session.add(CommitActivity(repository_id=repo.id, week_start=start, commits=int(week.get("total") or 0)))
        else:
            row.commits = int(week.get("total") or 0)


async def _sync_forks(session: AsyncSession, client: GitHubClient, repo: Repository) -> None:
    if repo.forks <= 0:
        return
    forks = await client.get_forks(repo.full_name, per_page=20)
    existing = {f.fork_full_name: f for f in (await session.scalars(select(ForkRelationship).where(ForkRelationship.parent_repository_id == repo.id))).all()}
    for item in forks:
        name = item.get("full_name")
        if not name:
            continue
        row = existing.get(name)
        if row is None:
            row = ForkRelationship(parent_repository_id=repo.id, fork_full_name=name)
            session.add(row)
        row.fork_html_url = item.get("html_url")
        row.stars = int(item.get("stargazers_count") or 0)
        row.pushed_at = parse_dt(item.get("pushed_at"))
        row.created_at_github = parse_dt(item.get("created_at"))


async def _sync_dependencies(session: AsyncSession, client: GitHubClient, repo: Repository, first_full_sync: bool, missing: list[str]) -> None:
    root = await client.list_root(repo.full_name)
    present = [m for m in MANIFEST_FILES if m in root]
    if not present:
        missing.append("dependencies: no supported root manifest (package.json, requirements.txt, pyproject.toml, go.mod, Cargo.toml)")
        return
    parsed = []
    for manifest in present:
        text = await client.get_file(repo.full_name, manifest)
        if text:
            parsed.extend(parse_manifest(manifest, text))
    existing = {(d.ecosystem, d.package_name, d.dep_type): d for d in (await session.scalars(select(Dependency).where(Dependency.repository_id == repo.id))).all()}
    wanted = {(p.ecosystem, p.name, p.dep_type): p for p in parsed}
    added = [k for k in wanted if k not in existing]
    removed = [k for k in existing if k not in wanted]
    for key in added:
        p = wanted[key]
        session.add(Dependency(repository_id=repo.id, ecosystem=p.ecosystem, package_name=p.name, version_spec=p.version_spec, dep_type=p.dep_type, manifest_path=p.manifest_path))
    for key, row in existing.items():
        if key in wanted:
            row.version_spec = wanted[key].version_spec
        else:
            await session.delete(row)
    if not first_full_sync and existing and (added or removed):
        today = utcnow().date().isoformat()
        runtime_added = [k[1] for k in added if k[2] == "runtime"][:25]
        runtime_removed = [k[1] for k in removed if k[2] == "runtime"][:25]
        if runtime_added or runtime_removed:
            await _add_event(session, repo, "dependency_change", today, f"{repo.full_name} changed its runtime dependencies",
                             {"added": runtime_added, "removed": runtime_removed}, repo.html_url)


async def full_sync_repository(session: AsyncSession, client: GitHubClient, repo: Repository, *, force: bool = False) -> dict:
    """Enrich one repository. Returns a summary including what could not be collected."""
    if repo.data_source == DataSource.DEMO.value:
        return {"status": "skipped", "reason": "demo fixtures are never synced against GitHub"}
    first_full_sync = repo.sync_level != "full"
    previous_language = repo.primary_language
    missing: list[str] = []
    try:
        data, etag = await client.get_repo(repo.full_name, None if (force or first_full_sync) else repo.etag)
    except GitHubNotFound:
        repo.missing_data = ["repository: no longer publicly available on GitHub"]
        await session.commit()
        return {"status": "not_found"}

    if data is None:  # unchanged since last sync - snapshot only
        repo.last_synced_at = utcnow()
        await record_snapshot(session, repo)
        await session.commit()
        return {"status": "unchanged", "requests": client.requests_made}

    _apply_repo_fields(repo, data, full=True)
    repo.etag = etag
    await session.flush()

    steps = [
        ("languages", lambda: _sync_languages(session, client, repo)),
        ("contributors", lambda: _sync_contributors(session, client, repo)),
        ("releases", lambda: _sync_releases(session, client, repo, first_full_sync)),
        ("commit_activity", lambda: _sync_commit_activity(session, client, repo, missing)),
        ("forks", lambda: _sync_forks(session, client, repo)),
        ("dependencies", lambda: _sync_dependencies(session, client, repo, first_full_sync, missing)),
    ]
    rate_limited: GitHubRateLimited | None = None
    for name, step in steps:
        if rate_limited:
            missing.append(f"{name}: skipped - GitHub rate limit reached, retried on the next sync")
            continue
        try:
            await step()
        except GitHubRateLimited as exc:
            rate_limited = exc
            missing.append(f"{name}: skipped - GitHub rate limit reached, retried on the next sync")
        except GitHubError as exc:
            missing.append(f"{name}: unavailable ({exc})")

    if not rate_limited:
        try:
            totals = await client.graphql_repo_metrics(repo.full_name)
        except GitHubRateLimited as exc:
            rate_limited, totals = exc, None
        except GitHubError:
            totals = None
        if totals:
            repo.open_issues, repo.closed_issues = totals["open_issues"], totals["closed_issues"]
            repo.open_prs, repo.merged_prs = totals["open_prs"], totals["merged_prs"]
        else:
            missing.append("issue_and_pr_totals: closed issue and pull request totals need a GitHub token (GraphQL)")

    if not first_full_sync and previous_language and repo.primary_language and previous_language != repo.primary_language:
        await _add_event(session, repo, "stack_change", f"{previous_language}->{repo.primary_language}",
                         f"{repo.full_name} primary language changed from {previous_language} to {repo.primary_language}",
                         {"from": previous_language, "to": repo.primary_language}, repo.html_url)

    repo.sync_level = "full"
    repo.missing_data = missing
    repo.last_synced_at = utcnow()
    await apply_classification(session, repo)
    await record_snapshot(session, repo)
    await session.commit()
    log.info("repository_synced", repository=repo.full_name, requests=client.requests_made, missing=len(missing))
    if rate_limited:
        # Partial data is saved; let the caller defer a retry until the limit resets.
        raise rate_limited
    return {"status": "synced", "requests": client.requests_made, "missing": missing}


async def track_repository(session: AsyncSession, client: GitHubClient, full_name: str) -> Repository:
    """Fetch a repository by name and store it at search level (one request)."""
    data, etag = await client.get_repo(full_name)
    assert data is not None
    repo = await upsert_repository(session, data, full=True)
    repo.etag = None  # force the first full sync to fetch sub-resources
    await session.commit()
    return repo


async def sync_developer(session: AsyncSession, client: GitHubClient, dev: DeveloperProfile) -> DeveloperProfile:
    """Refresh a developer's *public* profile. E-mail addresses are never stored."""
    if dev.data_source == DataSource.DEMO.value:
        return dev
    data = await client.get_user(dev.login)
    dev.github_id = data.get("id")
    dev.login = data.get("login") or dev.login
    dev.account_type = data.get("type") or "User"
    dev.name = data.get("name")
    dev.avatar_url = data.get("avatar_url")
    dev.html_url = data.get("html_url")
    dev.company = data.get("company")
    dev.location = data.get("location")
    dev.bio = data.get("bio")
    dev.followers = data.get("followers")
    dev.following = data.get("following")
    dev.public_repos = data.get("public_repos")
    dev.created_at_github = parse_dt(data.get("created_at"))
    dev.sync_level = "full"
    dev.last_synced_at = utcnow()
    await session.commit()
    return dev
