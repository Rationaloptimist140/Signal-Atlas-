"""FastAPI application factory."""

import time
import uuid
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import func, select, text
from starlette.exceptions import HTTPException as StarletteHTTPException

from app import __version__
from app.config import get_settings
from app.database import get_sessionmaker
from app.logging_config import configure_logging, get_logger
from app.models import Repository
from app.routers import account, auth, competitors, dashboard, developers, opportunities, repositories, trends

log = get_logger("api")

DESCRIPTION = """
**SIGNAL ATLAS** turns public open-source activity into technology and commercial intelligence.

* Every intelligence object carries `data_source`: `live_github` (verified public GitHub data) or
  `demo_fixture` (fictional sample data). Use the `source` query parameter to choose.
* Authenticate with a session cookie (browser) or an API key: `X-API-Key: sa_live_...`.
* Scores are transparent heuristics with evidence and confidence, not predictions.
"""


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    configure_logging(settings.log_level, json_logs=settings.app_env == "production")
    if settings.seed_demo_data:
        from app.services import demo

        async with get_sessionmaker()() as session:
            if not await session.scalar(select(func.count()).select_from(Repository)):
                summary = await demo.load_demo(session)
                log.info("demo_fixtures_loaded", **summary)
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="SIGNAL ATLAS API", version=__version__, description=DESCRIPTION, lifespan=lifespan,
                  docs_url="/api/docs", redoc_url="/api/redoc", openapi_url="/api/openapi.json")
    app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origin_list, allow_credentials=True,
                       allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"], allow_headers=["Content-Type", "X-CSRF-Token", "X-API-Key", "Authorization"])

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        request_id = request.headers.get("x-request-id") or uuid.uuid4().hex[:16]
        structlog.contextvars.bind_contextvars(request_id=request_id)
        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            log.exception("unhandled_error", path=request.url.path, method=request.method)
            structlog.contextvars.clear_contextvars()
            return JSONResponse(status_code=500, content={"error": {"code": "internal_error", "message": "Something went wrong on our side.", "request_id": request_id}})
        duration_ms = round((time.perf_counter() - started) * 1000, 1)
        if request.url.path.startswith("/api/v1"):
            log.info("request", method=request.method, path=request.url.path, status=response.status_code, duration_ms=duration_ms)
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        if request.url.path.startswith("/api/v1"):
            response.headers["Cache-Control"] = "no-store"
        if settings.app_env == "production":
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        structlog.contextvars.clear_contextvars()
        return response

    @app.exception_handler(StarletteHTTPException)
    async def http_error(_request: Request, exc: StarletteHTTPException):
        detail = exc.detail if isinstance(exc.detail, dict) else {"code": "error", "message": str(exc.detail)}
        return JSONResponse(status_code=exc.status_code, content={"error": detail}, headers=getattr(exc, "headers", None))

    @app.exception_handler(RequestValidationError)
    async def validation_error(_request: Request, exc: RequestValidationError):
        fields = [{"field": ".".join(str(p) for p in err["loc"][1:]) or str(err["loc"][0]), "message": err["msg"].removeprefix("Value error, ")} for err in exc.errors()]
        message = fields[0]["message"] if len(fields) == 1 else "Some fields are invalid."
        return JSONResponse(status_code=422, content={"error": {"code": "validation_error", "message": message, "fields": fields}})

    @app.get("/health", tags=["system"], summary="Liveness probe")
    async def health() -> dict:
        return {"status": "ok", "version": __version__}

    @app.get("/health/ready", tags=["system"], summary="Readiness probe (checks the database)")
    async def ready():
        try:
            async with get_sessionmaker()() as session:
                await session.execute(text("SELECT 1"))
        except Exception:  # noqa: BLE001
            return JSONResponse(status_code=503, content={"status": "unavailable", "database": False})
        return {"status": "ready", "database": True}

    for router in (auth.router, repositories.router, developers.router, trends.router, opportunities.router, competitors.router, dashboard.router, account.router):
        app.include_router(router, prefix="/api/v1")
    return app


app = create_app()
