# Progress

_Last updated: 14 November 2026 — session 3 (integration and deployment readiness, v0.3.0)._

## Where things stand

The application is complete and prepared for deployment. **It is not deployed, CI is not active on GitHub, and neither Resend nor Stripe has been exercised for real.** Those three items need access only the owner can give (see [TASKS.md](TASKS.md)).

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
| Intelligence features (repositories, developers, trends, opportunities, competitors, scoring) | ✅ | — | — | ❌ not deployed |
| Accounts, sessions, soft verification gate, password reset | ✅ | — | — | ❌ |
| Sign-up without account enumeration | ✅ | — | — | ❌ |
| Rate limiting on Redis, failing closed | ✅ real Redis 7 | ✅ | — | ❌ |
| Content-Security-Policy | ✅ real browser, zero violations | — | — | ❌ |
| E-mail content, links, expiry, single use, limits | ✅ | ✅ Resend API mocked | **Blocked** — no Resend key or verified domain | ❌ |
| **Real e-mail delivery** | — | — | **Blocked — never tested** | ❌ |
| Stripe checkout, webhooks, renewal, failure, cancellation, refunds, history, entitlements | ✅ browser journey against the local stub | ✅ | **Blocked** — no Stripe test key | ❌ |
| **Real Stripe test-mode checkout** | — | — | **Blocked — never tested** | ❌ |
| GitHub sign-in (OAuth) | — | ✅ | **Blocked** — no OAuth app | ❌ |
| AI report enrichment | — | ✅ | **Blocked** — no LLM key | ❌ |
| CI on GitHub | ✅ every step run by hand | — | **Blocked** — Workflows permission | — |
| Railway deployment | ✅ start commands, migrations, health checks and IPv4+IPv6 listening run by hand. **Docker images not built** (no Docker in the build environment) | — | **Blocked** — awaiting approval | ❌ |

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

No critical or high-severity issue is open.

## Deployment preparation

* Deprecated `railway.json` files removed (Railway no longer reads them for new services); exact dashboard settings are in [DEPLOYMENT.md](DEPLOYMENT.md).
* The API container now listens on IPv4 and IPv6 (Railway's private network can be IPv6-only) and has a container health check.
* `/health/ready` covers the database and Redis.
* `python -m app.cli doctor` checks configuration, database migrations, Redis, the Resend domain, the Stripe key and webhook endpoint, and can send a test e-mail.

## Sending domain (mail.flanuer.com)

Checked 14 November 2026: `flanuer.com` uses Porkbun nameservers; neither it nor `mail.flanuer.com` has MX, SPF, DKIM or DMARC records. It is not set up for sending. Nothing was changed. The records to add are described in DEPLOYMENT.md §4.

## Known limitations

* The two Dockerfiles have never been built: the first Railway build will be their first. The commands inside them were each run by hand.
* Anonymous GitHub access allows about five full repository syncs an hour.
* Changing plan while subscribed goes through Stripe's customer portal.
* No teammate invitations or multi-factor authentication.
* Classification is keyword-based and labelled as inferred; scores are unvalidated heuristics.
* The repository has no licence file: all rights are reserved by default.

## Change log

* **Session 3 (v0.3.0)** — security hardening, Redis rate limiting, CSP, billing synchronisation, configuration checker, acceptance suite, deployment checklist.
* **Session 2 (v0.2.0)** — e-mail verification, password reset, subscriptions, Stripe test-mode billing, landing and pricing pages.
* **Session 1 (v0.1.0)** — intelligence platform, accounts, API, frontend.
