from types import SimpleNamespace

from app.services import metric_service


def test_coerce_numeric_handles_numbers_and_numeric_strings():
    assert metric_service._coerce_numeric(42) == 42.0
    assert metric_service._coerce_numeric("42.5") == 42.5
    assert metric_service._coerce_numeric("1,234.50 kWh") == 1234.5
    assert metric_service._coerce_numeric("1.234,50 kWh") == 1234.5
    assert metric_service._coerce_numeric("not-a-number") is None


def test_metric_candidates_prefer_primary_value_field():
    extraction = SimpleNamespace(
        id="ex-1",
        document_id="doc-1",
        payload={"value": "400.75", "unit": "kWh", "amount": "99.00"},
    )
    template = SimpleNamespace(id="tpl-1", name="Electricity Consumption")

    candidates = metric_service._metric_candidates(extraction, template)

    assert len(candidates) == 1
    assert candidates[0].metric_code == "tpl-1:value:ex-1"
    assert candidates[0].name == "Electricity Consumption"
    assert candidates[0].unit == "kWh"
    assert candidates[0].value == 400.75


def test_metric_candidates_fall_back_to_numeric_payload_fields():
    extraction = SimpleNamespace(
        id="ex-2",
        document_id="doc-2",
        payload={"co2e": "18.2", "co2e_unit": "tCO2e", "site": "Berlin"},
    )
    template = SimpleNamespace(id="tpl-2", name="Emissions Template")

    candidates = metric_service._metric_candidates(extraction, template)

    assert len(candidates) == 1
    assert candidates[0].metric_code == "tpl-2:co2e:ex-2"
    assert candidates[0].unit == "tCO2e"
    assert candidates[0].value == 18.2


def test_metric_candidates_ignore_accounting_and_date_fields():
    extraction = SimpleNamespace(
        id="ex-3",
        document_id="doc-3",
        payload={
            "invoice_date": "2025-03-31",
            "total_gross_amount": "659.89",
            "total_net_amount": "554.53",
            "facility_location": "Berlin",
        },
    )
    template = SimpleNamespace(id="tpl-3", name="Invoice Template")

    candidates = metric_service._metric_candidates(extraction, template)

    assert candidates == []


def test_metric_candidates_include_primary_and_additional_metric_signals():
    extraction = SimpleNamespace(
        id="ex-4",
        document_id="doc-4",
        payload={
            "value": "400.75",
            "unit": "kWh",
            "scope2_co2e": "112.0",
            "scope2_co2e_unit": "kgCO2e",
        },
    )
    template = SimpleNamespace(id="tpl-4", name="Electricity and Emissions")

    candidates = metric_service._metric_candidates(extraction, template)

    assert len(candidates) == 2
    assert candidates[0].metric_code == "tpl-4:value:ex-4"
    assert candidates[1].metric_code == "tpl-4:scope2_co2e:ex-4"


def test_build_workspace_metric_summary_converts_emissions_units():
    metrics = [
        SimpleNamespace(
            metric_code="scope2_tco2e",
            unit="tCO2e",
            value=0.5,
            pillar="environmental",
            status="approved",
        ),
        SimpleNamespace(
            metric_code="scope1_tco2e",
            unit="kgCO2e",
            value=500.0,
            pillar="environmental",
            status="approved",
        ),
    ]

    summary = metric_service.build_workspace_metric_summary(metrics, "c-1", "w-1")
    cards = {card["key"]: card for card in summary["cards"]}

    assert cards["emissions"]["value"] == 1.0
    assert cards["emissions"]["unit"] == "tCO2e"
    assert summary["environmental_count"] == 2


def test_build_workspace_metric_summary_uses_canonical_electricity_when_available():
    metrics = [
        SimpleNamespace(
            metric_code="electricity_kwh_total",
            unit="kWh",
            value=1200.0,
            pillar="environmental",
            status="approved",
        ),
        SimpleNamespace(
            metric_code="tpl:value:ex-1",
            unit="kWh",
            value=800.0,
            pillar="environmental",
            status="approved",
        ),
    ]

    summary = metric_service.build_workspace_metric_summary(metrics, "c-1", "w-1")
    cards = {card["key"]: card for card in summary["cards"]}

    assert cards["electricity"]["value"] == 1200.0
