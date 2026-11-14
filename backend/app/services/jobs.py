"""Durable job queue on PostgreSQL (``FOR UPDATE SKIP LOCKED``) with retries and rate-limit deferral.

No Redis is required: a solo deployment runs one API service and one worker against one database.
"""

import datetime as dt
from collections.abc import Awaitable, Callable

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.logging_config import get_logger
from app.models import (
    AuditLog,
    ChangeEvent,
    Competitor,
    CompetitorRepository,
    DataSource,
    DeveloperProfile,
    EmailToken,
    GitHubAccount,
    IntelligenceReport,
    Job,
    Notification,
    Repository,
    RepositorySnapshot,
    Watchlist,
    WatchlistItem,
    utcnow,
)
from app.security import decrypt_secret
from app.services import billing, ingestion, intelligence, trends
from app.services.github_client import GitHubClient, GitHubRateLimited
from app.services.reports import enrich_report

log = get_logger("jobs")

Handler = Callable[[AsyncSession, dict], Awaitable[dict | None]]
HANDLERS: dict[str, Handler] = {}
BACKOFF_SECONDS = [30, 120, 600, 3600]


def handler(name: str) -> Callable[[Handler], Handler]:
    def register(func: Handler) -> Handler:
        HANDLERS[name] = func
        return func
    return register


async def enqueue(session: AsyncSession, job_type: str, payload: dict | None = None, *, dedupe_key: str | None = None,
                  run_after: dt.datetime | None = None, organisation_id: int | None = None, max_attempts: int = 4) -> Job:
    """Queue a job. With ``dedupe_key`` an identical pending job is reused instead of duplicated."""
    if job_type not in HANDLERS:
        raise ValueError(f"unknown job type {job_type}")
    if dedupe_key:
        existing = await session.scalar(select(Job).where(Job.dedupe_key == dedupe_key, Job.status.in_(("queued", "running"))))
        if existing:
            return existing
    job = Job(job_type=job_type, payload=payload or {}, dedupe_key=dedupe_key, run_after=run_after or utcnow(),
              organisation_id=organisation_id, max_attempts=max_attempts)
    session.add(job)
    await session.flush()
    return job


async def claim_next(session: AsyncSession) -> Job | None:
    now = utcnow()
    query = select(Job).where(Job.status == "queued", Job.run_after <= now).order_by(Job.run_after, Job.id).limit(1)
    if session.bind is not None and session.bind.dialect.name == "postgresql":
        query = query.with_for_update(skip_locked=True)
    job = await session.scalar(query)
    if job is None:
        return None
    job.status = "running"
    job.locked_at = now
    job.attempts += 1
    await session.commit()
    return job


async def run_job(session: AsyncSession, job: Job) -> Job:
    """Execute one claimed job, recording success, retry with backoff, deferral or failure."""
    func = HANDLERS.get(job.job_type)
    try:
        if func is None:
            raise ValueError(f"no handler for {job.job_type}")
        result = await func(session, dict(job.payload or {}))
        job.status, job.result, job.last_error, job.finished_at = "succeeded", result or {}, None, utcnow()
        log.info("job_succeeded", job_id=job.id, job_type=job.job_type, attempts=job.attempts)
    except GitHubRateLimited as exc:
        await session.rollback()
        job = await session.get(Job, job.id)
        job.status = "queued"
        job.attempts = max(job.attempts - 1, 0)  # waiting for a quota reset is not a failed attempt
        job.run_after = exc.reset_at + dt.timedelta(seconds=15)
        job.last_error = "Deferred: GitHub rate limit reached"
        log.info("job_deferred", job_id=job.id, job_type=job.job_type, until=job.run_after.isoformat())
    except Exception as exc:  # noqa: BLE001 - a job must never crash the worker
        await session.rollback()
        job = await session.get(Job, job.id)
        job.last_error = f"{type(exc).__name__}: {exc}"[:1000]
        if job.attempts >= job.max_attempts:
            job.status, job.finished_at = "failed", utcnow()
            log.error("job_failed", job_id=job.id, job_type=job.job_type, error=job.last_error)
        else:
            job.status = "queued"
            job.run_after = utcnow() + dt.timedelta(seconds=BACKOFF_SECONDS[min(job.attempts - 1, len(BACKOFF_SECONDS) - 1)])
            log.warning("job_retry_scheduled", job_id=job.id, job_type=job.job_type, attempt=job.attempts, error=job.last_error)
    await session.commit()
    return job


async def run_pending(session: AsyncSession, limit: int = 50) -> int:
    """Drain due jobs (used by the worker loop, inline mode and tests)."""
    done = 0
    while done < limit:
        job = await claim_next(session)
        if job is None:
            break
        await run_job(session, job)
        done += 1
    return done


async def enqueue_and_maybe_run(session: AsyncSession, job_type: str, payload: dict | None = None, **kwargs) -> Job:
    job = await enqueue(session, job_type, payload, **kwargs)
    await session.commit()
    if get_settings().jobs_inline:
        claimed = await claim_next(session)
        while claimed is not None:
            await run_job(session, claimed)
            if claimed.id == job.id:
                break
            claimed = await claim_next(session)
        await session.refresh(job)
    return job


async def github_client_for(session: AsyncSession, user_id: int | None) -> GitHubClient:
    """Prefer the requesting user's own read-only token so their quota is used; fall back to the server token."""
    if user_id:
        account = await session.scalar(select(GitHubAccount).where(GitHubAccount.user_id == user_id))
        if account:
            token = decrypt_secret(account.access_token_encrypted)
            if token:
                return GitHubClient(token)
    return GitHubClient()


# --------------------------------------------------------------------------- handlers


@handler("sync_repository")
async def _sync_repository(session: AsyncSession, payload: dict) -> dict:
    repo = await session.get(Repository, payload["repository_id"])
    if repo is None:
        return {"status": "missing"}
    async with await github_client_for(session, payload.get("user_id")) as client:
        try:
            result = await ingestion.full_sync_repository(session, client, repo, force=bool(payload.get("force")))
        finally:
            await intelligence.recompute_intelligence(session, [repo.id])
    await notify_change_events(session, [repo.id])
    return result


@handler("sync_developer")
async def _sync_developer(session: AsyncSession, payload: dict) -> dict:
    dev = await session.get(DeveloperProfile, payload["developer_id"])
    if dev is None:
        return {"status": "missing"}
    async with await github_client_for(session, payload.get("user_id")) as client:
        await ingestion.sync_developer(session, client, dev)
    return {"status": "synced", "login": dev.login}


@handler("discover")
async def _discover(session: AsyncSession, payload: dict) -> dict:
    async with await github_client_for(session, payload.get("user_id")) as client:
        repos, total = await ingestion.discover_repositories(session, client, payload["query"], per_page=int(payload.get("per_page", 30)))
    await intelligence.recompute_intelligence(session, [r.id for r in repos])
    return {"found": len(repos), "total_available": total}


@handler("discover_all")
async def _discover_all(session: AsyncSession, payload: dict) -> dict:
    """Fan out the curated discovery queries, spaced to respect the search rate limit (10/min anonymous)."""
    now = utcnow()
    for index, (_category, template) in enumerate(ingestion.DISCOVERY_QUERIES):
        query = ingestion.render_query(template, now)
        await enqueue(session, "discover", {"query": query, "per_page": int(payload.get("per_page", 30))},
                      dedupe_key=f"discover:{query}", run_after=now + dt.timedelta(seconds=8 * index))
    await enqueue(session, "recompute_intelligence", {}, dedupe_key="recompute", run_after=now + dt.timedelta(seconds=8 * len(ingestion.DISCOVERY_QUERIES) + 30))
    await session.commit()
    return {"queued": len(ingestion.DISCOVERY_QUERIES)}


@handler("recompute_intelligence")
async def _recompute(session: AsyncSession, payload: dict) -> dict:
    summary = await intelligence.recompute_intelligence(session, payload.get("repository_ids"))
    summary.update(await trends.detect_trends(session))
    return summary


@handler("enrich_report")
async def _enrich_report(session: AsyncSession, payload: dict) -> dict:
    report = await session.get(IntelligenceReport, payload["report_id"])
    if report is None:
        return {"status": "missing"}
    await enrich_report(session, report)
    await session.commit()
    return {"status": report.status, "provider": report.provider}


async def watched_repository_ids(session: AsyncSession, organisation_id: int | None = None) -> set[int]:
    wl = select(WatchlistItem.item_id).where(WatchlistItem.item_type == "repository")
    cr = select(CompetitorRepository.repository_id).join(Competitor, Competitor.id == CompetitorRepository.competitor_id)
    if organisation_id is not None:
        wl = wl.where(WatchlistItem.organisation_id == organisation_id)
        cr = cr.where(Competitor.organisation_id == organisation_id)
    ids = set((await session.scalars(wl)).all()) | set((await session.scalars(cr)).all())
    return ids


@handler("monitor_watched")
async def _monitor_watched(session: AsyncSession, payload: dict) -> dict:
    """Re-sync every repository that any organisation watches or tracks as a competitor."""
    ids = await watched_repository_ids(session)
    cutoff = utcnow() - dt.timedelta(hours=max(get_settings().sync_interval_hours - 1, 1))
    queued = 0
    for index, repo in enumerate((await session.scalars(select(Repository).where(Repository.id.in_(ids), Repository.data_source == DataSource.LIVE.value))).all()):
        if repo.last_synced_at and repo.sync_level == "full" and repo.last_synced_at > cutoff:
            continue
        await enqueue(session, "sync_repository", {"repository_id": repo.id}, dedupe_key=f"sync_repository:{repo.id}", run_after=utcnow() + dt.timedelta(seconds=2 * index))
        queued += 1
    await session.commit()
    return {"watched": len(ids), "queued": queued}


@handler("deepen_top_repositories")
async def _deepen_top(session: AsyncSession, payload: dict) -> dict:
    """Queue full syncs for the highest-starred repositories known only from search results.

    The batch is sized to the available GitHub quota (about ten requests per repository): small
    without a token, larger with one, so discovery results gain full evidence over time.
    """
    batch = int(payload.get("limit") or (40 if get_settings().github_token else 4))
    repos = (await session.scalars(
        select(Repository).where(Repository.data_source == DataSource.LIVE.value, Repository.sync_level == "search", Repository.archived.is_(False))
        .order_by(Repository.stars.desc()).limit(batch))).all()
    for index, repo in enumerate(repos):
        await enqueue(session, "sync_repository", {"repository_id": repo.id}, dedupe_key=f"sync_repository:{repo.id}", run_after=utcnow() + dt.timedelta(seconds=3 * index))
    await session.commit()
    return {"queued": len(repos)}


@handler("retention_cleanup")
async def _retention(session: AsyncSession, payload: dict) -> dict:
    """Data-retention controls: drop old snapshots, audit logs, finished jobs and read notifications."""
    settings = get_settings()
    now = utcnow()
    snapshots = await session.execute(delete(RepositorySnapshot).where(RepositorySnapshot.captured_on < (now - dt.timedelta(days=settings.snapshot_retention_days)).date()))
    audits = await session.execute(delete(AuditLog).where(AuditLog.created_at < now - dt.timedelta(days=settings.audit_retention_days)))
    jobs = await session.execute(delete(Job).where(Job.status.in_(("succeeded", "failed")), Job.finished_at < now - dt.timedelta(days=14)))
    notes = await session.execute(delete(Notification).where(Notification.read_at.is_not(None), Notification.created_at < now - dt.timedelta(days=90)))
    scores = await intelligence.purge_old_scores(session, settings.snapshot_retention_days)
    tokens = await session.execute(delete(EmailToken).where(EmailToken.expires_at < now - dt.timedelta(days=7)))
    await session.commit()
    lapsed = await billing.expire_lapsed(session, now)
    return {"snapshots": snapshots.rowcount, "audit_logs": audits.rowcount, "jobs": jobs.rowcount, "notifications": notes.rowcount, "scores": scores,
            "email_tokens": tokens.rowcount, "subscriptions_expired": lapsed}


async def notify_change_events(session: AsyncSession, repository_ids: list[int]) -> int:
    """Create one notification per (organisation, change event) for organisations watching the repository."""
    if not repository_ids:
        return 0
    since = utcnow() - dt.timedelta(days=7)
    events = list((await session.scalars(select(ChangeEvent).where(ChangeEvent.repository_id.in_(repository_ids), ChangeEvent.detected_at >= since))).all())
    if not events:
        return 0
    watchers: dict[int, set[int]] = {}
    rows = (await session.execute(
        select(WatchlistItem.item_id, Watchlist.organisation_id).join(Watchlist, Watchlist.id == WatchlistItem.watchlist_id)
        .where(WatchlistItem.item_type == "repository", WatchlistItem.item_id.in_(repository_ids)))).all()
    rows += (await session.execute(
        select(CompetitorRepository.repository_id, Competitor.organisation_id).join(Competitor, Competitor.id == CompetitorRepository.competitor_id)
        .where(CompetitorRepository.repository_id.in_(repository_ids)))).all()
    for repo_id, org_id in rows:
        watchers.setdefault(repo_id, set()).add(org_id)
    created = 0
    for event in events:
        for org_id in watchers.get(event.repository_id, ()):
            key = f"{org_id}:change:{event.id}"
            if await session.scalar(select(Notification.id).where(Notification.dedupe_key == key)):
                continue
            session.add(Notification(organisation_id=org_id, dedupe_key=key, kind=event.event_type, title=event.title,
                                     body="Detected on a repository you monitor.", link=f"/repositories/{event.repository_id}"))
            created += 1
    await session.commit()
    return created


RECURRING: list[tuple[str, str, dict]] = [
    ("monitor_watched", "recurring:monitor_watched", {}),
    ("deepen_top_repositories", "recurring:deepen_top", {}),
    ("recompute_intelligence", "recurring:recompute", {}),
    ("retention_cleanup", "recurring:retention", {}),
]


async def schedule_recurring(session: AsyncSession) -> int:
    """Ensure each recurring job has exactly one future run queued. Called by the worker loop."""
    settings = get_settings()
    queued = 0
    recurring = list(RECURRING)
    if settings.discovery_enabled:
        recurring.append(("discover_all", "recurring:discover_all", {}))
    for job_type, key, payload in recurring:
        pending = await session.scalar(select(Job.id).where(Job.dedupe_key == key, Job.status.in_(("queued", "running"))))
        if pending:
            continue
        last = await session.scalar(select(Job).where(Job.dedupe_key == key, Job.status == "succeeded").order_by(Job.finished_at.desc()))
        run_after = utcnow() if last is None else (last.finished_at or utcnow()) + dt.timedelta(hours=settings.sync_interval_hours)
        await enqueue(session, job_type, payload, dedupe_key=key, run_after=run_after)
        queued += 1
    await session.commit()
    return queued
