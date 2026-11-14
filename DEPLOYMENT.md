# Deployment (Railway)

> **Nothing has been deployed and no Railway resource exists.** This is the checklist to follow when you decide to deploy. Railway bills by usage: review its pricing before creating services.

Railway's per-service `railway.json` ("Config as Code") is deprecated and is not read for new services, so this project ships none. Settings below are entered in the Railway dashboard. (Railway's replacement, `.railway/railway.ts`, can be added later with `railway config pull` once the project exists.)

## 1. Resources

| Resource | Type | Needed? |
|---|---|---|
| PostgreSQL | Railway database | Required |
| `api` | Service from this repo | Required |
| `web` | Service from this repo | Required |
| `worker` | Service from this repo | Recommended: scheduled syncs, discovery, AI enrichment, housekeeping. Without it set `JOBS_INLINE=true` on `api` |
| Redis | Railway database | Recommended: shared rate limiting. Without it set `RATE_LIMIT_BACKEND=memory` on `api` and run exactly one `api` instance |

Smallest footprint: PostgreSQL + `api` + `web` (three services).

## 2. Service settings

| Setting | `api` | `worker` | `web` |
|---|---|---|---|
| Source | this repository, branch `main` | same | same |
| Root Directory | `/backend` | `/backend` | `/frontend` |
| Builder | Dockerfile (detected) | Dockerfile | Dockerfile |
| Custom Start Command | *(leave empty)* | `python -m app.worker` | *(leave empty)* |
| Healthcheck Path | `/health/ready` | *(none)* | `/login` |
| Healthcheck Timeout | 120 | — | 120 |
| Restart Policy | On failure | On failure | On failure |
| Public domain | **No** | No | **Yes** (generate one) |
| Replicas | 1 (more only with Redis) | 1 | 1 |

The `api` image runs `alembic upgrade head` before starting the server: migrations are applied on every deploy, are idempotent, and a failed migration stops the release before it takes traffic. `/health/ready` returns 503 if the database, or a configured Redis, is unreachable, which keeps a broken release from going live.

The browser only ever talks to `web`; `web` proxies `/api/*` to `api` over Railway's private network. That is why `api` needs no public domain.

## 3. Variables

### `api` and `worker` (use one shared variable group linked to both)

| Variable | Value | Notes |
|---|---|---|
| `APP_ENV` | `production` | Turns on the safety checks below |
| `SECRET_KEY` | 48+ random characters | `python -c "import secrets; print(secrets.token_urlsafe(48))"` |
| `DATABASE_URL` | `${{Postgres.DATABASE_URL}}` | `postgres://` is converted automatically |
| `FRONTEND_URL` | `https://<web public domain>` | Used in e-mail links and Stripe return URLs |
| `CORS_ORIGINS` | same as `FRONTEND_URL` | |
| `PORT` | `8000` | Fixed port so `web` can reach `api` privately |
| `REDIS_URL` | `${{Redis.REDIS_URL}}` | Or `RATE_LIMIT_BACKEND=memory` instead |
| `TRUSTED_PROXY_HOPS` | `2` | Railway edge + the `web` proxy (measured on the live deployment). See "After the first deploy" |
| `PLATFORM_ADMIN_EMAILS` | your login e-mail | Who may run discovery and demo tools. Only takes effect once that address is verified, so it needs working e-mail |
| `JOBS_INLINE` | `true` only if there is no `worker` | |
| E-mail | `EMAIL_PROVIDER=resend`, `RESEND_API_KEY`, `EMAIL_FROM` | Section 4 |
| Payments | `BILLING_PROVIDER=stripe`, `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET` | Section 5 (test mode) |
| Optional | `GITHUB_TOKEN`, `GITHUB_OAUTH_CLIENT_ID`, `GITHUB_OAUTH_CLIENT_SECRET`, `LLM_PROVIDER`, `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` | |

Add variables to the services themselves (or a shared group **linked** to them), not to an unlinked group.

With `APP_ENV=production` the API **refuses to start** if: `SECRET_KEY` is the default or shorter than 32 characters; `DATABASE_URL` is SQLite; `FRONTEND_URL`/`CORS_ORIGINS` are not public `https://` URLs; secure cookies are disabled; neither `REDIS_URL` nor `RATE_LIMIT_BACKEND=memory` is set; demo seeding or development plan switching is on; or a live Stripe key is supplied. The deploy log states which rule failed.

### `web`

| Variable | Value | Notes |
|---|---|---|
| `BACKEND_URL` | `http://${{api.RAILWAY_PRIVATE_DOMAIN}}:8000` | Needed at **build** time as well as runtime (the Dockerfile declares it as a build argument) |

## 4. E-mail delivery (Resend)

Railway's Hobby plan blocks outbound SMTP; Signal Atlas sends through Resend's HTTPS API, which works on every plan.

1. Create a Resend account (free tier: 3,000 e-mails a month, 100 a day).
2. **Domains → Add Domain.** Use a subdomain you control, for example `mail.flanuer.com`. Resend then shows the DNS records to create. Add them at the domain's DNS host exactly as shown. For `mail.flanuer.com` (DNS hosted at Porkbun) expect records of this shape:

   | Type | Host (relative to `flanuer.com`) | Value |
   |---|---|---|
   | MX | `send.mail` | `feedback-smtp.<region>.amazonses.com`, priority 10 |
   | TXT | `send.mail` | `v=spf1 include:amazonses.com ~all` |
   | TXT | `resend._domainkey.mail` | DKIM public key, unique to your account (copy from Resend) |
   | TXT (recommended) | `_dmarc.mail` | `v=DMARC1; p=none;` |

   Newer Resend accounts may be given CNAME records instead of the MX/TXT pair. **Always use the records in your own Resend dashboard**; the table only shows what to expect. As of 14 November 2026 `flanuer.com` and `mail.flanuer.com` have no MX, SPF, DKIM or DMARC records, so nothing has been set up yet.
3. Wait until the domain shows **Verified** in Resend (usually minutes, up to 72 hours).
4. Create an API key and set `EMAIL_PROVIDER=resend`, `RESEND_API_KEY`, and `EMAIL_FROM="Signal Atlas <no-reply@mail.flanuer.com>"` on `api` and `worker`.
5. Test from the `api` service shell:

   ```bash
   python -m app.cli doctor --send-test-email you@your-inbox.example
   ```

   It reports whether Resend accepts the key, whether the sending domain is verified, and sends one test message. Confirm the message arrives (check spam).

Until this is done no e-mail is sent, the app says so, and accounts cannot be verified. `EMAIL_VERIFICATION_REQUIRED=false` switches the verification gate off if you need to run without e-mail for a period.

## 5. Card payments (Stripe, test mode only)

1. In the Stripe dashboard switch to **Test mode**; copy the secret key (`sk_test_…`). A live key makes the API refuse to start.
2. **Developers → Webhooks → Add endpoint**
   * URL: `https://<web public domain>/api/v1/billing/webhooks/stripe`
   * Events: `checkout.session.completed`, `customer.subscription.created`, `customer.subscription.updated`, `customer.subscription.deleted`, `invoice.paid`, `invoice.payment_failed`, `invoice_payment.paid`, `charge.refunded`
   * Copy the signing secret (`whsec_…`).
3. Set on `api` and `worker`: `BILLING_PROVIDER=stripe`, `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET`.
4. **Settings → Billing → Customer portal:** activate it (used by "Manage card and invoices").
5. No products or prices need creating: checkout sends the amount from the plan catalogue (`backend/app/plans.py`, overridable with `PLAN_OVERRIDES_JSON`).
6. Check the configuration, then make one test purchase:

   ```bash
   python -m app.cli doctor        # verifies the key, test mode, and the webhook endpoint and its events
   ```

   In the app: **Settings → Plan & billing → Subscribe to Pro**, pay with card `4242 4242 4242 4242`, any future expiry and CVC. On return the plan should show **Pro · Active**, the payment should appear under Payment history, and **API & Developers → Create API key** should now work. Then **Cancel subscription** and confirm it shows "Cancels at period end". Card `4000 0000 0000 0341` attaches successfully but fails on renewal, for testing the failed-payment state.

The plan is activated by Stripe's confirmation (webhook, or a direct check with Stripe when the customer returns), never by the browser redirect alone.

## 6. GitHub integrations (optional)

**Server token:** a fine-grained token with *Public repositories (read-only)* and no other permissions, as `GITHUB_TOKEN`. Raises the limit from 60 to 5,000 requests an hour and enables issue and pull-request totals.

**OAuth app:** Homepage `https://<web domain>`, callback `https://<web domain>/api/v1/auth/github/callback`; set `GITHUB_OAUTH_CLIENT_ID` and `GITHUB_OAUTH_CLIENT_SECRET`. Requests `read:user user:email` only.

## 7. After the first deploy

1. Open `https://<web domain>/` — the landing page should load; `…/api/docs` shows the API reference.
2. Run `python -m app.cli doctor` on the `api` service (Railway CLI: `railway run -s api python -m app.cli doctor`, or set it temporarily as the pre-deploy command and read the deploy log). Every line should be `PASS`, or a `WARN` you have chosen to accept.
3. Create your account, sign in, and open **Settings → Data & jobs**. Under "Rate limiting and proxy check", *Your address as seen by the API* must be your own public IP address. If it shows a private or shared address, change `TRUSTED_PROXY_HOPS` (0 = use the connection address, 1 = one trusted proxy, 2 = two) and redeploy. On Railway with `web` proxying to `api` the correct value is `2`: with `1` every visitor appeared as the same Railway address and shared one rate-limit allowance. Per-IP rate limits depend on this being right.
4. Load data: **Settings → Data & jobs → Run discovery**, or **Repository Intelligence → Search GitHub**.
5. Run the deployed-site journey from your own machine: `cd e2e && BASE_URL=https://<web domain> node production.mjs`.

**Without a `worker` service** (`JOBS_INLINE=true`) jobs run only as part of a request. Discovery queues its searches a few seconds apart, so press **Recompute** a minute or two later to finish them, and nothing runs on a timer: no daily re-sync, and lapsed subscriptions are not expired automatically. Add the `worker` before taking payments.

## 8. Backups and rollback

Railway's own backups depend on your plan. A free manual export from your own machine:

```
pg_dump "<external DATABASE_URL>" -Fc -f signal_atlas.dump
```

The external URL is `DATABASE_PUBLIC_URL` on the Postgres service (Railway → Postgres → Variables). With the Railway CLI, `railway connect Postgres` opens a `psql` session the same way. Restore into an empty database with `pg_restore --no-owner -d "<target URL>" signal_atlas.dump`, and try that once before you need it. No export has been taken yet.

Take one before any deploy that includes a new migration. To roll back code, redeploy a previous deployment in Railway. Migrations `0001`–`0002` are additive; `alembic downgrade -1` reverses the latest one if older code must run.

## 9. Go-live checklist

- [ ] PostgreSQL, `api`, `web` created (plus `worker` and Redis if chosen); only `web` has a public domain
- [ ] `APP_ENV=production`; the `api` deploy log shows no "Unsafe production configuration" error
- [ ] `python -m app.cli doctor` passes on the `api` service
- [ ] "Your address as seen by the API" shows your real IP
- [ ] Resend domain verified; test e-mail received; a new sign-up receives its confirmation e-mail
- [ ] Stripe test checkout completed end to end; cancellation tested
- [ ] `GITHUB_TOKEN` set if you expect more than light use
- [ ] CI workflow installed and green (see README)
- [ ] Database export taken
- [ ] Privacy notice and terms published before inviting users (see SECURITY.md)
- [ ] Live payments stay off until the Stripe test run and tax handling are complete
