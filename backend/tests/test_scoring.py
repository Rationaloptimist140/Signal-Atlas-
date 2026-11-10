import datetime as dt

import pytest

from app.services.scoring import (
    DEFAULT_WEIGHTS,
    RepoFacts,
    commercial_potential,
    compute_score,
    growth_rate_30d,
    licence_score,
    log_scale,
    raw_total_from_metrics,
    total_from_metrics,
    validate_weights,
)

NOW = dt.datetime(2026, 11, 10, tzinfo=dt.UTC)


def rich_facts(**overrides) -> RepoFacts:
    base = dict(
        full_name="acme/widget", html_url="https://github.com/acme/widget", stars=12000, forks=900, now=NOW, sync_level="full", watchers=150,
        open_issues=80, closed_issues=900, open_prs=12, merged_prs=700, contributors_count=60, license_spdx="MIT", category="ai-ml",
        technologies=["llm", "rag"], topics=["llm", "self-hosted"], description="Enterprise platform", owner_type="Organization", has_homepage=True,
        created_at=NOW - dt.timedelta(days=400), pushed_at=NOW - dt.timedelta(days=1), last_synced_at=NOW,
        weekly_commits=[10] * 12 + [30] * 4, release_dates=[NOW - dt.timedelta(days=10)],
        star_history=[(NOW.date() - dt.timedelta(days=30), 10000), (NOW.date(), 12000)], peer_stars=[100, 2000, 50000, 300, 7000, 9000],
    )
    base.update(overrides)
    return RepoFacts(**base)


def test_default_weights_match_specification():
    assert DEFAULT_WEIGHTS == {"development_momentum": 20, "developer_adoption": 15, "community_growth": 10, "technical_innovation": 15,
                               "commercial_potential": 20, "market_demand": 10, "competitive_positioning": 10}
    assert sum(DEFAULT_WEIGHTS.values()) == 100


def test_log_scale_bounds():
    assert log_scale(0, 100) == 0
    assert log_scale(100, 100) == pytest.approx(100)
    assert log_scale(10**9, 100) == 100
    assert 0 < log_scale(10, 100) < log_scale(50, 100) < 100


def test_score_is_deterministic_and_bounded():
    a, b = compute_score(rich_facts()), compute_score(rich_facts())
    assert a.to_dict() == b.to_dict()
    assert 0 <= a.total <= 100
    assert all(m.score is None or 0 <= m.score <= 100 for m in a.metrics)


def test_every_metric_has_explanation_evidence_and_confidence():
    result = compute_score(rich_facts()).to_dict()
    assert {m["key"] for m in result["metrics"]} == set(DEFAULT_WEIGHTS)
    for metric in result["metrics"]:
        assert metric["explanation"]
        assert metric["evidence"], metric["key"]
        assert 0 <= metric["confidence"] <= 1
        assert all(e["kind"] in ("verified", "calculated", "inferred") for e in metric["evidence"])
    assert result["data_freshness"]["status"] == "fresh"
    assert result["confidence"] in ("low", "medium", "high")
    assert "not predictions" in result["methodology_note"]


def test_missing_data_is_reported_not_invented():
    sparse = RepoFacts(full_name="a/b", html_url=None, stars=50, forks=3, now=NOW)
    result = compute_score(sparse)
    by_key = {m.key: m for m in result.metrics}
    assert by_key["development_momentum"].score is None  # no commit, push or release data at all
    assert by_key["competitive_positioning"].score is None
    assert any("full sync" in item for item in result.missing)
    assert result.coverage < 0.6
    assert result.confidence == "low"
    assert result.data_freshness["status"] == "never_synced"


def test_total_renormalises_over_scored_metrics():
    metrics = [{"key": "development_momentum", "score": 80.0}, {"key": "developer_adoption", "score": 40.0}, {"key": "community_growth", "score": None}]
    raw, coverage = raw_total_from_metrics(metrics, DEFAULT_WEIGHTS)
    assert raw == pytest.approx((80 * 20 + 40 * 15) / 35)
    assert coverage == pytest.approx(0.35)
    # the published total is damped towards a neutral 50 by the share of weight that has no data
    total, _ = total_from_metrics(metrics, DEFAULT_WEIGHTS)
    assert total == pytest.approx(50 + (raw - 50) * 0.35)
    full = [{"key": key, "score": 80.0} for key in DEFAULT_WEIGHTS]
    assert total_from_metrics(full, DEFAULT_WEIGHTS) == (pytest.approx(80.0), pytest.approx(1.0))  # no damping with complete data
    assert total_from_metrics([{"key": "community_growth", "score": None}], DEFAULT_WEIGHTS) == (0.0, 0.0)


def test_custom_weights_change_total_but_not_metric_scores():
    default = compute_score(rich_facts())
    weights = dict.fromkeys(DEFAULT_WEIGHTS, 0.0) | {"developer_adoption": 100.0}
    custom = compute_score(rich_facts(), weights)
    assert [m.score for m in default.metrics] == [m.score for m in custom.metrics]
    adoption = next(m.score for m in custom.metrics if m.key == "developer_adoption")
    assert custom.total == pytest.approx(adoption, abs=0.06)  # totals are derived from the stored (1 d.p.) metric scores


@pytest.mark.parametrize("weights", [
    {"development_momentum": 100},
    dict(DEFAULT_WEIGHTS, development_momentum=30),
    dict(DEFAULT_WEIGHTS, development_momentum=-20, developer_adoption=55),
    dict(DEFAULT_WEIGHTS, extra=0),
])
def test_invalid_weights_rejected(weights):
    with pytest.raises(ValueError):
        validate_weights(weights)


def test_archived_repository_momentum_is_capped():
    result = compute_score(rich_facts(archived=True))
    momentum = next(m for m in result.metrics if m.key == "development_momentum")
    assert momentum.score <= 5
    assert "archived" in momentum.explanation


def test_stale_data_lowers_confidence():
    fresh = compute_score(rich_facts())
    stale = compute_score(rich_facts(last_synced_at=NOW - dt.timedelta(days=60)))
    assert stale.confidence_value < fresh.confidence_value
    assert stale.data_freshness["status"] == "outdated"


def test_growth_uses_snapshots_and_flags_fallback():
    with_history = compute_score(rich_facts())
    growth = next(m for m in with_history.metrics if m.key == "community_growth")
    assert any("normalised to 30 days" in e.label for e in growth.evidence)
    without = compute_score(rich_facts(star_history=[]))
    fallback = next(m for m in without.metrics if m.key == "community_growth")
    assert any("Lifetime average" in e.label for e in fallback.evidence)
    assert any("two snapshots" in item for item in fallback.missing)
    assert fallback.confidence < growth.confidence


def test_growth_rate_requires_a_week_of_history():
    today = NOW.date()
    assert growth_rate_30d([(today, 100)]) is None
    assert growth_rate_30d([(today - dt.timedelta(days=2), 100), (today, 120)]) is None
    pct, start, end, span = growth_rate_30d([(today - dt.timedelta(days=15), 1000), (today, 1100)])
    assert (start, end, span) == (1000, 1100, 15)
    assert pct == pytest.approx(20.0)


@pytest.mark.parametrize(("spdx", "low", "high"), [("MIT", 100, 100), ("AGPL-3.0", 30, 40), ("BUSL-1.1", 20, 20), (None, 10, 10), ("WTFPL", 30, 30)])
def test_licence_scoring_table(spdx, low, high):
    score, text = licence_score(spdx)
    assert low <= score <= high
    assert text


def test_popularity_alone_does_not_max_commercial_potential():
    popular_unlicensed = rich_facts(stars=250_000, license_spdx=None, category=None, topics=[], description="", owner_type="User", has_homepage=False)
    metric = commercial_potential(popular_unlicensed)
    assert metric.score < 25
    assert metric.confidence <= 0.75


def test_competitive_positioning_needs_five_peers():
    result = compute_score(rich_facts(peer_stars=[10, 20]))
    metric = next(m for m in result.metrics if m.key == "competitive_positioning")
    assert metric.score is None
    assert "5 needed" in metric.missing[0]


def test_thin_evidence_cannot_outrank_a_fully_analysed_repository():
    headline_only = RepoFacts(full_name="hype/project", html_url=None, stars=250_000, forks=30_000, now=NOW, license_spdx="MIT", category="ai-ml", technologies=["llm", "ai-agents"],
                              topics=["llm", "enterprise", "platform", "saas", "api"], owner_type="Organization", has_homepage=True, created_at=NOW - dt.timedelta(days=90), last_synced_at=NOW)
    thin, rich = compute_score(headline_only), compute_score(rich_facts())
    thin_raw, _ = raw_total_from_metrics([m.to_dict() for m in thin.metrics], thin.weights)
    assert thin_raw > rich.total  # on raw averages the hyped repository would win...
    assert thin.coverage < rich.coverage and thin.total < rich.total  # ...but its missing evidence damps the published score
    assert thin.confidence != "high"


def test_truncated_release_history_is_marked_as_a_lower_bound():
    many = [NOW - dt.timedelta(days=i % 20) for i in range(100)]
    momentum = next(m for m in compute_score(rich_facts(release_dates=many)).metrics if m.key == "development_momentum")
    assert any(e.label == "Releases in the last 180 days" and e.value == "100+" for e in momentum.evidence)
