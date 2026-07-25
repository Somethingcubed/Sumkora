import json
import re
from datetime import datetime, timezone
from pathlib import Path

import fitz

from assessment import file_sha256
from db import execute, query_all, query_one


PARSER_VERSION = "cambridge-0606-ms-v1"
QUESTION_LABEL = re.compile(r"^\d+(?:\([a-z]\)(?:\([ivx]+\))?)?$", re.I)
MARK_TOKEN = re.compile(r"\(?\b(M|A|B|SC)(\d)\b\)?", re.I)


def _now():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _component_from_name(path: Path) -> str:
    match = re.search(r"_([0-9]{2})(?:\s|\(|\.|_)", path.name)
    if not match:
        raise ValueError(f"Could not detect component from {path.name}")
    return match.group(1)


def _session_from_name(path: Path) -> tuple[str, int]:
    match = re.search(r"_([smw])(\d{2})_", path.name, re.I)
    if not match:
        return "unknown", 0
    session = {"s": "May/June", "w": "October/November", "m": "February/March"}[
        match.group(1).lower()
    ]
    return session, 2000 + int(match.group(2))


def _files_by_component(directory: Path):
    result = {}
    for path in directory.glob("0606_*.pdf"):
        if "_gt" in path.name:
            continue
        component = _component_from_name(path)
        record = result.setdefault(component, {})
        if "_qp_" in path.name:
            record["question_paper"] = path
        elif "_ms_" in path.name:
            record["mark_scheme"] = path
    thresholds = next(iter(directory.glob("0606_*_gt*.pdf")), None)
    return result, thresholds


def _question_sections(mark_scheme: Path):
    sections = []
    with fitz.open(mark_scheme) as doc:
        current = None
        for page_index, page in enumerate(doc):
            blocks = sorted(page.get_text("blocks"), key=lambda block: (block[1], block[0]))
            for block in blocks:
                x0, y0, _, _, text, *_ = block
                if y0 < 55 or y0 > 780:
                    continue
                cleaned = " ".join(text.split())
                if not cleaned or cleaned.startswith(("Question Answer Marks", "MARK SCHEME NOTES")):
                    continue
                first = cleaned.split()[0]
                if x0 < 78 and QUESTION_LABEL.fullmatch(first):
                    if current:
                        sections.append(current)
                    current = {
                        "label": first,
                        "page": page_index + 1,
                        "lines": [cleaned[len(first) :].strip()],
                    }
                elif current:
                    current["lines"].append(cleaned)
        if current:
            sections.append(current)
    deduped = {}
    for section in sections:
        label = section["label"]
        if label in deduped:
            deduped[label]["lines"].extend(section["lines"])
        else:
            deduped[label] = section
    return list(deduped.values())


def _marks_from_section(lines: list[str]):
    criteria = []
    for index, line in enumerate(lines):
        for match in MARK_TOKEN.finditer(line):
            mark_type = match.group(1).upper()
            if line.startswith("("):
                continue
            context = " ".join(lines[max(0, index - 1) : min(len(lines), index + 2)])
            criteria.append(
                {
                    "mark_type": mark_type,
                    "marks": int(match.group(2)),
                    "description": context[:1000],
                    "dependencies": ["previous"] if "dep" in context.lower() else [],
                    "follow_through": "FT" if " ft " in f" {context.lower()} " else "",
                    "raw": line,
                }
            )
    return criteria


def ingest_0606_directory(directory: str) -> list[dict]:
    root = Path(directory)
    grouped, threshold = _files_by_component(root)
    imported = []
    for component, files in sorted(grouped.items()):
        qp = files.get("question_paper")
        ms = files.get("mark_scheme")
        if not qp or not ms:
            continue
        session, year = _session_from_name(qp)
        calculator_policy = "non-calculator" if component.startswith("1") else "calculator"
        now = _now()
        existing = query_one(
            """
            SELECT id FROM paper_packs
            WHERE syllabus_code = '0606' AND year = ?
              AND examination_session = ? AND component = ?
            """,
            (year, session, component),
        )
        values = (
            "2025-2027",
            year,
            session,
            component,
            component[0],
            calculator_policy,
            str(qp),
            str(ms),
            str(threshold) if threshold else None,
            file_sha256(str(qp)),
            file_sha256(str(ms)),
            file_sha256(str(threshold)) if threshold else None,
            "Owner-supplied Cambridge files; private development use only.",
            "parsed_requires_review",
            PARSER_VERSION,
            0.45,
            json.dumps({"private": True, "copyrighted": True}),
            now,
        )
        if existing:
            execute(
                """
                UPDATE paper_packs
                SET syllabus_version = ?, year = ?, examination_session = ?,
                    component = ?, paper_number = ?, calculator_policy = ?,
                    question_paper_path = ?, mark_scheme_path = ?,
                    grade_threshold_path = ?, question_paper_hash = ?,
                    mark_scheme_hash = ?, threshold_hash = ?, provenance = ?,
                    ingestion_status = ?, parser_version = ?,
                    parsing_confidence = ?, raw_metadata = ?, updated_at = ?
                WHERE id = ?
                """,
                (*values, existing["id"]),
            )
            pack_id = existing["id"]
        else:
            pack_id = execute(
                """
                INSERT INTO paper_packs
                (syllabus_code, syllabus_version, year, examination_session,
                 component, paper_number, calculator_policy, maximum_marks,
                 question_paper_path, mark_scheme_path, grade_threshold_path,
                 question_paper_hash, mark_scheme_hash, threshold_hash,
                 provenance, ingestion_status, parser_version,
                 parsing_confidence, raw_metadata, created_at, updated_at)
                VALUES ('0606', ?, ?, ?, ?, ?, ?, 80, ?, ?, ?, ?, ?, ?, ?, ?,
                        ?, ?, ?, ?, ?)
                """,
                (*values, now),
            )

        execute(
            """
            DELETE FROM paper_questions
            WHERE paper_pack_id = ? AND parser_version = ?
            """,
            (pack_id, PARSER_VERSION),
        )
        sections = _question_sections(ms)
        for order, section in enumerate(sections):
            criteria = _marks_from_section(section["lines"])
            maximum = sum(item["marks"] for item in criteria)
            existing_question = query_one(
                """
                SELECT id FROM paper_questions
                WHERE paper_pack_id = ? AND question_number = ? AND subpart = ''
                """,
                (pack_id, section["label"]),
            )
            question_values = (
                json.dumps([section["page"]]),
                "\n".join(section["lines"][:20]),
                min(maximum, 20),
                calculator_policy,
                0.4,
                "\n".join(section["lines"]),
                PARSER_VERSION,
                order,
            )
            if existing_question:
                execute(
                    """
                    UPDATE paper_questions
                    SET source_pages = ?, prompt_text = ?, maximum_marks = ?,
                        calculator_policy = ?, parsing_confidence = ?,
                        raw_source_text = ?, parser_version = ?, order_index = ?
                    WHERE id = ?
                    """,
                    (*question_values, existing_question["id"]),
                )
                paper_question_id = existing_question["id"]
                execute(
                    "UPDATE marking_criteria SET is_active = 0 WHERE paper_question_id = ?",
                    (paper_question_id,),
                )
            else:
                paper_question_id = execute(
                    """
                    INSERT INTO paper_questions
                    (paper_pack_id, question_number, source_pages, prompt_text,
                     maximum_marks, calculator_policy, parsing_confidence,
                     raw_source_text, parser_version, order_index)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (pack_id, section["label"], *question_values),
                )
            for criterion_index, criterion in enumerate(criteria):
                execute(
                    """
                    INSERT INTO marking_criteria
                    (paper_question_id, criterion_code, mark_type, marks,
                     description, dependencies, follow_through_rules,
                     raw_mark_scheme_text, source_page, source_confidence,
                     order_index, version)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0.45, ?, 1)
                    """,
                    (
                        paper_question_id,
                        f"{section['label']}-{criterion_index + 1}",
                        criterion["mark_type"],
                        criterion["marks"],
                        criterion["description"],
                        json.dumps(criterion["dependencies"]),
                        criterion["follow_through"],
                        criterion["raw"],
                        section["page"],
                        criterion_index,
                    ),
                )
        imported.append(
            {
                "paper_pack_id": pack_id,
                "component": component,
                "questions": len(sections),
                "status": "parsed_requires_review",
            }
        )
    return imported


def paper_pack_inventory():
    return query_all(
        """
        SELECT pp.*,
               COUNT(DISTINCT pq.id) AS question_count,
               COUNT(DISTINCT mc.id) AS criterion_count
        FROM paper_packs pp
        LEFT JOIN paper_questions pq ON pq.paper_pack_id = pp.id
        LEFT JOIN marking_criteria mc
          ON mc.paper_question_id = pq.id AND mc.is_active = 1
        GROUP BY pp.id
        ORDER BY pp.year DESC, pp.examination_session, pp.component
        """
    )
