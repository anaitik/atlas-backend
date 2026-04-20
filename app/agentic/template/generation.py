"""
Template generation from sample documents.
"""

from __future__ import annotations

import csv
import io
import json
import re
import tempfile
import shutil
from pathlib import Path
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from app.core.errors import AppError, ErrorCode
from app.llm_factory import create_llm
from app.config import get_settings


SYSTEM_PROMPT = (
    "You are an expert at designing document extraction templates for sustainability data pipelines. "
    "Identify data points for ESG reporting. Pay special attention to energy types: "
    "Electricity (German: Strom, kWh), Water (Wasser, m3), Waste (Abfall/Müll, kg), and Gas. "
    "Ensure values are extracted correctly regardless of document language. "
    "Strictly map regional terms (like Strom to electricity). "
    "Never invent or hallucinate data; if fields are missing, they should evaluate to null. "
    "Return a single valid JSON object only."
)

TEMPLATE_SCHEMA_DESCRIPTION = """
The template JSON must follow this exact schema:
{
  "template_id": "<snake_case_unique_id>",
  "label": "<Human readable label>",
  "document_types": ["pdf"],
  "measurement_type": "<electricity_kwh | gas_kwh | fuel_litres | water_m3 | waste_kg | generic>",
  "output_unit": "<primary unit e.g. kWh | m3 | litres | kg>",
  "fields": [
    {
      "key": "<snake_case_key>",
      "label": "<Human readable label>",
      "type": "<string | float | int | date | bool>",
      "unit": "<unit string or null>",
      "required": <true | false>,
      "hint": "<precise extraction instruction>"
    }
  ],
  "target_metrics_nlp": "<Natural language string explaining what metrics to derive, e.g. Compute total kWh consumed>"
}

Rules for fields:
- Always include a primary value field with key="value"
- Always include relevant date fields such as period_start, period_end, or invoice_date
- Add supplier, facility, or location fields if the document shows them
- Add currency and amount if the document is an invoice
- required=true only for fields essential to downstream metric calculation
"""

RULES_SCHEMA_DESCRIPTION = """
Also generate a companion rules JSON:
{
  "<rule_name>": {
    "description": "<short description>",
    "rule": "<precise instruction for the extraction LLM>"
  }
}

Include rules for unit conversions, date normalization, aggregation logic, net vs gross handling, and label aliases where relevant.
Return the rules JSON as a separate key "rules" inside your main response.
"""


def _get_tesseract_cmd() -> str | None:
    settings = get_settings()
    if getattr(settings, "TESSERACT_CMD", None):
        return settings.TESSERACT_CMD
    return shutil.which("tesseract") or "/usr/bin/tesseract"


def _ocr_bytes(img_bytes: bytes) -> str:
    """Uses Tesseract to OCR an image in bytes with pre-processing."""
    try:
        import pytesseract
        from PIL import Image, ImageOps
        
        tess_path = _get_tesseract_cmd()
        if tess_path and Path(tess_path).exists():
            pytesseract.pytesseract.tesseract_cmd = tess_path
            
        settings = get_settings()
        lang = getattr(settings, "TESSERACT_LANG", "eng+deu")
        psm = getattr(settings, "TESSERACT_PSM", 3)
            
        img = Image.open(io.BytesIO(img_bytes))
        img = ImageOps.grayscale(img)
        # Binarize with a adaptive-like approach
        img = img.point(lambda x: 0 if x < 180 else 255, '1') 
        
        text = pytesseract.image_to_string(img, lang=lang, config=f'--psm {psm}')
        if not text.strip():
            # Try PSM 6 (Uniform block of text) if initial fails
            text = pytesseract.image_to_string(img, lang=lang, config='--psm 6')
            
        return text
    except Exception as e:
        import structlog
        structlog.get_logger().error("ocr_bytes_failed", error=str(e))
        return ""


def _convert_pdf_to_images(pdf_bytes: bytes, max_pages: int = 0) -> list[bytes]:
    """Renders pages of a PDF as PNGs at 288 DPI."""
    images = []
    try:
        import fitz
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        if doc.page_count == 0:
            doc.close()
            return images
            
        num_pages = min(doc.page_count, max_pages) if max_pages > 0 else doc.page_count
        for i in range(num_pages):
            page = doc.load_page(i)
            # 4x zoom = ~288 DPI. High enough for professional OCR results.
            pix = page.get_pixmap(matrix=fitz.Matrix(4, 4)) 
            images.append(pix.tobytes("png"))
        doc.close()
        return images
    except Exception:
        return images


def _extract_pdf_text(path: Path, max_pages: int = 0) -> str:
    try:
        import pymupdf4llm  # type: ignore

        pages = pymupdf4llm.to_markdown(str(path), page_chunks=True, write_images=False)
        if max_pages > 0 and isinstance(pages, list):
            pages = pages[:max_pages]
            
        if pages and isinstance(pages[0], dict):
            return "\n\n".join(page.get("text", page.get("markdown", "")) for page in pages)
        if isinstance(pages, list):
            return "\n\n".join(str(page) for page in pages)
        return str(pages)
    except Exception:
        try:
            from pypdf import PdfReader  # type: ignore

            reader = PdfReader(str(path))
            pages = reader.pages[:max_pages] if max_pages > 0 else reader.pages
            return "\n\n".join(page.extract_text() or "" for page in pages)
        except Exception as exc:
            raise AppError(
                ErrorCode.DEPENDENCY_FAILURE,
                f"Could not read PDF contents: {exc}",
            ) from exc


def _extract_image_text(path: Path) -> str:
    try:
        import pymupdf4llm  # type: ignore

        content = pymupdf4llm.to_markdown(str(path), write_images=False)
        if isinstance(content, list):
            return "\n\n".join(
                block.get("text", block.get("markdown", "")) if isinstance(block, dict) else str(block)
                for block in content
            )
        return str(content)
    except Exception:
        # Fallback to Tesseract OCR if pymupdf4llm fails to get text
        return _ocr_path(path)


def _ocr_path(path: Path) -> str:
    """Uses Tesseract to OCR an image file."""
    try:
        import pytesseract
        from PIL import Image, ImageOps
        
        tess_path = _get_tesseract_cmd()
        if tess_path and Path(tess_path).exists():
            pytesseract.pytesseract.tesseract_cmd = tess_path
            
        settings = get_settings()
        lang = getattr(settings, "TESSERACT_LANG", "eng+deu")
        psm = getattr(settings, "TESSERACT_PSM", 3)
            
        img = Image.open(path)
        img = ImageOps.grayscale(img)
        text = pytesseract.image_to_string(img, lang=lang, config=f'--psm {psm}')
        if not text.strip():
            text = pytesseract.image_to_string(img, lang=lang, config='--psm 6')
        return text
    except Exception as exc:
        raise AppError(
            ErrorCode.DEPENDENCY_FAILURE,
            f"Could not OCR document via Tesseract: {exc}",
        ) from exc


def _extract_csv_text(file_bytes: bytes) -> str:
    decoded = file_bytes.decode("utf-8", errors="replace")
    reader = csv.reader(io.StringIO(decoded))
    rows = list(reader)
    if not rows:
        return ""

    preview_rows = rows[:26]
    return "\n".join(",".join(str(cell) for cell in row) for row in preview_rows)


def extract_document_preview(file_bytes: bytes, filename: str, max_chars: int = 6000, max_pages: int = 0) -> str:
    suffix = Path(filename).suffix.lower()

    if suffix in {".txt", ".md"}:
        return file_bytes.decode("utf-8", errors="replace")[:max_chars]
    if suffix == ".csv":
        return _extract_csv_text(file_bytes)[:max_chars]

    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as temp_file:
        temp_file.write(file_bytes)
        temp_path = Path(temp_file.name)

    try:
        if suffix == ".pdf":
            preview = _extract_pdf_text(temp_path, max_pages=max_pages)
            if not preview.strip():
                # If PDF text extraction returned nothing, it's likely a scan.
                # Render pages and OCR them.
                images = _convert_pdf_to_images(file_bytes, max_pages=max_pages)
                if images:
                    preview = "\n\n".join(_ocr_bytes(img) for img in images)
        elif suffix in {".png", ".jpg", ".jpeg", ".tiff"}:
            preview = _extract_image_text(temp_path)
        else:
            preview = file_bytes.decode("utf-8", errors="replace")
    finally:
        temp_path.unlink(missing_ok=True)

    preview = preview.strip()
    return preview[:max_chars]


def build_generation_prompt(document_preview: str, user_hints: str = "") -> str:
    hint_block = f"\n\n## Additional user hints\n{user_hints.strip()}" if user_hints.strip() else ""
    return (
        "## Task\n"
        "Analyse the document excerpt below and generate an extraction template plus rules "
        "for a sustainability data pipeline.\n\n"
        "## Document excerpt\n"
        f"{document_preview}"
        f"{hint_block}\n\n"
        "## Template schema to follow\n"
        f"{TEMPLATE_SCHEMA_DESCRIPTION}\n\n"
        f"{RULES_SCHEMA_DESCRIPTION}\n\n"
        "## Response format\n"
        'Return a single JSON object with two keys: {"template": {...}, "rules": {...}}.\n'
        "Think carefully about what fields matter for reporting, carbon accounting, and auditability."
    )


def parse_generation_response(raw: str) -> tuple[dict[str, Any], dict[str, Any]]:
    cleaned = raw.strip()
    cleaned = re.sub(r"^```[a-zA-Z]*\s*\n?", "", cleaned)
    cleaned = re.sub(r"\n?```\s*$", "", cleaned)
    cleaned = cleaned.strip()

    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if not match:
            raise AppError(ErrorCode.DEPENDENCY_FAILURE, "Template generation returned invalid JSON.")
        parsed = json.loads(match.group())

    template = parsed.get("template", parsed)
    rules = parsed.get("rules", {})
    if not isinstance(template, dict) or not isinstance(rules, dict):
        raise AppError(ErrorCode.DEPENDENCY_FAILURE, "Template generation returned an unexpected response shape.")
    return template, rules


def validate_generated_template(template: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if not template.get("template_id"):
        errors.append("Missing template_id")
    if not template.get("label"):
        errors.append("Missing label")
    fields = template.get("fields")
    if not isinstance(fields, list) or not fields:
        errors.append("Missing fields list")
        return errors

    for index, field in enumerate(fields):
        if not isinstance(field, dict):
            errors.append(f"Field #{index + 1} is not an object")
            continue
        for key in ("key", "label", "type", "required"):
            if key not in field:
                errors.append(f"Field #{index + 1} missing {key}")
    if "measurement_type" not in template:
        errors.append("Missing measurement_type")
    return errors


def build_compact_system_prompt(
    *,
    template_name: str,
    schema_definition: dict[str, Any],
    target_metrics_nlp: str | None = None,
    measurement_type: str | None = None,
    output_unit: str | None = None,
) -> str:
    schema_json = json.dumps(schema_definition, ensure_ascii=False, indent=2)
    target_text = (target_metrics_nlp or "").strip()

    parts = [
        f"You are extracting structured ESG data for template: {template_name}.",
        f"Measurement context: {measurement_type}." if measurement_type else None,
        f"Primary output unit target: {output_unit}." if output_unit else None,
        "Return JSON only with this payload shape (exact keys):",
        schema_json,
        "Extraction rules:",
        "- Use only evidence present in the document. Never hallucinate.",
        "- If a field is missing or unreadable, return null for that field.",
        "- Preserve units exactly when unit fields exist.",
        "- Normalize dates to ISO format (YYYY-MM-DD) when the source supports it.",
        "- Parse localized number formats correctly (e.g. 1.234,56 vs 1,234.56).",
        "- If a `value` field exists, map the primary measurable ESG quantity to `value`.",
        f"Downstream metric intent: {target_text}" if target_text else None,
    ]
    return "\n".join(part for part in parts if part)


def build_system_prompt_from_generated_template(template: dict[str, Any], rules: dict[str, Any] | None = None) -> str:
    rules = rules or {}
    fields = template.get("fields", [])
    schema_definition = {
        field.get("key"): field.get("type", "string")
        for field in fields
        if isinstance(field, dict) and field.get("key")
    }
    if not schema_definition:
        schema_definition = {"value": "float"}

    target_metrics = template.get("target_metrics_nlp")
    if not target_metrics:
        non_empty_rules = [name for name, value in rules.items() if value]
        if non_empty_rules:
            target_metrics = f"Apply template-specific logic from rules: {', '.join(non_empty_rules[:6])}."

    return build_compact_system_prompt(
        template_name=str(template.get("label") or template.get("template_id") or "Generated Template"),
        schema_definition=schema_definition,
        target_metrics_nlp=str(target_metrics) if target_metrics else None,
        measurement_type=str(template.get("measurement_type")) if template.get("measurement_type") else None,
        output_unit=str(template.get("output_unit")) if template.get("output_unit") else None,
    )


def normalize_generated_template(template: dict[str, Any], rules: dict[str, Any], workspace_id: str | None) -> dict[str, Any]:
    fields = template.get("fields", [])
    schema_definition = {
        field["key"]: field.get("type", "string")
        for field in fields
        if isinstance(field, dict) and field.get("key")
    }
    if not schema_definition:
        raise AppError(ErrorCode.VALIDATION_ERROR, "Generated template did not contain any usable fields.")

    return {
        "name": template.get("label") or template.get("template_id") or "Generated Blueprint",
        "workspace_id": workspace_id,
        "schema_definition": schema_definition,
        "system_prompt": build_system_prompt_from_generated_template(template, rules),
        "target_metrics_nlp": template.get("target_metrics_nlp") or "Automatically detect and calculate total values",
    }


async def generate_template_from_document(
    file_bytes: bytes,
    filename: str,
    workspace_id: str | None = None,
    user_hints: str = "",
) -> dict[str, Any]:
    document_preview = extract_document_preview(file_bytes, filename, max_pages=3)
    prompt = build_generation_prompt(document_preview, user_hints)

    try:
        llm = create_llm(temperature=0.2)
        
        # If preview is empty even after all fallback attempts, then we fail
        if not document_preview.strip():
            raise AppError(ErrorCode.VALIDATION_ERROR, "No readable text found in document.")

        response = await llm.ainvoke(
            [
                SystemMessage(content=SYSTEM_PROMPT),
                HumanMessage(content=prompt),
            ]
        )
    except Exception as exc:
        raise AppError(ErrorCode.DEPENDENCY_FAILURE, f"Template generation failed: {exc}") from exc

    content = getattr(response, "content", response)
    if isinstance(content, list):
        content = " ".join(
            block.get("text", "") if isinstance(block, dict) else str(block)
            for block in content
        )

    template, rules = parse_generation_response(str(content))
    validation_errors = validate_generated_template(template)
    normalized_template = normalize_generated_template(template, rules, workspace_id)

    return {
        "filename": filename,
        "document_preview": document_preview,
        "template": template,
        "rules": rules,
        "normalized_template": normalized_template,
        "validation_errors": validation_errors,
    }
