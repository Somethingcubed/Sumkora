"""Student-owned paper ingestion, versioned analysis, and research helpers."""

from __future__ import annotations

import json
import os
import re
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import fitz

import config
from db import execute, query_all, query_one
from grading import grade_question
from ocr import cxsee_vl_ocr_detailed
from pdf_utils import get_page_image_base64, is_valid_pdf, save_upload


SELF_SERVICE_STAGES = [
    "validation",
    "document_extraction",
    "ocr",
    "question_mapping",
    "criterion_grading",
    "diagnosis",
    "profile_update",
    "report_generation",
]

CORE_SKILLS = [
    ("Algebra and graphs", "algebraic manipulation"),
    ("Algebra and graphs", "equations and inequalities"),
    ("Algebra and graphs", "functions and graphs"),
    ("Coordinate geometry", "coordinate geometry"),
    ("Geometry", "circular measure"),
    ("Trigonometry", "trigonometric identities and equations"),
    ("Calculus", "differentiation"),
    ("Calculus", "integration"),
    ("Series", "binomial theorem"),
    ("Vectors", "vectors in two dimensions"),
]


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def json_text(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def parse_json(value, fallback):
    try:
        parsed = json.loads(value or "")
        return parsed
    except (TypeError, json.JSONDecodeError):
        return fallback


def pdf_text(path: str, max_pages: int | None = None) -> str:
    with fitz.open(path) as document:
        pages = document if max_pages is None else list(document)[:max_pages]
        return "\n".join(page.get_text("text") for page in pages)


def normalize_answer_upload(filename: str, content: bytes) -> tuple[str, bytes]:
    suffix = Path(filename or "").suffix.lower()
    if is_valid_pdf(content):
        return Path(filename or "answer-script.pdf").name, content
    if suffix not in {".png", ".jpg", ".jpeg", ".webp"}:
        raise ValueError("Answer script must be a PDF, PNG, JPEG, or WebP image.")
    image_doc = fitz.open(stream=content, filetype=suffix.lstrip("."))
    pdf_bytes = image_doc.convert_to_pdf()
    image_doc.close()
    return f"{Path(filename).stem}.pdf", pdf_bytes


def save_document(prefix: str, filename: str, content: bytes) -> str:
    safe_name = Path(filename or f"{prefix}.pdf").name
    return save_upload(f"{prefix}_{uuid.uuid4().hex}_{safe_name}", content)


def _session(text: str) -> str:
    lower = text.lower()
    if "october/november" in lower or "oct/nov" in lower:
        return "October/November"
    if "may/june" in lower:
        return "May/June"
    if "february/march" in lower:
        return "February/March"
    return ""


def _topic(text: str) -> tuple[str, str]:
    lower = text.lower()
    rules = [
        (("differentiat", "stationary", "gradient function"), ("Calculus", "differentiation")),
        (("integrat", "area under"), ("Calculus", "integration")),
        (("sin ", "cos ", "tan ", "trigonom"), ("Trigonometry", "trigonometric identities and equations")),
        (("vector", "position vector"), ("Vectors", "vectors in two dimensions")),
        (("binomial", "coefficient of"), ("Series", "binomial theorem")),
        (("coordinate", "normal", "perpendicular bisector"), ("Coordinate geometry", "coordinate geometry")),
        (("circle", "radian", "arc", "sector"), ("Geometry", "circular measure")),
        (("function", "inverse", "composite"), ("Algebra and graphs", "functions and graphs")),
        (("inequal", "solve", "equation"), ("Algebra and graphs", "equations and inequalities")),
    ]
    for keywords, result in rules:
        if any(keyword in lower for keyword in keywords):
            return result
    return "Algebra and graphs", "algebraic manipulation"


def _question_chunks(text: str) -> list[dict]:
    cleaned = text.replace("\r", "\n")
    pattern = re.compile(
        r"(?m)^\s*(\d{1,2})(?:\s*\(([a-z])\))?(?:\s*\(([ivx]+)\))?\s+"
    )
    matches = list(pattern.finditer(cleaned))
    questions = []
    seen = set()
    for index, match in enumerate(matches[:80]):
        number, part, roman = match.groups()
        label = f"Q{number}"
        if part:
            label += part
        if roman:
            label += f"({roman})"
        if label in seen:
            continue
        seen.add(label)
        end = matches[index + 1].start() if index + 1 < len(matches) else len(cleaned)
        chunk = re.sub(r"\s+", " ", cleaned[match.end():end]).strip()
        if len(chunk) < 8:
            continue
        marks = re.findall(r"\[\s*(\d{1,2})\s*\]", chunk[-240:])
        maximum = int(marks[-1]) if marks else 1
        topic, skill = _topic(chunk)
        questions.append(
            {
                "label": label,
                "question_text": chunk[:2500],
                "mark_scheme_text": "",
                "maximum_marks": maximum,
                "topic": topic,
                "subtopic": skill,
                "skill": skill,
                "answer_page": min(index + 1, 80),
                "criteria": [],
            }
        )
    return questions


def _mark_scheme_chunks(text: str) -> dict[str, dict]:
    chunks = _question_chunks(text)
    result = {}
    for item in chunks:
        scheme = item["question_text"]
        criteria = []
        for index, match in enumerate(
            re.finditer(r"\b((?:M|A|B|SC)\d+)\b", scheme, re.I)
        ):
            start = max(0, match.start() - 100)
            end = min(len(scheme), match.end() + 180)
            code = match.group(1).upper()
            criteria.append(
                {
                    "code": code,
                    "mark_type": re.sub(r"\d", "", code),
                    "marks": int(re.sub(r"\D", "", code) or "1"),
                    "description": scheme[start:end].strip(),
                }
            )
        item["criteria"] = criteria
        result[item["label"]] = item
    return result


def detect_documents(question_path: str, mark_scheme_path: str, title_hint: str = "") -> dict:
    question_text = pdf_text(question_path, max_pages=8)
    mark_text = pdf_text(mark_scheme_path, max_pages=12) if mark_scheme_path else ""
    combined = f"{question_text}\n{mark_text}"
    question_plan = _question_chunks(question_text)
    schemes = _mark_scheme_chunks(mark_text)
    for question in question_plan:
        scheme = schemes.get(question["label"])
        if scheme:
            question["mark_scheme_text"] = scheme["question_text"]
            question["criteria"] = scheme["criteria"]
            if scheme["maximum_marks"] > question["maximum_marks"]:
                question["maximum_marks"] = scheme["maximum_marks"]
    if not question_plan:
        question_plan = list(schemes.values())
    if not question_plan:
        question_plan = [
            {
                "label": "Q1",
                "question_text": "Question text was not detected. Review before analysis.",
                "mark_scheme_text": mark_text[:4000],
                "maximum_marks": 1,
                "topic": "Unclassified",
                "subtopic": "",
                "skill": "unclassified",
                "answer_page": 1,
                "criteria": [],
            }
        ]

    code = re.search(r"\b(\d{4})\s*/\s*(\d{2})\b", combined)
    year = re.search(r"\b(20\d{2})\b", combined)
    maximum_matches = re.findall(
        r"(?:maximum\s+mark|total\s+marks?)\D{0,12}(\d{1,3})",
        combined,
        re.I,
    )
    maximum = (
        float(maximum_matches[-1])
        if maximum_matches
        else float(sum(q["maximum_marks"] for q in question_plan))
    )
    lines = [
        re.sub(r"\s+", " ", line).strip()
        for line in question_text.splitlines()
        if 8 <= len(re.sub(r"\s+", " ", line).strip()) <= 120
    ]
    detected_title = title_hint.strip() or (lines[0] if lines else "Untitled mathematics paper")
    calculator_policy = "unknown"
    if re.search(r"calculator(?:s)?\s+(?:must\s+not|not\s+allowed)", combined, re.I):
        calculator_policy = "non-calculator"
    elif re.search(r"calculator(?:s)?\s+(?:may|allowed|required)", combined, re.I):
        calculator_policy = "calculator"
    return {
        "metadata": {
            "title": detected_title[:160],
            "syllabus_code": code.group(1) if code else "0606",
            "paper_number": code.group(2) if code else "",
            "paper_year": int(year.group(1)) if year else None,
            "examination_session": _session(combined),
            "calculator_policy": calculator_policy,
            "maximum_marks": maximum,
            "source_type": "official" if code and code.group(1) == "0606" else "custom",
        },
        "questions": question_plan,
        "warnings": [
            warning
            for warning, condition in [
                ("Question text required manual review.", not question_text.strip()),
                ("Mark scheme text required manual review.", not mark_text.strip()),
                ("No paper number was detected.", not code),
            ]
            if condition
        ],
    }


def create_student_paper_draft(
    student_id: int,
    title_hint: str,
    question_filename: str,
    question_content: bytes,
    answer_filename: str,
    answer_content: bytes,
    mark_scheme_filename: str,
    mark_scheme_content: bytes,
) -> tuple[int, int]:
    if not is_valid_pdf(question_content):
        raise ValueError("Question paper must be a valid PDF.")
    if not is_valid_pdf(mark_scheme_content):
        raise ValueError("Mark scheme must be a valid PDF.")
    answer_filename, answer_content = normalize_answer_upload(
        answer_filename, answer_content
    )
    question_path = save_document("question", question_filename, question_content)
    answer_path = save_document("answers", answer_filename, answer_content)
    scheme_path = save_document("scheme", mark_scheme_filename, mark_scheme_content)
    detected = detect_documents(question_path, scheme_path, title_hint)
    metadata = detected["metadata"]
    now = now_iso()
    paper_id = execute(
        """
        INSERT INTO student_papers
        (student_id, title, syllabus_code, paper_number, paper_year,
         examination_session, calculator_policy, maximum_marks, source_type,
         status, latest_version_number, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'draft', 1, ?, ?)
        """,
        (
            student_id,
            metadata["title"],
            metadata["syllabus_code"],
            metadata["paper_number"],
            metadata["paper_year"],
            metadata["examination_session"],
            metadata["calculator_policy"],
            metadata["maximum_marks"],
            metadata["source_type"],
            now,
            now,
        ),
    )
    version_id = execute(
        """
        INSERT INTO paper_analysis_versions
        (paper_id, version_number, question_paper_path, answer_script_path,
         mark_scheme_path, detected_metadata, question_plan, ocr_model,
         grading_model, diagnosis_model, ocr_prompt_version, image_resolution,
         warnings, created_at, updated_at)
        VALUES (?, 1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            paper_id,
            question_path,
            answer_path,
            scheme_path,
            json_text(metadata),
            json_text(detected["questions"]),
            config.CXSEE_OCR_MODEL,
            config.CXSEE_MARKING_MODEL,
            config.CXSEE_DIAGNOSIS_MODEL or config.CXSEE_MARKING_MODEL,
            config.OCR_PROMPT_VERSION,
            config.OCR_RENDER_DPI,
            json_text(detected["warnings"]),
            now,
            now,
        ),
    )
    return paper_id, version_id


def create_rerun_draft(
    student_id: int,
    paper_id: int,
    question_file: tuple[str, bytes] | None,
    answer_file: tuple[str, bytes] | None,
    scheme_file: tuple[str, bytes] | None,
) -> int:
    paper = query_one(
        "SELECT * FROM student_papers WHERE id = ? AND student_id = ?",
        (paper_id, student_id),
    )
    latest = query_one(
        """
        SELECT * FROM paper_analysis_versions
        WHERE paper_id = ? ORDER BY version_number DESC LIMIT 1
        """,
        (paper_id,),
    )
    if not paper or not latest:
        raise ValueError("Paper was not found.")
    question_path = latest["question_paper_path"]
    answer_path = latest["answer_script_path"]
    scheme_path = latest["mark_scheme_path"]
    if question_file:
        if not is_valid_pdf(question_file[1]):
            raise ValueError("Replacement question paper must be a PDF.")
        question_path = save_document("question", *question_file)
    if answer_file:
        filename, content = normalize_answer_upload(*answer_file)
        answer_path = save_document("answers", filename, content)
    if scheme_file:
        if not is_valid_pdf(scheme_file[1]):
            raise ValueError("Replacement mark scheme must be a PDF.")
        scheme_path = save_document("scheme", *scheme_file)
    version_number = int(latest["version_number"]) + 1
    detected = detect_documents(question_path, scheme_path, paper["title"])
    now = now_iso()
    version_id = execute(
        """
        INSERT INTO paper_analysis_versions
        (paper_id, version_number, supersedes_version_id, question_paper_path,
         answer_script_path, mark_scheme_path, detected_metadata, question_plan,
         ocr_model, grading_model, diagnosis_model, ocr_prompt_version,
         image_resolution, warnings, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            paper_id,
            version_number,
            latest["id"],
            question_path,
            answer_path,
            scheme_path,
            json_text(detected["metadata"]),
            json_text(detected["questions"]),
            config.CXSEE_OCR_MODEL,
            config.CXSEE_MARKING_MODEL,
            config.CXSEE_DIAGNOSIS_MODEL or config.CXSEE_MARKING_MODEL,
            config.OCR_PROMPT_VERSION,
            config.OCR_RENDER_DPI,
            json_text(detected["warnings"]),
            now,
            now,
        ),
    )
    execute(
        "UPDATE student_papers SET status = 'draft', updated_at = ? WHERE id = ?",
        (now, paper_id),
    )
    return version_id


def confirm_version(
    student_id: int,
    version_id: int,
    metadata: dict,
    questions: list[dict],
) -> int:
    version = query_one(
        """
        SELECT pav.*, sp.student_id
        FROM paper_analysis_versions pav
        JOIN student_papers sp ON sp.id = pav.paper_id
        WHERE pav.id = ? AND sp.student_id = ?
        """,
        (version_id, student_id),
    )
    if not version:
        raise ValueError("Analysis version was not found.")
    now = now_iso()
    execute(
        """
        UPDATE paper_analysis_versions
        SET status = 'queued', current_stage = 'validation',
            confirmed_metadata = ?, question_plan = ?, updated_at = ?
        WHERE id = ?
        """,
        (json_text(metadata), json_text(questions), now, version_id),
    )
    execute(
        """
        UPDATE student_papers
        SET title = ?, syllabus_code = ?, paper_number = ?, paper_year = ?,
            examination_session = ?, calculator_policy = ?,
            maximum_marks = ?, source_type = ?, status = 'processing',
            latest_version_number = ?, updated_at = ?
        WHERE id = ?
        """,
        (
            metadata.get("title") or "Untitled paper",
            metadata.get("syllabus_code") or "custom",
            metadata.get("paper_number") or "",
            metadata.get("paper_year") or None,
            metadata.get("examination_session") or "",
            metadata.get("calculator_policy") or "unknown",
            float(metadata.get("maximum_marks") or 0),
            metadata.get("source_type") or "custom",
            version["version_number"],
            now,
            version["paper_id"],
        ),
    )
    return version["paper_id"]


def _update_version(version_id: int, stage: str, index: int, status: str = "processing"):
    execute(
        """
        UPDATE paper_analysis_versions
        SET status = ?, current_stage = ?, stage_index = ?,
            started_at = COALESCE(started_at, ?), updated_at = ?
        WHERE id = ?
        """,
        (status, stage, index, now_iso(), now_iso(), version_id),
    )


def _diagnosis(mark: float, maximum: float, confidence: float, flags: list[str]):
    if mark >= maximum:
        return None, None
    if "model_error" in flags or confidence < 0.35:
        return "uncertain evidence", "OCR or model output requires review"
    if mark <= 0:
        return "method selection", "required method was not demonstrated"
    return "procedural execution", "method was only partially completed"


def run_self_service_analysis(version_id: int) -> dict:
    version = query_one(
        """
        SELECT pav.*, sp.student_id, sp.id AS student_paper_id
        FROM paper_analysis_versions pav
        JOIN student_papers sp ON sp.id = pav.paper_id
        WHERE pav.id = ?
        """,
        (version_id,),
    )
    if not version:
        return {"status": "failed", "error": "Version was not found."}
    try:
        for path in (
            version["question_paper_path"],
            version["answer_script_path"],
            version["mark_scheme_path"],
        ):
            if not path or not os.path.isfile(path):
                raise RuntimeError("One of the required analysis documents is missing.")
        questions = parse_json(version["question_plan"], [])
        if not questions:
            raise RuntimeError("No questions were confirmed for analysis.")

        _update_version(version_id, "validation", 0)
        _update_version(version_id, "document_extraction", 1)
        with fitz.open(version["answer_script_path"]) as answer_doc:
            page_count = len(answer_doc)
        if page_count > 80:
            raise RuntimeError("Answer script exceeds the 80-page limit.")

        _update_version(version_id, "ocr", 2)
        page_texts = {}
        page_confidences = {}
        for page_number in range(1, page_count + 1):
            started = time.monotonic()
            with fitz.open(version["answer_script_path"]) as answer_doc:
                native = answer_doc[page_number - 1].get_text("text").strip()
            raw = None
            warnings = []
            model = "native-pdf-text"
            provider = "native"
            confidence = 0.98 if native else 0.0
            text = native
            if not native and config.OCR_ENABLED:
                image_b64 = get_page_image_base64(
                    version["answer_script_path"], page_number, dpi=version["image_resolution"]
                )
                text, confidence, raw = cxsee_vl_ocr_detailed(image_b64)
                provider = "cxsee"
                meta = raw.get("_numera", {})
                model = meta.get("used_model", version["ocr_model"])
                if meta.get("warning"):
                    warnings.append(meta["warning"])
            elif not native:
                warnings.append("OCR disabled; no native text was available.")
            duration = int((time.monotonic() - started) * 1000)
            page_texts[page_number] = text
            page_confidences[page_number] = confidence or 0.0
            execute(
                """
                INSERT INTO analysis_ocr_pages
                (analysis_version_id, document_type, page_number, provider,
                 model, prompt_version, text, normalized_text, confidence,
                 warnings, raw_response, timing_ms, created_at)
                VALUES (?, 'answer_script', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    version_id,
                    page_number,
                    provider,
                    model,
                    version["ocr_prompt_version"],
                    text,
                    re.sub(r"\s+", " ", text).strip(),
                    confidence,
                    json_text(warnings),
                    json_text(raw) if raw else None,
                    duration,
                    now_iso(),
                ),
            )

        _update_version(version_id, "question_mapping", 3)
        _update_version(version_id, "criterion_grading", 4)
        execute(
            "DELETE FROM analysis_question_results WHERE analysis_version_id = ?",
            (version_id,),
        )
        confirmed_min = provisional = possible_max = 0.0
        for index, item in enumerate(questions):
            page_number = min(max(int(item.get("answer_page") or 1), 1), page_count)
            page_text = page_texts.get(page_number, "")
            question = {
                "label": item.get("label") or f"Q{index + 1}",
                "question_text": item.get("question_text") or "",
                "max_marks": float(item.get("maximum_marks") or 1),
                "mark_scheme_text": item.get("mark_scheme_text") or "",
            }
            image_b64 = get_page_image_base64(
                version["answer_script_path"], page_number, dpi=version["image_resolution"]
            )
            result = grade_question(question, image_b64, page_text)
            mark = float(result.get("ai_mark") or 0)
            maximum = question["max_marks"]
            confidence = float(result.get("ai_confidence") or 0)
            flags = result.get("risk_flags") or []
            uncertain = confidence < float(version["confidence_threshold"]) or bool(flags)
            if uncertain:
                possible_max += maximum
            else:
                confirmed_min += mark
                possible_max += mark
            provisional += mark
            topic = item.get("topic") or "Unclassified"
            skill = item.get("skill") or item.get("subtopic") or topic
            category, mechanism = _diagnosis(mark, maximum, confidence, flags)
            result_id = execute(
                """
                INSERT INTO analysis_question_results
                (analysis_version_id, question_label, question_text,
                 mark_scheme_text, structured_criteria, maximum_marks, topic,
                 subtopic, skill, answer_page, response_text,
                 mapping_confidence, ai_mark, ai_confidence, ai_rationale,
                 cited_evidence, error_category, error_mechanism,
                 deterministic_check, risk_flags, model, prompt_version,
                 created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                        ?, ?, ?, ?, ?)
                """,
                (
                    version_id,
                    question["label"],
                    question["question_text"],
                    question["mark_scheme_text"],
                    json_text(item.get("criteria") or []),
                    maximum,
                    topic,
                    item.get("subtopic") or "",
                    skill,
                    page_number,
                    page_text[:12000],
                    page_confidences.get(page_number, 0.5),
                    mark,
                    confidence,
                    result.get("ai_notes") or "",
                    page_text[:1200],
                    category,
                    mechanism,
                    json_text({"enabled": bool(version["deterministic_checks"])}),
                    json_text(flags),
                    version["grading_model"],
                    version["grading_prompt_version"],
                    now_iso(),
                ),
            )
            weight = max(maximum, 1) * max(confidence, 0.1) * max(
                page_confidences.get(page_number, 0.5), 0.1
            )
            execute(
                """
                INSERT INTO analysis_skill_observations
                (student_id, paper_id, analysis_version_id, question_result_id,
                 observed_at, topic, subtopic, skill, marks_earned,
                 marks_available, success_fraction, grading_confidence,
                 extraction_confidence, evidence_weight, error_category,
                 error_mechanism, is_current)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
                """,
                (
                    version["student_id"],
                    version["student_paper_id"],
                    version_id,
                    result_id,
                    now_iso(),
                    topic,
                    item.get("subtopic") or "",
                    skill,
                    mark,
                    maximum,
                    mark / maximum if maximum else 0,
                    confidence,
                    page_confidences.get(page_number, 0.5),
                    weight,
                    category,
                    mechanism,
                ),
            )
            if "model_error" in flags:
                execute(
                    """
                    INSERT INTO research_failure_cases
                    (analysis_version_id, question_result_id, failure_type,
                     severity, tags, notes, created_at, updated_at)
                    VALUES (?, ?, 'grading_model_error', 'high',
                            '["model_error"]', ?, ?, ?)
                    """,
                    (
                        version_id,
                        result_id,
                        result.get("ai_notes") or "",
                        now_iso(),
                        now_iso(),
                    ),
                )

        _update_version(version_id, "diagnosis", 5)
        execute(
            """
            UPDATE analysis_skill_observations
            SET is_current = 0
            WHERE paper_id = ? AND analysis_version_id != ?
            """,
            (version["student_paper_id"], version_id),
        )
        _update_version(version_id, "profile_update", 6)
        from assessment import rebuild_student_profile

        rebuild_student_profile(version["student_id"])
        _update_version(version_id, "report_generation", 7)
        execute(
            """
            UPDATE paper_analysis_versions
            SET status = 'completed', current_stage = 'completed',
                stage_index = ?, confirmed_min_score = ?,
                provisional_score = ?, possible_max_score = ?,
                updated_at = ?, finished_at = ?
            WHERE id = ?
            """,
            (
                len(SELF_SERVICE_STAGES),
                round(confirmed_min, 2),
                round(provisional, 2),
                round(possible_max, 2),
                now_iso(),
                now_iso(),
                version_id,
            ),
        )
        execute(
            """
            UPDATE student_papers
            SET status = 'completed', latest_version_number = ?, updated_at = ?
            WHERE id = ?
            """,
            (version["version_number"], now_iso(), version["student_paper_id"]),
        )
        return {"status": "completed", "paper_id": version["student_paper_id"]}
    except Exception as exc:
        execute(
            """
            UPDATE paper_analysis_versions
            SET status = 'failed', failure_message = ?, updated_at = ?,
                finished_at = ?
            WHERE id = ?
            """,
            (str(exc), now_iso(), now_iso(), version_id),
        )
        execute(
            "UPDATE student_papers SET status = 'failed', updated_at = ? WHERE id = ?",
            (now_iso(), version["student_paper_id"]),
        )
        return {"status": "failed", "error": str(exc)}


def student_owned_papers(student_id: int):
    return query_all(
        """
        SELECT sp.*, pav.id AS latest_version_id, pav.status AS analysis_status,
               pav.confirmed_min_score, pav.provisional_score,
               pav.possible_max_score, pav.created_at AS analysis_created_at,
               (SELECT COUNT(*) FROM paper_analysis_versions v
                WHERE v.paper_id = sp.id) AS version_count
        FROM student_papers sp
        LEFT JOIN paper_analysis_versions pav
          ON pav.paper_id = sp.id
         AND pav.version_number = sp.latest_version_number
        WHERE sp.student_id = ? AND sp.status != 'archived'
        ORDER BY sp.updated_at DESC
        """,
        (student_id,),
    )


def paper_with_versions(student_id: int, paper_id: int):
    paper = query_one(
        "SELECT * FROM student_papers WHERE id = ? AND student_id = ?",
        (paper_id, student_id),
    )
    if not paper:
        return None, []
    versions = query_all(
        """
        SELECT pav.*,
               (SELECT COUNT(*) FROM analysis_question_results aqr
                WHERE aqr.analysis_version_id = pav.id) AS question_count
        FROM paper_analysis_versions pav
        WHERE pav.paper_id = ?
        ORDER BY pav.version_number DESC
        """,
        (paper_id,),
    )
    return paper, versions


def analysis_result(student_id: int, paper_id: int, version_id: int | None = None):
    paper = query_one(
        "SELECT * FROM student_papers WHERE id = ? AND student_id = ?",
        (paper_id, student_id),
    )
    if not paper:
        return None
    if version_id:
        version = query_one(
            "SELECT * FROM paper_analysis_versions WHERE id = ? AND paper_id = ?",
            (version_id, paper_id),
        )
    else:
        version = query_one(
            """
            SELECT * FROM paper_analysis_versions
            WHERE paper_id = ? ORDER BY version_number DESC LIMIT 1
            """,
            (paper_id,),
        )
    if not version:
        return None
    questions = query_all(
        """
        SELECT aqr.*,
               (SELECT corrected_mark FROM analysis_human_corrections ahc
                WHERE ahc.analysis_question_result_id = aqr.id
                ORDER BY ahc.id DESC LIMIT 1) AS human_mark
        FROM analysis_question_results aqr
        WHERE aqr.analysis_version_id = ?
        ORDER BY aqr.id
        """,
        (version["id"],),
    )
    return {"paper": paper, "version": version, "questions": questions}


def direct_profile_rows(student_id: int):
    return query_all(
        """
        SELECT aso.*, sp.title AS paper_title, pav.version_number
        FROM analysis_skill_observations aso
        JOIN student_papers sp ON sp.id = aso.paper_id
        JOIN paper_analysis_versions pav ON pav.id = aso.analysis_version_id
        WHERE aso.student_id = ? AND aso.is_current = 1
        ORDER BY aso.observed_at
        """,
        (student_id,),
    )


def direct_summary(student_id: int) -> dict:
    papers = student_owned_papers(student_id)
    completed = [row for row in papers if row["analysis_status"] == "completed"]
    percentages = []
    for row in completed:
        maximum = float(row["maximum_marks"] or 0)
        percentages.append(
            100 * float(row["provisional_score"] or 0) / maximum if maximum else 0
        )
    return {
        "papers": papers,
        "completed_count": len(completed),
        "latest_percentage": round(percentages[0], 1) if percentages else None,
        "average_percentage": round(sum(percentages) / len(percentages), 1)
        if percentages
        else None,
    }


def compare_direct_papers(student_id: int, paper_ids: list[int]) -> dict:
    papers = []
    for paper_id in paper_ids:
        result = analysis_result(student_id, paper_id)
        if not result or result["version"]["status"] != "completed":
            continue
        paper = dict(result["paper"])
        version = result["version"]
        maximum = float(paper["maximum_marks"] or 0)
        provisional = float(version["provisional_score"] or 0)
        lost_by_topic = {}
        for question in result["questions"]:
            lost = max(
                0.0,
                float(question["maximum_marks"] or 0)
                - float(question["ai_mark"] or 0),
            )
            topic = question["topic"] or "Unclassified"
            lost_by_topic[topic] = round(lost_by_topic.get(topic, 0) + lost, 2)
        papers.append(
            {
                **paper,
                "version_id": version["id"],
                "version_number": version["version_number"],
                "earned": provisional,
                "possible": maximum,
                "percentage": round(100 * provisional / maximum, 1)
                if maximum
                else 0,
                "confirmed_min": version["confirmed_min_score"],
                "possible_max": version["possible_max_score"],
                "marks_lost": lost_by_topic,
            }
        )
    warnings = []
    if len(papers) < 2:
        warnings.append("Select at least two completed papers for a useful comparison.")
    if len({paper["possible"] for paper in papers}) > 1:
        warnings.append("Maximum marks differ; compare percentages as well as raw marks.")
    if len({paper["calculator_policy"] for paper in papers}) > 1:
        warnings.append("Calculator policies differ between the selected papers.")
    return {"papers": papers, "warnings": warnings}
