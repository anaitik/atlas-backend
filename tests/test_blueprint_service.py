"""Tests for blueprint seeding, catalogue binding, and safe fallback."""

import pytest

from app.services import config_service, blueprint_service
from app.agentic.interview import generation


def setup_function():
    config_service.reset_cache_for_tests()


def test_seed_questions_from_config():
    qs = blueprint_service._seed_questions()
    assert len(qs) == 15  # the canonical VSME-15 seed
    assert all(q.source == "canonical" and q.status == "approved" for q in qs)
    assert all(q.metric_code for q in qs)  # every seed question binds to a metric


def test_question_to_dict_shape():
    q = blueprint_service._seed_questions()[0]
    d = blueprint_service.question_to_dict(q)
    for key in ("id", "pillar", "metric_code", "question_text", "answer_modes"):
        assert key in d


def test_canonical_catalog_matches_scored_metrics():
    catalog = generation.canonical_catalog()
    codes = {c["metric_code"] for c in catalog}
    # The scored metrics the engine recognises must be present in the catalogue.
    assert "ENERGY_ELEC_CONSUMPTION" in codes
    assert "GHG_TOTAL_EMISSIONS" in codes
    assert "WORKFORCE_MIN_WAGE_COMPLIANCE" in codes


@pytest.mark.asyncio
async def test_get_active_questions_falls_back_without_db():
    """No DB / no blueprint → canonical default questions, not locked."""
    questions, locked = await blueprint_service.get_active_questions("ws-nodb")
    assert locked is False
    assert len(questions) == 15
