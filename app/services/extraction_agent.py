"""Compatibility shim for extraction agent service."""

from app.agentic.extraction.workflow import (
    _extract_llm_text,
    _fallback_value,
    run_extraction,
    run_extraction_prerun,
    submit_review,
)

__all__ = [
    "run_extraction",
    "run_extraction_prerun",
    "submit_review",
    "_fallback_value",
    "_extract_llm_text",
]
