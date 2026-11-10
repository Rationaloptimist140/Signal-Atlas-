# SIGNAL ATLAS — Product Requirements

Version 1.0 (MVP). Source: the Master Product & Engineering Build Specification.

## 1. Vision

Transform the global open-source ecosystem into actionable technology and business intelligence. Help users **discover emerging technologies and commercial opportunities before the wider market recognises them** — with the feel of a premium intelligence terminal.

Questions the product answers: what is gaining momentum; which developers drive it; which projects grow unusually fast; which markets look underserved; which projects could become commercial products; what competitors are building; where to focus attention.

## 2. Customers

Entrepreneurs and SaaS founders · technology investors and VC firms · AI startups · software companies · product managers · technology consultants · corporate innovation teams · independent developers.

## 3. Product principles (non-negotiable)

1. **Real data before impressive numbers.** Live GitHub data and demo fixtures are always distinguished. No invented statistics.
2. **Evidence and confidence on everything.** Scores list evidence, data freshness, confidence and missing data.
3. **Hypotheses are labelled as hypotheses.** Popularity never validates an opportunity.
4. **Read-only GitHub access.** We analyse; we never modify repositories or collect private data.
5. **Popularity is not ability.** Developer indicators describe visibility, not skill.
6. **Not a speculation platform.** A commercially minded intelligence business, not token or price prediction.

## 4. The six engines

| # | Engine | MVP scope delivered |
|---|---|---|
| 1 | Repository Intelligence | Discovery (GitHub Search), profiles, stars/forks/watchers, commit frequency, contributors, releases, issues/PRs, languages, licence, root-manifest dependencies, fork family, momentum |
| 2 | Developer Intelligence | Public profiles, contribution history on tracked repos, inferred languages/specialisation, collaboration network, influence indicators with disclaimer, emerging-contributor flag |
| 3 | Emerging Technology Detection | Star surges, unusual growth vs peers (robust z-score), commit acceleration, breakout new projects, contributor growth, release bursts, category momentum, emerging clusters; daily/weekly/monthly windows |
| 4 | Commercial Opportunity Intelligence | Per-repository hypothesis: problem, target customers, demand indicators, applications, monetisation, enterprise uses, adjacent projects, differentiation, feasibility/maturity, licensing and commercialisation risks, next steps, recommended action |
| 5 | Competitive Intelligence | Competitors with attached repositories, comparison table, release / dependency / stack change detection, notifications, change reports |
| 6 | Business Potential Scoring | 0–100, seven metrics, configurable weights, evidence, freshness, confidence, missing-data indicators |

AI Intelligence Engine: provider-independent enrichment (Anthropic, OpenAI-compatible) with validated JSON output and numeric guardrails; deterministic rules engine as the always-available base.

## 5. Scoring framework

| Metric | Default weight | Built from |
|---|---:|---|
| Development momentum | 20% | Commits (4 weeks), commit trend, push recency, release cadence |
| Developer adoption | 15% | Stars, forks, watchers (log scale) |
| Community growth | 10% | Star growth between snapshots, contributors, contributor growth |
| Technical innovation | 15% | Proxy: traction for age, frontier-technology alignment, originality, merged PRs |
| Commercial potential | 20% | Licence terms, category affinity, commercial-intent keywords, organisational backing |
| Market demand | 10% | Issue volume, fork intent, pull-request demand |
| Competitive positioning | 10% | Star percentile and gap to leader among tracked peers in the category |

Metrics with insufficient data are **not scored**; the total is the weighted mean of scored metrics, damped towards a neutral 50 in proportion to the weight without data. Scores are heuristics and have not been validated against commercial outcomes.

## 6. Experience

Dark premium interface (palette and typography per the specification), collapsible sidebar with eleven sections, global search (⌘K), notification centre, live/demo data switch, and a persistent banner whenever demo data is shown.

Pages: Overview · Explore Technologies · Repository Intelligence (+ detail with 8 tabs) · Developer Intelligence (+ detail) · Emerging Trends · Opportunity Discovery (+ detail) · Competitor Intelligence (+ detail) · Intelligence Reports (+ detail) · Watchlists · API & Developers · Settings.

## 7. Commercial model (proposal — payments not live)

| Plan | Price | Reports/mo | Saved items | Competitors | Live GitHub requests/mo | API requests/mo | AI enrichment | Custom weights |
|---|---:|---:|---:|---:|---:|---:|:-:|:-:|
| Free | £0 | 3 | 10 | 1 | 20 | — | — | — |
| Pro | £19 | 30 | 100 | 5 | 300 | 10,000 | ✓ | — |
| Professional | £49 | 150 | 500 | 20 | 1,500 | 100,000 | ✓ | ✓ |
| Business | £149 | 750 | 2,500 | 100 | 10,000 | 1,000,000 | ✓ | ✓ |
| Enterprise | Custom | Unlimited | Unlimited | Unlimited | Unlimited | Unlimited | ✓ | ✓ |

Limits are enforced by the API (HTTP 402 with an upgrade payload) and surfaced as upgrade prompts. These limits are starting assumptions to validate with customers.

## 8. Definition of MVP success

A user can: (1) register and log in; (2) connect a GitHub account securely; (3) search public GitHub repositories; (4) explore development activity; (5) view developer profiles; (6) identify emerging signals; (7) view opportunity scores; (8) generate opportunity reports; (9) save repositories and opportunities; (10) monitor competitors. Status of each: see [PROGRESS.md](PROGRESS.md).

## 9. Out of scope for the MVP

Live payments · team invitations and email verification (need an email provider) · Neo4j · code-level novelty analysis · package-registry download statistics · external market data (search volume, funding, job postings) · organisation-wide GitHub App install.
