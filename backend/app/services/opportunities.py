"""Rule-based commercial opportunity analysis.

Everything here is deterministic. Each statement is tagged with its epistemic ``basis``:

* ``verified_fact``      - copied from GitHub public data
* ``calculated_metric``  - computed by Signal Atlas from verified facts
* ``interpretation``     - a rule-based reading of the facts
* ``hypothesis``         - an unvalidated commercial idea worth testing

Popularity never upgrades a hypothesis to a validated opportunity.
"""

from app.services.scoring import (
    NETWORK_COPYLEFT,
    PERMISSIVE,
    SOURCE_AVAILABLE,
    STRONG_COPYLEFT,
    WEAK_COPYLEFT,
    RepoFacts,
    ScoreResult,
)
from app.taxonomy import CATEGORIES

DISCLAIMER = (
    "This analysis is generated from public repository metadata. Hypotheses are unvalidated: repository "
    "popularity is not evidence of commercial demand. Validate with customer research before investing."
)

CATEGORY_PLAYBOOK: dict[str, dict[str, list[str]]] = {
    "ai-ml": {
        "customers": ["Product teams adding AI features without an in-house ML platform", "AI startups needing production-grade building blocks", "Enterprises with data-residency constraints that rule out public AI APIs"],
        "applications": ["Managed inference or agent runtime with usage-based pricing", "Vertical AI assistant built on the project for one regulated industry", "Evaluation, monitoring and guardrail tooling sold alongside the open core"],
        "enterprise": ["Private deployment with SSO, audit logging and role-based access", "Model governance and compliance reporting", "Support contracts with response-time guarantees"],
    },
    "fintech": {
        "customers": ["SME finance teams replacing spreadsheets", "Fintech startups that need audited financial primitives", "Accountancy practices serving many small clients"],
        "applications": ["Hosted, compliance-ready edition with bank and accounting integrations", "White-label module licensed to software vendors", "Reconciliation and reporting add-ons sold per entity"],
        "enterprise": ["Audit trails and segregation of duties", "Regulatory reporting packs", "Certified integrations with ERP systems"],
    },
    "blockchain": {
        "customers": ["Infrastructure teams running nodes or indexers", "Exchanges and custodians needing audited components", "Developers building on-chain applications"],
        "applications": ["Managed node or API service with SLAs", "Security auditing and monitoring service", "Developer tooling subscription"],
        "enterprise": ["Permissioned deployments", "Compliance and transaction monitoring", "Dedicated support"],
    },
    "developer-infrastructure": {
        "customers": ["Engineering teams of 10-200 developers", "Platform engineering groups standardising tooling", "Developer-tool startups needing an embeddable component"],
        "applications": ["Hosted team edition with collaboration and usage analytics", "Paid plugins or integrations marketplace", "CI/CD or IDE integration sold per seat"],
        "enterprise": ["SSO/SAML, audit logs and policy controls", "Self-hosted enterprise licence", "Priority support and migration services"],
    },
    "cybersecurity": {
        "customers": ["Security teams at mid-sized companies without large budgets", "Managed security service providers", "Compliance-driven organisations preparing for SOC 2 or ISO 27001"],
        "applications": ["Managed scanning or monitoring service with alerting", "Compliance evidence collection built on the tool's output", "Curated rules or threat-intelligence subscription"],
        "enterprise": ["Central policy management across teams", "SIEM and ticketing integrations", "Attested builds and support SLAs"],
    },
    "automation": {
        "customers": ["Operations teams automating repetitive back-office work", "Agencies delivering automation for clients", "SaaS vendors embedding workflow features"],
        "applications": ["Hosted automation platform priced per run or per workflow", "Template and connector marketplace", "Done-for-you automation service built on the project"],
        "enterprise": ["Governance, approvals and audit history", "On-premise runners for sensitive data", "Premium connectors for enterprise systems"],
    },
    "cloud-computing": {
        "customers": ["Platform teams operating Kubernetes or multi-cloud estates", "Start-ups wanting a simpler deployment path", "Regulated firms requiring self-hosting"],
        "applications": ["Managed control plane with usage-based pricing", "Cost and reliability insights add-on", "Certified distribution with long-term support"],
        "enterprise": ["Multi-cluster management and policy enforcement", "Compliance-hardened builds", "24x7 support"],
    },
    "data-infrastructure": {
        "customers": ["Data teams outgrowing a single database or warehouse", "SaaS companies needing embedded analytics or storage", "Enterprises consolidating data tooling"],
        "applications": ["Fully managed cloud service (the dominant model in this category)", "Enterprise features such as replication, backup and security", "Consulting and migration services"],
        "enterprise": ["High-availability and disaster-recovery features", "Fine-grained access control and encryption", "Support subscriptions"],
    },
    "enterprise-software": {
        "customers": ["SMEs seeking an affordable alternative to incumbent SaaS", "Organisations that must self-host for privacy", "Agencies and resellers serving a niche vertical"],
        "applications": ["Hosted edition priced per seat", "Vertical-specific edition for one industry", "Implementation, hosting and support packages"],
        "enterprise": ["SSO, permissions and audit logs", "Data-residency options", "Integration with existing identity and ERP systems"],
    },
}
DEFAULT_PLAYBOOK = {
    "customers": ["Teams already using the project who would pay for convenience or support"],
    "applications": ["Hosted edition of the project", "Paid support and implementation services"],
    "enterprise": ["Security, compliance and support add-ons"],
}


def _stmt(text: str, basis: str, **extra) -> dict:
    return {"text": text, "basis": basis, **extra}


def maturity_of(f: RepoFacts) -> tuple[str, str]:
    age_days = (f.now - f.created_at).days if f.created_at else None
    releases = len(f.release_dates) if f.release_dates is not None else None
    contributors = f.contributors_count
    if age_days is None:
        return "unknown", "Creation date unknown."
    detail = f"{age_days} days old" + (f", {releases} releases recorded" if releases is not None else "") + (f", {contributors} contributors" if contributors is not None else "")
    if age_days < 180 or (releases == 0 and (contributors or 0) < 5):
        return "experimental", detail
    if age_days < 540 or (releases is not None and releases < 10):
        return "emerging", detail
    if age_days >= 1460 and (contributors or 0) >= 20 and (releases or 0) >= 10:
        return "mature", detail
    return "established", detail


def licensing_risks(spdx: str | None) -> tuple[list[dict], int]:
    if not spdx:
        return [_stmt("No licence was detected. Without an explicit licence, default copyright applies and commercial reuse is not permitted without the owner's consent.", "interpretation", severity="high")], 3
    if spdx in PERMISSIVE:
        return [_stmt(f"{spdx} is permissive: commercial use is allowed with attribution. The same freedom lets competitors, including cloud providers, offer the project as a service.", "interpretation", severity="low")], 0
    if spdx in WEAK_COPYLEFT:
        return [_stmt(f"{spdx} is weak copyleft: modifications to the licensed files or library must be shared, but it can usually be combined with proprietary code.", "interpretation", severity="medium")], 1
    if spdx in STRONG_COPYLEFT:
        return [_stmt(f"{spdx} is strong copyleft: distributing a derivative product requires releasing its source under the same licence, which constrains proprietary products.", "interpretation", severity="medium")], 2
    if spdx in NETWORK_COPYLEFT:
        return [_stmt("AGPL-3.0 extends copyleft to network use: offering a modified version as a hosted service requires publishing the source. Third-party SaaS built on it generally needs a commercial licence from the copyright holder.", "interpretation", severity="high")], 2
    if spdx in SOURCE_AVAILABLE:
        return [_stmt(f"{spdx} is source-available, not open source: it typically prohibits offering the software as a competing managed service.", "interpretation", severity="high")], 3
    return [_stmt(f"Licence '{spdx}' is not in the standard set we evaluate; obtain legal review before any commercial use.", "interpretation", severity="medium")], 2


def build_analysis(f: RepoFacts, score: ScoreResult, adjacent: list[dict]) -> dict:
    """Assemble the structured opportunity analysis for one repository."""
    playbook = CATEGORY_PLAYBOOK.get(f.category or "", DEFAULT_PLAYBOOK)
    category_label = CATEGORIES.get(f.category or "", "Uncategorised")
    maturity, maturity_detail = maturity_of(f)
    lic_risks, risk_points = licensing_risks(f.license_spdx)

    demand: list[dict] = [
        _stmt(f"{f.stars:,} stars and {f.forks:,} forks on GitHub.", "verified_fact", source_url=f.html_url),
    ]
    if f.open_issues is not None:
        demand.append(_stmt(f"{f.open_issues:,} open issues and pull requests, indicating active users reporting needs.", "verified_fact", source_url=f.html_url and f"{f.html_url}/issues"))
    if f.contributors_count is not None:
        demand.append(_stmt(f"{f.contributors_count:,} contributors have committed to the project.", "verified_fact", source_url=f.html_url and f"{f.html_url}/graphs/contributors"))
    for metric in score.metrics:
        if metric.key in ("community_growth", "development_momentum") and metric.score is not None:
            demand.append(_stmt(f"{metric.label} scores {metric.score:.0f}/100.", "calculated_metric"))

    commercial_risks: list[dict] = []
    if f.archived:
        commercial_risks.append(_stmt("The repository is archived: no further upstream development is expected.", "verified_fact", severity="high"))
        risk_points += 5
    if f.pushed_at and (f.now - f.pushed_at).days > 180:
        commercial_risks.append(_stmt(f"No push for {(f.now - f.pushed_at).days} days: the project may be unmaintained.", "calculated_metric", severity="high"))
        risk_points += 2
    if f.top_contributor_share is not None and f.top_contributor_share > 0.7:
        commercial_risks.append(_stmt(f"Key-person dependency: one contributor accounts for {f.top_contributor_share:.0%} of commits among the top contributors.", "calculated_metric", severity="medium"))
        risk_points += 2
    if f.contributors_count is not None and f.contributors_count < 5:
        commercial_risks.append(_stmt(f"Very small contributor base ({f.contributors_count}).", "verified_fact", severity="medium"))
        risk_points += 1
    if maturity == "experimental":
        commercial_risks.append(_stmt("Early-stage project: APIs and direction may change significantly.", "interpretation", severity="medium"))
        risk_points += 1
    if f.owner_type == "Organization" and f.has_homepage:
        commercial_risks.append(_stmt("The maintainers appear to be an organisation with a product website and may already commercialise this project; check for an existing paid offering before competing.", "hypothesis", severity="medium"))
        risk_points += 1
    commercial_risks.append(_stmt("Demand is inferred from developer activity only. Willingness to pay has not been tested.", "interpretation", severity="medium"))

    risk_level = "low" if risk_points <= 2 else "medium" if risk_points <= 5 else "high"

    total = score.total
    if f.archived or risk_level == "high" and total < 60:
        action, action_text = "deprioritise", "Deprioritise unless you have a specific reason to accept the risks listed."
    elif total >= 65 and score.confidence == "low":
        action, action_text = "monitor", "Promising on headline figures, but the evidence is thin. Run a full sync to complete the data before investing time."
    elif total >= 65:
        action, action_text = "investigate", "Investigate now: run customer discovery with the target segments below."
    elif total >= 45:
        action, action_text = "monitor", "Monitor: add to a watchlist and revisit when momentum or evidence improves."
    else:
        action, action_text = "deprioritise", "Deprioritise: current signals are weak relative to other tracked projects."

    next_steps = [
        "Interview 5-10 people from the target segment about the problem before building anything.",
        f"Review the licence ({f.license_spdx or 'none detected'}) with a qualified adviser for your intended distribution model.",
        "Check whether the maintainers already offer a hosted or enterprise edition.",
        "Read the 20 most-commented open issues to find unmet needs users describe in their own words.",
    ]
    if score.missing:
        next_steps.append("Run a full sync and connect a GitHub token to fill the data gaps listed in the score before relying on it.")

    description = (f.description or "").strip()
    return {
        "problem": _stmt(
            (f"The project describes itself as: \"{description}\". " if description else "The repository has no description. ")
            + f"It is classified under {category_label}; the underlying problem should be confirmed with users.",
            "interpretation"),
        "target_customers": [_stmt(t, "hypothesis") for t in playbook["customers"]],
        "demand_indicators": demand,
        "commercial_applications": [_stmt(t, "hypothesis") for t in playbook["applications"]],
        "monetisation": [
            _stmt("Managed cloud hosting with usage- or seat-based pricing.", "hypothesis", model="hosted_saas"),
            _stmt("Open-core: paid enterprise features (SSO, audit, governance) on top of the free project.", "hypothesis", model="open_core"),
            _stmt("Support, implementation and training contracts.", "hypothesis", model="services"),
        ],
        "enterprise_applications": [_stmt(t, "hypothesis") for t in playbook["enterprise"]],
        "adjacent_projects": adjacent,
        "differentiation": [
            _stmt("Specialise for one vertical or compliance regime the general-purpose project does not address.", "hypothesis"),
            _stmt("Compete on operational experience: onboarding, reliability, integrations and support.", "hypothesis"),
        ],
        "technical_feasibility": _stmt(f"Maturity assessed as {maturity} ({maturity_detail}).", "interpretation", maturity=maturity),
        "licensing_risks": lic_risks,
        "commercialisation_risks": commercial_risks,
        "risk_level": risk_level,
        "recommended_action": {"key": action, "text": action_text, "basis": "interpretation"},
        "recommended_next_steps": next_steps,
        "disclaimer": DISCLAIMER,
    }


def summarise(f: RepoFacts, score: ScoreResult, analysis: dict) -> str:
    category_label = CATEGORIES.get(f.category or "", "uncategorised")
    return (
        f"{f.full_name} ({category_label}) scores {score.total:.0f}/100 with {score.confidence} confidence. "
        f"Maturity: {analysis['technical_feasibility']['maturity']}; risk: {analysis['risk_level']}. "
        f"{analysis['recommended_action']['text']}"
    )
