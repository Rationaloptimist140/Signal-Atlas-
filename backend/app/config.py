"""Environment-based configuration. No secret ever has a usable production default."""

from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEV_SECRET = "dev-only-insecure-secret-change-me"  # noqa: S105 - rejected in production


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: Literal["development", "test", "production"] = "development"
    app_name: str = "SIGNAL ATLAS"
    log_level: str = "INFO"

    # --- security ---
    secret_key: str = DEV_SECRET
    encryption_key: str | None = None  # Fernet key; derived from secret_key when unset
    session_cookie_name: str = "sa_session"
    csrf_cookie_name: str = "sa_csrf"
    session_ttl_hours: int = 24 * 14
    cookie_secure: bool | None = None  # defaults to True in production
    cors_origins: str = "http://localhost:3000"
    frontend_url: str = "http://localhost:3000"
    allow_registration: bool = True
    login_requires_verified_email: bool = False  # hard gate (closes sign-up enumeration fully); default is the soft gate
    api_docs_enabled: bool = True
    trusted_proxy_hops: int = 1  # proxies between the internet and this API that append to X-Forwarded-For (Railway edge + Next.js proxy = 2)
    rate_limit_backend: Literal["auto", "memory", "redis"] = "auto"  # auto = redis when REDIS_URL is set
    platform_admin_emails: str = ""  # comma-separated; may run instance-wide tools in production

    # --- data stores ---
    database_url: str = "sqlite+aiosqlite:///./signal_atlas.db"
    redis_url: str | None = None

    # --- GitHub (read-only public data) ---
    github_token: str | None = None  # optional server token; raises rate limits, no scopes needed
    github_api_url: str = "https://api.github.com"
    github_oauth_client_id: str | None = None
    github_oauth_client_secret: str | None = None
    github_oauth_redirect_url: str | None = None  # defaults to {frontend_url}/api/v1/auth/github/callback
    github_oauth_scopes: str = "read:user user:email"  # minimum: identity only, never repo write

    # --- AI (provider independent; deterministic rules engine always available) ---
    llm_provider: Literal["rules", "anthropic", "openai"] = "rules"
    llm_model: str | None = None
    anthropic_api_key: str | None = None
    openai_api_key: str | None = None
    openai_base_url: str = "https://api.openai.com/v1"
    llm_timeout_seconds: float = 60.0

    # --- jobs ---
    jobs_inline: bool = False  # run enqueued jobs immediately in-process (dev/test convenience)
    worker_poll_seconds: float = 5.0
    sync_interval_hours: int = 24
    discovery_enabled: bool = True

    # --- email (provider independent; "console" never delivers) ---
    email_provider: Literal["console", "resend"] = "console"
    resend_api_key: str | None = None
    email_from: str = "Signal Atlas <no-reply@example.com>"  # must use a domain verified with the provider
    email_reply_to: str | None = None
    email_verification_required: bool = True  # soft gate: verify before reports, API keys and live GitHub operations
    verification_token_hours: int = 24
    password_reset_token_minutes: int = 30

    # --- product & billing ---
    seed_demo_data: bool = False
    billing_provider: Literal["manual", "stripe"] = "manual"
    stripe_secret_key: str | None = None  # test-mode key (sk_test_...); live keys are refused unless allow_live_payments
    stripe_webhook_secret: str | None = None
    stripe_api_url: str = "https://api.stripe.com"
    allow_live_payments: bool = False
    billing_currency: str = "gbp"
    billing_grace_days: int = 7  # access kept this long after a failed renewal
    plan_overrides_json: str | None = None  # e.g. {"pro": {"price_gbp_month": 25, "reports_per_month": 40}}
    allow_self_serve_plan_change: bool = False  # dev/test only: lets an owner switch plan without payment
    snapshot_retention_days: int = 730
    audit_retention_days: int = 365
    rate_limit_per_minute: int = Field(default=120, description="Session-authenticated requests per minute")

    @field_validator("database_url")
    @classmethod
    def _normalise_db_url(cls, v: str) -> str:
        # Railway/Heroku style URLs -> async driver
        if v.startswith("postgres://"):
            v = "postgresql://" + v[len("postgres://") :]
        if v.startswith("postgresql://"):
            v = "postgresql+asyncpg://" + v[len("postgresql://") :]
        return v

    @model_validator(mode="after")
    def _production_guards(self) -> "Settings":
        if self.cookie_secure is None:
            self.cookie_secure = self.app_env == "production"
        if self.rate_limit_backend == "redis" and not self.redis_url:
            raise ValueError("RATE_LIMIT_BACKEND=redis requires REDIS_URL")
        if self.app_env == "production":
            problems = []
            if self.secret_key == DEV_SECRET or len(self.secret_key) < 32:
                problems.append("SECRET_KEY must be set to a random value of at least 32 characters")
            if self.allow_self_serve_plan_change:
                problems.append("ALLOW_SELF_SERVE_PLAN_CHANGE must be false")
            if self.is_sqlite:
                problems.append("DATABASE_URL must point at PostgreSQL (a local SQLite file is for development only)")
            if not self.cookie_secure:
                problems.append("COOKIE_SECURE must not be disabled")
            urls = [self.frontend_url, *self.cors_origin_list]
            if any(not u.startswith("https://") or "localhost" in u or "127.0.0.1" in u for u in urls):
                problems.append("FRONTEND_URL and CORS_ORIGINS must be public https:// URLs (not localhost)")
            if self.rate_limit_backend == "auto" and not self.redis_url:
                problems.append("set REDIS_URL for shared rate limiting, or RATE_LIMIT_BACKEND=memory to accept per-process limits (single API instance only)")
            if self.seed_demo_data:
                problems.append("SEED_DEMO_DATA must be false")
            if problems:
                raise ValueError("Unsafe production configuration: " + "; ".join(problems))
        if self.stripe_secret_key and not self.stripe_secret_key.startswith(("sk_test_", "rk_test_")) and not self.allow_live_payments:
            raise ValueError("STRIPE_SECRET_KEY must be a test-mode key (sk_test_...). Live payments are not activated in this release.")
        return self

    @property
    def rate_limit_uses_redis(self) -> bool:
        return self.rate_limit_backend == "redis" or (self.rate_limit_backend == "auto" and bool(self.redis_url))

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def platform_admins(self) -> set[str]:
        return {e.strip().lower() for e in self.platform_admin_emails.split(",") if e.strip()}

    @property
    def github_oauth_configured(self) -> bool:
        return bool(self.github_oauth_client_id and self.github_oauth_client_secret)

    @property
    def oauth_redirect_url(self) -> str:
        return self.github_oauth_redirect_url or f"{self.frontend_url.rstrip('/')}/api/v1/auth/github/callback"

    @property
    def email_delivery_configured(self) -> bool:
        return self.email_provider == "resend" and bool(self.resend_api_key)

    @property
    def stripe_configured(self) -> bool:
        return self.billing_provider == "stripe" and bool(self.stripe_secret_key)

    @property
    def stripe_test_mode(self) -> bool:
        return bool(self.stripe_secret_key) and self.stripe_secret_key.startswith(("sk_test_", "rk_test_"))

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")

    @property
    def llm_configured(self) -> bool:
        if self.llm_provider == "anthropic":
            return bool(self.anthropic_api_key)
        if self.llm_provider == "openai":
            return bool(self.openai_api_key)
        return False


@lru_cache
def get_settings() -> Settings:
    return Settings()
