"""Test harness.

Runs against in-memory SQLite by default; set TEST_DATABASE_URL to run the same suite on PostgreSQL.
No test performs real network I/O: GitHub and LLM calls are mocked with respx.
"""

import os

os.environ["APP_ENV"] = "test"
os.environ["SECRET_KEY"] = "test-secret-key-test-secret-key-test-secret-key"
os.environ["DATABASE_URL"] = os.environ.get("TEST_DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ["JOBS_INLINE"] = "true"
os.environ["COOKIE_SECURE"] = "false"
os.environ["ALLOW_SELF_SERVE_PLAN_CHANGE"] = "true"
os.environ["LLM_PROVIDER"] = "rules"
for _var in ("EMAIL_PROVIDER", "RESEND_API_KEY", "STRIPE_SECRET_KEY", "STRIPE_WEBHOOK_SECRET", "BILLING_PROVIDER", "PLAN_OVERRIDES_JSON", "GITHUB_TOKEN", "GITHUB_OAUTH_CLIENT_ID", "GITHUB_OAUTH_CLIENT_SECRET", "REDIS_URL", "ANTHROPIC_API_KEY", "OPENAI_API_KEY"):
    os.environ.pop(_var, None)

import httpx  # noqa: E402
import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402

from app import ratelimit  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.database import configure_engine, get_sessionmaker, make_engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Base  # noqa: E402
from app.routers import repositories as repositories_router  # noqa: E402
from app.services import github_client  # noqa: E402
from app.services.mailer import ConsoleMailer  # noqa: E402

PASSWORD = "Str0ngPassw0rd!"


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def engine():
    engine = make_engine(get_settings().database_url)
    configure_engine(engine)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture(autouse=True, loop_scope="session")
async def clean_state(engine):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    ratelimit.reset()
    github_client.reset_rate_limit_state()
    repositories_router._SEARCH_CACHE.clear()
    ConsoleMailer.outbox.clear()
    yield


@pytest_asyncio.fixture(loop_scope="session")
async def db(engine):
    async with get_sessionmaker()() as session:
        yield session


class ApiClient(httpx.AsyncClient):
    """httpx client that echoes the CSRF token like the real frontend does."""

    csrf: str | None = None

    async def request(self, method, url, **kwargs):
        if self.csrf and method.upper() not in ("GET", "HEAD", "OPTIONS"):
            headers = dict(kwargs.pop("headers", None) or {})
            headers.setdefault("X-CSRF-Token", self.csrf)
            kwargs["headers"] = headers
        return await super().request(method, url, **kwargs)


def make_client() -> ApiClient:
    return ApiClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver")


def last_token(kind: str, to: str | None = None) -> str:
    """Token from the most recent captured e-mail of a kind (the test mailer never delivers)."""
    message = next(m for m in reversed(ConsoleMailer.outbox) if m.kind == kind and (to is None or m.to == to))
    return message.action_url.split("token=")[1]


async def register(client: ApiClient, email: str, name: str = "Test User", org: str | None = None, verify: bool = True) -> dict:
    resp = await client.post("/api/v1/auth/register", json={"email": email, "password": PASSWORD, "full_name": name, "organisation_name": org})
    assert resp.status_code == 201, resp.text
    data = resp.json()
    client.csrf = data["csrf_token"]
    if verify:  # follow the verification link exactly as a user would
        confirmed = await client.post("/api/v1/auth/verify-email/confirm", json={"token": last_token("verify_email", email.lower())})
        assert confirmed.status_code == 200, confirmed.text
    return data


@pytest_asyncio.fixture(loop_scope="session")
async def anon():
    async with make_client() as client:
        yield client


@pytest_asyncio.fixture(loop_scope="session")
async def client():
    """Authenticated owner of organisation A."""
    async with make_client() as c:
        c.me = await register(c, "owner-a@example.com", "Alice Owner", "Org A")
        yield c


@pytest_asyncio.fixture(loop_scope="session")
async def other_client():
    """Authenticated owner of a different organisation (B)."""
    async with make_client() as c:
        c.me = await register(c, "owner-b@example.com", "Bob Owner", "Org B")
        yield c


@pytest_asyncio.fixture(loop_scope="session")
async def demo_data(db):
    from app.services import demo

    return await demo.load_demo(db)


@pytest.fixture
def settings():
    return get_settings()
