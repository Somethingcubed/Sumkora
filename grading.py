import json
import re
import unicodedata
from datetime import datetime
from typing import Optional

import config
from db import execute, query_all, query_one
from ocr import cxsee_chat_completion, cxsee_response_text, ocr_text_for_page, run_submission_ocr
from pdf_utils import get_page_image_base64, get_page_text


MARKING_PREFIX = "Answer / marking notes:"


def grading_result(
    ai_mark: float,
    ai_confidence: float,
    ai_notes: str,
    risk_flags: Optional[list[str]] = None,
    needs_exception_review: bool = False,
    auto_finalize_reason: str = "auto_graded",
) -> dict:
    flags = risk_flags or []
    return {
        "ai_mark": ai_mark,
        "ai_confidence": ai_confidence,
        "ai_notes": ai_notes,
        "risk_flags": flags,
        "needs_exception_review": bool(needs_exception_review or flags),
        "auto_finalize_reason": auto_finalize_reason,
    }


def normalize_text(text: str) -> str:
    text = unicodedata.normalize("NFKC", text or "")
    replacements = {
        "−": "-",
        "–": "-",
        "—": "-",
        "×": "x",
        "÷": "/",
        "π": "pi",
        "Π": "pi",
        "²": "2",
        "³": "3",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    return text.lower()


def compact_math(text: str) -> str:
    text = normalize_text(text)
    text = re.sub(r"\b(cao|oe|final answer|answer)\b", " ", text)
    return re.sub(r"[^a-z0-9.+/=\\-]", "", text)


def clean_answer_line(line: str) -> str:
    line = normalize_text(line)
    line = re.sub(r"^\s*answer\s*[:=]\s*", " ", line)
    line = re.sub(r"\b(cao|oe|final answer|seen then spoilt)\b", " ", line)
    line = re.sub(r"\[[^\]]+\]", " ", line)
    return re.sub(r"\s+", " ", line).strip(" .;:")


def answer_candidates(mark_scheme_text: str) -> list[str]:
    text = (mark_scheme_text or "").replace(MARKING_PREFIX, "", 1).strip()
    if not text:
        return []

    explicit = []
    for match in re.finditer(
        r"\b(?:answer|lcm|hcf|mean|median|mode|x|y|n|m|r|p|q)\s*[:=]\s*([-+]?\d+(?:\.\d+)?(?:\s*[a-z%°]+)?)",
        normalize_text(text),
    ):
        explicit.append(clean_answer_line(match.group(1)))
    for match in re.finditer(r"\b(final|answer)\s+([-+]?\d+(?:\.\d+)?)\b", normalize_text(text)):
        explicit.append(clean_answer_line(match.group(2)))

    lines = [clean_answer_line(line) for line in text.splitlines()]
    candidates = []
    for line in lines:
        if not line:
            continue
        if re.match(r"^(m|a|b|sc)\d\b", line):
            break
        if re.match(r"^[1-9]\s+(m|a|b|sc)\d\b", line):
            break
        if line.startswith(("or b", "or m", "or sc", "if ", "with ", "where ")):
            continue
        if re.fullmatch(r"[1-9]", line):
            continue
        candidates.append(line)
        if len(candidates) >= 3:
            break

    split_candidates = []
    for candidate in candidates:
        for part in re.split(r"\s+\bor\b\s+|/", candidate):
            cleaned = clean_answer_line(part)
            if cleaned:
                split_candidates.append(cleaned)
    merged = explicit + split_candidates
    deduped = []
    for candidate in merged or candidates:
        if candidate and candidate not in deduped:
            deduped.append(candidate)
    return deduped


def number_tokens(text: str) -> list[str]:
    text = normalize_text(text)
    return re.findall(r"-?\d+(?:\.\d+)?", text)


def extract_labelled_response(page_text: str, label: str) -> tuple[str, bool]:
    if not page_text:
        return "", False
    normalized = normalize_text(page_text)
    escaped = re.escape(label.lower())
    pattern = re.compile(
        rf"(?:^|\n|\b){escaped}\s*[:.)-]?\s*(.*?)(?=\n\s*q\d{{1,2}}[a-zivx]*\s*[:.)-]?|\Z)",
        re.S,
    )
    match = pattern.search(normalized)
    if match:
        return match.group(1).strip(), True
    return normalized, False


def exact_answer_grade(question, page_text: str) -> Optional[dict]:
    candidates = answer_candidates(question["mark_scheme_text"])
    if not candidates or not page_text:
        return None

    response, labelled = extract_labelled_response(page_text, question["label"])
    if not response:
        return None

    response_compact = compact_math(response)
    expected_numbers = []
    for candidate in candidates:
        candidate_compact = compact_math(candidate)
        if candidate_compact and candidate_compact in response_compact:
            if float(question["max_marks"]) > 1:
                return grading_result(
                    0.0,
                    0.55 if labelled else 0.45,
                    (
                        f"Auto-check found possible answer '{candidate}', but this is a "
                        "multi-mark item. It was not awarded full marks by exact match alone."
                    ),
                    ["unsafe_exact_match_multi_mark"],
                    True,
                    "exception_exact_match_multi_mark",
                )
            return grading_result(
                float(question["max_marks"]),
                0.93 if labelled else 0.78,
                f"Auto-check matched answer '{candidate}' in extracted student text.",
                [],
                not labelled,
                "exact_answer_match",
            )
        nums = number_tokens(candidate)
        if nums:
            expected_numbers.extend(nums)

    if expected_numbers:
        response_numbers = set(number_tokens(response))
        expected_set = set(expected_numbers)
        if expected_set and expected_set.issubset(response_numbers):
            if float(question["max_marks"]) > 1:
                return grading_result(
                    0.0,
                    0.52 if labelled else 0.42,
                    (
                        "Auto-check found the required numeric token(s), but this is a "
                        "multi-mark item. It was not awarded full marks by numeric-token match alone."
                    ),
                    ["unsafe_numeric_subset_multi_mark"],
                    True,
                    "exception_numeric_subset_multi_mark",
                )
            return grading_result(
                float(question["max_marks"]),
                0.9 if labelled else 0.74,
                "Auto-check matched the required numeric answer(s) in extracted student text.",
                [],
                not labelled,
                "exact_numeric_match",
            )

    if labelled and response:
        if float(question["max_marks"]) <= 1:
            return grading_result(
                0.0,
                0.82,
                "Auto-check found a labelled answer-only response, but it did not match the mark scheme answer.",
                [],
                False,
                "exact_answer_mismatch",
            )
        return grading_result(
            0.0,
            0.72,
            "Auto-check found a labelled response, but it did not match the mark scheme answer. Human review is recommended if working may earn method marks.",
            ["answer_mismatch"],
            True,
            "exception_answer_mismatch",
        )
    return None


def needs_review_grade(page_text: str, risk_flag: str = "needs_review") -> dict:
    if page_text.strip():
        notes = (
            "Auto-check could not find a matching labelled answer in the extracted text. "
            "No marks awarded automatically; human review of the student's work is recommended."
        )
    else:
        notes = (
            "No readable text was found on this page. No marks awarded automatically "
            "without a vision-capable model; human review of the uploaded work is recommended."
        )
    return grading_result(
        0.0,
        0.2,
        notes,
        [risk_flag],
        True,
        f"exception_{risk_flag}",
    )


def clamp_mark(mark: float, max_marks: float) -> float:
    return max(0.0, min(float(mark), float(max_marks)))


def safe_json_object(raw: str) -> dict:
    raw = (raw or "").strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", raw, re.S)
        if match:
            return json.loads(match.group(0))
        raise


def openai_grade(question, page_b64: str) -> dict:
    from openai import OpenAI

    client = OpenAI(api_key=config.OPENAI_API_KEY)
    prompt = f"""You are grading Cambridge IGCSE Additional Mathematics 0606.
Question: {question['label']}
Max marks: {question['max_marks']}
Mark scheme: {question['mark_scheme_text']}

Look at the student's handwritten work on the attached page image.
Return JSON only with keys: ai_mark (number), ai_confidence (0-1), ai_notes (short string).
Apply Cambridge method marks where appropriate."""

    response = client.chat.completions.create(
        model=getattr(config, "OPENAI_MODEL", "gpt-4o-mini"),
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/png;base64,{page_b64}",
                        },
                    },
                ],
            }
        ],
        response_format={"type": "json_object"},
    )
    data = safe_json_object(response.choices[0].message.content)
    confidence = float(data.get("ai_confidence", 0.5))
    risk_flags = ["low_model_confidence"] if confidence < 0.65 else []
    return grading_result(
        clamp_mark(data.get("ai_mark", 0), question["max_marks"]),
        confidence,
        data.get("ai_notes", "AI grading complete."),
        risk_flags,
        bool(risk_flags),
        "openai_vision_grade",
    )


def cxsee_qwen_vision_grade(question, page_b64: str, page_text: str = "") -> dict:
    if not getattr(config, "CXSEE_API_KEY", ""):
        return grading_result(
            0.0,
            0.1,
            "CXSee API key is not configured, so Qwen vision grading did not run.",
            ["model_not_configured"],
            True,
            "exception_model_not_configured",
        )
    if not page_b64:
        return needs_review_grade(page_text)

    prompt = f"""You are evaluating Cambridge IGCSE Additional Mathematics 0606 student work.
Look at the attached student work image and grade only this question.

Question label: {question['label']}
Question text: {question['question_text'] or 'Not provided'}
Max marks: {question['max_marks']}
Mark scheme: {question['mark_scheme_text']}

OCR text already extracted from the page, if any:
{page_text or 'None'}

Rules:
- Return JSON only with keys ai_mark, ai_confidence, ai_notes.
- ai_mark must be between 0 and max marks.
- Award method marks only when the work shown supports them.
- If the page is blank, unrelated, unreadable, or cannot be matched to this question, set ai_mark to 0.
- Do not award marks just because the correct answer appears in the prompt or mark scheme.
- Keep ai_notes short and mention what evidence from the student's work you used."""

    try:
        result = cxsee_chat_completion(
            getattr(config, "CXSEE_MARKING_MODEL", "qwen3-vl-plus"),
            [
                {"type": "text", "text": prompt},
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:image/png;base64,{page_b64}"},
                },
            ],
        )
        data = safe_json_object(cxsee_response_text(result))
        notes = data.get("ai_notes", "Qwen vision grading complete.")
        confidence = float(data.get("ai_confidence", 0.5))
        risk_flags = []
        if confidence < 0.65:
            risk_flags.append("low_model_confidence")
        if not page_text.strip():
            risk_flags.append("no_ocr_text")
        return grading_result(
            clamp_mark(data.get("ai_mark", 0), question["max_marks"]),
            confidence,
            f"CXSee Qwen vision: {notes}",
            risk_flags,
            bool(risk_flags),
            "cxsee_qwen_vision_grade",
        )
    except Exception as exc:
        return grading_result(
            0.0,
            0.1,
            f"CXSee Qwen vision grading failed, so no marks were awarded automatically: {exc}",
            ["model_error"],
            True,
            "exception_model_error",
        )


def reusable_ai_suggestion(existing) -> bool:
    if not existing or existing["ai_mark"] is None:
        return False
    notes = (existing["ai_notes"] or "").lower()
    if not notes:
        return False
    retry_markers = [
        "failed",
        "not configured",
        "no readable text",
        "could not find",
        "did not run",
    ]
    return not any(marker in notes for marker in retry_markers)


def backfill_reusable_suggestion(existing):
    if not reusable_ai_suggestion(existing):
        return False
    if existing["teacher_override_mark"] is not None:
        return True
    if existing["auto_finalized_at"]:
        return True
    execute(
        """
        UPDATE grade_drafts
        SET final_mark = COALESCE(final_mark, ai_mark),
            risk_flags = COALESCE(NULLIF(risk_flags, ''), '[]'),
            needs_exception_review = COALESCE(needs_exception_review, 0),
            auto_finalized_at = ?,
            auto_finalize_reason = COALESCE(auto_finalize_reason, 'reused_ai_suggestion')
        WHERE id = ?
        """,
        (datetime.now().isoformat(), existing["id"]),
    )
    return True


def deepseek_text_grade(question, page_text: str) -> dict:
    from openai import OpenAI

    client = OpenAI(
        api_key=config.DEEPSEEK_API_KEY,
        base_url=getattr(config, "DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
    )
    response_text, labelled = extract_labelled_response(page_text, question["label"])
    if not labelled:
        return grading_result(
            0.0,
            0.35,
            (
                "DeepSeek text check could not find a clearly labelled response for this question. "
                "No marks awarded automatically; human review of the work is recommended."
            ),
            ["label_not_found"],
            True,
            "exception_label_not_found",
        )

    prompt = f"""You are evaluating Cambridge IGCSE Additional Mathematics 0606 student work.
Grade only the extracted student text for this one question.

Question label: {question['label']}
Question text: {question['question_text'] or 'Not provided'}
Max marks: {question['max_marks']}
Mark scheme: {question['mark_scheme_text']}

Extracted student response:
{response_text}

Rules:
- Return JSON only with keys ai_mark, ai_confidence, ai_notes.
- ai_mark must be between 0 and max marks, using Cambridge method marks where the mark scheme supports them.
- If the response is unrelated, blank, not mathematical, or cannot be matched to this question, set ai_mark to 0.
- Do not award marks for an answer that is merely mentioned in the mark scheme or prompt."""

    try:
        response = client.chat.completions.create(
            model=getattr(config, "DEEPSEEK_MODEL", "deepseek-v4-pro"),
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
        )
        data = safe_json_object(response.choices[0].message.content)
        confidence = float(data.get("ai_confidence", 0.5))
        risk_flags = ["low_model_confidence"] if confidence < 0.65 else []
        return grading_result(
            clamp_mark(data.get("ai_mark", 0), question["max_marks"]),
            confidence,
            data.get("ai_notes", "DeepSeek text grading complete."),
            risk_flags,
            bool(risk_flags),
            "deepseek_text_grade",
        )
    except Exception as exc:
        return grading_result(
            0.0,
            0.1,
            f"DeepSeek text grading failed, so no marks were awarded automatically: {exc}",
            ["model_error"],
            True,
            "exception_model_error",
        )


def grade_question(question, page_b64: str, page_text: str = "") -> dict:
    qwen_available = (
        getattr(config, "AI_PROVIDER", "") == "cxsee_qwen"
        and getattr(config, "CXSEE_API_KEY", "")
    )
    deepseek_available = (
        getattr(config, "AI_PROVIDER", "") == "deepseek"
        and getattr(config, "DEEPSEEK_API_KEY", "")
    )
    checked = exact_answer_grade(question, page_text)
    if checked:
        if checked["ai_mark"] > 0:
            return checked
        if qwen_available and float(question["max_marks"]) > 1:
            return cxsee_qwen_vision_grade(question, page_b64, page_text)
        if not deepseek_available or not page_text.strip():
            return checked
        return deepseek_text_grade(question, page_text)
    if qwen_available:
        return cxsee_qwen_vision_grade(question, page_b64, page_text)
    if deepseek_available:
        if page_text.strip():
            return deepseek_text_grade(question, page_text)
        return needs_review_grade(page_text, "no_readable_text")
    if config.OPENAI_API_KEY and page_b64:
        return openai_grade(question, page_b64)
    return needs_review_grade(page_text, "no_readable_text" if not page_text.strip() else "label_not_found")


def run_grading_job(submission_id: int):
    submission = query_one("SELECT * FROM submissions WHERE id = ?", (submission_id,))
    if not submission:
        return

    execute(
        "UPDATE submissions SET status = 'grading' WHERE id = ?",
        (submission_id,),
    )

    run_submission_ocr(submission_id, submission["file_path"])

    questions = query_all(
        "SELECT * FROM questions WHERE assignment_id = ? ORDER BY order_index",
        (submission["assignment_id"],),
    )

    for question in questions:
        native_text = get_page_text(
            submission["file_path"], question["page_number"]
        )
        ocr_text = ocr_text_for_page(
            submission_id, submission["file_path"], question["page_number"]
        )
        page_text = ocr_text.strip() or native_text
        page_b64 = get_page_image_base64(
            submission["file_path"], question["page_number"]
        )
        existing = query_one(
            """
            SELECT id, ai_mark, ai_confidence, ai_notes,
                   teacher_override_mark, auto_finalized_at
            FROM grade_drafts
            WHERE submission_id = ? AND question_id = ?
            """,
            (submission_id, question["id"]),
        )
        if existing and existing["teacher_override_mark"] is not None:
            execute(
                """
                UPDATE grade_drafts
                SET needs_exception_review = 0,
                    risk_flags = ''
                WHERE id = ?
                """,
                (existing["id"],),
            )
            continue
        if backfill_reusable_suggestion(existing):
            continue

        result = grade_question(question, page_b64, page_text)
        risk_flags = json.dumps(result.get("risk_flags", []), ensure_ascii=False)
        needs_exception_review = 1 if result.get("needs_exception_review") else 0
        auto_finalized_at = datetime.now().isoformat()
        auto_finalize_reason = result.get("auto_finalize_reason", "auto_graded")
        if existing:
            if submission["status"] == "pending":
                execute(
                    """
                    UPDATE grade_drafts
                    SET ai_mark = ?, ai_confidence = ?, ai_notes = ?,
                        final_mark = ?, risk_flags = ?, needs_exception_review = ?,
                        auto_finalized_at = ?, auto_finalize_reason = ?
                    WHERE id = ?
                    """,
                    (
                        result["ai_mark"],
                        result["ai_confidence"],
                        result["ai_notes"],
                        result["ai_mark"],
                        risk_flags,
                        needs_exception_review,
                        auto_finalized_at,
                        auto_finalize_reason,
                        existing["id"],
                    ),
                )
            else:
                execute(
                    """
                    UPDATE grade_drafts
                    SET ai_mark = ?, ai_confidence = ?, ai_notes = ?,
                        risk_flags = ?, needs_exception_review = ?,
                        auto_finalized_at = ?, auto_finalize_reason = ?,
                        final_mark = CASE
                            WHEN final_mark IS NULL OR final_mark = ai_mark THEN ?
                            ELSE final_mark
                        END
                    WHERE id = ?
                    """,
                    (
                        result["ai_mark"],
                        result["ai_confidence"],
                        result["ai_notes"],
                        risk_flags,
                        needs_exception_review,
                        auto_finalized_at,
                        auto_finalize_reason,
                        result["ai_mark"],
                        existing["id"],
                    ),
                )
        else:
            execute(
                """
                INSERT INTO grade_drafts
                (submission_id, question_id, ai_mark, ai_confidence, ai_notes,
                 final_mark, risk_flags, needs_exception_review,
                 auto_finalized_at, auto_finalize_reason)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    submission_id,
                    question["id"],
                    result["ai_mark"],
                    result["ai_confidence"],
                    result["ai_notes"],
                    result["ai_mark"],
                    risk_flags,
                    needs_exception_review,
                    auto_finalized_at,
                    auto_finalize_reason,
                ),
            )

    execute(
        "UPDATE submissions SET status = 'final' WHERE id = ?",
        (submission_id,),
    )


def finalize_submission(submission_id: int):
    grades = query_all(
        "SELECT id, ai_mark, final_mark FROM grade_drafts WHERE submission_id = ?",
        (submission_id,),
    )
    for g in grades:
        if g["final_mark"] is None and g["ai_mark"] is not None:
            execute(
                "UPDATE grade_drafts SET final_mark = ? WHERE id = ?",
                (g["ai_mark"], g["id"]),
            )
    execute(
        "UPDATE submissions SET status = 'final' WHERE id = ?",
        (submission_id,),
    )


def ensure_grade_rows(submission_id: int, assignment_id: int):
    questions = query_all(
        "SELECT id FROM questions WHERE assignment_id = ?",
        (assignment_id,),
    )
    for q in questions:
        existing = query_one(
            "SELECT id FROM grade_drafts WHERE submission_id = ? AND question_id = ?",
            (submission_id, q["id"]),
        )
        if not existing:
            execute(
                """
                INSERT INTO grade_drafts (submission_id, question_id)
                VALUES (?, ?)
                """,
                (submission_id, q["id"]),
            )


def reset_grade_rows(submission_id: int):
    execute(
        """
        UPDATE grade_drafts
        SET ai_mark = NULL,
            ai_confidence = NULL,
            ai_notes = NULL,
            final_mark = NULL,
            teacher_comment = NULL,
            risk_flags = '',
            needs_exception_review = 0,
            auto_finalized_at = NULL,
            auto_finalize_reason = NULL,
            teacher_override_mark = NULL,
            teacher_override_comment = NULL,
            teacher_override_at = NULL,
            teacher_override_by = NULL
        WHERE submission_id = ?
        """,
        (submission_id,),
    )
