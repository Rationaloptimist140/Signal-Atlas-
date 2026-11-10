# Progress

_Last updated: 10 November 2026 — implementation session 1._

## Summary

Phases 1–4 are implemented and Phase 5 is implemented except live payments. The product runs end to end locally: FastAPI on PostgreSQL 16, Next.js through its API proxy, real public GitHub data. **Nothing is deployed.**

## Verification performed in this session

| Check | Result |
|---|---|
| Backend tests on SQLite | 101 passed |
| Backend tests on PostgreSQL 16 | 101 passed |
| `ruff check app tests alembic` | clean |
| `alembic upgrade head` + `alembic check` on PostgreSQL 16 | applied; no drift from models |
| `pip-audit -r requirements.txt` | no known vulnerabilities |
| Frontend `tsc --noEmit` | clean |
| Frontend tests (Vitest + Testing Library) | 28 passed |
| Frontend `next build` | succeeded (20 routes) |
| `npm audit --omit=dev` | 0 vulnerabilities (PostCSS inside Next pinned via an npm override) |
| Live GitHub API (anonymous) | Discovery search stored 30 repositories; full sync of `fastapi/fastapi` collected languages, contributors, 52 weeks of commits, releases, forks and dependencies; scores, opportunities and signals computed from that data |
| End-to-end through the Next.js proxy | Register → session cookie → dashboard → demo load → report generation; CSRF rejection confirmed; all 12 app pages returned HTTP 200 |
| Browser smoke test (headless Chromium, ad hoc) | 13 screens rendered at 1440px and 390px with no console errors |

Not verified against real services (no credentials available): GitHub OAuth (tested with mocked GitHub responses), LLM enrichment (tested with a fake provider), Railway deployment.

## Definition of MVP success

| # | Capability | Status |
|---|---|---|
| 1 | Register and log in | ✅ Verified end to end |
| 2 | Connect a GitHub account securely | 🟡 Implemented and tested with mocks; needs `GITHUB_OAUTH_CLIENT_ID/SECRET` to use |
| 3 | Search public GitHub repositories | ✅ Verified against the live GitHub API |
| 4 | Explore repository development activity | ✅ Verified with live data |
| 5 | View developer profiles | ✅ |
| 6 | Identify emerging technology signals | ✅ (daily/weekly star signals need snapshots on several days) |
| 7 | View commercial opportunity scores | ✅ |
| 8 | Generate AI-powered opportunity reports | 🟡 Rules-engine reports verified; AI enrichment implemented, needs an LLM key to use |
| 9 | Save repositories and opportunities | ✅ |
| 10 | Monitor selected competitors | ✅ (change history starts at each repository's first full sync) |

## What was built

**Backend** — 72 API operations; 33-table schema with one Alembic migration; argon2 passwords, hashed server-side sessions, CSRF, roles, API keys; read-only GitHub client with ETags and rate-limit deferral; ingestion at two depths; manifest parsers for five ecosystems; taxonomy classifier; scoring engine; trend detection; opportunity analysis; report builder; AI providers with guardrails; PostgreSQL job queue and worker; plans, metering and audit log; fictional demo fixtures; CLI.

**Frontend** — design system and responsive shell (collapsible sidebar, global search, notifications, live/demo switch, provenance banner); 20 routes covering all eleven sections plus detail pages; momentum charts, opportunity radar, metric radar, ecosystem map; forms with client-side validation; loading, empty and error states; upgrade prompts.

**Operations** — Dockerfiles, Docker Compose, Railway config for three services, GitHub Actions CI, `.env.example`.

## Decisions taken (and why)

* **Job queue on PostgreSQL, Redis optional** — avoids a second paid service; Redis only adds shared rate limiting for multi-instance deployments.
* **Score damping for missing data** — live testing showed repositories known only from search results outranking fully analysed ones on thin evidence. Totals are now pulled towards 50 in proportion to the weight without data, and low-confidence scores cannot receive an "investigate" recommendation.
* **Release-burst guard** — only the latest 100 releases are fetched; when they all fall inside the comparison window the baseline is unknown, so no burst is claimed.
* **Demo fixtures are fictional projects**, not real repositories with made-up figures, and are excluded from peer comparisons with live data.
* **Tailwind 3.4, Next 15, Recharts 2** — pinned to mature majors rather than the newest releases to reduce build risk.

## Known limitations

* Anonymous GitHub access allows roughly five full repository syncs per hour; set `GITHUB_TOKEN` for practical use.
* Closed-issue and pull-request totals need a token (GraphQL); without one they are reported as missing.
* Technology classification is keyword-based and will misclassify some repositories; it is labelled as inferred.
* Dependencies are read from root-level manifests only.
* No email verification, password reset or teammate invitations (no email provider configured).
* Rate limiting is per process without Redis.
* The ad hoc browser smoke test is not yet a committed end-to-end suite; there is no ESLint configuration.
* Scores are unvalidated heuristics.

## Change log

* **Session 1** — Phases 1–5 implemented as above; documentation and deployment configuration written.
