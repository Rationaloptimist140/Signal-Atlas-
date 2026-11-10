"""Subscription plans, prices and entitlements - the single source of truth.

Prices are initial hypotheses. Override any field without a code change through
``PLAN_OVERRIDES_JSON``, e.g. ``{"pro": {"price_gbp_month": 25, "reports_per_month": 40}}``.
``None`` means unlimited (or "custom" for prices).
"""

import json
from dataclasses import asdict, dataclass, replace
from functools import lru_cache

from app.config import get_settings


@dataclass(frozen=True)
class Plan:
    key: str
    name: str
    price_gbp_month: int | None
    price_gbp_year: int | None
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
    purchasable: bool = True

    def to_dict(self) -> dict:
        return asdict(self)

    def price_minor(self, interval: str) -> int | None:
        """Price in pence for a billing interval (month | year)."""
        price = self.price_gbp_month if interval == "month" else self.price_gbp_year
        return None if price is None else int(round(price * 100))


_DEFAULT_PLANS: dict[str, Plan] = {
    "free": Plan("free", "Free", 0, 0, "Explore the intelligence terminal", 10, 1, 3, 20, 0, 0, 0, False, False, 1, purchasable=False),
    "pro": Plan("pro", "Pro", 19, 190, "For founders and independent developers", 100, 5, 30, 300, 2, 10_000, 60, True, False, 1),
    "business": Plan("business", "Business", 49, 490, "For product teams, consultants and investors", 500, 20, 150, 1_500, 10, 100_000, 180, True, True, 10),
    "enterprise": Plan("enterprise", "Enterprise", None, None, "Custom limits, SSO and support", None, None, None, None, None, None, 600, True, True, None, purchasable=False),
}
PLAN_ORDER = ["free", "pro", "business", "enterprise"]
INTERVALS = ("month", "year")
_OVERRIDABLE = {f for f in Plan.__dataclass_fields__ if f not in ("key",)}


@lru_cache
def _plans(overrides_json: str | None) -> dict[str, Plan]:
    plans = dict(_DEFAULT_PLANS)
    if overrides_json:
        overrides = json.loads(overrides_json)
        for key, fields in overrides.items():
            if key in plans and isinstance(fields, dict):
                plans[key] = replace(plans[key], **{k: v for k, v in fields.items() if k in _OVERRIDABLE})
    return plans


def all_plans() -> dict[str, Plan]:
    return _plans(get_settings().plan_overrides_json)


def get_plan(key: str | None) -> Plan:
    plans = all_plans()
    if key == "professional":  # legacy plan key from v0.1, folded into Business
        key = "business"
    return plans.get(key or "free", plans["free"])


def next_plan(key: str) -> str | None:
    idx = PLAN_ORDER.index(key) if key in PLAN_ORDER else 0
    return PLAN_ORDER[idx + 1] if idx + 1 < len(PLAN_ORDER) else None
