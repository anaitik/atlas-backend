"""
VSME interview response — stores per-question answers and AI interpretations.
"""

from __future__ import annotations

from typing import Optional
from pymongo import IndexModel

from app.models.base import BaseDocument


class InterviewResponse(BaseDocument):
    company_id: str
    workspace_id: str
    question_id: str

    # How the user answered
    answer_mode: str = "text"   # "upload" | "value" | "text" | "skipped"

    # Upload mode
    document_id: Optional[str] = None

    # Value mode (direct numeric entry)
    raw_value: Optional[float] = None
    raw_unit: Optional[str] = None

    # Text mode (free-form; goes through AI interpreter)
    raw_text: Optional[str] = None

    # AI interpretation result
    interpreted_metric_code: Optional[str] = None
    interpreted_value: Optional[float] = None
    interpreted_unit: Optional[str] = None
    interpretation_confidence: float = 0.0
    interpretation_reasoning: Optional[str] = None

    # Human decision
    status: str = "pending"   # "pending" | "approved" | "skipped"
    approved_metric_id: Optional[str] = None
    skipped_reason: Optional[str] = None

    # Auto-fill provenance (where a suggested answer came from) + override audit.
    # autofill_source example: {"type": "approved_metric"|"prior_period"|"document",
    #   "label": "Electricity bill Q1", "document_id": "...", "workspace_id": "...",
    #   "metric_id": "...", "confidence": 0.9}
    autofill_source: Optional[dict] = None
    override_reason: Optional[str] = None

    class Settings:
        name = "interview_responses"
        indexes = [
            IndexModel([("workspace_id", 1), ("question_id", 1)], unique=True),
            IndexModel([("workspace_id", 1), ("status", 1)]),
        ]
