from datetime import UTC, datetime
from types import SimpleNamespace

from app.services import report_service, story_service


def test_normalize_interview_answers_preserves_known_questions():
    answers = report_service._normalize_interview_answers(
        [
            {"question_id": "e_initiatives", "answer": "Installed rooftop solar across two sites."},
            {"question_id": "unknown_question", "answer": "Should be ignored."},
            {"question_id": "g_policy", "answer": "   "},
        ]
    )

    assert [item["question_id"] for item in answers] == ["e_initiatives", "g_policy"]
    assert answers[0]["skipped"] is False
    assert answers[1]["skipped"] is True


def test_render_report_markdown_includes_sections_and_caveats():
    report = SimpleNamespace(
        reporting_year=2025,
        exec_summary="Summary text.",
        sections={
            "environmental": {
                "title": "Environmental Performance",
                "content": "Energy usage declined year over year.",
                "data_caveats": ["One regional meter is still pending review."],
            },
            "social": {
                "title": "Social & People Performance",
                "content": "Training hours increased.",
                "data_caveats": [],
            },
        },
    )

    markdown = report_service.render_report_markdown(report)

    assert "# Sustainability Report - 2025" in markdown
    assert "## Environmental Performance" in markdown
    assert "One regional meter is still pending review." in markdown


def test_fallback_story_orders_events_chronologically():
    events = [
        SimpleNamespace(
            created_at=datetime(2025, 1, 3, 10, 30, tzinfo=UTC),
            event_type="REPORT_GENERATED",
            entity_table="reports",
            entity_id="r1",
            actor_user_id=None,
            payload={"reporting_year": 2025},
        ),
        SimpleNamespace(
            created_at=datetime(2025, 1, 2, 9, 15, tzinfo=UTC),
            event_type="DOCUMENT_ANCHORED",
            entity_table="documents",
            entity_id="d1",
            actor_user_id=None,
            payload={"filename": "utility-bill.pdf"},
        ),
    ]

    story = story_service._fallback_story(events, actors={})

    assert "DOCUMENT_ANCHORED" not in story
    assert story.index("Jan 02") < story.index("Jan 03")
