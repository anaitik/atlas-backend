"""
Extraction AI models. Part of Pack 05.
"""

from __future__ import annotations

from typing import Any, Dict, Optional
from pydantic import Field, field_validator
from pymongo import IndexModel

from app.models.base import BaseDocument

class SchemaTemplate(BaseDocument):
    """
    Instructions and expected JSON schema for LLM extraction.
    E.g. "GRI 305 Emissions"
    """
    name: str
    company_id: str
    workspace_id: Optional[str] = None
    
    # The actual schema the agent should force the LLM to return
    schema_definition: Dict[str, Any]
    
    # Prompt context specific to this template
    system_prompt: str
    
    # Natural language description for what metrics the agent should derive
    target_metrics_nlp: Optional[str] = None
    
    class Settings:
        name = "schema_templates"
        indexes = [
            IndexModel([("company_id", 1), ("workspace_id", 1), ("name", 1)]),
        ]

class ExtractedData(BaseDocument):
    """
    The result of an LLM extraction run against a document & template.
    """
    company_id: str
    workspace_id: str
    
    document_id: str
    template_id: str
    
    # The populated schema mapped by the AI
    payload: Dict[str, Any] = Field(default_factory=dict)
    
    # AI Confidence for exception routing
    confidence_score: float = Field(default=0.0)
    exception_reason: Optional[str] = None
    
    # Human-in-the-loop review state
    status: str = "pending_review"  # pending_review, approved, rejected
    reviewer: Optional[str] = None
    
    @field_validator("payload", mode="before")
    @classmethod
    def validate_payload(cls, v: Any) -> Dict[str, Any]:
        if v is None:
            return {}
        return v
    
    class Settings:
        name = "extracted_data"
        indexes = [
            IndexModel([("company_id", 1), ("workspace_id", 1), ("status", 1)]),
            IndexModel([("document_id", 1), ("template_id", 1)]),
        ]
