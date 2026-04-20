"""
Pipeline story service.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from app.llm_factory import create_llm
from app.models.audit_event import AuditEvent


EVENT_LABELS = {
    "COMPANY_CREATED": "A company workspace was provisioned.",
    "WORKSPACE_CREATED": "A new reporting workspace was created.",
    "WORKSPACE_DELETED": "A reporting workspace was deleted.",
    "DOCUMENT_ANCHORED": "A source document was uploaded and fingerprinted.",
    "DOCUMENT_BLOCKCHAIN_ANCHORED": "The document fingerprint was anchored on chain.",
    "EXTRACTION_CREATED": "An extraction run produced structured data for review.",
    "RECORD_APPROVED": "A reviewer approved extracted data.",
    "RECORD_REJECTED": "A reviewer rejected extracted data.",
    "METRIC_CREATED": "A metric was computed from extracted records.",
    "METRICS_APPROVED": "A reviewer approved a metric result.",
    "METRIC_OVERRIDE": "A metric was adjusted by human override.",
    "REPORT_GENERATED": "A workspace report was generated.",
    "REPORT_SECTION_REGENERATED": "One report section was regenerated.",
}

STORY_SYSTEM_PROMPT = (
    "You are a product assistant narrating sustainability workflow activity for business users. "
    "Turn the event feed into a short chronological story. Keep it concrete, professional, and easy to scan."
)


def _event_headline(event: AuditEvent) -> str:
    return EVENT_LABELS.get(event.event_type, event.event_type.replace("_", " ").title())


def _event_detail(event: AuditEvent) -> str:
    parts = []
    if event.entity_table and event.entity_id:
        parts.append(f"{event.entity_table}:{event.entity_id}")
    if event.payload:
        for key, value in list(event.payload.items())[:3]:
            parts.append(f"{key}={value}")
    return " | ".join(parts) or "No extra details recorded."


def _fallback_story(events: list[AuditEvent]) -> str:
    if not events:
        return "No tracked workspace activity has been recorded yet. Start by uploading documents or generating a report."

    ordered = list(reversed(events))
    lines = []
    for event in ordered[:6]:
        timestamp = event.created_at.strftime("%b %d, %H:%M")
        lines.append(f"On {timestamp}, {_event_headline(event)} {_event_detail(event)}")
    return " ".join(lines)


async def build_workspace_story(workspace_id: str, company_id: str | None, limit: int = 25) -> dict[str, Any]:
    query: dict[str, Any] = {"workspace_id": workspace_id}
    if company_id:
        query["company_id"] = company_id

    events = await AuditEvent.find(query).sort("-created_at").limit(limit).to_list()
    story = _fallback_story(events)

    if events:
        prompt = "Recent workspace events:\n" + "\n".join(
            f"- {event.created_at.isoformat()}: {_event_headline(event)} ({_event_detail(event)})"
            for event in reversed(events)
        )
        try:
            llm = create_llm(temperature=0.2)
            response = await llm.ainvoke(
                [
                    SystemMessage(content=STORY_SYSTEM_PROMPT),
                    HumanMessage(content=prompt),
                ]
            )
            content = getattr(response, "content", response)
            if isinstance(content, list):
                content = " ".join(
                    block.get("text", "") if isinstance(block, dict) else str(block)
                    for block in content
                )
            if str(content).strip():
                story = str(content).strip()
        except Exception:
            pass

    return {
        "workspace_id": workspace_id,
        "story": story,
        "events": [
            {
                "id": event.id,
                "event_type": event.event_type,
                "created_at": event.created_at,
                "headline": _event_headline(event),
                "detail": _event_detail(event),
                "payload": event.payload,
            }
            for event in events
        ],
        "generated_at": datetime.now(UTC),
    }
