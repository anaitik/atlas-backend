"""
Interview blueprint — the per-workspace, AI-generated, human-curated set of ESG
interview questions. Replaces the static VSME-15 as the source of interview
questions while keeping every question bound to a canonical metric_code so the
score and benchmark stay comparable across companies.

Lifecycle: draft → pending_review → approved.
A `system_audit_officer` (Atlas-side) reviews/edits/deletes questions and approves
the blueprint; the MSME interview is locked until status == "approved".
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field
from pymongo import IndexModel

from app.models.base import BaseDocument


class BlueprintQuestion(BaseModel):
    local_id: str                                  # stable id within the blueprint
    metric_code: Optional[str] = None              # canonical scored binding
    metric_name: str = ""
    pillar: str = "environmental"
    category: str = ""
    question_text: str
    help_text: str = ""
    answer_modes: List[str] = Field(default_factory=lambda: ["value", "text"])
    value_schema: Optional[Dict[str, Any]] = None
    requirement: str = "optional"                  # mandatory | optional
    skip_condition: Optional[str] = None
    grounding_citation: Optional[str] = None       # which source justifies this question
    bank_relevance: str = ""
    source: str = "canonical"                      # canonical | ai_added
    status: str = "approved"                       # approved | pending | rejected
    edit_history: List[Dict[str, Any]] = Field(default_factory=list)


class InterviewBlueprint(BaseDocument):
    workspace_id: str
    company_id: str
    status: str = "draft"                           # draft | pending_review | approved
    generated_by: str = "seed"                      # seed | ai
    grounding_refs: List[str] = Field(default_factory=list)
    questions: List[BlueprintQuestion] = Field(default_factory=list)
    approved_by: Optional[str] = None
    approved_at: Optional[str] = None

    class Settings:
        name = "interview_blueprints"
        indexes = [
            IndexModel([("workspace_id", 1)], unique=True),
            IndexModel([("status", 1)]),
        ]
