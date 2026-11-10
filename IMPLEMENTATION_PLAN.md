# Implementation Plan

Phases follow the build specification. Status key: ✅ done · 🟡 partly done · ⬜ not started. Detail and evidence are in [PROGRESS.md](PROGRESS.md); the backlog is in [TASKS.md](TASKS.md).

## Phase 1 — Foundation ✅
- ✅ Monorepo structure (`backend/`, `frontend/`), environment-based configuration, Docker Compose
- ✅ FastAPI application, async SQLAlchemy, PostgreSQL schema (33 tables), Alembic migration
- ✅ Email + password authentication, server-side sessions, CSRF, roles, profile
- ✅ GitHub OAuth (identity scopes only) — code complete, needs credentials to enable
- ✅ Design system (dark palette, Geist typography, primitives) and responsive application shell

## Phase 2 — Core intelligence ✅
- ✅ Read-only GitHub client (REST + GraphQL), rate-limit handling, ETag incremental sync
- ✅ Repository discovery, profiles and eight detail sections
- ✅ Developer profiles with public/inferred separation
- ✅ Activity analytics (commits, snapshots, releases, change events)
- ✅ Technology classification (9 categories, 39 technologies), search, filters, sorting

## Phase 3 — Commercial intelligence ✅
- ✅ Trend detection across daily / weekly / monthly windows
- ✅ Business Potential Scoring with configurable weights
- ✅ Rule-based opportunity analysis with labelled hypotheses
- ✅ Intelligence reports (opportunity, repository, comparison, competitor)
- ✅ Provider-independent AI enrichment with validation and guardrails — needs an API key to enable
- ✅ Evidence, confidence, freshness and missing-data tracking

## Phase 4 — Competitive intelligence ✅
- ✅ Competitors with attached repositories and comparison
- ✅ Watchlists for repositories, opportunities and developers
- ✅ Release, dependency and stack change detection; notifications
- ✅ Competitor change reports
- 🟡 "New feature detection" is limited to release notes and dependency changes (no code diff analysis)

## Phase 5 — Commercialisation 🟡
- ✅ Plans, entitlements and usage limits enforced by the API; upgrade prompts in the UI
- ✅ API keys, per-key rate limits, monthly usage metering
- ✅ Billing architecture with a modular provider (manual provider active)
- ⬜ Live payment provider (deliberately deferred until pricing is validated)

## Cross-cutting ✅
- ✅ Background worker with retries, rate-limit deferral and recurring schedule
- ✅ Security controls (see SECURITY.md) and audit logging
- ✅ Automated tests: backend 101, frontend 28; CI workflow
- ✅ Documentation set and Railway deployment configuration

## Next phases (proposed)
1. **Launch readiness** — deploy to Railway, add `GITHUB_TOKEN`, email provider (verification, reset, invitations), privacy notice and terms.
2. **Data depth** — SBOM-based dependencies, package-registry adoption data, stargazer history backfill, GitHub App for higher quotas.
3. **Validation** — backtest scores against known outcomes; customer interviews on pricing and limits.
4. **Monetisation** — Stripe provider behind the existing billing interface once pricing is validated.
