"""
Deterministic ESG calculations from approved extractions.

Aggregates electricity consumption and applies emission factors with full provenance.
"""

from __future__ import annotations

import re
from typing import Any

from app.agentic.metric.catalog import resolve_emission_factor, _load_metric_definitions
from app.models.extraction import ExtractedData, SchemaTemplate
from app.models.metric import Metric
from app.models.workspace import Workspace
from app.services import audit_service, metric_service

ELECTRICITY_TEMPLATE_HINTS = ("scope 2", "electricity", "kwh")

COUNTRY_TO_REGION: dict[str, str] = {
    "germany": "de",
    "deutschland": "de",
    "de": "de",
    "united kingdom": "uk",
    "uk": "uk",
    "great britain": "uk",
    "gb": "uk",
    "england": "uk",
    "france": "fr",
    "fr": "fr",
    "netherlands": "nl",
    "nl": "nl",
    "spain": "es",
    "es": "es",
    "italy": "it",
    "it": "it",
}

JUNK_SYNC_FIELD_KEYS = {
    "reporting_period_start",
    "reporting_period_end",
    "evidence_doc_type",
    "invoice_date",
    "period_start",
    "period_end",
}


def _metric_definition(metric_code: str, company_id: str) -> dict[str, Any]:
    definitions = _load_metric_definitions(company_id)
    return definitions.get(
        metric_code,
        {
            "description": metric_code.replace("_", " ").title(),
            "pillar": "environmental",
            "unit": "value",
            "tags": [],
        },
    )


def resolve_reporting_year(workspace: Workspace) -> int | None:
    if workspace.reporting_year:
        return workspace.reporting_year

    text = f"{workspace.name} {workspace.description or ''}"
    fy_match = re.search(r"FY\s*(\d{4})", text, re.IGNORECASE)
    if fy_match:
        return int(fy_match.group(1))

    year_match = re.search(r"Reporting year:\s*(\d{4})", text, re.IGNORECASE)
    if year_match:
        return int(year_match.group(1))

    return None


def is_electricity_template(template: SchemaTemplate) -> bool:
    name = (template.name or "").lower()
    return any(hint in name for hint in ELECTRICITY_TEMPLATE_HINTS)


def _country_to_region(country: str | None) -> str | None:
    if not country:
        return None
    normalized = country.strip().lower()
    return COUNTRY_TO_REGION.get(normalized)


def _resolve_grid_factor_key(*, country: str | None, region: str) -> str:
    country_region = _country_to_region(country)
    if country_region == "de":
        return "electricity_grid_de"
    if country_region == "uk":
        return "electricity_grid_uk"

    normalized_region = (region or "EU").strip().lower()
    if normalized_region in {"de", "germany"}:
        return "electricity_grid_de"
    if normalized_region in {"uk", "gb", "great_britain", "united_kingdom"}:
        return "electricity_grid_uk"
    return "electricity_grid_eu_avg"


def _kwh_from_payload(payload: dict[str, Any]) -> float | None:
    raw_value = payload.get("value")
    numeric = metric_service._coerce_numeric(raw_value)
    if numeric is None:
        return None
    return metric_service._to_kwh(numeric, str(payload.get("unit") or ""))


async def purge_junk_extraction_sync_metrics(company_id: str, workspace_id: str) -> int:
    """Remove extraction-sync metrics created from date/metadata fields."""
    metrics = await Metric.find({"company_id": company_id, "workspace_id": workspace_id}).to_list()
    removed = 0
    for metric in metrics:
        metadata = metric.metadata if isinstance(metric.metadata, dict) else {}
        if metadata.get("source_type") != "extraction_sync":
            continue
        field_key = str(metadata.get("field_key") or "")
        if field_key in JUNK_SYNC_FIELD_KEYS:
            await metric.delete()
            removed += 1
            continue
        if field_key.startswith("reporting_period") or (
            "period" in field_key and field_key.endswith(("_start", "_end"))
        ):
            await metric.delete()
            removed += 1
    return removed


async def _upsert_esg_metric(
    *,
    company_id: str,
    workspace_id: str,
    actor_id: str,
    metric_code: str,
    definition: dict[str, Any],
    value: float,
    unit: str,
    source_ids: list[str],
    metadata: dict[str, Any],
) -> Metric:
    from app.services.workflow_service import get_workflow_policy

    policy = await get_workflow_policy(workspace_id)
    initial_status = "pending" if policy.require_metric_approval else "approved"
    initial_reviewer = actor_id if initial_status == "approved" else None

    existing = await Metric.find_one(
        {"company_id": company_id, "workspace_id": workspace_id, "metric_code": metric_code}
    )
    if existing and isinstance(existing.metadata, dict) and existing.metadata.get("human_override") and existing.status == "approved":
        return existing

    payload_metadata = {
        "source_type": "esg_engine",
        "pillar": definition.get("pillar", "environmental"),
        "tags": definition.get("tags", []),
        **metadata,
    }

    if existing:
        existing.name = definition.get("description") or metric_code.replace("_", " ").title()
        existing.unit = unit
        existing.pillar = definition.get("pillar", "environmental")
        existing.value = value
        existing.metadata = payload_metadata
        existing.source_extracted_data_ids = source_ids
        existing.status = initial_status
        existing.reviewer = initial_reviewer
        await existing.save_with_timestamp()
        return existing

    metric = Metric(
        company_id=company_id,
        workspace_id=workspace_id,
        metric_code=metric_code,
        name=definition.get("description") or metric_code.replace("_", " ").title(),
        unit=unit,
        pillar=definition.get("pillar", "environmental"),
        value=value,
        metadata=payload_metadata,
        source_extracted_data_ids=source_ids,
        status=initial_status,
        reviewer=initial_reviewer,
    )
    await metric.insert()
    await audit_service.emit(
        event_type="METRIC_CREATED",
        actor_user_id=actor_id,
        company_id=company_id,
        workspace_id=workspace_id,
        entity_table="metrics",
        entity_id=metric.id,
        payload={"metric_code": metric_code, "source_type": "esg_engine"},
    )
    return metric


async def run_workspace_esg_calculations(
    company_id: str,
    workspace_id: str,
    actor_id: str,
    actor_company_id: str | None = None,
) -> list[Metric]:
    if actor_company_id and actor_company_id != company_id:
        from app.core.errors import AppError, ErrorCode

        raise AppError(ErrorCode.FORBIDDEN, "Cross-tenant access denied")

    workspace = await Workspace.get(workspace_id)
    if not workspace or workspace.company_id != company_id:
        return []

    await purge_junk_extraction_sync_metrics(company_id, workspace_id)

    extractions = await ExtractedData.find(
        {"company_id": company_id, "workspace_id": workspace_id, "status": "approved"}
    ).to_list()

    electricity_rows: list[tuple[ExtractedData, SchemaTemplate, dict[str, Any]]] = []
    for extraction in extractions:
        template = await SchemaTemplate.get(extraction.template_id)
        if not template or not is_electricity_template(template):
            continue
        payload = extraction.payload if isinstance(extraction.payload, dict) else {}
        electricity_rows.append((extraction, template, payload))

    if not electricity_rows:
        return []

    total_kwh = 0.0
    source_ids: list[str] = []
    country_hint: str | None = None
    period_labels: list[str] = []

    for extraction, _template, payload in electricity_rows:
        kwh = _kwh_from_payload(payload)
        if kwh is None or kwh <= 0:
            continue
        total_kwh += kwh
        source_ids.append(extraction.id)
        if not country_hint and payload.get("country"):
            country_hint = str(payload.get("country"))
        period_start = payload.get("reporting_period_start") or payload.get("period_start")
        period_end = payload.get("reporting_period_end") or payload.get("period_end")
        if period_start or period_end:
            period_labels.append(f"{period_start or '?'} → {period_end or '?'}")

    if total_kwh <= 0 or not source_ids:
        return []

    reporting_year = resolve_reporting_year(workspace)
    region = workspace.region or "EU"
    scope2_method = workspace.scope2_method or "location_based"
    factor_key = _resolve_grid_factor_key(country=country_hint, region=region)

    factor_result = resolve_emission_factor(
        company_id=company_id,
        factor_key=factor_key,
        region=_country_to_region(country_hint) or region,
        year=reporting_year,
    )
    factor = factor_result["factor"]
    factor_value = float(factor.get("value", 0))
    factor_unit = str(factor.get("unit") or "kgCO2e/kWh")

    scope2_kg = total_kwh * factor_value
    scope2_t = scope2_kg / 1000.0

    trace = {
        "engine": "atlas_esg_v1",
        "inputs": {"electricity_kwh_total": total_kwh},
        "formula": f"{total_kwh} kWh × {factor_value} {factor_unit} = {scope2_kg} kgCO2e",
        "scope2_method": scope2_method,
        "reporting_year": reporting_year,
        "source_extraction_count": len(source_ids),
        "periods": period_labels[:20],
    }

    factor_metadata = {
        "factor_key": factor_result["factor_key"],
        "factor_value": factor_value,
        "factor_unit": factor_unit,
        "factor_source": factor.get("source"),
        "factor_year": factor.get("year"),
        "quality_flags": factor_result.get("quality_flags", []),
        "used_fallback_factor": factor_result.get("used_fallback_factor", False),
    }

    results: list[Metric] = []

    elec_def = _metric_definition("electricity_kwh_total", company_id)
    results.append(
        await _upsert_esg_metric(
            company_id=company_id,
            workspace_id=workspace_id,
            actor_id=actor_id,
            metric_code="electricity_kwh_total",
            definition=elec_def,
            value=total_kwh,
            unit="kWh",
            source_ids=source_ids,
            metadata={
                "calculation_trace": trace,
                "input_keys": ["electricity_kwh"],
                "aggregation": "sum_approved_extractions",
            },
        )
    )

    scope2_kg_def = _metric_definition("scope2_kgco2e", company_id)
    results.append(
        await _upsert_esg_metric(
            company_id=company_id,
            workspace_id=workspace_id,
            actor_id=actor_id,
            metric_code="scope2_kgco2e",
            definition=scope2_kg_def,
            value=round(scope2_kg, 4),
            unit="kgCO2e",
            source_ids=source_ids,
            metadata={
                "calculation_trace": trace,
                "factor_metadata": factor_metadata,
                "input_keys": ["electricity_kwh_total"],
                "tool_used": "apply_emission_factor",
                "ef_version": factor.get("version"),
            },
        )
    )

    scope2_t_def = _metric_definition("scope2_tco2e", company_id)
    results.append(
        await _upsert_esg_metric(
            company_id=company_id,
            workspace_id=workspace_id,
            actor_id=actor_id,
            metric_code="scope2_tco2e",
            definition=scope2_t_def,
            value=round(scope2_t, 6),
            unit="tCO2e",
            source_ids=source_ids,
            metadata={
                "calculation_trace": {
                    **trace,
                    "formula": f"{scope2_kg} kgCO2e ÷ 1000 = {scope2_t} tCO2e",
                },
                "input_keys": ["scope2_kgco2e"],
                "tool_used": "unit_convert",
            },
        )
    )

    return results
