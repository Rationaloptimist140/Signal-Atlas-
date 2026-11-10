"""Background worker: ``python -m app.worker``. Runs queued jobs and schedules recurring ones."""

import asyncio
import signal

from app.config import get_settings
from app.database import dispose_engine, get_sessionmaker
from app.logging_config import configure_logging, get_logger
from app.services import jobs

log = get_logger("worker")


async def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level, json_logs=settings.app_env == "production")
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:  # Windows
            pass
    log.info("worker_started", poll_seconds=settings.worker_poll_seconds)
    last_schedule = 0.0
    while not stop.is_set():
        try:
            async with get_sessionmaker()() as session:
                if loop.time() - last_schedule > 300:
                    await jobs.schedule_recurring(session)
                    last_schedule = loop.time()
                ran = await jobs.run_pending(session, limit=20)
        except Exception as exc:  # noqa: BLE001 - keep the worker alive through transient DB errors
            log.error("worker_loop_error", error=f"{type(exc).__name__}: {exc}")
            ran = 0
        if ran == 0:
            try:
                await asyncio.wait_for(stop.wait(), timeout=settings.worker_poll_seconds)
            except TimeoutError:
                pass
    await dispose_engine()
    log.info("worker_stopped")


if __name__ == "__main__":
    asyncio.run(main())
