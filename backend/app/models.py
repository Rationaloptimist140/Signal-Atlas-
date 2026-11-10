"""Relational data model.

Two families of tables:

* **Global intelligence tables** (repositories, developers, technologies, signals, ...) hold
  *public* GitHub data shared by every tenant. Every row carries ``data_source`` so demo
  fixtures can never be mistaken for verified live data.
* **Tenant tables** (watchlists, competitors, reports, API keys, ...) always carry
  ``organisation_id`` and are only ever queried through an organisation filter.
"""

import datetime as dt
import enum

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import TypeDecorator


def utcnow() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


class UTCDateTime(TypeDecorator):
    """Timezone-aware UTC datetimes on every backend (SQLite returns naive values)."""

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is not None and value.tzinfo is None:
            value = value.replace(tzinfo=dt.UTC)
        return value

    def process_result_value(self, value, dialect):
        if value is not None and value.tzinfo is None:
            value = value.replace(tzinfo=dt.UTC)
        return value


JSONType = JSON().with_variant(JSONB(), "postgresql")


class Base(DeclarativeBase):
    pass


class DataSource(enum.StrEnum):
    LIVE = "live_github"
    DEMO = "demo_fixture"


class Role(enum.StrEnum):
    OWNER = "owner"
    ADMIN = "admin"
    ANALYST = "analyst"
    VIEWER = "viewer"


ROLE_RANK = {Role.VIEWER: 0, Role.ANALYST: 1, Role.ADMIN: 2, Role.OWNER: 3}


# --------------------------------------------------------------------------- identity & tenancy


class Organisation(Base):
    __tablename__ = "organisations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    slug: Mapped[str] = mapped_column(String(80), unique=True)
    created_at: Mapped[dt.datetime] = mapped_column(UTCDateTime, default=utcnow)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True)
    password_hash: Mapped[str | None] = mapped_column(String(255))
    full_name: Mapped[str] = mapped_column(String(200), default="")
    job_title: Mapped[str | None] = mapped_column(String(200))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    failed_logins: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[dt.datetime | None] = mapped_column(UTCDateTime)
    created_at: Mapped[dt.datetime] = mapped_column(UTCDateTime, default=utcnow)
    last_login_at: Mapped[dt.datetime | None] = mapped_column(UTCDateTime)


class Membership(Base):
    __tablename__ = "memberships"
    __table_args__ = (
        UniqueConstraint("user_id", "organisation_id", name="uq_membership_user_org"),
        CheckConstraint("role in ('owner','admin','analyst','viewer')", name="ck_membership_role"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    organisation_id: Mapped[int] = mapped_column(ForeignKey("organisations.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(20), default=Role.OWNER.value)
    created_at: Mapped[dt.datetime] = mapped_column(UTCDateTime, default=utcnow)


class UserSession(Base):
    __tablename__ = "sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    organisation_id: Mapped[int] = mapped_column(ForeignKey("organisations.id", ondelete="CASCADE"))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    csrf_token: Mapped[str] = mapped_column(String(64))
    ip_address: Mapped[str | None] = mapped_column(String(64))
    user_agent: Mapped[str | None] = mapped_column(String(400))
    created_at: Mapped[dt.datetime] = mapped_column(UTCDateTime, default=utcnow)
    expires_at: Mapped[dt.datetime] = mapped_column(UTCDateTime)
    revoked_at: Mapped[dt.datetime | None] = mapped_column(UTCDateTime)


class GitHubAccount(Base):
    """A user's connected GitHub identity. The OAuth token is encrypted at rest and never serialised."""

    __tablename__ = "github_accounts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), unique=True)
    github_user_id: Mapped[int] = mapped_column(BigInteger, unique=True)
    login: Mapped[str] = mapped_column(String(100))
    avatar_url: Mapped[str | None] = mapped_column(String(500))
    access_token_encrypted: Mapped[str] = mapped_column(Text)
    scopes: Mapped[str] = mapped_column(String(300), default="")
    connected_at: Mapped[dt.datetime] = mapped_column(UTCDateTime, default=utcnow)


# --------------------------------------------------------------------------- global intelligence


class Technology(Base):
    __tablename__ = "technologies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    slug: Mapped[str] = mapped_column(String(80), unique=True)
    name: Mapped[str] = mapped_column(String(120))
    category: Mapped[str] = mapped_column(String(60), index=True)
    description: Mapped[str] = mapped_column(Text, default="")


class Language(Base):
    __tablename__ = "languages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(80), unique=True)


class Repository(Base):
    __tablename__ = "repositories"
    __table_args__ = (
        Index("ix_repositories_category_stars", "category", "stars"),
        Index("ix_repositories_language", "primary_language"),
        Index("ix_repositories_pushed", "pushed_at_github"),
        CheckConstraint("data_source in ('live_github','demo_fixture')", name="ck_repository_data_source"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    github_id: Mapped[int | None] = mapped_column(BigInteger, unique=True)
    full_name: Mapped[str] = mapped_column(String(255), unique=True)
    owner_login: Mapped[str] = mapped_column(String(100), index=True)
    owner_type: Mapped[str | None] = mapped_column(String(20))  # User | Organization
    name: Mapped[str] = mapped_column(String(150))
    description: Mapped[str | None] = mapped_column(Text)
    html_url: Mapped[str | None] = mapped_column(String(500))
    homepage: Mapped[str | None] = mapped_column(String(500))
    primary_language: Mapped[str | None] = mapped_column(String(80))
    license_spdx: Mapped[str | None] = mapped_column(String(60))
    license_name: Mapped[str | None] = mapped_column(String(120))
    topics: Mapped[list] = mapped_column(JSONType, default=list)
    category: Mapped[str | None] = mapped_column(String(60))
    stars: Mapped[int] = mapped_column(Integer, default=0)
    forks: Mapped[int] = mapped_column(Integer, default=0)
    watchers: Mapped[int | None] = mapped_column(Integer)  # subscribers_count; only known after a full sync
    open_issues: Mapped[int | None] = mapped_column(Integer)
    closed_issues: Mapped[int | None] = mapped_column(Integer)
    open_prs: Mapped[int | None] = mapped_column(Integer)
    merged_prs: Mapped[int | None] = mapped_column(Integer)
    contributors_count: Mapped[int | None] = mapped_column(Integer)
    size_kb: Mapped[int | None] = mapped_column(Integer)
    is_fork: Mapped[bool] = mapped_column(Boolean, default=False)
    archived: Mapped[bool] = mapped_column(Boolean, default=False)
    parent_full_name: Mapped[str | None] = mapped_column(String(255))
    source_full_name: Mapped[str | None] = mapped_column(String(255))
    default_branch: Mapped[str | None] = mapped_column(String(100))
    created_at_github: Mapped[dt.datetime | None] = mapped_column(UTCDateTime)
    pushed_at_github: Mapped[dt.datetime | None] = mapped_column(UTCDateTime)
    updated_at_github: Mapped[dt.datetime | None] = mapped_column(UTCDateTime)
    data_source: Mapped[str] = mapped_column(String(20), default=DataSource.LIVE.value, index=True)
    sync_level: Mapped[str] = mapped_column(String(10), default="search")  # search | full
    missing_data: Mapped[list] = mapped_column(JSONType, default=list)
    etag: Mapped[str | None] = mapped_column(String(120))
    first_seen_at: Mapped[dt.datetime] = mapped_column(UTCDateTime, default=utcnow)
    last_synced_at: Mapped[dt.datetime | None] = mapped_column(UTCDateTime)


class RepositoryLanguage(Base):
    __tablename__ = "repository_languages"
    __table_args__ = (UniqueConstraint("repository_id", "language_id", name="uq_repo_language"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    repository_id: Mapped[int] = mapped_column(ForeignKey("repositories.id", ondelete="CASCADE"), index=True)
    language_id: Mapped[int] = mapped_column(ForeignKey("languages.id", ondelete="CASCADE"))
    byte_count: Mapped[int] = mapped_column(BigInteger, default=0)


class RepositoryTechnology(Base):
    __tablename__ = "repository_technologies"
    __table_args__ = (UniqueConstraint("repository_id", "technology_id", name="uq_repo_technology"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    repository_id: Mapped[int] = mapped_column(ForeignKey("repositories.id", ondelete="CASCADE"), index=True)
    technology_id: Mapped[int] = mapped_column(ForeignKey("technologies.id", ondelete="CASCADE"), index=True)
    confidence: Mapped[float] = mapped_column(Float, default=0.5)
    method: Mapped[str] = mapped_column(String(40), default="keyword_rules")  # how it was inferred


class RepositorySnapshot(Base):
    """One point-in-time measurement per repository per day; the basis of all growth maths."""

    __tablename__ = "repository_snapshots"
    __table_args__ = (UniqueConstraint("repository_id", "captured_on", name="uq_snapshot_repo_day"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    repository_id: Mapped[int] = mapped_column(ForeignKey("repositories.id", ondelete="CASCADE"), index=True)
    captured_on: Mapped[dt.date] = mapped_column(Date, index=True)
    captured_at: Mapped[dt.datetime] = mapped_column(UTCDateTime, default=utcnow)
    stars: Mapped[int] = mapped_column(Integer)
    forks: Mapped[int] = mapped_column(Integer)
    watchers: Mapped[int | None] = mapped_column(Integer)
    open_issues: Mapped[int | None] = mapped_column(Integer)
    contributors_count: Mapped[int | None] = mapped_column(Integer)


class CommitActivity(Base):
    __tablename__ = "commit_activity"
    __table_args__ = (UniqueConstraint("repository_id", "week_start", name="uq_commit_activity_repo_week"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    repository_id: Mapped[int] = mapped_column(ForeignKey("repositories.id", ondelete="CASCADE"), index=True)
    week_start: Mapped[dt.date] = mapped_column(Date)
    commits: Mapped[int] = mapped_column(Integer, default=0)


class Release(Base):
    __tablename__ = "releases"
    __table_args__ = (UniqueConstraint("repository_id", "tag_name", name="uq_release_repo_tag"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    repository_id: Mapped[int] = mapped_column(ForeignKey("repositories.id", ondelete="CASCADE"), index=True)
    tag_name: Mapped[str] = mapped_column(String(200))
    name: Mapped[str | None] = mapped_column(String(300))
    published_at: Mapped[dt.datetime | None] = mapped_column(UTCDateTime, index=True)
    prerelease: Mapped[bool] = mapped_column(Boolean, default=False)
    html_url: Mapped[str | None] = mapped_column(String(500))
    body_excerpt: Mapped[str | None] = mapped_column(Text)


class Dependency(Base):
    __tablename__ = "dependencies"
    __table_args__ = (
        UniqueConstraint("repository_id", "ecosystem", "package_name", "dep_type", name="uq_dependency"),
        Index("ix_dependencies_package", "ecosystem", "package_name"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    repository_id: Mapped[int] = mapped_column(ForeignKey("repositories.id", ondelete="CASCADE"), index=True)
    ecosystem: Mapped[str] = mapped_column(String(30))  # npm | pypi | go | cargo
    package_name: Mapped[str] = mapped_column(String(200))
    version_spec: Mapped[str | None] = mapped_column(String(120))
    dep_type: Mapped[str] = mapped_column(String(20), default="runtime")  # runtime | dev
    manifest_path: Mapped[str] = mapped_column(String(200))
    first_seen_at: Mapped[dt.datetime] = mapped_column(UTCDateTime, default=utcnow)


class ForkRelationship(Base):
    __tablename__ = "fork_relationships"
    __table_args__ = (UniqueConstraint("parent_repository_id", "fork_full_name", name="uq_fork_parent_child"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    parent_repository_id: Mapped[int] = mapped_column(ForeignKey("repositories.id", ondelete="CASCADE"), index=True)
    fork_full_name: Mapped[str] = mapped_column(String(255))
    fork_html_url: Mapped[str | None] = mapped_column(String(500))
    stars: Mapped[int] = mapped_column(Integer, default=0)
    pushed_at: Mapped[dt.datetime | None] = mapped_column(UTCDateTime)
    created_at_github: Mapped[dt.datetime | None] = mapped_column(UTCDateTime)


class DeveloperProfile(Base):
    """Public GitHub profile data only. Inferred fields live in ``inferred`` and are labelled as such."""

    __tablename__ = "developer_profiles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    github_id: Mapped[int | None] = mapped_column(BigInteger, unique=True)
    login: Mapped[str] = mapped_column(String(100), unique=True)
    account_type: Mapped[str] = mapped_column(String(20), default="User")
    name: Mapped[str | None] = mapped_column(String(200))
    avatar_url: Mapped[str | None] = mapped_column(String(500))
    html_url: Mapped[str | None] = mapped_column(String(500))
    company: Mapped[str | None] = mapped_column(String(200))
    location: Mapped[str | None] = mapped_column(String(200))
    bio: Mapped[str | None] = mapped_column(Text)
    followers: Mapped[int | None] = mapped_column(Integer)
    following: Mapped[int | None] = mapped_column(Integer)
    public_repos: Mapped[int | None] = mapped_column(Integer)
    created_at_github: Mapped[dt.datetime | None] = mapped_column(UTCDateTime)
    inferred: Mapped[dict] = mapped_column(JSONType, default=dict)
    data_source: Mapped[str] = mapped_column(String(20), default=DataSource.LIVE.value, index=True)
    sync_level: Mapped[str] = mapped_column(String(10), default="stub")  # stub | full
    last_synced_at: Mapped[dt.datetime | None] = mapped_column(UTCDateTime)


class Contributor(Base):
    __tablename__ = "contributors"
    __table_args__ = (UniqueConstraint("repository_id", "developer_id", name="uq_contributor_repo_dev"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    repository_id: Mapped[int] = mapped_column(ForeignKey("repositories.id", ondelete="CASCADE"), index=True)
    developer_id: Mapped[int] = mapped_column(ForeignKey("developer_profiles.id", ondelete="CASCADE"), index=True)
    contributions: Mapped[int] = mapped_column(Integer, default=0)


class TrendSignal(Base):
    __tablename__ = "trend_signals"
    __table_args__ = (
        Index("ix_trend_signals_window_detected", "time_window", "detected_at"),
        CheckConstraint("time_window in ('daily','weekly','monthly')", name="ck_trend_signal_window"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    dedupe_key: Mapped[str] = mapped_column(String(200), unique=True)
    repository_id: Mapped[int | None] = mapped_column(ForeignKey("repositories.id", ondelete="CASCADE"), index=True)
    category: Mapped[str | None] = mapped_column(String(60), index=True)
    signal_type: Mapped[str] = mapped_column(String(40), index=True)
    time_window: Mapped[str] = mapped_column(String(10))
    strength: Mapped[float] = mapped_column(Float)  # 0..100, relative ranking only
    confidence: Mapped[str] = mapped_column(String(10))  # low | medium | high
    title: Mapped[str] = mapped_column(String(300))
    summary: Mapped[str] = mapped_column(Text)
    evidence: Mapped[list] = mapped_column(JSONType, default=list)
    data_source: Mapped[str] = mapped_column(String(20), default=DataSource.LIVE.value)
    detected_at: Mapped[dt.datetime] = mapped_column(UTCDateTime, default=utcnow)


class OpportunityScore(Base):
    """Weight-independent metric scores for a repository. Totals are derived per organisation weights."""

    __tablename__ = "opportunity_scores"
    __table_args__ = (Index("ix_opportunity_scores_repo_time", "repository_id", "computed_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    repository_id: Mapped[int] = mapped_column(ForeignKey("repositories.id", ondelete="CASCADE"))
    total_default: Mapped[float] = mapped_column(Float)
    metrics: Mapped[list] = mapped_column(JSONType)
    confidence: Mapped[str] = mapped_column(String(10))
    confidence_value: Mapped[float] = mapped_column(Float, default=0.0)
    missing: Mapped[list] = mapped_column(JSONType, default=list)
    data_freshness: Mapped[dict] = mapped_column(JSONType, default=dict)
    is_current: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    computed_at: Mapped[dt.datetime] = mapped_column(UTCDateTime, default=utcnow)


class Opportunity(Base):
    __tablename__ = "opportunities"
    __table_args__ = (Index("ix_opportunities_category_score", "category", "score"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    repository_id: Mapped[int] = mapped_column(ForeignKey("repositories.id", ondelete="CASCADE"), unique=True)
    title: Mapped[str] = mapped_column(String(300))
    category: Mapped[str | None] = mapped_column(String(60))
    summary: Mapped[str] = mapped_column(Text, default="")
    score: Mapped[float] = mapped_column(Float, index=True)
    confidence: Mapped[str] = mapped_column(String(10))
    risk_level: Mapped[str] = mapped_column(String(10))  # low | medium | high
    maturity: Mapped[str] = mapped_column(String(20))  # experimental | emerging | established | mature
    analysis: Mapped[dict] = mapped_column(JSONType, default=dict)
    data_source: Mapped[str] = mapped_column(String(20), default=DataSource.LIVE.value, index=True)
    created_at: Mapped[dt.datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[dt.datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)


class ChangeEvent(Base):
    """A detected change on a monitored repository (release, surge, dependency or stack change)."""

    __tablename__ = "change_events"
    __table_args__ = (Index("ix_change_events_repo_time", "repository_id", "occurred_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    dedupe_key: Mapped[str] = mapped_column(String(300), unique=True)
    repository_id: Mapped[int] = mapped_column(ForeignKey("repositories.id", ondelete="CASCADE"))
    event_type: Mapped[str] = mapped_column(String(40))
    title: Mapped[str] = mapped_column(String(300))
    details: Mapped[dict] = mapped_column(JSONType, default=dict)
    evidence_url: Mapped[str | None] = mapped_column(String(500))
    data_source: Mapped[str] = mapped_column(String(20), default=DataSource.LIVE.value)
    occurred_at: Mapped[dt.datetime] = mapped_column(UTCDateTime, default=utcnow)
    detected_at: Mapped[dt.datetime] = mapped_column(UTCDateTime, default=utcnow)


# --------------------------------------------------------------------------- tenant-scoped tables


class ScoringConfig(Base):
    __tablename__ = "scoring_configs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organisation_id: Mapped[int] = mapped_column(ForeignKey("organisations.id", ondelete="CASCADE"), unique=True)
    weights: Mapped[dict] = mapped_column(JSONType)
    updated_at: Mapped[dt.datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)


class Competitor(Base):
    __tablename__ = "competitors"
    __table_args__ = (UniqueConstraint("organisation_id", "name", name="uq_competitor_org_name"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organisation_id: Mapped[int] = mapped_column(ForeignKey("organisations.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    website: Mapped[str | None] = mapped_column(String(500))
    github_org: Mapped[str | None] = mapped_column(String(100))
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[dt.datetime] = mapped_column(UTCDateTime, default=utcnow)


class CompetitorRepository(Base):
    __tablename__ = "competitor_repositories"
    __table_args__ = (UniqueConstraint("competitor_id", "repository_id", name="uq_competitor_repo"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    competitor_id: Mapped[int] = mapped_column(ForeignKey("competitors.id", ondelete="CASCADE"), index=True)
    repository_id: Mapped[int] = mapped_column(ForeignKey("repositories.id", ondelete="CASCADE"), index=True)
    added_at: Mapped[dt.datetime] = mapped_column(UTCDateTime, default=utcnow)


class Watchlist(Base):
    __tablename__ = "watchlists"
    __table_args__ = (UniqueConstraint("organisation_id", "name", name="uq_watchlist_org_name"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organisation_id: Mapped[int] = mapped_column(ForeignKey("organisations.id", ondelete="CASCADE"), index=True)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[dt.datetime] = mapped_column(UTCDateTime, default=utcnow)


class WatchlistItem(Base):
    __tablename__ = "watchlist_items"
    __table_args__ = (
        UniqueConstraint("watchlist_id", "item_type", "item_id", name="uq_watchlist_item"),
        CheckConstraint("item_type in ('repository','opportunity','developer')", name="ck_watchlist_item_type"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    watchlist_id: Mapped[int] = mapped_column(ForeignKey("watchlists.id", ondelete="CASCADE"), index=True)
    organisation_id: Mapped[int] = mapped_column(ForeignKey("organisations.id", ondelete="CASCADE"), index=True)
    item_type: Mapped[str] = mapped_column(String(20))
    item_id: Mapped[int] = mapped_column(Integer)
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[dt.datetime] = mapped_column(UTCDateTime, default=utcnow)


class IntelligenceReport(Base):
    __tablename__ = "intelligence_reports"
    __table_args__ = (Index("ix_reports_org_created", "organisation_id", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organisation_id: Mapped[int] = mapped_column(ForeignKey("organisations.id", ondelete="CASCADE"))
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    report_type: Mapped[str] = mapped_column(String(30))  # opportunity | repository | competitor | comparison
    subject_type: Mapped[str] = mapped_column(String(30))
    subject_id: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String(300))
    status: Mapped[str] = mapped_column(String(20), default="complete")  # complete | enriching | failed
    provider: Mapped[str] = mapped_column(String(30), default="rules")
    model: Mapped[str | None] = mapped_column(String(100))
    content: Mapped[dict] = mapped_column(JSONType, default=dict)
    error: Mapped[str | None] = mapped_column(Text)
    data_source: Mapped[str] = mapped_column(String(20), default=DataSource.LIVE.value)
    created_at: Mapped[dt.datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[dt.datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)


class ApiKey(Base):
    __tablename__ = "api_keys"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organisation_id: Mapped[int] = mapped_column(ForeignKey("organisations.id", ondelete="CASCADE"), index=True)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    name: Mapped[str] = mapped_column(String(120))
    prefix: Mapped[str] = mapped_column(String(32))
    key_hash: Mapped[str] = mapped_column(String(64), unique=True)
    scopes: Mapped[str] = mapped_column(String(100), default="read")
    last_used_at: Mapped[dt.datetime | None] = mapped_column(UTCDateTime)
    revoked_at: Mapped[dt.datetime | None] = mapped_column(UTCDateTime)
    created_at: Mapped[dt.datetime] = mapped_column(UTCDateTime, default=utcnow)


class Subscription(Base):
    __tablename__ = "subscriptions"
    __table_args__ = (
        CheckConstraint("plan in ('free','pro','professional','business','enterprise')", name="ck_subscription_plan"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organisation_id: Mapped[int] = mapped_column(ForeignKey("organisations.id", ondelete="CASCADE"), unique=True)
    plan: Mapped[str] = mapped_column(String(20), default="free")
    status: Mapped[str] = mapped_column(String(20), default="active")
    provider: Mapped[str] = mapped_column(String(20), default="manual")
    provider_customer_id: Mapped[str | None] = mapped_column(String(120))
    provider_subscription_id: Mapped[str | None] = mapped_column(String(120))
    current_period_end: Mapped[dt.datetime | None] = mapped_column(UTCDateTime)
    created_at: Mapped[dt.datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[dt.datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)


class UsageRecord(Base):
    """Monthly usage counters per organisation and metric (api_requests, reports, live_syncs...)."""

    __tablename__ = "usage_records"
    __table_args__ = (UniqueConstraint("organisation_id", "metric", "period", name="uq_usage_org_metric_period"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organisation_id: Mapped[int] = mapped_column(ForeignKey("organisations.id", ondelete="CASCADE"), index=True)
    metric: Mapped[str] = mapped_column(String(40))
    period: Mapped[str] = mapped_column(String(7))  # YYYY-MM
    quantity: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[dt.datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)


class Notification(Base):
    __tablename__ = "notifications"
    __table_args__ = (Index("ix_notifications_org_created", "organisation_id", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organisation_id: Mapped[int] = mapped_column(ForeignKey("organisations.id", ondelete="CASCADE"))
    dedupe_key: Mapped[str | None] = mapped_column(String(300), unique=True)
    kind: Mapped[str] = mapped_column(String(40))
    title: Mapped[str] = mapped_column(String(300))
    body: Mapped[str] = mapped_column(Text, default="")
    link: Mapped[str | None] = mapped_column(String(300))
    read_at: Mapped[dt.datetime | None] = mapped_column(UTCDateTime)
    created_at: Mapped[dt.datetime] = mapped_column(UTCDateTime, default=utcnow)


class AuditLog(Base):
    __tablename__ = "audit_logs"
    __table_args__ = (Index("ix_audit_org_created", "organisation_id", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organisation_id: Mapped[int | None] = mapped_column(ForeignKey("organisations.id", ondelete="CASCADE"))
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    action: Mapped[str] = mapped_column(String(80))
    target_type: Mapped[str | None] = mapped_column(String(40))
    target_id: Mapped[str | None] = mapped_column(String(80))
    details: Mapped[dict] = mapped_column(JSONType, default=dict)
    ip_address: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[dt.datetime] = mapped_column(UTCDateTime, default=utcnow)


class Job(Base):
    """Durable Postgres-backed job queue (no extra infrastructure needed)."""

    __tablename__ = "jobs"
    __table_args__ = (Index("ix_jobs_status_run_after", "status", "run_after"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_type: Mapped[str] = mapped_column(String(60))
    dedupe_key: Mapped[str | None] = mapped_column(String(200), index=True)
    payload: Mapped[dict] = mapped_column(JSONType, default=dict)
    status: Mapped[str] = mapped_column(String(20), default="queued")  # queued|running|succeeded|failed|deferred
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=4)
    run_after: Mapped[dt.datetime] = mapped_column(UTCDateTime, default=utcnow)
    locked_at: Mapped[dt.datetime | None] = mapped_column(UTCDateTime)
    last_error: Mapped[str | None] = mapped_column(Text)
    result: Mapped[dict | None] = mapped_column(JSONType)
    organisation_id: Mapped[int | None] = mapped_column(ForeignKey("organisations.id", ondelete="CASCADE"))
    created_at: Mapped[dt.datetime] = mapped_column(UTCDateTime, default=utcnow)
    finished_at: Mapped[dt.datetime | None] = mapped_column(UTCDateTime)
