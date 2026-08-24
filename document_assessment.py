"""Whole-document assessment for student-owned mathematics papers.

New analyses send the completed work, and optionally a mark scheme, directly
to a reasoning model. The compact marking response is validated before
optional context and bilingual-feedback passes, so provider failures or
contradictory output never become zero marks.
"""

from __future__ import annotations

import base64
import http.client
import json
import math
import time
import urllib.error
from pathlib import Path
from typing import Any, Callable

import fitz

import config
from curricula import curriculum_prompt_context
from ocr import api_post_json, cxsee_api_base


ASSESSMENT_PROMPT_VERSION = "whole-document-assessment-v3-gpt55-direct"
VALID_STATUSES = {"graded", "estimated", "uncertain", "ungraded"}
CONTRADICTION_PHRASES = (
    "blank",
    "empty page",
    "unrelated",
    "wrong question",
    "not visible",
    "cannot be read",
    "could not be read",
    "no student work",
    "no answer shown",
)
ProgressCallback = Callable[[str, str], None]


class AssessmentValidationError(ValueError):
    """Raised when a provider result is unsafe to display as an assessment."""

    def __init__(self, errors: list[str]):
        self.errors = errors
        super().__init__("; ".join(errors))


def _notify_progress(
    callback: ProgressCallback | None,
    substage: str,
    detail: str = "",
) -> None:
    if not callback:
        return
    try:
        callback(substage, detail)
    except Exception:
        # Progress reporting is diagnostic only. A transient database/UI issue
        # must never discard a valid assessment.
        return


def assessment_schema() -> dict[str, Any]:
    nullable_number = {"type": ["number", "null"]}
    question = {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "label",
            "maximum_marks",
            "awarded_mark",
            "status",
            "confidence",
            "evidence_pages",
            "rationale",
            "topic",
        ],
        "properties": {
            "label": {"type": "string"},
            "maximum_marks": nullable_number,
            "awarded_mark": nullable_number,
            "status": {
                "type": "string",
                "enum": sorted(VALID_STATUSES),
            },
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
            "evidence_pages": {
                "type": "array",
                "items": {"type": "integer", "minimum": 1},
            },
            "rationale": {"type": "string"},
            "topic": {"type": "string"},
        },
    }
    return {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "assessment_mode",
            "total_max_marks",
            "questions",
            "warnings",
        ],
        "properties": {
            "assessment_mode": {
                "type": "string",
                "enum": ["estimate", "detailed"],
            },
            "total_max_marks": nullable_number,
            "questions": {
                "type": "array",
                "minItems": 1,
                "items": question,
            },
            "warnings": {
                "type": "array",
                "items": {"type": "string"},
            },
        },
    }


def document_context_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["questions"],
        "properties": {
            "questions": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": [
                        "label",
                        "question_text",
                        "evidence_quote",
                        "skill",
                    ],
                    "properties": {
                        "label": {"type": "string"},
                        "question_text": {"type": "string"},
                        "evidence_quote": {"type": "string"},
                        "skill": {"type": "string"},
                    },
                },
            }
        },
    }


def feedback_schema() -> dict[str, Any]:
    """Small text-only contract for bilingual student feedback.

    Marking stays in the direct-PDF call. Keeping translation and coaching out
    of that vision response prevents long papers from exceeding the provider's
    upstream generation window.
    """
    string_array = {"type": "array", "items": {"type": "string"}}
    return {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "questions",
            "strengths",
            "weaknesses",
            "recommendations",
            "warnings_zh",
            "strengths_zh",
            "weaknesses_zh",
            "recommendations_zh",
        ],
        "properties": {
            "questions": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": [
                        "label",
                        "rationale_zh",
                        "improvement",
                        "improvement_zh",
                    ],
                    "properties": {
                        "label": {"type": "string"},
                        "rationale_zh": {"type": "string"},
                        "improvement": {"type": "string"},
                        "improvement_zh": {"type": "string"},
                    },
                },
            },
            "strengths": string_array,
            "weaknesses": string_array,
            "recommendations": string_array,
            "warnings_zh": string_array,
            "strengths_zh": string_array,
            "weaknesses_zh": string_array,
            "recommendations_zh": string_array,
        },
    }


def _pdf_data_url(path: str) -> str:
    payload = Path(path).read_bytes()
    return "data:application/pdf;base64," + base64.b64encode(payload).decode("ascii")


def _pdf_inline_part(path: str) -> dict[str, Any]:
    return {
        "inlineData": {
            "mimeType": "application/pdf",
            "data": base64.b64encode(Path(path).read_bytes()).decode("ascii"),
        }
    }


def _render_document_image_parts(
    path: str,
    *,
    label: str,
    dpi: int,
) -> list[dict[str, Any]]:
    parts: list[dict[str, Any]] = []
    with fitz.open(path) as document:
        total = len(document)
        matrix = fitz.Matrix(dpi / 72, dpi / 72)
        for index, page in enumerate(document):
            pixmap = page.get_pixmap(matrix=matrix, alpha=False)
            encoded = base64.b64encode(
                pixmap.tobytes("jpeg", jpg_quality=88)
            ).decode("ascii")
            parts.extend(
                [
                    {
                        "type": "text",
                        "text": f"{label}, page {index + 1} of {total}:",
                    },
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/jpeg;base64,{encoded}",
                        },
                    },
                ]
            )
    return parts


def _render_responses_document_image_parts(
    path: str,
    *,
    label: str,
    dpi: int,
) -> list[dict[str, Any]]:
    parts: list[dict[str, Any]] = []
    with fitz.open(path) as document:
        total = len(document)
        matrix = fitz.Matrix(dpi / 72, dpi / 72)
        for index, page in enumerate(document):
            pixmap = page.get_pixmap(matrix=matrix, alpha=False)
            encoded = base64.b64encode(
                pixmap.tobytes("jpeg", jpg_quality=88)
            ).decode("ascii")
            parts.extend(
                [
                    {
                        "type": "input_text",
                        "text": f"{label}, page {index + 1} of {total}:",
                    },
                    {
                        "type": "input_image",
                        "image_url": f"data:image/jpeg;base64,{encoded}",
                        "detail": "high",
                    },
                ]
            )
    return parts


def _document_render_dpi(paths: list[str]) -> int:
    pages = sum(_page_count(path) for path in paths)
    if pages <= 4:
        return 160
    if pages <= 10:
        return 130
    if pages <= 20:
        return 100
    if pages <= 40:
        return 75
    return 60


def _page_count(path: str) -> int:
    with fitz.open(path) as document:
        return len(document)


def _prompt(
    mode: str,
    repair_errors: list[str] | None = None,
    expected_maximum_marks: float | None = None,
    curriculum: dict[str, Any] | None = None,
) -> str:
    mode_instruction = (
        """
This is the DETAILED mode. You receive:
1. the student's complete worked paper, which normally includes the printed
   questions and handwriting; and
2. the complete official mark scheme.

Use the mark scheme exactly, including method, accuracy, independent, and
follow-through marks. Match questions across the two complete documents using
their printed labels, order, mathematical content, and page context. Do not
require a separate question paper. Return an exact mark only when supported by
visible work and the scheme. Use `uncertain` with a defensible range when a
small region is unreadable, and `ungraded` with null awarded_mark when the
evidence is genuinely insufficient.
"""
        if mode == "detailed"
        else """
This is the ESTIMATE mode. You receive only the student's complete worked
paper. Infer the printed questions, available marks, and demonstrated methods
from that document. Produce a conservative estimated score range, not a claim
of official marking. Identify useful strengths, weaknesses, and next steps.
Use `estimated` or `uncertain`, and use `ungraded` with null awarded_mark when
the evidence is genuinely insufficient.
"""
    )
    repair = ""
    if repair_errors:
        repair = (
            "\nYour previous structured response was rejected for these reasons:\n- "
            + "\n- ".join(repair_errors[:12])
            + "\nReturn a fully corrected assessment of the documents.\n"
        )
    expected_total = ""
    if expected_maximum_marks is not None:
        expected_total = f"""
The student supplied an expected maximum of {expected_maximum_marks:g} marks
for this complete paper. Treat this as a coverage checksum, not evidence for
awarding marks. Read all pages, include every visible question and subquestion,
and ensure the sum of question maximum_marks and total_max_marks both equal
{expected_maximum_marks:g}. If the document genuinely contradicts this value,
explain the discrepancy in warnings without inventing questions or marks.
"""
    subject = str((curriculum or {}).get("subject") or "mathematics")
    curriculum_instruction = (
        curriculum_prompt_context(curriculum)
        if curriculum
        else "Use Cambridge IGCSE Additional Mathematics 0606 terminology."
    )
    subject_rules = ""
    if subject == "physics":
        subject_rules = """
Physics-specific rules:
- Check formula choice, substitution, units, significant figures, graphs,
  vector/scalar meaning, and scientific explanations.
- Distinguish knowledge, calculation, explanation, and experimental skills.
- For practical work, evaluate variables, apparatus, method, tables, graphs,
  uncertainty, conclusions, and improvements.
"""
    elif subject == "chemistry":
        subject_rules = """
Chemistry-specific rules:
- Check chemical formulae, balanced symbol and ionic equations, state symbols,
  reaction conditions, conservation of mass, mole or mass relationships, and
  units before awarding calculation marks.
- Distinguish an observed colour, precipitate, gas, temperature, or other
  experimental result from the student's inference or explanation.
- For practical work, check apparatus, reagents, sequence, laboratory safety,
  variables, observations, conclusions, and improvements.
- Stay within the selected Grade 9 curriculum; do not require senior-high
  chemistry terminology or methods to earn credit.
"""
    return rf"""
You are Sumkora's senior {subject} assessor. Assess the
documents as a whole. Work question by question internally, but do not rely on
an external OCR mapper or assume one answer page per question.

{mode_instruction}

Curriculum boundary:
{curriculum_instruction}
{subject_rules}

Rules:
- Read every page. Page numbers in evidence_pages refer to the completed-work
  PDF, starting at 1.
- First establish a complete inventory of question labels across the entire
  document. Do not stop after the first few pages. Before returning, verify
  that the questions array covers student work from the beginning through the
  final page and that no visible top-level question or subquestion was omitted.
- Preserve labels such as Q1, Q2(a), and Q2(b) when separable. Do not invent
  questions or omit visible answered questions.
- A positive mark requires visible supporting student evidence.
- A blank, unrelated, wrong, or unreadable region must never receive a
  positive mark.
- Do not award marks merely because an answer appears in the mark scheme.
- awarded_mark must be null for a truly ungradable item. Keep maximum_marks
  when the official allocation is identifiable; use null only when the
  allocation itself cannot be determined.
- Confidence describes confidence in the mark and document matching together.
- Transcribe the student's final answer exactly. Before calling a final answer
  correct, compare its signs, digits, variables, and domain with the expected
  answer. A visible wrong final value cannot receive its accuracy mark even
  when earlier method marks are earned.
- Keep rationales concise, specific, and understandable to a student.
- Totals must be arithmetically consistent with question results.
- The overall estimate must satisfy min <= estimate <= max <= total maximum.
- Never turn a technical or reading failure into zero marks.
- Return only the requested structured JSON.
- Keep every rationale to one concise sentence. Marking and complete document
  coverage are the only jobs in this call; full question transcription,
  evidence excerpts, and bilingual coaching are produced separately after the
  marks have been validated.
- Before returning, verify that maximum_marks sum to total_max_marks and that
  awarded_mark values sum to the score implied by the question results.
{expected_total}
{repair}
"""


def _extract_response_text(result: dict[str, Any]) -> str:
    error = result.get("error")
    if isinstance(error, dict) and error.get("message"):
        raise RuntimeError(f"Assessment provider error: {error['message']}")
    direct = result.get("output_text")
    if isinstance(direct, str) and direct.strip():
        return direct.strip()
    parts: list[str] = []
    for item in result.get("output") or []:
        if not isinstance(item, dict):
            continue
        for content in item.get("content") or []:
            if not isinstance(content, dict):
                continue
            value = content.get("text")
            if isinstance(value, str) and value.strip():
                parts.append(value)
    if not parts:
        raise RuntimeError("Assessment provider returned no structured text.")
    return "\n".join(parts)


def _extract_gemini_text(result: dict[str, Any]) -> str:
    parts: list[str] = []
    for candidate in result.get("candidates") or []:
        if not isinstance(candidate, dict):
            continue
        content = candidate.get("content") or {}
        for part in content.get("parts") or []:
            if not isinstance(part, dict) or part.get("thought"):
                continue
            value = part.get("text")
            if isinstance(value, str) and value.strip():
                parts.append(value.strip())
    if not parts:
        reasons = [
            str(candidate.get("finishReason") or "")
            for candidate in result.get("candidates") or []
            if isinstance(candidate, dict)
        ]
        reason = ", ".join(value for value in reasons if value) or "unknown"
        raise RuntimeError(
            f"Assessment provider returned no structured text (finish reason: {reason})."
        )
    return "\n".join(parts)


def _strip_json_fence(text: str) -> str:
    value = text.strip()
    if not value.startswith("```"):
        return value
    lines = value.splitlines()
    if lines and lines[0].strip().startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    return "\n".join(lines).strip()


def _repair_json_string_escapes(text: str) -> str:
    """Escape provider-emitted TeX commands without altering valid JSON escapes."""
    repaired: list[str] = []
    in_string = False
    index = 0
    length = len(text)
    while index < length:
        char = text[index]
        if char == '"':
            backslashes = 0
            cursor = index - 1
            while cursor >= 0 and text[cursor] == "\\":
                backslashes += 1
                cursor -= 1
            if backslashes % 2 == 0:
                in_string = not in_string
            repaired.append(char)
            index += 1
            continue
        if char != "\\" or not in_string or index + 1 >= length:
            repaired.append(char)
            index += 1
            continue

        next_char = text[index + 1]
        if next_char in {'"', "\\", "/"}:
            repaired.extend((char, next_char))
            index += 2
            continue
        if (
            next_char == "u"
            and index + 5 < length
            and all(
                value in "0123456789abcdefABCDEF"
                for value in text[index + 2 : index + 6]
            )
        ):
            repaired.extend(text[index : index + 6])
            index += 6
            continue
        if next_char in "bfnrt":
            if index + 2 >= length or not text[index + 2].islower():
                repaired.extend((char, next_char))
                index += 2
                continue

        repaired.extend(("\\", "\\"))
        index += 1
    return "".join(repaired)


def _parse_provider_json(text: str) -> dict[str, Any]:
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        repaired = _repair_json_string_escapes(text)
        try:
            parsed = json.loads(repaired)
        except json.JSONDecodeError:
            # Some compatible providers leave literal newlines or tabs inside
            # otherwise valid JSON strings. Python's non-strict parser accepts
            # those control characters after TeX backslashes have been fixed.
            parsed = json.loads(repaired, strict=False)
    if not isinstance(parsed, dict):
        raise AssessmentValidationError(
            ["structured assessment response was not a JSON object"]
        )
    return parsed


def _thinking_budget(effort: str) -> int:
    return {
        "minimal": 512,
        "low": 1024,
        "medium": 4096,
        "high": 8192,
    }.get(effort, 4096)


def _retryable_provider_error(error: Exception) -> bool:
    if isinstance(error, urllib.error.HTTPError):
        if error.code in {408, 429, 500, 502, 503, 504}:
            return True
        if error.code == 400:
            # Some OpenAI-compatible gateways expose the Responses API but
            # temporarily reject native PDF parts for an otherwise
            # vision-capable model. In that case the controlled recovery
            # request below renders the same complete document as page
            # images. Do not retry unrelated 400s (for example, a malformed
            # schema), because changing the document transport cannot repair
            # those requests.
            try:
                body = error.read().decode("utf-8", errors="replace")
            except Exception:
                body = ""
            normalized = body.lower()
            return "input_file" in normalized and any(
                marker in normalized
                for marker in (
                    "invalid value",
                    "not supported",
                    "unsupported",
                    "supported values",
                )
            )
        return False
    return isinstance(
        error,
        (
            urllib.error.URLError,
            TimeoutError,
            ConnectionResetError,
            http.client.RemoteDisconnected,
        ),
    )


def _call_structured_document_model(
    *,
    model: str,
    prompt: str,
    schema: dict[str, Any],
    document_paths: list[str],
    reasoning_effort: str,
    document_texts: list[tuple[str, str]] | None = None,
    timeout_seconds: int | None = None,
    retries: int | None = None,
    render_documents_as_images: bool = False,
    render_dpi_override: int | None = None,
) -> tuple[str, dict[str, Any]]:
    request_timeout = timeout_seconds or config.WHOLE_DOCUMENT_TIMEOUT_SECONDS
    request_retries = (
        config.CXSEE_MAX_RETRIES if retries is None else max(0, retries)
    )
    # CXSEE's current gpt-5.5 Responses route rejects native `input_file`
    # parts even though the same vision model accepts `input_image`. Preserve
    # whole-document assessment by sending every rendered page in order; this
    # is model vision input, not OCR text or question-to-question mapping.
    if (
        model.strip().lower() == "gpt-5.5"
        and document_paths
        and not document_texts
    ):
        render_documents_as_images = True
    schema_instruction = (
        "\n\nYou must follow this exact JSON Schema yourself. Return every "
        "required field with the exact property names and enum values. "
        "Return one JSON object only, without Markdown fences or commentary. "
        "Escape every backslash inside JSON strings.\n"
        + json.dumps(schema, ensure_ascii=False)
    )
    if model.startswith("qwen"):
        dpi = render_dpi_override or _document_render_dpi(document_paths)
        content: list[dict[str, Any]] = [
            {"type": "text", "text": prompt + schema_instruction},
        ]
        if document_texts:
            content.extend(
                {
                    "type": "text",
                    "text": f"=== {label} ===\n{text}",
                }
                for label, text in document_texts
            )
        else:
            for index, path in enumerate(document_paths):
                label = (
                    "Completed student work"
                    if index == 0
                    else "Official mark scheme"
                )
                content.extend(
                    _render_document_image_parts(path, label=label, dpi=dpi)
                )
        result = api_post_json(
            f"{cxsee_api_base()}/chat/completions",
            {
                "model": model,
                "messages": [{"role": "user", "content": content}],
                "temperature": 0,
                "max_tokens": 16384,
                "response_format": {"type": "json_object"},
            },
            headers={"Authorization": f"Bearer {config.CXSEE_API_KEY}"},
            timeout=request_timeout,
            retries=request_retries,
        )
        choices = result.get("choices") or []
        message = (
            choices[0].get("message") or {}
            if choices and isinstance(choices[0], dict)
            else {}
        )
        value = message.get("content")
        if not isinstance(value, str) or not value.strip():
            finish_reason = (
                choices[0].get("finish_reason")
                if choices and isinstance(choices[0], dict)
                else "unknown"
            )
            raise RuntimeError(
                "Assessment provider returned no structured text "
                f"(finish reason: {finish_reason})."
            )
        return _strip_json_fence(value), {
            "provider": "cxsee_qwen_vision",
            "usage": result.get("usage") or {},
            "response_id": result.get("id"),
            "model_version": result.get("model"),
            "render_dpi": None if document_texts else dpi,
        }

    if model.startswith("gemini-"):
        gateway_schema_instruction = (
            "\n\nThe API gateway may not enforce responseJsonSchema. You must "
            "therefore follow this exact JSON Schema yourself. Return every "
            "required field with the exact property names and enum values. "
            "Escape every backslash inside JSON strings.\n"
            + json.dumps(schema, ensure_ascii=False)
        )
        result = api_post_json(
            (
                f"{config.CXSEE_BASE_URL.rstrip('/')}/v1beta/models/"
                f"{model}:generateContent"
            ),
            {
                "contents": [
                    {
                        "parts": [
                            {"text": prompt + gateway_schema_instruction},
                            *[_pdf_inline_part(path) for path in document_paths],
                        ]
                    }
                ],
                "generationConfig": {
                    "temperature": 0,
                    "maxOutputTokens": 32768,
                    "thinkingConfig": {
                        "thinkingBudget": _thinking_budget(reasoning_effort),
                        "includeThoughts": False,
                    },
                    "responseMimeType": "application/json",
                    "responseJsonSchema": schema,
                },
            },
            headers={"Authorization": f"Bearer {config.CXSEE_API_KEY}"},
            timeout=request_timeout,
            retries=request_retries,
        )
        return _strip_json_fence(_extract_gemini_text(result)), {
            "provider": "cxsee_gemini_native",
            "usage": result.get("usageMetadata") or {},
            "response_id": result.get("responseId"),
            "model_version": result.get("modelVersion"),
        }

    text_sections = [prompt]
    if document_texts:
        text_sections.extend(
            f"=== {label} ===\n{text}" for label, text in document_texts
        )
        content: list[dict[str, Any]] = [
            {"type": "input_text", "text": "\n\n".join(text_sections)}
        ]
        render_dpi = None
    elif render_documents_as_images:
        content = [{"type": "input_text", "text": prompt}]
        render_dpi = render_dpi_override or _document_render_dpi(document_paths)
        for index, path in enumerate(document_paths):
            label = (
                "Completed student work"
                if index == 0
                else "Official mark scheme"
            )
            content.extend(
                _render_responses_document_image_parts(
                    path,
                    label=label,
                    dpi=render_dpi,
                )
            )
    else:
        content = [{"type": "input_text", "text": prompt}]
        content.extend(
            {
                "type": "input_file",
                "filename": Path(path).name,
                "file_data": _pdf_data_url(path),
            }
            for path in document_paths
        )
        render_dpi = None
    result = api_post_json(
        f"{cxsee_api_base()}/responses",
        {
            "model": model,
            "input": [{"role": "user", "content": content}],
            "reasoning": {"effort": reasoning_effort},
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "sumkora_structured_document_result",
                    "strict": True,
                    "schema": schema,
                }
            },
            "max_output_tokens": 16384,
            "store": False,
        },
        headers={"Authorization": f"Bearer {config.CXSEE_API_KEY}"},
        timeout=request_timeout,
        retries=1 if retries is None else max(0, retries),
    )
    return _strip_json_fence(_extract_response_text(result)), {
        "provider": (
            "cxsee_responses_images"
            if render_documents_as_images
            else "cxsee_responses"
        ),
        "usage": result.get("usage") or {},
        "response_id": result.get("id"),
        "model_version": result.get("model"),
        "render_dpi": render_dpi,
    }


def _as_number(value: Any) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def validate_assessment(
    assessment: dict[str, Any],
    *,
    mode: str,
    completed_work_pages: int,
    expected_maximum_marks: float | None = None,
) -> dict[str, Any]:
    errors: list[str] = []
    if assessment.get("assessment_mode") != mode:
        errors.append("assessment_mode does not match the requested mode")
    questions = assessment.get("questions")
    if not isinstance(questions, list) or not questions:
        raise AssessmentValidationError(["no question results were returned"])

    labels: set[str] = set()
    graded_marks = 0.0
    known_maximum = 0.0
    ungraded_available = 0.0
    normalized_questions = []
    for index, original in enumerate(questions):
        if not isinstance(original, dict):
            errors.append(f"question {index + 1} is not an object")
            continue
        item = dict(original)
        label = str(item.get("label") or "").strip()
        if not label:
            errors.append(f"question {index + 1} has no label")
            label = f"Q{index + 1}"
        if label in labels:
            errors.append(f"duplicate question label {label}")
        labels.add(label)

        status = str(item.get("status") or "")
        if status not in VALID_STATUSES:
            errors.append(f"{label} has invalid status {status!r}")
        maximum = _as_number(item.get("maximum_marks"))
        mark = _as_number(item.get("awarded_mark"))
        confidence = _as_number(item.get("confidence"))
        if confidence is None or not 0 <= confidence <= 1:
            errors.append(f"{label} confidence is outside 0 to 1")
            confidence = 0.0
        if status == "ungraded" and mark is not None:
            errors.append(f"{label} is ungraded but has an awarded mark")
        if status != "ungraded":
            if maximum is None or maximum <= 0:
                errors.append(f"{label} has no positive maximum mark")
            if mark is None:
                errors.append(f"{label} has no awarded mark")
            elif maximum is not None and not 0 <= mark <= maximum:
                errors.append(f"{label} mark is outside 0 to maximum")

        pages = item.get("evidence_pages")
        if not isinstance(pages, list):
            errors.append(f"{label} evidence_pages is not a list")
            pages = []
        normalized_pages = []
        for page in pages:
            if (
                not isinstance(page, int)
                or isinstance(page, bool)
                or not 1 <= page <= completed_work_pages
            ):
                errors.append(f"{label} cites invalid completed-work page {page!r}")
            elif page not in normalized_pages:
                normalized_pages.append(page)
        if status != "ungraded" and not normalized_pages:
            errors.append(f"{label} has a mark but no evidence page")

        rationale = str(item.get("rationale") or "")
        evidence = str(item.get("evidence_quote") or "")
        contradiction_text = f"{rationale} {evidence}".lower()
        if mark is not None and mark > 0 and any(
            phrase in contradiction_text for phrase in CONTRADICTION_PHRASES
        ):
            errors.append(f"{label} awards marks while describing missing or wrong evidence")

        item.update(
            {
                "label": label,
                "status": status,
                "maximum_marks": maximum,
                "awarded_mark": mark,
                "confidence": confidence,
                "evidence_pages": normalized_pages,
                "question_text": str(item.get("question_text") or "").strip(),
                "question_latex": str(
                    item.get("question_latex") or item.get("question_text") or ""
                ).strip(),
                "evidence_quote": evidence.strip(),
                "rationale": rationale.strip(),
                "rationale_zh": str(item.get("rationale_zh") or "").strip(),
                "topic": str(item.get("topic") or "Unclassified").strip(),
                "skill": str(item.get("skill") or "unclassified").strip(),
                "improvement": str(item.get("improvement") or "").strip(),
                "improvement_zh": str(item.get("improvement_zh") or "").strip(),
            }
        )
        normalized_questions.append(item)
        if maximum is not None and maximum > 0:
            known_maximum += maximum
            if status == "ungraded":
                ungraded_available += maximum
        if mark is not None and status != "ungraded":
            graded_marks += mark

    total_maximum = _as_number(assessment.get("total_max_marks"))
    if expected_maximum_marks is not None:
        total_maximum = float(expected_maximum_marks)
        if known_maximum and abs(total_maximum - known_maximum) > 0.51:
            errors.append(
                f"question maximums total {known_maximum:g}, but the student "
                f"supplied {total_maximum:g}; re-read every page and include "
                "all questions before returning the assessment"
            )
        provider_total = _as_number(assessment.get("total_max_marks"))
        if provider_total is not None and abs(provider_total - total_maximum) > 0.51:
            errors.append(
                f"provider total maximum {provider_total:g} does not match "
                f"the student-supplied maximum {total_maximum:g}"
            )
    elif mode == "estimate" and known_maximum:
        total_maximum = known_maximum
    elif total_maximum is None:
        total_maximum = known_maximum or None
    elif known_maximum and abs(total_maximum - known_maximum) > 0.51:
        errors.append(
            f"total maximum {total_maximum:g} does not equal question maximums "
            f"{known_maximum:g}"
        )

    score_min = _as_number(assessment.get("estimated_score_min"))
    score = _as_number(assessment.get("estimated_score"))
    score_max = _as_number(assessment.get("estimated_score_max"))
    if mode == "estimate" and known_maximum:
        score = graded_marks
        score_min = sum(
            float(item["awarded_mark"])
            for item in normalized_questions
            if item["awarded_mark"] is not None
            and item["status"] in {"estimated", "graded"}
        )
        score_max = min(
            known_maximum,
            graded_marks
            + sum(
                max(
                    0.0,
                    float(item["maximum_marks"] or 0)
                    - float(item["awarded_mark"] or 0),
                )
                for item in normalized_questions
                if item["status"] == "uncertain"
            )
            + ungraded_available,
        )
    if mode == "detailed":
        derived_min = sum(
            float(item["awarded_mark"])
            for item in normalized_questions
            if item["awarded_mark"] is not None and item["status"] == "graded"
        )
        derived_score = graded_marks
        derived_max = derived_score + sum(
            float(item["maximum_marks"] or 0) - float(item["awarded_mark"] or 0)
            for item in normalized_questions
            if item["status"] in {"uncertain", "ungraded"}
        )
        score_min, score, score_max = derived_min, derived_score, derived_max
    if None in (total_maximum, score_min, score, score_max):
        errors.append("overall score range is incomplete")
    elif not (0 <= score_min <= score <= score_max <= total_maximum):
        errors.append("overall score range is not ordered within the total maximum")
    elif mode == "estimate":
        calibration_margin = max(3.0, float(total_maximum) * 0.075)
        score_min = min(float(score_min), max(0.0, float(score) - calibration_margin))
        score_max = max(
            float(score_max),
            min(float(total_maximum), float(score) + calibration_margin),
        )

    if errors:
        raise AssessmentValidationError(errors)

    result = dict(assessment)
    result.update(
        {
            "assessment_mode": mode,
            "total_max_marks": round(float(total_maximum), 2),
            "estimated_score_min": round(float(score_min), 2),
            "estimated_score": round(float(score), 2),
            "estimated_score_max": round(float(score_max), 2),
            "questions": normalized_questions,
        }
    )
    for field in (
        "strengths",
        "weaknesses",
        "recommendations",
        "warnings",
        "strengths_zh",
        "weaknesses_zh",
        "recommendations_zh",
        "warnings_zh",
    ):
        values = result.get(field)
        result[field] = [
            str(value).strip()
            for value in (values if isinstance(values, list) else [])
            if str(value).strip()
        ]
    if mode == "estimate":
        result["warnings"].append(
            "The score range includes a calibration margin because no official "
            "mark scheme was supplied."
        )
    return result


def _context_targets(assessment: dict[str, Any]) -> list[dict[str, Any]]:
    targets = []
    for item in assessment["questions"]:
        maximum = item.get("maximum_marks")
        awarded = item.get("awarded_mark")
        if (
            item.get("status") in {"uncertain", "ungraded"}
            or maximum is None
            or awarded is None
            or float(awarded) < float(maximum)
        ):
            targets.append(
                {
                    "label": item["label"],
                    "topic": item["topic"],
                    "evidence_pages": item["evidence_pages"],
                }
            )
    return targets


def _ensure_question_display_fields(
    assessment: dict[str, Any],
) -> dict[str, Any]:
    result = dict(assessment)
    questions = []
    for original in assessment["questions"]:
        item = dict(original)
        fallback = f"{item['label']} — {item['topic']}"
        item["question_text"] = item.get("question_text") or fallback
        item["question_latex"] = item.get("question_latex") or item["question_text"]
        item["skill"] = item.get("skill") or item["topic"]
        questions.append(item)
    result["questions"] = questions
    return result


def _document_context_prompt(
    assessment: dict[str, Any],
    curriculum: dict[str, Any] | None = None,
) -> str:
    targets = _context_targets(assessment)
    subject = str((curriculum or {}).get("subject") or "mathematics")
    boundary = (
        curriculum_prompt_context(curriculum)
        if curriculum
        else "Cambridge IGCSE Additional Mathematics 0606."
    )
    return rf"""
You are transcribing only the lost-mark questions from the same complete
student {subject} paper that has already been marked. Read the attached PDF
visually and return exactly one item for each target label below, in the same
order. Do not mark or recalculate anything.

For question_text, transcribe the complete readable printed question. A
subquestion must stand alone: repeat its parent stem, definitions, diagram or
table context, sequence notation, and any earlier result it depends on. Place
mathematics inside valid TeX delimiters \( ... \) or \[ ... \], using proper
TeX such as \frac, \sqrt, superscripts, subscripts, inequalities, vectors,
matrices, and set notation. Keep prose outside TeX delimiters.

For evidence_quote, briefly transcribe the exact visible student step or final
answer relevant to the lost mark. Use an empty string only when no work is
visible. skill must be a concise {subject} skill name.

Curriculum boundary: {boundary}

Target labels and already-verified page hints:
{json.dumps(targets, ensure_ascii=False)}
"""


def _apply_document_context(
    assessment: dict[str, Any],
    context: dict[str, Any],
) -> dict[str, Any]:
    targets = [item["label"] for item in _context_targets(assessment)]
    received = context.get("questions")
    if not isinstance(received, list):
        raise AssessmentValidationError(["document context questions are missing"])
    by_label: dict[str, dict[str, Any]] = {}
    for item in received:
        if not isinstance(item, dict):
            raise AssessmentValidationError(
                ["document context contains a non-object question"]
            )
        label = str(item.get("label") or "").strip()
        if not label or label in by_label:
            raise AssessmentValidationError(
                [f"document context has an invalid or duplicate label {label!r}"]
            )
        by_label[label] = item
    if set(by_label) != set(targets):
        raise AssessmentValidationError(
            ["document context labels do not match the lost-mark questions"]
        )

    enriched = dict(assessment)
    questions = []
    for original in assessment["questions"]:
        item = dict(original)
        source = by_label.get(item["label"])
        if source:
            item["question_text"] = str(source.get("question_text") or "").strip()
            item["question_latex"] = item["question_text"]
            item["evidence_quote"] = str(
                source.get("evidence_quote") or ""
            ).strip()
            item["skill"] = str(source.get("skill") or item["topic"]).strip()
        else:
            item["question_text"] = (
                item.get("question_text")
                or f"{item['label']} — {item['topic']}"
            )
            item["question_latex"] = (
                item.get("question_latex") or item["question_text"]
            )
            item["skill"] = item.get("skill") or item["topic"]
        questions.append(item)
    enriched["questions"] = questions
    return enriched


def _enrich_document_context(
    assessment: dict[str, Any],
    *,
    model: str,
    document_paths: list[str],
    timeout_seconds: int | None = None,
    curriculum: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    targets = _context_targets(assessment)
    if not targets:
        return assessment, {"status": "not_needed", "duration_ms": 0}
    started = time.monotonic()
    response_text, response_metadata = _call_structured_document_model(
        model=model,
        prompt=_document_context_prompt(assessment, curriculum),
        schema=document_context_schema(),
        document_paths=document_paths,
        reasoning_effort="low",
        timeout_seconds=timeout_seconds,
        retries=0,
    )
    parsed = _parse_provider_json(response_text)
    enriched = _apply_document_context(assessment, parsed)
    return enriched, {
        "provider": response_metadata["provider"],
        "model": model,
        "duration_ms": int((time.monotonic() - started) * 1000),
        "usage": response_metadata["usage"],
        "response_id": response_metadata["response_id"],
        "model_version": response_metadata["model_version"],
        "question_count": len(targets),
    }


def _feedback_prompt(
    assessment: dict[str, Any],
    curriculum: dict[str, Any] | None = None,
) -> str:
    source = {
        "assessment_mode": assessment["assessment_mode"],
        "total_max_marks": assessment["total_max_marks"],
        "estimated_score": assessment["estimated_score"],
        "questions": [
            {
                "label": item["label"],
                "maximum_marks": item["maximum_marks"],
                "awarded_mark": item["awarded_mark"],
                "status": item["status"],
                "topic": item["topic"],
                "skill": item["skill"],
                "rationale": item["rationale"],
            }
            for item in assessment["questions"]
        ],
        "warnings": assessment.get("warnings") or [],
    }
    subject = str((curriculum or {}).get("subject") or "mathematics")
    return f"""
You are Sumkora's bilingual {subject} learning coach. The marks below have
already been validated and are immutable. Do not recalculate, reinterpret, or
change any mark.

For every question label, return:
- rationale_zh: a faithful, natural Simplified Chinese translation of the
  English rationale;
- improvement: one concise, specific English next step, or a short positive
  continuation tip when full marks were earned;
- improvement_zh: the same learning meaning in natural Simplified Chinese.

Return exactly one feedback item for every supplied label, in the same order.
Then provide concise English strengths, weaknesses, and recommendations and
their Simplified Chinese equivalents. Translate each warning into warnings_zh.
Do not add generic motivational filler and do not mention being an AI.

Validated assessment:
{json.dumps(source, ensure_ascii=False)}
"""


def _apply_feedback(
    assessment: dict[str, Any],
    feedback: dict[str, Any],
) -> dict[str, Any]:
    expected = [item["label"] for item in assessment["questions"]]
    received = feedback.get("questions")
    if not isinstance(received, list):
        raise AssessmentValidationError(["bilingual feedback questions are missing"])
    by_label: dict[str, dict[str, Any]] = {}
    for item in received:
        if not isinstance(item, dict):
            raise AssessmentValidationError(
                ["bilingual feedback contains a non-object question"]
            )
        label = str(item.get("label") or "").strip()
        if not label or label in by_label:
            raise AssessmentValidationError(
                [f"bilingual feedback has an invalid or duplicate label {label!r}"]
            )
        by_label[label] = item
    if set(by_label) != set(expected):
        raise AssessmentValidationError(
            ["bilingual feedback labels do not match the validated assessment"]
        )

    enriched = dict(assessment)
    enriched_questions = []
    for original in assessment["questions"]:
        item = dict(original)
        translated = by_label[item["label"]]
        for field in ("rationale_zh", "improvement", "improvement_zh"):
            item[field] = str(translated.get(field) or "").strip()
        enriched_questions.append(item)
    enriched["questions"] = enriched_questions
    for field in (
        "strengths",
        "weaknesses",
        "recommendations",
        "warnings_zh",
        "strengths_zh",
        "weaknesses_zh",
        "recommendations_zh",
    ):
        values = feedback.get(field)
        enriched[field] = [
            str(value).strip()
            for value in (values if isinstance(values, list) else [])
            if str(value).strip()
        ]
    return enriched


def _enrich_feedback(
    assessment: dict[str, Any],
    *,
    model: str,
    timeout_seconds: int | None = None,
    curriculum: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    started = time.monotonic()
    response_text, response_metadata = _call_structured_document_model(
        model=model,
        prompt=_feedback_prompt(assessment, curriculum),
        schema=feedback_schema(),
        document_paths=[],
        reasoning_effort="low",
        timeout_seconds=timeout_seconds,
        retries=0,
    )
    parsed = _parse_provider_json(response_text)
    enriched = _apply_feedback(assessment, parsed)
    return enriched, {
        "provider": response_metadata["provider"],
        "model": model,
        "duration_ms": int((time.monotonic() - started) * 1000),
        "usage": response_metadata["usage"],
        "response_id": response_metadata["response_id"],
        "model_version": response_metadata["model_version"],
    }


def audit_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["checks", "warnings"],
        "properties": {
            "checks": {
                "type": "array",
                "minItems": 1,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": [
                        "label",
                        "verdict",
                        "corrected_mark",
                        "confidence",
                        "student_answer",
                        "expected_answer",
                        "reason",
                    ],
                    "properties": {
                        "label": {"type": "string"},
                        "verdict": {
                            "type": "string",
                            "enum": ["verified", "corrected", "uncertain"],
                        },
                        "corrected_mark": {"type": ["number", "null"]},
                        "confidence": {
                            "type": "number",
                            "minimum": 0,
                            "maximum": 1,
                        },
                        "student_answer": {"type": "string"},
                        "expected_answer": {"type": "string"},
                        "reason": {"type": "string"},
                    },
                },
            },
            "warnings": {
                "type": "array",
                "items": {"type": "string"},
            },
        },
    }


def _audit_prompt(
    assessment: dict[str, Any],
    curriculum: dict[str, Any] | None = None,
) -> str:
    prior = {
        "questions": [
            {
                key: item.get(key)
                for key in (
                    "label",
                    "question_text",
                    "maximum_marks",
                    "awarded_mark",
                    "status",
                    "evidence_pages",
                    "evidence_quote",
                    "rationale",
                )
            }
            for item in assessment["questions"]
        ]
    }
    curriculum_name = str(
        (curriculum or {}).get("name")
        or "Cambridge IGCSE Additional Mathematics"
    )
    return f"""
You are the independent senior examiner auditing a proposed {curriculum_name}
assessment. You receive the same complete worked-paper PDF and
complete official mark-scheme PDF used by the first assessor.

Independently verify every proposed question mark. Do not defer to the prior
assessment. For each label:
- find the cited work in the complete student PDF;
- apply the exact official method, accuracy, independent, dependency, and
  follow-through rules;
- transcribe the student's final answer exactly, including every sign and
  digit;
- transcribe the expected final answer exactly when one exists;
- return `corrected` when the proposed mark is wrong;
- return `uncertain` instead of inventing a mark when evidence cannot be read;
- otherwise return `verified`.

Return exactly one check for every prior label and no extra labels. A wrong
visible final value must not receive its accuracy mark merely because the
method is correct. Blank or unrelated evidence must not receive positive
marks. corrected_mark is the final audited mark for verified and corrected
items; it may be null only for an uncertain/ungradable item.

Prior assessment:
{json.dumps(prior, ensure_ascii=False)}
"""


def _apply_audit(
    assessment: dict[str, Any],
    audit: dict[str, Any],
    *,
    completed_work_pages: int,
) -> dict[str, Any]:
    questions = {item["label"]: dict(item) for item in assessment["questions"]}
    checks = audit.get("checks")
    if not isinstance(checks, list):
        raise AssessmentValidationError(["audit checks are missing"])
    errors: list[str] = []
    seen: set[str] = set()
    for check in checks:
        if not isinstance(check, dict):
            errors.append("audit contains a non-object check")
            continue
        label = str(check.get("label") or "").strip()
        if label not in questions:
            errors.append(f"audit returned unknown label {label!r}")
            continue
        if label in seen:
            errors.append(f"audit returned duplicate label {label}")
            continue
        seen.add(label)
        item = questions[label]
        verdict = str(check.get("verdict") or "")
        mark = _as_number(check.get("corrected_mark"))
        maximum = item.get("maximum_marks")
        confidence = _as_number(check.get("confidence"))
        if verdict not in {"verified", "corrected", "uncertain"}:
            errors.append(f"audit has invalid verdict for {label}")
        if confidence is None or not 0 <= confidence <= 1:
            errors.append(f"audit has invalid confidence for {label}")
            confidence = 0.0
        if mark is not None and (
            maximum is None or not 0 <= mark <= float(maximum)
        ):
            errors.append(f"audit mark is outside bounds for {label}")
        if verdict in {"verified", "corrected"} and mark is None:
            errors.append(f"audit did not provide a final mark for {label}")
        original_mark = item.get("awarded_mark")
        if verdict == "verified" and mark != original_mark:
            errors.append(f"audit changed {label} while calling it verified")
        if verdict == "corrected" and mark == original_mark:
            errors.append(f"audit called {label} corrected without changing its mark")
        if verdict == "uncertain":
            item["status"] = "uncertain" if mark is not None else "ungraded"
        else:
            item["status"] = "graded"
        item["awarded_mark"] = mark
        item["confidence"] = min(float(item.get("confidence") or 0), confidence)
        reason = str(check.get("reason") or "").strip()
        student_answer = str(check.get("student_answer") or "").strip()
        expected_answer = str(check.get("expected_answer") or "").strip()
        if verdict == "corrected":
            item["rationale"] = (
                f"{item.get('rationale', '')} Independent audit correction: {reason}"
            ).strip()
        elif verdict == "uncertain":
            item["rationale"] = (
                f"{item.get('rationale', '')} Independent audit: {reason}"
            ).strip()
        item["audit"] = {
            "verdict": verdict,
            "confidence": confidence,
            "student_answer": student_answer,
            "expected_answer": expected_answer,
            "reason": reason,
        }
    missing = set(questions) - seen
    if missing:
        errors.append(
            "audit omitted labels: " + ", ".join(sorted(missing))
        )
    if errors:
        raise AssessmentValidationError(errors)
    audited = dict(assessment)
    audited["questions"] = [
        questions[item["label"]] for item in assessment["questions"]
    ]
    audited["warnings"] = list(assessment.get("warnings") or []) + [
        str(value).strip()
        for value in (audit.get("warnings") or [])
        if str(value).strip()
    ]
    return validate_assessment(
        audited,
        mode="detailed",
        completed_work_pages=completed_work_pages,
    )


def _audit_detailed_assessment(
    assessment: dict[str, Any],
    completed_work_path: str,
    mark_scheme_path: str,
    *,
    completed_work_pages: int,
    curriculum: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    started = time.monotonic()
    response_text, response_metadata = _call_structured_document_model(
        model=config.WHOLE_DOCUMENT_AUDIT_MODEL,
        prompt=_audit_prompt(assessment, curriculum),
        schema=audit_schema(),
        document_paths=[completed_work_path, mark_scheme_path],
        reasoning_effort=config.WHOLE_DOCUMENT_AUDIT_REASONING_EFFORT,
    )
    try:
        parsed = _parse_provider_json(response_text)
    except json.JSONDecodeError as exc:
        raise AssessmentValidationError(
            ["independent audit response was not valid JSON"]
        ) from exc
    audited = _apply_audit(
        assessment,
        parsed,
        completed_work_pages=completed_work_pages,
    )
    return audited, {
        "provider": response_metadata["provider"],
        "model": config.WHOLE_DOCUMENT_AUDIT_MODEL,
        "reasoning_effort": config.WHOLE_DOCUMENT_AUDIT_REASONING_EFFORT,
        "duration_ms": int((time.monotonic() - started) * 1000),
        "usage": response_metadata["usage"],
        "response_id": response_metadata["response_id"],
        "model_version": response_metadata["model_version"],
        "render_dpi": response_metadata.get("render_dpi"),
    }


def assess_documents(
    completed_work_path: str,
    mark_scheme_path: str | None = None,
    *,
    model: str | None = None,
    reasoning_effort: str | None = None,
    allow_repair: bool = True,
    expected_maximum_marks: float | None = None,
    completed_work_text: str | None = None,
    mark_scheme_text: str | None = None,
    progress_callback: ProgressCallback | None = None,
    curriculum: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    if not config.CXSEE_API_KEY:
        raise RuntimeError("The assessment API key is not configured.")
    mode = "detailed" if mark_scheme_path else "estimate"
    if expected_maximum_marks is not None:
        expected_maximum_marks = float(expected_maximum_marks)
        if not math.isfinite(expected_maximum_marks) or not (
            1 <= expected_maximum_marks <= 500
        ):
            raise ValueError("Expected maximum marks must be between 1 and 500.")
    pages = _page_count(completed_work_path)
    if not 1 <= pages <= config.WHOLE_DOCUMENT_MAX_PAGES:
        raise ValueError(
            f"Completed work must contain 1 to {config.WHOLE_DOCUMENT_MAX_PAGES} pages."
        )
    scheme_pages = 0
    if mark_scheme_path:
        scheme_pages = _page_count(mark_scheme_path)
        if not 1 <= scheme_pages <= config.WHOLE_DOCUMENT_MAX_PAGES:
            raise ValueError(
                f"Mark scheme must contain 1 to {config.WHOLE_DOCUMENT_MAX_PAGES} pages."
            )

    selected_model = model or config.WHOLE_DOCUMENT_MODEL
    fast_estimate_page_limit = max(
        1,
        int(getattr(config, "WHOLE_DOCUMENT_FAST_ESTIMATE_MAX_PAGES", 20)),
    )
    fast_detailed_page_limit = min(10, fast_estimate_page_limit)
    fast_estimate = mode == "estimate" and pages <= fast_estimate_page_limit
    fast_detailed = (
        mode == "detailed"
        and pages <= fast_detailed_page_limit
        and scheme_pages
        <= max(
            1,
            int(
                getattr(
                    config,
                    "WHOLE_DOCUMENT_FAST_DETAILED_MAX_SCHEME_PAGES",
                    20,
                )
            ),
        )
    )
    compact_assessment = fast_estimate or fast_detailed
    effort = (
        reasoning_effort
        or ("low" if compact_assessment else config.WHOLE_DOCUMENT_REASONING_EFFORT)
    )
    repair_errors: list[str] | None = None
    last_validation_error: AssessmentValidationError | None = None
    started = time.monotonic()
    target_seconds = max(
        60,
        int(getattr(config, "WHOLE_DOCUMENT_TARGET_SECONDS", 480)),
    )
    if compact_assessment:
        # Native-PDF estimates normally finish within the short product
        # target. Do not let an interrupted provider request consume the
        # long-document budget before recovery begins.
        target_seconds = min(
            target_seconds,
            max(
                120,
                int(
                    getattr(
                        config,
                        "WHOLE_DOCUMENT_COMPACT_TARGET_SECONDS",
                        120,
                    )
                ),
            ),
        )

    def remaining_seconds() -> float:
        return max(0.0, target_seconds - (time.monotonic() - started))

    attempts = 2 if allow_repair else 1
    for attempt in range(attempts):
        document_paths = [completed_work_path]
        if mark_scheme_path:
            document_paths.append(mark_scheme_path)
        document_texts = None
        if completed_work_text:
            document_texts = [
                ("COMPLETED STUDENT WORK — OCR TRANSCRIPT", completed_work_text)
            ]
            if mark_scheme_text:
                document_texts.append(
                    ("OFFICIAL MARK SCHEME — OCR TRANSCRIPT", mark_scheme_text)
                )
        _notify_progress(
            progress_callback,
            "primary_request",
            (
                f"Assessment attempt {attempt + 1} of {attempts}; "
                f"{pages} completed-work pages"
            ),
        )
        remaining = remaining_seconds()
        if remaining < 45:
            raise TimeoutError(
                "The assessment exceeded its processing time budget."
            )
        # A long document request can continue upstream after our HTTP client
        # times out. Retrying it immediately previously produced a second 500
        # and made a healthy image gallery look corrupt. Keep one controlled
        # recovery window, pause briefly, and always respect the total budget.
        transport_attempt = 0
        transport_timeouts: list[int] = []
        transport_reasoning_efforts: list[str] = []
        transport_models: list[str] = []
        while True:
            remaining = remaining_seconds()
            if remaining < 45:
                raise TimeoutError(
                    "The assessment exceeded its processing time budget."
                )
            if compact_assessment:
                if transport_attempt == 0 and (
                    pages > 10 or scheme_pages > 10
                ):
                    compact_timeout = int(
                        getattr(
                            config,
                            "WHOLE_DOCUMENT_FAST_LONG_TIMEOUT_SECONDS",
                            110,
                        )
                    )
                else:
                    compact_timeout = int(
                        getattr(
                            config,
                            (
                                "WHOLE_DOCUMENT_COMPACT_INITIAL_TIMEOUT_SECONDS"
                                if transport_attempt == 0
                                else "WHOLE_DOCUMENT_COMPACT_RETRY_TIMEOUT_SECONDS"
                            ),
                            70 if transport_attempt == 0 else 45,
                        )
                    )
                primary_timeout = max(
                    45,
                    min(
                        config.WHOLE_DOCUMENT_TIMEOUT_SECONDS,
                        compact_timeout,
                        int(remaining - 15),
                    ),
                )
            else:
                recovery_reserve = (
                    135 if transport_attempt == 0 and remaining >= 240 else 0
                )
                primary_timeout = max(
                    45,
                    min(
                        config.WHOLE_DOCUMENT_TIMEOUT_SECONDS,
                        int(remaining - 15 - recovery_reserve),
                    ),
                )
            transport_timeouts.append(primary_timeout)
            request_reasoning_effort = (
                "low" if transport_attempt > 0 and effort != "low" else effort
            )
            transport_reasoning_efforts.append(request_reasoning_effort)
            request_model = selected_model
            if fast_estimate and model is None:
                fast_primary_model = (
                    getattr(
                        config,
                        "WHOLE_DOCUMENT_FAST_PRIMARY_MODEL",
                        "gpt-5.4-mini",
                    )
                    or selected_model
                )
                fast_fallback_model = (
                    getattr(
                        config,
                        "WHOLE_DOCUMENT_FAST_FALLBACK_MODEL",
                        selected_model,
                    )
                    or selected_model
                )
                request_model = (
                    fast_primary_model
                    if transport_attempt == 0
                    else fast_fallback_model
                )
            transport_models.append(request_model)
            try:
                response_text, response_metadata = (
                    _call_structured_document_model(
                        model=request_model,
                        prompt=_prompt(
                            mode,
                            repair_errors,
                            expected_maximum_marks=expected_maximum_marks,
                            curriculum=curriculum,
                        ),
                        schema=assessment_schema(),
                        document_paths=document_paths,
                        reasoning_effort=request_reasoning_effort,
                        document_texts=document_texts,
                        timeout_seconds=primary_timeout,
                        retries=0,
                        render_documents_as_images=(
                            transport_attempt > 0
                            and request_model == selected_model
                            and not document_texts
                        ),
                        render_dpi_override=(
                            max(
                                90,
                                int(
                                    getattr(
                                        config,
                                        "WHOLE_DOCUMENT_FAST_ESTIMATE_RENDER_DPI",
                                        110,
                                    )
                                ),
                            )
                            if compact_assessment
                            and request_model == selected_model
                            and not document_texts
                            else None
                        ),
                    )
                )
                break
            except Exception as exc:
                can_recover = (
                    transport_attempt == 0
                    and _retryable_provider_error(exc)
                    and remaining_seconds()
                    >= (45 if compact_assessment else 60)
                )
                if not can_recover:
                    raise
                transport_attempt += 1
                _notify_progress(
                    progress_callback,
                    "provider_retry",
                    (
                        "The document provider interrupted the first request; "
                        "a separate backup assessor is reading the same complete paper"
                    ),
                )
                time.sleep(1 if compact_assessment else 4)
        _notify_progress(
            progress_callback,
            "primary_response",
            "The assessor responded; checking question coverage and totals",
        )
        try:
            parsed = _parse_provider_json(response_text)
            validated = validate_assessment(
                parsed,
                mode=mode,
                completed_work_pages=pages,
                expected_maximum_marks=expected_maximum_marks,
            )
            provider_metadata = {
                "provider": response_metadata["provider"],
                "model": transport_models[-1],
                "requested_model": selected_model,
                "prompt_version": ASSESSMENT_PROMPT_VERSION,
                "reasoning_effort": transport_reasoning_efforts[-1],
                "requested_reasoning_effort": effort,
                "duration_ms": int((time.monotonic() - started) * 1000),
                "attempts": attempt + 1,
                "usage": response_metadata["usage"],
                "response_id": response_metadata["response_id"],
                "model_version": response_metadata["model_version"],
                "render_dpi": response_metadata.get("render_dpi"),
                "expected_maximum_marks": expected_maximum_marks,
                "target_seconds": target_seconds,
                "primary_timeout_seconds": primary_timeout,
                "transport_attempts": transport_attempt + 1,
                "transport_timeouts": transport_timeouts,
                "transport_reasoning_efforts": transport_reasoning_efforts,
                "transport_models": transport_models,
                "fallback_used": transport_attempt > 0,
                "model_substituted": transport_models[-1] != selected_model,
                "curriculum_id": (curriculum or {}).get("id"),
                "compact_fast_path": compact_assessment,
                "fast_estimate_path": fast_estimate,
                "fast_detailed_path": fast_detailed,
            }
            if (
                mode == "detailed"
                and config.WHOLE_DOCUMENT_AUDIT_ENABLED
                and mark_scheme_path
            ):
                _notify_progress(
                    progress_callback,
                    "audit",
                    "Cross-checking every detailed mark",
                )
                validated, audit_metadata = _audit_detailed_assessment(
                    validated,
                    completed_work_path,
                    mark_scheme_path,
                    completed_work_pages=pages,
                    curriculum=curriculum,
                )
                provider_metadata["audit"] = audit_metadata
                provider_metadata["duration_ms"] = int(
                    (time.monotonic() - started) * 1000
                )
            validated = _ensure_question_display_fields(validated)
            assessment_model = transport_models[-1]
            if config.WHOLE_DOCUMENT_CONTEXT_ENABLED and compact_assessment:
                # The primary whole-paper result already contains the marks,
                # topics and rationales needed for the report.  A second vision
                # pass exists only to transcribe missed questions for the
                # mistake book; it must not hold up a quick estimate.
                provider_metadata["document_context"] = {
                    "status": "skipped_fast_assessment",
                    "duration_ms": 0,
                }
            elif config.WHOLE_DOCUMENT_CONTEXT_ENABLED:
                context_remaining = remaining_seconds()
                if context_remaining < 35:
                    provider_metadata["document_context"] = {
                        "status": "skipped_time_budget",
                        "duration_ms": 0,
                    }
                    validated["warnings"] = list(
                        validated.get("warnings") or []
                    ) + [
                        "Complete question transcription was skipped to keep "
                        "this run within its processing time target; the "
                        "validated marks are unaffected."
                    ]
                else:
                    try:
                        _notify_progress(
                            progress_callback,
                            "document_context",
                            (
                                f"Preparing complete text for "
                                f"{len(_context_targets(validated))} missed questions"
                            ),
                        )
                        context_timeout = max(
                            20,
                            min(
                                int(
                                    getattr(
                                        config,
                                        "WHOLE_DOCUMENT_OPTIONAL_TIMEOUT_SECONDS",
                                        120,
                                    )
                                ),
                                int(context_remaining - 15),
                            ),
                        )
                        validated, context_metadata = _enrich_document_context(
                            validated,
                            model=assessment_model,
                            document_paths=[completed_work_path],
                            timeout_seconds=context_timeout,
                            curriculum=curriculum,
                        )
                        provider_metadata["document_context"] = context_metadata
                    except Exception as exc:
                        provider_metadata["document_context"] = {
                            "status": "unavailable",
                            "error_type": type(exc).__name__,
                        }
                        validated["warnings"] = list(
                            validated.get("warnings") or []
                        ) + [
                            "Complete question transcription could not be generated "
                            "for this run; the validated marks are unaffected."
                        ]
            if config.WHOLE_DOCUMENT_FEEDBACK_ENABLED:
                feedback_remaining = remaining_seconds()
                if feedback_remaining < 30:
                    provider_metadata["feedback"] = {
                        "status": "skipped_time_budget",
                        "duration_ms": 0,
                    }
                    validated["warnings"] = list(
                        validated.get("warnings") or []
                    ) + [
                        "Bilingual coaching was skipped to keep this run "
                        "within its processing time target; the validated "
                        "English marks and rationales are unaffected."
                    ]
                else:
                    try:
                        _notify_progress(
                            progress_callback,
                            "feedback",
                            "Writing concise English and Chinese learning feedback",
                        )
                        feedback_timeout_cap = int(
                            getattr(
                                config,
                                "WHOLE_DOCUMENT_OPTIONAL_TIMEOUT_SECONDS",
                                120,
                            )
                        )
                        if compact_assessment:
                            feedback_timeout_cap = min(
                                feedback_timeout_cap,
                                max(
                                    20,
                                    int(
                                        getattr(
                                            config,
                                            "WHOLE_DOCUMENT_FAST_FEEDBACK_TIMEOUT_SECONDS",
                                            35,
                                        )
                                    ),
                                ),
                            )
                        feedback_timeout = max(
                            20,
                            min(
                                feedback_timeout_cap,
                                int(feedback_remaining - 10),
                            ),
                        )
                        validated, feedback_metadata = _enrich_feedback(
                            validated,
                            model=assessment_model,
                            timeout_seconds=feedback_timeout,
                            curriculum=curriculum,
                        )
                        provider_metadata["feedback"] = feedback_metadata
                    except Exception as exc:
                        # A translation/coaching outage must not discard validated
                        # marks. The English marking rationale remains available.
                        provider_metadata["feedback"] = {
                            "status": "unavailable",
                            "error_type": type(exc).__name__,
                        }
                        validated["warnings"] = list(
                            validated.get("warnings") or []
                        ) + [
                            "Bilingual coaching could not be generated for this "
                            "run; the validated marks are unaffected."
                        ]
                provider_metadata["duration_ms"] = int(
                    (time.monotonic() - started) * 1000
                )
            _notify_progress(
                progress_callback,
                "reasoning_complete",
                f"{len(validated['questions'])} question results validated",
            )
            return validated, provider_metadata
        except (json.JSONDecodeError, AssessmentValidationError) as exc:
            if isinstance(exc, AssessmentValidationError):
                last_validation_error = exc
                repair_errors = exc.errors
            else:
                repair_errors = ["response was not valid JSON"]
                last_validation_error = AssessmentValidationError(repair_errors)
            if attempt + 1 < attempts:
                _notify_progress(
                    progress_callback,
                    "validation_repair",
                    (
                        "The first response was incomplete; requesting one "
                        "corrected result"
                    ),
                )
    raise last_validation_error or RuntimeError("Assessment response could not be validated.")
