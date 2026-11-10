"""Glue between stored data and the pure scoring / opportunity engines."""

import datetime as dt

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.logging_config import get_logger
from app.models import (
    CommitActivity,
    Contributor,
    Opportunity,
    OpportunityScore,
    Release,
    Repository,
    RepositorySnapshot,
    RepositoryTechnology,
    ScoringConfig,
    Technology,
    utcnow,
)
from app.services.opportunities import build_analysis, maturity_of, summarise
from app.services.scoring import (
    DEFAULT_WEIGHTS,
    METHODOLOGY_NOTE,
    RepoFacts,
    ScoreResult,
    compute_score,
    raw_total_from_metrics,
    total_from_metrics,
)

log = get_logger("intelligence")

OPPORTUNITY_MIN_SCORE = 30.0
OPPORTUNITY_MIN_METRICS = 3


class PeerCache:
    """Per-run cache of category peers so scoring N repositories stays O(N)."""

    def __init__(self) -> None:
        self._by_category: dict[tuple[str, str], list[tuple[int, str, int]]] = {}

    async def peers(self, session: AsyncSession, category: str | None, data_source: str) -> list[tuple[int, str, int]]:
        if not category:
            return []
        key = (category, data_source)
        if key not in self._by_category:
            rows = await session.execute(
                select(Repository.id, Repository.full_name, Repository.stars)
                .where(Repository.category == category, Repository.data_source == data_source, Repository.archived.is_(False))
                .order_by(Repository.stars.desc()).limit(500)
            )
            self._by_category[key] = [tuple(r) for r in rows.all()]
        return self._by_category[key]


async def build_facts(session: AsyncSession, repo: Repository, peer_cache: PeerCache | None = None, now: dt.datetime | None = None) -> RepoFacts:
    now = now or utcnow()
    peer_cache = peer_cache or PeerCache()
    tech_slugs = list((await session.scalars(
        select(Technology.slug).join(RepositoryTechnology, RepositoryTechnology.technology_id == Technology.id)
        .where(RepositoryTechnology.repository_id == repo.id))).all())
    weeks = (await session.execute(
        select(CommitActivity.week_start, CommitActivity.commits).where(CommitActivity.repository_id == repo.id)
        .order_by(CommitActivity.week_start.desc()).limit(52))).all()
    weekly_commits = [c for _, c in reversed(weeks)] if weeks else None
    full = repo.sync_level == "full"
    release_dates = None
    if full:
        release_dates = [d for d in (await session.scalars(select(Release.published_at).where(Release.repository_id == repo.id))).all() if d]
    snaps = (await session.execute(
        select(RepositorySnapshot.captured_on, RepositorySnapshot.stars, RepositorySnapshot.contributors_count)
        .where(RepositorySnapshot.repository_id == repo.id, RepositorySnapshot.captured_on >= (now.date() - dt.timedelta(days=120)))
        .order_by(RepositorySnapshot.captured_on))).all()
    contribs = list((await session.scalars(select(Contributor.contributions).where(Contributor.repository_id == repo.id))).all())
    top_share = (max(contribs) / sum(contribs)) if contribs and sum(contribs) > 0 else None
    peers = [s for pid, _, s in await peer_cache.peers(session, repo.category, repo.data_source) if pid != repo.id]
    return RepoFacts(
        full_name=repo.full_name, html_url=repo.html_url, stars=repo.stars, forks=repo.forks, now=now,
        data_source=repo.data_source, sync_level=repo.sync_level, watchers=repo.watchers, open_issues=repo.open_issues,
        closed_issues=repo.closed_issues, open_prs=repo.open_prs, merged_prs=repo.merged_prs,
        contributors_count=repo.contributors_count, top_contributor_share=top_share, is_fork=repo.is_fork,
        archived=repo.archived, owner_type=repo.owner_type, has_homepage=bool(repo.homepage), license_spdx=repo.license_spdx,
        category=repo.category, technologies=tech_slugs, topics=list(repo.topics or []), description=repo.description or "",
        created_at=repo.created_at_github, pushed_at=repo.pushed_at_github, last_synced_at=repo.last_synced_at,
        weekly_commits=weekly_commits, release_dates=release_dates,
        star_history=[(d, s) for d, s, _ in snaps],
        contributor_history=[(d, c) for d, _, c in snaps if c is not None],
        peer_stars=peers,
    )


async def score_repository(session: AsyncSession, repo: Repository, peer_cache: PeerCache | None = None,
                           now: dt.datetime | None = None) -> tuple[OpportunityScore, ScoreResult, RepoFacts]:
    """Compute and persist the current score (one row per repository per day; history retained)."""
    now = now or utcnow()
    facts = await build_facts(session, repo, peer_cache, now)
    result = compute_score(facts)
    current = await session.scalar(
        select(OpportunityScore).where(OpportunityScore.repository_id == repo.id, OpportunityScore.is_current.is_(True))
        .order_by(OpportunityScore.computed_at.desc()))
    if current is not None and current.computed_at.date() == now.date():
        row = current
    else:
        if current is not None:
            current.is_current = False
        row = OpportunityScore(repository_id=repo.id, total_default=0.0, metrics=[], confidence="low")
        session.add(row)
    row.total_default = round(result.total, 2)
    row.metrics = [m.to_dict() for m in result.metrics]
    row.confidence = result.confidence
    row.confidence_value = round(result.confidence_value, 3)
    row.missing = result.missing
    row.data_freshness = result.data_freshness
    row.is_current = True
    row.computed_at = now
    await session.flush()
    return row, result, facts


async def refresh_opportunity(session: AsyncSession, repo: Repository, result: ScoreResult, facts: RepoFacts,
                              peer_cache: PeerCache) -> Opportunity | None:
    scored = sum(1 for m in result.metrics if m.score is not None)
    existing = await session.scalar(select(Opportunity).where(Opportunity.repository_id == repo.id))
    eligible = not repo.archived and not repo.is_fork and result.total >= OPPORTUNITY_MIN_SCORE and scored >= OPPORTUNITY_MIN_METRICS
    if not eligible:
        if existing is not None:
            await session.delete(existing)
        return None
    peers = await peer_cache.peers(session, repo.category, repo.data_source)
    adjacent = [
        {"repository_id": pid, "full_name": name, "stars": stars, "basis": "verified_fact",
         "note": "Tracked in the same category; adjacency is inferred from classification, not confirmed competition."}
        for pid, name, stars in peers if pid != repo.id][:5]
    analysis = build_analysis(facts, result, adjacent)
    maturity, _ = maturity_of(facts)
    if existing is None:
        existing = Opportunity(repository_id=repo.id, title="", score=0.0, confidence="low", risk_level="medium", maturity="unknown")
        session.add(existing)
    existing.title = f"Commercial opportunity hypothesis: {repo.full_name}"
    existing.category = repo.category
    existing.summary = summarise(facts, result, analysis)
    existing.score = round(result.total, 2)
    existing.confidence = result.confidence
    existing.risk_level = analysis["risk_level"]
    existing.maturity = maturity
    existing.analysis = analysis
    existing.data_source = repo.data_source
    existing.updated_at = utcnow()
    return existing


async def recompute_intelligence(session: AsyncSession, repository_ids: list[int] | None = None, now: dt.datetime | None = None) -> dict:
    """Re-score repositories and refresh their opportunity hypotheses."""
    query = select(Repository).order_by(Repository.id)
    if repository_ids is not None:
        query = query.where(Repository.id.in_(repository_ids))
    repos = list((await session.scalars(query)).all())
    cache = PeerCache()
    opportunities = 0
    for index, repo in enumerate(repos, start=1):
        _, result, facts = await score_repository(session, repo, cache, now)
        if await refresh_opportunity(session, repo, result, facts, cache):
            opportunities += 1
        if index % 50 == 0:
            await session.commit()
    await session.commit()
    log.info("intelligence_recomputed", repositories=len(repos), opportunities=opportunities)
    return {"repositories_scored": len(repos), "opportunities": opportunities}


async def get_weights(session: AsyncSession, organisation_id: int | None) -> dict[str, float]:
    if organisation_id is None:
        return dict(DEFAULT_WEIGHTS)
    config = await session.scalar(select(ScoringConfig).where(ScoringConfig.organisation_id == organisation_id))
    return dict(config.weights) if config else dict(DEFAULT_WEIGHTS)


def present_score(row: OpportunityScore, weights: dict[str, float]) -> dict:
    """Serialise a stored score using an organisation's weights."""
    total, coverage = total_from_metrics(row.metrics, weights)
    raw_total, _ = raw_total_from_metrics(row.metrics, weights)
    return {
        "total": round(total, 1),
        "raw_total": round(raw_total, 1),
        "default_total": round(row.total_default, 1),
        "metrics": [dict(m, weight=weights.get(m["key"], 0)) for m in row.metrics],
        "weights": weights,
        "custom_weights": weights != DEFAULT_WEIGHTS,
        "confidence": row.confidence,
        "confidence_value": row.confidence_value,
        "coverage": round(coverage, 2),
        "missing": row.missing,
        "data_freshness": row.data_freshness,
        "computed_at": row.computed_at.isoformat(),
        "methodology_note": METHODOLOGY_NOTE,
    }


async def current_score(session: AsyncSession, repository_id: int) -> OpportunityScore | None:
    return await session.scalar(
        select(OpportunityScore).where(OpportunityScore.repository_id == repository_id, OpportunityScore.is_current.is_(True))
        .order_by(OpportunityScore.computed_at.desc()))


async def purge_old_scores(session: AsyncSession, keep_days: int) -> int:
    cutoff = utcnow() - dt.timedelta(days=keep_days)
    result = await session.execute(delete(OpportunityScore).where(OpportunityScore.is_current.is_(False), OpportunityScore.computed_at < cutoff))
    return result.rowcount or 0


async def count_rows(session: AsyncSession, model, *conditions) -> int:
    return int(await session.scalar(select(func.count()).select_from(model).where(*conditions)) or 0)
