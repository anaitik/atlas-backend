"""
Canonical error handling for the SustainabilityAI platform.
All domain packs MUST use these error types — no local redefinitions.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Optional

from fastapi import Request
from fastapi.responses import JSONResponse


# ── Error Codes (stable uppercase constants) ─────────────────────
class ErrorCode(str, Enum):
    BAD_REQUEST = "BAD_REQUEST"
    VALIDATION_ERROR = "VALIDATION_ERROR"
    UNAUTHORIZED = "UNAUTHORIZED"
    FORBIDDEN = "FORBIDDEN"
    NOT_FOUND = "NOT_FOUND"
    CONFLICT = "CONFLICT"
    DEPENDENCY_FAILURE = "DEPENDENCY_FAILURE"
    INTERNAL_ERROR = "INTERNAL_ERROR"


# ── Error code to HTTP status mapping ────────────────────────────
ERROR_STATUS_MAP: dict[ErrorCode, int] = {
    ErrorCode.BAD_REQUEST: 400,
    ErrorCode.VALIDATION_ERROR: 422,
    ErrorCode.UNAUTHORIZED: 401,
    ErrorCode.FORBIDDEN: 403,
    ErrorCode.NOT_FOUND: 404,
    ErrorCode.CONFLICT: 409,
    ErrorCode.DEPENDENCY_FAILURE: 502,
    ErrorCode.INTERNAL_ERROR: 500,
}


# ── Application Exception ───────────────────────────────────────
class AppError(Exception):
    """
    Canonical application error. Raise this from any service or router.
    The global exception handler normalizes it into the ApiError envelope.
    """

    def __init__(
        self,
        code: ErrorCode,
        message: str,
        details: Optional[list[dict[str, Any]]] = None,
    ):
        self.code = code
        self.message = message
        self.details = details or []
        super().__init__(message)


# ── Exception Handlers (registered in main.py) ──────────────────
async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    """Normalize AppError into the shared error envelope."""
    from app.core.responses import build_meta

    status = ERROR_STATUS_MAP.get(exc.code, 500)
    return JSONResponse(
        status_code=status,
        content={
            "success": False,
            "error": {
                "code": exc.code.value,
                "message": exc.message,
                "details": exc.details,
            },
            "meta": build_meta(request),
        },
    )


async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """Catch-all for uncaught exceptions → INTERNAL_ERROR envelope."""
    import structlog

    logger = structlog.get_logger()
    logger.error("unhandled_exception", error=str(exc), exc_info=True)

    from app.core.responses import build_meta

    return JSONResponse(
        status_code=500,
        content={
            "success": False,
            "error": {
                "code": ErrorCode.INTERNAL_ERROR.value,
                "message": "An unexpected error occurred.",
                "details": [],
            },
            "meta": build_meta(request),
        },
    )
