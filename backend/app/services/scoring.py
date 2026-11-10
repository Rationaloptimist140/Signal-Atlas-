"""Business Potential Scoring - a transparent 0-100 framework.

Design rules
------------
* Pure functions: the same ``RepoFacts`` always produce the same score.
* Every metric is built from named components. A component with no data is *dropped* and
  reported under ``missing`` - it is never silently replaced by a guess.
* Metric scores are independent of weights, so an organisation can re-weight without recomputation.
* The score ranks repositories by observable signals. It is **not** a prediction of commercial
  success and has not been validated against outcomes.
"""

import datetime as dt
import math
from dataclasses import dataclass, field

DEFAULT_WEIGHTS: dict[str, float] = {
    "development_momentum": 20,
    "developer_adoption": 15,
    "community_growth": 10,
    "technical_innovation": 15,
    "commercial_potential": 20,
    "market_demand": 10,
    "competitive_positioning": 10,
}

METRIC_LABELS: dict[str, str] = {
    "development_momentum": "Development momentum",
    "developer_adoption": "Developer adoption",
    "community_growth": "Community growth",
    "technical_innovation": "Technical innovation",
    "commercial_potential": "Commercial potential",
    "market_demand": "Market demand",
    "competitive_positioning": "Competitive positioning",
}

METHODOLOGY_NOTE = (
    "Scores rank repositories by observable public signals. They are heuristics, not predictions, "
    "and have not been validated against commercial outcomes. Metrics without data are excluded and the "
    "total is damped towards a neutral 50 in proportion to the missing weight."
)

PERMISSIVE = {"MIT", "Apache-2.0", "BSD-2-Clause", "BSD-3-Clause", "ISC", "Unlicense", "0BSD", "Zlib", "CC0-1.0", "BSL-1.0"}
WEAK_COPYLEFT = {"MPL-2.0", "LGPL-2.1", "LGPL-3.0", "EPL-2.0", "EPL-1.0"}
STRONG_COPYLEFT = {"GPL-2.0", "GPL-3.0"}
NETWORK_COPYLEFT = {"AGPL-3.0"}
SOURCE_AVAILABLE = {"BUSL-1.1", "SSPL-1.0", "Elastic-2.0"}

CATEGORY_AFFINITY = {
    "data-infrastructure": 85,
    "cybersecurity": 85,
    "developer-infrastructure": 80,
    "enterprise-software": 80,
    "ai-ml": 80,
    "cloud-computing": 75,
    "automation": 75,
    "fintech": 75,
    "blockchain": 50,
}
RELEASE_FETCH_LIMIT = 100  # most recent releases fetched per sync

COMMERCIAL_KEYWORDS = [
    "enterprise", "saas", "self-hosted", "selfhosted", "platform", "managed", "b2b", "compliance",
    "sso", "team", "teams", "cloud", "open-core", "production-ready", "scalable", "api",
]


@dataclass
class Evidence:
    label: str
    value: str
    kind: str  # verified | calculated | inferred
    source_url: str | None = None

    def to_dict(self) -> dict:
        return {"label": self.label, "value": self.value, "kind": self.kind, "source_url": self.source_url}


@dataclass
class RepoFacts:
    full_name: str
    html_url: str | None
    stars: int
    forks: int
    now: dt.datetime
    data_source: str = "live_github"
    sync_level: str = "search"
    watchers: int | None = None
    open_issues: int | None = None
    closed_issues: int | None = None
    open_prs: int | None = None
    merged_prs: int | None = None
    contributors_count: int | None = None
    top_contributor_share: float | None = None
    is_fork: bool = False
    archived: bool = False
    owner_type: str | None = None
    has_homepage: bool = False
    license_spdx: str | None = None
    category: str | None = None
    technologies: list[str] = field(default_factory=list)
    topics: list[str] = field(default_factory=list)
    description: str = ""
    created_at: dt.datetime | None = None
    pushed_at: dt.datetime | None = None
    last_synced_at: dt.datetime | None = None
    weekly_commits: list[int] | None = None  # oldest -> newest
    release_dates: list[dt.datetime] | None = None
    star_history: list[tuple[dt.date, int]] = field(default_factory=list)
    contributor_history: list[tuple[dt.date, int]] = field(default_factory=list)
    peer_stars: list[int] | None = None  # other repositories in the same category in our dataset


@dataclass
class Component:
    key: str
    weight: float
    score: float | None
    evidence: Evidence | None = None
    missing_reason: str | None = None
    confidence: float = 1.0


@dataclass
class MetricResult:
    key: str
    label: str
    score: float | None
    explanation: str
    evidence: list[Evidence]
    missing: list[str]
    confidence: float

    def to_dict(self) -> dict:
        return {
            "key": self.key,
            "label": self.label,
            "score": None if self.score is None else round(self.score, 1),
            "explanation": self.explanation,
            "evidence": [e.to_dict() for e in self.evidence],
            "missing": self.missing,
            "confidence": round(self.confidence, 2),
        }


@dataclass
class ScoreResult:
    total: float
    metrics: list[MetricResult]
    weights: dict[str, float]
    confidence: str
    confidence_value: float
    coverage: float
    missing: list[str]
    data_freshness: dict

    def to_dict(self) -> dict:
        return {
            "total": round(self.total, 1),
            "metrics": [dict(m.to_dict(), weight=self.weights.get(m.key, 0)) for m in self.metrics],
            "weights": self.weights,
            "confidence": self.confidence,
            "confidence_value": round(self.confidence_value, 2),
            "coverage": round(self.coverage, 2),
            "missing": self.missing,
            "data_freshness": self.data_freshness,
            "methodology_note": METHODOLOGY_NOTE,
        }


# ----------------------------------------------------------------------------- helpers


def clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


def log_scale(value: float, reference: float) -> float:
    """0 at 0, 100 at ``reference`` (and above), logarithmic in between."""
    if value <= 0:
        return 0.0
    return clamp(100.0 * math.log1p(value) / math.log1p(reference))


def validate_weights(weights: dict[str, float]) -> dict[str, float]:
    if set(weights) != set(DEFAULT_WEIGHTS):
        raise ValueError(f"weights must contain exactly: {', '.join(DEFAULT_WEIGHTS)}")
    cleaned = {k: float(v) for k, v in weights.items()}
    if any(v < 0 or v > 100 for v in cleaned.values()):
        raise ValueError("each weight must be between 0 and 100")
    if abs(sum(cleaned.values()) - 100.0) > 0.01:
        raise ValueError("weights must sum to 100")
    return cleaned


def _combine(key: str, components: list[Component], explanation: str, extra_missing: list[str] | None = None,
             confidence_cap: float = 1.0) -> MetricResult:
    available = [c for c in components if c.score is not None]
    total_weight = sum(c.weight for c in components)
    avail_weight = sum(c.weight for c in available)
    missing = [c.missing_reason for c in components if c.score is None and c.missing_reason]
    missing += extra_missing or []
    evidence = [c.evidence for c in available if c.evidence]
    if not available or avail_weight / total_weight < 0.35:
        return MetricResult(key, METRIC_LABELS[key], None, explanation + " Not enough data to score this metric yet.", evidence, missing, 0.0)
    score = sum(c.score * c.weight for c in available) / avail_weight
    confidence = sum(c.weight * c.confidence for c in available) / total_weight
    return MetricResult(key, METRIC_LABELS[key], clamp(score), explanation, evidence, missing, min(confidence, confidence_cap))


def _age_days(facts: RepoFacts) -> float | None:
    if not facts.created_at:
        return None
    return max((facts.now - facts.created_at).total_seconds() / 86400.0, 1.0)


def growth_rate_30d(history: list[tuple[dt.date, int]], min_span_days: int = 7, lookback_days: int = 45) -> tuple[float, int, int, int] | None:
    """Percentage growth normalised to 30 days from dated measurements.

    Returns ``(pct_per_30d, start_value, end_value, span_days)`` or ``None`` when history is too short.
    """
    if len(history) < 2:
        return None
    ordered = sorted(history)
    end_date, end_value = ordered[-1]
    candidates = [(d, v) for d, v in ordered[:-1] if (end_date - d).days <= lookback_days]
    if not candidates:
        return None
    start_date, start_value = candidates[0]
    span = (end_date - start_date).days
    if span < min_span_days or start_value <= 0:
        return None
    pct = (end_value - start_value) / start_value * 100.0 * (30.0 / span)
    return pct, start_value, end_value, span


# ----------------------------------------------------------------------------- metrics


def development_momentum(f: RepoFacts) -> MetricResult:
    comps: list[Component] = []
    wc = f.weekly_commits
    if wc is not None and len(wc) >= 4:
        last4 = sum(wc[-4:])
        comps.append(Component("commits_4w", 0.35, log_scale(last4, 400), Evidence("Commits in the last 4 weeks", str(last4), "verified", f.html_url and f"{f.html_url}/graphs/commit-activity")))
    else:
        comps.append(Component("commits_4w", 0.35, None, missing_reason="Weekly commit activity not synced yet (requires a full sync)."))
    if wc is not None and len(wc) >= 16:
        recent = sum(wc[-4:]) / 4.0
        prior = sum(wc[-16:-4]) / 12.0
        if prior == 0:
            trend = 100.0 if recent > 0 else 0.0
            ratio_text = "new activity after a quiet quarter" if recent > 0 else "no commits in 16 weeks"
        else:
            ratio = recent / prior
            trend = clamp(50.0 + 50.0 * (ratio - 1.0))
            ratio_text = f"{ratio:.2f}x the prior 12-week average"
        comps.append(Component("commit_trend", 0.25, trend, Evidence("Commit trend (last 4 weeks vs prior 12)", ratio_text, "calculated")))
    else:
        comps.append(Component("commit_trend", 0.25, None, missing_reason="Fewer than 16 weeks of commit history available for a trend."))
    if f.pushed_at:
        days = (f.now - f.pushed_at).total_seconds() / 86400.0
        recency = 100 if days <= 7 else 80 if days <= 30 else 50 if days <= 90 else 25 if days <= 180 else 10 if days <= 365 else 0
        comps.append(Component("push_recency", 0.25, float(recency), Evidence("Days since last push", f"{max(days, 0):.0f}", "verified", f.html_url)))
    else:
        comps.append(Component("push_recency", 0.25, None, missing_reason="Last push date unknown."))
    if f.release_dates is not None:
        recent_rel = sum(1 for d in f.release_dates if (f.now - d).days <= 180)
        # Only the most recent RELEASE_FETCH_LIMIT releases are fetched; if they all fall inside the window the true count may be higher.
        truncated = len(f.release_dates) >= RELEASE_FETCH_LIMIT and recent_rel == len(f.release_dates)
        comps.append(Component("release_cadence", 0.15, log_scale(recent_rel, 12), Evidence("Releases in the last 180 days", f"{recent_rel}{'+' if truncated else ''}", "verified", f.html_url and f"{f.html_url}/releases")))
    else:
        comps.append(Component("release_cadence", 0.15, None, missing_reason="Release history not synced yet."))
    result = _combine("development_momentum", comps, "How actively the project is being developed right now: recent commits, the commit trend, push recency and release cadence.")
    if f.archived and result.score is not None:
        result.score = min(result.score, 5.0)
        result.explanation += " The repository is archived, so momentum is capped."
    return result


def developer_adoption(f: RepoFacts) -> MetricResult:
    comps = [
        Component("stars", 0.5, log_scale(f.stars, 100_000), Evidence("Stars", f"{f.stars:,}", "verified", f.html_url)),
        Component("forks", 0.3, log_scale(f.forks, 10_000), Evidence("Forks", f"{f.forks:,}", "verified", f.html_url)),
    ]
    if f.watchers is not None:
        comps.append(Component("watchers", 0.2, log_scale(f.watchers, 3000), Evidence("Watchers (subscribers)", f"{f.watchers:,}", "verified", f.html_url)))
    else:
        comps.append(Component("watchers", 0.2, None, missing_reason="Watcher count is only available after a full sync."))
    return _combine("developer_adoption", comps, "How widely developers have adopted the project, measured on a logarithmic scale of stars, forks and watchers.",
                    extra_missing=["Package download and dependent-repository counts are not collected yet."])


def community_growth(f: RepoFacts) -> MetricResult:
    comps: list[Component] = []
    growth = growth_rate_30d(f.star_history)
    age = _age_days(f)
    if growth:
        pct, start, end, span = growth
        comps.append(Component("star_growth", 0.5, clamp(100.0 * pct / 20.0), Evidence("Star growth (normalised to 30 days)", f"{pct:+.1f}% ({start:,} -> {end:,} over {span} days)", "calculated")))
    elif age:
        per_day = f.stars / age
        comps.append(Component("star_growth", 0.5, log_scale(per_day, 50), Evidence("Lifetime average stars per day (recent growth not yet measurable)", f"{per_day:.2f}", "calculated"), confidence=0.5))
    else:
        comps.append(Component("star_growth", 0.5, None, missing_reason="No snapshot history or creation date to measure growth."))
    if f.contributors_count is not None:
        comps.append(Component("contributors", 0.3, log_scale(f.contributors_count, 300), Evidence("Contributors", f"{f.contributors_count:,}", "verified", f.html_url and f"{f.html_url}/graphs/contributors")))
    else:
        comps.append(Component("contributors", 0.3, None, missing_reason="Contributor count is only available after a full sync."))
    cgrowth = growth_rate_30d(f.contributor_history)
    if cgrowth:
        pct, start, end, span = cgrowth
        comps.append(Component("contributor_growth", 0.2, clamp(100.0 * pct / 10.0), Evidence("Contributor growth (normalised to 30 days)", f"{pct:+.1f}% ({start} -> {end})", "calculated")))
    else:
        comps.append(Component("contributor_growth", 0.2, None, missing_reason="Contributor growth needs at least two snapshots a week apart."))
    extra = [] if growth else ["Recent star growth needs at least two snapshots a week apart; a lifetime average is used meanwhile."]
    return _combine("community_growth", comps, "Whether the community around the project is growing: star growth between snapshots, contributor count and contributor growth.", extra_missing=extra)


def technical_innovation(f: RepoFacts) -> MetricResult:
    from app.taxonomy import EMERGING_TECHNOLOGIES

    comps: list[Component] = []
    age = _age_days(f)
    if age:
        per_day = f.stars / age
        comps.append(Component("traction_for_age", 0.4, log_scale(per_day, 30), Evidence("Stars per day since creation", f"{per_day:.2f} (age {age:.0f} days)", "calculated")))
    else:
        comps.append(Component("traction_for_age", 0.4, None, missing_reason="Creation date unknown."))
    if f.technologies:
        hits = sorted(set(f.technologies) & EMERGING_TECHNOLOGIES)
        score = 100.0 if len(hits) >= 2 else 70.0 if len(hits) == 1 else 30.0
        comps.append(Component("frontier_alignment", 0.3, score, Evidence("Frontier technology areas matched", ", ".join(hits) or "none", "inferred")))
    else:
        comps.append(Component("frontier_alignment", 0.3, None, missing_reason="No technology classification matched this repository."))
    comps.append(Component("originality", 0.15, 20.0 if f.is_fork else 100.0, Evidence("Original project (not a fork)", "no" if f.is_fork else "yes", "verified", f.html_url)))
    if f.merged_prs is not None:
        comps.append(Component("engineering_throughput", 0.15, log_scale(f.merged_prs, 2000), Evidence("Merged pull requests", f"{f.merged_prs:,}", "verified", f.html_url and f"{f.html_url}/pulls?q=is%3Amerged")))
    else:
        comps.append(Component("engineering_throughput", 0.15, None, missing_reason="Pull request totals require a GitHub token (GraphQL)."))
    return _combine("technical_innovation", comps,
                    "A proxy only: innovation cannot be measured directly from metadata. Combines traction relative to age, alignment with frontier technology areas, originality and engineering throughput.",
                    extra_missing=["No code-level novelty analysis is performed."], confidence_cap=0.6)


def licence_score(spdx: str | None) -> tuple[float, str]:
    if not spdx:
        return 10.0, "No licence detected - reuse is legally unclear"
    if spdx in PERMISSIVE:
        return 100.0, "Permissive licence - commercial reuse generally allowed"
    if spdx in WEAK_COPYLEFT:
        return 70.0, "Weak copyleft - commercial use possible with file/library-level obligations"
    if spdx in STRONG_COPYLEFT:
        return 45.0, "Strong copyleft - derivative works must be released under the same licence"
    if spdx in NETWORK_COPYLEFT:
        return 35.0, "Network copyleft (AGPL) - hosted derivatives must publish source; often the basis of open-core models"
    if spdx in SOURCE_AVAILABLE:
        return 20.0, "Source-available licence - third-party commercial hosting is typically restricted"
    return 30.0, "Non-standard or unrecognised licence - requires legal review"


def commercial_potential(f: RepoFacts) -> MetricResult:
    lic, lic_text = licence_score(f.license_spdx)
    comps = [Component("licence", 0.3, lic, Evidence("Licence", f"{f.license_spdx or 'none detected'} - {lic_text}", "verified" if f.license_spdx else "inferred", f.html_url))]
    if f.category:
        comps.append(Component("category_affinity", 0.25, float(CATEGORY_AFFINITY.get(f.category, 40)), Evidence("Category commercial affinity (editorial heuristic)", f.category, "inferred")))
    else:
        comps.append(Component("category_affinity", 0.25, None, missing_reason="Repository is not classified into a technology category."))
    text = " ".join([f.description or "", " ".join(f.topics)]).lower()
    hits = sorted({k for k in COMMERCIAL_KEYWORDS if k in text})
    comps.append(Component("commercial_signals", 0.25, clamp(25.0 * len(hits)), Evidence("Commercial-intent keywords in description/topics", ", ".join(hits) or "none", "inferred"), confidence=0.7))
    backing = (70.0 if f.owner_type == "Organization" else 25.0) + (30.0 if f.has_homepage else 0.0)
    comps.append(Component("backing", 0.2, clamp(backing), Evidence("Maintained by", f"{f.owner_type or 'unknown owner type'}{' with a project website' if f.has_homepage else ''}", "verified", f.html_url), confidence=0.8 if f.owner_type else 0.4))
    return _combine("commercial_potential", comps,
                    "Structural suitability for a commercial offering: licence terms, category affinity, commercial-intent signals and organisational backing. This is a hypothesis generator, not validation.",
                    extra_missing=["No revenue, pricing or customer data is available for open-source repositories."], confidence_cap=0.75)


def market_demand(f: RepoFacts) -> MetricResult:
    comps: list[Component] = []
    if f.open_issues is not None and f.closed_issues is not None:
        total = f.open_issues + f.closed_issues
        comps.append(Component("issue_volume", 0.4, log_scale(total, 5000), Evidence("Issues opened (all time)", f"{total:,}", "verified", f.html_url and f"{f.html_url}/issues")))
    elif f.open_issues is not None:
        comps.append(Component("issue_volume", 0.4, log_scale(f.open_issues, 1000), Evidence("Open issues and pull requests", f"{f.open_issues:,}", "verified", f.html_url and f"{f.html_url}/issues"), confidence=0.6))
    else:
        comps.append(Component("issue_volume", 0.4, None, missing_reason="Issue counts unavailable."))
    if f.stars >= 20:
        ratio = f.forks / f.stars
        comps.append(Component("fork_intent", 0.3, clamp(100.0 * ratio / 0.25), Evidence("Fork-to-star ratio (people building on it)", f"{ratio:.3f}", "calculated")))
    else:
        comps.append(Component("fork_intent", 0.3, None, missing_reason="Too few stars for a meaningful fork ratio."))
    if f.open_prs is not None and f.merged_prs is not None:
        prs = f.open_prs + f.merged_prs
        comps.append(Component("pr_demand", 0.3, log_scale(prs, 3000), Evidence("Pull requests (open + merged)", f"{prs:,}", "verified", f.html_url and f"{f.html_url}/pulls")))
    else:
        comps.append(Component("pr_demand", 0.3, None, missing_reason="Pull request totals require a GitHub token (GraphQL)."))
    return _combine("market_demand", comps,
                    "Demand inferred from repository activity only: issue volume, fork intent and pull-request demand.",
                    extra_missing=["No external market data (search volume, job postings, funding, surveys) is integrated yet."], confidence_cap=0.6)


def competitive_positioning(f: RepoFacts) -> MetricResult:
    peers = f.peer_stars
    explanation = "Position relative to other repositories in the same category within the Signal Atlas dataset - not the whole market."
    if not peers or len(peers) < 5:
        n = len(peers or [])
        return MetricResult("competitive_positioning", METRIC_LABELS["competitive_positioning"], None, explanation + " Not enough data to score this metric yet.", [],
                            [f"Only {n} comparable repositories tracked in this category (5 needed)."], 0.0)
    below = sum(1 for s in peers if s < f.stars)
    percentile = 100.0 * below / len(peers)
    leader = max(max(peers), f.stars)
    gap = 100.0 * f.stars / leader if leader else 0.0
    comps = [
        Component("category_rank", 0.6, percentile, Evidence("Star percentile within category", f"{percentile:.0f}th of {len(peers)} tracked peers", "calculated")),
        Component("leadership_gap", 0.4, clamp(gap), Evidence("Stars relative to the category leader in our dataset", f"{gap:.0f}%", "calculated")),
    ]
    conf_cap = 0.5 if len(peers) < 15 else 0.7
    return _combine("competitive_positioning", comps, explanation, extra_missing=["Closed-source and commercial competitors are not represented."], confidence_cap=conf_cap)


METRIC_FUNCS = {
    "development_momentum": development_momentum,
    "developer_adoption": developer_adoption,
    "community_growth": community_growth,
    "technical_innovation": technical_innovation,
    "commercial_potential": commercial_potential,
    "market_demand": market_demand,
    "competitive_positioning": competitive_positioning,
}


def _freshness(f: RepoFacts) -> tuple[dict, float]:
    if not f.last_synced_at:
        return {"last_synced_at": None, "age_hours": None, "status": "never_synced"}, 0.5
    hours = (f.now - f.last_synced_at).total_seconds() / 3600.0
    status, factor = ("fresh", 1.0) if hours <= 48 else ("recent", 0.9) if hours <= 168 else ("stale", 0.7) if hours <= 720 else ("outdated", 0.5)
    return {"last_synced_at": f.last_synced_at.isoformat(), "age_hours": round(hours, 1), "status": status}, factor


NEUTRAL_SCORE = 50.0


def total_from_metrics(metrics: list[dict], weights: dict[str, float]) -> tuple[float, float]:
    """Weighted total from stored metric dicts, damped for missing data.

    1. Unscored metrics are excluded and the remaining weights renormalised (the *raw* mean).
    2. The raw mean is then pulled towards a neutral 50 in proportion to the weight that has no
       data: ``total = 50 + (raw - 50) * coverage``. A repository known only from headline figures
       therefore cannot outrank a fully analysed one on thin evidence alone.

    Returns ``(total, coverage)`` where coverage is the share of weight backed by data.
    """
    raw, coverage = raw_total_from_metrics(metrics, weights)
    if coverage <= 0:
        return 0.0, 0.0
    return NEUTRAL_SCORE + (raw - NEUTRAL_SCORE) * coverage, coverage


def raw_total_from_metrics(metrics: list[dict], weights: dict[str, float]) -> tuple[float, float]:
    """Weighted mean over scored metrics only (no damping) and the data coverage."""
    weight_sum = sum(weights.values()) or 1.0
    scored = [(m["score"], weights.get(m["key"], 0.0)) for m in metrics if m.get("score") is not None]
    avail = sum(w for _, w in scored)
    if avail <= 0:
        return 0.0, 0.0
    return sum(s * w for s, w in scored) / avail, avail / weight_sum


def confidence_label(value: float) -> str:
    return "high" if value >= 0.7 else "medium" if value >= 0.45 else "low"


def compute_score(facts: RepoFacts, weights: dict[str, float] | None = None) -> ScoreResult:
    weights = validate_weights(weights) if weights else dict(DEFAULT_WEIGHTS)
    metrics = [func(facts) for func in METRIC_FUNCS.values()]
    total, coverage = total_from_metrics([m.to_dict() for m in metrics], weights)
    freshness, fresh_factor = _freshness(facts)
    weight_sum = sum(weights.values()) or 1.0
    metric_conf = sum(m.confidence * weights[m.key] for m in metrics) / weight_sum
    level_factor = 1.0 if facts.sync_level == "full" else 0.8
    conf_value = clamp(metric_conf * fresh_factor * level_factor, 0.0, 1.0)
    missing: list[str] = []
    for m in metrics:
        for item in m.missing:
            if item not in missing:
                missing.append(item)
    return ScoreResult(total, metrics, weights, confidence_label(conf_value), conf_value, coverage, missing, freshness)
