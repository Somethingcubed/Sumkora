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

TRANSCRIPTION_PROMPT = r"""Read the photographed exam page and transcribe ONLY the complete printed question labelled {label}. Include its printed parent stem, every subpart belonging to it, instructions, definitions, given values, domains, units, table entries, and diagram labels needed to answer it.

Ignore handwriting, annotations, crossed-out student work, page headers and footers, page numbers, barcodes, examiner markings, and neighbouring questions.

Transcribe the printed question faithfully. Do not solve, simplify, paraphrase, interpret, correct, reorder, or add content. Preserve the original wording, numerical values, symbols, labels, and mathematical structure as closely as possible.

Return transcription only. Do not include a solution, explanation, commentary, topic label, Markdown heading, introduction, conclusion, or code fence.

FORMAT ALL MATHEMATICS FOR DIRECT WEBSITE RENDERING:

- Use `$...$` for every inline mathematical expression.
- Use `$$...$$` only for mathematical expressions that should appear as separate displayed lines.
- Output the dollar-sign delimiters literally. Do NOT escape them as `\$`.
- Do NOT use `\(...\)` or `\[...\]`.
- Do NOT place mathematical expressions inside backticks or code fences.
- Every LaTeX command must be completely inside `$...$` or `$$...$$`.
- Never output raw LaTeX commands outside math delimiters.
- Never nest math delimiters.
- Never open a math delimiter without closing it.

For example, output:

The function $f(x)=\frac{x^2+1}{\sqrt{x-3}}$ is defined for $x>3$.

and NOT:

The function f(x)=\frac{x^2+1}{\sqrt{x-3}} is defined for x>3.

and NOT:

The function (f(x)=\frac{x^2+1}{\sqrt{x-3}}) is defined for (x>3).

Use valid LaTeX syntax inside the math delimiters. Fractions must use `\frac{...}{...}`, square roots must use `\sqrt{...}`, and superscripts and subscripts must use properly grouped LaTeX when necessary. Keep all braces balanced.

Preserve mathematical notation accurately, including fractions, radicals, exponents, subscripts, superscripts, coordinates, intervals, sets, functions, equations, inequalities, vectors, matrices, Greek letters, degree symbols, multiplication signs, and grouping symbols.

Do not unnecessarily place ordinary prose inside math mode. For example, write:

Find the value of $x$ when $x^2-5x+6=0$.

Do not write:

$Find\ the\ value\ of\ x\ when\ x^2-5x+6=0.$

If a printed mathematical expression contains ordinary words that genuinely belong inside the expression, use appropriate LaTeX such as `\text{...}` where necessary.

For tables, reproduce every relevant printed heading, row, column, value, symbol, and unit without changing any entry. Keep mathematical entries inside `$...$`.

For diagrams, transcribe only the printed labels, values, symbols, and textual or mathematical information needed to answer the question. Do not invent a verbal description of the diagram.

If any part of the requested printed question cannot be read reliably, do not guess or fabricate it.

Before returning the transcription, silently verify that:

1. every `$` or `$$` delimiter is correctly paired;
2. every LaTeX command occurs inside math delimiters;
3. all braces are balanced;
4. there are no escaped math delimiters such as `\$`;
5. there are no `\(...\)` or `\[...\]` delimiters;
6. the output contains only the requested question.

The final response must contain only the transcription of question {label}."""


TEXT_SOLUTIONS_PROMPT = r"""You are Sumkora's subject tutor. Produce a concise but complete worked solution for every question in the JSON input.

For every supplied `id`, provide a solution that:

- answers every part of the question;
- shows the reasoning, derivation, or calculation process step by step;
- preserves exact values whenever appropriate;
- preserves all relevant formulae, equations, units, domains, inequalities, conditions, and experimental observations;
- checks calculations, algebraic signs, notation, symbols, scientific claims, and final conclusions for correctness;
- ends with a clear final answer.

Return both:

- `solution_en`: English solution
- `solution_zh`: Simplified Chinese solution

The English and Chinese versions must express the same mathematical or scientific reasoning and reach the same final answer.

FORMAT ALL MATHEMATICS FOR DIRECT WEBSITE RENDERING:

In both `solution_en` and `solution_zh`:

- Use `$...$` for every inline mathematical expression.
- Use `$$...$$` only for equations or mathematical expressions that should appear on separate displayed lines.
- Output the dollar-sign delimiters literally. Do NOT escape them as `\$`.
- Do NOT use `\(...\)` or `\[...\]`.
- Do NOT place mathematics inside backticks or Markdown code fences.
- Every LaTeX command must occur entirely inside `$...$` or `$$...$$`.
- Never leave commands such as `\frac`, `\sqrt`, `\theta`, `\times`, `\le`, `\ge`, subscripts, superscripts, or other LaTeX syntax outside math delimiters.
- Never nest math delimiters.
- Never open a math delimiter without closing it.
- Keep ordinary prose outside math mode unless text genuinely belongs inside a mathematical expression.

For example, write:

`The acceleration is $a=\frac{v-u}{t}=3.0\,\mathrm{m\,s^{-2}}$.`

not:

`The acceleration is a=\frac{v-u}{t}=3.0 m/s^2.`

and not:

`The acceleration is \(a=\frac{v-u}{t}\).`

Use valid LaTeX inside every math delimiter. Ensure:

- all braces, parentheses, brackets, absolute-value signs, and delimiters are balanced;
- fractions use valid forms such as `\frac{a}{b}`;
- radicals use valid forms such as `\sqrt{x}`;
- exponents and subscripts are correctly grouped when needed;
- Greek letters and mathematical operators use valid LaTeX;
- units inside math mode use suitable formatting such as `\mathrm{m}`, `\mathrm{s}`, `^\circ`, or equivalent valid LaTeX;
- vectors, matrices, sets, intervals, functions, inequalities, coordinates, scientific notation, and other mathematical structures are represented faithfully.

Do not replace exact values with decimal approximations unless the question requires or benefits from an approximation. If both are useful, give the exact value first and then the approximation.

For multi-part questions, preserve the original part structure clearly inside each solution so that every subpart is answered.

For numerical work, show enough intermediate steps to make the reasoning verifiable, but remain concise. Do not omit a non-obvious step that is necessary to justify the answer.

For proof, explanation, or theory questions, give the necessary logical steps rather than only stating the conclusion.

For experimental or scientific questions, preserve relevant observations, units, physical quantities, chemical species, conditions, directions, signs, and cause-and-effect relationships accurately.

Some questions include a private reference answer. Use it only as an internal accuracy check. Never mention or reveal:

- the reference answer;
- a mark scheme;
- marking instructions;
- marks or point allocations;
- examiner comments;
- examiner codes;
- grading criteria.

Write each response as a natural worked solution, not as a marking guide.

OUTPUT FORMAT:

Return only one valid JSON object containing exactly one result for every supplied `id`.

Do not include:

- Markdown code fences;
- commentary before or after the JSON;
- headings outside the JSON;
- explanations of the output format;
- any additional ids that were not supplied.

The output must be syntactically valid JSON. Escape quotation marks, backslashes, and control characters correctly wherever required by JSON.

Within JSON string values, preserve the literal `$...$` and `$$...$$` math delimiters exactly as required by the website renderer.

Before returning the result, silently verify that:

1. every supplied `id` appears exactly once;
2. every question and subpart has been answered;
3. every solution contains a clear reasoning process and final answer;
4. `solution_en` and `solution_zh` are consistent;
5. every mathematical expression is inside `$...$` or `$$...$$`;
6. no LaTeX command appears outside math delimiters;
7. no `\(...\)` or `\[...\]` delimiters appear;
8. every math delimiter is correctly paired;
9. all LaTeX braces and grouping symbols are balanced;
10. calculations, signs, units, domains, inequalities, and scientific claims have been checked;
11. the final output is valid JSON and contains nothing outside the required JSON object."""


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
    math_blocks = []
    for match in re.finditer(
        r"\\\((.*?)\\\)|\\\[(.*?)\\\]|"
        r"\$\$(.*?)\$\$|(?<![\\$])\$(?!\$)([^$\n]*?)(?<![\\$])\$(?!\$)",
        text,
        flags=re.DOTALL,
    ):
        math_blocks.append(next(group for group in match.groups() if group is not None))
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


_MATHJAX_DELIMITED_RE = re.compile(
    r"(\$\$(?:.|\n)*?\$\$|(?<![\\$])\$(?!\$)[^$\n]*?(?<![\\$])\$(?!\$))"
)
_BARE_TEX_TEXT_RE = re.compile(
    r"\\text(?:bf|it|rm|sf)?\{([^{}]*)\}"
)
_BARE_MATH_RE = re.compile(
    r"("
    r"\\(?:dfrac|tfrac|frac)\{[^{}\n]*\}\{[^{}\n]*\}"
    r"|\\sqrt(?:\[[^\]\n]*\])?\{[^{}\n]*\}"
    r"|\\(?:mathrm|mathbf|mathit|overline|vec)\{[^{}\n]*\}"
    r"|\\(?:alpha|beta|gamma|delta|epsilon|theta|lambda|mu|pi|rho|"
    r"sigma|tau|phi|omega|sin|cos|tan|sec|cosec|cot|log|ln|exp)\b"
    r"|(?:[A-Za-z0-9]+(?:\^\{[^{}\n]+\}|_\{[^{}\n]+\}|\^[A-Za-z0-9]+|_[A-Za-z0-9]+)+)"
    r"|(?:[A-Za-z](?:_\{?\w+\}?)?|[-+]?\d+(?:\.\d+)?)"
    r"\s*(?:=|≤|≥|<|>)\s*"
    r"(?:[A-Za-z](?:_\{?\w+\}?)?|[-+]?\d+(?:\.\d+)?)"
    r")"
)


def normalize_mathjax_text(value: str) -> str:
    """Make model-authored mathematics deterministic and MathJax-safe.

    Website output is standardized to literal dollar delimiters.  Legacy
    ``\\(...\\)`` and ``\\[...\\]`` blocks are converted for compatibility;
    malformed bare TeX is repaired without making another model call.
    """
    text = _restore_tex_control_escapes(value)
    if not text:
        return ""
    text = text.replace(r"\$", "$")
    text = re.sub(
        r"\\\[((?:.|\n)*?)\\\]",
        lambda match: f"$${match.group(1)}$$",
        text,
    )
    text = re.sub(
        r"\\\(((?:.|\n)*?)\\\)",
        lambda match: f"${match.group(1)}$",
        text,
    )
    parts = _MATHJAX_DELIMITED_RE.split(text)
    normalized: list[str] = []
    for index, part in enumerate(parts):
        if not part:
            continue
        if index % 2:
            normalized.append(part)
            continue
        outside = _BARE_TEX_TEXT_RE.sub(r"\1", part)
        outside = outside.replace(r"\ ", " ")
        outside = outside.replace(r"\quad", " ").replace(r"\qquad", " ")
        outside = outside.replace(r"\left", "").replace(r"\right", "")
        protected_math: list[str] = []

        def protect_math(match: re.Match[str]) -> str:
            protected_math.append(f"${match.group(0)}$")
            return f"\x00MATH{len(protected_math) - 1}\x00"

        outside = _BARE_MATH_RE.sub(protect_math, outside)
        # Any command still outside a math block is malformed provider output.
        # Preserve its readable name but never expose a raw backslash in the UI.
        outside = re.sub(r"\\([A-Za-z]+)", r"\1", outside)
        outside = outside.replace("\\", "")
        outside = outside.replace("$", "")
        for math_index, math_value in enumerate(protected_math):
            outside = outside.replace(f"\x00MATH{math_index}\x00", math_value)
        normalized.append(outside)
    return "".join(normalized)


def transcribe_question_image_bytes(
    payload: bytes,
    *,
    mime_type: str = "image/jpeg",
    target_label: str = "",
    timeout_seconds: int = 18,
) -> dict:
    """Quickly recover one printed question without solving the page.

    Mistake Book recovery used to ask a reasoning model for transcription,
    classification, two solutions, and final answers in one large request.
    Production traces showed that request timing out before returning any
    question.  This smaller transcription-only request uses the authorized
    fast vision model; worked solutions are generated separately from text.
    """
    label = str(target_label or "the target question").strip()
    prompt = TRANSCRIPTION_PROMPT.replace("{label}", label)
    candidates = list(dict.fromkeys([
        config.MISTAKE_RECOVERY_MODEL,
        config.WHOLE_DOCUMENT_FAST_FALLBACK_MODEL,
    ]))
    last_error: Exception | None = None
    for model in candidates:
        try:
            result = api_post_json(
                f"{cxsee_api_base()}/responses",
                {
                    "model": model,
                    "input": [
                        {
                            "role": "user",
                            "content": [
                                {"type": "input_text", "text": prompt},
                                {
                                    "type": "input_image",
                                    "image_url": _bytes_data_url(
                                        payload, mime_type
                                    ),
                                },
                            ],
                        }
                    ],
                    "reasoning": {"effort": "low"},
                    "text": {
                        "format": {
                            "type": "json_schema",
                            "name": "sumkora_question_transcription",
                            "strict": True,
                            "schema": {
                                "type": "object",
                                "additionalProperties": False,
                                "required": ["question"],
                                "properties": {
                                    "question": {"type": "string"}
                                },
                            },
                        }
                    },
                    "max_output_tokens": 1400,
                    "store": False,
                },
                headers={"Authorization": f"Bearer {config.CXSEE_API_KEY}"},
                # Two short attempts are materially more reliable than the
                # previous single 26-second request and still keep the whole
                # interaction below the browser's 29-second ceiling.
                timeout=max(8, min(12, int(timeout_seconds))),
                retries=1,
            )
            parsed = _parse_provider_json(
                _strip_json_fence(_extract_response_text(result))
            )
            question = normalize_mathjax_text(
                str(parsed.get("question") or "").strip()
            )
            if question:
                return {
                    "transcription": question,
                    "question_latex": question,
                    "model": result.get("model") or model,
                    "usage": result.get("usage") or {},
                }
        except Exception as exc:
            last_error = exc
    if last_error:
        raise last_error
    raise RuntimeError("The question transcription provider returned no text.")


def _clean_solution_fields(parsed: dict) -> None:
    for key in (
        "transcription",
        "question_latex",
        "solution_en",
        "solution_zh",
        "final_answer",
        "final_answer_zh",
    ):
        parsed[key] = normalize_mathjax_text(parsed.get(key, ""))


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
