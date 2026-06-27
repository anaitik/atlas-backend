"""
Tests for interview_service — ESG scoring, GHG auto-calc, prefill logic.
These are pure unit tests: no DB, no LLM calls.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ── ESG Score Calculation ─────────────────────────────────────────

def _make_mock_response(question_id: str, status: str = "approved") -> MagicMock:
    from app.services.interview_service import get_question_by_id
    q = get_question_by_id(question_id)
    r = MagicMock()
    r.question_id = question_id
    r.status = status
    r.answer_mode = "value"
    r.interpretation_confidence = 0.95
    r.interpreted_value = 100.0
    r.interpreted_unit = "kWh"
    r.interpreted_metric_code = q["metric_code"] if q else None
    r.interpretation_reasoning = ""
    return r


def test_pillar_score_weighting():
    """ESG score = E*40% + S*30% + G*30%."""
    from app.services.interview_service import get_questions
    questions = get_questions()

    e_qs = [q for q in questions if q["pillar"] == "environmental"]
    s_qs = [q for q in questions if q["pillar"] == "social"]
    g_qs = [q for q in questions if q["pillar"] == "governance"]

    # All environmental answered → E=100, S=0, G=0 → overall = 40
    e_score = 100
    s_score = 0
    g_score = 0
    overall = round(e_score * 0.40 + s_score * 0.30 + g_score * 0.30)
    assert overall == 40

    # All answered → overall = 100
    overall_full = round(100 * 0.40 + 100 * 0.30 + 100 * 0.30)
    assert overall_full == 100

    # None answered → 0
    assert round(0 * 0.40 + 0 * 0.30 + 0 * 0.30) == 0


def test_question_count():
    """VSME Module A must have exactly 15 questions."""
    from app.services.interview_service import get_questions
    questions = get_questions()
    assert len(questions) == 15


def test_question_ids():
    """All question IDs must be unique and follow expected pattern."""
    from app.services.interview_service import get_questions
    questions = get_questions()
    ids = [q["id"] for q in questions]
    assert len(ids) == len(set(ids)), "Duplicate question IDs found"
    env_ids = {q["id"] for q in questions if q["pillar"] == "environmental"}
    soc_ids = {q["id"] for q in questions if q["pillar"] == "social"}
    gov_ids = {q["id"] for q in questions if q["pillar"] == "governance"}
    assert all(i.startswith("vsme-e") for i in env_ids)
    assert all(i.startswith("vsme-s") for i in soc_ids)
    assert all(i.startswith("vsme-g") for i in gov_ids)


def test_pillar_question_counts():
    """Environmental=6, Social=4, Governance=5."""
    from app.services.interview_service import get_questions
    questions = get_questions()
    e = sum(1 for q in questions if q["pillar"] == "environmental")
    s = sum(1 for q in questions if q["pillar"] == "social")
    g = sum(1 for q in questions if q["pillar"] == "governance")
    assert e == 6, f"Expected 6 environmental questions, got {e}"
    assert s == 4, f"Expected 4 social questions, got {s}"
    assert g == 5, f"Expected 5 governance questions, got {g}"


def test_get_question_by_id_returns_none_for_unknown():
    from app.services.interview_service import get_question_by_id
    assert get_question_by_id("does-not-exist") is None


def test_get_question_by_id_returns_correct():
    from app.services.interview_service import get_question_by_id
    q = get_question_by_id("vsme-e1")
    assert q is not None
    assert q["metric_code"] == "ENERGY_ELEC_CONSUMPTION"
    assert q["pillar"] == "environmental"


# ── GHG Auto-Calculation ──────────────────────────────────────────

def test_ghg_calculation_formula():
    """Scope2 + Scope1 formula correctness."""
    kwh = 10_000
    litres = 500
    scope2_kg = kwh * 0.276       # EEA EU27 avg
    scope1_kg = litres * 2.68784  # diesel DESNZ 2024
    total_t = round((scope1_kg + scope2_kg) / 1000, 4)

    assert scope2_kg == pytest.approx(2760.0, abs=0.01)
    assert scope1_kg == pytest.approx(1343.92, abs=0.01)
    assert total_t == pytest.approx(4.1039, abs=0.001)


@pytest.mark.asyncio
async def test_ghg_calc_skipped_if_no_energy_data():
    """_try_calculate_ghg should do nothing when neither e1 nor e3 is approved."""
    from app.services.interview_service import _try_calculate_ghg

    with patch("app.services.interview_service.get_response", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = None  # no responses
        # Should not raise
        await _try_calculate_ghg("ws-1", "co-1", "vsme-e1")
        # get_response called for both e1 and e3
        assert mock_get.call_count >= 1


@pytest.mark.asyncio
async def test_ghg_calc_does_not_overwrite_human_answer():
    """Human-entered vsme-e4 must never be overwritten by auto-calc."""
    from app.services.interview_service import _try_calculate_ghg

    mock_e1 = MagicMock()
    mock_e1.status = "approved"
    mock_e1.interpreted_value = 10_000.0

    mock_e3 = MagicMock()
    mock_e3.status = "approved"
    mock_e3.interpreted_value = 500.0

    mock_e4 = MagicMock()
    mock_e4.status = "approved"
    mock_e4.interpretation_reasoning = "Direct numeric entry by user"  # human

    async def fake_get_response(ws_id, qid):
        return {"vsme-e1": mock_e1, "vsme-e3": mock_e3, "vsme-e4": mock_e4}.get(qid)

    with patch("app.services.interview_service.get_response", side_effect=fake_get_response):
        await _try_calculate_ghg("ws-1", "co-1", "vsme-e1")
        # e4 save should NOT have been called
        mock_e4.save_with_timestamp.assert_not_called()


# ── Progress Scoring ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_progress_returns_correct_structure():
    """get_progress returns expected keys, including the v2 atlas_score."""
    from app.services.interview_service import get_progress

    with patch("app.services.interview_service.get_responses", new_callable=AsyncMock) as mock_responses, \
         patch("app.models.workspace.Workspace.get", new_callable=AsyncMock) as mock_ws:
        mock_responses.return_value = []
        mock_ws.return_value = None
        result = await get_progress("workspace-123")

    assert "total_questions" in result
    assert "approved" in result
    assert "pillar_scores" in result
    assert "overall_esg_score" in result
    assert "data_quality_score" in result
    assert "atlas_score" in result
    assert result["total_questions"] == 15
    assert result["approved"] == 0
    assert result["overall_esg_score"] == 0
    # With no data, completeness is 0 and performance is not computable.
    assert result["atlas_score"]["completeness_score"] == 0
    assert result["atlas_score"]["performance_score"] is None


@pytest.mark.asyncio
async def test_completeness_and_performance_are_distinct():
    """The core fix: 100% completion must NOT mean a perfect performance score.

    Every answer here is 100.0 — which means 100% female (unbalanced) and a
    sky-high incident rate. A completion-based score would read 100; the real
    performance score must not.
    """
    from app.services.interview_service import get_progress, get_questions

    questions = get_questions()
    responses = [_make_mock_response(q["id"], "approved") for q in questions]

    with patch("app.services.interview_service.get_responses", new_callable=AsyncMock) as mock_r, \
         patch("app.models.workspace.Workspace.get", new_callable=AsyncMock) as mock_ws:
        mock_r.return_value = responses
        mock_ws.return_value = None
        result = await get_progress("workspace-123")

    assert result["approved"] == 15
    assert result["completion_pct"] == 100
    assert result["atlas_score"]["completeness_score"] == 100
    # Performance reflects the (poor) values, not the completeness.
    assert result["overall_esg_score"] < 100
    assert result["overall_esg_score"] == result["atlas_score"]["performance_score"]
