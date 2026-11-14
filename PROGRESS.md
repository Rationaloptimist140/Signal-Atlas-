# Progress

_Last updated: 14 November 2026 — session 4 (production deployment, v0.3.1)._

## Where things stand

**The application is deployed on Railway and serving over HTTPS:** <https://web-production-e6e86402.up.railway.app>. It holds live GitHub data and passes the deployed-site journey for everything that does not need e-mail or payments.

**It is not ready to launch.** No e-mail can be sent, so nobody can verify an address, and without a verified address reports, API keys and live GitHub requests stay locked. Card payments are not configured. CI has still never run on GitHub. Each of these needs something only the owner can supply (see [TASKS.md](TASKS.md)).

How each area was verified:

| Label | Meaning |
|---|---|
| **Local** | Run on a developer machine against real components (PostgreSQL 16, Redis 7, a real browser, the public GitHub API) |
| **Mock** | Provider replaced by a mocked HTTP response or the local Stripe stub |
| **Sandbox** | Run against the provider's own test environment |
| **Production** | Run on the deployed system |
| **Blocked** | Cannot be done without a credential, permission or approval |

| Area | Local | Mock | Sandbox | Production |
|---|:-:|:-:|:-:|:-:|
| Intelligence features (repositories, trends, opportunities, scoring) | ✅ | — | — | ✅ 234 live repositories, pages and profiles load |
| Accounts, sessions, sign-out, CSRF, soft verification gate | ✅ | — | — | ✅ |
| Sign-up and password-reset request without account enumeration | ✅ | — | — | ✅ |
| Tenant isolation (one workspace cannot change another's data) | ✅ | — | — | ✅ |
| Rate limiting on Redis | ✅ real Redis 7 | ✅ | — | ✅ shared Redis; sign-in limit returns 429 with `Retry-After` |
| Rate limiting fails closed when Redis is down | ✅ real Redis 7 stopped mid-run | ✅ | — | Not tested (would take the live service down) |
| Content-Security-Policy and security headers | ✅ | — | — | ✅ real browser, zero violations |
| Database migrations | ✅ PostgreSQL 16 | — | — | ✅ `0001`→`0002` applied on first start; data kept across four redeploys |
| Mobile layout (390px) | ✅ | — | — | ✅ six pages, no overflow |
| E-mail content, links, expiry, single use, limits | ✅ | ✅ Resend API mocked | **Blocked** — no Resend key or verified domain | **Blocked** |
| **Real e-mail delivery** | — | — | **Blocked — never tested** | **Blocked — never tested** |
| Stripe checkout, webhooks, renewal, failure, cancellation, refunds, history, entitlements | ✅ browser journey against the local stub | ✅ | **Blocked** — no Stripe test key | **Blocked**; checkout refuses safely with "not configured", no plan change |
| **Real Stripe test-mode checkout** | — | — | **Blocked — never tested** | **Blocked — never tested** |
| Verified-only features on the live site (report generation, API keys, live GitHub search) | ✅ | — | — | **Blocked** — refusal confirmed, success path needs e-mail |
| GitHub sign-in (OAuth) | — | ✅ | **Blocked** — no OAuth app | Not configured |
| AI report enrichment | — | ✅ | **Blocked** — no LLM key | Not configured |
| CI on GitHub | ✅ every step run by hand | — | **Blocked** — Workflows permission; zero runs | — |
| Database export and restore | — | — | — | **Blocked** — no shell or database connection from the build environment; steps in DEPLOYMENT.md §8 |

## Production deployment (session 4)

| Item | Value |
|---|---|
| Public address | <https://web-production-e6e86402.up.railway.app> (HTTP redirects to HTTPS) |
| Railway project | `signal-atlas`, environment `production` — new project; the three existing projects were not touched |
| Services | `web` (Next.js, public), `api` (FastAPI, private network only), `Postgres`, `Redis` — both with volumes |
| Not created | `worker`. Jobs run inline, so nothing runs on a timer (see Known limitations) |
| Source | `main`, auto-deploy on push; `api` watches `/backend/**`, `web` watches `/frontend/**` |
| Limits | 1 vCPU / 1 GB per app service |
| Health checks | `api` `/health/ready` (database + Redis), `web` `/login` |
| Configuration check | `python -m app.cli doctor`: 0 failures; warnings only for e-mail, payments, GitHub token, GitHub sign-in and AI (all not configured) |

Both Docker images built and started first time. One setting was wrong and is corrected: `TRUSTED_PROXY_HOPS` must be `2` on Railway, not `1`. With `1` every visitor appeared to the API as the same Railway address and would have shared a single rate-limit allowance.

**Deployed-site journey** (`e2e/production.mjs`, real browser, fresh account): 34 passed, 0 failed, 3 blocked. The blocked steps are e-mail verification, completing a password reset, and checkout through to cancellation.

**Data:** 234 repositories from nine live GitHub searches; three more searches are still queued after GitHub's anonymous rate limit. No demonstration fixtures are loaded.

**Test accounts left in the database** (all `@example.com`, unverified, Free): `persist-1794648557`, `e2e-prod-1794648968439`, `e2e-prod-other-1794648968439`, `e2e-prod-1794649035661`, `e2e-prod-other-1794649035661`, plus any from later runs of the journey. They can be deleted once a database connection is available.

## Verification performed in session 3

| Check | Result |
|---|---|
| Backend tests, SQLite | 158 passed, 1 skipped (needs Redis) |
| Backend tests, PostgreSQL 16 + Redis 7 | 159 passed |
| Ruff · `alembic check` · `pip-audit` | clean · no drift · no known vulnerabilities |
| Frontend ESLint · TypeScript · tests · production build | clean · clean · 42 passed · built |
| `npm audit --omit=dev` | 0 vulnerabilities |
| Acceptance journey in a real browser (production build, PostgreSQL, Redis, Stripe stub) | 32 of 32 checks passed; no CSP violations or console errors |
| Token leakage | No e-mail token appeared in any API or web server request log |

## Acceptance journey (session 3)

| # | Step | Result | How |
|---|---|---|---|
| 1 | Open Signal Atlas | Pass | Local |
| 2 | Register a new user | Pass | Local |
| 3 | Send and receive the verification e-mail | Link issued and followed from the development log. **Delivery to an inbox: blocked** | Local / Blocked |
| 4 | Verify the account | Pass (link is single-use) | Local |
| 5 | Sign in | Pass | Local |
| 6 | Browse repository intelligence | Pass | Local |
| 7 | Discover an emerging technology | Pass | Local |
| 8 | Generate an opportunity report | Pass | Local |
| 9 | Premium action as a Free user | Refused with an upgrade prompt | Local |
| 10 | Checkout | Cancelled and completed checkouts pass **against the local stub**. Stripe test mode: **blocked** | Mock / Blocked |
| 11 | Subscription activation | Pass, including with webhooks switched off | Mock |
| 12 | Premium entitlement | API key creation unlocked; key authenticates | Mock |
| 13 | Cancel the subscription | Pass | Mock |
| 14 | Subscription state | Failed renewal → grace → recovery → cancelled-at-period-end all correct | Mock |
| 15 | Password recovery | Pass; other devices signed out; old password rejected | Local |
| 16 | Sign out and session revocation | Old cookie rejected by the API | Local |

## Security findings

| Finding | Severity | Status |
|---|---|---|
| Registration revealed whether an e-mail was registered | Low | **Fixed.** Identical `202` response and no session either way; existing owners are told by e-mail. Residual under the soft gate documented in SECURITY.md, with `LOGIN_REQUIRES_VERIFIED_EMAIL` to close it fully |
| Rate limiting was per process | Low | **Fixed.** Redis-backed, required in production unless explicitly waived; sensitive actions fail closed when Redis is down |
| No Content-Security-Policy | Low | **Fixed.** Nonce-based policy on pages, `default-src 'none'` on the API |
| Per-IP limits trusted the first `X-Forwarded-For` entry, which a client can forge | Medium (found this session) | **Fixed.** Only the trusted end of the chain is used (`TRUSTED_PROXY_HOPS`) |
| E-mail tokens travelled in the query string and could reach platform access logs | Low (found this session) | **Fixed.** Tokens are in the URL fragment |
| Production would start on weak settings other than the secret key | Low (found this session) | **Fixed.** Start-up refuses SQLite, non-https URLs, insecure cookies, demo seeding, an undecided rate-limit backend |
| Refunds could not be matched on newer Stripe API versions | Low (found this session) | **Fixed** (payment-intent link plus a fallback); mock-tested only |

| A listed platform-admin e-mail gave instance-wide tools to whoever registered that address first, verified or not | Medium (found in session 4) | **Fixed.** The address must be verified. `PLATFORM_ADMIN_EMAILS` is unset on the live deployment until e-mail works |
| `TRUSTED_PROXY_HOPS=1` made all visitors share one per-IP allowance on Railway | Medium (found in session 4) | **Fixed** on the live deployment (`2`) and in the documentation |

No critical or high-severity issue is open.

## Deployment preparation

* Deprecated `railway.json` files removed (Railway no longer reads them for new services); exact dashboard settings are in [DEPLOYMENT.md](DEPLOYMENT.md).
* The API container now listens on IPv4 and IPv6 (Railway's private network can be IPv6-only) and has a container health check.
* `/health/ready` covers the database and Redis.
* `python -m app.cli doctor` checks configuration, database migrations, Redis, the Resend domain, the Stripe key and webhook endpoint, and can send a test e-mail.

## Sending domain (mail.flanuer.com)

Checked 14 November 2026: `flanuer.com` uses Porkbun nameservers; neither it nor `mail.flanuer.com` has MX, SPF, DKIM or DMARC records. It is not set up for sending. Nothing was changed. The records to add are described in DEPLOYMENT.md §4.

## Known limitations

* No `worker` service is deployed. Jobs run only as part of a request, so there is no daily re-sync and lapsed subscriptions are not expired automatically. Add it before taking payments.
* Until e-mail is configured nobody can verify an address, so the platform-admin tools (discovery, recompute, status) are unavailable to everyone, including the owner.
* The database has never been exported or restored.
* Anonymous GitHub access allows about five full repository syncs an hour.
* Changing plan while subscribed goes through Stripe's customer portal.
* No teammate invitations or multi-factor authentication.
* Classification is keyword-based and labelled as inferred; scores are unvalidated heuristics.
* The repository has no licence file: all rights are reserved by default.

## Change log

* **Session 4 (v0.3.1)** — deployed to Railway; proxy setting corrected; platform-admin tools require a verified address; deployed-site journey added.
* **Session 3 (v0.3.0)** — security hardening, Redis rate limiting, CSP, billing synchronisation, configuration checker, acceptance suite, deployment checklist.
* **Session 2 (v0.2.0)** — e-mail verification, password reset, subscriptions, Stripe test-mode billing, landing and pricing pages.
* **Session 1 (v0.1.0)** — intelligence platform, accounts, API, frontend.
