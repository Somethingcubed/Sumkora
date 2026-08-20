"""Original, curriculum-bound practice with an independent validation pass."""

from __future__ import annotations

import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed

import config
from curricula import curriculum_prompt_context
from document_assessment import (
    _extract_response_text,
    _parse_provider_json,
    _strip_json_fence,
)
from ocr import api_post_json, cxsee_api_base
from taxonomy import canonical_skill, canonical_topic_for_curriculum


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
    "maximum_marks": {"type": "number", "minimum": 1, "maximum": 15},
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


GENERATION_PROMPT = r"""You create original practice for Sumkora. Generate
exactly the requested number of stand-alone questions. They must assess the
specified curriculum objective but must not copy, quote, closely imitate, or
claim to be an official examination question.

Requirements:
- every question contains every definition, value, domain, unit, table, and
  piece of context needed to solve it;
- do not require an image or diagram; express any essential geometry or
  experimental arrangement fully in words;
- questions do not depend on one another;
- vary structures and numerical values and avoid near-duplicates;
- use valid TeX delimiters for every mathematical expression;
- provide equivalent English and Simplified Chinese questions;
- provide a complete worked solution and a matching final answer in both
  languages;
- use exactly one allowed curriculum topic and a concise specific skill;
- match the requested level, difficulty, and calculator policy;
- allocate a sensible whole-number maximum mark from 1 to 15.

For physics, use SI units unless the curriculum normally requires otherwise,
state any constant not supplied by the course, and make data physically
plausible. For chemistry, use correct formula subscripts and ionic charges,
balance every equation, include state symbols or conditions when the skill
requires them, describe observable results precisely, and keep experiments
safe and feasible for Grade 9. Put every chemical formula and equation inside
TeX delimiters and use supported notation such as \(\mathrm{H_2O}\), not
plain H_2O or an unsupported chemistry extension. For statistics, provide the
complete dataset or summary information and ask for conclusions in context.
Return only the required JSON."""


VALIDATION_PROMPT = r"""You are Sumkora's independent practice validator.
Solve every supplied question from scratch without trusting its proposed
answer. Check completeness, uniqueness, curriculum fit, level, language
equivalence, mathematical or scientific consistency, units, significant
figures, final answers, worked solutions, mark allocation, and calculator
policy.

Correct a fixable problem directly. Set valid=false when the question is
ambiguous, impossible, outside the specified curriculum, depends on a missing
diagram, has an unverifiable answer, or cannot be repaired without replacing
its core task. For physics, independently check dimensions and physical
plausibility. For chemistry, independently check formulae, equation balancing,
charges, states, conditions, observations, calculations, and laboratory safety.
For statistics, verify the data and inference conditions. Return one result for
every supplied order and only the required JSON."""


def _call_model(prompt: str, schema: dict, schema_name: str, tokens: int) -> tuple[dict, str]:
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
    return parsed, str(result.get("model") or config.QUESTION_SOLVER_MODEL)


def _normalise_question(item: dict, curriculum: dict) -> dict | None:
    try:
        order = int(item.get("order"))
        maximum_marks = float(item.get("maximum_marks") or 1)
    except (TypeError, ValueError):
        return None
    values = {
        key: str(item.get(key) or "").strip()
        for key in (
            "prompt_en",
            "prompt_zh",
            "solution_en",
            "solution_zh",
            "final_answer_en",
            "final_answer_zh",
        )
    }
    if not all(values.values()):
        return None
    topic = canonical_topic_for_curriculum(
        curriculum["id"],
        str(item.get("topic") or ""),
        str(item.get("skill") or ""),
        values["prompt_en"],
    )
    if topic not in curriculum["topics"]:
        return None
    prompt_signature = re.sub(r"\s+", " ", values["prompt_en"].lower())
    if len(prompt_signature) < 16:
        return None
    return {
        "order": order,
        "topic": topic,
        "skill": canonical_skill(str(item.get("skill") or ""), topic),
        "difficulty": str(item.get("difficulty") or "standard").strip().lower(),
        **values,
        "maximum_marks": max(1.0, min(15.0, maximum_marks)),
        "valid": bool(item.get("valid", True)),
        "validation_notes": str(item.get("validation_notes") or "").strip(),
        "signature": prompt_signature,
    }


def _generate_batch(
    *,
    curriculum: dict,
    topic: str,
    count: int,
    start_order: int,
    difficulty: str,
    calculator_policy: str,
    avoid: list[str],
) -> tuple[list[dict], str]:
    request = {
        "number_of_questions": count,
        "first_order_number": start_order,
        "target_topic": topic or "balanced curriculum review",
        "difficulty": difficulty,
        "calculator_policy": calculator_policy,
        "curriculum": curriculum_prompt_context(curriculum),
        "allowed_topics": list(curriculum["topics"]),
        "avoid_questions": avoid[-20:],
    }
    result, model = _call_model(
        f"{GENERATION_PROMPT}\n\nRequest:\n"
        f"{json.dumps(request, ensure_ascii=False)}",
        GENERATION_SCHEMA,
        "sumkora_generated_practice",
        min(12000, max(4200, count * 1500)),
    )
    questions = [
        question
        for item in result.get("questions") or []
        if (question := _normalise_question(item, curriculum))
    ]
    return questions, model


def _validate_batch(
    questions: list[dict],
    *,
    curriculum: dict,
    difficulty: str,
    calculator_policy: str,
) -> tuple[list[dict], str]:
    payload = [
        {
            key: value
            for key, value in item.items()
            if key not in {"valid", "signature"}
        }
        for item in questions
    ]
    request = {
        "curriculum": curriculum_prompt_context(curriculum),
        "difficulty": difficulty,
        "calculator_policy": calculator_policy,
        "questions": payload,
    }
    result, model = _call_model(
        f"{VALIDATION_PROMPT}\n\n"
        f"{json.dumps(request, ensure_ascii=False)}",
        VALIDATION_SCHEMA,
        "sumkora_validated_practice",
        min(12000, max(4200, len(payload) * 1600)),
    )
    validated = [
        question
        for item in result.get("questions") or []
        if (question := _normalise_question(item, curriculum))
        and question["valid"]
    ]
    return validated, model


def generate_validated_practice_questions(
    *,
    curriculum: dict,
    topic: str,
    count: int,
    difficulty: str,
    calculator_policy: str,
) -> tuple[list[dict], dict]:
    """Generate, independently solve, repair, and return validated items."""
    count = max(10, min(int(count), 50))
    batch_specs = [
        (start, min(5, count - start + 1))
        for start in range(1, count + 1, 5)
    ]
    generated: list[dict] = []
    generation_models: list[str] = []
    with ThreadPoolExecutor(max_workers=min(4, len(batch_specs))) as pool:
        futures = [
            pool.submit(
                _generate_batch,
                curriculum=curriculum,
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
            generation_models.append(model)

    generated.sort(key=lambda item: item["order"])
    unique: list[dict] = []
    seen: set[str] = set()
    for item in generated:
        if item["signature"] in seen:
            continue
        seen.add(item["signature"])
        unique.append(item)

    validated: list[dict] = []
    validation_models: list[str] = []
    batches = [unique[index:index + 5] for index in range(0, len(unique), 5)]
    with ThreadPoolExecutor(max_workers=min(4, len(batches))) as pool:
        futures = [
            pool.submit(
                _validate_batch,
                batch,
                curriculum=curriculum,
                difficulty=difficulty,
                calculator_policy=calculator_policy,
            )
            for batch in batches
        ]
        for future in as_completed(futures):
            questions, model = future.result()
            validated.extend(questions)
            validation_models.append(model)

    validated.sort(key=lambda item: item["order"])
    final = validated[:count]
    for order, item in enumerate(final, start=1):
        item["order"] = order
        item.pop("signature", None)
    return final, {
        "generation_model": generation_models[-1] if generation_models else "",
        "validation_model": validation_models[-1] if validation_models else "",
        "generated_count": len(generated),
        "validated_count": len(final),
    }
