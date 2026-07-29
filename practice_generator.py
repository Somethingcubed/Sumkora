"""Validated AI-authored mathematics practice for general-mathematics students."""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor, as_completed

import config
from document_assessment import (
    _extract_response_text,
    _parse_provider_json,
    _strip_json_fence,
)
from ocr import api_post_json, cxsee_api_base
from taxonomy import GENERAL_MATH_TOPICS, canonical_skill, canonical_topic


QUESTION_FIELDS = {
    "order": {"type": "integer"},
    "topic": {"type": "string"},
    "skill": {"type": "string"},
    "difficulty": {"type": "string"},
    "prompt_en": {"type": "string"},
    "prompt_zh": {"type": "string"},
    "solution_en": {"type": "string"},
    "solution_zh": {"type": "string"},
    "final_answer_en": {"type": "string"},
    "final_answer_zh": {"type": "string"},
    "maximum_marks": {"type": "number", "minimum": 1, "maximum": 12},
}


GENERATION_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["questions"],
    "properties": {
        "questions": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": list(QUESTION_FIELDS),
                "properties": QUESTION_FIELDS,
            },
        }
    },
}


VALIDATION_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["questions"],
    "properties": {
        "questions": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": [*QUESTION_FIELDS, "valid", "validation_notes"],
                "properties": {
                    **QUESTION_FIELDS,
                    "valid": {"type": "boolean"},
                    "validation_notes": {"type": "string"},
                },
            },
        }
    },
}


GENERATION_PROMPT = """You create original secondary or pre-university
mathematics practice for Sumkora. Generate exactly the requested number of
stand-alone questions. Do not copy, quote, imitate, or identify a past paper.

Requirements:
- every question must contain all definitions, diagrams-as-text, tables,
  values, domains, units, and parent context it needs;
- no question may depend on another question;
- vary structures and numerical values; do not create near-duplicates;
- use valid readable TeX delimiters for mathematics;
- give a complete worked solution and final answer;
- provide equivalent English and Simplified Chinese versions;
- use a concise specific skill and one of the allowed broad topics;
- match the requested difficulty and calculator policy;
- allocate a sensible whole-number maximum mark from 1 to 12.

Return only the required JSON."""


VALIDATION_PROMPT = """You are Sumkora's independent mathematics worksheet
validator. Solve every supplied question from scratch. Check completeness,
uniqueness, mathematical consistency, the final answer, the worked process,
language equivalence, difficulty, and calculator policy.

Correct any fixable issue directly in the returned question and solution.
Set valid=false only if a question cannot be repaired without replacing its
core idea. Do not mention this validation process inside the student-facing
question or solution. Return exactly one result for every supplied order and
only the required JSON."""


def _call_model(prompt: str, schema: dict, schema_name: str, tokens: int) -> dict:
    result = api_post_json(
        f"{cxsee_api_base()}/responses",
        {
            "model": config.QUESTION_SOLVER_MODEL,
            "input": [
                {
                    "role": "user",
                    "content": [{"type": "input_text", "text": prompt}],
                }
            ],
            "reasoning": {"effort": "low"},
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": schema_name,
                    "strict": True,
                    "schema": schema,
                }
            },
            "max_output_tokens": tokens,
            "store": False,
        },
        headers={"Authorization": f"Bearer {config.CXSEE_API_KEY}"},
        timeout=max(config.QUESTION_SOLVER_TIMEOUT_SECONDS, 90),
        retries=1,
    )
    parsed = _parse_provider_json(
        _strip_json_fence(_extract_response_text(result))
    )
    parsed["model"] = result.get("model") or config.QUESTION_SOLVER_MODEL
    return parsed


def _normalise_question(item: dict) -> dict | None:
    try:
        order = int(item.get("order"))
        maximum_marks = float(item.get("maximum_marks") or 1)
    except (TypeError, ValueError):
        return None
    prompt_en = str(item.get("prompt_en") or "").strip()
    prompt_zh = str(item.get("prompt_zh") or "").strip()
    solution_en = str(item.get("solution_en") or "").strip()
    solution_zh = str(item.get("solution_zh") or "").strip()
    if not all((prompt_en, prompt_zh, solution_en, solution_zh)):
        return None
    topic = canonical_topic(
        str(item.get("topic") or ""),
        str(item.get("skill") or ""),
        prompt_en,
    )
    if topic not in GENERAL_MATH_TOPICS:
        topic = "Algebra"
    return {
        "order": order,
        "topic": topic,
        "skill": canonical_skill(str(item.get("skill") or ""), topic),
        "difficulty": str(item.get("difficulty") or "standard").strip().lower(),
        "prompt_en": prompt_en,
        "prompt_zh": prompt_zh,
        "solution_en": solution_en,
        "solution_zh": solution_zh,
        "final_answer_en": str(item.get("final_answer_en") or "").strip(),
        "final_answer_zh": str(item.get("final_answer_zh") or "").strip(),
        "maximum_marks": max(1.0, min(12.0, maximum_marks)),
        "valid": bool(item.get("valid", True)),
        "validation_notes": str(item.get("validation_notes") or "").strip(),
    }


def _generate_batch(
    *,
    topic: str,
    count: int,
    start_order: int,
    difficulty: str,
    calculator_policy: str,
    avoid: list[str],
) -> tuple[list[dict], str]:
    allowed = ", ".join(GENERAL_MATH_TOPICS)
    request = {
        "number_of_questions": count,
        "first_order_number": start_order,
        "target_topic": topic or "Mixed mathematics",
        "difficulty": difficulty,
        "calculator_policy": calculator_policy,
        "allowed_topics": allowed,
        "avoid_questions": avoid[-20:],
    }
    result = _call_model(
        f"{GENERATION_PROMPT}\n\nRequest:\n"
        f"{json.dumps(request, ensure_ascii=False)}",
        GENERATION_SCHEMA,
        "sumkora_generated_practice",
        min(10000, max(4000, count * 1400)),
    )
    questions = [
        question
        for item in result.get("questions") or []
        if (question := _normalise_question(item))
    ]
    return questions, str(result.get("model") or "")


def _validate_batch(
    questions: list[dict],
    *,
    difficulty: str,
    calculator_policy: str,
) -> tuple[list[dict], str]:
    payload = [
        {key: value for key, value in item.items() if key not in {"valid"}}
        for item in questions
    ]
    result = _call_model(
        f"{VALIDATION_PROMPT}\n\nRequested difficulty: {difficulty}\n"
        f"Requested calculator policy: {calculator_policy}\n"
        f"Questions:\n{json.dumps(payload, ensure_ascii=False)}",
        VALIDATION_SCHEMA,
        "sumkora_validated_practice",
        min(10000, max(4000, len(payload) * 1500)),
    )
    validated = [
        question
        for item in result.get("questions") or []
        if (question := _normalise_question(item)) and question["valid"]
    ]
    return validated, str(result.get("model") or "")


def generate_validated_practice_questions(
    *,
    topic: str,
    count: int,
    difficulty: str,
    calculator_policy: str,
) -> tuple[list[dict], str]:
    """Generate, independently solve, repair, and return up to ``count`` items."""
    count = max(10, min(int(count), 50))
    batch_specs = []
    for start in range(1, count + 1, 5):
        batch_specs.append((start, min(5, count - start + 1)))

    generated: list[dict] = []
    models: list[str] = []
    with ThreadPoolExecutor(max_workers=min(4, len(batch_specs))) as pool:
        futures = [
            pool.submit(
                _generate_batch,
                topic=topic,
                count=batch_count,
                start_order=start,
                difficulty=difficulty,
                calculator_policy=calculator_policy,
                avoid=[],
            )
            for start, batch_count in batch_specs
        ]
        for future in as_completed(futures):
            questions, model = future.result()
            generated.extend(questions)
            if model:
                models.append(model)

    generated.sort(key=lambda item: item["order"])
    unique: list[dict] = []
    seen = set()
    for item in generated:
        signature = " ".join(item["prompt_en"].lower().split())
        if signature in seen:
            continue
        seen.add(signature)
        unique.append(item)

    validation_batches = [
        unique[index:index + 5] for index in range(0, len(unique), 5)
    ]
    validated: list[dict] = []
    with ThreadPoolExecutor(max_workers=min(4, len(validation_batches))) as pool:
        futures = [
            pool.submit(
                _validate_batch,
                batch,
                difficulty=difficulty,
                calculator_policy=calculator_policy,
            )
            for batch in validation_batches
        ]
        for future in as_completed(futures):
            questions, model = future.result()
            validated.extend(questions)
            if model:
                models.append(model)

    validated.sort(key=lambda item: item["order"])
    for order, item in enumerate(validated[:count], start=1):
        item["order"] = order
    return validated[:count], (models[-1] if models else config.QUESTION_SOLVER_MODEL)
