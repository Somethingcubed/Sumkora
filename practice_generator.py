"""Original, curriculum-bound practice with an independent validation pass."""

from __future__ import annotations

import json
import logging
import re
from concurrent.futures import ThreadPoolExecutor, as_completed

import config
from curricula import curriculum_prompt_context
from document_assessment import (
    _extract_response_text,
    _parse_provider_json,
    _retryable_provider_error,
    _strip_json_fence,
)
from ocr import api_post_json, cxsee_api_base
from taxonomy import canonical_skill, canonical_topic_for_curriculum


logger = logging.getLogger(__name__)


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
                "required": [
                    "order",
                    "valid",
                    "validation_notes",
                    "replacement",
                ],
                "properties": {
                    "order": {"type": "integer"},
                    "valid": {"type": "boolean"},
                    "validation_notes": {"type": "string"},
                    "replacement": {
                        "anyOf": [
                            {"type": "null"},
                            {
                                "type": "object",
                                "additionalProperties": False,
                                "required": list(QUESTION_FIELDS),
                                "properties": QUESTION_FIELDS,
                            },
                        ]
                    },
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

When the supplied item is already fully correct, set replacement=null; do not
repeat its question or solution text. Correct a fixable problem by returning
the complete corrected item in replacement. Set valid=false when the question is
ambiguous, impossible, outside the specified curriculum, depends on a missing
diagram, has an unverifiable answer, or cannot be repaired without replacing
its core task. For physics, independently check dimensions and physical
plausibility. For chemistry, independently check formulae, equation balancing,
charges, states, conditions, observations, calculations, and laboratory safety.
For statistics, verify the data and inference conditions. Return one compact
result for every supplied order and only the required JSON."""


# Five bilingual questions plus two worked solutions per item regularly push
# the gateway past its upstream completion window. Three keeps each request
# small enough to finish promptly while four workers still generate ten-item
# worksheets in one concurrent wave.
PRACTICE_BATCH_SIZE = 3


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
        # Recovery is handled at the worksheet-batch level below. Retrying an
        # identical large request here can block for another 90 seconds and
        # still throw away all the batches that already succeeded.
        retries=0,
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
    originals = {item["order"]: item for item in questions}
    validated = []
    for check in result.get("questions") or []:
        try:
            order = int(check.get("order"))
        except (AttributeError, TypeError, ValueError):
            continue
        original = originals.get(order)
        if not original or not bool(check.get("valid")):
            continue
        replacement = check.get("replacement")
        candidate = dict(replacement) if isinstance(replacement, dict) else dict(original)
        candidate["order"] = order
        candidate["valid"] = True
        candidate["validation_notes"] = str(
            check.get("validation_notes") or "Independently solved and checked."
        ).strip()
        question = _normalise_question(candidate, curriculum)
        if question and question["valid"]:
            validated.append(question)
    return validated, model


def _generate_specs_resilient(
    specs: list[tuple[int, int]],
    *,
    curriculum: dict,
    topic: str,
    difficulty: str,
    calculator_policy: str,
    avoid: list[str],
) -> tuple[list[dict], list[str]]:
    """Keep successful batches and split timed-out batches into single items."""

    def run(
        pending: list[tuple[int, int]],
    ) -> tuple[list[dict], list[str], list[tuple[int, int]]]:
        if not pending:
            return [], [], []
        questions: list[dict] = []
        models: list[str] = []
        failed: list[tuple[int, int]] = []
        with ThreadPoolExecutor(max_workers=min(4, len(pending))) as pool:
            futures = {
                pool.submit(
                    _generate_batch,
                    curriculum=curriculum,
                    topic=topic,
                    count=batch_count,
                    start_order=start_order,
                    difficulty=difficulty,
                    calculator_policy=calculator_policy,
                    avoid=avoid,
                ): (start_order, batch_count)
                for start_order, batch_count in pending
            }
            for future in as_completed(futures):
                spec = futures[future]
                try:
                    batch_questions, model = future.result()
                except Exception as exc:
                    if not _retryable_provider_error(exc):
                        raise
                    logger.warning(
                        "Practice generation batch start=%s count=%s failed; "
                        "preserving completed batches",
                        spec[0],
                        spec[1],
                    )
                    failed.append(spec)
                    continue
                questions.extend(batch_questions)
                models.append(model)
        return questions, models, failed

    questions, models, failed = run(specs)
    single_item_retries = [
        (start_order + offset, 1)
        for start_order, batch_count in failed
        for offset in range(batch_count)
    ]
    retry_questions, retry_models, retry_failures = run(single_item_retries)
    if retry_failures:
        logger.warning(
            "%s single-question practice generation requests still failed",
            len(retry_failures),
        )
    return questions + retry_questions, models + retry_models


def _validate_batches_resilient(
    batches: list[list[dict]],
    *,
    curriculum: dict,
    difficulty: str,
    calculator_policy: str,
) -> tuple[list[dict], list[str]]:
    """Validate every successful batch and retry only timed-out items."""

    def run(
        pending: list[list[dict]],
    ) -> tuple[list[dict], list[str], list[list[dict]]]:
        if not pending:
            return [], [], []
        validated: list[dict] = []
        models: list[str] = []
        failed: list[list[dict]] = []
        with ThreadPoolExecutor(max_workers=min(4, len(pending))) as pool:
            futures = {
                pool.submit(
                    _validate_batch,
                    batch,
                    curriculum=curriculum,
                    difficulty=difficulty,
                    calculator_policy=calculator_policy,
                ): batch
                for batch in pending
            }
            for future in as_completed(futures):
                batch = futures[future]
                try:
                    batch_questions, model = future.result()
                except Exception as exc:
                    if not _retryable_provider_error(exc):
                        raise
                    logger.warning(
                        "Practice validation batch count=%s failed; preserving "
                        "completed batches",
                        len(batch),
                    )
                    failed.append(batch)
                    continue
                validated.extend(batch_questions)
                models.append(model)
        return validated, models, failed

    validated, models, failed = run(batches)
    single_item_retries = [[item] for batch in failed for item in batch]
    retry_validated, retry_models, retry_failures = run(single_item_retries)
    if retry_failures:
        logger.warning(
            "%s single-question practice validation requests still failed",
            len(retry_failures),
        )
    return validated + retry_validated, models + retry_models


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
    # Generate a small reserve in the same worker waves. Previously one item
    # rejected by the independent validator caused the entire worksheet to be
    # discarded after several minutes of otherwise successful work.
    generation_target = count + max(2, (count + 9) // 10)
    batch_specs = [
        (start, min(PRACTICE_BATCH_SIZE, generation_target - start + 1))
        for start in range(1, generation_target + 1, PRACTICE_BATCH_SIZE)
    ]
    generated, generation_models = _generate_specs_resilient(
        batch_specs,
        curriculum=curriculum,
        topic=topic,
        difficulty=difficulty,
        calculator_policy=calculator_policy,
        avoid=[],
    )

    generated.sort(key=lambda item: item["order"])
    unique: list[dict] = []
    seen: set[str] = set()
    for item in generated:
        if item["signature"] in seen:
            continue
        seen.add(item["signature"])
        unique.append(item)

    batches = [
        unique[index:index + PRACTICE_BATCH_SIZE]
        for index in range(0, len(unique), PRACTICE_BATCH_SIZE)
    ]
    validated, validation_models = _validate_batches_resilient(
        batches,
        curriculum=curriculum,
        difficulty=difficulty,
        calculator_policy=calculator_policy,
    )

    validated.sort(key=lambda item: item["order"])
    # A validator can legitimately reject more than the reserve. Make one
    # bounded replacement pass instead of failing the whole worksheet.
    if len(validated) < count:
        replacement_count = (count - len(validated)) + 1
        replacement_specs = [
            (
                generation_target + start,
                min(PRACTICE_BATCH_SIZE, replacement_count - start + 1),
            )
            for start in range(1, replacement_count + 1, PRACTICE_BATCH_SIZE)
        ]
        replacement_candidates, replacement_models = _generate_specs_resilient(
            replacement_specs,
            curriculum=curriculum,
            topic=topic,
            difficulty=difficulty,
            calculator_policy=calculator_policy,
            avoid=[item["prompt_en"] for item in generated][-20:],
        )
        generation_models.extend(replacement_models)
        replacements: list[dict] = []
        for item in replacement_candidates:
            if item["signature"] not in seen:
                seen.add(item["signature"])
                generated.append(item)
                replacements.append(item)
        replacement_batches = [
            replacements[index:index + PRACTICE_BATCH_SIZE]
            for index in range(0, len(replacements), PRACTICE_BATCH_SIZE)
        ]
        replacement_validated, replacement_validation_models = (
            _validate_batches_resilient(
                replacement_batches,
                curriculum=curriculum,
                difficulty=difficulty,
                calculator_policy=calculator_policy,
            )
        )
        validated.extend(replacement_validated)
        validation_models.extend(replacement_validation_models)
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
