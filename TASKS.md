# Tasks

## Needed from the owner (nothing here has been done)

| # | What | Why | Steps |
|---|---|---|---|
| 1 | Install the CI workflow | CI cannot run until `.github/workflows/ci.yml` exists | `ci/README.md` (one minute in the browser) |
| 2 | Resend account, API key and a verified sending domain | No e-mail can be sent without them | DEPLOYMENT.md §4 |
| 3 | DNS records for the sending domain | Resend only sends from a verified domain | Added at the DNS host by whoever controls the domain |
| 4 | Stripe test-mode secret key and webhook signing secret | Checkout has only been run against a local stub | DEPLOYMENT.md §5 |
| 5 | Approval to create Railway services | Deployment is billable | DEPLOYMENT.md §1–3 |
| 6 | GitHub read-only token (optional but recommended) | 60 → 5,000 requests an hour | DEPLOYMENT.md §6 |
| 7 | GitHub OAuth app, LLM key (optional) | "Sign in with GitHub", AI-enriched reports | DEPLOYMENT.md §6 |

Set secrets as service variables on the host. Do not paste them into chat or commit them.

## Remaining steps before production

1. Install the CI workflow and confirm the first run is green.
2. Create the Railway resources and set the variables (DEPLOYMENT.md §1–3).
3. Deploy; run `python -m app.cli doctor` on the `api` service; confirm the proxy check shows your own IP (§7).
4. Verify the Resend domain; send the test e-mail; register a fresh account and confirm the e-mail arrives.
5. Configure Stripe test mode; complete one test checkout and one cancellation end to end.
6. Take a database export.
7. Publish a privacy notice and terms; decide on a licence or proprietary notice.
8. Keep live payments off until the Stripe test run, pricing validation and tax handling are done.

## Next engineering tasks

- [ ] `.railway/railway.ts` (Railway's infrastructure-as-code) once the project exists
- [ ] In-app plan change for existing subscribers; billing e-mails (receipt, payment failed)
- [ ] Teammate invitations and seat limits; multi-factor authentication
- [ ] Run the acceptance suite in CI
- [ ] Dependencies from GitHub's SBOM endpoint; package-registry adoption data
- [ ] Backtest the scoring model against known outcomes
- [ ] Error tracking and metrics
