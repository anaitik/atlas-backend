"""Metric target recommendation logic from extraction structure."""

from __future__ import annotations

import json
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from app.core.errors import AppError, ErrorCode
from app.llm_factory import create_llm
from app.models.extraction import ExtractedData, SchemaTemplate

from .catalog import _load_metric_definitions
from .constants import METRIC_PRIORITY, RECOMMENDER_SYSTEM
from .fields import (
    _collect_structure_fields,
    _extract_response_text,
    _field_catalog,
    _parse_json_response,
    _structure_field_aliases,
)


def _default_metric_targets_from_keys(keys: set[str]) -> list[str]:
    targets: list[str] = []

    if any("electric" in key or "strom" in key for key in keys):
        targets.extend(["electricity_kwh_total", "scope2_kgco2e", "scope2_tco2e"])
        if "electricity_kwh_winema" in keys:
            targets.append("electricity_kwh_winema")
        if "electricity_kwh_transfer" in keys:
            targets.append("electricity_kwh_transfer")
    if any("gas" in key for key in keys):
        targets.extend(["gas_kwh_total", "scope1_kgco2e", "scope1_tco2e"])
    if any(token in key for key in keys for token in ("fuel", "diesel", "petrol", "lpg")):
        targets.extend(["fuel_litres_total", "scope1_kgco2e", "scope1_tco2e"])
    if "headcount" in keys:
        targets.append("headcount")
        if any(target in targets for target in ("electricity_kwh_total", "scope2_kgco2e", "scope2_tco2e")):
            targets.extend(["energy_intensity_kwh_per_employee", "emission_intensity_kgco2e_per_employee"])
    if "board_independence_pct" in keys:
        targets.append("board_independence_pct")
    if "whistleblower_cases" in keys:
        targets.append("whistleblower_cases")
    if "training_hours" in keys and "headcount" in keys:
        targets.append("training_hours_per_employee")
    if any(token in key for key in keys for token in ("water", "wasser", "m3")):
        targets.append("water_consumption_m3_total")
    if any(token in key for key in keys for token in ("waste", "abfall", "mull", "tonne")):
        targets.append("waste_generated_kg_total")

    if not targets:
        return []
    return sorted(set(targets), key=lambda key: (METRIC_PRIORITY.get(key, 999), key))


def _default_metric_targets(gold_records: dict[str, Any]) -> list[str]:
    return _default_metric_targets_from_keys(set(_field_catalog(gold_records)))


def _recommendation_reason(metric_key: str, aliases: set[str]) -> str:
    if metric_key in {"electricity_kwh_total", "scope2_kgco2e", "scope2_tco2e"}:
        return "Electricity-related fields were detected in the approved JSON structure."
    if metric_key in {"gas_kwh_total", "scope1_kgco2e", "scope1_tco2e"} and any("gas" in alias for alias in aliases):
        return "Gas consumption fields were detected in the approved JSON structure."
    if metric_key in {"fuel_litres_total", "scope1_kgco2e", "scope1_tco2e"} and any(
        token in alias for alias in aliases for token in ("fuel", "diesel", "petrol", "lpg")
    ):
        return "Fuel-related fields were detected in the approved JSON structure."
    if metric_key == "headcount":
        return "Headcount or workforce fields were detected in the approved JSON structure."
    if metric_key == "energy_intensity_kwh_per_employee":
        return "Energy and headcount fields are both present, so an intensity metric is likely derivable."
    if metric_key == "emission_intensity_kgco2e_per_employee":
        return "Emissions and headcount fields are both present, so an intensity metric is likely derivable."
    if metric_key == "training_hours_per_employee":
        return "Training-hours and headcount fields are both present in the approved JSON structure."
    if metric_key == "board_independence_pct":
        return "Board independence fields were detected in the approved JSON structure."
    if metric_key == "whistleblower_cases":
        return "Ethics or whistleblower case fields were detected in the approved JSON structure."
    if metric_key == "total_ghg_tco2e":
        return "Emissions-related fields were detected, so a total GHG rollup is recommended."
    if metric_key == "water_consumption_m3_total":
        return "Water consumption fields were detected in the approved JSON structure."
    if metric_key == "waste_generated_kg_total":
        return "Waste generation fields were detected in the approved JSON structure."
    return "Recommended from approved extraction structure without using metric values."


async def _build_structure_catalog(
    extractions: list[ExtractedData],
    schema_template_cls: type[SchemaTemplate] = SchemaTemplate,
) -> dict[str, dict[str, Any]]:
    template_ids = {extraction.template_id for extraction in extractions}
    template_map: dict[str, SchemaTemplate] = {}
    for template_id in template_ids:
        template = await schema_template_cls.get(template_id)
        if template:
            template_map[template.id] = template

    catalog: dict[str, dict[str, Any]] = {}
    for extraction in extractions:
        template = template_map.get(extraction.template_id)
        template_name = template.name if template else extraction.template_id

        for path, unit in _collect_structure_fields(extraction.payload):
            aliases = _structure_field_aliases(path, unit, template_name)
            for alias in aliases:
                item = catalog.setdefault(
                    alias,
                    {
                        "key": alias,
                        "unit": unit,
                        "records": [],
                        "paths": [],
                    },
                )
                if not item["unit"] and unit:
                    item["unit"] = unit
                if template_name not in item["records"]:
                    item["records"].append(template_name)
                if path not in item["paths"] and len(item["paths"]) < 4:
                    item["paths"].append(path)

    return catalog


def _heuristic_structure_recommendations(structure_catalog: dict[str, dict[str, Any]]) -> dict[str, Any]:
    aliases = set(structure_catalog)
    targets = _default_metric_targets_from_keys(aliases)
    return {
        "metric_targets": targets,
        "structure_signals": [structure_catalog[key] for key in sorted(structure_catalog)],
        "explanation": "Recommended from approved extraction structure only. Numeric values were not used for target selection.",
        "rationale": [{"metric_key": metric_key, "reason": _recommendation_reason(metric_key, aliases)} for metric_key in targets],
    }


def _build_recommendation_prompt(
    structure_catalog: dict[str, dict[str, Any]],
    user_nlp_directive: str | None = None,
    company_id: str | None = None,
) -> str:
    definitions = _load_metric_definitions(company_id)
    signals = [
        {
            "key": key,
            "unit": value.get("unit"),
            "records": value.get("records", []),
            "paths": value.get("paths", []),
        }
        for key, value in sorted(structure_catalog.items())
    ]
    catalog = [
        {
            "key": key,
            "description": value.get("description", key),
            "pillar": value.get("pillar", "environmental"),
            "unit": value.get("unit", "value"),
        }
        for key, value in definitions.items()
    ]
    allowed_targets = _default_metric_targets_from_keys(set(structure_catalog))

    prompt = (
        f"Detected structure signals: {json.dumps(signals)}\n"
        f"Metric catalog: {json.dumps(catalog)}\n"
        f"Allowed metric targets: {json.dumps(allowed_targets)}\n"
    )
    if user_nlp_directive:
        prompt += (
            "USER NLP DIRECTIVE: The user explicitly requested these targets: "
            f"'{user_nlp_directive}'. You MUST prioritize selecting metric target keys from the catalog that fulfill this goal.\n"
        )
    prompt += 'Return JSON only in this shape: {"metric_targets": ["metric_key"]}. Choose a subset of allowed metric targets only.'
    return prompt


def _normalize_recommended_targets(raw_targets: Any, allowed_targets: list[str]) -> list[str]:
    if not isinstance(raw_targets, list):
        return allowed_targets
    allowed = set(allowed_targets)
    normalized = [str(target) for target in raw_targets if isinstance(target, str) and target in allowed]
    if not normalized:
        return allowed_targets
    unique_targets = list(dict.fromkeys(normalized))
    # Keep companion scope units together when derivable to preserve downstream totals/intensity options.
    allowed = set(allowed_targets)
    if "scope2_kgco2e" in unique_targets and "scope2_tco2e" in allowed and "scope2_tco2e" not in unique_targets:
        unique_targets.append("scope2_tco2e")
    if "scope1_kgco2e" in unique_targets and "scope1_tco2e" in allowed and "scope1_tco2e" not in unique_targets:
        unique_targets.append("scope1_tco2e")
    return sorted(unique_targets[:8], key=lambda key: (METRIC_PRIORITY.get(key, 999), key))


async def recommend_metric_targets_for_extractions(
    extractions: list[ExtractedData],
    *,
    llm_factory=create_llm,
    schema_template_cls: type[SchemaTemplate] = SchemaTemplate,
) -> dict[str, Any]:
    if not extractions:
        raise AppError(ErrorCode.BAD_REQUEST, "No approved extraction data is available for this workspace")

    structure_catalog = await _build_structure_catalog(extractions, schema_template_cls=schema_template_cls)
    heuristic = _heuristic_structure_recommendations(structure_catalog)
    fallback_targets = heuristic["metric_targets"]

    if not fallback_targets:
        return heuristic

    try:
        template_ids = {ex.template_id for ex in extractions}
        nlp_targets = []
        for template_id in template_ids:
            template = await schema_template_cls.get(template_id)
            if template and getattr(template, "target_metrics_nlp", None):
                nlp_targets.append(template.target_metrics_nlp)
        combined_nlp_directive = " | ".join(nlp_targets) if nlp_targets else None

        llm = llm_factory(temperature=0.0)
        company_id = getattr(extractions[0], "company_id", None) if extractions else None

        response = await llm.ainvoke(
            [
                SystemMessage(content=RECOMMENDER_SYSTEM),
                HumanMessage(content=_build_recommendation_prompt(structure_catalog, combined_nlp_directive, company_id)),
            ]
        )
        raw = _parse_json_response(_extract_response_text(response))
        heuristic["metric_targets"] = _normalize_recommended_targets(raw.get("metric_targets"), fallback_targets)
        heuristic["rationale"] = [
            {"metric_key": metric_key, "reason": _recommendation_reason(metric_key, set(structure_catalog))}
            for metric_key in heuristic["metric_targets"]
        ]
    except Exception:
        pass

    return heuristic
