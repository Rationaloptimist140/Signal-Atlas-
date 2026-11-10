# API Documentation

Base path: `/api/v1` · Interactive reference: `/api/docs` (Swagger) and `/api/redoc` · Schema: `/api/openapi.json`.

## Authentication

| Method | How | Use |
|---|---|---|
| Session cookie | `POST /auth/login` sets `sa_session` (HttpOnly). Send `X-CSRF-Token` (from `/auth/me` or the `sa_csrf` cookie) on every POST/PUT/PATCH/DELETE | Browser |
| API key | `X-API-Key: sa_live_…` or `Authorization: Bearer sa_live_…` | Scripts and integrations (Pro plan and above) |

API keys are read-only unless created with the `read write` scope, and can never call account-management endpoints (`/auth/*`, `/api-keys`, `/billing/*`, `/settings/*`, `/notifications`).

## Conventions

* **Provenance** — intelligence objects include `data_source` (`live_github` | `demo_fixture`). Intelligence endpoints accept `source=auto|live|demo|all`; `auto` (default) returns live data when any exists, otherwise demo fixtures.
* **Pagination** — `page` (≥1) and `page_size` (≤100); responses are `{items, total, page, page_size}`.
* **Errors** — `{"error": {"code", "message", ...}}`.

| Status | Code | Meaning |
|---|---|---|
| 401 | `not_authenticated`, `invalid_api_key`, `invalid_credentials` | Sign in or check the key |
| 402 | `upgrade_required` | Plan limit reached; payload has `feature`, `current_plan`, `suggested_plan`, `limit`, `used` |
| 403 | `csrf_failed`, `insufficient_role`, `read_only_key`, `session_required` | Not permitted |
| 404 | `not_found` | Missing, or belongs to another organisation |
| 422 | `validation_error` | Invalid input; `fields` lists problems |
| 423 | `account_locked` | Too many failed logins |
| 429 | `rate_limited` | Honour `Retry-After` |
| 503 | `github_rate_limited`, `github_oauth_not_configured` | Upstream limit or missing setup |

## Endpoints

### Auth
`GET /auth/providers` · `POST /auth/register` · `POST /auth/login` · `POST /auth/logout` · `GET /auth/me` · `PATCH /auth/me` · `POST /auth/change-password` · `GET /auth/github/start?mode=connect|login` · `DELETE /auth/github`

### Repository Intelligence
| Endpoint | Description |
|---|---|
| `GET /repositories` | Search and filter. Params: `q`, `category`, `technology`, `language`, `license` (SPDX or `none`), `min_stars`, `min_contributors`, `activity` (`active_7d`/`active_30d`/`active_90d`/`stale`), `sort` (`stars`, `score`, `recently_pushed`, `newest`, `forks`, `contributors`, `name`) |
| `GET /repositories/facets` | Category, language and licence counts |
| `GET /repositories/github-search?q=` | Live GitHub search; stores and returns results (metered) |
| `POST /repositories/track` | Track `{"full_name": "owner/repo"}` and queue a full sync |
| `GET /repositories/{id}` | Profile: facts, languages, inferred technologies, score, licence reading, provenance, missing data |
| `GET /repositories/{id}/activity` | Weekly commits, star snapshots, issue/PR totals, change events |
| `GET /repositories/{id}/contributors` · `/dependencies` · `/forks` · `/releases` | Detail sections |
| `GET /repositories/{id}/score` | Score with metrics, evidence, confidence, missing data and history |
| `POST /repositories/{id}/sync` | Queue a full sync (metered) |

### Developer Intelligence
`GET /developers` (`q`, `language`, `sort`: `tracked_contributions`, `followers`, `emerging`, `login`) · `GET /developers/{id}` (sections tagged `public_data` or `inferred_analysis`) · `POST /developers/{id}/sync`

### Trends and technologies
`GET /trends` (`window`: `daily`/`weekly`/`monthly`/`all`, `category`, `signal_type`, `limit`) · `GET /trends/momentum` · `GET /technologies` · `GET /technologies/{slug}`

Signal types: `star_surge`, `unusual_growth`, `commit_acceleration`, `breakout_new_project`, `contributor_growth`, `release_burst`, `category_momentum`, `emerging_cluster`. Each carries `strength`, `confidence`, `summary` and an `evidence` list (`verified` / `calculated`, with source links).

### Opportunities and reports
`GET /opportunities` (`category`, `min_score`, `risk`, `maturity`, `confidence`, `sort`) · `GET /opportunities/{id}` · `POST /reports/generate` · `GET /reports` · `GET /reports/{id}` · `DELETE /reports/{id}` · `GET /reports-capabilities`

```jsonc
// POST /reports/generate
{ "report_type": "opportunity", "subject_id": 12 }                 // or "repository", "competitor"
{ "report_type": "comparison", "repository_ids": [3, 8, 21] }      // 2–4 repositories
```

A report's `content` contains `executive_summary`, `verified_facts` (numbered `F1…`), `calculated_metrics`, `interpretations`, `hypotheses`, `commercial_use_cases`, `score`, `analysis`, `recommended_next_steps`, `sources` and `provenance` (provider, model, `ai_enriched`, guardrail report). Each interpretation and hypothesis states `generated_by` (`rules` or `ai`). With an AI provider configured the response has `status: "enriching"` until the worker finishes; the rule-based content is complete immediately.

### Competitors and watchlists
`GET|POST /competitors` · `GET|PATCH|DELETE /competitors/{id}` · `POST /competitors/{id}/repositories` (`repository_id` or `full_name`) · `DELETE /competitors/{id}/repositories/{repository_id}`
`GET|POST /watchlists` · `DELETE /watchlists/{id}` · `POST /watchlists/{id}/items` (`item_type`: `repository`/`opportunity`/`developer`) · `DELETE /watchlists/{id}/items/{item_id}` · `GET /watchlists/saved?item_type=`

### Dashboard, search, notifications
`GET /dashboard` · `GET /ecosystem/graph` (`category`, `limit`) · `GET /search?q=` · `GET /notifications` · `POST /notifications/read-all` · `POST /notifications/{id}/read`

### Account
`GET|POST /api-keys` · `DELETE /api-keys/{id}` · `GET /billing/plans` · `GET /billing/subscription` · `POST /billing/checkout` (returns 501 unless development plan switching is enabled) · `GET|PUT|DELETE /settings/scoring` · `GET|PATCH /settings/organisation` · `GET /settings/audit-log`

### System (workspace admin; platform admins only in production)
`GET /system/status` · `POST /system/demo/load` · `DELETE /system/demo` · `POST /system/discover` · `POST /system/recompute`

### Health
`GET /health` · `GET /health/ready`

## Example

```bash
curl "https://YOUR-HOST/api/v1/opportunities?min_score=65&risk=low&source=live" \
  -H "X-API-Key: sa_live_xxxxxxxx_your_secret"
```

## Rate limits and metering

| Plan | Requests / minute per key | Requests / month |
|---|---:|---:|
| Pro | 60 | 10,000 |
| Professional | 120 | 100,000 |
| Business | 300 | 1,000,000 |
| Enterprise | 600 | Unlimited |

Every accepted API-key request increments the organisation's monthly `api_requests` counter (`GET /billing/subscription`).
