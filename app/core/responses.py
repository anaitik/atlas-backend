"""
Canonical response builders for the SustainabilityAI platform.
All API responses MUST use these envelopes — no domain pack alternatives.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional, TypeVar, Generic, List

from fastapi import Request
from pydantic import BaseModel, Field

T = TypeVar("T")


# ── Pydantic Schemas ─────────────────────────────────────────────

class RequestMeta(BaseModel):
    """Metadata attached to every API response."""
    request_id: str = ""
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class SuccessResponse(BaseModel, Generic[T]):
    """Standard success response wrapper."""
    success: bool = True
    data: T
    meta: RequestMeta = Field(default_factory=RequestMeta)


class ErrorDetail(BaseModel):
    field: Optional[str] = None
    issue: str = ""


class ApiErrorBody(BaseModel):
    code: str
    message: str
    details: List[ErrorDetail] = []


class ErrorResponse(BaseModel):
    """Standard error response wrapper."""
    success: bool = False
    error: ApiErrorBody
    meta: RequestMeta = Field(default_factory=RequestMeta)


class PaginationMeta(BaseModel):
    """Pagination metadata."""
    page: int
    page_size: int
    total: int
    has_next: bool


class PaginatedSuccessResponse(BaseModel, Generic[T]):
    """Paginated response wrapper."""
    success: bool = True
    data: List[T] = []
    pagination: PaginationMeta
    meta: RequestMeta = Field(default_factory=RequestMeta)


# ── Builder Helpers ──────────────────────────────────────────────

def build_meta(request: Optional[Request] = None) -> dict[str, Any]:
    """Extract meta from request context."""
    request_id = ""
    if request and hasattr(request.state, "request_id"):
        request_id = request.state.request_id
    return {
        "request_id": request_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def api_response(
    data: Any,
    request: Optional[Request] = None,
) -> dict[str, Any]:
    """Wrap any payload in ApiEnvelope."""
    return {
        "success": True,
        "data": data,
        "meta": build_meta(request),
    }


def paginated_response(
    items: list[Any],
    total: int,
    page: int,
    page_size: int,
    request: Optional[Request] = None,
) -> dict[str, Any]:
    """Wrap a list and pagination metadata in PaginatedResponse."""
    return {
        "success": True,
        "data": items,
        "pagination": {
            "page": page,
            "page_size": page_size,
            "total": total,
            "has_next": (page * page_size) < total,
        },
        "meta": build_meta(request),
    }
