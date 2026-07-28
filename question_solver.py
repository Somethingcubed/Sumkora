"""Fast, direct-vision worked solutions for a single uploaded question."""

from __future__ import annotations

import base64
import json
import mimetypes
import re
from pathlib import Path

import config
from document_assessment import (
    _extract_response_text,
    _parse_provider_json,
    _strip_json_fence,
)
from ocr import api_post_json, cxsee_api_base
from taxonomy import canonical_skill, canonical_topic


SOLUTION_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "transcription",
        "question_latex",
        "solution_en",
        "solution_zh",
        "final_answer",
        "final_answer_zh",
        "topic",
        "skill",
        "classification_confidence",
    ],
    "properties": {
        "transcription": {"type": "string"},
        "question_latex": {"type": "string"},
        "solution_en": {"type": "string"},
        "solution_zh": {"type": "string"},
        "final_answer": {"type": "string"},
        "final_answer_zh": {"type": "string"},
        "topic": {"type": "string"},
        "skill": {"type": "string"},
        "classification_confidence": {"type": "number", "minimum": 0, "maximum": 1},
    },
}

TEXT_SOLUTIONS_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["solutions"],
    "properties": {
        "solutions": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["id", "solution_en", "solution_zh"],
                "properties": {
                    "id": {"type": "integer"},
                    "solution_en": {"type": "string"},
                    "solution_zh": {"type": "string"},
                },
            },
        }
    },
}


PROMPT = """You are Sumkora's mathematics tutor. Read the single question image
directly and solve it. The image may come from any mathematics source, not an
IGCSE paper. Preserve every relevant instruction, table, diagram label,
definition, domain restriction, unit, and question part in the transcription.
Do not silently repair or discard context.

Return:
- an accurate plain-text transcription;
- readable LaTeX for the complete question;
- a concise but complete worked solution in English and Simplified Chinese;
- the final answer in both languages;
- a broad canonical topic and a specific skill;
- classification confidence.

Check the algebra, signs, domain, exact/approximate form, and units before
returning. The final_answer fields MUST exactly agree with the final line of
the corresponding worked solution; copy the same result rather than
recalculating or simplifying it differently. Use one of these broad topics when appropriate: Algebra, Functions
and graphs, Coordinate geometry, Geometry, Trigonometry, Calculus, Sequences
and series, Vectors. Return only the required JSON object."""

TEXT_SOLUTIONS_PROMPT = """You are Sumkora's mathematics tutor. Produce a
concise, complete worked solution for every mathematics question in the JSON
input. Each solution must show the mathematical process step by step and end
with the final answer. Preserve exact values, units, domains, inequalities,
and all question parts. Check the algebra and signs.

Some questions include a private reference answer. Use it only to verify
accuracy. Do not mention a mark scheme, marking instructions, marks, examiner
codes, or the reference answer in the output. Write a natural worked solution,
not a marking guide. Return both English and Simplified Chinese. Return only
the required JSON object, with one result for every supplied id."""


def _image_data_url(path: str) -> str:
    mime = mimetypes.guess_type(path)[0] or "image/jpeg"
    payload = base64.b64encode(Path(path).read_bytes()).decode("ascii")
    return f"data:{mime};base64,{payload}"


def _conclusion(solution: str, *, chinese: bool = False) -> str:
    lines = [
        line.strip()
        for line in str(solution or "").splitlines()
        if line.strip() and line.strip() not in {r"\[", r"\]"}
    ]
    markers = ("因此", "所以", "最终") if chinese else (
        "therefore",
        "thus",
        "hence",
        "final",
    )
    for line in reversed(lines):
        if any(marker in line.lower() for marker in markers):
            return line
    return lines[-1] if lines else ""


def _numeric_values(value: str) -> set[str]:
    return {
        token.lstrip("+").lstrip("0") or "0"
        for token in re.findall(r"(?<![A-Za-z])[-+]?\d+(?:\.\d+)?", value or "")
    }


def _enforce_solution_consistency(parsed: dict) -> None:
    """Prefer the solution's explicit conclusion when final fields contradict it."""
    for final_key, solution_key, chinese in (
        ("final_answer", "solution_en", False),
        ("final_answer_zh", "solution_zh", True),
    ):
        conclusion = _conclusion(parsed.get(solution_key, ""), chinese=chinese)
        conclusion_numbers = _numeric_values(conclusion)
        final_numbers = _numeric_values(parsed.get(final_key, ""))
        if conclusion_numbers and final_numbers and conclusion_numbers.isdisjoint(final_numbers):
            parsed[final_key] = conclusion


def solve_question_image(path: str) -> dict:
    result = api_post_json(
        f"{cxsee_api_base()}/responses",
        {
            "model": config.QUESTION_SOLVER_MODEL,
            "input": [
                {
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": PROMPT},
                        {"type": "input_image", "image_url": _image_data_url(path)},
                    ],
                }
            ],
            "reasoning": {"effort": "low"},
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "sumkora_question_solution",
                    "strict": True,
                    "schema": SOLUTION_SCHEMA,
                }
            },
            "max_output_tokens": 4200,
            "store": False,
        },
        headers={"Authorization": f"Bearer {config.CXSEE_API_KEY}"},
        timeout=config.QUESTION_SOLVER_TIMEOUT_SECONDS,
        retries=0,
    )
    parsed = _parse_provider_json(
        _strip_json_fence(_extract_response_text(result))
    )
    _enforce_solution_consistency(parsed)
    parsed["topic"] = canonical_topic(
        parsed.get("topic", ""),
        parsed.get("skill", ""),
        parsed.get("transcription", ""),
    )
    parsed["skill"] = canonical_skill(parsed.get("skill", ""), parsed["topic"])
    parsed["classification_confidence"] = max(
        0.0, min(1.0, float(parsed.get("classification_confidence") or 0.5))
    )
    parsed["model"] = result.get("model") or config.QUESTION_SOLVER_MODEL
    parsed["usage"] = result.get("usage") or {}
    return parsed


def solve_question_texts(questions: list[dict]) -> dict:
    """Return bilingual worked solutions keyed by the supplied integer id."""
    if not questions:
        return {"solutions": [], "model": "", "usage": {}}
    compact = [
        {
            "id": int(item["id"]),
            "question": str(item.get("question") or "")[:5000],
            "reference_answer": str(
                item.get("reference_answer") or ""
            )[:2500],
        }
        for item in questions
    ]
    result = api_post_json(
        f"{cxsee_api_base()}/responses",
        {
            "model": config.QUESTION_SOLVER_MODEL,
            "input": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": (
                                f"{TEXT_SOLUTIONS_PROMPT}\n\n"
                                f"Questions:\n"
                                f"{json.dumps(compact, ensure_ascii=False)}"
                            ),
                        }
                    ],
                }
            ],
            "reasoning": {"effort": "low"},
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "sumkora_worked_solutions",
                    "strict": True,
                    "schema": TEXT_SOLUTIONS_SCHEMA,
                }
            },
            "max_output_tokens": min(18000, max(4200, len(compact) * 1400)),
            "store": False,
        },
        headers={"Authorization": f"Bearer {config.CXSEE_API_KEY}"},
        timeout=config.QUESTION_SOLVER_TIMEOUT_SECONDS,
        retries=1,
    )
    parsed = _parse_provider_json(
        _strip_json_fence(_extract_response_text(result))
    )
    supplied_ids = {item["id"] for item in compact}
    solutions = []
    for solution in parsed.get("solutions") or []:
        try:
            source_id = int(solution.get("id"))
        except (TypeError, ValueError):
            continue
        if source_id not in supplied_ids:
            continue
        solution_en = str(solution.get("solution_en") or "").strip()
        solution_zh = str(solution.get("solution_zh") or "").strip()
        if solution_en or solution_zh:
            solutions.append(
                {
                    "id": source_id,
                    "solution_en": solution_en,
                    "solution_zh": solution_zh,
                }
            )
    return {
        "solutions": solutions,
        "model": result.get("model") or config.QUESTION_SOLVER_MODEL,
        "usage": result.get("usage") or {},
    }
