"""Fast, direct-vision worked solutions for a single uploaded question."""

from __future__ import annotations

import base64
import json
import mimetypes
import re
from pathlib import Path

import config
from curricula import curriculum_prompt_context
from document_assessment import (
    _extract_response_text,
    _parse_provider_json,
    _strip_json_fence,
)
from ocr import api_post_json, cxsee_api_base
from taxonomy import (
    canonical_skill,
    canonical_topic,
    canonical_topic_for_curriculum,
)


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


PROMPT = """You are Sumkora's subject tutor. Read the single question image
directly and solve it. Preserve every relevant instruction, table, diagram label,
definition, domain restriction, unit, and question part in the transcription.
Do not silently repair or discard context.

Return:
- an accurate plain-text transcription;
- readable LaTeX for the complete question;
- a concise but complete worked solution in English and Simplified Chinese;
- the final answer in both languages;
- a broad canonical topic and a specific skill;
- classification confidence.

In question_latex, solution_en, solution_zh, final_answer, and final_answer_zh,
enclose every inline mathematical expression in \\( ... \\) and every display
equation in \\[ ... \\]. Never leave LaTeX commands such as \\frac, \\sqrt,
\\theta, or superscript notation outside MathJax delimiters. Keep ordinary
sentences outside the delimiters.

Check the reasoning, calculations, signs, domain, exact/approximate form, and units before
returning. The final_answer fields MUST exactly agree with the final line of
the corresponding worked solution; copy the same result rather than
recalculating or simplifying it differently. Return only the required JSON object."""

TEXT_SOLUTIONS_PROMPT = """You are Sumkora's subject tutor. Produce a concise,
complete worked solution for every question in the JSON input. Each solution
must show the reasoning or calculation process step by step and end with the
final answer. Preserve exact values, formulae, equations, units, domains,
inequalities, experimental observations, and all question parts. Check all
calculations, symbols, scientific claims, and signs.

In solution_en and solution_zh, enclose every inline mathematical expression
in \\( ... \\) and every display equation in \\[ ... \\]. Never leave LaTeX
commands such as \\frac, \\sqrt, \\theta, subscripts, or superscripts outside
MathJax delimiters. Keep ordinary sentences outside the delimiters.

Some questions include a private reference answer. Use it only to verify
accuracy. Do not mention a mark scheme, marking instructions, marks, examiner
codes, or the reference answer in the output. Write a natural worked solution,
not a marking guide. Return both English and Simplified Chinese. Return only
the required JSON object, with one result for every supplied id."""


def _image_data_url(path: str) -> str:
    mime = mimetypes.guess_type(path)[0] or "image/jpeg"
    payload = base64.b64encode(Path(path).read_bytes()).decode("ascii")
    return f"data:{mime};base64,{payload}"


def _bytes_data_url(payload: bytes, mime_type: str) -> str:
    encoded = base64.b64encode(payload).decode("ascii")
    return f"data:{mime_type};base64,{encoded}"


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


def _equation_rhs_signature(value: str) -> str:
    """Return a stable signature for the last explicit equation's right side."""
    text = str(value or "")
    math_blocks = [
        inline or display
        for inline, display in re.findall(
            r"\\\((.*?)\\\)|\\\[(.*?)\\\]",
            text,
            flags=re.DOTALL,
        )
        if inline or display
    ]
    candidates = list(reversed(math_blocks)) + [text]
    for candidate in candidates:
        parts = re.split(r"(?<![<>!])=(?!=)", candidate)
        if len(parts) < 2:
            continue
        rhs = parts[-1].lower()
        rhs = re.sub(r"\\(?:dfrac|tfrac)", r"\\frac", rhs)
        rhs = re.sub(r"\\(?:left|right)", "", rhs)
        rhs = rhs.replace("√", r"\sqrt")
        rhs = rhs.strip().rstrip(".,;:。；，")
        return re.sub(r"[^a-z0-9\\^_{}()+\-*/.]", "", rhs)
    return ""


def _enforce_solution_consistency(parsed: dict) -> None:
    """Prefer the solution's explicit conclusion when final fields contradict it."""
    for final_key, solution_key, chinese in (
        ("final_answer", "solution_en", False),
        ("final_answer_zh", "solution_zh", True),
    ):
        conclusion = _conclusion(parsed.get(solution_key, ""), chinese=chinese)
        conclusion_rhs = _equation_rhs_signature(conclusion)
        final_rhs = _equation_rhs_signature(parsed.get(final_key, ""))
        if conclusion_rhs and final_rhs and conclusion_rhs != final_rhs:
            parsed[final_key] = conclusion
            continue
        conclusion_numbers = _numeric_values(conclusion)
        final_numbers = _numeric_values(parsed.get(final_key, ""))
        if conclusion_numbers and final_numbers and conclusion_numbers.isdisjoint(final_numbers):
            parsed[final_key] = conclusion


def _restore_tex_control_escapes(value: str) -> str:
    """Undo JSON control escapes produced by single-backslash model TeX.

    Some OpenAI-compatible gateways return syntactically valid JSON containing
    ``\text`` or ``\frac`` with only one JSON backslash.  A normal JSON decoder
    then turns those prefixes into tab/form-feed control characters.  The
    response is otherwise valid, so the generic invalid-JSON repair never runs.
    Repair the known TeX prefixes before they reach MathJax or the database.
    """
    text = str(value or "").replace("\x01", "")
    replacements = {
        "\text": r"\text",
        "\theta": r"\theta",
        "\times": r"\times",
        "\tan": r"\tan",
        "\tfrac": r"\tfrac",
        "\frac": r"\frac",
        "\begin": r"\begin",
        "\beta": r"\beta",
        "\right": r"\right",
        "\rho": r"\rho",
        "\neq": r"\neq",
        "\nabla": r"\nabla",
        "\not": r"\not",
    }
    for damaged, repaired in replacements.items():
        text = text.replace(damaged, repaired)
    return text


def _clean_solution_fields(parsed: dict) -> None:
    for key in (
        "transcription",
        "question_latex",
        "solution_en",
        "solution_zh",
        "final_answer",
        "final_answer_zh",
    ):
        parsed[key] = _restore_tex_control_escapes(parsed.get(key, ""))


def _solve_question_image_url(
    image_url: str,
    curriculum: dict | None = None,
    *,
    target_label: str = "",
    model: str = "",
    timeout_seconds: int | None = None,
    retries: int = 0,
) -> dict:
    curriculum_instruction = (
        curriculum_prompt_context(curriculum)
        if curriculum
        else (
            "Subject: mathematics. The source may be any curriculum. "
            "Use a clear broad topic and a precise skill."
        )
    )
    subject = str((curriculum or {}).get("subject") or "mathematics")
    subject_instruction = ""
    if subject == "physics":
        subject_instruction = (
            "Check equations, units, significant figures, directions, diagrams, "
            "and experimental reasoning before returning."
        )
    elif subject == "chemistry":
        subject_instruction = (
            "Check chemical formulae, balanced equations, ionic charges, state "
            "symbols, reaction conditions, calculations, observations, apparatus, "
            "and laboratory safety. Preserve Chinese chemical terminology. Write "
            "formulae with standard LaTeX subscripts and superscripts (for example "
            "\\(\\mathrm{CO_2}\\)) rather than plain-text approximations."
        )
    target_instruction = ""
    if target_label:
        target_instruction = f"""
The image may contain more than one printed question. Work ONLY on the question
labelled {target_label}. Transcribe that target's complete printed wording and
mathematics, not merely its label or topic. Include any visible parent stem,
diagram, table, definitions, or earlier-part context needed to solve it. Do not
solve a neighbouring question and do not treat the student's handwriting as
part of the printed question.
"""
    prompt = (
        f"{PROMPT}\n\n{curriculum_instruction}\n{subject_instruction}"
        f"\n{target_instruction}"
    )
    selected_model = model or config.QUESTION_SOLVER_MODEL
    result = api_post_json(
        f"{cxsee_api_base()}/responses",
        {
            "model": selected_model,
            "input": [
                {
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": prompt},
                        {"type": "input_image", "image_url": image_url},
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
        timeout=timeout_seconds or config.QUESTION_SOLVER_TIMEOUT_SECONDS,
        retries=retries,
    )
    parsed = _parse_provider_json(
        _strip_json_fence(_extract_response_text(result))
    )
    _clean_solution_fields(parsed)
    _enforce_solution_consistency(parsed)
    parsed["topic"] = (
        canonical_topic_for_curriculum(
            curriculum["id"],
            parsed.get("topic", ""),
            parsed.get("skill", ""),
            parsed.get("transcription", ""),
        )
        if curriculum
        else canonical_topic(
            parsed.get("topic", ""),
            parsed.get("skill", ""),
            parsed.get("transcription", ""),
        )
    )
    parsed["skill"] = canonical_skill(parsed.get("skill", ""), parsed["topic"])
    parsed["classification_confidence"] = max(
        0.0, min(1.0, float(parsed.get("classification_confidence") or 0.5))
    )
    parsed["model"] = result.get("model") or selected_model
    parsed["usage"] = result.get("usage") or {}
    return parsed


def solve_question_image(
    path: str,
    curriculum: dict | None = None,
    *,
    target_label: str = "",
    model: str = "",
    timeout_seconds: int | None = None,
    retries: int = 0,
) -> dict:
    return _solve_question_image_url(
        _image_data_url(path),
        curriculum,
        target_label=target_label,
        model=model,
        timeout_seconds=timeout_seconds,
        retries=retries,
    )


def solve_question_image_bytes(
    payload: bytes,
    curriculum: dict | None = None,
    *,
    mime_type: str = "image/png",
    target_label: str = "",
    model: str = "",
    timeout_seconds: int | None = None,
    retries: int = 0,
) -> dict:
    """Solve one labelled question from an in-memory source-page image."""
    return _solve_question_image_url(
        _bytes_data_url(payload, mime_type),
        curriculum,
        target_label=target_label,
        model=model,
        timeout_seconds=timeout_seconds,
        retries=retries,
    )


def solve_question_texts(
    questions: list[dict], curriculum: dict | None = None
) -> dict:
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
    curriculum_instruction = (
        curriculum_prompt_context(curriculum)
        if curriculum
        else "Subject: mathematics. Use an appropriate school-level method."
    )
    chemistry_instruction = (
        "For chemistry, independently check every formula, balanced equation, "
        "ionic charge, state symbol, condition, calculation, observation, and "
        "laboratory-safety claim before returning."
        if curriculum and curriculum.get("subject") == "chemistry"
        else ""
    )
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
                                f"{curriculum_instruction}\n"
                                f"{chemistry_instruction}\n\n"
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
