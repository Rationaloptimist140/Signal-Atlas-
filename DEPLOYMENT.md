# Deployment (Railway)

> Nothing has been deployed and no Railway resource has been created. These are the steps to follow when you are ready. Creating services on Railway may incur cost on your plan — review before proceeding.

## Services

| Service | Root directory | Config | Start |
|---|---|---|---|
| `api` | `backend` | `backend/railway.json` | `alembic upgrade head && uvicorn …` (in the Dockerfile) |
| `worker` | `backend` | `backend/railway.worker.json` | `python -m app.worker` |
| `web` | `frontend` | `frontend/railway.json` | `next start` |
| PostgreSQL | Railway plugin | — | — |
| Redis | *not required* | — | Add only when running more than one `api` instance |

Minimum footprint: PostgreSQL + `api` + `web`. Without `worker`, set `JOBS_INLINE=true` on `api`: syncs and reports run inside the request and scheduled monitoring/discovery does not run. Add `worker` when you want automatic updates.

## Steps

1. **Create a project** on Railway and add the **PostgreSQL** plugin.
2. **Create `api`** from this GitHub repository. Settings → Root Directory `backend`; Config-as-code path `backend/railway.json`.
3. **Set variables on `api`:**

   | Variable | Value |
   |---|---|
   | `APP_ENV` | `production` |
   | `SECRET_KEY` | 48+ random characters (`python -c "import secrets; print(secrets.token_urlsafe(48))"`) |
   | `DATABASE_URL` | `${{Postgres.DATABASE_URL}}` |
   | `FRONTEND_URL` | Public URL of the `web` service, e.g. `https://signal-atlas.up.railway.app` |
   | `CORS_ORIGINS` | Same as `FRONTEND_URL` |
   | `PLATFORM_ADMIN_EMAILS` | Your login email |
   | `JOBS_INLINE` | `true` only if you run no worker |
   | Optional | `GITHUB_TOKEN`, `GITHUB_OAUTH_CLIENT_ID`, `GITHUB_OAUTH_CLIENT_SECRET`, `LLM_PROVIDER`, `ANTHROPIC_API_KEY` / `OPENAI_API_KEY`, `LLM_MODEL` |

   Add them as **service variables** on `api` (and the same set on `worker`), not as a shared group that is not linked to the service.
4. **Create `worker`** from the same repository: Root Directory `backend`, Config path `backend/railway.worker.json`, same variables as `api` (a Railway shared variable group linked to both services works well).
5. **Create `web`**: Root Directory `frontend`, Config path `frontend/railway.json`. Variable `BACKEND_URL` = the **private** URL of `api`, e.g. `http://${{api.RAILWAY_PRIVATE_DOMAIN}}:${{api.PORT}}`. It must be available at **build** time (Railway passes service variables to Docker builds; the Dockerfile declares `ARG BACKEND_URL`).
6. **Generate a public domain** for `web` only. The `api` service does not need one; the browser reaches it through the `web` proxy.
7. **Deploy.** The API runs `alembic upgrade head` on start.
8. **Verify:** open `https://<web-domain>/login`, create an account, then check `Settings → Integrations` and `Settings → Data & jobs`. `GET https://<web-domain>/api/docs` shows the API reference.

## Email delivery (verification and password reset)

Railway's Hobby plan blocks outbound SMTP, so Signal Atlas sends through an HTTPS API (Resend).

1. Create a Resend account (the free tier is enough to start) and add a **sending domain** you control. Resend shows the DNS records to add at your registrar; sending to other people's addresses only works after the domain shows as verified.
2. Set on `api` and `worker`: `EMAIL_PROVIDER=resend`, `RESEND_API_KEY=...`, `EMAIL_FROM="Signal Atlas <no-reply@your-verified-domain>"`.
3. Without these, no email is sent: the app says so, and accounts cannot be verified. `EMAIL_VERIFICATION_REQUIRED=false` turns the gate off if you need to run without email for a while.

## Card payments (Stripe, test mode)

1. In the Stripe dashboard switch to **Test mode** and copy the secret key (`sk_test_...`). A live key makes the API refuse to start.
2. Developers → Webhooks → add endpoint `https://<web-domain>/api/v1/billing/webhooks/stripe` with events: `checkout.session.completed`, `customer.subscription.created`, `customer.subscription.updated`, `customer.subscription.deleted`, `invoice.paid`, `invoice.payment_failed`, `charge.refunded`. Copy the signing secret (`whsec_...`).
3. Set on `api`: `BILLING_PROVIDER=stripe`, `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET`.
4. No products or prices need creating in Stripe: checkout sends the amount from the plan catalogue. Enable the Stripe customer portal (Settings → Billing → Customer portal) for "Manage card and invoices".
5. Test with card `4242 4242 4242 4242`. The plan changes when the webhook arrives, not on the browser redirect.

## GitHub integrations (optional)

**Server token (recommended first):** GitHub → Settings → Developer settings → Fine-grained tokens → *Public repositories (read-only)*, no extra permissions. Set as `GITHUB_TOKEN`. Raises the limit from 60 to 5,000 requests/hour and enables issue and pull-request totals.

**OAuth app:** GitHub → Settings → Developer settings → OAuth Apps → New.
* Homepage URL: `https://<web-domain>`
* Authorization callback URL: `https://<web-domain>/api/v1/auth/github/callback`
* Set `GITHUB_OAUTH_CLIENT_ID` and `GITHUB_OAUTH_CLIENT_SECRET` on `api`.
The app requests `read:user user:email` only.

## First data

* **Live:** `Settings → Data & jobs → Run discovery` (needs the worker), or `Repository Intelligence → Search GitHub`.
* **Demo:** `Settings → Data & jobs → Load demo fixtures`, or set `SEED_DEMO_DATA=true` before the first start.

## Database backups

Railway backups depend on your plan. For a free manual export from your own machine:

```
pg_dump "<External DATABASE_URL>" -Fc -f signal_atlas.dump
```

## Rollback

Railway → service → Deployments → **Redeploy** a previous deployment. Migrations are additive in v0.1; to revert the schema run `alembic downgrade -1` against the database before redeploying older code.

## Production checklist

- [ ] `APP_ENV=production` and a unique `SECRET_KEY` (the API refuses to start otherwise)
- [ ] `FRONTEND_URL` / `CORS_ORIGINS` match the public web domain (HTTPS)
- [ ] `PLATFORM_ADMIN_EMAILS` set
- [ ] `ALLOW_SELF_SERVE_PLAN_CHANGE` unset (the API refuses `true` in production)
- [ ] Email provider configured with a verified sending domain
- [ ] Stripe test-mode key and webhook secret set; a test checkout completed end to end
- [ ] Only `web` has a public domain
- [ ] `GITHUB_TOKEN` set if you expect more than light usage
- [ ] Privacy notice and terms published before inviting users (see SECURITY.md)
