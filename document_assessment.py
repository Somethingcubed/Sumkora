"""Whole-document assessment for student-owned mathematics papers.

New analyses send the completed work, and optionally a mark scheme, to one
reasoning model request.  The response is validated before any marks are
persisted so provider failures or contradictory output never become zero marks.
"""

from __future__ import annotations

import base64
import json
import math
import time
from pathlib import Path
from typing import Any

import fitz

import config
from ocr import api_post_json, cxsee_api_base


ASSESSMENT_PROMPT_VERSION = "whole-document-assessment-v2"
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


class AssessmentValidationError(ValueError):
    """Raised when a provider result is unsafe to display as an assessment."""

    def __init__(self, errors: list[str]):
        self.errors = errors
        super().__init__("; ".join(errors))


def assessment_schema() -> dict[str, Any]:
    nullable_number = {"type": ["number", "null"]}
    question = {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "label",
            "question_text",
            "question_latex",
            "maximum_marks",
            "awarded_mark",
            "status",
            "confidence",
            "evidence_pages",
            "evidence_quote",
            "rationale",
            "topic",
            "skill",
            "improvement",
        ],
        "properties": {
            "label": {"type": "string"},
            "question_text": {"type": "string"},
            "question_latex": {"type": "string"},
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
            "evidence_quote": {"type": "string"},
            "rationale": {"type": "string"},
            "rationale_zh": {"type": "string"},
            "topic": {"type": "string"},
            "skill": {"type": "string"},
            "improvement": {"type": "string"},
            "improvement_zh": {"type": "string"},
        },
    }
    return {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "assessment_mode",
            "paper_title",
            "syllabus_code",
            "paper_reference",
            "total_max_marks",
            "estimated_score_min",
            "estimated_score",
            "estimated_score_max",
            "questions",
            "strengths",
            "weaknesses",
            "recommendations",
            "warnings",
        ],
        "properties": {
            "assessment_mode": {
                "type": "string",
                "enum": ["estimate", "detailed"],
            },
            "paper_title": {"type": "string"},
            "syllabus_code": {"type": "string"},
            "paper_reference": {"type": "string"},
            "total_max_marks": nullable_number,
            "estimated_score_min": nullable_number,
            "estimated_score": nullable_number,
            "estimated_score_max": nullable_number,
            "questions": {
                "type": "array",
                "minItems": 1,
                "items": question,
            },
            "strengths": {
                "type": "array",
                "items": {"type": "string"},
            },
            "weaknesses": {
                "type": "array",
                "items": {"type": "string"},
            },
            "recommendations": {
                "type": "array",
                "items": {"type": "string"},
            },
            "warnings": {
                "type": "array",
                "items": {"type": "string"},
            },
            "strengths_zh": {
                "type": "array",
                "items": {"type": "string"},
            },
            "weaknesses_zh": {
                "type": "array",
                "items": {"type": "string"},
            },
            "recommendations_zh": {
                "type": "array",
                "items": {"type": "string"},
            },
            "warnings_zh": {
                "type": "array",
                "items": {"type": "string"},
            },
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


def _prompt(mode: str, repair_errors: list[str] | None = None) -> str:
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
    return rf"""
You are Sumkora's senior Cambridge IGCSE mathematics assessor. Assess the
documents as a whole. Work question by question internally, but do not rely on
an external OCR mapper or assume one answer page per question.

{mode_instruction}

Rules:
- Read every page. Page numbers in evidence_pages refer to the completed-work
  PDF, starting at 1.
- Preserve labels such as Q1, Q2(a), and Q2(b) when separable. Do not invent
  questions or omit visible answered questions.
- question_text must contain the complete readable question, not a summary of
  the task. When an item is a subquestion, repeat the parent stem, definitions,
  sequence notation, diagram description, table context, and any earlier
  results needed to understand that subquestion independently.
- question_latex must contain the same complete question as question_text, but
  place every mathematical expression inside valid TeX delimiters \( ... \)
  or \[ ... \]. Use proper TeX such as \frac, \sqrt, superscripts, subscripts,
  inequalities, vectors, matrices, and set notation. Do not leave display
  mathematics as plain text such as x^2 or sqrt(x). Keep ordinary prose outside
  TeX delimiters. If no mathematics is present, return the question text.
- A positive mark requires visible supporting student evidence.
- A blank, unrelated, wrong, or unreadable region must never receive a
  positive mark.
- Do not award marks merely because an answer appears in the mark scheme.
- awarded_mark must be null for a truly ungradable item. Keep maximum_marks
  when the official allocation is identifiable; use null only when the
  allocation itself cannot be determined.
- Confidence describes confidence in the mark and document matching together.
- evidence_quote must briefly transcribe the exact visible student step or
  answer supporting the decision. Use an empty string for ungraded work.
- Transcribe the student's final answer exactly. Before calling a final answer
  correct, compare its signs, digits, variables, and domain with the expected
  answer. A visible wrong final value cannot receive its accuracy mark even
  when earlier method marks are earned.
- Keep rationales concise, specific, and understandable to a student.
- For every question, also return rationale_zh and improvement_zh in natural,
  student-friendly Simplified Chinese. Return the same learning meaning in
  both languages; translation must never change any mark.
- Also return strengths_zh, weaknesses_zh, recommendations_zh, and warnings_zh
  as Simplified Chinese equivalents of the English summary arrays.
- Totals must be arithmetically consistent with question results.
- The overall estimate must satisfy min <= estimate <= max <= total maximum.
- Never turn a technical or reading failure into zero marks.
- Return only the requested structured JSON.
{repair}
"""


def _extract_response_text(result: dict[str, Any]) -> str:
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
        parsed = json.loads(_repair_json_string_escapes(text))
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


def _call_structured_document_model(
    *,
    model: str,
    prompt: str,
    schema: dict[str, Any],
    document_paths: list[str],
    reasoning_effort: str,
) -> tuple[str, dict[str, Any]]:
    schema_instruction = (
        "\n\nYou must follow this exact JSON Schema yourself. Return every "
        "required field with the exact property names and enum values. "
        "Return one JSON object only, without Markdown fences or commentary. "
        "Escape every backslash inside JSON strings.\n"
        + json.dumps(schema, ensure_ascii=False)
    )
    if model.startswith("qwen"):
        dpi = _document_render_dpi(document_paths)
        content: list[dict[str, Any]] = [
            {"type": "text", "text": prompt + schema_instruction},
        ]
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
                "max_tokens": 32768,
                "response_format": {"type": "json_object"},
            },
            headers={"Authorization": f"Bearer {config.CXSEE_API_KEY}"},
            timeout=config.WHOLE_DOCUMENT_TIMEOUT_SECONDS,
            retries=config.CXSEE_MAX_RETRIES,
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
            "render_dpi": dpi,
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
            timeout=config.WHOLE_DOCUMENT_TIMEOUT_SECONDS,
            retries=config.CXSEE_MAX_RETRIES,
        )
        return _strip_json_fence(_extract_gemini_text(result)), {
            "provider": "cxsee_gemini_native",
            "usage": result.get("usageMetadata") or {},
            "response_id": result.get("responseId"),
            "model_version": result.get("modelVersion"),
        }

    content: list[dict[str, Any]] = [
        {"type": "input_text", "text": prompt},
        *[
            {
                "type": "input_file",
                "filename": Path(path).name,
                "file_data": _pdf_data_url(path),
            }
            for path in document_paths
        ],
    ]
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
            "store": False,
        },
        headers={"Authorization": f"Bearer {config.CXSEE_API_KEY}"},
        timeout=config.WHOLE_DOCUMENT_TIMEOUT_SECONDS,
        retries=config.CXSEE_MAX_RETRIES,
    )
    return _strip_json_fence(_extract_response_text(result)), {
        "provider": "cxsee_responses",
        "usage": result.get("usage") or {},
        "response_id": result.get("id"),
        "model_version": result.get("model"),
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
    if mode == "estimate" and known_maximum:
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


def _audit_prompt(assessment: dict[str, Any]) -> str:
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
    return f"""
You are the independent senior examiner auditing a proposed Cambridge IGCSE
mathematics assessment. You receive the same complete worked-paper PDF and
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
) -> tuple[dict[str, Any], dict[str, Any]]:
    started = time.monotonic()
    response_text, response_metadata = _call_structured_document_model(
        model=config.WHOLE_DOCUMENT_AUDIT_MODEL,
        prompt=_audit_prompt(assessment),
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
) -> tuple[dict[str, Any], dict[str, Any]]:
    if not config.CXSEE_API_KEY:
        raise RuntimeError("The assessment API key is not configured.")
    mode = "detailed" if mark_scheme_path else "estimate"
    pages = _page_count(completed_work_path)
    if not 1 <= pages <= config.WHOLE_DOCUMENT_MAX_PAGES:
        raise ValueError(
            f"Completed work must contain 1 to {config.WHOLE_DOCUMENT_MAX_PAGES} pages."
        )
    if mark_scheme_path:
        scheme_pages = _page_count(mark_scheme_path)
        if not 1 <= scheme_pages <= config.WHOLE_DOCUMENT_MAX_PAGES:
            raise ValueError(
                f"Mark scheme must contain 1 to {config.WHOLE_DOCUMENT_MAX_PAGES} pages."
            )

    selected_model = model or config.WHOLE_DOCUMENT_MODEL
    effort = reasoning_effort or config.WHOLE_DOCUMENT_REASONING_EFFORT
    repair_errors: list[str] | None = None
    last_validation_error: AssessmentValidationError | None = None
    started = time.monotonic()
    attempts = 2 if allow_repair else 1
    for attempt in range(attempts):
        document_paths = [completed_work_path]
        if mark_scheme_path:
            document_paths.append(mark_scheme_path)
        response_text, response_metadata = _call_structured_document_model(
            model=selected_model,
            prompt=_prompt(mode, repair_errors),
            schema=assessment_schema(),
            document_paths=document_paths,
            reasoning_effort=effort,
        )
        try:
            parsed = _parse_provider_json(response_text)
            validated = validate_assessment(
                parsed,
                mode=mode,
                completed_work_pages=pages,
            )
            provider_metadata = {
                "provider": response_metadata["provider"],
                "model": selected_model,
                "prompt_version": ASSESSMENT_PROMPT_VERSION,
                "reasoning_effort": effort,
                "duration_ms": int((time.monotonic() - started) * 1000),
                "attempts": attempt + 1,
                "usage": response_metadata["usage"],
                "response_id": response_metadata["response_id"],
                "model_version": response_metadata["model_version"],
                "render_dpi": response_metadata.get("render_dpi"),
            }
            if (
                mode == "detailed"
                and config.WHOLE_DOCUMENT_AUDIT_ENABLED
                and mark_scheme_path
            ):
                validated, audit_metadata = _audit_detailed_assessment(
                    validated,
                    completed_work_path,
                    mark_scheme_path,
                    completed_work_pages=pages,
                )
                provider_metadata["audit"] = audit_metadata
                provider_metadata["duration_ms"] = int(
                    (time.monotonic() - started) * 1000
                )
            return validated, provider_metadata
        except (json.JSONDecodeError, AssessmentValidationError) as exc:
            if isinstance(exc, AssessmentValidationError):
                last_validation_error = exc
                repair_errors = exc.errors
            else:
                repair_errors = ["response was not valid JSON"]
                last_validation_error = AssessmentValidationError(repair_errors)
    raise last_validation_error or RuntimeError("Assessment response could not be validated.")
