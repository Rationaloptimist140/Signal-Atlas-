"""Competitive Intelligence (Engine 5) and watchlists. Everything here is tenant-scoped."""

import datetime as dt

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.deps import Principal, get_principal, require_analyst, require_verified
from app.models import (
    ChangeEvent,
    Competitor,
    CompetitorRepository,
    DeveloperProfile,
    Opportunity,
    Release,
    Repository,
    RepositorySnapshot,
    Watchlist,
    WatchlistItem,
    utcnow,
)
from app.routers.common import repo_list_items
from app.schemas import CompetitorIn, CompetitorRepoIn, CompetitorUpdateIn, WatchlistIn, WatchlistItemIn
from app.services import ingestion, jobs
from app.services.github_client import GitHubError, GitHubNotFound, GitHubRateLimited
from app.services.intelligence import get_weights
from app.services.usage import audit, enforce_count_limit, org_plan

router = APIRouter(tags=["competitors"])


async def _competitor_or_404(db: AsyncSession, competitor_id: int, organisation_id: int) -> Competitor:
    competitor = await db.scalar(select(Competitor).where(Competitor.id == competitor_id, Competitor.organisation_id == organisation_id))
    if competitor is None:
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": "Competitor not found."})
    return competitor


async def _competitor_repos(db: AsyncSession, competitor_id: int) -> list[Repository]:
    return list((await db.scalars(
        select(Repository).join(CompetitorRepository, CompetitorRepository.repository_id == Repository.id)
        .where(CompetitorRepository.competitor_id == competitor_id).order_by(Repository.stars.desc()))).all())


@router.get("/competitors", summary="Competitors monitored by your organisation")
async def list_competitors(principal: Principal = Depends(get_principal), db: AsyncSession = Depends(get_db)) -> dict:
    competitors = list((await db.scalars(select(Competitor).where(Competitor.organisation_id == principal.organisation_id).order_by(Competitor.name))).all())
    since = utcnow() - dt.timedelta(days=30)
    items = []
    for competitor in competitors:
        repos = await _competitor_repos(db, competitor.id)
        ids = [r.id for r in repos]
        changes = int(await db.scalar(select(func.count()).select_from(ChangeEvent).where(ChangeEvent.repository_id.in_(ids), ChangeEvent.occurred_at >= since)) or 0) if ids else 0
        latest = await db.scalar(select(func.max(ChangeEvent.occurred_at)).where(ChangeEvent.repository_id.in_(ids))) if ids else None
        items.append({"id": competitor.id, "name": competitor.name, "description": competitor.description, "website": competitor.website, "github_org": competitor.github_org,
                      "repository_count": len(repos), "total_stars": sum(r.stars for r in repos), "changes_30d": changes, "latest_change_at": latest,
                      "repositories": [{"id": r.id, "full_name": r.full_name, "data_source": r.data_source} for r in repos[:5]], "created_at": competitor.created_at})
    plan = await org_plan(db, principal.organisation_id)
    return {"items": items, "limit": plan.competitors, "used": len(items)}


@router.post("/competitors", status_code=201, summary="Start monitoring a competitor")
async def create_competitor(body: CompetitorIn, principal: Principal = Depends(require_analyst), db: AsyncSession = Depends(get_db)) -> dict:
    plan = await org_plan(db, principal.organisation_id)
    count = int(await db.scalar(select(func.count()).select_from(Competitor).where(Competitor.organisation_id == principal.organisation_id)) or 0)
    enforce_count_limit(plan, "competitors", count, "monitored competitors")
    competitor = Competitor(organisation_id=principal.organisation_id, name=body.name.strip(), description=body.description, website=body.website,
                            github_org=body.github_org, created_by=principal.user_id)
    db.add(competitor)
    try:
        await db.flush()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(status_code=409, detail={"code": "duplicate", "message": "You already monitor a competitor with this name."}) from exc
    for repo_id in dict.fromkeys(body.repository_ids):
        if await db.get(Repository, repo_id):
            db.add(CompetitorRepository(competitor_id=competitor.id, repository_id=repo_id))
    await audit(db, "competitor.created", organisation_id=principal.organisation_id, user_id=principal.user_id, target_type="competitor", target_id=competitor.id)
    await db.commit()
    return {"id": competitor.id, "name": competitor.name}


@router.get("/competitors/{competitor_id}", summary="Competitor detail: repositories, comparison and detected changes")
async def get_competitor(competitor_id: int, principal: Principal = Depends(get_principal), db: AsyncSession = Depends(get_db)) -> dict:
    competitor = await _competitor_or_404(db, competitor_id, principal.organisation_id)
    repos = await _competitor_repos(db, competitor.id)
    ids = [r.id for r in repos]
    items = await repo_list_items(db, repos, await get_weights(db, principal.organisation_id))
    comparison = []
    month_ago = utcnow().date() - dt.timedelta(days=30)
    for repo, item in zip(repos, items, strict=True):
        earlier = await db.scalar(select(RepositorySnapshot.stars).where(RepositorySnapshot.repository_id == repo.id, RepositorySnapshot.captured_on <= month_ago)
                                  .order_by(RepositorySnapshot.captured_on.desc()))
        latest_release = await db.scalar(select(Release).where(Release.repository_id == repo.id, Release.published_at.is_not(None)).order_by(Release.published_at.desc()))
        comparison.append({"repository_id": repo.id, "full_name": repo.full_name, "stars": repo.stars, "forks": repo.forks, "contributors": repo.contributors_count,
                           "primary_language": repo.primary_language, "pushed_at": repo.pushed_at_github, "score": item.score, "score_confidence": item.score_confidence,
                           "stars_30d_change": (repo.stars - earlier) if earlier is not None else None,
                           "latest_release": {"tag_name": latest_release.tag_name, "published_at": latest_release.published_at, "html_url": latest_release.html_url} if latest_release else None,
                           "sync_level": repo.sync_level, "data_source": repo.data_source})
    events = list((await db.scalars(select(ChangeEvent).where(ChangeEvent.repository_id.in_(ids)).order_by(ChangeEvent.occurred_at.desc()).limit(50))).all()) if ids else []
    names = {r.id: r.full_name for r in repos}
    return {
        "competitor": {"id": competitor.id, "name": competitor.name, "description": competitor.description, "website": competitor.website, "github_org": competitor.github_org,
                       "created_at": competitor.created_at},
        "repositories": items,
        "comparison": comparison,
        "changes": [{"id": e.id, "repository_id": e.repository_id, "repository_full_name": names.get(e.repository_id), "event_type": e.event_type, "title": e.title,
                     "details": e.details, "evidence_url": e.evidence_url, "occurred_at": e.occurred_at, "data_source": e.data_source} for e in events],
        "monitoring_note": "Changes are detected by comparing each full sync with the previous one, so history begins at the first full sync. 30-day star change needs a snapshot at least 30 days old.",
    }


@router.patch("/competitors/{competitor_id}", summary="Update a competitor")
async def update_competitor(competitor_id: int, body: CompetitorUpdateIn, principal: Principal = Depends(require_analyst), db: AsyncSession = Depends(get_db)) -> dict:
    competitor = await _competitor_or_404(db, competitor_id, principal.organisation_id)
    for field in ("name", "description", "website"):
        value = getattr(body, field)
        if value is not None:
            setattr(competitor, field, value.strip() or None if field != "name" else value.strip())
    await db.commit()
    return {"id": competitor.id, "name": competitor.name}


@router.delete("/competitors/{competitor_id}", status_code=204, summary="Stop monitoring a competitor")
async def delete_competitor(competitor_id: int, principal: Principal = Depends(require_analyst), db: AsyncSession = Depends(get_db)) -> None:
    competitor = await _competitor_or_404(db, competitor_id, principal.organisation_id)
    await db.delete(competitor)
    await audit(db, "competitor.deleted", organisation_id=principal.organisation_id, user_id=principal.user_id, target_type="competitor", target_id=competitor_id)
    await db.commit()


@router.post("/competitors/{competitor_id}/repositories", status_code=201, summary="Attach a repository (tracked id, or owner/name fetched from GitHub)")
async def add_competitor_repository(competitor_id: int, body: CompetitorRepoIn, principal: Principal = Depends(require_analyst), db: AsyncSession = Depends(get_db)) -> dict:
    competitor = await _competitor_or_404(db, competitor_id, principal.organisation_id)
    repo = None
    if body.repository_id:
        repo = await db.get(Repository, body.repository_id)
    elif body.full_name:
        repo = await db.scalar(select(Repository).where(func.lower(Repository.full_name) == body.full_name.lower()))
        if repo is None:
            await require_verified(principal)  # fetching an untracked repository is a live GitHub operation
            async with await jobs.github_client_for(db, principal.user_id) as client:
                try:
                    repo = await ingestion.track_repository(db, client, body.full_name)
                except GitHubNotFound as exc:
                    raise HTTPException(status_code=404, detail={"code": "not_found", "message": "No public repository with that name exists on GitHub."}) from exc
                except GitHubRateLimited as exc:
                    raise HTTPException(status_code=503, detail={"code": "github_rate_limited", "message": "GitHub's API rate limit has been reached. Try again later or connect a GitHub account.", "retry_at": exc.reset_at.isoformat()}) from exc
                except GitHubError as exc:
                    raise HTTPException(status_code=502, detail={"code": "github_error", "message": str(exc)}) from exc
    if repo is None:
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": "Repository not found. Provide repository_id or full_name."})
    if not await db.scalar(select(CompetitorRepository.id).where(CompetitorRepository.competitor_id == competitor.id, CompetitorRepository.repository_id == repo.id)):
        db.add(CompetitorRepository(competitor_id=competitor.id, repository_id=repo.id))
    await db.commit()
    if repo.sync_level != "full" and repo.data_source == "live_github":
        await jobs.enqueue_and_maybe_run(db, "sync_repository", {"repository_id": repo.id, "user_id": principal.user_id}, dedupe_key=f"sync_repository:{repo.id}")
    return {"competitor_id": competitor.id, "repository_id": repo.id, "full_name": repo.full_name}


@router.delete("/competitors/{competitor_id}/repositories/{repository_id}", status_code=204, summary="Detach a repository")
async def remove_competitor_repository(competitor_id: int, repository_id: int, principal: Principal = Depends(require_analyst), db: AsyncSession = Depends(get_db)) -> None:
    competitor = await _competitor_or_404(db, competitor_id, principal.organisation_id)
    link = await db.scalar(select(CompetitorRepository).where(CompetitorRepository.competitor_id == competitor.id, CompetitorRepository.repository_id == repository_id))
    if link:
        await db.delete(link)
        await db.commit()


# ----------------------------------------------------------------------------- watchlists


async def _watchlist_or_404(db: AsyncSession, watchlist_id: int, organisation_id: int) -> Watchlist:
    watchlist = await db.scalar(select(Watchlist).where(Watchlist.id == watchlist_id, Watchlist.organisation_id == organisation_id))
    if watchlist is None:
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": "Watchlist not found."})
    return watchlist


async def _resolve_items(db: AsyncSession, items: list[WatchlistItem]) -> list[dict]:
    by_type: dict[str, list[int]] = {}
    for item in items:
        by_type.setdefault(item.item_type, []).append(item.item_id)
    repos = {r.id: r for r in (await db.scalars(select(Repository).where(Repository.id.in_(by_type.get("repository", []))))).all()} if by_type.get("repository") else {}
    devs = {d.id: d for d in (await db.scalars(select(DeveloperProfile).where(DeveloperProfile.id.in_(by_type.get("developer", []))))).all()} if by_type.get("developer") else {}
    opp_rows = (await db.execute(select(Opportunity, Repository.full_name).join(Repository, Repository.id == Opportunity.repository_id)
                                 .where(Opportunity.id.in_(by_type.get("opportunity", []))))).all() if by_type.get("opportunity") else []
    opps = {o.id: (o, name) for o, name in opp_rows}
    out = []
    for item in items:
        entry = {"id": item.id, "item_type": item.item_type, "item_id": item.item_id, "note": item.note, "created_at": item.created_at, "available": True}
        if item.item_type == "repository" and item.item_id in repos:
            r = repos[item.item_id]
            entry.update(title=r.full_name, subtitle=r.description, link=f"/repositories/{r.id}", data_source=r.data_source, stars=r.stars)
        elif item.item_type == "developer" and item.item_id in devs:
            d = devs[item.item_id]
            entry.update(title=d.login, subtitle=d.name, link=f"/developers/{d.id}", data_source=d.data_source)
        elif item.item_type == "opportunity" and item.item_id in opps:
            o, name = opps[item.item_id]
            entry.update(title=name, subtitle=o.summary, link=f"/opportunities/{o.id}", data_source=o.data_source, score=o.score)
        else:
            entry.update(title="No longer available", subtitle=None, link=None, available=False)
        out.append(entry)
    return out


@router.get("/watchlists", tags=["watchlists"], summary="Your organisation's watchlists with resolved items")
async def list_watchlists(principal: Principal = Depends(get_principal), db: AsyncSession = Depends(get_db)) -> dict:
    watchlists = list((await db.scalars(select(Watchlist).where(Watchlist.organisation_id == principal.organisation_id).order_by(Watchlist.created_at))).all())
    out = []
    total_items = 0
    for watchlist in watchlists:
        items = list((await db.scalars(select(WatchlistItem).where(WatchlistItem.watchlist_id == watchlist.id, WatchlistItem.organisation_id == principal.organisation_id)
                                       .order_by(WatchlistItem.created_at.desc()))).all())
        total_items += len(items)
        out.append({"id": watchlist.id, "name": watchlist.name, "description": watchlist.description, "created_at": watchlist.created_at, "items": await _resolve_items(db, items)})
    plan = await org_plan(db, principal.organisation_id)
    return {"items": out, "limit": plan.watchlist_items, "used": total_items}


@router.post("/watchlists", status_code=201, tags=["watchlists"], summary="Create a watchlist")
async def create_watchlist(body: WatchlistIn, principal: Principal = Depends(require_analyst), db: AsyncSession = Depends(get_db)) -> dict:
    watchlist = Watchlist(organisation_id=principal.organisation_id, created_by=principal.user_id, name=body.name.strip(), description=body.description)
    db.add(watchlist)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(status_code=409, detail={"code": "duplicate", "message": "A watchlist with this name already exists."}) from exc
    return {"id": watchlist.id, "name": watchlist.name, "description": watchlist.description, "items": []}


@router.delete("/watchlists/{watchlist_id}", status_code=204, tags=["watchlists"], summary="Delete a watchlist")
async def delete_watchlist(watchlist_id: int, principal: Principal = Depends(require_analyst), db: AsyncSession = Depends(get_db)) -> None:
    watchlist = await _watchlist_or_404(db, watchlist_id, principal.organisation_id)
    await db.delete(watchlist)
    await db.commit()


@router.post("/watchlists/{watchlist_id}/items", status_code=201, tags=["watchlists"], summary="Save a repository, opportunity or developer")
async def add_watchlist_item(watchlist_id: int, body: WatchlistItemIn, principal: Principal = Depends(require_analyst), db: AsyncSession = Depends(get_db)) -> dict:
    watchlist = await _watchlist_or_404(db, watchlist_id, principal.organisation_id)
    model = {"repository": Repository, "opportunity": Opportunity, "developer": DeveloperProfile}[body.item_type]
    target = await db.get(model, body.item_id)
    if target is None:
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": f"{body.item_type.title()} not found."})
    existing = await db.scalar(select(WatchlistItem).where(WatchlistItem.watchlist_id == watchlist.id, WatchlistItem.item_type == body.item_type, WatchlistItem.item_id == body.item_id))
    if existing:
        return {"id": existing.id, "created": False}
    plan = await org_plan(db, principal.organisation_id)
    used = int(await db.scalar(select(func.count()).select_from(WatchlistItem).where(WatchlistItem.organisation_id == principal.organisation_id)) or 0)
    enforce_count_limit(plan, "watchlist_items", used, "saved items")
    item = WatchlistItem(watchlist_id=watchlist.id, organisation_id=principal.organisation_id, item_type=body.item_type, item_id=body.item_id, note=body.note)
    db.add(item)
    await db.commit()
    if body.item_type == "repository" and target.sync_level != "full" and target.data_source == "live_github":
        await jobs.enqueue_and_maybe_run(db, "sync_repository", {"repository_id": target.id, "user_id": principal.user_id}, dedupe_key=f"sync_repository:{target.id}")
    return {"id": item.id, "created": True}


@router.delete("/watchlists/{watchlist_id}/items/{item_id}", status_code=204, tags=["watchlists"], summary="Remove a saved item")
async def remove_watchlist_item(watchlist_id: int, item_id: int, principal: Principal = Depends(require_analyst), db: AsyncSession = Depends(get_db)) -> None:
    watchlist = await _watchlist_or_404(db, watchlist_id, principal.organisation_id)
    item = await db.scalar(select(WatchlistItem).where(WatchlistItem.id == item_id, WatchlistItem.watchlist_id == watchlist.id, WatchlistItem.organisation_id == principal.organisation_id))
    if item:
        await db.delete(item)
        await db.commit()


@router.get("/watchlists/saved", tags=["watchlists"], summary="Compact map of saved items (for save buttons)")
async def saved_map(item_type: str = Query(..., pattern="^(repository|opportunity|developer)$"), principal: Principal = Depends(get_principal), db: AsyncSession = Depends(get_db)) -> dict:
    rows = (await db.execute(select(WatchlistItem.item_id, WatchlistItem.id, WatchlistItem.watchlist_id).where(
        WatchlistItem.organisation_id == principal.organisation_id, WatchlistItem.item_type == item_type))).all()
    return {"saved": {str(item_id): {"item_row_id": row_id, "watchlist_id": wl_id} for item_id, row_id, wl_id in rows}}
