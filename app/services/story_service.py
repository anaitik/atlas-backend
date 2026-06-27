"""
Pipeline story service.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
import re

from langchain_core.messages import HumanMessage, SystemMessage

from app.llm_factory import create_llm
from app.models.audit_event import AuditEvent
from app.models.user import User


EVENT_LABELS = {
    "COMPANY_CREATED": "Organization created",
    "WORKSPACE_CREATED": "Reporting period created",
    "WORKSPACE_DELETED": "Reporting period removed",
    "DOCUMENT_ANCHORED": "Document uploaded",
    "DOCUMENT_BLOCKCHAIN_ANCHORED": "Document secured",
    "EXTRACTION_CREATED": "Values extracted for review",
    "RECORD_APPROVED": "Extracted values approved",
    "RECORD_REJECTED": "Extracted values rejected",
    "METRIC_CREATED": "Metric calculated",
    "METRICS_APPROVED": "Metric approved",
    "METRIC_OVERRIDE": "Metric adjusted",
    "REPORT_GENERATED": "Report draft generated",
    "REPORT_SECTION_REGENERATED": "Report section updated",
}

ENTITY_TABLE_LABELS = {
    "documents": "document",
    "extracted_data": "extraction",
    "metrics": "metric",
    "reports": "report",
    "schema_templates": "document type",
}

UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)

STORY_SYSTEM_PROMPT = (
    "You are a product assistant narrating sustainability workflow activity for business users. "
    "Turn the event feed into a short chronological story. Keep it concrete, professional, and easy to scan."
)


def _event_headline(event: AuditEvent) -> str:
    return EVENT_LABELS.get(event.event_type, event.event_type.replace("_", " ").title())


def _payload_label(payload: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = payload.get(key)
        if value is not None and str(value).strip() and not UUID_RE.match(str(value).strip()):
            return str(value).strip()
    return None


def _entity_label(event: AuditEvent) -> str | None:
    payload = event.payload or {}
    labeled = _payload_label(
        payload,
        "document_filename",
        "filename",
        "template_name",
        "metric_name",
        "name",
        "report_title",
    )
    if labeled:
        return labeled
    table = event.entity_table or ""
    if table:
        return ENTITY_TABLE_LABELS.get(table, table.replace("_", " "))
    return None


def _event_detail(event: AuditEvent, actor_name: str | None = None) -> str:
    payload = event.payload or {}
    subject = _entity_label(event)
    actor_clause = f" by {actor_name}" if actor_name else ""

    if event.event_type == "DOCUMENT_ANCHORED":
        filename = _payload_label(payload, "filename", "document_filename")
        return f"{filename or 'A source file'} was uploaded and fingerprinted{actor_clause}."
    if event.event_type == "DOCUMENT_BLOCKCHAIN_ANCHORED":
        filename = _payload_label(payload, "filename", "document_filename")
        return f"{filename or 'The file'} was secured for verification{actor_clause}."
    if event.event_type == "EXTRACTION_CREATED":
        filename = _payload_label(payload, "document_filename", "filename")
        template = _payload_label(payload, "template_name")
        parts = [f"Values were extracted from {filename or 'a document'}"]
        if template:
            parts.append(f"using the {template} document type")
        return " ".join(parts) + "."
    if event.event_type in {"RECORD_APPROVED", "METRICS_APPROVED"}:
        target = subject or "extracted values"
        return f"{target.capitalize()} were approved{actor_clause}."
    if event.event_type == "RECORD_REJECTED":
        target = subject or "extracted values"
        reason = _payload_label(payload, "reason", "rejection_reason")
        base = f"{target.capitalize()} were rejected{actor_clause}"
        return f"{base}: {reason}." if reason else f"{base}."
    if event.event_type == "METRIC_CREATED":
        metric = _payload_label(payload, "metric_name", "name") or subject or "A metric"
        return f"{metric} was calculated from approved source data."
    if event.event_type == "REPORT_GENERATED":
        fmt = _payload_label(payload, "output_format")
        return f"A report draft was generated{(' (' + fmt.upper() + ')') if fmt else ''}{actor_clause}."
    if event.event_type == "WORKSPACE_CREATED":
        name = _payload_label(payload, "name", "workspace_name")
        return f"Reporting period {name or 'started'} was created{actor_clause}."

    if subject:
        return f"Updated {subject}{actor_clause}."
    return "Activity recorded for this reporting period."


def _fallback_story(events: list[AuditEvent], actors: dict[str, str]) -> str:
    if not events:
        return "No tracked workspace activity has been recorded yet. Start by uploading documents or generating a report."

    ordered = list(reversed(events))
    lines = []
    for event in ordered[:6]:
        timestamp = event.created_at.strftime("%b %d, %H:%M")
        actor = actors.get(event.actor_user_id or "")
        lines.append(f"On {timestamp}, {_event_headline(event)}. {_event_detail(event, actor)}")
    return " ".join(lines)


async def build_workspace_story(workspace_id: str, company_id: str | None, limit: int = 25) -> dict[str, Any]:
    query: dict[str, Any] = {"workspace_id": workspace_id}
    if company_id:
        query["company_id"] = company_id

    events = await AuditEvent.find(query).sort("-created_at").limit(limit).to_list()
    actor_ids = list({event.actor_user_id for event in events if event.actor_user_id})
    users = await User.find({"id": {"$in": actor_ids}}).to_list() if actor_ids else []
    actors = {user.id: user.full_name for user in users}

    story = _fallback_story(events, actors)

    if events:
        prompt = "Recent workspace events:\n" + "\n".join(
            f"- {event.created_at.isoformat()}: {_event_headline(event)} ({_event_detail(event, actors.get(event.actor_user_id or ''))})"
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
                "detail": _event_detail(event, actors.get(event.actor_user_id or "")),
                "entity_label": _entity_label(event),
                "payload": event.payload,
            }
            for event in events
        ],
        "generated_at": datetime.now(UTC),
    }
