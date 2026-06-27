"""Tests for the auto-fill metric-vocabulary bridge (the prefill fix)."""

from types import SimpleNamespace

from app.services import answer_resolver as ar
from app.services import config_service

ALIASES = config_service.get("interview.metric_aliases")


def _m(code, value, unit, status="approved"):
    return SimpleNamespace(metric_code=code, value=value, unit=unit, status=status,
                           id=f"id-{code}", name=code, source_extracted_data_ids=[])


def test_engine_code_bridges_to_interview():
    """electricity_kwh_total (engine) resolves the ENERGY_ELEC_CONSUMPTION question."""
    metrics = [_m("electricity_kwh_total", 50000, "kWh")]
    hit = ar._resolve_from_metrics(metrics, ALIASES["ENERGY_ELEC_CONSUMPTION"])
    assert hit is not None
    value, _, approved = hit
    assert value == 50000 and approved is True


def test_raw_extraction_unit_match_bridges():
    """A raw composite-code extraction with a kWh unit still maps to electricity."""
    metrics = [_m("tpl-abc:value:ext123", 1200, "kWh", status="pending")]
    hit = ar._resolve_from_metrics(metrics, ALIASES["ENERGY_ELEC_CONSUMPTION"])
    assert hit is not None
    value, _, approved = hit
    assert value == 1200 and approved is False  # pending -> suggestion


def test_emissions_alias_and_unit_conversion():
    metrics = [_m("scope2_tco2e", 12.5, "tCO2e")]
    hit = ar._resolve_from_metrics(metrics, ALIASES["GHG_TOTAL_EMISSIONS"])
    assert hit and hit[0] == 12.5


def test_kgco2e_converted_to_tonnes():
    metrics = [_m("scope2_kgco2e_raw", 2500, "kgCO2e", status="pending")]
    hit = ar._resolve_from_metrics(metrics, ALIASES["GHG_TOTAL_EMISSIONS"])
    assert hit is not None and abs(hit[0] - 2.5) < 1e-6  # 2500 kg -> 2.5 t


def test_raw_extraction_bills_sum():
    """Multiple raw kWh extractions (no canonical total) sum into one figure."""
    metrics = [_m("tpl:value:e1", 1000, "kWh", status="pending"),
               _m("tpl:value:e2", 500, "kWh", status="pending")]
    hit = ar._resolve_from_metrics(metrics, ALIASES["ENERGY_ELEC_CONSUMPTION"])
    assert hit and hit[0] == 1500 and hit[2] is False


def test_canonical_total_used_alone_not_double_counted():
    """When the engine's aggregated total exists, use it as-is (don't add raw rows)."""
    metrics = [_m("electricity_kwh_total", 50000, "kWh"),
               _m("tpl:value:e1", 1000, "kWh", status="pending")]
    hit = ar._resolve_from_metrics(metrics, ALIASES["ENERGY_ELEC_CONSUMPTION"])
    assert hit and hit[0] == 50000  # canonical total, raw row not added


def test_no_match_returns_none():
    metrics = [_m("WORKFORCE_GENDER_FEMALE_PCT", 40, "%")]
    assert ar._resolve_from_metrics(metrics, ALIASES["ENERGY_ELEC_CONSUMPTION"]) is None
