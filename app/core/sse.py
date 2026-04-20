"""
Canonical SSE (Server-Sent Events) envelope for the SustainabilityAI platform.
Domain packs own the payload structure; this module owns the outer wrapper.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from enum import Enum
from typing import Any, AsyncGenerator, Optional

from pydantic import BaseModel, Field


# ── SSE Event Types ──────────────────────────────────────────────
class SseEventType(str, Enum):
    QUEUED = "queued"
    STARTED = "started"
    PROGRESS = "progress"
    RECORD_COMPLETE = "record_complete"
    SECTION_COMPLETE = "section_complete"
    COMPLETED = "completed"
    FAILED = "failed"


# ── SSE Envelope ─────────────────────────────────────────────────
class SseEventEnvelope(BaseModel):
    """
    Canonical SSE event wrapper.
    Domain packs own 'payload'; this module owns everything else.
    """
    event_type: SseEventType
    entity_type: str              # e.g. "batch", "record", "metric_run", "report"
    entity_id: str
    sequence: int
    timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    payload: dict[str, Any] = {}


# ── Helpers ──────────────────────────────────────────────────────

def build_sse_event(
    event_type: SseEventType,
    entity_type: str,
    entity_id: str,
    sequence: int,
    payload: Optional[dict[str, Any]] = None,
) -> SseEventEnvelope:
    """Build a typed SSE event envelope."""
    return SseEventEnvelope(
        event_type=event_type,
        entity_type=entity_type,
        entity_id=entity_id,
        sequence=sequence,
        payload=payload or {},
    )


def format_sse(event: SseEventEnvelope) -> str:
    """Format an SSE envelope as a text/event-stream line."""
    data = event.model_dump_json()
    return f"event: {event.event_type.value}\ndata: {data}\n\n"


async def sse_stream(
    events: AsyncGenerator[SseEventEnvelope, None],
) -> AsyncGenerator[str, None]:
    """Wrap an async generator of events into SSE text format."""
    async for event in events:
        yield format_sse(event)
