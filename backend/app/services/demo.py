"""Demonstration fixtures.

Every project, developer and number below is **fictional** and stored with
``data_source = 'demo_fixture'``. Fixtures exist so the product can be explored before live
GitHub data is synced; the API and UI label them as demo data everywhere and they carry no
GitHub links. They are never mixed into live rankings (peer comparisons are per data source).
"""

import datetime as dt
import random

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    ChangeEvent,
    CommitActivity,
    Contributor,
    DataSource,
    Dependency,
    DeveloperProfile,
    ForkRelationship,
    IntelligenceReport,
    Language,
    Release,
    Repository,
    RepositoryLanguage,
    RepositorySnapshot,
    TrendSignal,
    WatchlistItem,
    utcnow,
)
from app.services import intelligence, trends
from app.services.ingestion import apply_classification

DEMO = DataSource.DEMO.value
NOTE = " (Demonstration fixture - not a real project.)"

# (owner, name, description, topics, language, licence, stars, age_days, profile, owner_type)
# profile: steady | surging | breakout | cooling
FIXTURES: list[tuple] = [
    ("demo-labs", "lumen-agents", "Framework for building multi-agent LLM workflows with tool use and memory", ["ai-agents", "llm", "agentic", "self-hosted"], "Python", "MIT", 18400, 210, "surging", "Organization"),
    ("demo-labs", "vectorloom", "Embeddable vector database for semantic search and RAG pipelines", ["vector-database", "rag", "embeddings", "database"], "Rust", "Apache-2.0", 9200, 520, "steady", "Organization"),
    ("demo-ai", "promptforge", "Evaluation and regression testing toolkit for LLM applications", ["llm", "llmops", "testing", "developer-tools"], "TypeScript", "MIT", 3100, 95, "breakout", "User"),
    ("demo-fin", "ledgerleaf", "Double-entry accounting ledger API for SaaS platforms", ["accounting", "ledger", "fintech", "api"], "Go", "Apache-2.0", 4300, 760, "steady", "Organization"),
    ("demo-fin", "payrail", "Payment orchestration layer with retries, routing and reconciliation", ["payments", "fintech", "billing", "enterprise"], "Java", "AGPL-3.0", 2700, 430, "surging", "Organization"),
    ("demo-fin", "quantbench", "Backtesting engine for systematic trading strategies", ["backtesting", "trading", "quant"], "Python", "GPL-3.0", 1500, 1300, "cooling", "User"),
    ("demo-chain", "blockquill", "Smart contract testing and deployment toolkit", ["smart-contracts", "solidity", "ethereum", "developer-tools"], "TypeScript", "MIT", 5200, 980, "cooling", "Organization"),
    ("demo-chain", "zkharbor", "Zero-knowledge proof circuits library for rollups", ["zero-knowledge", "rollup", "blockchain", "cryptography"], "Rust", "Apache-2.0", 2100, 300, "steady", "Organization"),
    ("demo-chain", "nodewarden", "Monitoring agent for blockchain validator nodes", ["blockchain", "monitoring", "web3"], "Go", "MIT", 800, 640, "steady", "User"),
    ("demo-dev", "forgecli", "Fast polyglot build tool and task runner for monorepos", ["build-tool", "developer-tools", "cli", "monorepo"], "Rust", "MIT", 14800, 880, "steady", "Organization"),
    ("demo-dev", "tracepilot", "OpenTelemetry-native observability platform you can self-host", ["observability", "opentelemetry", "monitoring", "self-hosted"], "Go", "AGPL-3.0", 11200, 610, "surging", "Organization"),
    ("demo-dev", "apiloom", "Design-first API gateway with OpenAPI validation", ["api-gateway", "openapi", "api", "cloud-native"], "Go", "Apache-2.0", 3900, 400, "steady", "Organization"),
    ("demo-sec", "vaultwisp", "Lightweight secrets management for small engineering teams", ["secrets-management", "security", "encryption", "self-hosted"], "Go", "MPL-2.0", 6100, 700, "steady", "Organization"),
    ("demo-sec", "scanhound", "Vulnerability scanner for container images and dependencies", ["vulnerability-scanner", "security", "docker", "security-tools"], "Go", "Apache-2.0", 8700, 1150, "steady", "Organization"),
    ("demo-sec", "gatekeep", "Open-source single sign-on and passkey authentication server", ["sso", "authentication", "passkeys", "identity", "enterprise"], "TypeScript", "MIT", 4600, 260, "surging", "Organization"),
    ("demo-auto", "flowmill", "Visual workflow automation engine with 200+ connectors", ["workflow-automation", "automation", "low-code", "self-hosted"], "TypeScript", "BUSL-1.1", 21500, 1400, "steady", "Organization"),
    ("demo-auto", "crawlkit", "Browser automation and scraping toolkit driven by LLM agents", ["browser-automation", "web-scraping", "ai-agents", "playwright"], "Python", "MIT", 7400, 110, "breakout", "User"),
    ("demo-auto", "taskrelay", "Distributed job scheduler with durable execution", ["job-scheduler", "workflow-engine", "orchestration"], "Go", "Apache-2.0", 2900, 820, "cooling", "Organization"),
    ("demo-cloud", "kubelantern", "Cost visibility and rightsizing for Kubernetes clusters", ["kubernetes", "cloud-native", "finops", "monitoring"], "Go", "Apache-2.0", 5600, 560, "steady", "Organization"),
    ("demo-cloud", "terraweave", "Policy-as-code checks for Terraform plans", ["terraform", "infrastructure-as-code", "compliance", "security"], "Go", "MPL-2.0", 3300, 900, "steady", "Organization"),
    ("demo-cloud", "edgeburst", "WebAssembly runtime for edge functions", ["webassembly", "wasm", "serverless", "edge-computing"], "Rust", "Apache-2.0", 4800, 190, "surging", "Organization"),
    ("demo-data", "streamquarry", "Change-data-capture pipelines from Postgres to anywhere", ["cdc", "data-pipeline", "postgres", "streaming"], "Java", "Apache-2.0", 6900, 730, "steady", "Organization"),
    ("demo-data", "tidepool-db", "Serverless Postgres-compatible database with branching", ["database", "postgres", "serverless", "cloud"], "Rust", "Apache-2.0", 12600, 450, "surging", "Organization"),
    ("demo-data", "chartwell", "Embedded product analytics for SaaS applications", ["product-analytics", "analytics", "self-hosted", "saas"], "TypeScript", "AGPL-3.0", 3700, 380, "steady", "Organization"),
    ("demo-biz", "deskharbor", "Open-source helpdesk and shared inbox for support teams", ["helpdesk", "customer-support", "self-hosted", "team"], "Ruby", "AGPL-3.0", 9800, 1600, "steady", "Organization"),
    ("demo-biz", "wikigrove", "Team knowledge base with real-time collaboration", ["knowledge-base", "wiki", "collaboration", "self-hosted"], "TypeScript", "MIT", 7300, 990, "cooling", "Organization"),
    ("demo-biz", "cartwright", "Headless commerce engine for B2B wholesalers", ["ecommerce", "headless-cms", "b2b", "api"], "PHP", None, 1900, 340, "steady", "User"),
]

PROFILE_GROWTH = {"steady": 0.0012, "surging": 0.009, "breakout": 0.02, "cooling": 0.0002}  # daily star growth rate
DEPENDENCIES = {
    "Python": ("pypi", ["fastapi", "pydantic", "httpx", "numpy", "sqlalchemy", "openai", "tiktoken"]),
    "TypeScript": ("npm", ["react", "next", "zod", "typescript", "express", "prisma", "vitest"]),
    "Go": ("go", ["github.com/spf13/cobra", "google.golang.org/grpc", "github.com/prometheus/client_golang", "go.uber.org/zap"]),
    "Rust": ("cargo", ["tokio", "serde", "clap", "axum", "tracing"]),
    "Java": ("npm", []),
    "Ruby": ("npm", ["stimulus", "tailwindcss"]),
    "PHP": ("npm", ["vue", "vite"]),
}


async def clear_demo(session: AsyncSession) -> int:
    """Remove every demo fixture and anything derived from it."""
    repo_ids = list((await session.scalars(select(Repository.id).where(Repository.data_source == DEMO))).all())
    dev_ids = list((await session.scalars(select(DeveloperProfile.id).where(DeveloperProfile.data_source == DEMO))).all())
    if repo_ids:
        await session.execute(delete(WatchlistItem).where(WatchlistItem.item_type == "repository", WatchlistItem.item_id.in_(repo_ids)))
    if dev_ids:
        await session.execute(delete(WatchlistItem).where(WatchlistItem.item_type == "developer", WatchlistItem.item_id.in_(dev_ids)))
    await session.execute(delete(TrendSignal).where(TrendSignal.data_source == DEMO))
    await session.execute(delete(ChangeEvent).where(ChangeEvent.data_source == DEMO))
    await session.execute(delete(IntelligenceReport).where(IntelligenceReport.data_source == DEMO))
    await session.execute(delete(Repository).where(Repository.data_source == DEMO))  # children cascade
    await session.execute(delete(DeveloperProfile).where(DeveloperProfile.data_source == DEMO))
    await session.commit()
    return len(repo_ids)


async def load_demo(session: AsyncSession, now: dt.datetime | None = None) -> dict:
    """(Re)load the fictional fixtures, then score them and detect trends."""
    await clear_demo(session)
    now = now or utcnow()
    today = now.date()
    rng = random.Random(20261110)

    developers: list[DeveloperProfile] = []
    for index in range(1, 37):
        dev = DeveloperProfile(
            login=f"demo-dev-{index:02d}", name=f"Demo Developer {index:02d}", account_type="User", bio="Fictional profile used for demonstration.",
            followers=rng.randint(20, 4000), following=rng.randint(5, 300), public_repos=rng.randint(4, 80),
            created_at_github=now - dt.timedelta(days=rng.randint(400, 4000)), data_source=DEMO, sync_level="full", last_synced_at=now, inferred={})
        session.add(dev)
        developers.append(dev)
    await session.flush()

    languages: dict[str, Language] = {lang.name: lang for lang in (await session.scalars(select(Language))).all()}
    repo_ids: list[int] = []
    for owner, name, description, topics, language, licence, stars, age_days, profile, owner_type in FIXTURES:
        rate = PROFILE_GROWTH[profile]
        repo = Repository(
            full_name=f"{owner}/{name}", owner_login=owner, owner_type=owner_type, name=name, description=description + NOTE,
            html_url=None, homepage="https://example.com" if owner_type == "Organization" else None, primary_language=language,
            license_spdx=licence, license_name=licence, topics=topics, stars=stars, forks=max(int(stars * rng.uniform(0.05, 0.14)), 3),
            watchers=max(int(stars * rng.uniform(0.008, 0.02)), 2), open_issues=rng.randint(12, 420), closed_issues=rng.randint(80, 4200),
            open_prs=rng.randint(2, 60), merged_prs=rng.randint(60, 3800), contributors_count=rng.randint(4, 260) if profile != "breakout" else rng.randint(3, 25),
            size_kb=rng.randint(800, 90000), is_fork=False, archived=False, default_branch="main",
            created_at_github=now - dt.timedelta(days=age_days),
            pushed_at_github=now - dt.timedelta(days=(rng.randint(40, 120) if profile == "cooling" else rng.randint(0, 3))),
            updated_at_github=now, data_source=DEMO, sync_level="full", missing_data=[], last_synced_at=now)
        session.add(repo)
        await session.flush()
        repo_ids.append(repo.id)
        await apply_classification(session, repo)

        if language not in languages:
            languages[language] = Language(name=language)
            session.add(languages[language])
            await session.flush()
        session.add(RepositoryLanguage(repository_id=repo.id, language_id=languages[language].id, byte_count=rng.randint(200_000, 4_000_000)))

        # 36 daily snapshots ending today, compounding at the profile's rate (with small noise)
        value = float(stars)
        series = []
        for back in range(0, 36):
            series.append((today - dt.timedelta(days=back), int(value)))
            value /= 1.0 + rate * rng.uniform(0.6, 1.4)
        contributors_now = repo.contributors_count or 0
        for back, (day, star_value) in enumerate(series):
            contributors_then = max(int(contributors_now / (1.0 + (0.006 if profile in ("surging", "breakout") else 0.0008) * back)), 1)
            session.add(RepositorySnapshot(repository_id=repo.id, captured_on=day, captured_at=now - dt.timedelta(days=back), stars=star_value,
                                           forks=repo.forks, watchers=repo.watchers, open_issues=repo.open_issues, contributors_count=contributors_then))

        # 26 weeks of commit activity; surging/breakout accelerate, cooling fades
        base = rng.randint(8, 60)
        monday = today - dt.timedelta(days=today.weekday())
        for back in range(25, -1, -1):
            factor = {"steady": 1.0, "surging": 1.0 + max(0, 6 - back) * 0.35, "breakout": 0.3 + max(0, 12 - back) * 0.25, "cooling": 0.15 + back * 0.04}[profile]
            if age_days < back * 7:
                continue
            session.add(CommitActivity(repository_id=repo.id, week_start=monday - dt.timedelta(weeks=back), commits=max(int(base * factor * rng.uniform(0.7, 1.3)), 0)))

        release_count = {"steady": 6, "surging": 9, "breakout": 5, "cooling": 2}[profile]
        for index in range(release_count):
            days_ago = (index * (9 if profile in ("surging", "breakout") else 40)) + rng.randint(1, 6) + (90 if profile == "cooling" else 0)
            if days_ago < age_days:
                session.add(Release(repository_id=repo.id, tag_name=f"v{release_count - index}.{rng.randint(0, 9)}.0", name=f"Release {release_count - index}",
                                    published_at=now - dt.timedelta(days=days_ago), prerelease=False, body_excerpt="Fictional release notes for demonstration."))

        team = rng.sample(developers, k=rng.randint(3, 7))
        lead_share = rng.choice([900, 400, 250])
        for position, dev in enumerate(team):
            session.add(Contributor(repository_id=repo.id, developer_id=dev.id, contributions=lead_share if position == 0 else rng.randint(8, 180)))

        ecosystem, packages = DEPENDENCIES.get(language, ("npm", []))
        for package in rng.sample(packages, k=min(len(packages), rng.randint(2, 5))):
            session.add(Dependency(repository_id=repo.id, ecosystem=ecosystem, package_name=package, version_spec=None, dep_type="runtime", manifest_path="(demo)"))
        for index in range(rng.randint(1, 3)):
            session.add(ForkRelationship(parent_repository_id=repo.id, fork_full_name=f"demo-fork-{index + 1}/{name}", stars=rng.randint(0, 90),
                                         pushed_at=now - dt.timedelta(days=rng.randint(1, 200)), created_at_github=now - dt.timedelta(days=rng.randint(10, max(age_days - 1, 11)))))
        if profile in ("surging", "breakout"):
            session.add(ChangeEvent(dedupe_key=f"{repo.id}:release:demo", repository_id=repo.id, event_type="release", title=f"{repo.full_name} released a new version",
                                    details={"notes_excerpt": "Fictional release notes for demonstration."}, data_source=DEMO, occurred_at=now - dt.timedelta(days=rng.randint(1, 6))))

    await session.commit()
    summary = await intelligence.recompute_intelligence(session, repo_ids, now)
    summary.update(await trends.detect_trends(session, now))
    summary["repositories"] = len(repo_ids)
    summary["developers"] = len(developers)
    return summary
