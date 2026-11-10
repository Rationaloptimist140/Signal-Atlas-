"""Emerging technology detection.

Signals are derived from dated snapshots and GitHub-computed commit history. A signal is a
statement that something changed - not a forecast. Each signal lists the evidence it rests on.
"""

import datetime as dt
import statistics

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.logging_config import get_logger
from app.models import (
    CommitActivity,
    Release,
    Repository,
    RepositorySnapshot,
    RepositoryTechnology,
    Technology,
    TrendSignal,
    utcnow,
)
from app.services.scoring import RELEASE_FETCH_LIMIT
from app.taxonomy import CATEGORIES

log = get_logger("trends")

WINDOWS: dict[str, int] = {"daily": 1, "weekly": 7, "monthly": 30}
STAR_THRESHOLDS = {"daily": (25, 1.0), "weekly": (100, 4.0), "monthly": (300, 10.0)}  # (min new stars, min % growth)


def period_key(window: str, day: dt.date) -> str:
    if window == "daily":
        return day.isoformat()
    if window == "weekly":
        iso = day.isocalendar()
        return f"{iso.year}-W{iso.week:02d}"
    return f"{day.year}-{day.month:02d}"


def window_delta(history: list[tuple[dt.date, int]], today: dt.date, days: int) -> tuple[int, int, int] | None:
    """Return ``(start_value, end_value, span_days)`` for the snapshot pair best matching the window."""
    if len(history) < 2:
        return None
    ordered = sorted(history)
    end_day, end_value = ordered[-1]
    if (today - end_day).days > max(2, days // 2):
        return None  # latest measurement is itself stale
    target = end_day - dt.timedelta(days=days)
    candidates = [(d, v) for d, v in ordered[:-1] if abs((d - target).days) <= max(1, days // 3)]
    if not candidates:
        return None
    start_day, start_value = min(candidates, key=lambda item: abs((item[0] - target).days))
    span = (end_day - start_day).days
    return (start_value, end_value, span) if span > 0 else None


def robust_z(value: float, population: list[float]) -> float | None:
    if len(population) < 8:
        return None
    median = statistics.median(population)
    mad = statistics.median([abs(x - median) for x in population])
    if mad == 0:
        return None
    return 0.6745 * (value - median) / mad


def _ev(label: str, value: str, kind: str, url: str | None = None) -> dict:
    return {"label": label, "value": value, "kind": kind, "source_url": url}


async def _upsert(session: AsyncSession, seen: set[str], key: str, **fields) -> None:
    seen.add(key)
    signal = await session.scalar(select(TrendSignal).where(TrendSignal.dedupe_key == key))
    if signal is None:
        session.add(TrendSignal(dedupe_key=key, detected_at=fields.pop("detected_at"), **fields))
        return
    fields.pop("detected_at", None)  # keep the original discovery date
    for name, value in fields.items():
        setattr(signal, name, value)


async def detect_trends(session: AsyncSession, now: dt.datetime | None = None) -> dict:
    now = now or utcnow()
    today = now.date()
    seen: set[str] = set()
    repos = list((await session.scalars(select(Repository).where(Repository.archived.is_(False)))).all())
    since = today - dt.timedelta(days=45)
    history: dict[int, list[tuple[dt.date, int]]] = {}
    contributor_history: dict[int, list[tuple[dt.date, int]]] = {}
    for rid, day, stars, contributors in (await session.execute(
            select(RepositorySnapshot.repository_id, RepositorySnapshot.captured_on, RepositorySnapshot.stars, RepositorySnapshot.contributors_count)
            .where(RepositorySnapshot.captured_on >= since))).all():
        history.setdefault(rid, []).append((day, stars))
        if contributors is not None:
            contributor_history.setdefault(rid, []).append((day, contributors))
    commits: dict[int, list[tuple[dt.date, int]]] = {}
    for rid, week, count in (await session.execute(
            select(CommitActivity.repository_id, CommitActivity.week_start, CommitActivity.commits)
            .where(CommitActivity.week_start >= today - dt.timedelta(days=7 * 17)))).all():
        commits.setdefault(rid, []).append((week, count))
    releases: dict[int, list[dt.datetime]] = {}
    for rid, published in (await session.execute(
            select(Release.repository_id, Release.published_at).where(Release.published_at >= now - dt.timedelta(days=120)))).all():
        releases.setdefault(rid, []).append(published)

    release_totals = dict((await session.execute(select(Release.repository_id, func.count()).group_by(Release.repository_id))).all())

    created = 0
    growth_by_window: dict[str, dict[int, tuple[float, int, int, int]]] = {w: {} for w in WINDOWS}
    for repo in repos:
        for window, days in WINDOWS.items():
            delta = window_delta(history.get(repo.id, []), today, days)
            if delta and delta[0] > 0:
                start, end, span = delta
                growth_by_window[window][repo.id] = ((end - start) / start * 100.0, start, end, span)

    by_id = {r.id: r for r in repos}
    for window, growth in growth_by_window.items():
        min_new, min_pct = STAR_THRESHOLDS[window]
        for repo_id, (pct, start, end, span) in growth.items():
            repo = by_id[repo_id]
            peers = [g[0] for rid, g in growth.items() if rid != repo_id and by_id[rid].category == repo.category and by_id[rid].data_source == repo.data_source]
            z = robust_z(pct, peers)
            unusual = z is not None and z >= 3.0 and (end - start) >= min_new / 2
            if not ((end - start) >= min_new and pct >= min_pct) and not unusual:
                continue
            evidence = [
                _ev(f"Stars {span} days ago", f"{start:,}", "verified", repo.html_url),
                _ev("Stars now", f"{end:,}", "verified", repo.html_url),
                _ev("Growth over the window", f"+{end - start:,} ({pct:+.1f}%)", "calculated"),
            ]
            if z is not None:
                evidence.append(_ev("Deviation from category peers (robust z-score)", f"{z:.1f} across {len(peers)} peers", "calculated"))
            await _upsert(
                session, seen, f"star_surge:{repo.id}:{window}:{period_key(window, today)}",
                repository_id=repo.id, category=repo.category, signal_type="unusual_growth" if unusual else "star_surge",
                time_window=window, strength=min(100.0, pct / (min_pct * 5) * 100.0), confidence="high" if span >= WINDOWS[window] else "medium",
                title=f"{repo.full_name} gained {end - start:,} stars in {span} day{'s' if span != 1 else ''}",
                summary=(f"Star count rose {pct:.1f}% between two Signal Atlas snapshots"
                         + (", well above comparable projects in its category." if unusual else ".")
                         + " Rapid attention often precedes ecosystem adoption, but it does not by itself indicate commercial demand."),
                evidence=evidence, data_source=repo.data_source, detected_at=now)
            created += 1

    for repo in repos:
        weeks = sorted(commits.get(repo.id, []))
        if len(weeks) >= 16:
            counts = [c for _, c in weeks][-16:]
            recent, prior = sum(counts[-4:]) / 4.0, sum(counts[:12]) / 12.0
            if sum(counts[-4:]) >= 20 and prior > 0 and recent / prior >= 2.0:
                ratio = recent / prior
                await _upsert(
                    session, seen, f"commit_acceleration:{repo.id}:monthly:{period_key('monthly', today)}",
                    repository_id=repo.id, category=repo.category, signal_type="commit_acceleration", time_window="monthly",
                    strength=min(100.0, ratio / 5.0 * 100.0), confidence="high",
                    title=f"{repo.full_name} development pace is {ratio:.1f}x its previous quarter",
                    summary="Weekly commits over the last four weeks are running well above the prior twelve-week average, suggesting renewed investment in the project.",
                    evidence=[_ev("Average weekly commits, last 4 weeks", f"{recent:.1f}", "verified", repo.html_url and f"{repo.html_url}/graphs/commit-activity"),
                              _ev("Average weekly commits, prior 12 weeks", f"{prior:.1f}", "verified", repo.html_url and f"{repo.html_url}/graphs/commit-activity"),
                              _ev("Acceleration", f"{ratio:.2f}x", "calculated")],
                    data_source=repo.data_source, detected_at=now)
                created += 1

        if repo.created_at_github and not repo.is_fork:
            age = max((now - repo.created_at_github).days, 1)
            if age <= 120 and repo.stars >= 500:
                per_day = repo.stars / age
                window = "weekly" if age <= 21 else "monthly"
                await _upsert(
                    session, seen, f"breakout_new_project:{repo.id}:{window}:{period_key(window, today)}",
                    repository_id=repo.id, category=repo.category, signal_type="breakout_new_project", time_window=window,
                    strength=min(100.0, per_day / 100.0 * 100.0), confidence="medium",
                    title=f"{repo.full_name} reached {repo.stars:,} stars within {age} days of creation",
                    summary="A new project attracting attention this quickly marks a change in developer interest. The figure is a lifetime average; recent growth is tracked as snapshots accumulate.",
                    evidence=[_ev("Repository created", repo.created_at_github.date().isoformat(), "verified", repo.html_url),
                              _ev("Stars", f"{repo.stars:,}", "verified", repo.html_url),
                              _ev("Average stars per day since creation", f"{per_day:.1f}", "calculated")],
                    data_source=repo.data_source, detected_at=now)
                created += 1

        cdelta = window_delta(contributor_history.get(repo.id, []), today, 30)
        if cdelta and cdelta[0] > 0 and (cdelta[1] - cdelta[0]) >= 5 and (cdelta[1] - cdelta[0]) / cdelta[0] >= 0.15:
            start, end, span = cdelta
            await _upsert(
                session, seen, f"contributor_growth:{repo.id}:monthly:{period_key('monthly', today)}",
                repository_id=repo.id, category=repo.category, signal_type="contributor_growth", time_window="monthly",
                strength=min(100.0, (end - start) / start * 200.0), confidence="high",
                title=f"{repo.full_name} added {end - start} contributors in {span} days",
                summary="A growing contributor base indicates the project is spreading beyond its original authors.",
                evidence=[_ev(f"Contributors {span} days ago", str(start), "verified", repo.html_url), _ev("Contributors now", str(end), "verified", repo.html_url)],
                data_source=repo.data_source, detected_at=now)
            created += 1

        rel = releases.get(repo.id, [])
        last30 = sum(1 for d in rel if (now - d).days <= 30)
        prior90 = sum(1 for d in rel if 30 < (now - d).days <= 120)
        # Only the latest RELEASE_FETCH_LIMIT releases are stored. If that many all fall inside the last 120 days
        # the baseline is unknown, so no burst is claimed.
        baseline_known = release_totals.get(repo.id, 0) < RELEASE_FETCH_LIMIT or release_totals.get(repo.id, 0) > len(rel)
        if not baseline_known:
            continue
        if last30 >= 3 and last30 > 2 * (prior90 / 3.0):
            await _upsert(
                session, seen, f"release_burst:{repo.id}:monthly:{period_key('monthly', today)}",
                repository_id=repo.id, category=repo.category, signal_type="release_burst", time_window="monthly",
                strength=min(100.0, last30 * 12.5), confidence="high",
                title=f"{repo.full_name} shipped {last30} releases in 30 days",
                summary="Release frequency is well above the project's recent baseline, which usually accompanies a major version push or a growing user base.",
                evidence=[_ev("Releases in the last 30 days", str(last30), "verified", repo.html_url and f"{repo.html_url}/releases"),
                          _ev("Releases in the 90 days before that", str(prior90), "verified", repo.html_url and f"{repo.html_url}/releases")],
                data_source=repo.data_source, detected_at=now)
            created += 1

    # ---- category momentum and emerging clusters (aggregates)
    for source in {r.data_source for r in repos}:
        for window in ("weekly", "monthly"):
            per_category: dict[str, list[float]] = {}
            for rid, (pct, *_rest) in growth_by_window[window].items():
                repo = by_id[rid]
                if repo.category and repo.data_source == source:
                    per_category.setdefault(repo.category, []).append(pct)
            medians = {c: statistics.median(v) for c, v in per_category.items() if len(v) >= 5}
            if len(medians) >= 2:
                overall = statistics.median(medians.values())
                for category, median in medians.items():
                    if median >= 1.0 and median >= overall * 1.5:
                        await _upsert(
                            session, seen, f"category_momentum:{category}:{source}:{window}:{period_key(window, today)}",
                            repository_id=None, category=category, signal_type="category_momentum", time_window=window,
                            strength=min(100.0, median * 10.0), confidence="medium",
                            title=f"{CATEGORIES.get(category, category)} is outpacing other categories",
                            summary=f"The median tracked repository in this category grew {median:.1f}% in stars over the window, against {overall:.1f}% across categories. Based only on repositories tracked by Signal Atlas.",
                            evidence=[_ev("Median star growth in category", f"{median:.1f}%", "calculated"), _ev("Median across categories", f"{overall:.1f}%", "calculated"),
                                      _ev("Repositories measured", str(len(per_category[category])), "calculated")],
                            data_source=source, detected_at=now)
                        created += 1

        year_ago = now - dt.timedelta(days=365)
        rows = (await session.execute(
            select(Technology.slug, Technology.name, Technology.category, Repository.id, Repository.full_name, Repository.stars)
            .join(RepositoryTechnology, RepositoryTechnology.technology_id == Technology.id)
            .join(Repository, Repository.id == RepositoryTechnology.repository_id)
            .where(Repository.created_at_github >= year_ago, Repository.stars >= 300, Repository.is_fork.is_(False),
                   Repository.data_source == source, RepositoryTechnology.confidence >= 0.7))).all()
        clusters: dict[str, list] = {}
        for slug, name, category, rid, full_name, stars in rows:
            clusters.setdefault(slug, []).append((name, category, rid, full_name, stars))
        for slug, members in clusters.items():
            if len(members) < 3:
                continue
            members.sort(key=lambda m: -m[4])
            name, category = members[0][0], members[0][1]
            await _upsert(
                session, seen, f"emerging_cluster:{slug}:{source}:monthly:{period_key('monthly', today)}",
                repository_id=None, category=category, signal_type="emerging_cluster", time_window="monthly",
                strength=min(100.0, len(members) * 12.5), confidence="medium",
                title=f"Emerging cluster: {len(members)} new {name} projects with early traction",
                summary=f"{len(members)} repositories created in the last 12 months and classified under {name} have each passed 300 stars. Clusters of new projects suggest an area where approaches are still being contested.",
                evidence=[_ev(full_name, f"{stars:,} stars", "verified", f"https://github.com/{full_name}" if source == "live_github" else None) for _, _, _, full_name, stars in members[:6]],
                data_source=source, detected_at=now)
            created += 1

    # Retract signals from the *current* period that no longer hold (e.g. after fuller data arrived).
    # Signals from earlier periods are history and are kept.
    current_suffixes = tuple(f":{window}:{period_key(window, today)}" for window in WINDOWS)
    retracted = 0
    for signal in (await session.scalars(select(TrendSignal).where(TrendSignal.detected_at >= now - dt.timedelta(days=32)))).all():
        if signal.dedupe_key.endswith(current_suffixes) and signal.dedupe_key not in seen:
            await session.delete(signal)
            retracted += 1
    await session.commit()
    log.info("trends_detected", signals=created, retracted=retracted)
    return {"signals": created, "retracted": retracted}
