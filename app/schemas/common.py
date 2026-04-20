"""
Pydantic schemas for common API shapes.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field


# ── Health ───────────────────────────────────────────────────────
class HealthResponse(BaseModel):
    status: str = "ok"
    version: str = ""
    environment: str = ""
    database: str = "unknown"


# ── Audit ────────────────────────────────────────────────────────
class AuditEventOut(BaseModel):
    id: str
    event_type: str
    actor_user_id: Optional[str] = None
    company_id: Optional[str] = None
    workspace_id: Optional[str] = None
    entity_table: Optional[str] = None
    entity_id: Optional[str] = None
    payload: dict[str, Any] = {}
    created_at: datetime


# ── Notification ─────────────────────────────────────────────────
class NotificationOut(BaseModel):
    id: str
    event_type: str
    title: str
    body: str = ""
    resource_url: Optional[str] = None
    read_at: Optional[datetime] = None
    created_at: datetime


class MarkReadRequest(BaseModel):
    notification_id: str
