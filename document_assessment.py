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


ASSESSMENT_PROMPT_VERSION = "whole-document-assessment-v1"
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
            "topic": {"type": "string"},
            "skill": {"type": "string"},
            "improvement": {"type": "string"},
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
        },
    }


def _pdf_data_url(path: str) -> str:
    payload = Path(path).read_bytes()
    return "data:application/pdf;base64," + base64.b64encode(payload).decode("ascii")


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
    return f"""
You are Sumkora's senior Cambridge IGCSE mathematics assessor. Assess the
documents as a whole. Work question by question internally, but do not rely on
an external OCR mapper or assume one answer page per question.

{mode_instruction}

Rules:
- Read every page. Page numbers in evidence_pages refer to the completed-work
  PDF, starting at 1.
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
- evidence_quote must briefly transcribe the exact visible student step or
  answer supporting the decision. Use an empty string for ungraded work.
- Transcribe the student's final answer exactly. Before calling a final answer
  correct, compare its signs, digits, variables, and domain with the expected
  answer. A visible wrong final value cannot receive its accuracy mark even
  when earlier method marks are earned.
- Keep rationales concise, specific, and understandable to a student.
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
    uncertain_available = 0.0
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
                "evidence_quote": evidence.strip(),
                "rationale": rationale.strip(),
                "topic": str(item.get("topic") or "Unclassified").strip(),
                "skill": str(item.get("skill") or "unclassified").strip(),
                "improvement": str(item.get("improvement") or "").strip(),
            }
        )
        normalized_questions.append(item)
        if maximum is not None and maximum > 0:
            known_maximum += maximum
            if status == "uncertain":
                uncertain_available += maximum
        if mark is not None and status != "ungraded":
            graded_marks += mark

    total_maximum = _as_number(assessment.get("total_max_marks"))
    if total_maximum is None:
        total_maximum = known_maximum or None
    elif known_maximum and abs(total_maximum - known_maximum) > 0.51:
        errors.append(
            f"total maximum {total_maximum:g} does not equal question maximums "
            f"{known_maximum:g}"
        )

    score_min = _as_number(assessment.get("estimated_score_min"))
    score = _as_number(assessment.get("estimated_score"))
    score_max = _as_number(assessment.get("estimated_score_max"))
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
    for field in ("strengths", "weaknesses", "recommendations", "warnings"):
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
    result = api_post_json(
        f"{cxsee_api_base()}/responses",
        {
            "model": config.WHOLE_DOCUMENT_AUDIT_MODEL,
            "input": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": _audit_prompt(assessment),
                        },
                        {
                            "type": "input_file",
                            "filename": Path(completed_work_path).name,
                            "file_data": _pdf_data_url(completed_work_path),
                        },
                        {
                            "type": "input_file",
                            "filename": Path(mark_scheme_path).name,
                            "file_data": _pdf_data_url(mark_scheme_path),
                        },
                    ],
                }
            ],
            "reasoning": {
                "effort": config.WHOLE_DOCUMENT_AUDIT_REASONING_EFFORT
            },
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "sumkora_assessment_audit",
                    "strict": True,
                    "schema": audit_schema(),
                }
            },
            "store": False,
        },
        headers={"Authorization": f"Bearer {config.CXSEE_API_KEY}"},
        timeout=config.WHOLE_DOCUMENT_TIMEOUT_SECONDS,
        retries=config.CXSEE_MAX_RETRIES,
    )
    try:
        parsed = json.loads(_extract_response_text(result))
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
        "model": config.WHOLE_DOCUMENT_AUDIT_MODEL,
        "reasoning_effort": config.WHOLE_DOCUMENT_AUDIT_REASONING_EFFORT,
        "duration_ms": int((time.monotonic() - started) * 1000),
        "usage": result.get("usage") or {},
        "response_id": result.get("id"),
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
        content: list[dict[str, Any]] = [
            {"type": "input_text", "text": _prompt(mode, repair_errors)},
            {
                "type": "input_file",
                "filename": Path(completed_work_path).name,
                "file_data": _pdf_data_url(completed_work_path),
            },
        ]
        if mark_scheme_path:
            content.append(
                {
                    "type": "input_file",
                    "filename": Path(mark_scheme_path).name,
                    "file_data": _pdf_data_url(mark_scheme_path),
                }
            )
        result = api_post_json(
            f"{cxsee_api_base()}/responses",
            {
                "model": selected_model,
                "input": [{"role": "user", "content": content}],
                "reasoning": {"effort": effort},
                "text": {
                    "format": {
                        "type": "json_schema",
                        "name": "sumkora_document_assessment",
                        "strict": True,
                        "schema": assessment_schema(),
                    }
                },
                "store": False,
            },
            headers={"Authorization": f"Bearer {config.CXSEE_API_KEY}"},
            timeout=config.WHOLE_DOCUMENT_TIMEOUT_SECONDS,
            retries=config.CXSEE_MAX_RETRIES,
        )
        try:
            parsed = json.loads(_extract_response_text(result))
            validated = validate_assessment(
                parsed,
                mode=mode,
                completed_work_pages=pages,
            )
            provider_metadata = {
                "provider": "cxsee",
                "model": selected_model,
                "prompt_version": ASSESSMENT_PROMPT_VERSION,
                "reasoning_effort": effort,
                "duration_ms": int((time.monotonic() - started) * 1000),
                "attempts": attempt + 1,
                "usage": result.get("usage") or {},
                "response_id": result.get("id"),
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
