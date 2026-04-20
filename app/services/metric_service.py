"""
Logic for deriving and rolling up metrics from extracted data.
"""

from __future__ import annotations

from typing import Any, Optional

from app.core.errors import AppError, ErrorCode
from app.models.extraction import ExtractedData, SchemaTemplate
from app.models.metric import Metric
from app.schemas.metric import MetricCreate
from app.services import audit_service

NON_METRIC_FIELD_EXACT = {
    "invoice_date",
    "invoice_number",
    "period_end",
    "period_start",
    "currency",
    "meter_readings_present",
}

NON_METRIC_FIELD_TOKENS = {
    "account",
    "address",
    "amount",
    "bank",
    "billing",
    "bill_to",
    "city",
    "cost",
    "country",
    "currency",
    "customer",
    "date",
    "due",
    "facility",
    "gross",
    "iban",
    "id",
    "identifier",
    "invoice",
    "location",
    "month",
    "name",
    "net",
    "number",
    "postal",
    "postcode",
    "price",
    "reference",
    "serial",
    "street",
    "supplier",
    "tax",
    "vat",
    "year",
    "zip",
}

METRIC_SIGNAL_TOKENS = {
    "co2",
    "co2e",
    "consumption",
    "diesel",
    "electricity",
    "emission",
    "employee",
    "employees",
    "energy",
    "fuel",
    "gas",
    "ghg",
    "headcount",
    "incident",
    "injury",
    "intensity",
    "kwh",
    "litres",
    "litre",
    "m3",
    "scope1",
    "scope2",
    "scope3",
    "training",
    "usage",
    "value",
    "volume",
    "waste",
    "water",
}

CANONICAL_ELECTRICITY_CODES = {"electricity_kwh_total"}
CANONICAL_EMISSIONS_CODES = {"total_ghg_tco2e", "scope1_tco2e", "scope2_tco2e"}
CANONICAL_WATER_CODES = {"water_consumption_m3_total"}
CANONICAL_WASTE_CODES = {"waste_generated_kg_total"}


def _normalize_key(value: str) -> str:
    import re

    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")


def _is_metric_field_candidate(field_key: str, payload: dict[str, Any]) -> bool:
    normalized = _normalize_key(field_key)
    if not normalized or normalized.endswith("_unit"):
        return False
    if normalized == "value":
        return True
    if normalized in NON_METRIC_FIELD_EXACT:
        return False

    tokens = {token for token in normalized.split("_") if token}
    if not tokens:
        return False

    has_metric_signal = bool(tokens & METRIC_SIGNAL_TOKENS)
    has_unit_signal = bool(payload.get(f"{field_key}_unit") or payload.get("unit"))
    has_non_metric_signal = bool(tokens & NON_METRIC_FIELD_TOKENS)

    if has_non_metric_signal and not has_metric_signal:
        return False

    return has_metric_signal or has_unit_signal


async def compute_and_store_metric(
    company_id: str, 
    workspace_id: str, 
    data: MetricCreate, 
    actor_id: str
) -> Metric:
    """
    Stores a newly computed metric, optionally checking for overlaps.
    """
    m = Metric(
        company_id=company_id,
        workspace_id=workspace_id,
        metric_code=data.metric_code,
        name=data.name,
        unit=data.unit,
        pillar=data.pillar,
        value=data.value,
        metadata=data.metadata,
        source_extracted_data_ids=data.source_extracted_data_ids,
        status="pending"
    )
    await m.insert()
    await audit_service.emit(
        event_type="METRIC_CREATED",
        actor_user_id=actor_id,
        company_id=company_id,
        workspace_id=workspace_id,
        entity_table="metrics",
        entity_id=m.id,
        payload={"metric_code": data.metric_code},
    )
    return m


def _coerce_numeric(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if not isinstance(value, str):
        return None

    text = value.strip()
    if not text:
        return None

    candidate = text.replace(" ", "")
    import re

    if not re.match(r"^[^\dA-Za-z\-+]*[-+]?\d", candidate):
        return None

    if "," in candidate and "." in candidate:
        if candidate.rfind(",") > candidate.rfind("."):
            candidate = candidate.replace(".", "").replace(",", ".")
        else:
            candidate = candidate.replace(",", "")
    elif "," in candidate:
        candidate = candidate.replace(",", ".")

    match = re.search(r"-?\d+(?:\.\d+)?", candidate)
    if not match:
        return None
    try:
        return float(match.group())
    except ValueError:
        return None


def _normalize_unit(unit: str | None) -> str:
    return (unit or "").strip().lower()


def _to_kwh(value: float, unit: str | None) -> float | None:
    normalized = _normalize_unit(unit)
    if normalized == "kwh":
        return value
    if normalized == "mwh":
        return value * 1000.0
    if normalized == "gj":
        return value * 277.778
    return None


def _to_tco2e(value: float, unit: str | None) -> float | None:
    normalized = _normalize_unit(unit)
    if normalized == "tco2e":
        return value
    if normalized == "kgco2e":
        return value / 1000.0
    return None


def build_workspace_metric_summary(
    metrics: list[Metric],
    company_id: str,
    workspace_id: str,
) -> dict[str, Any]:
    eligible = [m for m in metrics if m.status in {"approved", "pending"}]
    source = eligible if eligible else metrics

    environmental_count = sum(1 for m in source if (m.pillar or "environmental") == "environmental")
    social_count = sum(1 for m in source if m.pillar == "social")
    governance_count = sum(1 for m in source if m.pillar == "governance")

    electricity_total = 0.0
    electricity_seen = False
    emissions_total = 0.0
    emissions_seen = False
    water_total = 0.0
    water_seen = False
    waste_total = 0.0
    waste_seen = False

    for metric in source:
        value = float(metric.value or 0.0)
        if metric.metric_code in CANONICAL_ELECTRICITY_CODES:
            converted = _to_kwh(value, metric.unit)
            if converted is not None:
                electricity_total += converted
                electricity_seen = True
        if metric.metric_code in CANONICAL_EMISSIONS_CODES:
            converted = _to_tco2e(value, metric.unit)
            if converted is not None:
                emissions_total += converted
                emissions_seen = True
        if metric.metric_code in CANONICAL_WATER_CODES and _normalize_unit(metric.unit) == "m3":
            water_total += value
            water_seen = True
        if metric.metric_code in CANONICAL_WASTE_CODES and _normalize_unit(metric.unit) == "kg":
            waste_total += value
            waste_seen = True

    if not electricity_seen:
        for metric in source:
            converted = _to_kwh(float(metric.value or 0.0), metric.unit)
            if converted is not None and ":" not in metric.metric_code:
                electricity_total += converted
    if not emissions_seen:
        for metric in source:
            converted = _to_tco2e(float(metric.value or 0.0), metric.unit)
            if converted is not None:
                emissions_total += converted
    if not water_seen:
        for metric in source:
            if _normalize_unit(metric.unit) == "m3":
                water_total += float(metric.value or 0.0)
    if not waste_seen:
        for metric in source:
            if _normalize_unit(metric.unit) == "kg":
                waste_total += float(metric.value or 0.0)

    cards = [
        {"key": "electricity", "label": "Total Electricity", "unit": "kWh", "value": round(electricity_total, 6)},
        {"key": "emissions", "label": "Total Emissions", "unit": "tCO2e", "value": round(emissions_total, 6)},
        {"key": "water", "label": "Water Consumption", "unit": "m3", "value": round(water_total, 6)},
        {"key": "waste", "label": "Waste Generated", "unit": "kg", "value": round(waste_total, 6)},
    ]

    return {
        "company_id": company_id,
        "workspace_id": workspace_id,
        "total_metrics": len(source),
        "environmental_count": environmental_count,
        "social_count": social_count,
        "governance_count": governance_count,
        "cards": cards,
    }


def _metric_candidates(extraction: ExtractedData, template: SchemaTemplate) -> list[MetricCreate]:
    payload = extraction.payload or {}
    if not isinstance(payload, dict):
        return []

    candidates: list[MetricCreate] = []
    # If Blueprint defines specific targets, use them instead of guessing
    if getattr(template, "metric_targets", None):
        for target in template.metric_targets:
            field_key = target.get("source_field")
            if not field_key or field_key not in payload:
                continue
            
            raw_value = payload[field_key]
            numeric_value = _coerce_numeric(raw_value)
            if numeric_value is None:
                continue
                
            unit_field = target.get("unit_field")
            resolved_unit = "value"
            if unit_field and unit_field in payload:
                resolved_unit = str(payload[unit_field])
            elif "unit" in target:
                resolved_unit = target["unit"]
                
            candidates.append(
                MetricCreate(
                    metric_code=f"{template.id}:{target.get('metric_code', field_key)}:{extraction.id}",
                    name=target.get("name", f"{template.name} - {field_key.replace('_', ' ').title()}"),
                    unit=resolved_unit,
                    value=numeric_value,
                    metadata={
                        "field_key": field_key,
                        "template_id": template.id,
                        "template_name": template.name,
                        "document_id": extraction.document_id,
                    },
                    source_extracted_data_ids=[extraction.id],
                )
            )
        return candidates

    # Fallback legacy logic for templates without explicit metric_targets
    unit = str(payload.get("unit") or "").strip()
    primary_value = _coerce_numeric(payload.get("value"))

    used_keys: set[str] = set()
    if primary_value is not None:
        candidates.append(
            MetricCreate(
                metric_code=f"{template.id}:value:{extraction.id}",
                name=template.name,
                unit=unit or "value",
                value=primary_value,
                metadata={
                    "field_key": "value",
                    "template_id": template.id,
                    "template_name": template.name,
                    "document_id": extraction.document_id,
                },
                source_extracted_data_ids=[extraction.id],
            )
        )
        used_keys.add("value")

    for key, raw_value in payload.items():
        if key in used_keys:
            continue
        if not _is_metric_field_candidate(key, payload):
            continue
        numeric_value = _coerce_numeric(raw_value)
        if numeric_value is None:
            continue
        candidates.append(
            MetricCreate(
                metric_code=f"{template.id}:{key}:{extraction.id}",
                name=f"{template.name} - {key.replace('_', ' ').title()}",
                unit=str(payload.get(f"{key}_unit") or payload.get("unit") or key),
                value=numeric_value,
                metadata={
                    "field_key": key,
                    "template_id": template.id,
                    "template_name": template.name,
                    "document_id": extraction.document_id,
                },
                source_extracted_data_ids=[extraction.id],
            )
        )
    return candidates


async def sync_metrics_from_approved_extraction(
    extraction: ExtractedData,
    actor_id: str,
    actor_company_id: str | None = None,
) -> list[Metric]:
    if actor_company_id and actor_company_id != extraction.company_id:
        raise AppError(ErrorCode.FORBIDDEN, "Cross-tenant access denied")
    if extraction.status != "approved":
        return []

    template = await SchemaTemplate.get(extraction.template_id)
    if not template:
        return []

    from app.services.workflow_service import get_workflow_policy
    policy = await get_workflow_policy(extraction.workspace_id)
    initial_status = "pending" if policy.require_metric_approval else "approved"
    initial_reviewer = actor_id if initial_status == "approved" else None

    metrics: list[Metric] = []
    for candidate in _metric_candidates(extraction, template):
        candidate.metadata = {
            **candidate.metadata,
            "source_type": "extraction_sync",
        }
        existing = await Metric.find_one(
            {
                "company_id": extraction.company_id,
                "workspace_id": extraction.workspace_id,
                "metric_code": candidate.metric_code,
            }
        )
        if existing:
            # If human override exists, don't revert to automated value
            if isinstance(existing.metadata, dict) and existing.metadata.get("human_override") and existing.status == "approved":
                metrics.append(existing)
                continue

            existing.name = candidate.name
            existing.unit = candidate.unit
            existing.pillar = candidate.pillar
            existing.value = candidate.value
            existing.metadata = candidate.metadata
            existing.source_extracted_data_ids = candidate.source_extracted_data_ids
            existing.status = initial_status
            existing.reviewer = initial_reviewer
            await existing.save_with_timestamp()
            metrics.append(existing)
            continue

        metric = Metric(
            company_id=extraction.company_id,
            workspace_id=extraction.workspace_id,
            metric_code=candidate.metric_code,
            name=candidate.name,
            unit=candidate.unit,
            pillar=candidate.pillar,
            value=candidate.value,
            metadata=candidate.metadata,
            source_extracted_data_ids=candidate.source_extracted_data_ids,
            status=initial_status,
            reviewer=initial_reviewer,
        )
        await metric.insert()
        await audit_service.emit(
            event_type="METRIC_CREATED",
            actor_user_id=actor_id,
            company_id=extraction.company_id,
            workspace_id=extraction.workspace_id,
            entity_table="metrics",
            entity_id=metric.id,
            payload={"metric_code": metric.metric_code, "extraction_id": extraction.id},
        )
        metrics.append(metric)

    return metrics


async def reject_metrics_from_extraction(
    extraction_id: str,
    actor_id: str,
    actor_company_id: str | None = None,
) -> list[Metric]:
    metrics = await Metric.find({"source_extracted_data_ids": extraction_id}).to_list()
    updated: list[Metric] = []
    for metric in metrics:
        if actor_company_id and actor_company_id != metric.company_id:
            continue
        metric.status = "rejected"
        metric.reviewer = actor_id
        await metric.save_with_timestamp()
        updated.append(metric)
    return updated


async def sync_workspace_metrics(
    company_id: str,
    workspace_id: str,
    actor_id: str,
    actor_company_id: str | None = None,
) -> list[Metric]:
    if actor_company_id and actor_company_id != company_id:
        raise AppError(ErrorCode.FORBIDDEN, "Cross-tenant access denied")

    extractions = await ExtractedData.find(
        {
            "company_id": company_id,
            "workspace_id": workspace_id,
            "status": "approved",
        }
    ).to_list()

    synced: list[Metric] = []
    for extraction in extractions:
        synced.extend(
            await sync_metrics_from_approved_extraction(
                extraction,
                actor_id,
                actor_company_id,
            )
        )
    return synced

async def review_metric(
    metric_id: str,
    action: str,
    actor_id: str,
    override_value: Optional[float] = None,
    override_rationale: Optional[str] = None,
    actor_company_id: str | None = None,
) -> Metric:
    m = await Metric.get(metric_id)
    if not m:
        raise AppError(ErrorCode.NOT_FOUND, "Metric not found")
    if actor_company_id and actor_company_id != m.company_id:
        raise AppError(ErrorCode.FORBIDDEN, "Cross-tenant access denied")
        
    if action not in ["approve", "reject"]:
        raise AppError(ErrorCode.BAD_REQUEST, "Invalid action, must be approve or reject")
        
    m.status = "approved" if action == "approve" else "rejected"
    m.reviewer = actor_id
    if not isinstance(m.metadata, dict):
        m.metadata = {}
    if override_value is not None:
        m.value = override_value
        m.metadata["human_override"] = True
        m.metadata["overridden_by"] = actor_id
    if override_rationale:
        m.metadata["override_rationale"] = override_rationale

    await m.save_with_timestamp()
    await audit_service.emit(
        event_type="METRIC_OVERRIDE" if override_value is not None else "METRICS_APPROVED",
        actor_user_id=actor_id,
        company_id=m.company_id,
        workspace_id=m.workspace_id,
        entity_table="metrics",
        entity_id=m.id,
        payload={
            "action": action,
            "override_value": override_value,
            "override_rationale": override_rationale,
        },
    )
    return m
