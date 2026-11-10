# Tasks

## Needs your input (external accounts, cost or scope)

- [ ] **Deploy to Railway** — follow DEPLOYMENT.md. Creates billable services; confirm before proceeding.
- [ ] **GitHub token** — create a read-only public-repository token and set `GITHUB_TOKEN`.
- [ ] **GitHub OAuth app** — create it and set `GITHUB_OAUTH_CLIENT_ID` / `GITHUB_OAUTH_CLIENT_SECRET` (callback URL in DEPLOYMENT.md).
- [ ] **LLM provider** — choose Anthropic or an OpenAI-compatible endpoint and set the key (usage is billed by the provider).
- [ ] **Email provider** — needed for verification, password reset and invitations.
- [ ] **Legal** — privacy notice, terms, Legitimate Interests Assessment for developer profiles.
- [ ] **Pricing validation** — confirm plan prices and limits with prospective customers before enabling payments.

## Next engineering tasks

### Launch readiness
- [ ] Email verification, password reset, teammate invitations
- [ ] Committed Playwright end-to-end suite and ESLint configuration
- [ ] Nonce-based Content-Security-Policy
- [ ] Organisation switcher for users in several workspaces
- [ ] Multi-factor authentication

### Data depth
- [ ] Dependencies from GitHub's SBOM endpoint (nested manifests, lockfiles)
- [ ] Package-registry adoption data (npm, PyPI, crates.io downloads)
- [ ] Backfill star history from stargazer timestamps for watched repositories
- [ ] Dependents ("used by") counts
- [ ] GitHub App installation for higher per-installation quotas
- [ ] Monitor a competitor's whole GitHub organisation, not only attached repositories

### Intelligence quality
- [ ] Backtest the scoring model against known commercial outcomes; publish calibration
- [ ] LLM-assisted classification with human-reviewable overrides
- [ ] Release-note summarisation and feature extraction for competitor reports
- [ ] External demand signals (search interest, job postings, funding) from permitted sources
- [ ] Typed response models for composite endpoints (dashboard, graph) in OpenAPI

### Commercialisation
- [ ] Stripe provider behind `BILLING_PROVIDER` (checkout, webhook, entitlement sync)
- [ ] Usage dashboards and limit warning notifications
- [ ] Scheduled email digests of signals and competitor changes
- [ ] Report export to PDF and Markdown

### Operations
- [ ] Redis-backed cache for dashboard aggregates
- [ ] Error tracking and metrics (Sentry / OpenTelemetry)
- [ ] Admin console for platform administrators
