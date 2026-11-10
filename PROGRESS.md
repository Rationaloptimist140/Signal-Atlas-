# Progress

_Last updated: 10 November 2026 — session 2 (MVP completion, v0.2.0)._

## Status at a glance

| Area | Implemented | Automated tests | Verified against the real service | Deployed |
|---|:-:|:-:|:-:|:-:|
| Repository, developer, trend, opportunity, competitor intelligence and scoring | ✅ | ✅ | ✅ live GitHub API (anonymous) | ❌ |
| Registration, login, sessions, roles, API keys | ✅ | ✅ | ✅ end to end in a browser | ❌ |
| Email verification and password reset | ✅ | ✅ | 🟡 flows verified end to end with development links; **no email has been sent through Resend** (no credentials) | ❌ |
| Subscription lifecycle, entitlements, usage limits | ✅ | ✅ | n/a | ❌ |
| Stripe hosted checkout and webhooks (test mode) | ✅ | ✅ mocked provider | ❌ **not yet run against Stripe** (no credentials) | ❌ |
| GitHub OAuth sign-in | ✅ | ✅ mocked provider | ❌ needs an OAuth app | ❌ |
| AI report enrichment | ✅ | ✅ fake provider | ❌ needs an LLM key | ❌ |
| CI workflow | ✅ file in repository | — | see "CI" below | — |

Nothing is deployed and no paid resource has been created. The product is **not production-ready** until the external configuration in [TASKS.md](TASKS.md) is done.

## Verification performed in session 2

| Check | Result |
|---|---|
| Backend tests on SQLite | 126 passed |
| Backend tests on PostgreSQL 16 | 126 passed |
| `ruff check app tests alembic` | clean |
| Migrations `0001` → `0002` on PostgreSQL 16 (upgrade, downgrade, upgrade) and `alembic check` | applied; no drift |
| Migrations on SQLite (upgrade to head, downgrade to base) | passed |
| `pip-audit` / `npm audit --omit=dev` | no known vulnerabilities / 0 vulnerabilities |
| Frontend ESLint, `tsc --noEmit` | clean |
| Frontend tests | 38 passed |
| Frontend production build | succeeded (25 routes) |
| Browser run (headless Chromium, desktop and 390 px) | 18 of 18 checks passed, no console errors: landing → pricing → sign-up → soft gate blocks a report → verify by link → report generated → sign out → forgot password → reset → old password rejected → new password accepted |

## Definition of done

| Criterion | Status |
|---|---|
| Application, frontend build and backend start; migrations run | ✅ |
| Register and log in | ✅ |
| Email verification and password recovery "when configured" | 🟡 implemented and tested; delivery needs a Resend key and a verified sending domain |
| Repository discovery, developer intelligence, emerging signals | ✅ |
| Opportunity reports, explainable scoring, competitor monitoring | ✅ (AI enrichment needs an LLM key; rule-based reports work without) |
| Pricing and subscription management | ✅ |
| Card checkout in test mode "when credentials are configured" | 🟡 implemented and tested with mocked Stripe responses; not yet run against Stripe |
| Entitlements protect premium features; usage limits enforced | ✅ server-side |
| Security tests and full regression pass | ✅ |
| CI active or blocker documented | 🟡 see below |
| Documentation and environment examples accurate | ✅ |
| Delivered to GitHub | ✅ see the pull request |

## CI

`.github/workflows/ci.yml` is complete. The GitHub App used to push this code is not allowed to write files under `.github/workflows/` (GitHub returns 403: the installation lacks the **Workflows** permission). Until that permission is granted, or the file is added through GitHub's web editor, no checks run on GitHub. All checks in the workflow were run locally and pass.

## What changed in session 2

* **Accounts** — email verification (24-hour single-use hashed tokens), password reset (30-minute tokens, generic responses, all sessions revoked), "sign out everywhere", soft gate enforced in the API.
* **Mailer** — provider-independent, with a Resend adapter and HTML + plain-text templates. Development prints links to the API log; production never logs tokens.
* **Billing** — four plans with monthly and annual prices in one catalogue (`PLAN_OVERRIDES_JSON` to change them); subscription states `pending`, `active`, `past_due`, `cancelled`, `expired`; 7-day grace period; cancellation at period end; payment history; Stripe hosted checkout, signed and idempotent webhooks, refunds; live keys and live-mode events refused.
* **Frontend** — public landing and pricing pages, forgot / reset / verify pages, verification banner, rebuilt billing dashboard (plan, status, usage, checkout, cancel, payment history), ESLint.
* **Other** — five-minute cache for repeated live GitHub searches; legacy `professional` plan folded into `business` by migration; existing accounts treated as verified by migration.

## Sending domain note (mail.flanuer.com)

Public DNS on 10 November 2026: `flanuer.com` is registered with nameservers at Porkbun. Neither `flanuer.com` nor `mail.flanuer.com` has MX or TXT records (no SPF, DKIM or DMARC), and `mail.flanuer.com` has A records pointing at a web host. It is therefore **not currently set up to send email**. It can be used with Resend if whoever controls the domain adds the DNS records Resend generates; nothing was changed and ownership was not assumed. The sender is configurable through `EMAIL_FROM`.

## Known limitations

* Anonymous GitHub access allows about five full repository syncs an hour; set `GITHUB_TOKEN` for practical use.
* Stripe plan switches for existing subscribers go through the Stripe customer portal, not an in-app upgrade flow.
* Registration reveals whether an email address is already registered.
* Rate limiting is per process unless Redis is configured.
* No teammate invitations or multi-factor authentication.
* Technology classification is keyword-based and labelled as inferred; scores are unvalidated heuristics.
* The repository has no licence file: all rights are reserved by default.
