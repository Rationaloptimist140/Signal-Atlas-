# End-to-end acceptance test

`acceptance.mjs` drives a real browser through the whole customer journey: landing → sign-up → verification → sign-in → repositories → trends → opportunity report → Free-plan restriction → checkout → activation → premium entitlement → failed renewal → cancellation → sign-out → password recovery. It also fails on any Content-Security-Policy violation or console error.

What it does **not** prove: e-mail links are read from the API's development log, and payments go through `stripe_stub.py`, a local stand-in for Stripe. Run the same journey against Resend and Stripe test mode before relying on either.

## Run

```bash
# 1. API (development mode prints e-mail links to its output; send that to a file)
cd backend
BILLING_PROVIDER=stripe STRIPE_SECRET_KEY=sk_test_stub STRIPE_WEBHOOK_SECRET=whsec_stub STRIPE_API_URL=http://localhost:4242 \
JOBS_INLINE=true COOKIE_SECURE=false uvicorn app.main:app --port 8000 > /tmp/sa_api.log 2>&1 &
python -m app.cli demo-load          # the journey needs some repositories and signals

# 2. Web app (production build, so the real CSP is tested)
cd ../frontend && npm run build && npm start &

# 3. Stripe stub and the journey
cd ../e2e && npm install && npx playwright install chromium
STRIPE_WEBHOOK_SECRET=whsec_stub python3 stripe_stub.py &
API_LOG=/tmp/sa_api.log npm run acceptance
```

Set `STUB_URL=off` to skip the billing steps. Add `REDIS_URL=redis://localhost:6379/0` to the API to exercise the shared rate limiter.

## Deployed site

`production.mjs` runs a shorter journey against a real deployment with a fresh account:

```bash
BASE_URL=https://<web domain> node production.mjs
```

It checks HTTPS and security headers, pricing, sign-up, sign-in, the soft verification gate, live repository data, CSRF, tenant isolation, the sign-in rate limit, mobile layout and sign-out. Steps that need a delivered e-mail or a payment are printed as `BLOCKED`, never as passed. Set `EXPECT_EMAIL=1` and `EXPECT_BILLING=1` once Resend and Stripe are configured so that a missing provider fails the run. Each run leaves two unverified `@example.com` accounts behind.
