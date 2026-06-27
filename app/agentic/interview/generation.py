"""
AI interview generation — produces a company-tailored, standard-grounded set of
ESG interview questions.

Design (option a, locked): the AI tailors *questions* (phrasing, applicability,
sector-specific additions) but binds them to the **canonical scored metric set**
so scores stay comparable across companies. Questions it cannot bind to a
canonical metric are emitted as `ai_added` (extra disclosure, not scored) and
flagged for the audit officer / admin canonicalization.

Everything here is best-effort: any failure returns an empty augmentation, and
the blueprint still works from its canonical seed (no hard dependency on the LLM).
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List

from app.services import config_service


def canonical_catalog() -> List[Dict[str, Any]]:
    """The canonical, scored metric set the AI must bind to (from config seed)."""
    questions = config_service.get("interview.default_blueprint").get("questions", [])
    catalog = []
    for q in questions:
        catalog.append({
            "metric_code": q.get("metric_code"),
            "metric_name": q.get("metric_name"),
            "pillar": q.get("pillar"),
            "unit": (q.get("value_schema") or {}).get("unit", ""),
        })
    return catalog


def _grounding_text() -> str:
    sources = config_service.get("interview.grounding").get("sources", [])
    parts = []
    for s in sources:
        label = s.get("label", s.get("id", ""))
        text = s.get("text", "")
        parts.append(f"[{s.get('id')}] {label}: {text}".strip())
    return "\n".join(parts)


def _parse_json_array(raw: str) -> List[Dict[str, Any]]:
    cleaned = re.sub(r"^```[a-zA-Z]*\s*", "", raw.strip())
    cleaned = re.sub(r"\s*```$", "", cleaned).strip()
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"\[.*\]", cleaned, re.DOTALL)
        if not match:
            return []
        parsed = json.loads(match.group())
    if isinstance(parsed, dict):
        parsed = parsed.get("questions", [])
    return parsed if isinstance(parsed, list) else []


async def generate_tailored_questions(profile_data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Return AI-proposed questions tailored to the company profile. Best-effort."""
    gen = config_service.get("interview.generation")
    catalog = canonical_catalog()
    valid_codes = {c["metric_code"] for c in catalog if c["metric_code"]}

    try:
        from app.llm_factory import create_llm
        from langchain_core.messages import HumanMessage, SystemMessage

        llm = create_llm(temperature=gen.get("temperature", 0.2), max_tokens=2048)
        system = SystemMessage(content=gen.get("system_prompt", ""))
        human = HumanMessage(content=(
            "## Company profile\n"
            f"{json.dumps(profile_data, ensure_ascii=False)}\n\n"
            "## Grounding (cite the source id in grounding_citation)\n"
            f"{_grounding_text()}\n\n"
            "## Canonical metric catalogue (bind metric_code to one of these where possible)\n"
            f"{json.dumps(catalog, ensure_ascii=False)}\n\n"
            f"Produce up to {gen.get('max_questions', 25)} interview questions tailored to this "
            "company and sector. Prefer questions that bind to a canonical metric_code; you may add "
            "sector-specific questions with metric_code=null (they will be extra disclosure). "
            "Return a JSON array only; each item:\n"
            '{"metric_code": <code|null>, "pillar": "environmental|social|governance", '
            '"category": <str>, "question_text": <str>, "help_text": <str>, '
            '"answer_modes": ["upload"|"value"|"text"], "requirement": "mandatory|optional", '
            '"grounding_citation": <source id>, "bank_relevance": <str>}'
        ))
        result = await llm.ainvoke([system, human])
        content = getattr(result, "content", "")
        if isinstance(content, list):
            content = " ".join(b.get("text", "") if isinstance(b, dict) else str(b) for b in content)
        items = _parse_json_array(str(content))
    except Exception:
        return []

    # Normalise + tag source based on whether the metric binds to the scored set.
    out: List[Dict[str, Any]] = []
    for it in items:
        if not isinstance(it, dict) or not it.get("question_text"):
            continue
        code = it.get("metric_code")
        out.append({
            "metric_code": code if code in valid_codes else None,
            "pillar": it.get("pillar", "environmental"),
            "category": it.get("category", ""),
            "question_text": it["question_text"],
            "help_text": it.get("help_text", ""),
            "answer_modes": it.get("answer_modes") or ["value", "text"],
            "requirement": "mandatory" if it.get("requirement") == "mandatory" else "optional",
            "grounding_citation": it.get("grounding_citation"),
            "bank_relevance": it.get("bank_relevance", ""),
            "source": "ai_added",
        })
    return out
