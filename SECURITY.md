# Security

## Principles

Read-only access to public data · least privilege · secrets never reach the browser or the logs · every tenant-owned row is filtered by organisation.

## Controls implemented

| Area | Control |
|---|---|
| Passwords | Argon2id (`argon2-cffi`), policy: ≥10 characters, upper-case letter and digit; automatic rehash; timing-equalised login for unknown emails; identical error for wrong email and wrong password |
| Brute force | Login rate limit (20/min per IP), account lock for 15 minutes after 5 failures, registration limit (10/hour per IP), failed logins audited |
| Sessions | Opaque 256-bit token in an `HttpOnly`, `SameSite=Lax`, `Secure` (production) cookie; only a SHA-256 hash is stored; server-side revocation on logout; changing password revokes other sessions; 14-day expiry |
| Email verification | Soft gate enforced by the API: unverified accounts can browse, but report generation, API key creation and live GitHub requests return 403 until the address is confirmed. Tokens are 256-bit, single-use, stored as SHA-256 hashes, expire after 24 hours, and are removed from the browser address bar after use |
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
| Rate limiting | Per session, per API key, per IP for auth endpoints (in-memory; Redis-backed when `REDIS_URL` is set) |
| Transport & headers | HSTS (production), `X-Content-Type-Options`, `X-Frame-Options: DENY`, `Referrer-Policy`, `Cache-Control: no-store` on API responses; restricted CORS origins |
| Secrets | Environment variables only; `.env` git-ignored; production refuses to start with a default or short `SECRET_KEY`; log processor redacts GitHub tokens, LLM keys, API keys and sensitive field names |
| Audit logging | Registration, login, failed login, password change, GitHub connect/disconnect, API key create/revoke, plan and weight changes, report generation |
| AI safety | LLM receives only the fact sheet; output is schema-validated; statements containing figures not in the fact sheet, or monetary / market-size claims, are removed; AI content is labelled |
| Data retention | `retention_cleanup` job prunes snapshots (`SNAPSHOT_RETENTION_DAYS`), audit logs (`AUDIT_RETENTION_DAYS`), finished jobs and read notifications |
| Dependencies | `pip-audit` and `npm audit` run in CI. Both report no known vulnerabilities at the time of writing |

## Privacy and UK GDPR notes

* Developer profiles contain only data the person has published on GitHub (login, name, avatar, company, location, bio, counts). Email addresses are not collected, even when the API returns one.
* Inferred attributes (languages, specialisation, "emerging") are labelled as inferred and derived only from public contribution counts.
* Lawful basis is likely *legitimate interests*; before commercial launch complete a Legitimate Interests Assessment, publish a privacy notice, and provide a removal route for developers who object. These are business tasks tracked in [TASKS.md](TASKS.md), not yet done.
* Respect GitHub's Terms of Service and Acceptable Use Policies: API access only, rate limits honoured, no scraping.

## Known limitations (MVP)

* Email verification and password reset are implemented but deliver nothing until an email provider is configured. Registration still reveals whether an email is already registered.
* The Stripe integration is verified with mocked provider responses only; it has not yet been exercised against Stripe's test environment.
* No multi-factor authentication.
* Rate limiting is per process unless Redis is configured.
* Session cookies rely on the frontend proxy; do not expose the API service publicly without it unless CORS and cookie settings are reviewed.
* No Content-Security-Policy header yet (Next.js inline scripts require a nonce-based policy).
* Licence assessments are automated readings, not legal advice.

## Reporting a vulnerability

Email the maintainers privately; do not open a public issue. Rotate any credential that may have been exposed.
