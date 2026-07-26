"""Student-owned paper ingestion, versioned analysis, and research helpers."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

import fitz

import config
from db import execute, query_all, query_one
from document_assessment import ASSESSMENT_PROMPT_VERSION, assess_documents
from grading import grade_question
from ocr import cxsee_vl_ocr_detailed
from pdf_utils import get_page_image_base64, is_valid_pdf, save_upload


logger = logging.getLogger(__name__)


SELF_SERVICE_STAGES = [
    "validation",
    "document_extraction",
    "whole_document_reasoning",
    "result_validation",
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


def _match_question_bank_parent(
    assessment: dict,
    question: dict,
) -> int | None:
    """Link a result only when one complete approved source question is clear."""
    syllabus_match = re.search(
        r"\b(\d{4})\b",
        str(assessment.get("syllabus_code") or ""),
    )
    question_match = re.search(r"\d+", str(question.get("label") or ""))
    if not syllabus_match or not question_match:
        return None
    reference = " ".join(
        (
            str(assessment.get("paper_reference") or ""),
            str(assessment.get("paper_title") or ""),
        )
    )
    component_candidates = [
        value
        for value in re.findall(r"(?<!\d)([12][1-3])(?!\d)", reference)
    ]
    if not component_candidates:
        return None
    component = component_candidates[0]
    rows = query_all(
        """
        SELECT pq.id
        FROM paper_questions pq
        JOIN paper_packs pp ON pp.id = pq.paper_pack_id
        WHERE pp.syllabus_code = ? AND pp.component = ?
          AND pq.question_number = ? AND pq.parent_question_id IS NULL
          AND pq.review_status = 'ready'
          AND pq.question_asset_path IS NOT NULL
        ORDER BY pp.year DESC, pq.id DESC
        LIMIT 2
        """,
        (
            syllabus_match.group(1),
            component,
            question_match.group(0),
        ),
    )
    return int(rows[0]["id"]) if len(rows) == 1 else None


def pdf_text(path: str, max_pages: int | None = None) -> str:
    with fitz.open(path) as document:
        pages = document if max_pages is None else list(document)[:max_pages]
        return "\n".join(page.get_text("text") for page in pages)


def _content_blocks(page) -> list[tuple[float, float, str]]:
    blocks = []
    for block in page.get_text("blocks"):
        x0, y0, x1, y1, text = block[:5]
        normalized = re.sub(r"\s+", " ", text).strip()
        if not normalized or y0 < 50 or y1 > 775 or x0 < 25 or x1 > 570:
            continue
        if any(
            phrase in normalized
            for phrase in (
                "DO NOT WRITE IN THIS MARGIN",
                "© UCLES",
                "© Cambridge University Press",
            )
        ):
            continue
        blocks.append((float(x0), float(y0), normalized))
    return sorted(blocks, key=lambda item: (item[1], item[0]))


def pdf_question_text(path: str) -> str:
    grouped: dict[int, list[str]] = {}
    current_number: int | None = None
    with fitz.open(path) as document:
        for page in document:
            for x0, y0, text in _content_blocks(page):
                combined = re.match(
                    r"^(\d{1,2})(?:\s*\([a-z]\))?\s+([A-Za-z(].{5,})",
                    text,
                )
                standalone = re.fullmatch(r"(\d{1,2})(?:\s*\([a-z]\))?", text)
                candidate = None
                remainder = ""
                if x0 < 95 and combined:
                    candidate = int(combined.group(1))
                    remainder = text[len(combined.group(1)):].strip()
                elif x0 < 95 and y0 < 180 and standalone:
                    candidate = int(standalone.group(1))
                if candidate is not None:
                    expected = 1 if current_number is None else current_number + 1
                    if candidate == expected:
                        current_number = candidate
                        grouped.setdefault(candidate, [])
                        if remainder:
                            grouped[candidate].append(remainder)
                        continue
                if current_number is not None:
                    grouped[current_number].append(text)
    return "\n".join(
        f"Q{number} {' '.join(grouped[number])}"
        for number in sorted(grouped)
        if grouped[number]
    )


def pdf_mark_scheme_text(path: str) -> str:
    grouped: dict[int, list[str]] = {}
    current_number: int | None = None
    with fitz.open(path) as document:
        for page in document:
            page_text_value = page.get_text("text")
            if "Question" not in page_text_value or "Guidance" not in page_text_value:
                continue
            for x0, _y0, text in _content_blocks(page):
                starter = re.match(
                    r"^(\d{1,2})(?:\s*\([a-z]\)|\([a-z]\))?(?=\s|$)",
                    text,
                )
                if x0 < 78 and starter:
                    candidate = int(starter.group(1))
                    expected = 1 if current_number is None else current_number + 1
                    if candidate in {current_number, expected}:
                        current_number = candidate
                        grouped.setdefault(candidate, []).append(text)
                        continue
                if current_number is not None:
                    grouped[current_number].append(text)
    return "\n".join(
        f"Q{number} {' '.join(grouped[number])}"
        for number in sorted(grouped)
        if grouped[number]
    )


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
        r"(?mi)^\s*(?:[-#>]\s*)?\*{0,2}(?:question\s*)?q?"
        r"(\d{1,2})(?:\s*\(([a-z])\)|\s+([a-z])(?=\s))?"
        r"(?:\s*\(([ivx]+)\))?\*{0,2}(?:\s+|[.:\-]\s*)"
    )
    matches = list(pattern.finditer(cleaned))
    questions_by_number: dict[int, dict] = {}
    for index, match in enumerate(matches[:80]):
        number, part, inline_part, roman = match.groups()
        number_value = int(number)
        if number_value < 1 or number_value > 50:
            continue
        label = f"Q{number}"
        end = matches[index + 1].start() if index + 1 < len(matches) else len(cleaned)
        chunk = re.sub(r"\s+", " ", cleaned[match.end():end]).strip()
        if len(chunk) < 8:
            continue
        marks = re.findall(r"\[\s*(\d{1,2})\s*\]", chunk)
        maximum = sum(int(value) for value in marks) if marks else 1
        topic, skill = _topic(chunk)
        part_label = part or inline_part
        prefix = f"({part_label}) " if part_label else ""
        if roman:
            prefix += f"({roman}) "
        existing = questions_by_number.get(number_value)
        if existing:
            combined = f"{existing['question_text']} {prefix}{chunk}".strip()
            existing["question_text"] = combined[:5000]
            existing["maximum_marks"] = (
                float(existing["maximum_marks"]) + float(maximum)
                if part_label or roman
                else max(float(existing["maximum_marks"]), float(maximum))
            )
            if existing["topic"] == "Algebra and graphs" and topic != existing["topic"]:
                existing["topic"] = topic
                existing["subtopic"] = skill
                existing["skill"] = skill
            continue
        questions_by_number[number_value] = {
            "label": label,
            "question_text": f"{prefix}{chunk}"[:5000],
            "mark_scheme_text": "",
            "maximum_marks": maximum,
            "topic": topic,
            "subtopic": skill,
            "skill": skill,
            "answer_page": 1,
            "criteria": [],
        }
    return [questions_by_number[key] for key in sorted(questions_by_number)]


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


def detect_document_texts(
    question_text: str,
    mark_text: str,
    title_hint: str = "",
) -> dict:
    combined = f"{question_text}\n{mark_text}"
    question_plan = _question_chunks(question_text)
    schemes = _mark_scheme_chunks(mark_text)
    planned_labels = {question["label"] for question in question_plan}
    for question in question_plan:
        scheme = schemes.get(question["label"])
        if scheme:
            question["mark_scheme_text"] = scheme["question_text"]
            question["criteria"] = scheme["criteria"]
            if scheme["maximum_marks"] > question["maximum_marks"]:
                question["maximum_marks"] = scheme["maximum_marks"]
    for label, scheme in schemes.items():
        if label not in planned_labels:
            question_plan.append(scheme)
    question_plan.sort(
        key=lambda item: int(re.sub(r"\D", "", item.get("label", "")) or 999)
    )
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


def detect_documents(question_path: str, mark_scheme_path: str, title_hint: str = "") -> dict:
    question_text = pdf_question_text(question_path) or pdf_text(question_path, max_pages=50)
    mark_text = (
        pdf_mark_scheme_text(mark_scheme_path)
        or pdf_text(mark_scheme_path, max_pages=60)
        if mark_scheme_path
        else ""
    )
    return detect_document_texts(question_text, mark_text, title_hint)


def create_student_paper_draft(
    student_id: int,
    answer_filename: str,
    answer_content: bytes,
    mark_scheme_filename: str | None = None,
    mark_scheme_content: bytes | None = None,
    expected_maximum_marks: float | None = None,
) -> tuple[int, int]:
    answer_filename, answer_content = normalize_answer_upload(
        answer_filename, answer_content
    )
    if mark_scheme_content is not None:
        if not is_valid_pdf(mark_scheme_content):
            raise ValueError("Mark scheme must be a valid PDF.")
        if hashlib.sha256(answer_content).digest() == hashlib.sha256(
            mark_scheme_content
        ).digest():
            raise ValueError("Completed work and mark scheme must be different documents.")
    answer_path = save_document("answers", answer_filename, answer_content)
    scheme_path = (
        save_document(
            "scheme",
            mark_scheme_filename or "mark-scheme.pdf",
            mark_scheme_content,
        )
        if mark_scheme_content is not None
        else None
    )
    metadata = {
        "title": Path(answer_filename).stem[:160] or "Mathematics paper",
        "syllabus_code": "Mathematics",
        "paper_number": "",
        "paper_year": None,
        "examination_session": "",
        "calculator_policy": "unknown",
        "maximum_marks": 0,
        "source_type": "student_upload",
    }
    mode = "detailed" if scheme_path else "estimate"
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
         warnings, assessment_mode, expected_maximum_marks, created_at, updated_at)
        VALUES (?, 1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            paper_id,
            "",
            answer_path,
            scheme_path,
            json_text(metadata),
            "[]",
            "",
            config.WHOLE_DOCUMENT_MODEL,
            config.WHOLE_DOCUMENT_MODEL,
            ASSESSMENT_PROMPT_VERSION,
            config.OCR_RENDER_DPI,
            json_text(
                []
                if scheme_path
                else ["Estimated assessment: no mark scheme was provided."]
            ),
            mode,
            expected_maximum_marks,
            now,
            now,
        ),
    )
    return paper_id, version_id


def create_rerun_draft(
    student_id: int,
    paper_id: int,
    answer_file: tuple[str, bytes] | None,
    scheme_file: tuple[str, bytes] | None,
    expected_maximum_marks: float | None = None,
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
    answer_path = latest["answer_script_path"]
    scheme_path = latest["mark_scheme_path"]
    if answer_file:
        filename, content = normalize_answer_upload(*answer_file)
        answer_path = save_document("answers", filename, content)
    if scheme_file:
        if not is_valid_pdf(scheme_file[1]):
            raise ValueError("Replacement mark scheme must be a PDF.")
        scheme_path = save_document("scheme", *scheme_file)
    version_number = int(latest["version_number"]) + 1
    metadata = {
        "title": paper["title"],
        "syllabus_code": paper["syllabus_code"],
        "paper_number": paper["paper_number"],
        "paper_year": paper["paper_year"],
        "examination_session": paper["examination_session"],
        "calculator_policy": paper["calculator_policy"],
        "maximum_marks": paper["maximum_marks"],
        "source_type": paper["source_type"],
    }
    mode = "detailed" if scheme_path else "estimate"
    now = now_iso()
    version_id = execute(
        """
        INSERT INTO paper_analysis_versions
        (paper_id, version_number, supersedes_version_id, question_paper_path,
         answer_script_path, mark_scheme_path, detected_metadata, question_plan,
         ocr_model, grading_model, diagnosis_model, ocr_prompt_version,
         image_resolution, warnings, assessment_mode, expected_maximum_marks,
         created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            paper_id,
            version_number,
            latest["id"],
            "",
            answer_path,
            scheme_path,
            json_text(metadata),
            "[]",
            "",
            config.WHOLE_DOCUMENT_MODEL,
            config.WHOLE_DOCUMENT_MODEL,
            ASSESSMENT_PROMPT_VERSION,
            config.OCR_RENDER_DPI,
            json_text(
                []
                if scheme_path
                else ["Estimated assessment: no mark scheme was provided."]
            ),
            mode,
            expected_maximum_marks,
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


def _extract_analysis_page(
    *,
    path: str,
    page_number: int,
    native: str,
    force_vision: bool,
    image_resolution: int,
    configured_ocr_model: str,
) -> dict:
    started = time.monotonic()
    raw = None
    warnings = []
    model = "native-pdf-text"
    provider = "native"
    confidence = 0.98 if native else 0.0
    text = native
    should_use_vision = bool(
        config.OCR_ENABLED and (force_vision or len(native) < 80)
    )
    if should_use_vision:
        image_b64 = get_page_image_base64(
            path,
            page_number,
            dpi=image_resolution,
        )
        vision_text, vision_confidence, raw = cxsee_vl_ocr_detailed(image_b64)
        if vision_text and vision_text.strip():
            text = vision_text
            confidence = vision_confidence or 0.0
            provider = "cxsee"
            meta = (
                raw.get("_sumkora", raw.get("_numera", {}))
                if isinstance(raw, dict)
                else {}
            )
            model = meta.get("used_model", configured_ocr_model)
            if meta.get("warning"):
                warnings.append(meta["warning"])
        elif native:
            warnings.append("Vision OCR was empty; native PDF text was used.")
    elif not native:
        warnings.append("OCR disabled; no native text was available.")
    return {
        "page_number": page_number,
        "text": text,
        "confidence": confidence or 0.0,
        "provider": provider,
        "model": model,
        "warnings": warnings,
        "raw": raw,
        "duration": int((time.monotonic() - started) * 1000),
    }


def _extract_analysis_document(
    version,
    document_type: str,
    path: str,
    *,
    force_vision: bool = False,
) -> tuple[dict[int, str], dict[int, float]]:
    page_texts: dict[int, str] = {}
    page_confidences: dict[int, float] = {}
    execute(
        """
        DELETE FROM analysis_ocr_pages
        WHERE analysis_version_id = ? AND document_type = ?
        """,
        (version["id"], document_type),
    )
    with fitz.open(path) as document:
        page_count = len(document)
        if page_count > 80:
            raise RuntimeError(f"{document_type.replace('_', ' ').title()} exceeds the 80-page limit.")
        native_pages = [
            document[page_number - 1].get_text("text").strip()
            for page_number in range(1, page_count + 1)
        ]

    worker_count = min(config.OCR_PAGE_CONCURRENCY, max(1, page_count))
    with ThreadPoolExecutor(
        max_workers=worker_count,
        thread_name_prefix="sumkora-ocr",
    ) as executor:
        futures = [
            executor.submit(
                _extract_analysis_page,
                path=path,
                page_number=page_number,
                native=native_pages[page_number - 1],
                force_vision=force_vision,
                image_resolution=version["image_resolution"],
                configured_ocr_model=version["ocr_model"],
            )
            for page_number in range(1, page_count + 1)
        ]
        completed_pages = 0
        for future in as_completed(futures):
            result = future.result()
            page_number = result["page_number"]
            text = result["text"]
            page_texts[page_number] = text
            page_confidences[page_number] = result["confidence"]
            execute(
                """
                INSERT INTO analysis_ocr_pages
                (analysis_version_id, document_type, page_number, provider,
                 model, prompt_version, text, normalized_text, confidence,
                 warnings, raw_response, timing_ms, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    version["id"],
                    document_type,
                    page_number,
                    result["provider"],
                    result["model"],
                    version["ocr_prompt_version"],
                    text,
                    re.sub(r"\s+", " ", text).strip(),
                    result["confidence"],
                    json_text(result["warnings"]),
                    json_text(result["raw"]) if result["raw"] else None,
                    result["duration"],
                    now_iso(),
                ),
            )
            completed_pages += 1
            logger.info(
                "Analysis %s OCR %s: %s/%s pages complete",
                version["id"],
                document_type,
                completed_pages,
                page_count,
            )
    return page_texts, page_confidences


def _ordered_page_transcript(
    page_texts: dict[int, str],
    *,
    document_label: str,
) -> str:
    return "\n\n".join(
        (
            f"--- {document_label}, PAGE {page_number} ---\n"
            f"{text.strip() or '[No readable text detected on this page]'}"
        )
        for page_number, text in sorted(page_texts.items())
    )


def _automatic_question_plan(
    version,
    question_pages: dict[int, str],
    scheme_pages: dict[int, str],
    answer_pages: dict[int, str],
) -> tuple[dict, list[dict], list[str]]:
    layout_detected = detect_documents(
        version["question_paper_path"],
        version["mark_scheme_path"],
        version["paper_title"],
    )
    ocr_detected = detect_document_texts(
        "\n".join(question_pages.values()),
        "\n".join(scheme_pages.values()),
        version["paper_title"],
    )
    def quality(candidate: dict) -> int:
        numbers = [
            int(re.sub(r"\D", "", item.get("label", "")) or 999)
            for item in candidate["questions"]
        ]
        if not numbers:
            return -1000
        missing = sum(
            1
            for number in range(min(numbers), max(numbers) + 1)
            if number not in numbers
        )
        starts_at_one = 5 if min(numbers) == 1 else 0
        return len(numbers) * 10 + starts_at_one - missing * 8

    detected = (
        layout_detected
        if quality(layout_detected) >= quality(ocr_detected)
        else ocr_detected
    )
    questions = detected["questions"]
    answer_page_by_label: dict[str, int] = {}
    for page_number, text in answer_pages.items():
        for item in _question_chunks(text):
            answer_page_by_label.setdefault(item["label"], page_number)
    page_count = max(len(answer_pages), 1)
    for index, item in enumerate(questions):
        item["answer_page"] = answer_page_by_label.get(
            item["label"],
            min(index + 1, page_count),
        )
    return detected["metadata"], questions, detected["warnings"]


def _run_legacy_self_service_analysis(version_id: int) -> dict:
    version = query_one(
        """
        SELECT pav.*, sp.student_id, sp.id AS student_paper_id,
               sp.title AS paper_title
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
        _update_version(version_id, "validation", 0)
        _update_version(version_id, "document_extraction", 1)
        _update_version(version_id, "ocr", 2)
        question_pages, _ = _extract_analysis_document(
            version,
            "question_paper",
            version["question_paper_path"],
        )
        scheme_pages, _ = _extract_analysis_document(
            version,
            "mark_scheme",
            version["mark_scheme_path"],
        )
        page_texts, page_confidences = _extract_analysis_document(
            version,
            "answer_script",
            version["answer_script_path"],
            force_vision=True,
        )
        page_count = len(page_texts)
        _update_version(version_id, "question_detection", 3)
        metadata, questions, detection_warnings = _automatic_question_plan(
            version,
            question_pages,
            scheme_pages,
            page_texts,
        )
        if not questions:
            raise RuntimeError("No questions could be detected from the uploaded documents.")
        execute(
            """
            UPDATE paper_analysis_versions
            SET detected_metadata = ?, confirmed_metadata = ?,
                question_plan = ?, warnings = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                json_text(metadata),
                json_text(metadata),
                json_text(questions),
                json_text(detection_warnings),
                now_iso(),
                version_id,
            ),
        )
        execute(
            """
            UPDATE student_papers
            SET title = ?, syllabus_code = ?, paper_number = ?, paper_year = ?,
                examination_session = ?, calculator_policy = ?,
                maximum_marks = ?, source_type = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                metadata.get("title") or version["paper_title"],
                metadata.get("syllabus_code") or "custom",
                metadata.get("paper_number") or "",
                metadata.get("paper_year"),
                metadata.get("examination_session") or "",
                metadata.get("calculator_policy") or "unknown",
                float(metadata.get("maximum_marks") or 0),
                metadata.get("source_type") or "custom",
                now_iso(),
                version["student_paper_id"],
            ),
        )
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
                (analysis_version_id, question_label, question_text, question_latex,
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
        from question_bank import link_analysis_results_to_bank

        link_analysis_results_to_bank(version_id)
        return {"status": "completed", "paper_id": version["student_paper_id"]}
    except Exception as exc:
        logger.exception("Paper analysis version %s failed", version_id)
        public_message = (
            "We could not complete this analysis. Try again; your files and "
            "previous results are safe."
        )
        execute(
            """
            UPDATE paper_analysis_versions
            SET status = 'failed', failure_message = ?, updated_at = ?,
                finished_at = ?
            WHERE id = ?
            """,
            (public_message, now_iso(), now_iso(), version_id),
        )
        execute(
            "UPDATE student_papers SET status = 'failed', updated_at = ? WHERE id = ?",
            (now_iso(), version["student_paper_id"]),
        )
        return {"status": "failed", "error": public_message}


def run_self_service_analysis(version_id: int) -> dict:
    """Run the active whole-document assessment pipeline.

    Historical completed versions remain untouched. Every new run uses the
    completed-work PDF as the source of questions and student evidence, with
    the mark scheme included only when the student supplies one.
    """
    version = query_one(
        """
        SELECT pav.*, sp.student_id, sp.id AS student_paper_id,
               sp.title AS paper_title
        FROM paper_analysis_versions pav
        JOIN student_papers sp ON sp.id = pav.paper_id
        WHERE pav.id = ?
        """,
        (version_id,),
    )
    if not version:
        return {"status": "failed", "error": "Version was not found."}
    try:
        if not version["answer_script_path"] or not os.path.isfile(
            version["answer_script_path"]
        ):
            raise RuntimeError("The completed-work document is missing.")
        scheme_path = version["mark_scheme_path"]
        if scheme_path and not os.path.isfile(scheme_path):
            raise RuntimeError("The mark-scheme document is missing.")

        mode = "detailed" if scheme_path else "estimate"
        _update_version(version_id, "validation", 0)
        _update_version(version_id, "document_extraction", 1)
        answer_pages, _ = _extract_analysis_document(
            version,
            "answer_script",
            version["answer_script_path"],
            force_vision=True,
        )
        scheme_pages = {}
        if scheme_path:
            scheme_pages, _ = _extract_analysis_document(
                version,
                "mark_scheme",
                scheme_path,
            )
        answer_transcript = _ordered_page_transcript(
            answer_pages,
            document_label="COMPLETED STUDENT WORK",
        )
        scheme_transcript = (
            _ordered_page_transcript(
                scheme_pages,
                document_label="OFFICIAL MARK SCHEME",
            )
            if scheme_pages
            else None
        )
        _update_version(version_id, "whole_document_reasoning", 2)
        assessment, provider_metadata = assess_documents(
            version["answer_script_path"],
            scheme_path,
            expected_maximum_marks=version["expected_maximum_marks"],
            completed_work_text=answer_transcript,
            mark_scheme_text=scheme_transcript,
        )
        _update_version(version_id, "result_validation", 3)

        questions = assessment["questions"]
        metadata = {
            "title": assessment.get("paper_title") or version["paper_title"],
            "syllabus_code": assessment.get("syllabus_code") or "Mathematics",
            "paper_number": assessment.get("paper_reference") or "",
            "paper_year": None,
            "examination_session": "",
            "calculator_policy": "unknown",
            "maximum_marks": assessment["total_max_marks"],
            "source_type": "student_upload",
        }
        warnings = list(assessment.get("warnings") or [])
        if mode == "estimate":
            warnings.insert(
                0,
                "Estimated assessment: no official mark scheme was provided.",
            )
        execute(
            """
            UPDATE paper_analysis_versions
            SET detected_metadata = ?, confirmed_metadata = ?,
                question_plan = ?, warnings = ?, assessment_mode = ?,
                assessment_summary = ?, provider_metadata = ?,
                grading_model = ?, diagnosis_model = ?,
                grading_prompt_version = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                json_text(metadata),
                json_text(metadata),
                json_text(questions),
                json_text(warnings),
                mode,
                json_text(assessment),
                json_text(provider_metadata),
                provider_metadata.get("model") or config.WHOLE_DOCUMENT_MODEL,
                provider_metadata.get("model") or config.WHOLE_DOCUMENT_MODEL,
                provider_metadata.get("prompt_version")
                or ASSESSMENT_PROMPT_VERSION,
                now_iso(),
                version_id,
            ),
        )
        execute(
            """
            UPDATE student_papers
            SET title = ?, syllabus_code = ?, paper_number = ?,
                maximum_marks = ?, source_type = ?, status = 'processing',
                updated_at = ?
            WHERE id = ?
            """,
            (
                metadata["title"],
                metadata["syllabus_code"],
                metadata["paper_number"],
                metadata["maximum_marks"],
                metadata["source_type"],
                now_iso(),
                version["student_paper_id"],
            ),
        )

        execute(
            "DELETE FROM analysis_question_results WHERE analysis_version_id = ?",
            (version_id,),
        )
        execute(
            "DELETE FROM analysis_skill_observations WHERE analysis_version_id = ?",
            (version_id,),
        )
        _update_version(version_id, "diagnosis", 4)
        for item in questions:
            mark = item.get("awarded_mark")
            maximum = item.get("maximum_marks")
            status = item["status"]
            confidence = float(item.get("confidence") or 0)
            pages = item.get("evidence_pages") or []
            lost_marks = (
                maximum is not None
                and mark is not None
                and float(mark) < float(maximum)
            )
            risk_flags = []
            if status in {"uncertain", "ungraded"}:
                risk_flags.append(f"assessment_{status}")
            if mode == "estimate":
                risk_flags.append("estimated_without_mark_scheme")
            paper_question_id = _match_question_bank_parent(assessment, item)
            result_id = execute(
                """
                INSERT INTO analysis_question_results
                (analysis_version_id, question_label, question_text,
                 question_latex, mark_scheme_text, structured_criteria,
                 maximum_marks, topic,
                 subtopic, skill, answer_page, response_text,
                 mapping_confidence, ai_mark, ai_confidence, ai_rationale,
                 ai_rationale_zh, cited_evidence, error_category, error_mechanism,
                 error_mechanism_zh,
                 deterministic_check, risk_flags, model, prompt_version,
                 assessment_status, awarded_mark, evidence_pages,
                 paper_question_id, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                        ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    version_id,
                    item["label"],
                    item.get("question_text") or "",
                    item.get("question_latex") or item.get("question_text") or "",
                    "Official mark scheme supplied as a complete document."
                    if scheme_path
                    else "No mark scheme supplied; this is an estimate.",
                    json_text(item.get("mark_breakdown") or []),
                    float(maximum or 0),
                    item.get("topic") or "Unclassified",
                    "",
                    item.get("skill") or "unclassified",
                    int(pages[0]) if pages else 1,
                    item.get("evidence_quote") or "",
                    confidence,
                    float(mark or 0),
                    confidence,
                    item.get("rationale") or "",
                    item.get("rationale_zh") or "",
                    item.get("evidence_quote") or "",
                    (
                        "uncertain evidence"
                        if status in {"uncertain", "ungraded"}
                        else "method or accuracy loss"
                        if lost_marks
                        else None
                    ),
                    (
                        item.get("improvement") or None
                        if lost_marks or status in {"uncertain", "ungraded"}
                        else None
                    ),
                    (
                        item.get("improvement_zh") or ""
                        if lost_marks or status in {"uncertain", "ungraded"}
                        else ""
                    ),
                    json_text(
                        {
                            "validated": True,
                            "whole_document": True,
                            "mode": mode,
                            "independent_audit": item.get("audit"),
                        }
                    ),
                    json_text(risk_flags),
                    provider_metadata.get("model") or config.WHOLE_DOCUMENT_MODEL,
                    provider_metadata.get("prompt_version")
                    or ASSESSMENT_PROMPT_VERSION,
                    status,
                    float(mark) if mark is not None else None,
                    json_text(pages),
                    paper_question_id,
                    now_iso(),
                ),
            )
            if (
                mark is not None
                and maximum is not None
                and float(maximum) > 0
                and status != "ungraded"
            ):
                evidence_weight = max(float(maximum), 1) * max(confidence, 0.1)
                if mode == "estimate":
                    evidence_weight *= 0.6
                execute(
                    """
                    INSERT INTO analysis_skill_observations
                    (student_id, paper_id, analysis_version_id,
                     question_result_id, observed_at, topic, subtopic, skill,
                     marks_earned, marks_available, success_fraction,
                     grading_confidence, extraction_confidence,
                     evidence_weight, error_category, error_mechanism,
                     is_current)
                    VALUES (?, ?, ?, ?, ?, ?, '', ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
                    """,
                    (
                        version["student_id"],
                        version["student_paper_id"],
                        version_id,
                        result_id,
                        now_iso(),
                        item.get("topic") or "Unclassified",
                        item.get("skill") or "unclassified",
                        float(mark),
                        float(maximum),
                        float(mark) / float(maximum),
                        confidence,
                        confidence,
                        evidence_weight,
                        (
                            "estimated assessment"
                            if mode == "estimate"
                            else None
                        ),
                        item.get("improvement") or None,
                    ),
                )

        execute(
            """
            UPDATE analysis_skill_observations
            SET is_current = 0
            WHERE paper_id = ? AND analysis_version_id != ?
            """,
            (version["student_paper_id"], version_id),
        )
        _update_version(version_id, "profile_update", 5)
        from assessment import rebuild_student_profile

        rebuild_student_profile(version["student_id"])
        _update_version(version_id, "report_generation", 6)
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
                assessment["estimated_score_min"],
                assessment["estimated_score"],
                assessment["estimated_score_max"],
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
    except Exception:
        logger.exception("Whole-document analysis version %s failed", version_id)
        public_message = (
            "We could not complete this analysis. No zero marks were recorded. "
            "Try again; your files and previous results are safe."
        )
        execute(
            """
            UPDATE paper_analysis_versions
            SET status = 'failed', failure_message = ?, updated_at = ?,
                finished_at = ?
            WHERE id = ?
            """,
            (public_message, now_iso(), now_iso(), version_id),
        )
        execute(
            "UPDATE student_papers SET status = 'failed', updated_at = ? WHERE id = ?",
            (now_iso(), version["student_paper_id"]),
        )
        return {"status": "failed", "error": public_message}


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
