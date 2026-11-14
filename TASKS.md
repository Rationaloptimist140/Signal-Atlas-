# Tasks

## Needed from the owner

| # | What | Why | Steps |
|---|---|---|---|
| 1 | Install the CI workflow | CI has never run; neither credential available to the build agent may write workflow files | `ci/README.md` (one minute in the browser) |
| 2 | Resend account and API key; add `mail.flanuer.com` in Resend | No e-mail can be sent, so no account can be verified | DEPLOYMENT.md §4 |
| 3 | DNS records for `mail.flanuer.com` at Porkbun | Resend only sends from a verified domain | Copy the four records Resend shows |
| 4 | Stripe test-mode secret key, webhook endpoint and signing secret | Checkout has only been run against a local stub | DEPLOYMENT.md §5. Endpoint: `https://web-production-e6e86402.up.railway.app/api/v1/billing/webhooks/stripe` |
| 5 | After e-mail works: register, verify, then set `PLATFORM_ADMIN_EMAILS` to your address | Unlocks discovery, recompute and the status page | Railway → `api` → Variables |
| 6 | GitHub read-only token (recommended) | 60 → 5,000 requests an hour | DEPLOYMENT.md §6 |
| 7 | Decide on the `worker` service | Timed jobs do not run without it | DEPLOYMENT.md §1–2; small extra usage cost |
| 8 | GitHub OAuth app, LLM key (optional) | "Sign in with GitHub", AI-enriched reports | DEPLOYMENT.md §6 |
| 9 | Delete the unused `ci/install-workflow` branch | Created by mistake in session 4; identical to `main` | GitHub → Branches |

Set secrets as service variables in Railway (`api` service). Do not paste them into chat or commit them.

## Remaining steps before launch

1. Install the CI workflow and confirm the first run is green.
2. Verify the Resend domain; send the test e-mail (`doctor --send-test-email`); register a fresh account and confirm the e-mail arrives.
3. Configure Stripe test mode; complete one test checkout and one cancellation end to end.
4. Re-run `e2e/production.mjs` with `EXPECT_EMAIL=1 EXPECT_BILLING=1`.
5. Take a database export and restore it once somewhere disposable (DEPLOYMENT.md §8).
6. Publish a privacy notice and terms; decide on a licence or proprietary notice.
7. Keep live payments off until the Stripe test run, pricing validation and tax handling are done.

## Next engineering tasks

- [ ] `.railway/railway.ts` (Railway's infrastructure-as-code) for the existing project
- [ ] Operator command to remove test accounts
- [ ] In-app plan change for existing subscribers; billing e-mails (receipt, payment failed)
- [ ] Teammate invitations and seat limits; multi-factor authentication
- [ ] Run the acceptance suite in CI
- [ ] Dependencies from GitHub's SBOM endpoint; package-registry adoption data
- [ ] Backtest the scoring model against known outcomes
- [ ] Error tracking and metrics
