"""Shared query helpers for routers."""

from typing import Literal

from fastapi import HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import DataSource, Opportunity, OpportunityScore, Repository
from app.schemas import RepositoryListItem
from app.services.scoring import DEFAULT_WEIGHTS, total_from_metrics

SourceParam = Literal["auto", "live", "demo", "all"]


def like_pattern(term: str) -> str:
    """Escape LIKE wildcards in user input and wrap for a contains-match."""
    escaped = term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


async def resolve_source(db: AsyncSession, source: str) -> str | None:
    """Translate the ``source`` query parameter into a ``data_source`` filter (None = no filter).

    ``auto`` shows verified live data as soon as any exists, and demo fixtures only before that,
    so demo numbers never dilute live intelligence.
    """
    if source == "live":
        return DataSource.LIVE.value
    if source == "demo":
        return DataSource.DEMO.value
    if source == "all":
        return None
    live = await db.scalar(select(func.count()).select_from(Repository).where(Repository.data_source == DataSource.LIVE.value))
    return DataSource.LIVE.value if live else DataSource.DEMO.value


def source_query(default: str = "auto"):
    return Query(default, description="Data provenance filter: auto (live if any, else demo), live, demo or all")


async def paginate(db: AsyncSession, query, page: int, page_size: int) -> tuple[list, int]:
    total = int(await db.scalar(select(func.count()).select_from(query.order_by(None).subquery())) or 0)
    rows = (await db.execute(query.limit(page_size).offset((page - 1) * page_size))).all()
    return rows, total


async def repo_list_items(db: AsyncSession, repos: list[Repository], weights: dict[str, float]) -> list[RepositoryListItem]:
    """Attach the current score (under the caller's weights) and opportunity id to repositories."""
    if not repos:
        return []
    ids = [r.id for r in repos]
    scores = {s.repository_id: s for s in (await db.scalars(select(OpportunityScore).where(OpportunityScore.repository_id.in_(ids), OpportunityScore.is_current.is_(True)))).all()}
    opps = dict((await db.execute(select(Opportunity.repository_id, Opportunity.id).where(Opportunity.repository_id.in_(ids)))).all())
    items = []
    for repo in repos:
        item = RepositoryListItem.model_validate(repo)
        score = scores.get(repo.id)
        if score:
            item.score = score.total_default if weights == DEFAULT_WEIGHTS else round(total_from_metrics(score.metrics, weights)[0], 2)
            item.score_confidence = score.confidence
        item.opportunity_id = opps.get(repo.id)
        items.append(item)
    return items


async def get_repo_or_404(db: AsyncSession, repository_id: int) -> Repository:
    repo = await db.get(Repository, repository_id)
    if repo is None:
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": "Repository not found."})
    return repo
