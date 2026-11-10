# Architecture

## Overview

```
Browser ──HTTPS──> Next.js (frontend service)
                      │  /api/* rewrite (server-side proxy; cookies stay first-party)
                      ▼
                 FastAPI (api service) ───────────┐
                      │                           │ enqueue
                      ▼                           ▼
                 PostgreSQL  <──── poll ──── Worker (python -m app.worker)
                                                  │ read-only HTTPS
                                                  ▼
                              GitHub REST + GraphQL · LLM provider (optional)
```

Three deployable processes, one database. Redis is optional.

## Key decisions

| Decision | Why |
|---|---|
| **Next.js proxies `/api` to FastAPI** | The browser only talks to one origin, so the session cookie is first-party, `HttpOnly`, `SameSite=Lax`; no CORS credentials, no API URL or token in the bundle. |
| **PostgreSQL-backed job queue** (`jobs` table, `FOR UPDATE SKIP LOCKED`) | Durable background work with retries and deferral without paying for a second datastore. Redis remains optional (shared rate limiting when scaling to several API instances). |
| **Async SQLAlchemy 2 + asyncpg** | Matches FastAPI's async model; GitHub and LLM calls are I/O bound. |
| **Relational graph, no Neo4j** | Repos ↔ developers ↔ technologies ↔ dependencies are join tables; the ecosystem map is a bounded query. Revisit only if multi-hop traversals become a product feature. |
| **Rules engine first, LLM as enrichment** | Deterministic, testable, free to run; reports stay truthful with no key and during provider outages. |
| **Weight-independent metric storage** | Metric scores are stored once; totals are derived per organisation from its weights, so custom weighting needs no recomputation and never changes evidence. |
| **Two sync levels** | `search` (1 request ≈ 30–100 repositories with headline data) and `full` (~10 requests per repository). Keeps the product useful inside GitHub's anonymous quota. |
| **Global public data, tenant-scoped private data** | Public GitHub intelligence is shared by all tenants; watchlists, competitors, reports, API keys, notifications, weights and usage are filtered by `organisation_id` on every query. |

## Backend layout (`backend/app`)

```
config.py            environment settings (production guards)
models.py            33 tables; UTC datetimes; data_source on all intelligence tables
security.py          argon2 hashing, opaque tokens, Fernet encryption, HMAC signing
deps.py              session / API-key principals, CSRF, roles, rate limits
ratelimit.py         fixed-window limiter (memory or Redis)
taxonomy.py          9 categories, 39 technologies, keyword classifier
plans.py             plans and entitlements
routers/             auth · repositories · developers · trends · opportunities(+reports) · competitors(+watchlists) · dashboard · account
services/
  github_client.py   read-only REST + GraphQL client, ETags, rate-limit handling
  ingestion.py       discovery, full sync, change detection, snapshots
  manifests.py       package.json / requirements.txt / pyproject.toml / go.mod / Cargo.toml parsers
  scoring.py         pure scoring engine (Engine 6)
  trends.py          signal detection (Engine 3)
  opportunities.py   rule-based opportunity analysis (Engine 4)
  intelligence.py    facts builder, score persistence, opportunity refresh
  reports.py         fact sheets and report assembly
  ai/                providers, schemas, guardrails, enrichment
  jobs.py            queue, handlers, recurring schedule, notifications
  usage.py           entitlements, metering, audit log
  demo.py            fictional fixtures
worker.py · cli.py   background process and operational commands
```

## Data model

**Identity & tenancy:** `organisations`, `users`, `memberships` (role), `sessions`, `github_accounts` (encrypted token).
**Global intelligence:** `repositories`, `repository_snapshots` (one per repo per day), `repository_languages`, `languages`, `technologies`, `repository_technologies`, `commit_activity`, `releases`, `dependencies`, `fork_relationships`, `developer_profiles`, `contributors`, `trend_signals`, `opportunity_scores`, `opportunities`, `change_events`.
**Tenant-scoped:** `scoring_configs`, `competitors`, `competitor_repositories`, `watchlists`, `watchlist_items`, `intelligence_reports`, `api_keys`, `subscriptions`, `usage_records`, `notifications`, `audit_logs`.
**Infrastructure:** `jobs`.

Constraints: unique keys on natural identifiers (`github_id`, `full_name`, `(repo, day)` snapshots, `(repo, tag)` releases …), check constraints on enumerations, cascading foreign keys, composite indexes for the main list queries. Schema is managed by Alembic (`alembic/versions`).

## Data flow

1. **Discover** — a search query upserts repositories at `search` level, classifies them, and records today's snapshot.
2. **Full sync** — conditional request (ETag); if changed: languages, contributors (+ count from pagination headers), releases, commit statistics, forks, root manifests, GraphQL totals (token only). Differences from the previous sync become `change_events`. Anything unavailable is written to `missing_data`.
3. **Score** — `build_facts` → `compute_score` → `opportunity_scores` (history kept, one row per day) → `opportunities` refreshed.
4. **Detect trends** — snapshot pairs and commit history → `trend_signals` with evidence; signals in the current period that no longer hold are retracted.
5. **Notify** — change events on watched or competitor repositories create per-organisation notifications.
6. **Report** — fact sheet with numbered facts → rules report → optional LLM enrichment (validated, guarded) → stored per organisation.

## Background jobs

`sync_repository`, `sync_developer`, `discover`, `discover_all`, `deepen_top_repositories`, `recompute_intelligence`, `monitor_watched`, `enrich_report`, `retention_cleanup`.
Retries use exponential backoff (30 s → 2 min → 10 min → 1 h). A GitHub rate limit **defers** the job until the reset time without consuming an attempt. Recurring jobs are scheduled by the worker every `SYNC_INTERVAL_HOURS`.

## Frontend layout (`frontend/src`)

```
app/(auth)           login, register
app/(app)            authenticated shell and the eleven sections (+ detail pages)
components/ui.tsx    design-system primitives (shadcn-style, Radix dialog, CVA variants)
components/intel.tsx provenance / basis / confidence labels, score ring and breakdown, signal and opportunity cards
components/charts.tsx, ecosystem-map.tsx   Recharts and React Flow visualisations
components/shell.tsx sidebar, global search, notifications, data-source switch, provenance banner
lib/api.ts           fetch client (CSRF, typed errors, upgrade events)
lib/session.tsx      session context and SWR hooks (useIntel applies the live/demo filter)
middleware.ts        redirect signed-out visitors (UX only; the API is the security boundary)
```

## Scaling path

Add a GitHub token (5,000 req/h) → add worker replicas (queue is safe for concurrent workers on PostgreSQL) → add Redis for shared rate limiting → read replicas / materialised aggregates for dashboard queries → consider a GitHub App for higher, per-installation quotas.
