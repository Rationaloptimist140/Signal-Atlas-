"""Subscription plans, entitlements and usage limits.

Prices are a proposal awaiting validation; no live payment provider is activated.
``None`` means unlimited.
"""

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class Plan:
    key: str
    name: str
    price_gbp_month: int | None
    tagline: str
    watchlist_items: int | None
    competitors: int | None
    reports_per_month: int | None
    live_syncs_per_month: int | None
    api_keys: int | None
    api_requests_per_month: int | None
    api_rate_per_minute: int
    ai_enrichment: bool
    custom_scoring_weights: bool
    seats: int | None

    def to_dict(self) -> dict:
        return asdict(self)


PLANS: dict[str, Plan] = {
    "free": Plan("free", "Free", 0, "Explore the intelligence terminal", 10, 1, 3, 20, 0, 0, 0, False, False, 1),
    "pro": Plan("pro", "Pro", 19, "For founders and independent developers", 100, 5, 30, 300, 2, 10_000, 60, True, False, 1),
    "professional": Plan("professional", "Professional", 49, "For consultants and product teams", 500, 20, 150, 1_500, 5, 100_000, 120, True, True, 5),
    "business": Plan("business", "Business", 149, "For investors and innovation teams", 2_500, 100, 750, 10_000, 20, 1_000_000, 300, True, True, 25),
    "enterprise": Plan("enterprise", "Enterprise", None, "Custom limits, SSO and support", None, None, None, None, None, None, 600, True, True, None),
}
PLAN_ORDER = ["free", "pro", "professional", "business", "enterprise"]


def get_plan(key: str | None) -> Plan:
    return PLANS.get(key or "free", PLANS["free"])


def next_plan(key: str) -> str | None:
    idx = PLAN_ORDER.index(key) if key in PLAN_ORDER else 0
    return PLAN_ORDER[idx + 1] if idx + 1 < len(PLAN_ORDER) else None
