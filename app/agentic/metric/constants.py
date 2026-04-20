"""Constants for the metric agent workflow."""

from __future__ import annotations

from pathlib import Path
from typing import Any


DATA_DIR = Path(__file__).resolve().parents[2] / "data"
MAX_ATTEMPTS = 2

ROUTER_SYSTEM = (
    "You are a metric calculation router. "
    "Choose the best deterministic tool for the target metric. "
    "Return JSON only. Do not perform arithmetic yourself."
)

RECOMMENDER_SYSTEM = (
    "You are a sustainability metric planner. "
    "You receive only JSON structure summaries from approved extraction batches: template names, field aliases, units, and JSON paths. "
    "Do not use or infer any numeric values. "
    "Recommend the smallest practical set of derivable metric targets from the catalog. "
    "Return JSON only."
)

GENERIC_FIELD_NAMES = {
    "amount",
    "count",
    "number",
    "quantity",
    "result",
    "total",
    "value",
}

METRIC_PRIORITY = {
    "electricity_kwh_total": 10,
    "electricity_kwh_winema": 11,
    "electricity_kwh_transfer": 11,
    "gas_kwh_total": 10,
    "fuel_litres_total": 10,
    "headcount": 10,
    "board_independence_pct": 10,
    "whistleblower_cases": 10,
    "scope1_kgco2e": 20,
    "scope2_kgco2e": 20,
    "scope1_tco2e": 30,
    "scope2_tco2e": 30,
    "total_ghg_tco2e": 40,
    "energy_intensity_kwh_per_employee": 50,
    "emission_intensity_kgco2e_per_employee": 50,
    "training_hours_per_employee": 50,
    "lost_time_injury_rate": 50,
    "electricity_yoy_pct": 60,
    "emissions_yoy_pct": 60,
}

TOOL_REGISTRY: dict[str, dict[str, Any]] = {
    "direct_read": {
        "description": "Read a single numeric key directly.",
        "args": ["source_key", "unit"],
    },
    "unit_convert": {
        "description": "Convert units after summing matching records for the source key.",
        "args": ["source_key", "from_unit", "to_unit"],
    },
    "apply_emission_factor": {
        "description": "Multiply a summed activity value by one emission factor.",
        "args": ["source_key", "ef_key", "result_unit"],
    },
    "aggregate_period": {
        "description": "Aggregate one or more keys across repeated records using sum, avg, min, or max.",
        "args": ["source_keys", "operation", "unit"],
    },
    "calc_intensity": {
        "description": "Divide an absolute metric by a denominator metric.",
        "args": ["absolute_key", "denominator_key", "unit"],
    },
    "yoy_delta": {
        "description": "Calculate year-on-year percentage change.",
        "args": ["current_key", "previous_key", "unit"],
    },
    "scope_total": {
        "description": "Sum Scope 1, 2, and 3 metric keys into one total.",
        "args": ["scope_keys", "unit"],
    },
}
