"""Deterministic metric calculation tools."""

from __future__ import annotations

from typing import Any
from datetime import datetime, timezone

from app.config import get_settings

from .catalog import resolve_emission_factor
from .fields import _extract_company_id, _first_key_value, _matching_entries, _normalize_unit, _sum_key


def _ef_version() -> str:
    return "dynamic"


def _convert_value(value: float, from_unit: str, to_unit: str) -> float:
    conversions: dict[tuple[str, str], float] = {
        ("kwh", "mwh"): 0.001,
        ("mwh", "kwh"): 1000.0,
        ("gj", "kwh"): 277.778,
        ("kwh", "gj"): 0.0036,
        ("kg", "t"): 0.001,
        ("t", "kg"): 1000.0,
        ("g", "kg"): 0.001,
        ("kg", "g"): 1000.0,
        ("litre", "m3"): 0.001,
        ("m3", "litre"): 1000.0,
        ("kgco2e", "tco2e"): 0.001,
        ("tco2e", "kgco2e"): 1000.0,
    }
    key = (_normalize_unit(from_unit), _normalize_unit(to_unit))
    if key not in conversions:
        raise ValueError(f"No conversion defined: {from_unit} to {to_unit}")
    return value * conversions[key]


def _run_tool(tool_name: str, gold_records: dict[str, Any], metric_key: str, arguments: dict[str, Any]) -> dict[str, Any]:
    if tool_name == "direct_read":
        source_key = arguments["source_key"]
        return {
            "metric_key": metric_key,
            "value": round(_first_key_value(gold_records, source_key), 6),
            "unit": arguments["unit"],
            "tool_used": "direct_read",
            "input_keys": [source_key],
            "status": "OK",
        }

    if tool_name == "aggregate_period":
        source_keys = arguments["source_keys"]
        operation = arguments["operation"]
        values: list[float] = []
        used_keys: list[str] = []
        for source_key in source_keys:
            matches = _matching_entries(gold_records, source_key)
            if not matches:
                continue
            values.extend(float(match["value"]) for match in matches)
            used_keys.append(source_key)
        if not values:
            raise ValueError("No values available for aggregation")
        if operation == "sum":
            result = sum(values)
        elif operation == "avg":
            result = sum(values) / len(values)
        elif operation == "max":
            result = max(values)
        elif operation == "min":
            result = min(values)
        else:
            raise ValueError(f"Unsupported aggregate operation: {operation}")
        return {
            "metric_key": metric_key,
            "value": round(result, 6),
            "unit": arguments["unit"],
            "tool_used": f"aggregate_period/{operation}",
            "input_keys": used_keys,
            "status": "OK",
        }

    if tool_name == "apply_emission_factor":
        source_key = arguments["source_key"]
        ef_key = arguments["ef_key"]
        company_id = _extract_company_id(gold_records)
        resolved = resolve_emission_factor(
            company_id=company_id,
            factor_key=ef_key,
            region=arguments.get("region"),
            year=arguments.get("reporting_year"),
            allow_global_fallback=bool(get_settings().ESG_ALLOW_GLOBAL_FACTOR_FALLBACK),
        )
        factor = resolved["factor"]
        resolved_key = resolved["factor_key"]
        quality_flags = list(resolved.get("quality_flags", []))
        methodology = arguments.get("scope2_method")
        if "scope2" in metric_key and not methodology:
            methodology = get_settings().ESG_SCOPE2_DEFAULT_METHOD
            quality_flags.append("method_missing")

        input_value = _sum_key(gold_records, source_key)
        value = input_value * float(factor["value"])
        result_unit = arguments["result_unit"]
        if _normalize_unit(result_unit) == "tco2e":
            value = _convert_value(value, "kgCO2e", "tCO2e")
        factor_metadata = {
            "factor_key": resolved_key,
            "source": factor.get("source"),
            "region": factor.get("region") or arguments.get("region"),
            "year": factor.get("year") or arguments.get("reporting_year"),
            "scope": factor.get("scope"),
            "unit_basis": factor.get("unit_basis") or factor.get("unit"),
            "version": factor.get("version") or _ef_version(),
            "used_fallback_factor": bool(resolved.get("used_fallback_factor")),
        }
        calculation_trace = {
            "tool_used": "apply_emission_factor",
            "input_keys": [source_key],
            "input_values_snapshot": {source_key: round(input_value, 6)},
            "factor_key": resolved_key,
            "factor_version": factor_metadata["version"],
            "conversions": ["kgCO2e->tCO2e"] if _normalize_unit(result_unit) == "tco2e" else [],
            "formula": "activity_value * emission_factor",
            "assumptions": {
                "scope2_method": methodology if "scope2" in metric_key else None,
            },
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        return {
            "metric_key": metric_key,
            "value": round(value, 6),
            "unit": result_unit,
            "tool_used": "apply_emission_factor",
            "input_keys": [source_key],
            "ef_version": factor_metadata["version"],
            "factor_metadata": factor_metadata,
            "calculation_trace": calculation_trace,
            "quality_flags": quality_flags,
            "methodology": {"scope2_method": methodology} if "scope2" in metric_key else {},
            "mapping_confidence": float(arguments.get("mapping_confidence", 0.85)),
            "status": "OK",
        }

    if tool_name == "unit_convert":
        source_key = arguments["source_key"]
        raw_value = _sum_key(gold_records, source_key)
        converted = _convert_value(raw_value, arguments["from_unit"], arguments["to_unit"])
        return {
            "metric_key": metric_key,
            "value": round(converted, 6),
            "unit": arguments["to_unit"],
            "tool_used": "unit_convert",
            "input_keys": [source_key],
            "status": "OK",
        }

    if tool_name == "calc_intensity":
        absolute_key = arguments["absolute_key"]
        denominator_key = arguments["denominator_key"]
        absolute_value = _sum_key(gold_records, absolute_key)
        denominator = _first_key_value(gold_records, denominator_key)
        if denominator == 0:
            raise ZeroDivisionError(f"Denominator '{denominator_key}' is zero")
        return {
            "metric_key": metric_key,
            "value": round(absolute_value / denominator, 6),
            "unit": arguments["unit"],
            "tool_used": "calc_intensity",
            "input_keys": [absolute_key, denominator_key],
            "status": "OK",
        }

    if tool_name == "yoy_delta":
        current_value = _sum_key(gold_records, arguments["current_key"])
        previous_value = _sum_key(gold_records, arguments["previous_key"])
        if previous_value == 0:
            raise ZeroDivisionError(f"Previous key '{arguments['previous_key']}' is zero")
        return {
            "metric_key": metric_key,
            "value": round(((current_value - previous_value) / abs(previous_value)) * 100, 6),
            "unit": arguments["unit"],
            "tool_used": "yoy_delta",
            "input_keys": [arguments["current_key"], arguments["previous_key"]],
            "status": "OK",
        }

    if tool_name == "scope_total":
        total = sum(_sum_key(gold_records, scope_key) for scope_key in arguments["scope_keys"])
        return {
            "metric_key": metric_key,
            "value": round(total, 6),
            "unit": arguments["unit"],
            "tool_used": "scope_total",
            "input_keys": list(arguments["scope_keys"]),
            "status": "OK",
        }

    raise KeyError(f"Unknown tool '{tool_name}'")
