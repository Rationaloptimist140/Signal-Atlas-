"""Operational CLI: ``python -m app.cli <command>``.

Commands: init-db | demo-load | demo-clear | discover [query] | sync <owner/name> | recompute | run-jobs
"""

import asyncio
import sys

from sqlalchemy import func, select

from app.config import get_settings
from app.database import dispose_engine, get_engine, get_sessionmaker
from app.logging_config import configure_logging
from app.models import Base, Repository
from app.services import demo, ingestion, intelligence, jobs, trends
from app.services.github_client import GitHubClient


async def _run(argv: list[str]) -> int:
    configure_logging(get_settings().log_level, json_logs=False)
    command = argv[0] if argv else "help"
    if command == "init-db":
        # Development convenience only. Production schemas are managed by Alembic (alembic upgrade head).
        async with get_engine().begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        print("tables created")
        return 0
    async with get_sessionmaker()() as session:
        if command == "demo-load":
            print(await demo.load_demo(session))
        elif command == "demo-clear":
            print({"removed_repositories": await demo.clear_demo(session)})
        elif command == "discover":
            async with GitHubClient() as client:
                queries = [" ".join(argv[1:])] if len(argv) > 1 else [ingestion.render_query(t) for _, t in ingestion.DISCOVERY_QUERIES]
                for query in queries:
                    repos, total = await ingestion.discover_repositories(session, client, query, per_page=30)
                    print(f"{len(repos):>3} stored ({total:,} on GitHub)  {query}")
                    if len(queries) > 1:
                        await asyncio.sleep(7)  # stay under the anonymous search limit (10/min)
            print(await intelligence.recompute_intelligence(session))
            print(await trends.detect_trends(session))
        elif command == "sync" and len(argv) > 1:
            async with GitHubClient() as client:
                repo = await session.scalar(select(Repository).where(func.lower(Repository.full_name) == argv[1].lower()))
                if repo is None:
                    repo = await ingestion.track_repository(session, client, argv[1])
                print(await ingestion.full_sync_repository(session, client, repo, force=True))
            print(await intelligence.recompute_intelligence(session, [repo.id]))
        elif command == "recompute":
            print(await intelligence.recompute_intelligence(session))
            print(await trends.detect_trends(session))
        elif command == "run-jobs":
            print({"jobs_run": await jobs.run_pending(session, limit=200)})
        else:
            print(__doc__)
            return 1
    return 0


async def _main(argv: list[str]) -> int:
    try:
        return await _run(argv)
    finally:
        await dispose_engine()


def main() -> None:
    sys.exit(asyncio.run(_main(sys.argv[1:])))


if __name__ == "__main__":
    main()
