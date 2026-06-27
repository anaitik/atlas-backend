"""Tests for the company general-info intake gate (config-driven fields)."""

from app.services import config_service, company_profile_service


def setup_function():
    config_service.reset_cache_for_tests()


def teardown_function():
    config_service.reset_cache_for_tests()


def test_required_fields_block_completeness():
    complete, missing = company_profile_service.evaluate({})
    assert complete is False
    # Default required keys come from config (legal_name, country, nace, employees, turnover)
    assert "legal_name" in missing
    assert "nace_sector" in missing


def test_complete_when_all_required_filled():
    data = {
        "legal_name": "Acme GmbH",
        "country": "Germany",
        "nace_sector": "C",
        "employee_count_range": "50-249",
        "turnover_range_eur": "40M-150M",
    }
    complete, missing = company_profile_service.evaluate(data)
    assert complete is True
    assert missing == []


def test_blank_strings_do_not_count_as_filled():
    data = {"legal_name": "   ", "country": "DE", "nace_sector": "C",
            "employee_count_range": "50-249", "turnover_range_eur": "40M-150M"}
    complete, missing = company_profile_service.evaluate(data)
    assert complete is False
    assert "legal_name" in missing


def test_field_definitions_are_config_driven():
    # Admin removes the 'country' requirement at runtime → completeness changes.
    sections = config_service.get("company_profile.fields")["sections"]
    for s in sections:
        for f in s["fields"]:
            if f["key"] == "country":
                f["required"] = False
    config_service._cache["company_profile.fields"]["sections"] = sections

    data = {"legal_name": "Acme", "nace_sector": "C",
            "employee_count_range": "50-249", "turnover_range_eur": "40M-150M"}
    complete, _ = company_profile_service.evaluate(data)
    assert complete is True
