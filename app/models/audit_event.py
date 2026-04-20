"""
Audit Event document — append-only, never updated or deleted.
Owned by Pack 03.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from beanie import Document
from pydantic import Field
from pymongo import IndexModel
from uuid import uuid4


class AuditEvent(Document):
    """
    Immutable audit trail entry.
    Every material state change in the platform writes one of these.
    Rows are NEVER updated or deleted.
    """

    id: str = Field(default_factory=lambda: str(uuid4()))
    event_type: str                             # e.g. "USER_APPROVED", "BATCH_CREATED"
    actor_user_id: Optional[str] = None         # Who triggered it
    company_id: Optional[str] = None            # Tenant scope
    workspace_id: Optional[str] = None          # Workspace scope (if applicable)
    entity_table: Optional[str] = None          # e.g. "users", "batch_runs"
    entity_id: Optional[str] = None             # ID of the affected entity
    payload: dict[str, Any] = Field(default_factory=dict)  # Event-specific data (JSONB equiv)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    class Settings:
        name = "audit_events"
        indexes = [
            IndexModel([("company_id", 1), ("created_at", -1)]),
            IndexModel([("entity_table", 1), ("entity_id", 1), ("created_at", -1)]),
            IndexModel([("event_type", 1), ("created_at", -1)]),
        ]
