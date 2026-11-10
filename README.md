# SIGNAL ATLAS

**Open-source technology intelligence and commercial opportunity discovery.**
Signal Atlas turns public GitHub activity into evidence-backed intelligence: what is gaining momentum, who is building it, and which projects have the structural signals of a commercial opportunity.

> Status: **MVP (v0.2.0)** — runs locally; not deployed. Email delivery and card payments are implemented and tested with mocked providers, and need external accounts to switch on. See [PROGRESS.md](PROGRESS.md) for what is implemented, tested, configured and deployed.

## What makes it different

| Principle | How it shows up |
|---|---|
| Real data before impressive numbers | Every object carries `data_source`: `live_github` or `demo_fixture`. Demo fixtures are fictional, badged everywhere, and never mixed into live rankings. An empty database shows zeros, not invented statistics. |
| Facts kept apart from inference | Verified facts, calculated metrics, interpretations and hypotheses are labelled separately in the API and the UI. |
| Transparent scoring | A 0–100 score built from seven weighted metrics, each with an explanation, evidence, confidence and a list of missing data. Weights are configurable per organisation. |
| Read-only by design | GitHub access uses GET requests on public data. OAuth requests identity scopes only — never repository write access. |
| Works with no AI key | A deterministic rules engine produces complete reports. An LLM (Anthropic or any OpenAI-compatible endpoint) is optional enrichment, guarded so it cannot introduce figures that are not in the fact sheet. |

## Repository layout

```
backend/    FastAPI + SQLAlchemy 2 (async) + Alembic · intelligence engines · accounts · billing · job queue · 126 tests
frontend/   Next.js 15 + React 19 + TypeScript + Tailwind · Recharts · React Flow · 38 tests
*.md        Product, architecture, security, API and deployment documentation
```

## Quick start (Docker)

```bash
docker compose up --build
# open http://localhost:3000 and create an account
```

The compose stack starts PostgreSQL, the API, the background worker and the web app, and loads the fictional demo fixtures on first start (`SEED_DEMO_DATA=true`). To pull live data, open **Repository Intelligence → Search GitHub**, or **Settings → Data & jobs → Run discovery**.

## Quick start (without Docker)

Requirements: Python 3.11+, Node 20+, PostgreSQL 14+ (SQLite works for a quick look).

```bash
# 1. API
cd backend
python -m venv .venv && . .venv/bin/activate          # Windows PowerShell: .venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
cp ../.env.example .env                                # then edit DATABASE_URL and SECRET_KEY
alembic upgrade head
python -m app.cli demo-load                            # optional: fictional fixtures
uvicorn app.main:app --reload --port 8000

# 2. Worker (second terminal) – scheduled syncs, discovery, AI enrichment
python -m app.worker

# 3. Web app (third terminal)
cd frontend
npm install
npm run dev                                            # http://localhost:3000 (proxies /api to :8000)
```

No PostgreSQL to hand? Set `DATABASE_URL=sqlite+aiosqlite:///./signal_atlas.db` and `JOBS_INLINE=true`, then run `python -m app.cli init-db`.

### Useful commands

```bash
python -m app.cli discover                             # run curated live GitHub discovery
python -m app.cli discover "topic:llm stars:>1000"     # one custom search
python -m app.cli sync fastapi/fastapi                 # full sync of one repository
python -m app.cli recompute                            # recompute scores, opportunities and signals
python -m app.cli demo-load | demo-clear               # manage fictional fixtures
```

## Tests

```bash
cd backend  && pytest -q && ruff check app tests alembic     # 126 tests (SQLite); set TEST_DATABASE_URL to run on PostgreSQL
cd frontend && npm run lint && npm run typecheck && npm test && npm run build   # 38 tests
```

## Optional integrations

| Integration | Variables | Without it |
|---|---|---|
| GitHub server token | `GITHUB_TOKEN` (no scopes needed) | 60 requests/hour; closed-issue and pull-request totals shown as unavailable |
| GitHub OAuth | `GITHUB_OAUTH_CLIENT_ID`, `GITHUB_OAUTH_CLIENT_SECRET` | Email + password sign-in only; the UI shows a setup notice |
| AI enrichment | `LLM_PROVIDER` + `ANTHROPIC_API_KEY` or `OPENAI_API_KEY` | Reports use the rules engine (still complete) |
| Email delivery | `EMAIL_PROVIDER=resend`, `RESEND_API_KEY`, `EMAIL_FROM` | No email is sent; accounts cannot be verified (development prints links to the API log) |
| Card payments | `BILLING_PROVIDER=stripe`, `STRIPE_SECRET_KEY` (test key), `STRIPE_WEBHOOK_SECRET` | Plans are shown but cannot be purchased; the UI says so |
| Redis | `REDIS_URL` | In-memory rate limiting (fine for a single API instance) |

## Accounts, email and billing

* **Accounts** — email + password, server-side sessions, email verification, password reset. Unverified users can browse; verification is required for report generation, API keys and live GitHub requests.
* **Plans** — Free, Pro (£19/month or £190/year), Business (£49 or £490), Enterprise (custom). Prices and limits are defined once in `backend/app/plans.py` and can be overridden with `PLAN_OVERRIDES_JSON`.
* **Payments** — Stripe hosted checkout in **test mode only**, signed idempotent webhooks, cancellation at period end, a 7-day grace period for failed renewals, payment history. Setup steps are in [DEPLOYMENT.md](DEPLOYMENT.md).
* **Database migrations** — `alembic upgrade head` (two migrations: `0001` initial schema, `0002` email tokens and billing).
* **CI** — `.github/workflows/ci.yml` runs backend lint and tests (SQLite and PostgreSQL), migration checks, dependency audits, and frontend lint, type check, tests and build.

## Documentation

[PRD](PRD.md) · [Architecture](ARCHITECTURE.md) · [API](API_DOCUMENTATION.md) · [Security](SECURITY.md) · [Deployment](DEPLOYMENT.md) · [Implementation plan](IMPLEMENTATION_PLAN.md) · [Progress](PROGRESS.md) · [Tasks](TASKS.md)

Interactive API reference: `http://localhost:8000/api/docs`.
