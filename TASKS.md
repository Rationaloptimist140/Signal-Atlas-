# Tasks

## External configuration still required (your accounts; none of this was done)

- [ ] **GitHub Workflows permission** — grant the GitHub App used for automated pushes the *Workflows* permission, or paste `.github/workflows/ci.yml` (full text in the pull request description) through GitHub's web editor. Without it CI does not run.
- [ ] **Resend** — create an account (free tier), verify a sending domain by adding its DNS records, then set `EMAIL_PROVIDER=resend`, `RESEND_API_KEY`, `EMAIL_FROM`. `mail.flanuer.com` has no mail DNS records today (see PROGRESS.md).
- [ ] **Stripe test mode** — set `BILLING_PROVIDER=stripe`, `STRIPE_SECRET_KEY` (`sk_test_...`), `STRIPE_WEBHOOK_SECRET`; add the webhook endpoint and enable the customer portal (steps in DEPLOYMENT.md); then run one test checkout end to end.
- [ ] **GitHub token** — read-only public-repository token as `GITHUB_TOKEN`.
- [ ] **GitHub OAuth app** — `GITHUB_OAUTH_CLIENT_ID` / `GITHUB_OAUTH_CLIENT_SECRET`.
- [ ] **LLM provider** — optional; `LLM_PROVIDER` plus a key.
- [ ] **Railway deployment** — awaiting separate confirmation; creates billable services.
- [ ] **Legal** — privacy notice, terms, Legitimate Interests Assessment for developer profiles; decide on a licence or proprietary notice.

## Before live payments

- [ ] Run the Stripe integration against Stripe's test environment and fix anything the mocks did not show
- [ ] Validate prices and limits with prospective customers
- [ ] Decide VAT / tax handling (Stripe Tax is not configured)
- [ ] Only then set `ALLOW_LIVE_PAYMENTS=true` with a live key

## Next engineering tasks

- [ ] In-app plan upgrade/downgrade for existing subscribers (currently via the Stripe portal)
- [ ] Billing emails (receipt, payment failed, cancellation confirmation)
- [ ] Teammate invitations and seat limits
- [ ] Committed Playwright end-to-end suite
- [ ] Nonce-based Content-Security-Policy; multi-factor authentication
- [ ] Dependencies from GitHub's SBOM endpoint; package-registry adoption data
- [ ] Backtest the scoring model against known outcomes
- [ ] Error tracking and metrics
