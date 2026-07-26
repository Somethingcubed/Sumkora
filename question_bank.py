"""Import owner-supplied Cambridge-style paper and mark-scheme archives."""

from __future__ import annotations

import hashlib
import json
import re
import uuid
import zipfile
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path

import fitz

import config
from db import execute, query_all, query_one


IMPORTER_VERSION = "sumkora-question-bank-v2"
FILE_PATTERN = re.compile(
    r"(?P<syllabus>\d{4})_(?P<session>[smw]\d{2})_"
    r"(?P<kind>qp|ms)_(?P<component>\d{2})(?:[^/]*)\.pdf$",
    re.I,
)
QUESTION_START = re.compile(r"^\s*(\d{1,2})(?=\s|\(|$)")
MARK_TOKEN = re.compile(r"\b(?:M|A|B|SC)(\d)\b", re.I)

TOPIC_RULES = [
    ("Calculus", ["differentiate", "derivative", "stationary", "integrate", "integration", "gradient function"]),
    ("Trigonometry", ["sin ", "cos ", "tan ", "trigonometric", "radian", "bearing"]),
    ("Logarithmic and exponential functions", ["logarithm", "log ", "ln ", "exponential", "e^"]),
    ("Quadratics and functions", ["quadratic", "discriminant", "function", "inverse function", "composite"]),
    ("Equations, inequalities and graphs", ["inequality", "inequalities", "sketch", "graph", "intersection"]),
    ("Coordinate geometry", ["coordinate", "straight line", "midpoint", "perpendicular", "parallel"]),
    ("Polynomials", ["polynomial", "remainder theorem", "factor theorem"]),
    ("Sequences and series", ["sequence", "progression", "arithmetic series", "geometric series", "sigma"]),
    ("Vectors", ["vector", "position vector", "magnitude"]),
    ("Circular measure", ["arc length", "sector", "radian"]),
    ("Binomial theorem", ["binomial", "coefficient of"]),
    ("Permutations and combinations", ["permutation", "combination", "arrange", "selection"]),
]

SKILL_RULES = [
    ("differentiation", ["differentiate", "derivative", "stationary"]),
    ("integration", ["integrate", "integration", "area under"]),
    ("solving inequalities", ["inequality", "inequalities"]),
    ("graph sketching", ["sketch", "graph"]),
    ("trigonometric equations", ["trigonometric equation", "solve", "sin ", "cos ", "tan "]),
    ("functions", ["function", "inverse", "composite"]),
    ("polynomial methods", ["polynomial", "remainder theorem", "factor theorem"]),
    ("sequences and series", ["sequence", "progression", "series"]),
    ("coordinate geometry", ["coordinate", "straight line", "midpoint"]),
    ("vectors", ["vector"]),
]


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _session_details(token: str) -> tuple[str, int]:
    code = token[0].lower()
    year = 2000 + int(token[1:])
    name = {
        "m": "February/March",
        "s": "May/June",
        "w": "October/November",
    }[code]
    return name, year


def _hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_extract_pdfs(payload: bytes, import_root: Path) -> list[Path]:
    if len(payload) > 250 * 1024 * 1024:
        raise ValueError("The ZIP is larger than the 250 MB import limit.")
    paths = []
    total_size = 0
    with zipfile.ZipFile(BytesIO(payload)) as archive:
        members = [item for item in archive.infolist() if not item.is_dir()]
        if len(members) > 500:
            raise ValueError("The ZIP contains too many files.")
        for member in members:
            if not member.filename.lower().endswith(".pdf"):
                continue
            total_size += member.file_size
            if total_size > 750 * 1024 * 1024:
                raise ValueError("The extracted PDFs exceed the 750 MB import limit.")
            base = Path(member.filename).name
            if not FILE_PATTERN.search(base):
                continue
            target = import_root / base
            target.write_bytes(archive.read(member))
            paths.append(target)
    return paths


def _pair_files(paths: list[Path]) -> tuple[list[dict], list[str]]:
    groups: dict[tuple[str, str, str], dict] = {}
    warnings = []
    for path in paths:
        match = FILE_PATTERN.search(path.name)
        if not match:
            warnings.append(f"Skipped unrecognized filename: {path.name}")
            continue
        values = match.groupdict()
        key = (
            values["syllabus"],
            values["session"].lower(),
            values["component"],
        )
        record = groups.setdefault(
            key,
            {
                "syllabus": values["syllabus"],
                "session_token": values["session"].lower(),
                "component": values["component"],
            },
        )
        record[values["kind"].lower()] = path
    pairs = []
    for key, record in sorted(groups.items()):
        if not record.get("qp") or not record.get("ms"):
            missing = "mark scheme" if not record.get("ms") else "question paper"
            warnings.append(f"{'_'.join(key)} is missing its {missing}.")
            continue
        pairs.append(record)
    return pairs, warnings


def _question_labels(question_paper: Path) -> list[str]:
    """Read top-level labels from the question paper, excluding cover pages."""
    found: dict[str, tuple[int, float]] = {}
    with fitz.open(question_paper) as document:
        for page_index, page in enumerate(document):
            if page_index < 2:
                continue
            for block in sorted(
                page.get_text("blocks"), key=lambda value: (value[1], value[0])
            ):
                x0, y0, _, _, text, *_ = block
                if x0 > 57 or y0 < 45 or y0 > page.rect.height - 90:
                    continue
                match = QUESTION_START.match(" ".join(text.split()))
                if not match:
                    continue
                label = match.group(1)
                number = int(label)
                if 1 <= number <= 40 and label not in found:
                    found[label] = (page_index, y0)
    ordered = sorted(found, key=lambda value: found[value])
    sequential = []
    expected = 1
    for label in ordered:
        number = int(label)
        if number == expected:
            sequential.append(label)
            expected += 1
    return sequential


def _find_starts(
    path: Path,
    labels: list[str],
    *,
    question_paper: bool = False,
) -> dict[str, tuple[int, float]]:
    expected = set(labels)
    starts = {}
    with fitz.open(path) as document:
        scheme_start_page = 0
        if not question_paper:
            for page_index, page in enumerate(document):
                if "Question Answer Marks Guidance" in " ".join(
                    page.get_text("text").split()
                ):
                    scheme_start_page = page_index
                    break
        for page_index, page in enumerate(document):
            if question_paper and page_index < 2:
                continue
            if not question_paper and page_index < scheme_start_page:
                continue
            blocks = sorted(
                page.get_text("blocks"), key=lambda value: (value[1], value[0])
            )
            for block in blocks:
                x0, y0, _, _, text, *_ = block
                maximum_x = 57 if question_paper else 150
                bottom_margin = 90 if question_paper else 35
                if x0 > maximum_x or y0 < 45 or y0 > page.rect.height - bottom_margin:
                    continue
                cleaned = " ".join(text.split())
                match = QUESTION_START.match(cleaned)
                if not match:
                    continue
                label = match.group(1)
                if label in expected and label not in starts:
                    starts[label] = (page_index, max(y0 - 8, 0))
    return starts


def _range_for_label(
    label: str,
    labels: list[str],
    starts: dict[str, tuple[int, float]],
    document: fitz.Document,
) -> list[tuple[int, fitz.Rect]]:
    if label not in starts:
        return []
    start_page, start_y = starts[label]
    ordered = [value for value in labels if value in starts]
    index = ordered.index(label)
    next_start = starts[ordered[index + 1]] if index + 1 < len(ordered) else None
    end_page = next_start[0] if next_start else len(document) - 1
    clips = []
    for page_index in range(start_page, end_page + 1):
        if (
            next_start
            and page_index == next_start[0]
            and page_index > start_page
            and next_start[1] < 120
        ):
            break
        page = document[page_index]
        top = start_y if page_index == start_page else 35
        bottom = page.rect.height - 35
        if next_start and page_index == next_start[0]:
            bottom = max(next_start[1] - 5, top + 20)
        if bottom > top + 15:
            clips.append(
                (
                    page_index,
                    fitz.Rect(28, top, page.rect.width - 28, bottom),
                )
            )
        if next_start and page_index == next_start[0]:
            break
    return clips


def _extract_asset(
    source_path: Path,
    clips: list[tuple[int, fitz.Rect]],
    target_path: Path,
) -> str | None:
    if not clips:
        return None
    output = fitz.open()
    with fitz.open(source_path) as source:
        for page_index, clip in clips:
            page = output.new_page(width=clip.width, height=clip.height)
            page.show_pdf_page(page.rect, source, page_index, clip=clip)
    if not len(output):
        output.close()
        return None
    output.save(target_path, garbage=3, deflate=True)
    output.close()
    return str(target_path)


def _clip_text(path: Path, clips: list[tuple[int, fitz.Rect]]) -> str:
    parts = []
    with fitz.open(path) as document:
        for page_index, clip in clips:
            parts.append(document[page_index].get_text("text", clip=clip))
    return "\n".join(part.strip() for part in parts if part.strip())


def _classify(text: str) -> tuple[str, list[str], float]:
    lowered = f" {' '.join(text.lower().split())} "
    if "differentiate" in lowered or "integration" in lowered:
        skills = ["differentiation"]
        if " d" in lowered or "area" in lowered:
            skills.append("integration")
        return "Calculus", skills, 0.9
    if "velocity" in lowered or "acceleration" in lowered:
        return "Calculus", ["kinematics"], 0.86
    if "amplitude" in lowered or "period" in lowered:
        return "Trigonometry", ["trigonometric graphs"], 0.9
    if "simultaneous equation" in lowered:
        return "Equations, inequalities and graphs", ["simultaneous equations"], 0.9
    if "solve the equation" in lowered:
        if " log" in lowered or " e " in lowered:
            return (
                "Logarithmic and exponential functions",
                ["solving logarithmic and exponential equations"],
                0.86,
            )
        return "Equations, inequalities and graphs", ["solving equations"], 0.78
    if "line" in lowered and "curve" in lowered and "distinct point" in lowered:
        return "Quadratics and functions", ["discriminant conditions"], 0.86
    if "normal to this curve" in lowered and "area" in lowered:
        return "Calculus", ["differentiation", "integration"], 0.9
    topic = "Unclassified"
    topic_score = 0
    for candidate, terms in TOPIC_RULES:
        score = sum(lowered.count(term) for term in terms)
        if score > topic_score:
            topic = candidate
            topic_score = score
    skills = []
    for skill, terms in SKILL_RULES:
        if any(term in lowered for term in terms):
            skills.append(skill)
    if not skills and topic != "Unclassified":
        skills = [topic.lower()]
    confidence = 0.82 if topic_score >= 2 else 0.68 if topic_score == 1 else 0.25
    return topic, skills, confidence


def _maximum_marks(question_text: str, answer_text: str) -> int:
    bracketed = [
        int(value)
        for value in re.findall(r"\[\s*(\d{1,2})\s*\]", question_text)
        if 0 < int(value) <= 20
    ]
    if bracketed:
        return min(sum(bracketed), 30)
    marks = [int(value) for value in MARK_TOKEN.findall(answer_text)]
    return min(sum(marks), 30) if marks else 0


def _demand(maximum_marks: int, question_text: str) -> str:
    lowered = question_text.lower()
    if maximum_marks >= 8 or any(
        term in lowered
        for term in ("hence", "prove that", "show that", "exact value")
    ):
        return "challenging"
    return "standard"


def _upsert_pack(record: dict, asset_root: Path) -> dict:
    syllabus = record["syllabus"]
    session_name, year = _session_details(record["session_token"])
    component = record["component"]
    calculator = "non-calculator" if component.startswith("1") else "calculator"
    now = _now()
    existing = query_one(
        """
        SELECT id FROM paper_packs
        WHERE syllabus_code = ? AND year = ?
          AND examination_session = ? AND component = ?
        """,
        (syllabus, year, session_name, component),
    )
    raw_metadata = json.dumps(
        {
            "session_token": record["session_token"],
            "question_filename": record["qp"].name,
            "mark_scheme_filename": record["ms"].name,
            "private": True,
        }
    )
    if existing:
        pack_id = existing["id"]
        execute(
            """
            UPDATE paper_packs
            SET question_paper_path = ?, mark_scheme_path = ?,
                question_paper_hash = ?, mark_scheme_hash = ?,
                calculator_policy = ?, ingestion_status = 'processing',
                parser_version = ?, parsing_confidence = 0,
                raw_metadata = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                str(record["qp"]),
                str(record["ms"]),
                _hash(record["qp"]),
                _hash(record["ms"]),
                calculator,
                IMPORTER_VERSION,
                raw_metadata,
                now,
                pack_id,
            ),
        )
    else:
        pack_id = execute(
            """
            INSERT INTO paper_packs
            (syllabus_code, syllabus_version, year, examination_session,
             component, paper_number, calculator_policy, maximum_marks,
             question_paper_path, mark_scheme_path, question_paper_hash,
             mark_scheme_hash, provenance, ingestion_status, parser_version,
             parsing_confidence, raw_metadata, created_at, updated_at)
            VALUES (?, '2025-2027', ?, ?, ?, ?, ?, 80, ?, ?, ?, ?,
                    'Owner-supplied authorized past papers', 'processing',
                    ?, 0, ?, ?, ?)
            """,
            (
                syllabus,
                year,
                session_name,
                component,
                component[0],
                calculator,
                str(record["qp"]),
                str(record["ms"]),
                _hash(record["qp"]),
                _hash(record["ms"]),
                IMPORTER_VERSION,
                raw_metadata,
                now,
                now,
            ),
        )

    labels = _question_labels(record["qp"])
    qp_starts = _find_starts(record["qp"], labels, question_paper=True)
    ms_starts = _find_starts(record["ms"], labels)
    ready_count = 0
    imported_count = 0
    with fitz.open(record["qp"]) as qp_document, fitz.open(record["ms"]) as ms_document:
        for order, label in enumerate(labels):
            qp_clips = _range_for_label(label, labels, qp_starts, qp_document)
            ms_clips = _range_for_label(label, labels, ms_starts, ms_document)
            question_path = asset_root / f"{syllabus}_{record['session_token']}_{component}_q{label}.pdf"
            answer_path = asset_root / f"{syllabus}_{record['session_token']}_{component}_q{label}_answers.pdf"
            question_asset = _extract_asset(record["qp"], qp_clips, question_path)
            answer_asset = _extract_asset(record["ms"], ms_clips, answer_path)
            prompt_text = _clip_text(record["qp"], qp_clips)
            answer_text = _clip_text(record["ms"], ms_clips)
            topic, skills, classification_confidence = _classify(prompt_text)
            maximum = _maximum_marks(prompt_text, answer_text)
            extraction_confidence = (
                0.95
                if question_asset and answer_asset and prompt_text and answer_text
                else 0.65
                if question_asset and prompt_text
                else 0.25
            )
            review_status = (
                "ready"
                if extraction_confidence >= 0.9
                and maximum > 0
                and topic != "Unclassified"
                else "needs_review"
            )
            if review_status == "ready":
                ready_count += 1
            source_key = (
                f"{syllabus}_{record['session_token']}_{component}_q{label}"
            )
            values = (
                json.dumps(sorted({page + 1 for page, _ in qp_clips})),
                prompt_text,
                maximum,
                topic,
                json.dumps(skills),
                calculator,
                _demand(maximum, prompt_text),
                extraction_confidence,
                answer_text,
                IMPORTER_VERSION,
                order,
                source_key,
                question_asset,
                answer_asset,
                answer_text,
                source_key,
                review_status,
                classification_confidence,
            )
            existing_question = query_one(
                """
                SELECT id FROM paper_questions
                WHERE paper_pack_id = ? AND question_number = ? AND subpart = ''
                """,
                (pack_id, label),
            )
            if existing_question:
                question_id = existing_question["id"]
                execute(
                    """
                    UPDATE paper_questions
                    SET source_pages = ?, prompt_text = ?, maximum_marks = ?,
                        topic = ?, skills = ?, calculator_policy = ?,
                        question_demand = ?, parsing_confidence = ?,
                        raw_source_text = ?, parser_version = ?, order_index = ?,
                        source_key = ?, question_asset_path = ?,
                        answer_asset_path = ?, answer_text = ?,
                        dependency_group = ?, review_status = ?,
                        classification_confidence = ?
                    WHERE id = ?
                    """,
                    (*values, question_id),
                )
                execute(
                    "UPDATE marking_criteria SET is_active = 0 WHERE paper_question_id = ?",
                    (question_id,),
                )
            else:
                question_id = execute(
                    """
                    INSERT INTO paper_questions
                    (paper_pack_id, question_number, subpart, source_pages,
                     prompt_text, maximum_marks, topic, skills,
                     calculator_policy, question_demand, parsing_confidence,
                     raw_source_text, parser_version, order_index, source_key,
                     question_asset_path, answer_asset_path, answer_text,
                     dependency_group, review_status,
                     classification_confidence)
                    VALUES (?, ?, '', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                            ?, ?, ?, ?, ?)
                    """,
                    (pack_id, label, *values),
                )
            criterion_matches = list(MARK_TOKEN.finditer(answer_text))
            for criterion_index, match in enumerate(criterion_matches, start=1):
                mark_type = match.group(0)[0].upper()
                marks = int(match.group(1))
                start = max(match.start() - 180, 0)
                end = min(match.end() + 320, len(answer_text))
                execute(
                    """
                    INSERT INTO marking_criteria
                    (paper_question_id, criterion_code, mark_type, marks,
                     description, raw_mark_scheme_text, source_confidence,
                     order_index, version, is_active)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, 1)
                    """,
                    (
                        question_id,
                        f"{source_key}-{criterion_index}",
                        mark_type,
                        marks,
                        answer_text[start:end],
                        answer_text,
                        extraction_confidence,
                        criterion_index,
                    ),
                )
            imported_count += 1
    confidence = ready_count / imported_count if imported_count else 0
    status = "ready" if ready_count == imported_count and imported_count else "needs_review"
    execute(
        """
        UPDATE paper_packs
        SET ingestion_status = ?, parsing_confidence = ?, updated_at = ?
        WHERE id = ?
        """,
        (status, confidence, now, pack_id),
    )
    return {
        "paper_pack_id": pack_id,
        "source": f"{syllabus} {record['session_token']} {component}",
        "questions": imported_count,
        "ready": ready_count,
        "status": status,
    }


def ingest_question_bank_zip(payload: bytes, filename: str = "question-bank.zip") -> dict:
    if not zipfile.is_zipfile(BytesIO(payload)):
        raise ValueError("Upload a valid ZIP file containing PDF papers and mark schemes.")
    import_id = uuid.uuid4().hex[:12]
    import_root = Path(config.UPLOAD_DIR).resolve() / "question_bank" / import_id
    asset_root = import_root / "assets"
    import_root.mkdir(parents=True, exist_ok=True)
    asset_root.mkdir(parents=True, exist_ok=True)
    paths = _safe_extract_pdfs(payload, import_root)
    pairs, warnings = _pair_files(paths)
    results = []
    for record in pairs:
        results.append(_upsert_pack(record, asset_root))
    linked = link_analysis_results_to_bank()
    return {
        "filename": Path(filename).name,
        "import_id": import_id,
        "pdf_count": len(paths),
        "pair_count": len(pairs),
        "papers": results,
        "linked_analysis_questions": linked,
        "warnings": warnings,
    }


def _paper_identity(text: str) -> tuple[str, int, str, str] | None:
    filename_match = re.search(
        r"(\d{4})_([smw])(\d{2})(?:_(?:qp|ms))?_(\d{2})",
        text,
        re.I,
    )
    if filename_match:
        syllabus, token, year, component = filename_match.groups()
        session_name, full_year = _session_details(f"{token}{year}")
        return syllabus, full_year, session_name, component
    reference_match = re.search(
        r"(\d{4})/(\d{2})/(F/M|M/J|O/N)/(\d{2})",
        text,
        re.I,
    )
    if reference_match:
        syllabus, component, session, year = reference_match.groups()
        session_name = {
            "F/M": "February/March",
            "M/J": "May/June",
            "O/N": "October/November",
        }[session.upper()]
        return syllabus, 2000 + int(year), session_name, component
    return None


def link_analysis_results_to_bank(version_id: int | None = None) -> int:
    sql = """
        SELECT aqr.id, aqr.question_label, aqr.awarded_mark,
               aqr.maximum_marks, pav.assessment_summary,
               sp.id AS paper_id, sp.title, sp.paper_number
        FROM analysis_question_results aqr
        JOIN paper_analysis_versions pav ON pav.id = aqr.analysis_version_id
        JOIN student_papers sp ON sp.id = pav.paper_id
        WHERE aqr.paper_question_id IS NULL
    """
    params = ()
    if version_id is not None:
        sql += " AND pav.id = ?"
        params = (version_id,)
    linked = 0
    for row in query_all(sql, params):
        summary = {}
        try:
            summary = json.loads(row["assessment_summary"] or "{}")
        except (TypeError, ValueError, json.JSONDecodeError):
            pass
        haystack = " ".join(
            [
                row["title"] or "",
                row["paper_number"] or "",
                str(summary.get("paper_reference") or ""),
                str(summary.get("paper_title") or ""),
            ]
        )
        identity = _paper_identity(haystack)
        label_match = re.search(r"(\d{1,2})", row["question_label"] or "")
        if not label_match:
            continue
        practice_item = query_one(
            """
            SELECT psi.paper_question_id, psi.mistake_book_entry_id
            FROM practice_sets ps
            JOIN practice_set_items psi ON psi.practice_set_id = ps.id
            WHERE ps.analysis_paper_id = ? AND psi.order_index = ?
            """,
            (row["paper_id"], int(label_match.group(1))),
        )
        if practice_item:
            question = {"id": practice_item["paper_question_id"]}
            if practice_item["mistake_book_entry_id"]:
                mark = float(row["awarded_mark"] or 0)
                maximum = float(row["maximum_marks"] or 0)
                new_status = (
                    "mastered"
                    if maximum > 0 and mark >= maximum - 0.001
                    else "improving"
                    if mark > 0
                    else "not_retried"
                )
                execute(
                    """
                    UPDATE mistake_book_entries
                    SET status = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        new_status,
                        _now(),
                        practice_item["mistake_book_entry_id"],
                    ),
                )
        else:
            if not identity:
                continue
            syllabus, year, session, component = identity
            question = query_one(
                """
                SELECT pq.id
                FROM paper_questions pq
                JOIN paper_packs pp ON pp.id = pq.paper_pack_id
                WHERE pp.syllabus_code = ? AND pp.year = ?
                  AND pp.examination_session = ? AND pp.component = ?
                  AND pq.question_number = ?
                """,
                (syllabus, year, session, component, label_match.group(1)),
            )
        if not question:
            continue
        execute(
            "UPDATE analysis_question_results SET paper_question_id = ? WHERE id = ?",
            (question["id"], row["id"]),
        )
        execute(
            """
            UPDATE mistake_book_entries
            SET paper_question_id = ?, updated_at = ?
            WHERE analysis_question_result_id = ?
            """,
            (question["id"], _now(), row["id"]),
        )
        linked += 1
    return linked


def review_questions(limit: int = 250) -> list[dict]:
    return [
        dict(row)
        for row in query_all(
            """
            SELECT pq.*, pp.year, pp.examination_session, pp.component,
                   pp.syllabus_code
            FROM paper_questions pq
            JOIN paper_packs pp ON pp.id = pq.paper_pack_id
            ORDER BY
              CASE pq.review_status WHEN 'needs_review' THEN 0 ELSE 1 END,
              pp.year DESC, pp.component, pq.order_index
            LIMIT ?
            """,
            (limit,),
        )
    ]


def update_question_review(
    question_id: int,
    *,
    topic: str,
    skills: str,
    difficulty: str,
    review_status: str,
) -> bool:
    row = query_one("SELECT id FROM paper_questions WHERE id = ?", (question_id,))
    if not row:
        return False
    status = review_status if review_status in {"ready", "needs_review"} else "needs_review"
    demand = difficulty if difficulty in {"standard", "challenging"} else "standard"
    skill_values = [value.strip() for value in skills.split(",") if value.strip()]
    execute(
        """
        UPDATE paper_questions
        SET topic = ?, skills = ?, question_demand = ?,
            review_status = ?, classification_confidence = 1
        WHERE id = ?
        """,
        (topic.strip() or "Unclassified", json.dumps(skill_values), demand, status, question_id),
    )
    return True


def paper_bank_rows() -> list[dict]:
    return [
        dict(row)
        for row in query_all(
            """
            SELECT pp.*,
                   COUNT(pq.id) AS question_count,
                   SUM(CASE WHEN pq.review_status = 'ready' THEN 1 ELSE 0 END)
                     AS ready_count
            FROM paper_packs pp
            LEFT JOIN paper_questions pq ON pq.paper_pack_id = pp.id
            GROUP BY pp.id
            ORDER BY pp.year DESC, pp.examination_session, pp.component
            """
        )
    ]
