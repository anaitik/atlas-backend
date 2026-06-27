"""Tests for the Atlas ESG Score v2 engine (pure scoring logic)."""

from types import SimpleNamespace

from app.services import esg_score_service as svc
from app.services.interview_service import get_questions

QUESTIONS = get_questions()
_QID_TO_METRIC = {q["id"]: q["metric_code"] for q in QUESTIONS}


def _resp(qid, value=None, status="approved", confidence=1.0, reasoning=""):
    # The engine binds to interpreted_metric_code, so map the question's canonical code.
    return SimpleNamespace(
        question_id=qid,
        interpreted_metric_code=_QID_TO_METRIC.get(qid),
        interpreted_value=value,
        status=status,
        interpretation_confidence=confidence,
        interpretation_reasoning=reasoning,
    )


def _ws(sector="C", turnover="40M-150M"):
    return SimpleNamespace(nace_sector=sector, turnover_range_eur=turnover)


def test_completion_no_longer_equals_performance():
    """A company that answers everything with BAD values must NOT score 100."""
    bad = [
        _resp("vsme-e1", 5_000_000),      # huge electricity
        _resp("vsme-e2", 0),              # 0% renewable
        _resp("vsme-e3", 200_000),        # lots of fuel
        _resp("vsme-e4", 9000),           # high emissions
        _resp("vsme-e6", 0),              # 0% recycling
        _resp("vsme-s1", 50),
        _resp("vsme-s2", 5),              # very unbalanced
        _resp("vsme-s3", 0),              # below min wage
        _resp("vsme-s4", 30),             # many incidents
        _resp("vsme-g1", 0), _resp("vsme-g2", 0), _resp("vsme-g3", 0),
        _resp("vsme-g4", 0), _resp("vsme-g5", 0),
    ]
    out = svc.compute_score(_ws(), bad, QUESTIONS)
    assert out["completeness_score"] >= 90      # they answered almost everything
    assert out["performance_score"] < 35        # but performance is poor
    assert out["grade"] in ("D", "E")
    assert any(f["code"] == "min_wage" for f in out["flags"])


def test_strong_performer_scores_high():
    good = [
        _resp("vsme-e1", 80_000),
        _resp("vsme-e2", 100),            # 100% renewable
        _resp("vsme-e3", 0),
        _resp("vsme-e4", 5),              # low emissions -> low intensity for sector C
        _resp("vsme-e6", 95),            # 95% recycling
        _resp("vsme-s1", 40),
        _resp("vsme-s2", 47),            # balanced
        _resp("vsme-s3", 1),             # min wage ok
        _resp("vsme-s4", 0),             # zero incidents
        _resp("vsme-g1", 1), _resp("vsme-g2", 1), _resp("vsme-g3", 1),
        _resp("vsme-g4", 1), _resp("vsme-g5", 1),
    ]
    out = svc.compute_score(_ws(), good, QUESTIONS)
    assert out["performance_score"] >= 80
    assert out["grade"] == "A"
    assert out["carbon_benchmark"]["ratio_to_peers"] < 1


def test_missing_data_omits_not_inflates():
    """Unanswered questions must not be scored as 0 or 100 — they're omitted."""
    partial = [
        _resp("vsme-e2", 50),
        _resp("vsme-g1", 1),
    ]
    out = svc.compute_score(_ws(), partial, QUESTIONS)
    assert out["completeness_score"] < 20
    # carbon intensity has no GHG -> not scored
    ci = next(i for i in out["breakdown"]["environmental"] if i["key"] == "carbon_intensity")
    assert ci["scored"] is False
    assert out["performance_score"] is not None  # still computed from what exists


def test_no_sector_benchmark_does_not_fabricate():
    out = svc.compute_score(_ws(sector="OTHER"), [_resp("vsme-e4", 1000)], QUESTIONS)
    assert out["carbon_benchmark"] is None
    assert any(f["code"] == "no_sector_benchmark" for f in out["flags"])


def test_plausibility_flags_out_of_range():
    out = svc.compute_score(_ws(), [_resp("vsme-e2", 150)], QUESTIONS)
    assert any(f["code"] == "out_of_range" and f["severity"] == "critical" for f in out["flags"])


def test_ghg_without_energy_flagged():
    out = svc.compute_score(_ws(), [_resp("vsme-e4", 500, reasoning="From our carbon report")], QUESTIONS)
    assert any(f["code"] == "ghg_without_energy" for f in out["flags"])


def test_pillar_grant_scoping_prevents_leak():
    """A bank granted only environmental must not receive social/governance detail."""
    responses = [
        _resp("vsme-e2", 80),
        _resp("vsme-s3", 0),   # below min wage — a SOCIAL critical flag
        _resp("vsme-g1", 1),
    ]
    full = svc.compute_score(_ws(), responses, QUESTIONS)
    env_only = svc.compute_score(_ws(), responses, QUESTIONS, allowed_pillars=["environmental"])

    # Full result exposes the social min-wage flag; the scoped one must not.
    assert any(f["code"] == "min_wage" for f in full["flags"])
    assert not any(f["code"] == "min_wage" for f in env_only["flags"])
    # Scoped result only carries the granted pillar.
    assert set(env_only["breakdown"].keys()) == {"environmental"}
    assert set(env_only["pillar_performance"].keys()) == {"environmental"}
    assert "social" not in env_only["pillar_completeness"]
