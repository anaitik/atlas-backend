"""Tests for the runtime config store and that the scorer is config-driven."""

from types import SimpleNamespace

import pytest

from app.services import config_service
from app.services import esg_score_service as svc
from app.services.interview_service import get_questions

QUESTIONS = get_questions()
_QID_TO_METRIC = {q["id"]: q["metric_code"] for q in QUESTIONS}


@pytest.fixture(autouse=True)
def _isolate_config():
    config_service.reset_cache_for_tests()
    yield
    config_service.reset_cache_for_tests()


def _resp(qid, value):
    return SimpleNamespace(
        question_id=qid, interpreted_metric_code=_QID_TO_METRIC.get(qid),
        interpreted_value=value, status="approved",
        interpretation_confidence=1.0, interpretation_reasoning="",
    )


def _ws():
    return SimpleNamespace(nace_sector="C", turnover_range_eur="40M-150M")


def test_defaults_present():
    rubric = config_service.get("scoring.rubric")
    assert rubric["pillar_weights"]["environmental"] == 0.40
    assert config_service.get("scoring.sector_benchmarks")["sectors"]["C"]
    assert config_service.get("company_profile.fields")["sections"]


def test_get_with_key_and_default():
    assert config_service.get("scoring.rubric", "carbon_outlier_ratio") == 5
    assert config_service.get("nope.ns", "missing", "fallback") == "fallback"


def test_scorer_honors_config_override():
    """Changing pillar weights via config must change the recomputed score."""
    responses = [
        _resp("vsme-e2", 100),   # perfect environmental signal
        _resp("vsme-s2", 0),     # poor social signal
    ]
    base = svc.compute_score(_ws(), responses, QUESTIONS)["performance_score"]

    # Flip weights so social dominates → score must drop.
    config_service._cache["scoring.rubric"]["pillar_weights"] = {
        "environmental": 0.0, "social": 1.0, "governance": 0.0,
    }
    social_heavy = svc.compute_score(_ws(), responses, QUESTIONS)["performance_score"]

    assert social_heavy < base
