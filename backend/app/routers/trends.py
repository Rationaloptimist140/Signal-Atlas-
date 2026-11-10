"""Emerging Technology Detection (Engine 3) and technology exploration."""

import datetime as dt
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.deps import Principal, get_principal
from app.models import (
    CommitActivity,
    Repository,
    RepositorySnapshot,
    RepositoryTechnology,
    Technology,
    TrendSignal,
    utcnow,
)
from app.routers.common import SourceParam, repo_list_items, resolve_source, source_query
from app.schemas import TrendSignalOut
from app.services.intelligence import get_weights
from app.taxonomy import CATEGORIES, EMERGING_TECHNOLOGIES

router = APIRouter(tags=["trends"])


async def signal_items(db: AsyncSession, signals: list[TrendSignal]) -> list[TrendSignalOut]:
    repo_ids = [s.repository_id for s in signals if s.repository_id]
    names = dict((await db.execute(select(Repository.id, Repository.full_name).where(Repository.id.in_(repo_ids)))).all()) if repo_ids else {}
    items = []
    for signal in signals:
        item = TrendSignalOut.model_validate(signal)
        item.repository_full_name = names.get(signal.repository_id)
        items.append(item)
    return items


@router.get("/trends", summary="Emerging signals by daily, weekly or monthly window")
async def list_trends(
    window: Literal["daily", "weekly", "monthly", "all"] = "all",
    category: str | None = Query(None, max_length=60),
    signal_type: str | None = Query(None, max_length=40),
    source: SourceParam = source_query(),
    limit: int = Query(50, ge=1, le=200),
    principal: Principal = Depends(get_principal),
    db: AsyncSession = Depends(get_db),
) -> dict:
    data_source = await resolve_source(db, source)
    query = select(TrendSignal).where(TrendSignal.detected_at >= utcnow() - dt.timedelta(days=45))
    if data_source:
        query = query.where(TrendSignal.data_source == data_source)
    if window != "all":
        query = query.where(TrendSignal.time_window == window)
    if category:
        query = query.where(TrendSignal.category == category)
    if signal_type:
        query = query.where(TrendSignal.signal_type == signal_type)
    signals = list((await db.scalars(query.order_by(TrendSignal.detected_at.desc(), TrendSignal.strength.desc()).limit(limit))).all())
    counts = dict((await db.execute(select(TrendSignal.time_window, func.count()).where(
        TrendSignal.detected_at >= utcnow() - dt.timedelta(days=45), *([TrendSignal.data_source == data_source] if data_source else [])).group_by(TrendSignal.time_window))).all())
    return {
        "items": await signal_items(db, signals),
        "counts_by_window": {w: counts.get(w, 0) for w in ("daily", "weekly", "monthly")},
        "data_source": data_source or "all",
        "methodology": "Signals compare dated Signal Atlas snapshots and GitHub-computed commit history. Daily and weekly windows need snapshots on consecutive days, so they fill in as syncs accumulate. A signal reports a change; it is not a forecast.",
    }


@router.get("/trends/momentum", summary="Time series for the technology momentum charts")
async def momentum(source: SourceParam = source_query(), weeks: int = Query(26, ge=4, le=52), principal: Principal = Depends(get_principal), db: AsyncSession = Depends(get_db)) -> dict:
    data_source = await resolve_source(db, source)
    cond = [Repository.data_source == data_source] if data_source else []
    today = utcnow().date()

    commit_rows = (await db.execute(
        select(CommitActivity.week_start, Repository.category, func.sum(CommitActivity.commits))
        .join(Repository, Repository.id == CommitActivity.repository_id)
        .where(CommitActivity.week_start >= today - dt.timedelta(weeks=weeks), Repository.category.is_not(None), *cond)
        .group_by(CommitActivity.week_start, Repository.category).order_by(CommitActivity.week_start))).all()
    commit_series: dict[str, dict] = {}
    for week, category, commits in commit_rows:
        commit_series.setdefault(week.isoformat(), {"week": week.isoformat()})[category] = int(commits or 0)

    # Star growth for a fixed cohort: repositories with a snapshot on the first day of the window,
    # so newly discovered repositories never create artificial jumps.
    start = today - dt.timedelta(days=30)
    first_day = await db.scalar(select(func.min(RepositorySnapshot.captured_on)).join(Repository, Repository.id == RepositorySnapshot.repository_id)
                                .where(RepositorySnapshot.captured_on >= start, *cond))
    star_series: list[dict] = []
    cohort_size = 0
    if first_day is not None:
        cohort = select(RepositorySnapshot.repository_id).where(RepositorySnapshot.captured_on == first_day)
        cohort_size = int(await db.scalar(select(func.count()).select_from(cohort.subquery())) or 0)
        rows = (await db.execute(
            select(RepositorySnapshot.captured_on, Repository.category, func.sum(RepositorySnapshot.stars), func.count())
            .join(Repository, Repository.id == RepositorySnapshot.repository_id)
            .where(RepositorySnapshot.captured_on >= first_day, RepositorySnapshot.repository_id.in_(cohort), Repository.category.is_not(None), *cond)
            .group_by(RepositorySnapshot.captured_on, Repository.category).order_by(RepositorySnapshot.captured_on))).all()
        baseline: dict[str, int] = {}
        by_day: dict[str, dict] = {}
        for day, category, stars, _count in rows:
            baseline.setdefault(category, int(stars or 0))
            base = baseline[category] or 1
            by_day.setdefault(day.isoformat(), {"date": day.isoformat()})[category] = round((int(stars or 0) / base - 1.0) * 100.0, 3)
        star_series = list(by_day.values())

    adoption = (await db.execute(select(Repository.category, func.count(), func.sum(Repository.stars)).where(Repository.category.is_not(None), *cond).group_by(Repository.category))).all()
    signal_counts = dict((await db.execute(select(TrendSignal.category, func.count()).where(
        TrendSignal.detected_at >= utcnow() - dt.timedelta(days=30), TrendSignal.category.is_not(None),
        *([TrendSignal.data_source == data_source] if data_source else [])).group_by(TrendSignal.category))).all())
    categories = sorted({c for c, _, _ in adoption})
    return {
        "categories": [{"key": c, "label": CATEGORIES.get(c, c)} for c in categories],
        "developer_activity": {"series": list(commit_series.values()), "unit": "commits per week", "basis": "verified (GitHub commit statistics for fully synced repositories)"},
        "repository_growth": {"series": star_series, "unit": "% star growth since first day of window", "cohort_size": cohort_size,
                              "has_history": len(star_series) >= 2, "basis": "calculated from Signal Atlas snapshots",
                              "note": None if len(star_series) >= 2 else "Growth history starts once snapshots exist on at least two different days."},
        "technology_adoption": [{"category": c, "label": CATEGORIES.get(c, c), "repositories": int(n), "stars": int(s or 0)} for c, n, s in sorted(adoption, key=lambda r: -r[1])],
        "trending_categories": [{"category": c, "label": CATEGORIES.get(c, c), "signals_30d": int(n)} for c, n in sorted(signal_counts.items(), key=lambda kv: -kv[1])],
        "data_source": data_source or "all",
    }


@router.get("/technologies", tags=["technologies"], summary="Explore technologies with aggregates")
async def list_technologies(category: str | None = Query(None, max_length=60), source: SourceParam = source_query(),
                            principal: Principal = Depends(get_principal), db: AsyncSession = Depends(get_db)) -> dict:
    data_source = await resolve_source(db, source)
    cond = [Repository.data_source == data_source] if data_source else []
    year_ago = utcnow() - dt.timedelta(days=365)
    rows = (await db.execute(
        select(Technology.id, func.count(Repository.id), func.coalesce(func.sum(Repository.stars), 0))
        .join(RepositoryTechnology, RepositoryTechnology.technology_id == Technology.id)
        .join(Repository, Repository.id == RepositoryTechnology.repository_id).where(*cond).group_by(Technology.id))).all()
    new_rows = dict((await db.execute(
        select(RepositoryTechnology.technology_id, func.count()).join(Repository, Repository.id == RepositoryTechnology.repository_id)
        .where(Repository.created_at_github >= year_ago, *cond).group_by(RepositoryTechnology.technology_id))).all())
    stats = {tid: (int(n), int(stars)) for tid, n, stars in rows}
    query = select(Technology).order_by(Technology.category, Technology.name)
    if category:
        query = query.where(Technology.category == category)
    items = []
    for tech in (await db.scalars(query)).all():
        repos, stars = stats.get(tech.id, (0, 0))
        items.append({"slug": tech.slug, "name": tech.name, "category": tech.category, "category_label": CATEGORIES.get(tech.category, tech.category),
                      "repositories": repos, "total_stars": stars, "new_repositories_12m": int(new_rows.get(tech.id, 0)),
                      "frontier": tech.slug in EMERGING_TECHNOLOGIES})
    items.sort(key=lambda i: (-i["repositories"], i["name"]))
    return {"items": items, "categories": [{"key": k, "label": v} for k, v in CATEGORIES.items()], "data_source": data_source or "all",
            "note": "Repositories are assigned to technologies by keyword classification of topics, names and descriptions (inferred, not verified)."}


@router.get("/technologies/{slug}", tags=["technologies"], summary="Technology detail with leading repositories and signals")
async def get_technology(slug: str, source: SourceParam = source_query(), principal: Principal = Depends(get_principal), db: AsyncSession = Depends(get_db)) -> dict:
    tech = await db.scalar(select(Technology).where(Technology.slug == slug))
    if tech is None:
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": "Technology not found."})
    data_source = await resolve_source(db, source)
    query = select(Repository).join(RepositoryTechnology, RepositoryTechnology.repository_id == Repository.id).where(RepositoryTechnology.technology_id == tech.id)
    if data_source:
        query = query.where(Repository.data_source == data_source)
    repos = list((await db.scalars(query.order_by(Repository.stars.desc()).limit(25))).all())
    newest = list((await db.scalars(query.where(Repository.created_at_github >= utcnow() - dt.timedelta(days=365)).order_by(Repository.stars.desc()).limit(10))).all())
    weights = await get_weights(db, principal.organisation_id)
    return {
        "technology": {"slug": tech.slug, "name": tech.name, "category": tech.category, "category_label": CATEGORIES.get(tech.category, tech.category), "frontier": tech.slug in EMERGING_TECHNOLOGIES},
        "top_repositories": await repo_list_items(db, repos, weights),
        "new_repositories_12m": await repo_list_items(db, newest, weights),
        "data_source": data_source or "all",
    }
