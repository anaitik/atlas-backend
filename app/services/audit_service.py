"""
Audit service — append-only event writer.
Owned by Pack 03. Domain packs call this to record material state changes.
"""

from __future__ import annotations

from typing import Any, Optional

import structlog

from app.models.audit_event import AuditEvent

logger = structlog.get_logger()


async def emit(
    event_type: str,
    actor_user_id: Optional[str] = None,
    company_id: Optional[str] = None,
    workspace_id: Optional[str] = None,
    entity_table: Optional[str] = None,
    entity_id: Optional[str] = None,
    payload: Optional[dict[str, Any]] = None,
) -> AuditEvent:
    """
    Write an immutable audit event.
    This is INSERT-ONLY — never update or delete audit rows.
    """
    event = AuditEvent(
        event_type=event_type,
        actor_user_id=actor_user_id,
        company_id=company_id,
        workspace_id=workspace_id,
        entity_table=entity_table,
        entity_id=entity_id,
        payload=payload or {},
    )
    await event.insert()

    logger.info(
        "audit_event_emitted",
        event_type=event_type,
        actor=actor_user_id,
        entity=f"{entity_table}:{entity_id}",
        company_id=company_id,
    )

    return event


async def get_audit_log(
    company_id: Optional[str] = None,
    workspace_id: Optional[str] = None,
    entity_table: Optional[str] = None,
    entity_id: Optional[str] = None,
    page: int = 1,
    page_size: int = 50,
) -> tuple[list[AuditEvent], int]:
    """Query audit events with filters and pagination."""
    filters: dict[str, Any] = {}
    if company_id:
        filters["company_id"] = company_id
    if workspace_id:
        filters["workspace_id"] = workspace_id
    if entity_table:
        filters["entity_table"] = entity_table
    if entity_id:
        filters["entity_id"] = entity_id

    skip = (page - 1) * page_size
    total = await AuditEvent.find(filters).count()
    items = await (
        AuditEvent.find(filters)
        .sort("-created_at")
        .skip(skip)
        .limit(page_size)
        .to_list()
    )
    return items, total
