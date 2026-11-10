"""Intelligence report generation.

A report is always produced by the deterministic rules engine first, so it is complete and
truthful with no LLM configured. When a provider is configured the report is *enriched* with
AI interpretations and hypotheses, which stay in their own clearly labelled sections.
"""

import datetime as dt

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.logging_config import get_logger
from app.models import (
    ChangeEvent,
    Competitor,
    CompetitorRepository,
    IntelligenceReport,
    Opportunity,
    Release,
    Repository,
    utcnow,
)
from app.services.ai.enrichment import enrich
from app.services.ai.providers import LLMError, get_provider
from app.services.intelligence import (
    PeerCache,
    current_score,
    get_weights,
    present_score,
    refresh_opportunity,
    score_repository,
)
from app.services.opportunities import DISCLAIMER
from app.taxonomy import CATEGORIES

log = get_logger("reports")

REPORT_TYPES = ("opportunity", "repository", "competitor", "comparison")


class ReportError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


class FactSheet:
    """Numbered facts so every AI statement can cite what it relies on."""

    def __init__(self) -> None:
        self.facts: list[dict] = []

    def add(self, label: str, value, kind: str = "verified_fact", source_url: str | None = None, explanation: str | None = None) -> str:
        fid = f"F{len(self.facts) + 1}"
        self.facts.append({"id": fid, "label": label, "value": str(value), "kind": kind, "source_url": source_url, "explanation": explanation})
        return fid

    @property
    def verified(self) -> list[dict]:
        return [f for f in self.facts if f["kind"] == "verified_fact"]

    @property
    def calculated(self) -> list[dict]:
        return [f for f in self.facts if f["kind"] == "calculated_metric"]


def _fmt_date(value: dt.datetime | None) -> str:
    return value.date().isoformat() if value else "unknown"


async def _repo_facts(session: AsyncSession, sheet: FactSheet, repo: Repository, score: dict | None, prefix: str = "") -> None:
    p = f"{prefix}: " if prefix else ""
    url = repo.html_url
    sheet.add(f"{p}Repository", repo.full_name, source_url=url)
    if repo.description:
        sheet.add(f"{p}Description (maintainers' own words)", repo.description, source_url=url)
    sheet.add(f"{p}Stars", f"{repo.stars:,}", source_url=url)
    sheet.add(f"{p}Forks", f"{repo.forks:,}", source_url=url)
    if repo.watchers is not None:
        sheet.add(f"{p}Watchers", f"{repo.watchers:,}", source_url=url)
    if repo.open_issues is not None:
        sheet.add(f"{p}Open issues and pull requests", f"{repo.open_issues:,}", source_url=url and f"{url}/issues")
    if repo.contributors_count is not None:
        sheet.add(f"{p}Contributors", f"{repo.contributors_count:,}", source_url=url and f"{url}/graphs/contributors")
    sheet.add(f"{p}Primary language", repo.primary_language or "not detected", source_url=url)
    sheet.add(f"{p}Licence", repo.license_spdx or "none detected", source_url=url)
    sheet.add(f"{p}Created", _fmt_date(repo.created_at_github), source_url=url)
    sheet.add(f"{p}Last push", _fmt_date(repo.pushed_at_github), source_url=url)
    if repo.topics:
        sheet.add(f"{p}Topics", ", ".join(repo.topics[:12]), source_url=url)
    latest = await session.scalar(select(Release).where(Release.repository_id == repo.id, Release.published_at.is_not(None)).order_by(Release.published_at.desc()))
    if latest:
        sheet.add(f"{p}Latest release", f"{latest.tag_name} on {_fmt_date(latest.published_at)}", source_url=latest.html_url)
    if repo.category:
        sheet.add(f"{p}Category (inferred by keyword classification)", CATEGORIES.get(repo.category, repo.category), kind="calculated_metric",
                  explanation="Assigned from topics, name and description; not a GitHub field.")
    if score:
        sheet.add(f"{p}Business potential score", f"{score['total']} out of 100", kind="calculated_metric",
                  explanation=f"Confidence {score['confidence']}; data coverage {score['coverage']:.0%}.")
        for metric in score["metrics"]:
            if metric["score"] is not None:
                sheet.add(f"{p}{metric['label']} score", f"{metric['score']} out of 100", kind="calculated_metric", explanation=metric["explanation"])
            for ev in metric["evidence"]:
                if ev["kind"] == "calculated":
                    sheet.add(f"{p}{ev['label']}", ev["value"], kind="calculated_metric")


async def _ensure_scored(session: AsyncSession, repo: Repository, organisation_id: int) -> dict:
    row = await current_score(session, repo.id)
    if row is None:
        cache = PeerCache()
        row, result, facts = await score_repository(session, repo, cache)
        await refresh_opportunity(session, repo, result, facts, cache)
        await session.flush()
    return present_score(row, await get_weights(session, organisation_id))


def _rules_interpretations(score: dict) -> list[dict]:
    out = []
    scored = [m for m in score["metrics"] if m["score"] is not None]
    for metric in sorted(scored, key=lambda m: -m["score"])[:2]:
        out.append({"text": f"Strongest signal: {metric['label'].lower()} at {metric['score']}/100. {metric['explanation']}", "generated_by": "rules", "confidence": score["confidence"], "references": []})
    for metric in sorted(scored, key=lambda m: m["score"])[:1]:
        out.append({"text": f"Weakest signal: {metric['label'].lower()} at {metric['score']}/100. {metric['explanation']}", "generated_by": "rules", "confidence": score["confidence"], "references": []})
    unscored = [m["label"] for m in score["metrics"] if m["score"] is None]
    if unscored:
        out.append({"text": f"Not scored for lack of data: {', '.join(unscored)}. The total is computed from the remaining metrics only.", "generated_by": "rules", "confidence": "high", "references": []})
    return out


async def _build_single(session: AsyncSession, organisation_id: int, repo: Repository, report_type: str) -> dict:
    score = await _ensure_scored(session, repo, organisation_id)
    sheet = FactSheet()
    await _repo_facts(session, sheet, repo, score)
    opportunity = await session.scalar(select(Opportunity).where(Opportunity.repository_id == repo.id))
    analysis = opportunity.analysis if opportunity else None
    hypotheses: list[dict] = []
    if analysis:
        for key in ("target_customers", "commercial_applications", "monetisation", "enterprise_applications", "differentiation"):
            for item in analysis.get(key, []):
                hypotheses.append({"text": item["text"], "generated_by": "rules", "confidence": "low", "topic": key, "references": []})
    summary = opportunity.summary if opportunity else (
        f"{repo.full_name} scores {score['total']}/100 with {score['confidence']} confidence. "
        "It does not currently meet the threshold for an opportunity hypothesis.")
    sources = [{"label": f"{repo.full_name} on GitHub", "url": repo.html_url}] if repo.html_url else []
    return {
        "subject": {"type": "repository", "repository_id": repo.id, "full_name": repo.full_name, "html_url": repo.html_url,
                    "opportunity_id": opportunity.id if opportunity else None},
        "title": f"{'Opportunity' if report_type == 'opportunity' else 'Repository'} intelligence report: {repo.full_name}",
        "summary": summary, "sheet": sheet, "score": score, "analysis": analysis, "hypotheses": hypotheses,
        "interpretations": _rules_interpretations(score), "sources": sources, "data_source": repo.data_source,
        "next_steps": (analysis or {}).get("recommended_next_steps", []),
    }


async def _build_comparison(session: AsyncSession, organisation_id: int, repos: list[Repository]) -> dict:
    sheet = FactSheet()
    scores = []
    for repo in repos:
        score = await _ensure_scored(session, repo, organisation_id)
        scores.append(score)
        await _repo_facts(session, sheet, repo, score, prefix=repo.full_name)
    ranked = sorted(zip(repos, scores, strict=True), key=lambda pair: -pair[1]["total"])
    leader, leader_score = ranked[0]
    interpretations = [{"text": f"{leader.full_name} has the highest business potential score ({leader_score['total']}/100) of the compared repositories.", "generated_by": "rules", "confidence": leader_score["confidence"], "references": []}]
    for key in ("development_momentum", "developer_adoption", "commercial_potential"):
        best = None
        for repo, score in ranked:
            metric = next((m for m in score["metrics"] if m["key"] == key and m["score"] is not None), None)
            if metric and (best is None or metric["score"] > best[1]["score"]):
                best = (repo, metric)
        if best:
            interpretations.append({"text": f"{best[0].full_name} leads on {best[1]['label'].lower()} ({best[1]['score']}/100).", "generated_by": "rules", "confidence": "medium", "references": []})
    return {
        "subject": {"type": "comparison", "repositories": [{"repository_id": r.id, "full_name": r.full_name, "html_url": r.html_url, "score": s["total"], "confidence": s["confidence"]} for r, s in ranked]},
        "title": "Comparison report: " + " vs ".join(r.full_name for r in repos),
        "summary": f"Compared {len(repos)} repositories on the Signal Atlas scoring framework. {leader.full_name} ranks first at {leader_score['total']}/100.",
        "sheet": sheet, "score": None, "analysis": None, "hypotheses": [], "interpretations": interpretations,
        "sources": [{"label": f"{r.full_name} on GitHub", "url": r.html_url} for r in repos if r.html_url],
        "data_source": "demo_fixture" if any(r.data_source == "demo_fixture" for r in repos) else "live_github",
        "next_steps": ["Open each repository's score breakdown to see the evidence behind the ranking.", "Check the 'missing data' notes: a repository with thin data can rank lower than it deserves."],
    }


async def _build_competitor(session: AsyncSession, organisation_id: int, competitor: Competitor) -> dict:
    repos = list((await session.scalars(
        select(Repository).join(CompetitorRepository, CompetitorRepository.repository_id == Repository.id)
        .where(CompetitorRepository.competitor_id == competitor.id).order_by(Repository.stars.desc()))).all())
    if not repos:
        raise ReportError("Add at least one repository to this competitor before generating a report.")
    sheet = FactSheet()
    sheet.add("Competitor", competitor.name)
    interpretations: list[dict] = []
    since = utcnow() - dt.timedelta(days=30)
    event_total = 0
    for repo in repos[:6]:
        score = await _ensure_scored(session, repo, organisation_id)
        await _repo_facts(session, sheet, repo, score, prefix=repo.full_name)
        events = list((await session.scalars(select(ChangeEvent).where(ChangeEvent.repository_id == repo.id, ChangeEvent.occurred_at >= since).order_by(ChangeEvent.occurred_at.desc()).limit(10))).all())
        event_total += len(events)
        for event in events:
            sheet.add(f"{repo.full_name}: change detected on {_fmt_date(event.occurred_at)}", event.title, source_url=event.evidence_url)
        releases = [e for e in events if e.event_type == "release"]
        deps = [e for e in events if e.event_type == "dependency_change"]
        if releases:
            interpretations.append({"text": f"{repo.full_name} shipped {len(releases)} release(s) in the last 30 days, indicating active product delivery.", "generated_by": "rules", "confidence": "high", "references": []})
        for event in deps[:2]:
            added = ", ".join(event.details.get("added", [])[:6]) or "none"
            removed = ", ".join(event.details.get("removed", [])[:6]) or "none"
            interpretations.append({"text": f"{repo.full_name} changed runtime dependencies (added: {added}; removed: {removed}). New dependencies can reveal features under development.", "generated_by": "rules", "confidence": "medium", "references": []})
    if event_total == 0:
        interpretations.append({"text": "No changes were detected in the last 30 days. Change detection starts from the first full sync of each repository, so history before that is not covered.", "generated_by": "rules", "confidence": "high", "references": []})
    return {
        "subject": {"type": "competitor", "competitor_id": competitor.id, "name": competitor.name,
                    "repositories": [{"repository_id": r.id, "full_name": r.full_name, "html_url": r.html_url} for r in repos]},
        "title": f"Competitor report: {competitor.name}",
        "summary": f"{competitor.name}: {len(repos)} monitored repositor{'y' if len(repos) == 1 else 'ies'}, {event_total} change(s) detected in the last 30 days.",
        "sheet": sheet, "score": None, "analysis": None, "hypotheses": [], "interpretations": interpretations,
        "sources": [{"label": f"{r.full_name} on GitHub", "url": r.html_url} for r in repos if r.html_url],
        "data_source": "demo_fixture" if any(r.data_source == "demo_fixture" for r in repos) else "live_github",
        "next_steps": ["Review each release's notes for features that overlap with your roadmap.", "Add the competitor's other public repositories to widen coverage."],
    }


def _assemble(built: dict, report_type: str, provider_name: str, model: str | None, ai: dict | None = None, guard: dict | None = None, ai_error: str | None = None) -> dict:
    sheet: FactSheet = built["sheet"]
    interpretations = list(built["interpretations"])
    hypotheses = list(built["hypotheses"])
    summary = {"text": built["summary"], "generated_by": "rules"}
    use_cases: list[dict] = []
    next_steps = [{"text": s, "generated_by": "rules"} for s in built["next_steps"]]
    if ai:
        if not (guard or {}).get("summary_rejected"):
            summary = {"text": ai["executive_summary"], "generated_by": "ai"}
        interpretations += [dict(i, generated_by="ai") for i in ai["interpretations"]]
        hypotheses += [dict(h, generated_by="ai") for h in ai["hypotheses"]]
        use_cases = [dict(u, generated_by="ai") for u in ai["commercial_use_cases"]]
        next_steps += [{"text": s, "generated_by": "ai"} for s in ai["recommended_next_steps"]]
    return {
        "schema_version": 1,
        "report_type": report_type,
        "subject": built["subject"],
        "executive_summary": summary,
        "verified_facts": sheet.verified,
        "calculated_metrics": sheet.calculated,
        "interpretations": interpretations,
        "hypotheses": hypotheses,
        "commercial_use_cases": use_cases,
        "score": built["score"],
        "analysis": built["analysis"],
        "recommended_next_steps": next_steps,
        "sources": built["sources"],
        "provenance": {
            "generated_at": utcnow().isoformat(),
            "provider": provider_name,
            "model": model,
            "ai_enriched": bool(ai),
            "ai_error": ai_error,
            "guardrails": guard,
            "data_source": built["data_source"],
            "legend": {
                "verified_facts": "Copied from GitHub public data at the time of the last sync.",
                "calculated_metrics": "Computed by Signal Atlas from verified facts using documented formulas.",
                "interpretations": "Readings of the facts, by the rules engine or an AI model (labelled per item).",
                "hypotheses": "Unverified commercial ideas. Not validated by any market evidence.",
            },
        },
        "disclaimer": DISCLAIMER,
    }


async def build_report(session: AsyncSession, organisation_id: int, report_type: str, subject_id: int | None, repository_ids: list[int] | None = None) -> dict:
    if report_type in ("opportunity", "repository"):
        if report_type == "opportunity":
            opportunity = await session.get(Opportunity, subject_id) if subject_id else None
            if opportunity is None:
                raise ReportError("Opportunity not found.", 404)
            repo = await session.get(Repository, opportunity.repository_id)
        else:
            repo = await session.get(Repository, subject_id) if subject_id else None
        if repo is None:
            raise ReportError("Repository not found.", 404)
        return await _build_single(session, organisation_id, repo, report_type)
    if report_type == "comparison":
        ids = list(dict.fromkeys(repository_ids or []))
        if not 2 <= len(ids) <= 4:
            raise ReportError("A comparison needs between 2 and 4 repository ids.")
        repos = list((await session.scalars(select(Repository).where(Repository.id.in_(ids)))).all())
        if len(repos) != len(ids):
            raise ReportError("One or more repositories were not found.", 404)
        return await _build_comparison(session, organisation_id, sorted(repos, key=lambda r: ids.index(r.id)))
    if report_type == "competitor":
        # Tenant isolation: a competitor is only ever resolved inside the caller's organisation.
        competitor = await session.scalar(select(Competitor).where(Competitor.id == subject_id, Competitor.organisation_id == organisation_id))
        if competitor is None:
            raise ReportError("Competitor not found.", 404)
        return await _build_competitor(session, organisation_id, competitor)
    raise ReportError(f"Unknown report type '{report_type}'.")


async def generate_report(session: AsyncSession, organisation_id: int, user_id: int | None, report_type: str, subject_id: int | None,
                          repository_ids: list[int] | None = None, use_ai: bool = True) -> IntelligenceReport:
    """Create the deterministic report. When AI is enabled the row is marked ``enriching`` for the worker."""
    built = await build_report(session, organisation_id, report_type, subject_id, repository_ids)
    provider = get_provider() if use_ai else None
    content = _assemble(built, report_type, "rules", None)
    content["_enrichment_input"] = {"facts": built["sheet"].facts, "rules_summary": built["summary"], "repository_ids": repository_ids}
    report = IntelligenceReport(
        organisation_id=organisation_id, created_by=user_id, report_type=report_type,
        subject_type=built["subject"]["type"], subject_id=subject_id or 0, title=built["title"][:300],
        status="enriching" if provider else "complete", provider="rules", model=None, content=content, data_source=built["data_source"])
    session.add(report)
    await session.flush()
    return report


async def enrich_report(session: AsyncSession, report: IntelligenceReport) -> IntelligenceReport:
    """Add AI interpretations to an existing report. Failure leaves the deterministic report intact."""
    provider = get_provider()
    content = dict(report.content)
    pending = content.pop("_enrichment_input", None)
    if provider is None or pending is None:
        report.status = "complete"
        report.content = content
        return report
    try:
        enrichment, guard = await enrich(provider, report.report_type, report.title, pending["facts"], pending["rules_summary"])
    except LLMError as exc:
        log.warning("report_enrichment_failed", report_id=report.id, error=str(exc)[:200])
        content["provenance"] = dict(content["provenance"], ai_error="AI enrichment was unavailable; this report contains rule-based analysis only.")
        report.content = content
        report.status = "complete"
        report.error = str(exc)[:500]
        return report
    ai = enrichment.model_dump()
    content["executive_summary"] = content["executive_summary"] if guard.get("summary_rejected") else {"text": ai["executive_summary"], "generated_by": "ai"}
    content["interpretations"] = content["interpretations"] + [dict(i, generated_by="ai") for i in ai["interpretations"]]
    content["hypotheses"] = content["hypotheses"] + [dict(h, generated_by="ai") for h in ai["hypotheses"]]
    content["commercial_use_cases"] = [dict(u, generated_by="ai") for u in ai["commercial_use_cases"]]
    content["recommended_next_steps"] = content["recommended_next_steps"] + [{"text": s, "generated_by": "ai"} for s in ai["recommended_next_steps"]]
    content["provenance"] = dict(content["provenance"], provider=provider.name, model=provider.model, ai_enriched=True, guardrails=guard, enriched_at=utcnow().isoformat())
    report.content = content
    report.provider = provider.name
    report.model = provider.model
    report.status = "complete"
    return report


def public_content(content: dict) -> dict:
    """Strip internal working data before returning a report to a client."""
    return {k: v for k, v in content.items() if not k.startswith("_")}


__all__ = ["REPORT_TYPES", "ReportError", "build_report", "enrich_report", "generate_report", "public_content", "get_settings"]
