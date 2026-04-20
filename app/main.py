"""
SustainabilityAI Backend — FastAPI Application Factory.
"""

from __future__ import annotations

from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import get_settings
from app.core.errors import AppError, app_error_handler, unhandled_error_handler
from app.core.logging import setup_logging
from app.core.responses import api_response
from app.core.security_headers import SecurityHeadersMiddleware
from app.db.session import connect_db, close_db
from app.observability import RequestContextMiddleware
from app.schemas.common import HealthResponse

logger = structlog.get_logger()


# ── Lifespan ─────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup and shutdown."""
    setup_logging()
    logger.info("starting_application", app=settings.APP_NAME, env=settings.ENVIRONMENT.value)

    # Connect to MongoDB
    await connect_db()
    logger.info("database_connected", db=settings.MONGODB_DATABASE_NAME)

    yield

    # Shutdown
    await close_db()
    logger.info("application_shutdown")


settings = get_settings()

# ── App Factory ──────────────────────────────────────────────────
app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    docs_url="/docs" if settings.DEBUG else None,
    redoc_url="/redoc" if settings.DEBUG else None,
    openapi_url="/openapi.json",
    lifespan=lifespan,
)

# ── Middleware Stack (order matters — last added = first executed) ─
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(RequestContextMiddleware)

# ── Exception Handlers ──────────────────────────────────────────
app.add_exception_handler(AppError, app_error_handler)
app.add_exception_handler(Exception, unhandled_error_handler)

# ── API Routes ──────────────────────────────────────────────────
from app.api.v1.router import api_router
app.include_router(api_router, prefix=settings.API_V1_PREFIX)


# ── Health Endpoints ─────────────────────────────────────────────
@app.get("/health", tags=["Platform"])
async def health(request: Request):
    """Basic health check — always responds if the process is alive."""
    return api_response(
        data=HealthResponse(
            status="ok",
            version=settings.APP_VERSION,
            environment=settings.ENVIRONMENT.value,
        ).model_dump(),
        request=request,
    )


@app.get("/ready", tags=["Platform"])
async def readiness(request: Request):
    """
    Readiness probe — verifies database connectivity.
    Returns degraded status if DB is unreachable.
    """
    db_status = "unknown"
    try:
        from app.db.session import get_client
        client = get_client()
        await client.admin.command("ping")
        db_status = "connected"
    except Exception as e:
        db_status = f"error: {str(e)}"

    return api_response(
        data=HealthResponse(
            status="ready" if db_status == "connected" else "degraded",
            version=settings.APP_VERSION,
            environment=settings.ENVIRONMENT.value,
            database=db_status,
        ).model_dump(),
        request=request,
    )


@app.get(f"{settings.API_V1_PREFIX}/ping", tags=["Platform"])
async def ping(request: Request):
    """Simple versioned API ping."""
    return api_response(data={"message": "pong"}, request=request)
