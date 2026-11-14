# Security

## Principles

Read-only access to public data · least privilege · secrets never reach the browser or the logs · every tenant-owned row is filtered by organisation.

## Controls implemented

| Area | Control |
|---|---|
| Passwords | Argon2id (`argon2-cffi`), policy: ≥10 characters, upper-case letter and digit; automatic rehash; timing-equalised login for unknown emails; identical error for wrong email and wrong password |
| Brute force | Login rate limit (20/min per IP), account lock for 15 minutes after 5 failures, registration limit (10/hour per IP), failed logins audited |
| Account enumeration | Registration returns the same `202` response, with no session, whether or not the address exists; an existing owner is told by e-mail instead (at most three notices an hour). Login and password reset were already generic. With `LOGIN_REQUIRES_VERIFIED_EMAIL=true` an unconfirmed account cannot be distinguished from a wrong password either |
| Sessions | Opaque 256-bit token in an `HttpOnly`, `SameSite=Lax`, `Secure` (production) cookie; only a SHA-256 hash is stored; server-side revocation on logout; changing password revokes other sessions; 14-day expiry |
| Email verification | Soft gate enforced by the API: unverified accounts can browse, but report generation, API key creation and live GitHub requests return 403 until the address is confirmed. Tokens are 256-bit, single-use, stored as SHA-256 hashes, expire after 24 hours, travel in the URL fragment (never sent to any server, so absent from access logs) and are removed from the address bar after use |
| Password reset | 30-minute single-use hashed tokens; identical response whether or not the account exists; rate limited per IP and per address; a successful reset revokes every session and clears lockout; all steps audited. Tokens are never logged in production |
| Payments | Stripe hosted checkout (card data never touches this application). Webhooks are HMAC-SHA256 signature-verified with a 5-minute tolerance and processed idempotently through a unique event ledger; live-mode events and live API keys are refused in this release. Entitlements change only on provider-confirmed events, never on the browser redirect |
| CSRF | Per-session CSRF token required in `X-CSRF-Token` for every state-changing cookie-authenticated request; compared in constant time. OAuth uses a signed, `HttpOnly` state cookie |
| GitHub OAuth | Scopes `read:user user:email` only (identity; never `repo`). Token encrypted at rest (Fernet), used server-side only, never serialised to clients or logs; grant revoked on disconnect. GitHub accounts are never auto-linked to an existing password account |
| GitHub data | Public endpoints only, GET requests (plus the read-only GraphQL endpoint). No private repositories, no email addresses stored. Bots excluded from developer profiles |
| API keys | `sa_live_…` keys shown once, stored as SHA-256 hashes; read-only by default (`write` scope opt-in); cannot reach account-management endpoints; per-key rate limit and monthly metering; revocable |
| Authorisation | Roles owner / admin / analyst / viewer enforced by dependencies; instance-wide tools restricted to `PLATFORM_ADMIN_EMAILS` in production |
| Tenant isolation | All tenant tables carry a non-null `organisation_id`; every query filters by the caller's organisation; cross-tenant access returns 404. Covered by dedicated tests |
| Input validation | Pydantic models on every request; bounded pagination; repository names and URLs validated by pattern; LIKE wildcards escaped |
| SQL injection | SQLAlchemy bound parameters throughout; no string-built SQL |
| Rate limiting | Redis-backed fixed windows shared by all API instances (in-memory for development, or by explicit production opt-in). Applied to registration, login, password reset, e-mail verification, public endpoints (per IP), API keys and sessions, and sensitive account actions (password change, key creation, checkout, cancellation). **Fails safely:** if Redis is unreachable, sensitive actions return 503 instead of running unlimited; ordinary reads fall back to a per-process limiter; the readiness probe reports unhealthy |
| Client address | Only the trusted right-hand end of `X-Forwarded-For` is used (`TRUSTED_PROXY_HOPS`), so a forged header cannot be used to dodge per-IP limits |
| Content-Security-Policy | Pages: `default-src 'self'`; scripts only from this origin and only with a per-request nonce (`'strict-dynamic'`, no `unsafe-eval`, no inline script); images from this origin, `data:` and GitHub's avatar host; `connect-src 'self'`; `object-src 'none'`; `frame-ancestors 'none'`; `form-action 'self'`; `base-uri 'self'`. API responses: `default-src 'none'`. Verified in a browser run across the whole journey with zero violations |
| Transport & headers | HSTS, `X-Content-Type-Options`, `X-Frame-Options: DENY`, `Referrer-Policy`, `Permissions-Policy`, `Cache-Control: no-store` on API responses; restricted CORS origins |
| Secrets | Environment variables only; `.env` git-ignored; production refuses to start on unsafe settings (default or short `SECRET_KEY`, SQLite, non-https or localhost URLs, insecure cookies, no rate-limit decision, demo seeding, live Stripe key); log processor redacts GitHub tokens, LLM keys, API keys and sensitive field names |
| Audit logging | Registration, login, failed login, password change, GitHub connect/disconnect, API key create/revoke, plan and weight changes, report generation |
| AI safety | LLM receives only the fact sheet; output is schema-validated; statements containing figures not in the fact sheet, or monetary / market-size claims, are removed; AI content is labelled |
| Data retention | `retention_cleanup` job prunes snapshots (`SNAPSHOT_RETENTION_DAYS`), audit logs (`AUDIT_RETENTION_DAYS`), finished jobs and read notifications |
| Dependencies | `pip-audit` and `npm audit` are part of the CI workflow and were run locally: no known vulnerabilities at the time of writing |

## Privacy and UK GDPR notes

* Developer profiles contain only data the person has published on GitHub (login, name, avatar, company, location, bio, counts). Email addresses are not collected, even when the API returns one.
* Inferred attributes (languages, specialisation, "emerging") are labelled as inferred and derived only from public contribution counts.
* Lawful basis is likely *legitimate interests*; before commercial launch complete a Legitimate Interests Assessment, publish a privacy notice, and provide a removal route for developers who object. These are business tasks tracked in [TASKS.md](TASKS.md), not yet done.
* Respect GitHub's Terms of Service and Acceptable Use Policies: API access only, rate limits honoured, no scraping.

## Documented exceptions and residual risks

* **`style-src 'unsafe-inline'`** — React, Recharts and React Flow position elements with inline `style` attributes, which a nonce cannot authorise. Inline styles cannot execute script; the residual risk is CSS-only injection.
* **Interactive API docs** (`/api/docs`, `/api/redoc`) load Swagger UI / ReDoc from jsDelivr and need inline script, so those two paths have their own, looser policy. Set `API_DOCS_ENABLED=false` to remove them.
* **Sign-up probing under the soft gate** — because unverified accounts may sign in (the approved policy), someone who registers an address and then signs in with the password they chose can tell the account was new. It costs them a created account and a rate-limited request. `LOGIN_REQUIRES_VERIFIED_EMAIL=true` closes this completely, at the cost of requiring working e-mail before anyone can sign in.
* **Stripe webhooks are not rate limited** — they are authenticated by signature and de-duplicated instead, so that provider retries are never refused.
* **Proxy trust must match the deployment** — per-IP limits are only as good as `TRUSTED_PROXY_HOPS`; verify it after deploying (DEPLOYMENT.md §7).

## Known limitations

* E-mail delivery and card payments are verified with mocked providers and a local stub only; neither has been run against Resend or Stripe.
* No multi-factor authentication; no teammate invitations.
* Session cookies rely on the frontend proxy; do not give the API service a public domain without reviewing CORS and cookie settings.
* Licence assessments are automated readings, not legal advice.

## Reporting a vulnerability

Email the maintainers privately; do not open a public issue. Rotate any credential that may have been exposed.
