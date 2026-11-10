"""Repository Intelligence (Engine 1)."""

import datetime as dt
import time
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.deps import Principal, get_principal, require_verified_analyst
from app.models import (
    ChangeEvent,
    CommitActivity,
    Contributor,
    DataSource,
    Dependency,
    DeveloperProfile,
    ForkRelationship,
    Language,
    Opportunity,
    OpportunityScore,
    Release,
    Repository,
    RepositoryLanguage,
    RepositorySnapshot,
    RepositoryTechnology,
    Technology,
    utcnow,
)
from app.routers.common import (
    SourceParam,
    get_repo_or_404,
    like_pattern,
    paginate,
    repo_list_items,
    resolve_source,
    source_query,
)
from app.schemas import Page, RepositoryListItem, RepositoryOut, TrackRepositoryIn
from app.services import ingestion, jobs
from app.services.github_client import GitHubError, GitHubNotFound, GitHubRateLimited
from app.services.intelligence import (
    PeerCache,
    current_score,
    get_weights,
    present_score,
    refresh_opportunity,
    score_repository,
)
from app.services.scoring import licence_score
from app.services.usage import audit, enforce_monthly_limit, record_usage
from app.taxonomy import CATEGORIES

router = APIRouter(prefix="/repositories", tags=["repositories"])

SEARCH_CACHE_SECONDS = 300
_SEARCH_CACHE: dict[tuple, tuple] = {}  # (query, sort, per_page) -> (monotonic time, repository ids, total, fetched_at, authenticated)

SORTS = {
    "stars": Repository.stars.desc(),
    "forks": Repository.forks.desc(),
    "recently_pushed": Repository.pushed_at_github.desc().nulls_last(),
    "newest": Repository.created_at_github.desc().nulls_last(),
    "contributors": Repository.contributors_count.desc().nulls_last(),
    "name": Repository.full_name.asc(),
}
ACTIVITY_DAYS = {"active_7d": 7, "active_30d": 30, "active_90d": 90}


def _rate_limited(exc: GitHubRateLimited) -> HTTPException:
    return HTTPException(status_code=503, detail={
        "code": "github_rate_limited",
        "message": "GitHub's API rate limit has been reached. Connect a GitHub account or set GITHUB_TOKEN to raise the limit.",
        "retry_at": exc.reset_at.isoformat(),
    })


@router.get("", response_model=Page[RepositoryListItem], summary="Search and filter tracked repositories")
async def list_repositories(
    q: str | None = Query(None, max_length=200, description="Matches name, description and topics"),
    category: str | None = Query(None, max_length=60),
    technology: str | None = Query(None, max_length=80, description="Technology slug"),
    language: str | None = Query(None, max_length=80),
    license: str | None = Query(None, max_length=60, description="SPDX id, or 'none'"),
    min_stars: int | None = Query(None, ge=0),
    min_contributors: int | None = Query(None, ge=0),
    activity: Literal["active_7d", "active_30d", "active_90d", "stale"] | None = None,
    sort: Literal["stars", "forks", "recently_pushed", "newest", "contributors", "name", "score"] = "stars",
    source: SourceParam = source_query(),
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    principal: Principal = Depends(get_principal),
    db: AsyncSession = Depends(get_db),
) -> Page[RepositoryListItem]:
    query = select(Repository)
    data_source = await resolve_source(db, source)
    if data_source:
        query = query.where(Repository.data_source == data_source)
    if q:
        pattern = like_pattern(q.strip())
        query = query.where(or_(Repository.full_name.ilike(pattern, escape="\\"), Repository.description.ilike(pattern, escape="\\")))
    if category:
        query = query.where(Repository.category == category)
    if technology:
        query = query.where(Repository.id.in_(
            select(RepositoryTechnology.repository_id).join(Technology, Technology.id == RepositoryTechnology.technology_id).where(Technology.slug == technology)))
    if language:
        query = query.where(func.lower(Repository.primary_language) == language.lower())
    if license:
        query = query.where(Repository.license_spdx.is_(None) if license.lower() == "none" else func.lower(Repository.license_spdx) == license.lower())
    if min_stars is not None:
        query = query.where(Repository.stars >= min_stars)
    if min_contributors is not None:
        query = query.where(Repository.contributors_count >= min_contributors)
    if activity:
        now = utcnow()
        if activity == "stale":
            query = query.where(Repository.pushed_at_github < now - dt.timedelta(days=180))
        else:
            query = query.where(Repository.pushed_at_github >= now - dt.timedelta(days=ACTIVITY_DAYS[activity]))
    if sort == "score":
        query = query.outerjoin(OpportunityScore, (OpportunityScore.repository_id == Repository.id) & OpportunityScore.is_current.is_(True)) \
            .order_by(OpportunityScore.total_default.desc().nulls_last(), Repository.stars.desc())
    else:
        query = query.order_by(SORTS[sort], Repository.id)
    rows, total = await paginate(db, query, page, page_size)
    items = await repo_list_items(db, [r[0] for r in rows], await get_weights(db, principal.organisation_id))
    return Page[RepositoryListItem](items=items, total=total, page=page, page_size=page_size)


@router.get("/facets", summary="Filter options with counts for the repository explorer")
async def facets(source: SourceParam = source_query(), principal: Principal = Depends(get_principal), db: AsyncSession = Depends(get_db)) -> dict:
    data_source = await resolve_source(db, source)
    cond = [Repository.data_source == data_source] if data_source else []

    async def grouped(column, limit=30):
        rows = await db.execute(select(column, func.count()).where(*cond).group_by(column).order_by(func.count().desc()).limit(limit))
        return [{"value": value, "count": count} for value, count in rows.all() if value]

    return {
        "categories": [dict(item, label=CATEGORIES.get(item["value"], item["value"])) for item in await grouped(Repository.category)],
        "languages": await grouped(Repository.primary_language),
        "licenses": await grouped(Repository.license_spdx),
        "data_source": data_source or "all",
    }


@router.get("/github-search", summary="Search public GitHub live and add the results to the tracked set")
async def github_search(
    q: str = Query(..., min_length=2, max_length=200),
    sort: Literal["stars", "updated", "best_match"] = "stars",
    per_page: int = Query(20, ge=1, le=50),
    principal: Principal = Depends(require_verified_analyst),
    db: AsyncSession = Depends(get_db),
) -> dict:
    cache_key = (q.strip().lower(), sort, per_page)
    cached = _SEARCH_CACHE.get(cache_key)
    if cached and time.monotonic() - cached[0] < SEARCH_CACHE_SECONDS:
        # Identical search within five minutes: serve the stored results instead of spending GitHub quota (not metered).
        repos = list((await db.scalars(select(Repository).where(Repository.id.in_(cached[1])).order_by(Repository.stars.desc()))).all())
        items = await repo_list_items(db, repos, await get_weights(db, principal.organisation_id))
        return {"items": items, "total_on_github": cached[2], "data_source": DataSource.LIVE.value, "fetched_at": cached[3], "authenticated_request": cached[4], "cached": True}
    await enforce_monthly_limit(db, principal.organisation_id, "live_syncs", "live_syncs_per_month", "live GitHub requests")
    async with await jobs.github_client_for(db, principal.user_id) as client:
        try:
            repos, total = await ingestion.discover_repositories(db, client, q, per_page=per_page, sort=None if sort == "best_match" else sort)
        except GitHubRateLimited as exc:
            raise _rate_limited(exc) from exc
        except GitHubError as exc:
            raise HTTPException(status_code=502, detail={"code": "github_error", "message": f"GitHub search failed: {exc}"}) from exc
        authenticated = client.authenticated
    await record_usage(db, principal.organisation_id, "live_syncs")
    await db.commit()
    await jobs.enqueue_and_maybe_run(db, "recompute_intelligence", {"repository_ids": [r.id for r in repos]}, dedupe_key=None)
    items = await repo_list_items(db, repos, await get_weights(db, principal.organisation_id))
    fetched_at = utcnow().isoformat()
    if len(_SEARCH_CACHE) > 500:
        _SEARCH_CACHE.clear()
    _SEARCH_CACHE[cache_key] = (time.monotonic(), [r.id for r in repos], total, fetched_at, authenticated)
    return {"items": items, "total_on_github": total, "data_source": DataSource.LIVE.value, "fetched_at": fetched_at, "authenticated_request": authenticated, "cached": False}


@router.post("/track", response_model=RepositoryOut, status_code=201, summary="Track a public repository by owner/name")
async def track(body: TrackRepositoryIn, principal: Principal = Depends(require_verified_analyst), db: AsyncSession = Depends(get_db)) -> Repository:
    existing = await db.scalar(select(Repository).where(func.lower(Repository.full_name) == body.full_name.lower()))
    if existing:
        return existing
    await enforce_monthly_limit(db, principal.organisation_id, "live_syncs", "live_syncs_per_month", "live GitHub requests")
    async with await jobs.github_client_for(db, principal.user_id) as client:
        try:
            repo = await ingestion.track_repository(db, client, body.full_name)
        except GitHubNotFound as exc:
            raise HTTPException(status_code=404, detail={"code": "not_found", "message": "No public repository with that name exists on GitHub."}) from exc
        except GitHubRateLimited as exc:
            raise _rate_limited(exc) from exc
        except GitHubError as exc:
            raise HTTPException(status_code=502, detail={"code": "github_error", "message": str(exc)}) from exc
    await record_usage(db, principal.organisation_id, "live_syncs")
    await audit(db, "repository.tracked", organisation_id=principal.organisation_id, user_id=principal.user_id, target_type="repository", target_id=repo.id)
    await db.commit()
    await jobs.enqueue_and_maybe_run(db, "sync_repository", {"repository_id": repo.id, "user_id": principal.user_id}, dedupe_key=f"sync_repository:{repo.id}")
    return repo


@router.get("/{repository_id}", summary="Repository profile")
async def get_repository(repository_id: int, principal: Principal = Depends(get_principal), db: AsyncSession = Depends(get_db)) -> dict:
    repo = await get_repo_or_404(db, repository_id)
    languages = (await db.execute(
        select(Language.name, RepositoryLanguage.byte_count).join(Language, Language.id == RepositoryLanguage.language_id)
        .where(RepositoryLanguage.repository_id == repo.id).order_by(RepositoryLanguage.byte_count.desc()))).all()
    total_bytes = sum(b for _, b in languages) or 1
    technologies = (await db.execute(
        select(Technology.slug, Technology.name, Technology.category, RepositoryTechnology.confidence, RepositoryTechnology.method)
        .join(Technology, Technology.id == RepositoryTechnology.technology_id)
        .where(RepositoryTechnology.repository_id == repo.id).order_by(RepositoryTechnology.confidence.desc()))).all()
    score_row = await current_score(db, repo.id)
    opportunity_id = await db.scalar(select(Opportunity.id).where(Opportunity.repository_id == repo.id))
    parent_id = None
    if repo.parent_full_name:
        parent_id = await db.scalar(select(Repository.id).where(Repository.full_name == repo.parent_full_name))
    lic_score, lic_text = licence_score(repo.license_spdx)
    return {
        "repository": RepositoryOut.model_validate(repo),
        "category_label": CATEGORIES.get(repo.category or ""),
        "languages": [{"name": n, "bytes": b, "share": round(b / total_bytes, 4)} for n, b in languages],
        "technologies": [{"slug": s, "name": n, "category": c, "confidence": conf, "method": m, "basis": "inferred"} for s, n, c, conf, m in technologies],
        "score": present_score(score_row, await get_weights(db, principal.organisation_id)) if score_row else None,
        "opportunity_id": opportunity_id,
        "parent": {"full_name": repo.parent_full_name, "repository_id": parent_id} if repo.parent_full_name else None,
        "licence": {"spdx": repo.license_spdx, "name": repo.license_name, "assessment": lic_text, "commercial_friendliness": lic_score, "basis": "interpretation",
                    "note": "Automated reading of the detected licence; not legal advice."},
        "provenance": {"data_source": repo.data_source, "is_demo": repo.data_source == DataSource.DEMO.value, "sync_level": repo.sync_level,
                       "last_synced_at": repo.last_synced_at, "missing_data": repo.missing_data},
    }


@router.get("/{repository_id}/activity", summary="Commit activity, star history and recent change events")
async def activity_detail(repository_id: int, principal: Principal = Depends(get_principal), db: AsyncSession = Depends(get_db)) -> dict:
    repo = await get_repo_or_404(db, repository_id)
    weeks = (await db.execute(select(CommitActivity.week_start, CommitActivity.commits).where(CommitActivity.repository_id == repo.id).order_by(CommitActivity.week_start))).all()
    snaps = (await db.execute(
        select(RepositorySnapshot.captured_on, RepositorySnapshot.stars, RepositorySnapshot.forks, RepositorySnapshot.contributors_count)
        .where(RepositorySnapshot.repository_id == repo.id).order_by(RepositorySnapshot.captured_on.desc()).limit(180))).all()
    events = (await db.scalars(select(ChangeEvent).where(ChangeEvent.repository_id == repo.id).order_by(ChangeEvent.occurred_at.desc()).limit(30))).all()
    return {
        "commit_activity": [{"week_start": w.isoformat(), "commits": c} for w, c in weeks],
        "commit_activity_available": bool(weeks),
        "snapshots": [{"date": d.isoformat(), "stars": s, "forks": f, "contributors": c} for d, s, f, c in reversed(snaps)],
        "snapshot_note": "Star history is recorded by Signal Atlas from the first sync onwards; GitHub does not provide historical totals.",
        "issues": {"open": repo.open_issues, "closed": repo.closed_issues, "open_prs": repo.open_prs, "merged_prs": repo.merged_prs,
                   "note": None if repo.closed_issues is not None else "Closed issue and pull request totals need a GitHub token (GraphQL). 'Open' includes open pull requests."},
        "change_events": [{"id": e.id, "event_type": e.event_type, "title": e.title, "details": e.details, "evidence_url": e.evidence_url,
                           "occurred_at": e.occurred_at, "data_source": e.data_source} for e in events],
        "data_source": repo.data_source,
    }


@router.get("/{repository_id}/contributors", summary="Top contributors and concentration")
async def contributors(repository_id: int, principal: Principal = Depends(get_principal), db: AsyncSession = Depends(get_db)) -> dict:
    repo = await get_repo_or_404(db, repository_id)
    rows = (await db.execute(
        select(DeveloperProfile.id, DeveloperProfile.login, DeveloperProfile.name, DeveloperProfile.avatar_url, DeveloperProfile.html_url, Contributor.contributions)
        .join(Contributor, Contributor.developer_id == DeveloperProfile.id).where(Contributor.repository_id == repo.id)
        .order_by(Contributor.contributions.desc()).limit(30))).all()
    total = sum(r[5] for r in rows) or 1
    return {
        "total_contributors": repo.contributors_count,
        "contributors": [{"developer_id": i, "login": login, "name": name, "avatar_url": avatar, "html_url": url, "contributions": c, "share_of_listed": round(c / total, 4)}
                         for i, login, name, avatar, url, c in rows],
        "top_contributor_share": round(rows[0][5] / total, 4) if rows else None,
        "note": "Shares are calculated across the listed top contributors only (GitHub returns the most active accounts; bots are excluded).",
        "data_source": repo.data_source,
    }


@router.get("/{repository_id}/dependencies", summary="Declared dependencies from root manifests")
async def dependencies(repository_id: int, principal: Principal = Depends(get_principal), db: AsyncSession = Depends(get_db)) -> dict:
    repo = await get_repo_or_404(db, repository_id)
    deps = (await db.scalars(select(Dependency).where(Dependency.repository_id == repo.id).order_by(Dependency.dep_type.desc(), Dependency.package_name))).all()
    shared_counts = dict((await db.execute(
        select(Dependency.package_name, func.count(func.distinct(Dependency.repository_id)))
        .where(Dependency.package_name.in_([d.package_name for d in deps]) if deps else Dependency.id < 0).group_by(Dependency.package_name))).all())
    return {
        "dependencies": [{"ecosystem": d.ecosystem, "package_name": d.package_name, "version_spec": d.version_spec, "dep_type": d.dep_type, "manifest_path": d.manifest_path,
                          "used_by_tracked_repositories": shared_counts.get(d.package_name, 1)} for d in deps],
        "analysed": repo.sync_level == "full",
        "note": "Parsed from root-level manifests (package.json, requirements.txt, pyproject.toml, go.mod, Cargo.toml). Nested workspaces and lockfiles are not analysed.",
        "data_source": repo.data_source,
    }


@router.get("/{repository_id}/forks", summary="Fork family: parent and most-starred forks")
async def forks(repository_id: int, principal: Principal = Depends(get_principal), db: AsyncSession = Depends(get_db)) -> dict:
    repo = await get_repo_or_404(db, repository_id)
    rows = (await db.scalars(select(ForkRelationship).where(ForkRelationship.parent_repository_id == repo.id).order_by(ForkRelationship.stars.desc()).limit(30))).all()
    parent = None
    if repo.parent_full_name:
        parent_id = await db.scalar(select(Repository.id).where(Repository.full_name == repo.parent_full_name))
        parent = {"full_name": repo.parent_full_name, "repository_id": parent_id,
                  "html_url": f"https://github.com/{repo.parent_full_name}" if repo.data_source == DataSource.LIVE.value else None}
    return {
        "total_forks": repo.forks, "is_fork": repo.is_fork, "parent": parent, "source_full_name": repo.source_full_name,
        "forks": [{"full_name": f.fork_full_name, "html_url": f.fork_html_url, "stars": f.stars, "pushed_at": f.pushed_at, "created_at": f.created_at_github} for f in rows],
        "note": "Shows up to 20 of the most-starred forks captured at the last full sync.",
        "data_source": repo.data_source,
    }


@router.get("/{repository_id}/releases", summary="Release history")
async def releases(repository_id: int, principal: Principal = Depends(get_principal), db: AsyncSession = Depends(get_db)) -> dict:
    repo = await get_repo_or_404(db, repository_id)
    rows = (await db.scalars(select(Release).where(Release.repository_id == repo.id).order_by(Release.published_at.desc().nulls_last()).limit(50))).all()
    return {"releases": [{"tag_name": r.tag_name, "name": r.name, "published_at": r.published_at, "prerelease": r.prerelease, "html_url": r.html_url, "body_excerpt": r.body_excerpt} for r in rows],
            "analysed": repo.sync_level == "full", "data_source": repo.data_source}


@router.get("/{repository_id}/score", summary="Business potential score with evidence")
async def score(repository_id: int, principal: Principal = Depends(get_principal), db: AsyncSession = Depends(get_db)) -> dict:
    repo = await get_repo_or_404(db, repository_id)
    row = await current_score(db, repo.id)
    if row is None:
        cache = PeerCache()
        row, result, facts = await score_repository(db, repo, cache)
        await refresh_opportunity(db, repo, result, facts, cache)
        await db.commit()
    history = (await db.execute(select(OpportunityScore.computed_at, OpportunityScore.total_default).where(OpportunityScore.repository_id == repo.id).order_by(OpportunityScore.computed_at).limit(120))).all()
    return dict(present_score(row, await get_weights(db, principal.organisation_id)), data_source=repo.data_source,
                history=[{"date": d.date().isoformat(), "total_default": t} for d, t in history])


@router.post("/{repository_id}/sync", status_code=202, summary="Queue a full sync from GitHub")
async def sync(repository_id: int, principal: Principal = Depends(require_verified_analyst), db: AsyncSession = Depends(get_db)) -> dict:
    repo = await get_repo_or_404(db, repository_id)
    if repo.data_source == DataSource.DEMO.value:
        raise HTTPException(status_code=400, detail={"code": "demo_fixture", "message": "Demo fixtures are fictional and cannot be synced with GitHub."})
    await enforce_monthly_limit(db, principal.organisation_id, "live_syncs", "live_syncs_per_month", "live GitHub requests")
    await record_usage(db, principal.organisation_id, "live_syncs")
    job = await jobs.enqueue_and_maybe_run(db, "sync_repository", {"repository_id": repo.id, "user_id": principal.user_id, "force": True}, dedupe_key=f"sync_repository:{repo.id}")
    return {"job_id": job.id, "status": job.status, "message": job.last_error or ("Sync complete." if job.status == "succeeded" else "Sync queued; the background worker will process it shortly.")}
