"""Developer Intelligence (Engine 2). Public profile data only; inferred fields are labelled."""

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.deps import Principal, get_principal, require_verified_analyst
from app.models import Contributor, DataSource, DeveloperProfile, Repository, utcnow
from app.routers.common import SourceParam, like_pattern, paginate, resolve_source, source_query
from app.schemas import DeveloperListItem, DeveloperOut, Page
from app.services import jobs
from app.services.usage import enforce_monthly_limit, record_usage
from app.taxonomy import CATEGORIES

router = APIRouter(prefix="/developers", tags=["developers"])

INFLUENCE_DISCLAIMER = (
    "Influence indicators describe public visibility (followers, stars on projects contributed to). "
    "They are not a measure of technical ability, and many excellent engineers have little public activity."
)


async def _footprint(db: AsyncSession, developer_ids: list[int]) -> dict[int, dict]:
    """Per-developer footprint across *tracked* repositories."""
    if not developer_ids:
        return {}
    rows = (await db.execute(
        select(Contributor.developer_id, Repository.id, Repository.full_name, Repository.primary_language, Repository.category, Repository.stars, Repository.owner_login,
               Contributor.contributions)
        .join(Repository, Repository.id == Contributor.repository_id).where(Contributor.developer_id.in_(developer_ids)))).all()
    out: dict[int, dict] = {i: {"repositories": [], "languages": {}, "categories": {}, "contributions": 0} for i in developer_ids}
    for dev_id, repo_id, full_name, language, category, stars, owner, contributions in rows:
        entry = out[dev_id]
        entry["repositories"].append({"repository_id": repo_id, "full_name": full_name, "primary_language": language, "category": category, "stars": stars,
                                      "contributions": contributions, "owner_login": owner})
        entry["contributions"] += contributions
        if language:
            entry["languages"][language] = entry["languages"].get(language, 0) + contributions
        if category:
            entry["categories"][category] = entry["categories"].get(category, 0) + contributions
    return out


@router.get("", response_model=Page[DeveloperListItem], summary="Developers contributing to tracked repositories")
async def list_developers(
    q: str | None = Query(None, max_length=100),
    language: str | None = Query(None, max_length=80, description="Has contributed to a tracked repository in this language"),
    sort: Literal["tracked_contributions", "followers", "login", "emerging"] = "tracked_contributions",
    source: SourceParam = source_query(),
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    principal: Principal = Depends(get_principal),
    db: AsyncSession = Depends(get_db),
) -> Page[DeveloperListItem]:
    contributions = func.coalesce(func.sum(Contributor.contributions), 0)
    repo_count = func.count(func.distinct(Contributor.repository_id))
    query = select(DeveloperProfile, contributions.label("contributions"), repo_count.label("repos")) \
        .outerjoin(Contributor, Contributor.developer_id == DeveloperProfile.id).group_by(DeveloperProfile.id)
    data_source = await resolve_source(db, source)
    if data_source:
        query = query.where(DeveloperProfile.data_source == data_source)
    if q:
        pattern = like_pattern(q.strip())
        query = query.where(or_(DeveloperProfile.login.ilike(pattern, escape="\\"), DeveloperProfile.name.ilike(pattern, escape="\\")))
    if language:
        query = query.where(DeveloperProfile.id.in_(
            select(Contributor.developer_id).join(Repository, Repository.id == Contributor.repository_id).where(func.lower(Repository.primary_language) == language.lower())))
    if sort == "followers":
        query = query.order_by(DeveloperProfile.followers.desc().nulls_last(), DeveloperProfile.id)
    elif sort == "login":
        query = query.order_by(func.lower(DeveloperProfile.login))
    elif sort == "emerging":
        # Emerging = newer public accounts already contributing heavily to tracked projects.
        query = query.where(DeveloperProfile.created_at_github.is_not(None)).order_by(DeveloperProfile.created_at_github.desc(), contributions.desc())
    else:
        query = query.order_by(contributions.desc(), DeveloperProfile.id)
    rows, total = await paginate(db, query, page, page_size)
    footprints = await _footprint(db, [r[0].id for r in rows])
    items = []
    for dev, contribution_total, repos in rows:
        item = DeveloperListItem.model_validate(dev)
        item.tracked_contributions, item.tracked_repositories = int(contribution_total or 0), int(repos or 0)
        item.top_languages = [name for name, _ in sorted(footprints[dev.id]["languages"].items(), key=lambda kv: -kv[1])[:3]]
        items.append(item)
    return Page[DeveloperListItem](items=items, total=total, page=page, page_size=page_size)


@router.get("/{developer_id}", summary="Developer profile with public data and labelled inferences")
async def get_developer(developer_id: int, principal: Principal = Depends(get_principal), db: AsyncSession = Depends(get_db)) -> dict:
    dev = await db.get(DeveloperProfile, developer_id)
    if dev is None:
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": "Developer not found."})
    footprint = (await _footprint(db, [dev.id]))[dev.id]
    repos = sorted(footprint["repositories"], key=lambda r: -r["contributions"])
    total = footprint["contributions"] or 1
    repo_ids = [r["repository_id"] for r in repos]
    collaborators = []
    if repo_ids:
        rows = (await db.execute(
            select(DeveloperProfile.id, DeveloperProfile.login, DeveloperProfile.avatar_url, func.count(func.distinct(Contributor.repository_id)).label("shared"))
            .join(Contributor, Contributor.developer_id == DeveloperProfile.id)
            .where(Contributor.repository_id.in_(repo_ids), DeveloperProfile.id != dev.id)
            .group_by(DeveloperProfile.id).order_by(func.count(func.distinct(Contributor.repository_id)).desc(), DeveloperProfile.login).limit(12))).all()
        collaborators = [{"developer_id": i, "login": login, "avatar_url": avatar, "shared_repositories": shared} for i, login, avatar, shared in rows]
    owned = [r for r in repos if r["owner_login"].lower() == dev.login.lower()]
    account_age_days = (utcnow() - dev.created_at_github).days if dev.created_at_github else None
    return {
        "public_profile": {"basis": "public_data", "source": "GitHub public profile", "developer": DeveloperOut.model_validate(dev),
                           "note": "Only fields the developer has made public on GitHub are stored. E-mail addresses are never collected."},
        "contribution_activity": {"basis": "public_data", "repositories": repos, "tracked_contributions": footprint["contributions"],
                                  "note": "Commit counts to repositories tracked by Signal Atlas, as reported by GitHub. Work in untracked or private repositories is not visible."},
        "owned_repositories": owned,
        "inferred": {
            "basis": "inferred_analysis",
            "languages": [{"language": name, "share": round(c / total, 3)} for name, c in sorted(footprint["languages"].items(), key=lambda kv: -kv[1])[:8]],
            "specialisations": [{"category": c, "label": CATEGORIES.get(c, c), "share": round(n / total, 3)} for c, n in sorted(footprint["categories"].items(), key=lambda kv: -kv[1])[:5]],
            "emerging": bool(account_age_days is not None and account_age_days < 730 and footprint["contributions"] >= 50),
            "note": "Inferred from the primary language and category of tracked repositories, weighted by commits. An approximation, not a skills assessment.",
        },
        "collaboration_network": {"basis": "inferred_analysis", "collaborators": collaborators,
                                  "note": "Developers who contribute to the same tracked repositories. Co-contribution does not imply they work together."},
        "influence_indicators": {
            "basis": "public_data", "followers": dev.followers, "public_repos": dev.public_repos,
            "stars_on_contributed_repositories": sum(r["stars"] for r in repos), "account_age_days": account_age_days,
            "disclaimer": INFLUENCE_DISCLAIMER,
        },
        "provenance": {"data_source": dev.data_source, "is_demo": dev.data_source == DataSource.DEMO.value, "sync_level": dev.sync_level, "last_synced_at": dev.last_synced_at},
    }


@router.post("/{developer_id}/sync", status_code=202, summary="Refresh a developer's public profile from GitHub")
async def sync_developer(developer_id: int, principal: Principal = Depends(require_verified_analyst), db: AsyncSession = Depends(get_db)) -> dict:
    dev = await db.get(DeveloperProfile, developer_id)
    if dev is None:
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": "Developer not found."})
    if dev.data_source == DataSource.DEMO.value:
        raise HTTPException(status_code=400, detail={"code": "demo_fixture", "message": "Demo fixtures are fictional and cannot be synced with GitHub."})
    await enforce_monthly_limit(db, principal.organisation_id, "live_syncs", "live_syncs_per_month", "live GitHub requests")
    await record_usage(db, principal.organisation_id, "live_syncs")
    job = await jobs.enqueue_and_maybe_run(db, "sync_developer", {"developer_id": dev.id, "user_id": principal.user_id}, dedupe_key=f"sync_developer:{dev.id}")
    return {"job_id": job.id, "status": job.status, "message": job.last_error or ("Profile refreshed." if job.status == "succeeded" else "Refresh queued.")}
