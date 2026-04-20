"""Metric persistence helpers."""

from __future__ import annotations

from typing import Any

from app.config import get_settings
from app.models.metric import Metric
from app.services import audit_service

from .fields import _matching_entries


def _append_derived_metric(
    gold_records: dict[str, Any],
    source_index: dict[str, list[str]],
    metric_key: str,
    record: dict[str, Any],
    source_ids: list[str],
) -> None:
    gold_records[f"derived:{metric_key}"] = {
        "label": "Derived metric",
        "template_name": "metric_agent",
        "document_id": None,
        "fields": {
            metric_key: {
                "value": record["value"],
                "unit": record["unit"],
                "path": metric_key,
            }
        },
    }
    source_index[metric_key] = source_ids


def _metric_source_ids(source_index: dict[str, list[str]], input_keys: list[str]) -> list[str]:
    ids: list[str] = []
    for key in input_keys:
        for source_id in source_index.get(key, []):
            if source_id not in ids:
                ids.append(source_id)
    return ids


async def _upsert_metric(
    company_id: str,
    workspace_id: str,
    actor_id: str,
    definition: dict[str, Any],
    record: dict[str, Any],
    source_ids: list[str],
    gold_records: dict[str, Any],
) -> Metric:
    existing = await Metric.find_one(
        {
            "company_id": company_id,
            "workspace_id": workspace_id,
            "metric_code": record["metric_key"],
        }
    )

    if existing and isinstance(existing.metadata, dict) and existing.metadata.get("human_override") and existing.status == "approved":
        return existing

    metadata = dict(existing.metadata) if existing and isinstance(existing.metadata, dict) else {}
    quality_flags = list(record.get("quality_flags") or [])
    mapping_confidence = float(record.get("mapping_confidence", 1.0))

    audit_trails = []
    if record.get("input_keys"):
        for key in record["input_keys"]:
            matches = _matching_entries(gold_records, key)
            for match in matches:
                if match.get("audit") and match["audit"] not in audit_trails:
                    audit_trails.append(match["audit"])

    metadata.update(
        {
            "source_type": "metric_agent",
            "pillar": definition.get("pillar"),
            "tags": definition.get("tags", []),
            "suggested_tool": definition.get("suggested_tool"),
            "tool_used": record.get("tool_used"),
            "input_keys": record.get("input_keys", []),
            "ef_version": record.get("ef_version"),
            "factor_metadata": record.get("factor_metadata"),
            "calculation_trace": record.get("calculation_trace"),
            "quality_flags": quality_flags,
            "methodology": record.get("methodology") or {},
            "mapping_confidence": mapping_confidence,
            "error_detail": record.get("error_detail"),
            "value_missing": record.get("value") is None,
            "audit_trail": audit_trails[:10],
        }
    )
    if record.get("status") == "MANUAL_REQUIRED":
        metadata["manual_required"] = True
    else:
        metadata.pop("manual_required", None)

    from app.services.workflow_service import get_workflow_policy

    policy = await get_workflow_policy(workspace_id)
    settings = get_settings()

    if record.get("status") == "OK":
        review_reasons: list[str] = []
        if mapping_confidence < settings.ESG_AUTO_APPROVE_MIN_CONFIDENCE:
            review_reasons.append("low_mapping_confidence")
        if "method_missing" in quality_flags:
            review_reasons.append("method_missing")
        if (
            settings.ESG_REQUIRE_REVIEW_ON_FALLBACK_FACTOR
            and policy.require_review_on_fallback_factor
            and "used_fallback_factor" in quality_flags
        ):
            review_reasons.append("fallback_factor_used")
        if "ambiguous_source" in quality_flags:
            review_reasons.append("ambiguous_source")

        if review_reasons:
            metadata["manual_required"] = True
            metadata["review_reasons"] = review_reasons
            final_status = "manual_required"
            final_reviewer = None
        else:
            final_status = "pending" if policy.require_metric_approval else "approved"
            final_reviewer = actor_id if final_status == "approved" else None
    else:
        final_status = "manual_required"
        final_reviewer = None

    payload = {
        "name": definition.get("description") or record["metric_key"].replace("_", " ").title(),
        "pillar": definition.get("pillar", "environmental"),
        "unit": record.get("unit") or definition.get("unit", "value"),
        "value": float(record["value"]) if record.get("value") is not None else 0.0,
        "metadata": metadata,
        "source_extracted_data_ids": source_ids,
        "status": final_status,
        "reviewer": final_reviewer,
    }

    if existing:
        existing.name = payload["name"]
        existing.pillar = payload["pillar"]
        existing.unit = payload["unit"]
        existing.value = payload["value"]
        existing.metadata = payload["metadata"]
        existing.source_extracted_data_ids = payload["source_extracted_data_ids"]
        existing.status = payload["status"]
        existing.reviewer = payload["reviewer"]
        await existing.save_with_timestamp()
        return existing

    metric = Metric(
        company_id=company_id,
        workspace_id=workspace_id,
        metric_code=record["metric_key"],
        name=payload["name"],
        unit=payload["unit"],
        pillar=payload["pillar"],
        value=payload["value"],
        metadata=payload["metadata"],
        source_extracted_data_ids=payload["source_extracted_data_ids"],
        status=payload["status"],
        reviewer=payload["reviewer"],
    )
    await metric.insert()
    await audit_service.emit(
        event_type="METRIC_CREATED",
        actor_user_id=actor_id,
        company_id=company_id,
        workspace_id=workspace_id,
        entity_table="metrics",
        entity_id=metric.id,
        payload={"metric_code": metric.metric_code, "source_type": "metric_agent"},
    )
    return metric
