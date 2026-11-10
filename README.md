# SIGNAL ATLAS

**Open-source technology intelligence and commercial opportunity discovery.**
Signal Atlas turns public GitHub activity into evidence-backed intelligence: what is gaining momentum, who is building it, and which projects have the structural signals of a commercial opportunity.

> Status: **MVP (v0.1.0)** — runs locally and is ready to deploy to Railway. Nothing has been deployed and no paid resource has been created. See [PROGRESS.md](PROGRESS.md).

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
backend/    FastAPI + SQLAlchemy 2 (async) + Alembic · intelligence engines · job queue · 101 tests
frontend/   Next.js 15 + React 19 + TypeScript + Tailwind · Recharts · React Flow · 28 tests
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
cd backend  && pytest -q && ruff check app tests alembic     # 101 tests (SQLite); set TEST_DATABASE_URL to run on PostgreSQL
cd frontend && npm run typecheck && npm test && npm run build   # 28 tests
```

## Optional integrations

| Integration | Variables | Without it |
|---|---|---|
| GitHub server token | `GITHUB_TOKEN` (no scopes needed) | 60 requests/hour; closed-issue and pull-request totals shown as unavailable |
| GitHub OAuth | `GITHUB_OAUTH_CLIENT_ID`, `GITHUB_OAUTH_CLIENT_SECRET` | Email + password sign-in only; the UI shows a setup notice |
| AI enrichment | `LLM_PROVIDER` + `ANTHROPIC_API_KEY` or `OPENAI_API_KEY` | Reports use the rules engine (still complete) |
| Redis | `REDIS_URL` | In-memory rate limiting (fine for a single API instance) |
| Payments | — | Intentionally not activated until pricing is validated |

## Documentation

[PRD](PRD.md) · [Architecture](ARCHITECTURE.md) · [API](API_DOCUMENTATION.md) · [Security](SECURITY.md) · [Deployment](DEPLOYMENT.md) · [Implementation plan](IMPLEMENTATION_PLAN.md) · [Progress](PROGRESS.md) · [Tasks](TASKS.md)

Interactive API reference: `http://localhost:8000/api/docs`.
