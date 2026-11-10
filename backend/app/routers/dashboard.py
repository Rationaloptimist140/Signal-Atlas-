"""Overview dashboard, ecosystem graph, global search and notifications."""

import datetime as dt

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_db
from app.deps import Principal, get_principal, get_session_principal
from app.models import (
    Competitor,
    Contributor,
    DataSource,
    Dependency,
    DeveloperProfile,
    Notification,
    Opportunity,
    OpportunityScore,
    Repository,
    RepositoryTechnology,
    Technology,
    TrendSignal,
    utcnow,
)
from app.routers.common import SourceParam, like_pattern, resolve_source, source_query
from app.routers.opportunities import _opportunity_item
from app.routers.trends import signal_items
from app.services.intelligence import get_weights
from app.taxonomy import CATEGORIES

router = APIRouter(tags=["dashboard"])


@router.get("/dashboard", summary="Intelligence summary for the overview page")
async def dashboard(source: SourceParam = source_query(), principal: Principal = Depends(get_principal), db: AsyncSession = Depends(get_db)) -> dict:
    live = int(await db.scalar(select(func.count()).select_from(Repository).where(Repository.data_source == DataSource.LIVE.value)) or 0)
    demo = int(await db.scalar(select(func.count()).select_from(Repository).where(Repository.data_source == DataSource.DEMO.value)) or 0)
    data_source = await resolve_source(db, source)
    r_cond = [Repository.data_source == data_source] if data_source else []
    s_cond = [TrendSignal.data_source == data_source] if data_source else []
    month_ago = utcnow() - dt.timedelta(days=30)

    async def count(query) -> int:
        return int(await db.scalar(query) or 0)

    repositories = await count(select(func.count()).select_from(Repository).where(*r_cond))
    technologies = await count(select(func.count(func.distinct(RepositoryTechnology.technology_id))).join(Repository, Repository.id == RepositoryTechnology.repository_id).where(*r_cond))
    trending = await count(select(func.count(func.distinct(TrendSignal.repository_id))).where(TrendSignal.repository_id.is_not(None), TrendSignal.detected_at >= month_ago, *s_cond))
    opportunities = await count(select(func.count()).select_from(Opportunity).where(*([Opportunity.data_source == data_source] if data_source else [])))
    developers = await count(select(func.count()).select_from(DeveloperProfile).where(*([DeveloperProfile.data_source == data_source] if data_source else [])))
    competitors = await count(select(func.count()).select_from(Competitor).where(Competitor.organisation_id == principal.organisation_id))
    last_sync = await db.scalar(select(func.max(Repository.last_synced_at)).where(*r_cond))
    full_synced = await count(select(func.count()).select_from(Repository).where(Repository.sync_level == "full", *r_cond))

    signals = list((await db.scalars(select(TrendSignal).where(TrendSignal.detected_at >= month_ago, *s_cond).order_by(TrendSignal.detected_at.desc(), TrendSignal.strength.desc()).limit(8))).all())
    weights = await get_weights(db, principal.organisation_id)
    opp_rows = (await db.execute(
        select(Opportunity, Repository, OpportunityScore).join(Repository, Repository.id == Opportunity.repository_id)
        .outerjoin(OpportunityScore, (OpportunityScore.repository_id == Repository.id) & OpportunityScore.is_current.is_(True))
        .where(*([Opportunity.data_source == data_source] if data_source else [])).order_by(Opportunity.score.desc()).limit(8))).all()

    mode = "empty" if not (live or demo) else "live" if data_source == DataSource.LIVE.value else "demo" if data_source == DataSource.DEMO.value else "mixed"
    settings = get_settings()
    return {
        "summary": {"repositories_monitored": repositories, "technologies_detected": technologies, "trending_projects": trending, "opportunities_discovered": opportunities,
                    "developers_analysed": developers, "competitors_monitored": competitors},
        "summary_definitions": {
            "repositories_monitored": "Public repositories stored in this Signal Atlas instance.",
            "technologies_detected": "Technology areas with at least one classified repository.",
            "trending_projects": "Repositories with at least one trend signal in the last 30 days.",
            "opportunities_discovered": "Repositories that currently meet the threshold for an opportunity hypothesis.",
            "developers_analysed": "Public contributor profiles linked to tracked repositories.",
            "competitors_monitored": "Competitors your organisation is tracking.",
        },
        "provenance": {"mode": mode, "showing": data_source or "all", "live_repositories": live, "demo_repositories": demo, "fully_synced_repositories": full_synced,
                       "last_synced_at": last_sync,
                       "message": {"empty": "No data yet. Search GitHub or load the demo fixtures to begin.",
                                   "demo": "Showing fictional demonstration fixtures. No figure on this page describes a real project.",
                                   "live": "Showing verified public GitHub data collected by this instance.",
                                   "mixed": "Showing live GitHub data and demo fixtures together."}[mode]},
        "signals": await signal_items(db, signals),
        "top_opportunities": [_opportunity_item(o, r, s, weights) for o, r, s in opp_rows],
        "setup": {"github_token_configured": bool(settings.github_token), "github_oauth_configured": settings.github_oauth_configured,
                  "llm_configured": settings.llm_configured, "llm_provider": settings.llm_provider},
    }


@router.get("/ecosystem/graph", summary="Nodes and edges for the technology ecosystem map")
async def ecosystem_graph(category: str | None = Query(None, max_length=60), limit: int = Query(24, ge=5, le=60), source: SourceParam = source_query(),
                          principal: Principal = Depends(get_principal), db: AsyncSession = Depends(get_db)) -> dict:
    data_source = await resolve_source(db, source)
    query = select(Repository).order_by(Repository.stars.desc()).limit(limit)
    if data_source:
        query = query.where(Repository.data_source == data_source)
    if category:
        query = query.where(Repository.category == category)
    repos = list((await db.scalars(query)).all())
    ids = [r.id for r in repos]
    nodes: dict[str, dict] = {}
    edges: list[dict] = []

    def node(node_id: str, kind: str, label: str, **meta) -> None:
        nodes.setdefault(node_id, {"id": node_id, "type": kind, "label": label, **meta})

    by_name = {r.full_name: r for r in repos}
    for repo in repos:
        node(f"repo:{repo.id}", "repository", repo.full_name, ref_id=repo.id, stars=repo.stars, category=repo.category, data_source=repo.data_source)
        if repo.owner_type == "Organization":
            node(f"org:{repo.owner_login}", "company", repo.owner_login)
            edges.append({"source": f"org:{repo.owner_login}", "target": f"repo:{repo.id}", "type": "maintains"})
        if repo.parent_full_name and repo.parent_full_name in by_name:
            edges.append({"source": f"repo:{by_name[repo.parent_full_name].id}", "target": f"repo:{repo.id}", "type": "fork"})
    if ids:
        for repo_id, slug, name in (await db.execute(
                select(RepositoryTechnology.repository_id, Technology.slug, Technology.name).join(Technology, Technology.id == RepositoryTechnology.technology_id)
                .where(RepositoryTechnology.repository_id.in_(ids), RepositoryTechnology.confidence >= 0.7))).all():
            node(f"tech:{slug}", "technology", name, slug=slug)
            edges.append({"source": f"repo:{repo_id}", "target": f"tech:{slug}", "type": "uses_technology"})
        # developers who connect at least two of the displayed repositories
        shared_devs = (await db.execute(
            select(Contributor.developer_id).where(Contributor.repository_id.in_(ids)).group_by(Contributor.developer_id)
            .having(func.count(func.distinct(Contributor.repository_id)) >= 2).limit(20))).scalars().all()
        if shared_devs:
            for dev_id, login, repo_id in (await db.execute(
                    select(DeveloperProfile.id, DeveloperProfile.login, Contributor.repository_id).join(Contributor, Contributor.developer_id == DeveloperProfile.id)
                    .where(DeveloperProfile.id.in_(shared_devs), Contributor.repository_id.in_(ids)))).all():
                node(f"dev:{dev_id}", "developer", login, ref_id=dev_id)
                edges.append({"source": f"dev:{dev_id}", "target": f"repo:{repo_id}", "type": "contributes"})
        # packages depended on by at least two displayed repositories
        shared_packages = (await db.execute(
            select(Dependency.ecosystem, Dependency.package_name).where(Dependency.repository_id.in_(ids), Dependency.dep_type == "runtime")
            .group_by(Dependency.ecosystem, Dependency.package_name).having(func.count(func.distinct(Dependency.repository_id)) >= 2)
            .order_by(func.count(func.distinct(Dependency.repository_id)).desc()).limit(15))).all()
        for ecosystem, package in shared_packages:
            node(f"pkg:{ecosystem}:{package}", "dependency", package, ecosystem=ecosystem)
            for (repo_id,) in (await db.execute(select(Dependency.repository_id).where(
                    Dependency.repository_id.in_(ids), Dependency.ecosystem == ecosystem, Dependency.package_name == package, Dependency.dep_type == "runtime").distinct())).all():
                edges.append({"source": f"repo:{repo_id}", "target": f"pkg:{ecosystem}:{package}", "type": "depends_on"})
    return {"nodes": list(nodes.values()), "edges": edges, "data_source": data_source or "all",
            "legend": {"repository": "Tracked repository", "technology": "Technology (inferred classification)", "company": "Owning organisation account",
                       "developer": "Developer contributing to 2+ shown repositories", "dependency": "Package used by 2+ shown repositories"},
            "note": "Shows the most-starred tracked repositories. Technology links are inferred; all other links come from GitHub data."}


@router.get("/search", summary="Global search across repositories, developers, technologies and opportunities")
async def global_search(q: str = Query(..., min_length=2, max_length=100), source: SourceParam = source_query(),
                        principal: Principal = Depends(get_principal), db: AsyncSession = Depends(get_db)) -> dict:
    pattern = like_pattern(q.strip())
    data_source = await resolve_source(db, source)
    repo_q = select(Repository).where(or_(Repository.full_name.ilike(pattern, escape="\\"), Repository.description.ilike(pattern, escape="\\"))).order_by(Repository.stars.desc()).limit(6)
    dev_q = select(DeveloperProfile).where(or_(DeveloperProfile.login.ilike(pattern, escape="\\"), DeveloperProfile.name.ilike(pattern, escape="\\"))).limit(5)
    opp_q = select(Opportunity, Repository.full_name).join(Repository, Repository.id == Opportunity.repository_id).where(Repository.full_name.ilike(pattern, escape="\\")).order_by(Opportunity.score.desc()).limit(5)
    if data_source:
        repo_q, dev_q, opp_q = repo_q.where(Repository.data_source == data_source), dev_q.where(DeveloperProfile.data_source == data_source), opp_q.where(Opportunity.data_source == data_source)
    techs = (await db.scalars(select(Technology).where(Technology.name.ilike(pattern, escape="\\")).limit(5))).all()
    return {
        "repositories": [{"id": r.id, "title": r.full_name, "subtitle": r.description, "link": f"/repositories/{r.id}", "data_source": r.data_source} for r in (await db.scalars(repo_q)).all()],
        "developers": [{"id": d.id, "title": d.login, "subtitle": d.name, "link": f"/developers/{d.id}", "data_source": d.data_source} for d in (await db.scalars(dev_q)).all()],
        "technologies": [{"id": t.id, "title": t.name, "subtitle": CATEGORIES.get(t.category, t.category), "link": f"/technologies?technology={t.slug}"} for t in techs],
        "opportunities": [{"id": o.id, "title": name, "subtitle": f"Score {o.score:.0f} - {o.risk_level} risk", "link": f"/opportunities/{o.id}", "data_source": o.data_source} for o, name in (await db.execute(opp_q)).all()],
    }


@router.get("/notifications", tags=["notifications"], summary="Notification centre")
async def notifications(limit: int = Query(30, ge=1, le=100), principal: Principal = Depends(get_session_principal), db: AsyncSession = Depends(get_db)) -> dict:
    rows = (await db.scalars(select(Notification).where(Notification.organisation_id == principal.organisation_id).order_by(Notification.created_at.desc()).limit(limit))).all()
    unread = int(await db.scalar(select(func.count()).select_from(Notification).where(Notification.organisation_id == principal.organisation_id, Notification.read_at.is_(None))) or 0)
    return {"items": [{"id": n.id, "kind": n.kind, "title": n.title, "body": n.body, "link": n.link, "read": n.read_at is not None, "created_at": n.created_at} for n in rows], "unread": unread}


@router.post("/notifications/read-all", status_code=204, tags=["notifications"], summary="Mark all notifications read")
async def read_all(principal: Principal = Depends(get_session_principal), db: AsyncSession = Depends(get_db)) -> None:
    await db.execute(update(Notification).where(Notification.organisation_id == principal.organisation_id, Notification.read_at.is_(None)).values(read_at=utcnow()))
    await db.commit()


@router.post("/notifications/{notification_id}/read", status_code=204, tags=["notifications"], summary="Mark one notification read")
async def read_one(notification_id: int, principal: Principal = Depends(get_session_principal), db: AsyncSession = Depends(get_db)) -> None:
    note = await db.scalar(select(Notification).where(Notification.id == notification_id, Notification.organisation_id == principal.organisation_id))
    if note is None:
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": "Notification not found."})
    note.read_at = note.read_at or utcnow()
    await db.commit()
