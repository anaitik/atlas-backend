from app.agentic.metric.tools import _run_tool


def test_apply_emission_factor_returns_trace_and_metadata():
    gold_records = {
        "ex-1": {
            "company_id": "c-1",
            "fields": {
                "electricity_kwh": {"value": 100.0, "unit": "kWh"},
            },
        }
    }

    record = _run_tool(
        "apply_emission_factor",
        gold_records,
        "scope2_kgco2e",
        {
            "source_key": "electricity_kwh",
            "ef_key": "electricity_grid_de",
            "result_unit": "kgCO2e",
            "region": "DE",
            "reporting_year": 2026,
            "scope2_method": "location_based",
            "mapping_confidence": 0.9,
        },
    )

    assert record["status"] == "OK"
    assert "factor_metadata" in record
    assert "calculation_trace" in record
    assert record["factor_metadata"]["factor_key"] == "electricity_grid_de"
    assert record["methodology"]["scope2_method"] == "location_based"
