"""Commercial Opportunity Intelligence (Engine 4) and reports (Engine 8)."""

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.deps import Principal, get_principal, require_analyst, require_verified_analyst
from app.models import IntelligenceReport, Opportunity, OpportunityScore, Repository
from app.routers.common import SourceParam, paginate, resolve_source, source_query
from app.schemas import OpportunityOut, Page, ReportGenerateIn, ReportOut
from app.services import jobs
from app.services.intelligence import current_score, get_weights, present_score
from app.services.reports import ReportError, generate_report, public_content
from app.services.scoring import DEFAULT_WEIGHTS, total_from_metrics
from app.services.usage import audit, enforce_monthly_limit, org_plan, record_usage
from app.taxonomy import CATEGORIES

router = APIRouter(tags=["opportunities"])


def _report_out(report: IntelligenceReport, *, with_content: bool) -> ReportOut:
    """Serialise a report. Internal working data (keys starting with ``_``) is never exposed."""
    content = public_content(report.content or {})
    return ReportOut(
        id=report.id, report_type=report.report_type, subject_type=report.subject_type, subject_id=report.subject_id, title=report.title,
        status=report.status, provider=report.provider, model=report.model, data_source=report.data_source, created_at=report.created_at,
        updated_at=report.updated_at, summary=(content.get("executive_summary") or {}).get("text"), content=content if with_content else None)


def _opportunity_item(opp: Opportunity, repo: Repository, score: OpportunityScore | None, weights: dict[str, float]) -> OpportunityOut:
    item = OpportunityOut.model_validate(opp)
    item.repository_full_name, item.repository_html_url = repo.full_name, repo.html_url
    item.stars, item.primary_language, item.license_spdx = repo.stars, repo.primary_language, repo.license_spdx
    item.recommended_action = (opp.analysis or {}).get("recommended_action", {}).get("key")
    if score:
        item.metrics = [{"key": m["key"], "label": m["label"], "score": m["score"]} for m in score.metrics]
        if weights != DEFAULT_WEIGHTS:
            item.score = round(total_from_metrics(score.metrics, weights)[0], 2)
    return item


@router.get("/opportunities", response_model=Page[OpportunityOut], summary="Ranked commercial opportunity hypotheses")
async def list_opportunities(
    category: str | None = Query(None, max_length=60),
    min_score: float | None = Query(None, ge=0, le=100),
    risk: Literal["low", "medium", "high"] | None = None,
    maturity: Literal["experimental", "emerging", "established", "mature"] | None = None,
    confidence: Literal["low", "medium", "high"] | None = None,
    sort: Literal["score", "recent", "stars"] = "score",
    source: SourceParam = source_query(),
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    principal: Principal = Depends(get_principal),
    db: AsyncSession = Depends(get_db),
) -> Page[OpportunityOut]:
    query = select(Opportunity, Repository, OpportunityScore).join(Repository, Repository.id == Opportunity.repository_id) \
        .outerjoin(OpportunityScore, (OpportunityScore.repository_id == Repository.id) & OpportunityScore.is_current.is_(True))
    data_source = await resolve_source(db, source)
    if data_source:
        query = query.where(Opportunity.data_source == data_source)
    if category:
        query = query.where(Opportunity.category == category)
    if min_score is not None:
        query = query.where(Opportunity.score >= min_score)
    if risk:
        query = query.where(Opportunity.risk_level == risk)
    if maturity:
        query = query.where(Opportunity.maturity == maturity)
    if confidence:
        query = query.where(Opportunity.confidence == confidence)
    order = {"score": Opportunity.score.desc(), "recent": Opportunity.updated_at.desc(), "stars": Repository.stars.desc()}[sort]
    rows, total = await paginate(db, query.order_by(order, Opportunity.id), page, page_size)
    weights = await get_weights(db, principal.organisation_id)
    items = [_opportunity_item(opp, repo, score, weights) for opp, repo, score in rows]
    if weights != DEFAULT_WEIGHTS and sort == "score":
        items.sort(key=lambda i: -i.score)
    return Page[OpportunityOut](items=items, total=total, page=page, page_size=page_size)


@router.get("/opportunities/{opportunity_id}", summary="Opportunity hypothesis with score, evidence and risks")
async def get_opportunity(opportunity_id: int, principal: Principal = Depends(get_principal), db: AsyncSession = Depends(get_db)) -> dict:
    opp = await db.get(Opportunity, opportunity_id)
    if opp is None:
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": "Opportunity not found."})
    repo = await db.get(Repository, opp.repository_id)
    score_row = await current_score(db, repo.id)
    weights = await get_weights(db, principal.organisation_id)
    return {
        "opportunity": _opportunity_item(opp, repo, score_row, weights),
        "category_label": CATEGORIES.get(opp.category or ""),
        "analysis": opp.analysis,
        "score": present_score(score_row, weights) if score_row else None,
        "repository": {"id": repo.id, "full_name": repo.full_name, "html_url": repo.html_url, "description": repo.description, "stars": repo.stars, "forks": repo.forks,
                       "last_synced_at": repo.last_synced_at, "sync_level": repo.sync_level},
        "labels": {"verified_fact": "Verified fact", "calculated_metric": "Calculated metric", "interpretation": "Interpretation", "hypothesis": "Unverified hypothesis"},
        "validation_status": "unvalidated",
        "validation_note": "This is a hypothesis generated from public repository data. It has not been validated with customers or market research.",
        "data_source": opp.data_source,
    }


@router.post("/reports/generate", response_model=ReportOut, status_code=201, tags=["reports"], summary="Generate an intelligence report")
async def generate(body: ReportGenerateIn, principal: Principal = Depends(require_verified_analyst), db: AsyncSession = Depends(get_db)) -> ReportOut:
    plan = await enforce_monthly_limit(db, principal.organisation_id, "reports", "reports_per_month", "reports")
    try:
        report = await generate_report(db, principal.organisation_id, principal.user_id, body.report_type, body.subject_id, body.repository_ids,
                                       use_ai=body.use_ai and plan.ai_enrichment)
    except ReportError as exc:
        raise HTTPException(status_code=exc.status, detail={"code": "report_error", "message": str(exc)}) from exc
    await record_usage(db, principal.organisation_id, "reports")
    await audit(db, "report.generated", organisation_id=principal.organisation_id, user_id=principal.user_id, target_type="report", target_id=report.id,
                details={"report_type": body.report_type})
    await db.commit()
    if report.status == "enriching":
        await jobs.enqueue_and_maybe_run(db, "enrich_report", {"report_id": report.id}, dedupe_key=f"enrich_report:{report.id}", organisation_id=principal.organisation_id)
        await db.refresh(report)
    return _report_out(report, with_content=True)


@router.get("/reports", response_model=Page[ReportOut], tags=["reports"], summary="Reports generated by your organisation")
async def list_reports(report_type: str | None = Query(None, max_length=30), page: int = Query(1, ge=1), page_size: int = Query(25, ge=1, le=100),
                       principal: Principal = Depends(get_principal), db: AsyncSession = Depends(get_db)) -> Page[ReportOut]:
    query = select(IntelligenceReport).where(IntelligenceReport.organisation_id == principal.organisation_id)
    if report_type:
        query = query.where(IntelligenceReport.report_type == report_type)
    rows, total = await paginate(db, query.order_by(IntelligenceReport.created_at.desc()), page, page_size)
    return Page[ReportOut](items=[_report_out(r[0], with_content=False) for r in rows], total=total, page=page, page_size=page_size)


@router.get("/reports/{report_id}", response_model=ReportOut, tags=["reports"], summary="A single report with full content")
async def get_report(report_id: int, principal: Principal = Depends(get_principal), db: AsyncSession = Depends(get_db)) -> ReportOut:
    report = await db.scalar(select(IntelligenceReport).where(IntelligenceReport.id == report_id, IntelligenceReport.organisation_id == principal.organisation_id))
    if report is None:
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": "Report not found."})
    return _report_out(report, with_content=True)


@router.delete("/reports/{report_id}", status_code=204, tags=["reports"], summary="Delete a report")
async def delete_report(report_id: int, principal: Principal = Depends(require_analyst), db: AsyncSession = Depends(get_db)) -> None:
    report = await db.scalar(select(IntelligenceReport).where(IntelligenceReport.id == report_id, IntelligenceReport.organisation_id == principal.organisation_id))
    if report is None:
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": "Report not found."})
    await db.delete(report)
    await db.commit()


@router.get("/reports-capabilities", tags=["reports"], summary="Which AI provider (if any) will enrich reports")
async def capabilities(principal: Principal = Depends(get_principal), db: AsyncSession = Depends(get_db)) -> dict:
    from app.config import get_settings

    settings = get_settings()
    plan = await org_plan(db, principal.organisation_id)
    return {
        "rules_engine": True,
        "llm_provider": settings.llm_provider if settings.llm_configured else None,
        "llm_configured": settings.llm_configured,
        "ai_enrichment_in_plan": plan.ai_enrichment,
        "setup_hint": None if settings.llm_configured else "Set LLM_PROVIDER and the matching API key to add AI interpretations. Reports are complete without it.",
    }
