"""Pydantic request and response models."""

import datetime as dt
from typing import Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

T = TypeVar("T")


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    page: int
    page_size: int


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ----------------------------------------------------------------------------- auth


class RegisterIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=10, max_length=128)
    full_name: str = Field(min_length=1, max_length=200)
    organisation_name: str | None = Field(default=None, max_length=200)

    @field_validator("password")
    @classmethod
    def _password_strength(cls, v: str) -> str:
        if v.lower() == v or not any(c.isdigit() for c in v):
            raise ValueError("Password must include an upper-case letter and a digit")
        return v


class LoginIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class ProfileUpdateIn(BaseModel):
    full_name: str | None = Field(default=None, min_length=1, max_length=200)
    job_title: str | None = Field(default=None, max_length=200)


class ChangePasswordIn(BaseModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=10, max_length=128)

    @field_validator("new_password")
    @classmethod
    def _password_strength(cls, v: str) -> str:
        if v.lower() == v or not any(c.isdigit() for c in v):
            raise ValueError("Password must include an upper-case letter and a digit")
        return v


# ----------------------------------------------------------------------------- intelligence


class RepositoryOut(ORMModel):
    id: int
    full_name: str
    owner_login: str
    owner_type: str | None
    name: str
    description: str | None
    html_url: str | None
    homepage: str | None
    primary_language: str | None
    license_spdx: str | None
    license_name: str | None
    topics: list[str]
    category: str | None
    stars: int
    forks: int
    watchers: int | None
    open_issues: int | None
    closed_issues: int | None
    open_prs: int | None
    merged_prs: int | None
    contributors_count: int | None
    is_fork: bool
    archived: bool
    parent_full_name: str | None
    created_at_github: dt.datetime | None
    pushed_at_github: dt.datetime | None
    data_source: str
    sync_level: str
    missing_data: list[str]
    last_synced_at: dt.datetime | None
    first_seen_at: dt.datetime


class RepositoryListItem(RepositoryOut):
    score: float | None = None
    score_confidence: str | None = None
    opportunity_id: int | None = None


class DeveloperOut(ORMModel):
    id: int
    login: str
    account_type: str
    name: str | None
    avatar_url: str | None
    html_url: str | None
    company: str | None
    location: str | None
    bio: str | None
    followers: int | None
    following: int | None
    public_repos: int | None
    created_at_github: dt.datetime | None
    data_source: str
    sync_level: str
    last_synced_at: dt.datetime | None


class DeveloperListItem(DeveloperOut):
    tracked_repositories: int = 0
    tracked_contributions: int = 0
    top_languages: list[str] = []


class TrendSignalOut(ORMModel):
    id: int
    repository_id: int | None
    repository_full_name: str | None = None
    category: str | None
    signal_type: str
    time_window: str
    strength: float
    confidence: str
    title: str
    summary: str
    evidence: list[dict]
    data_source: str
    detected_at: dt.datetime


class OpportunityOut(ORMModel):
    id: int
    repository_id: int
    repository_full_name: str | None = None
    repository_html_url: str | None = None
    title: str
    category: str | None
    summary: str
    score: float
    confidence: str
    risk_level: str
    maturity: str
    data_source: str
    updated_at: dt.datetime
    recommended_action: str | None = None
    stars: int | None = None
    primary_language: str | None = None
    license_spdx: str | None = None
    metrics: list[dict] = []


class ReportGenerateIn(BaseModel):
    report_type: Literal["opportunity", "repository", "competitor", "comparison"]
    subject_id: int | None = Field(default=None, ge=1)
    repository_ids: list[int] | None = Field(default=None, max_length=4)
    use_ai: bool = True


class ReportOut(ORMModel):
    id: int
    report_type: str
    subject_type: str
    subject_id: int
    title: str
    status: str
    provider: str
    model: str | None
    data_source: str
    created_at: dt.datetime
    updated_at: dt.datetime
    summary: str | None = None
    content: dict | None = None


class CompetitorIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    website: str | None = Field(default=None, max_length=500)
    github_org: str | None = Field(default=None, max_length=100, pattern=r"^[A-Za-z0-9](?:[A-Za-z0-9\-]{0,98})$")
    repository_ids: list[int] = Field(default_factory=list, max_length=50)

    @field_validator("website")
    @classmethod
    def _http_only(cls, v: str | None) -> str | None:
        if v and not v.lower().startswith(("http://", "https://")):
            raise ValueError("Website must start with http:// or https://")
        return v


class CompetitorUpdateIn(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    website: str | None = Field(default=None, max_length=500)


class CompetitorRepoIn(BaseModel):
    repository_id: int | None = Field(default=None, ge=1)
    full_name: str | None = Field(default=None, max_length=255, pattern=r"^[A-Za-z0-9_.\-]+/[A-Za-z0-9_.\-]+$")


class WatchlistIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)


class WatchlistItemIn(BaseModel):
    item_type: Literal["repository", "opportunity", "developer"]
    item_id: int = Field(ge=1)
    note: str | None = Field(default=None, max_length=2000)


class TrackRepositoryIn(BaseModel):
    full_name: str = Field(max_length=255, pattern=r"^[A-Za-z0-9_.\-]+/[A-Za-z0-9_.\-]+$")


class ApiKeyIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    scopes: Literal["read", "read write"] = "read"


class WeightsIn(BaseModel):
    weights: dict[str, float]


class OrganisationUpdateIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)


class BillingSyncIn(BaseModel):
    session_id: str | None = Field(default=None, max_length=200, pattern=r"^cs_(test|live)_[A-Za-z0-9]+$")


class CheckoutIn(BaseModel):
    plan: Literal["pro", "business"]
    interval: Literal["month", "year"] = "month"


class TokenIn(BaseModel):
    token: str = Field(min_length=20, max_length=200)


class EmailIn(BaseModel):
    email: EmailStr


class PasswordResetRequestIn(BaseModel):
    email: EmailStr


class PasswordResetConfirmIn(BaseModel):
    token: str = Field(min_length=20, max_length=200)
    new_password: str = Field(min_length=10, max_length=128)

    @field_validator("new_password")
    @classmethod
    def _password_strength(cls, v: str) -> str:
        if v.lower() == v or not any(c.isdigit() for c in v):
            raise ValueError("Password must include an upper-case letter and a digit")
        return v
