"""Student progress, mistake-book, and targeted-practice services."""

from __future__ import annotations

import json
import math
import os
import random
import re
import textwrap
from threading import BoundedSemaphore, Lock, Thread
from io import BytesIO
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

import fitz

from db import execute, query_all, query_one
from curricula import profile_from_user
from i18n import topic_label
from practice_generator import generate_validated_practice_questions
from taxonomy import canonical_topic

import config


_MISTAKE_RECOVERY_SEMAPHORE = BoundedSemaphore(
    config.MISTAKE_RECOVERY_CONCURRENCY
)
_MISTAKE_PDF_LOCK = Lock()


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _json(value, fallback):
    try:
        return json.loads(value or "")
    except (TypeError, ValueError, json.JSONDecodeError):
        return fallback


def _display_skill(value: str) -> str:
    return (value or "Unclassified").replace("_", " ").strip()


def _is_unclassified(value: str | None) -> bool:
    return (value or "").strip().lower().replace("_", " ") in {
        "",
        "unclassified",
        "unknown",
        "uncategorized",
        "uncategorised",
    }


def _student_curriculum(student_id: int) -> dict:
    return profile_from_user(
        query_one("SELECT * FROM users WHERE id = ?", (student_id,))
    )


def skill_url(skill: str) -> str:
    return f"/student/skills/detail?skill={quote(skill or '', safe='')}"


def skill_detail(student_id: int, skill: str = "", topic: str = "") -> dict | None:
    curriculum = _student_curriculum(student_id)
    state = None
    if topic:
        from assessment import student_skill_profile

        state = next(
            (
                item
                for item in student_skill_profile(student_id)["topic_states"]
                if item["topic"].lower() == topic.lower()
            ),
            None,
        )
    else:
        state = query_one(
            """
            SELECT * FROM student_skill_states
            WHERE student_id = ? AND lower(skill) = lower(?)
            """,
            (student_id, skill),
        )
    observations = query_all(
        """
        SELECT aso.*, sp.title AS paper_title, sp.id AS source_id,
               sp.updated_at AS paper_date, pav.assessment_mode,
               aqr.question_label, aqr.question_text, aqr.question_latex,
               aqr.ai_rationale,
               aqr.ai_rationale_zh, aqr.assessment_status,
               aqr.paper_question_id
        FROM analysis_skill_observations aso
        JOIN student_papers sp ON sp.id = aso.paper_id
        JOIN paper_analysis_versions pav ON pav.id = aso.analysis_version_id
        JOIN analysis_question_results aqr ON aqr.id = aso.question_result_id
        WHERE aso.student_id = ? AND aso.is_current = 1
          AND sp.curriculum_id = ? AND sp.curriculum_level = ?
          AND (? != '' OR lower(aso.skill) = lower(?))
        ORDER BY aso.observed_at, aso.id
        """,
        (student_id, curriculum["id"], curriculum["level"], topic, skill),
    )
    legacy = query_all(
        """
        SELECT so.*, a.title AS paper_title, s.id AS source_id,
               s.uploaded_at AS paper_date, 'detailed' AS assessment_mode,
               q.label AS question_label, q.question_text,
               '' AS question_latex,
               gd.ai_notes AS ai_rationale, '' AS ai_rationale_zh,
               'graded' AS assessment_status, NULL AS paper_question_id
        FROM skill_observations so
        JOIN submissions s ON s.id = so.submission_id
        JOIN assignments a ON a.id = s.assignment_id
        LEFT JOIN questions q ON q.id = so.question_id
        LEFT JOIN grade_drafts gd
          ON gd.submission_id = s.id AND gd.question_id = q.id
        WHERE so.student_id = ?
          AND ? = 'cambridge-igcse-additional-mathematics-0606'
          AND (? != '' OR lower(so.skill) = lower(?))
        ORDER BY so.observed_at, so.id
        """,
        (student_id, curriculum["id"], topic, skill),
    )
    rows = [dict(row) for row in observations] + [dict(row) for row in legacy]
    if topic:
        rows = [
            row
            for row in rows
            if canonical_topic(row.get("topic", ""), row.get("skill", "")).lower()
            == topic.lower()
        ]
    if not state and not rows:
        return None

    papers: dict[tuple[str, int], dict] = {}
    for row in sorted(rows, key=lambda item: item["observed_at"]):
        source_type = "paper" if "paper_id" in row.keys() else "submission"
        key = (source_type, int(row["source_id"]))
        record = papers.setdefault(
            key,
            {
                "source_type": source_type,
                "source_id": row["source_id"],
                "title": row["paper_title"],
                "date": (row["paper_date"] or row["observed_at"])[:10],
                "assessment_mode": row["assessment_mode"],
                "earned": 0.0,
                "available": 0.0,
                "correct": 0,
                "partial": 0,
                "incorrect": 0,
                "questions": [],
                "confidence_total": 0.0,
                "confidence_count": 0,
            },
        )
        earned = float(row["marks_earned"] or 0)
        available = float(row["marks_available"] or 0)
        record["earned"] += earned
        record["available"] += available
        if available > 0 and earned >= available - 0.001:
            outcome = "correct"
        elif earned <= 0:
            outcome = "incorrect"
        else:
            outcome = "partial"
        record[outcome] += 1
        confidence = min(
            float(row["grading_confidence"] or 0),
            float(row["extraction_confidence"] or 0),
        )
        record["confidence_total"] += confidence
        record["confidence_count"] += 1
        record["questions"].append(
            {
                "label": row["question_label"],
                "question_text": row["question_latex"] or row["question_text"],
                "earned": earned,
                "available": available,
                "outcome": outcome,
                "rationale": row["ai_rationale"],
                "rationale_zh": row["ai_rationale_zh"],
                "paper_question_id": row["paper_question_id"],
            }
        )

    trend = []
    for index, record in enumerate(papers.values()):
        record["earned"] = round(record["earned"], 2)
        record["available"] = round(record["available"], 2)
        record["percentage"] = (
            round(100 * record["earned"] / record["available"], 1)
            if record["available"]
            else 0
        )
        record["confidence"] = round(
            record["confidence_total"] / max(record["confidence_count"], 1), 2
        )
        record["chart_x"] = index
        trend.append(record)

    trend.sort(key=lambda item: (item["date"], item["source_id"]))
    for index, item in enumerate(trend):
        item["chart_x"] = index
    return {
        "skill": topic or (state["skill"] if state else skill),
        "display_skill": topic or _display_skill(state["skill"] if state else skill),
        "topic": topic or (state["topic"] if state else (rows[-1]["topic"] if rows else "")),
        "state": dict(state) if state else None,
        "papers": trend,
        "paper_count": len(trend),
        "is_topic": bool(topic),
    }


def sync_mistake_book(student_id: int) -> int:
    """Materialize current lost-mark results without duplicating entries."""
    curriculum = _student_curriculum(student_id)
    rows = query_all(
        """
        SELECT aqr.id, aqr.paper_question_id,
               COALESCE(
                 (SELECT corrected_mark FROM analysis_human_corrections ahc
                  WHERE ahc.analysis_question_result_id = aqr.id
                  ORDER BY ahc.id DESC LIMIT 1),
                 aqr.awarded_mark
               ) AS mark,
               aqr.maximum_marks, aqr.assessment_status
        FROM analysis_question_results aqr
        JOIN paper_analysis_versions pav ON pav.id = aqr.analysis_version_id
        JOIN student_papers sp ON sp.id = pav.paper_id
        WHERE sp.student_id = ?
          AND sp.curriculum_id = ? AND sp.curriculum_level = ?
          AND pav.version_number = sp.latest_version_number
          AND pav.status = 'completed'
        """,
        (student_id, curriculum["id"], curriculum["level"]),
    )
    now = _now()
    added = 0
    for row in rows:
        if (
            row["mark"] is None
            or row["assessment_status"] == "ungraded"
            or float(row["maximum_marks"] or 0) <= 0
            or float(row["mark"]) >= float(row["maximum_marks"]) - 0.001
        ):
            continue
        existing = query_one(
            """
            SELECT id FROM mistake_book_entries
            WHERE student_id = ? AND analysis_question_result_id = ?
            """,
            (student_id, row["id"]),
        )
        if existing:
            if row["paper_question_id"]:
                execute(
                    """
                    UPDATE mistake_book_entries
                    SET paper_question_id = COALESCE(paper_question_id, ?),
                        updated_at = ?
                    WHERE id = ?
                    """,
                    (row["paper_question_id"], now, existing["id"]),
                )
            continue
        execute(
            """
            INSERT INTO mistake_book_entries
            (student_id, analysis_question_result_id, paper_question_id,
             status, first_added_at, updated_at)
            VALUES (?, ?, ?, 'not_retried', ?, ?)
            """,
            (
                student_id,
                row["id"],
                row["paper_question_id"],
                now,
                now,
            ),
        )
        added += 1
    return added


def _source_paper_identity(item: dict, cache: dict[int, tuple | None]):
    """Resolve an official paper identity without touching assessment output."""
    version_id = int(item["analysis_version_id"])
    if version_id in cache:
        return cache[version_id]

    from question_bank import _paper_identity

    summary = _json(item.get("assessment_summary"), {})
    identity = _paper_identity(
        " ".join(
            [
                str(item.get("paper_title") or ""),
                str(item.get("paper_number") or ""),
                str(summary.get("paper_reference") or ""),
                str(summary.get("paper_title") or ""),
            ]
        )
    )
    if not identity:
        for field in ("question_paper_path", "answer_script_path"):
            path = str(item.get(field) or "")
            if not path or not os.path.isfile(path):
                continue
            identity = _paper_identity(Path(path).name)
            if identity:
                break
            try:
                with fitz.open(path) as document:
                    for page in document:
                        identity = _paper_identity(page.get_text("text"))
                        if identity:
                            break
            except (fitz.FileDataError, RuntimeError, OSError):
                continue
            if identity:
                break
    cache[version_id] = identity
    return identity


def _resolve_bank_question(item: dict, cache: dict[int, tuple | None]) -> dict | None:
    if item.get("paper_question_id"):
        return None
    identity = _source_paper_identity(item, cache)
    label_match = re.search(r"\d{1,2}", str(item.get("question_label") or ""))
    if not identity or not label_match:
        return None
    syllabus, year, session, component = identity
    question = query_one(
        """
        SELECT pq.id, pq.prompt_text AS bank_question_text,
               pq.prompt_latex AS bank_question_latex,
               pq.question_asset_path, pq.answer_asset_path,
               pq.answer_text, pq.source_key
        FROM paper_questions pq
        JOIN paper_packs pp ON pp.id = pq.paper_pack_id
        WHERE pp.syllabus_code = ? AND pp.year = ?
          AND pp.examination_session = ? AND pp.component = ?
          AND pq.question_number = ?
        """,
        (syllabus, year, session, component, label_match.group(0)),
    )
    if not question:
        return None
    execute(
        "UPDATE analysis_question_results SET paper_question_id = ? WHERE id = ?",
        (question["id"], item["question_result_id"]),
    )
    execute(
        """
        UPDATE mistake_book_entries
        SET paper_question_id = ?, updated_at = ?
        WHERE id = ?
        """,
        (question["id"], _now(), item["id"]),
    )
    return dict(question)


def _is_substantive_question_text(label: str, text: str) -> bool:
    cleaned = text.strip()
    if label and cleaned.lower().startswith(label.lower()):
        cleaned = cleaned[len(label):].strip(" :-—")
    lowered = cleaned.lower()
    has_instruction = bool(
        re.search(
            r"\b(?:calculate|determine|differentiate|expand|find|given|"
            r"integrate|prove|show|sketch|solve|state|write)\b",
            lowered,
        )
    )
    has_mathematics = bool(
        re.search(r"(?:\\frac|\\\(|[=<>≤≥]|\d)", cleaned)
    )
    return (has_instruction and len(cleaned) >= 12) or (
        has_mathematics and len(cleaned) >= 20
    ) or len(cleaned) >= 80


def mistake_book(
    student_id: int,
    *,
    topic: str = "",
    status: str = "",
) -> dict:
    from question_solver import normalize_mathjax_text

    sync_mistake_book(student_id)
    curriculum = _student_curriculum(student_id)
    rows = query_all(
        """
        SELECT mbe.*, aqr.id AS question_result_id,
               aqr.analysis_version_id, aqr.question_label,
               aqr.question_text, aqr.question_latex,
               aqr.answer_page, aqr.evidence_pages,
               aqr.maximum_marks, aqr.awarded_mark, aqr.ai_mark,
               aqr.ai_rationale, aqr.ai_rationale_zh,
               aqr.mark_scheme_text, aqr.topic, aqr.skill,
               aqr.error_category, aqr.error_mechanism,
               aqr.error_mechanism_zh, aqr.assessment_status,
               sp.id AS paper_id, sp.title AS paper_title,
               sp.syllabus_code, sp.paper_number,
               sp.updated_at AS paper_date, pav.assessment_mode,
               pav.assessment_summary, pav.question_paper_path,
               pav.answer_script_path,
               pq.question_asset_path, pq.answer_asset_path,
               pq.answer_text, pq.source_key,
               pq.prompt_text AS bank_question_text,
               pq.prompt_latex AS bank_question_latex
        FROM mistake_book_entries mbe
        JOIN analysis_question_results aqr
          ON aqr.id = mbe.analysis_question_result_id
        JOIN paper_analysis_versions pav ON pav.id = aqr.analysis_version_id
        JOIN student_papers sp ON sp.id = pav.paper_id
        LEFT JOIN paper_questions pq ON pq.id = mbe.paper_question_id
        WHERE mbe.student_id = ?
          AND sp.curriculum_id = ? AND sp.curriculum_level = ?
        ORDER BY sp.updated_at DESC, aqr.id
        """,
        (student_id, curriculum["id"], curriculum["level"]),
    )
    sibling_rows = query_all(
        """
        SELECT aqr.analysis_version_id, aqr.question_label,
               aqr.question_text, aqr.question_latex
        FROM analysis_question_results aqr
        JOIN paper_analysis_versions pav ON pav.id = aqr.analysis_version_id
        JOIN student_papers sp ON sp.id = pav.paper_id
        WHERE sp.student_id = ?
          AND sp.curriculum_id = ? AND sp.curriculum_level = ?
        ORDER BY aqr.analysis_version_id, aqr.id
        """,
        (student_id, curriculum["id"], curriculum["level"]),
    )
    sibling_groups: dict[tuple[int, str], list[dict]] = defaultdict(list)
    for sibling in sibling_rows:
        label = str(sibling["question_label"] or "")
        match = re.search(r"\d+", label)
        parent_label = match.group(0) if match else label.lower()
        sibling_groups[(sibling["analysis_version_id"], parent_label)].append(
            dict(sibling)
        )
    items = []
    topics = set()
    identity_cache: dict[int, tuple | None] = {}
    for raw in rows:
        item = dict(raw)
        resolved_question = _resolve_bank_question(item, identity_cache)
        if resolved_question:
            resolved_question = dict(resolved_question)
            item["paper_question_id"] = resolved_question.pop("id")
            item.update(resolved_question)
        if not _is_unclassified(item.get("topic")):
            topics.add(item["topic"])
        if topic and item["topic"] != topic:
            continue
        if status and item["status"] != status:
            continue
        mark = item["awarded_mark"]
        if mark is None:
            mark = item["ai_mark"]
        item["mark"] = mark
        maximum = float(item["maximum_marks"] or 0)
        item["outcome"] = (
            "incorrect"
            if float(mark or 0) <= 0
            else "partial"
            if float(mark or 0) < maximum
            else "correct"
        )
        match = re.search(r"\d+", str(item["question_label"] or ""))
        parent_label = match.group(0) if match else str(item["question_label"]).lower()
        siblings = sibling_groups.get(
            (item["analysis_version_id"], parent_label),
            [],
        )
        complete_parts = []
        incomplete_context = False
        for sibling in siblings:
            sibling_text = (
                sibling.get("question_latex")
                or sibling.get("question_text")
                or ""
            ).strip()
            if not sibling_text:
                incomplete_context = True
                continue
            label = str(sibling.get("question_label") or "").strip()
            if not _is_substantive_question_text(label, sibling_text):
                incomplete_context = True
                continue
            complete_parts.append(
                sibling_text
                if sibling_text.lower().startswith(label.lower())
                else f"{label}  {sibling_text}"
            )
        bank_question = (
            item.get("bank_question_latex")
            or item.get("bank_question_text")
            or ""
        ).strip()
        is_subpart = bool(
            re.search(r"\([a-z]\)", str(item.get("question_label") or ""), re.I)
        )
        use_bank_parent = bool(
            bank_question and (incomplete_context or is_subpart)
        )
        if use_bank_parent:
            item["complete_question_text"] = bank_question
        elif complete_parts:
            item["complete_question_text"] = "\n\n".join(complete_parts)
        else:
            item["complete_question_text"] = (
                item.get("question_latex")
                or item.get("question_text")
                or bank_question
            )
        normalized_question = normalize_mathjax_text(
            str(item.get("complete_question_text") or "")
        )
        item["complete_question_text"] = normalized_question
        own_latex = str(item.get("question_latex") or "")
        normalized_own_latex = normalize_mathjax_text(own_latex)
        if own_latex and normalized_own_latex != own_latex:
            execute(
                "UPDATE analysis_question_results SET question_latex = ? WHERE id = ?",
                (normalized_own_latex, item["question_result_id"]),
            )
            item["question_latex"] = normalized_own_latex
        solution_en = str(item.get("worked_solution_en") or "")
        solution_zh = str(item.get("worked_solution_zh") or "")
        normalized_solution_en = normalize_mathjax_text(solution_en)
        normalized_solution_zh = normalize_mathjax_text(solution_zh)
        if (
            normalized_solution_en != solution_en
            or normalized_solution_zh != solution_zh
        ):
            execute(
                """
                UPDATE mistake_book_entries
                SET worked_solution_en = ?, worked_solution_zh = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    normalized_solution_en,
                    normalized_solution_zh,
                    _now(),
                    item["id"],
                ),
            )
            item["worked_solution_en"] = normalized_solution_en
            item["worked_solution_zh"] = normalized_solution_zh
        item["needs_question_recovery"] = not _is_substantive_question_text(
            str(item.get("question_label") or ""),
            str(item.get("complete_question_text") or ""),
        )
        if item["needs_question_recovery"]:
            # A label/topic fallback such as "Q2 — Calculus" is navigation
            # metadata, not a usable question.  Keep it out of the rendered
            # question and recover the printed source page on demand below.
            item["complete_question_text"] = ""
        item["has_parent_context"] = use_bank_parent or len(complete_parts) > 1
        evidence_pages = _json(item.get("evidence_pages"), [])
        source_page = next(
            (
                int(page)
                for page in evidence_pages
                if str(page).isdigit() and int(page) > 0
            ),
            int(item.get("answer_page") or 1),
        )
        item["source_page"] = source_page
        item["has_source_image"] = bool(
            item.get("answer_script_path")
            and os.path.isfile(item["answer_script_path"])
        )
        items.append(item)
    help_rows = query_all(
        """
        SELECT * FROM student_help_questions
        WHERE student_id = ? AND status = 'completed'
        ORDER BY created_at DESC, id DESC
        """,
        (student_id,),
    )
    for raw in help_rows:
        help_item = dict(raw)
        help_topic = help_item["topic"] or "Unclassified"
        if not _is_unclassified(help_topic):
            topics.add(help_topic)
        if topic and help_topic != topic:
            continue
        if status and help_item["mistake_status"] != status:
            continue
        items.append(
            {
                "id": -int(help_item["id"]),
                "question_result_id": None,
                "analysis_version_id": None,
                "question_label": "Question",
                "question_text": help_item["transcription"],
                "question_latex": help_item["question_latex"],
                "maximum_marks": 2,
                "mark": 0,
                "ai_rationale": help_item["solution_en"],
                "ai_rationale_zh": help_item["solution_zh"],
                "mark_scheme_text": "",
                "topic": help_topic,
                "skill": help_item["skill"],
                "error_category": "unsolved question",
                "error_mechanism": "You asked Sumkora for a worked solution.",
                "error_mechanism_zh": "你向 Sumkora 请求了这道题的完整解答。",
                "assessment_status": "help",
                "paper_id": None,
                "paper_title": "Solved with Sumkora",
                "paper_date": help_item["created_at"],
                "assessment_mode": "help",
                "question_asset_path": None,
                "answer_asset_path": None,
                "answer_text": help_item["final_answer"],
                "worked_solution_en": help_item["solution_en"],
                "worked_solution_zh": help_item["solution_zh"],
                "worked_solution_model": help_item["model"],
                "source_key": f"help:{help_item['id']}",
                "bank_question_text": "",
                "bank_question_latex": "",
                "complete_question_text": (
                    help_item["question_latex"] or help_item["transcription"]
                ),
                "needs_question_recovery": False,
                "has_parent_context": False,
                "source_page": 1,
                "has_source_image": bool(
                    help_item.get("image_path")
                    and os.path.isfile(help_item["image_path"])
                ),
                "outcome": "incorrect",
                "status": help_item["mistake_status"],
            }
        )
    total_count = len(rows) + len(help_rows)
    all_statuses = [row["status"] for row in rows] + [
        row["mistake_status"] for row in help_rows
    ]
    return {
        "items": items,
        "topics": sorted(topics),
        "selected_topic": topic,
        "selected_status": status,
        "counts": {
            "total": total_count,
            "not_retried": sum(value == "not_retried" for value in all_statuses),
            "improving": sum(value == "improving" for value in all_statuses),
            "mastered": sum(value == "mastered" for value in all_statuses),
        },
    }


def update_mistake_status(student_id: int, entry_id: int, status: str) -> bool:
    if status not in {"not_retried", "improving", "mastered"}:
        return False
    if entry_id < 0:
        row = query_one(
            "SELECT id FROM student_help_questions WHERE id = ? AND student_id = ?",
            (-entry_id, student_id),
        )
        if not row:
            return False
        execute(
            """
            UPDATE student_help_questions
            SET mistake_status = ?, updated_at = ?
            WHERE id = ?
            """,
            (status, _now(), -entry_id),
        )
        return True
    row = query_one(
        "SELECT id FROM mistake_book_entries WHERE id = ? AND student_id = ?",
        (entry_id, student_id),
    )
    if not row:
        return False
    execute(
        "UPDATE mistake_book_entries SET status = ?, updated_at = ? WHERE id = ?",
        (status, _now(), entry_id),
    )
    return True


def question_bank_inventory() -> dict:
    counts = query_one(
        """
        SELECT COUNT(*) AS questions,
               SUM(CASE WHEN review_status = 'ready' THEN 1 ELSE 0 END) AS ready,
               SUM(CASE WHEN review_status = 'needs_review' THEN 1 ELSE 0 END) AS needs_review,
               COUNT(DISTINCT paper_pack_id) AS papers
        FROM paper_questions
        """
    )
    topics = query_all(
        """
        SELECT topic, COUNT(*) AS question_count
        FROM paper_questions
        WHERE review_status = 'ready'
        GROUP BY topic ORDER BY topic
        """
    )
    return {
        "questions": int(counts["questions"] or 0),
        "ready": int(counts["ready"] or 0),
        "needs_review": int(counts["needs_review"] or 0),
        "papers": int(counts["papers"] or 0),
        "topics": [dict(row) for row in topics],
    }


def _bank_candidates() -> list[dict]:
    rows = query_all(
        """
        SELECT pq.*, pp.syllabus_code, pp.year, pp.examination_session,
               pp.component
        FROM paper_questions pq
        JOIN paper_packs pp ON pp.id = pq.paper_pack_id
        WHERE pq.review_status = 'ready'
          AND pq.parent_question_id IS NULL
          AND (pq.question_asset_path IS NOT NULL OR pq.prompt_text != '')
        ORDER BY pp.year DESC, pp.component, pq.order_index
        """
    )
    result = []
    for row in rows:
        item = dict(row)
        item["canonical_topic"] = canonical_topic(
            item.get("topic") or "",
            " ".join(str(value) for value in _json(item.get("skills"), [])),
            item.get("prompt_text") or "",
        )
        item["skill_list"] = [
            str(value).lower() for value in _json(item["skills"], [])
        ]
        result.append(item)
    return result


def _choose_weak_topic(
    topic_states: list[dict],
    available_topics: set[str],
    previous_topic: str = "",
    *,
    rng=None,
) -> str:
    """Choose one evidenced weak topic, avoiding the previous set when possible."""
    rng = rng or random.SystemRandom()
    eligible = [
        row
        for row in topic_states
        if row.get("topic") in available_topics
    ]
    if not eligible:
        return ""
    alternatives = [
        row for row in eligible
        if len(eligible) < 2 or row.get("topic") != previous_topic
    ]
    pool = alternatives or eligible
    weights = []
    for row in pool:
        mastery = max(0.0, min(1.0, float(row.get("current_estimate") or 0.5)))
        evidence = max(1, int(row.get("evidence_count") or 1))
        confidence = max(0.25, min(1.0, float(row.get("confidence") or 0.5)))
        # Severity dominates; evidence and confidence stop one noisy result
        # from overwhelming repeated, well-supported weaknesses.
        weight = (0.12 + (1.0 - mastery) ** 2) * (1.0 + math.log1p(evidence)) * confidence
        weights.append(max(weight, 0.01))
    threshold = rng.random() * sum(weights)
    cumulative = 0.0
    for row, weight in zip(pool, weights):
        cumulative += weight
        if cumulative >= threshold:
            return str(row["topic"])
    return str(pool[-1]["topic"])


def create_practice_set(
    student_id: int,
    *,
    count: int,
    selection_mode: str,
    topic: str,
    difficulty: str,
    calculator_policy: str,
    lang: str,
) -> int:
    count = max(10, min(int(count), 50))
    if selection_mode not in {"weaknesses", "topic", "mixed", "mistakes"}:
        selection_mode = "weaknesses"
    if difficulty not in {"mixed", "standard", "challenging"}:
        difficulty = "mixed"
    if calculator_policy not in {"any", "calculator", "non-calculator"}:
        calculator_policy = "any"

    candidates = _bank_candidates()
    recent = {
        row["paper_question_id"]
        for row in query_all(
            """
            SELECT psi.paper_question_id
            FROM practice_set_items psi
            JOIN practice_sets ps ON ps.id = psi.practice_set_id
            WHERE ps.student_id = ?
            ORDER BY ps.created_at DESC LIMIT 150
            """,
            (student_id,),
        )
    }
    from assessment import student_skill_profile

    profile = student_skill_profile(student_id)
    topic_states = profile["topic_states"]
    states = profile["states"]
    available_topics = {item["canonical_topic"] for item in candidates}
    previous = query_one(
        """
        SELECT topic FROM practice_sets
        WHERE student_id = ? AND selection_mode = 'weaknesses' AND topic != ''
        ORDER BY created_at DESC, id DESC LIMIT 1
        """,
        (student_id,),
    )
    selected_weak_topic = ""
    if selection_mode == "weaknesses":
        selected_weak_topic = _choose_weak_topic(
            topic_states,
            available_topics,
            previous["topic"] if previous else "",
        )
        if not selected_weak_topic and available_topics:
            selected_weak_topic = sorted(available_topics)[0]
        topic = selected_weak_topic
    mistake_question_ids = {
        row["paper_question_id"]: row["id"]
        for row in query_all(
            """
            SELECT id, paper_question_id FROM mistake_book_entries
            WHERE student_id = ? AND status != 'mastered'
              AND paper_question_id IS NOT NULL
            """,
            (student_id,),
        )
    }

    scored = []
    for item in candidates:
        if (
            calculator_policy != "any"
            and item["calculator_policy"] != calculator_policy
        ):
            continue
        if difficulty != "mixed" and item["question_demand"] != difficulty:
            continue
        item_topic = item["canonical_topic"]
        item_skills = item["skill_list"]
        score = 0
        reason = "Mixed revision"
        if selection_mode == "topic":
            requested_topic = canonical_topic(topic)
            if not topic or item_topic != requested_topic:
                continue
            score = 100
            topic = requested_topic
            reason = f"Selected topic: {requested_topic}"
        elif selection_mode == "mistakes":
            if item["id"] not in mistake_question_ids:
                continue
            score = 120
            reason = "Retry an earlier mistake"
        elif selection_mode == "weaknesses":
            if selected_weak_topic and item_topic != selected_weak_topic:
                continue
            score = 100
            reason = f"Targeted weak topic: {selected_weak_topic or item_topic}"
        else:
            score = 20
        if item["id"] in recent:
            score -= 35
        score += min(int(item["year"] or 0) - 2020, 10)
        scored.append((score, item["id"], item, reason))

    scored.sort(key=lambda value: (-value[0], value[1]))
    selected = []
    selected_groups: set[str] = set()
    for score, item_id, item, reason in scored:
        group = str(
            item.get("dependency_group")
            or item.get("source_key")
            or f"question:{item_id}"
        )
        if group in selected_groups:
            continue
        selected_groups.add(group)
        selected.append((score, item_id, item, reason))
        if len(selected) >= count:
            break
    now = _now()
    title_en = {
        "weaknesses": f"{topic or 'Targeted'} practice",
        "topic": f"{topic or 'Topic'} practice",
        "mixed": "Mixed revision worksheet",
        "mistakes": "Mistake retry worksheet",
    }[selection_mode]
    title_zh = {
        "weaknesses": f"{topic or '薄弱项'}专项练习",
        "topic": f"{topic or '专题'}练习",
        "mixed": "综合复习练习",
        "mistakes": "错题重练",
    }[selection_mode]
    explanation_en = (
        f"Selected {len(selected)} non-repeating questions from the approved "
        f"question bank for {title_en.lower()}. "
        + (
            f"Only {len(selected)} suitable questions were available."
            if len(selected) < count
            else "The worksheet contains the requested number of questions."
        )
    )
    explanation_zh = (
        f"已从审核通过的题库中选择 {len(selected)} 道不重复题目，用于{title_zh}。"
        + (
            f"题库中目前只有 {len(selected)} 道符合条件的题目。"
            if len(selected) < count
            else "练习题数量符合你的选择。"
        )
    )
    set_id = execute(
        """
        INSERT INTO practice_sets
        (student_id, title, selection_mode, requested_count, actual_count,
         topic, difficulty, calculator_policy, language, status,
         selection_explanation, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'ready', ?, ?, ?)
        """,
        (
            student_id,
            title_zh if lang == "zh" else title_en,
            selection_mode,
            count,
            len(selected),
            topic,
            difficulty,
            calculator_policy,
            lang,
            explanation_zh if lang == "zh" else explanation_en,
            now,
            now,
        ),
    )
    for order, (_, _, item, reason) in enumerate(selected, start=1):
        execute(
            """
            INSERT INTO practice_set_items
            (practice_set_id, paper_question_id, mistake_book_entry_id,
             order_index, selection_reason)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                set_id,
                item["id"],
                mistake_question_ids.get(item["id"]),
                order,
                reason,
            ),
        )
    return set_id


def create_generated_practice_set(
    student_id: int,
    *,
    count: int,
    selection_mode: str,
    topic: str,
    difficulty: str,
    calculator_policy: str,
    lang: str,
) -> int:
    """Create an original worksheet only after every item is validated."""
    curriculum = _student_curriculum(student_id)
    count = max(10, min(int(count), 50))
    if selection_mode not in {"weaknesses", "topic", "mixed"}:
        selection_mode = "weaknesses"
    if difficulty not in {"mixed", "standard", "challenging"}:
        difficulty = "mixed"
    if calculator_policy not in {"any", "calculator", "non-calculator"}:
        calculator_policy = "any"

    allowed_topics = set(curriculum["topics"])
    selected_topic = ""
    if selection_mode == "topic":
        selected_topic = str(topic or "").strip()
        if selected_topic not in allowed_topics:
            raise ValueError("Choose a valid topic for this curriculum.")
    elif selection_mode == "weaknesses":
        from assessment import student_skill_profile

        previous = query_one(
            """
            SELECT topic FROM practice_sets
            WHERE student_id = ? AND curriculum_id = ?
              AND curriculum_level = ? AND source_mode = 'generated'
              AND selection_mode = 'weaknesses' AND topic != ''
            ORDER BY created_at DESC, id DESC LIMIT 1
            """,
            (student_id, curriculum["id"], curriculum["level"]),
        )
        selected_topic = _choose_weak_topic(
            student_skill_profile(student_id)["topic_states"],
            allowed_topics,
            previous["topic"] if previous else "",
        )
        # No observed topic means there is no defensible weakness yet.  The
        # generator receives a balanced diagnostic request instead.
        if not selected_topic:
            selection_mode = "mixed"

    questions, model_info = generate_validated_practice_questions(
        curriculum=curriculum,
        topic=selected_topic,
        count=count,
        difficulty=difficulty,
        calculator_policy=calculator_policy,
    )
    if len(questions) != count:
        raise RuntimeError(
            "The worksheet could not be fully generated and independently checked."
        )

    topic_name = selected_topic or "Mixed curriculum review"
    title_en = (
        f"{topic_name} targeted practice"
        if selected_topic
        else f"{curriculum['name']} diagnostic practice"
    )
    title_zh = (
        f"{topic_label('zh', topic_name)} 专项练习"
        if selected_topic
        else f"{curriculum['name_zh']}综合诊断练习"
    )
    explanation_en = (
        f"{count} original {curriculum['name']} questions were generated, "
        "solved independently, and checked before being saved."
    )
    explanation_zh = (
        f"已生成 {count} 道原创{curriculum['name_zh']}题目，并在保存前完成独立解答与校验。"
    )
    now = _now()
    model_label = "/".join(
        value
        for value in (
            model_info.get("generation_model"),
            model_info.get("validation_model"),
        )
        if value
    )
    set_id = execute(
        """
        INSERT INTO practice_sets
        (student_id, title, selection_mode, requested_count, actual_count,
         topic, difficulty, calculator_policy, language, status,
         selection_explanation, source_mode, generation_model,
         curriculum_id, curriculum_level, subject, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'ready', ?, 'generated', ?, ?, ?, ?, ?, ?)
        """,
        (
            student_id,
            title_zh if lang == "zh" else title_en,
            selection_mode,
            count,
            count,
            selected_topic,
            difficulty,
            calculator_policy,
            lang,
            explanation_zh if lang == "zh" else explanation_en,
            model_label,
            curriculum["id"],
            curriculum["level"],
            curriculum["subject"],
            now,
            now,
        ),
    )
    for item in questions:
        execute(
            """
            INSERT INTO generated_practice_questions
            (practice_set_id, order_index, topic, skill, difficulty,
             calculator_policy, prompt_en, prompt_zh, solution_en, solution_zh,
             final_answer_en, final_answer_zh, maximum_marks,
             validation_notes, generation_model, validation_model,
             validation_status, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'validated', ?)
            """,
            (
                set_id,
                item["order"],
                item["topic"],
                item["skill"],
                item["difficulty"],
                calculator_policy,
                item["prompt_en"],
                item["prompt_zh"],
                item["solution_en"],
                item["solution_zh"],
                item["final_answer_en"],
                item["final_answer_zh"],
                item["maximum_marks"],
                item.get("validation_notes") or "",
                model_info.get("generation_model") or "",
                model_info.get("validation_model") or "",
                now,
            ),
        )
    return set_id


def practice_sets(student_id: int) -> list[dict]:
    curriculum = _student_curriculum(student_id)
    return [
        dict(row)
        for row in query_all(
            """
            SELECT * FROM practice_sets
            WHERE student_id = ? AND curriculum_id = ? AND curriculum_level = ?
            ORDER BY created_at DESC
            """,
            (student_id, curriculum["id"], curriculum["level"]),
        )
    ]


def practice_set_detail(student_id: int, set_id: int) -> dict | None:
    practice = query_one(
        "SELECT * FROM practice_sets WHERE id = ? AND student_id = ?",
        (set_id, student_id),
    )
    if not practice:
        return None
    if practice["source_mode"] == "generated":
        generated = query_all(
            """
            SELECT *, order_index AS generated_order
            FROM generated_practice_questions
            WHERE practice_set_id = ? AND validation_status = 'validated'
            ORDER BY order_index
            """,
            (set_id,),
        )
        return {"set": dict(practice), "items": [dict(row) for row in generated]}
    items = query_all(
        """
        SELECT psi.*, pq.*, pp.year, pp.examination_session, pp.component,
               pp.syllabus_code
        FROM practice_set_items psi
        JOIN paper_questions pq ON pq.id = psi.paper_question_id
        JOIN paper_packs pp ON pp.id = pq.paper_pack_id
        WHERE psi.practice_set_id = ?
        ORDER BY psi.order_index
        """,
        (set_id,),
    )
    return {"set": dict(practice), "items": [dict(row) for row in items]}


_CJK_FONT_BUFFER = None
_LATIN_FONT_BUFFER = None


def _font_name(page: fitz.Page, lang: str) -> str:
    if lang != "zh":
        return "helv"
    global _CJK_FONT_BUFFER
    if _CJK_FONT_BUFFER is None:
        _CJK_FONT_BUFFER = fitz.Font(fontname="china-s").buffer
    font_name = "sumkoracjk"
    page.insert_font(fontname=font_name, fontbuffer=_CJK_FONT_BUFFER)
    return font_name


def _latin_font_buffer() -> bytes:
    """Load the bundled Latin/math font once per process."""
    global _LATIN_FONT_BUFFER
    if _LATIN_FONT_BUFFER is None:
        from matplotlib import get_data_path

        font_path = os.path.join(get_data_path(), "fonts", "ttf", "DejaVuSans.ttf")
        _LATIN_FONT_BUFFER = fitz.Font(fontfile=font_path).buffer
    return _LATIN_FONT_BUFFER


def _latin_font_name(page: fitz.Page) -> str:
    """Embed a Latin/math font with reliable super/subscript glyphs."""
    font_name = "sumkoralatin"
    page.insert_font(fontname=font_name, fontbuffer=_latin_font_buffer())
    return font_name


_SUPERSCRIPTS = str.maketrans("0123456789+-=()", "⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻⁼⁽⁾")
_SUBSCRIPTS = str.maketrans("0123456789+-=()", "₀₁₂₃₄₅₆₇₈₉₊₋₌₍₎")
_CHEMICAL_SUBSCRIPTS = str.maketrans("0123456789", "₀₁₂₃₄₅₆₇₈₉")

_CHEMICAL_ELEMENTS = {
    "H", "He", "Li", "Be", "B", "C", "N", "O", "F", "Ne", "Na", "Mg",
    "Al", "Si", "P", "S", "Cl", "Ar", "K", "Ca", "Sc", "Ti", "V", "Cr",
    "Mn", "Fe", "Co", "Ni", "Cu", "Zn", "Ga", "Ge", "As", "Se", "Br", "Kr",
    "Rb", "Sr", "Y", "Zr", "Nb", "Mo", "Tc", "Ru", "Rh", "Pd", "Ag", "Cd",
    "In", "Sn", "Sb", "Te", "I", "Xe", "Cs", "Ba", "La", "Ce", "Pr", "Nd",
    "Pm", "Sm", "Eu", "Gd", "Tb", "Dy", "Ho", "Er", "Tm", "Yb", "Lu", "Hf",
    "Ta", "W", "Re", "Os", "Ir", "Pt", "Au", "Hg", "Tl", "Pb", "Bi", "Po",
    "At", "Rn", "Fr", "Ra", "Ac", "Th", "Pa", "U", "Np", "Pu", "Am", "Cm",
    "Bk", "Cf", "Es", "Fm", "Md", "No", "Lr", "Rf", "Db", "Sg", "Bh", "Hs",
    "Mt", "Ds", "Rg", "Cn", "Nh", "Fl", "Mc", "Lv", "Ts", "Og",
}


def _plain_chemical_formulae(value: str) -> str:
    """Use Unicode subscripts for bare, valid chemical formulae such as H2O2."""

    def convert(match: re.Match[str]) -> str:
        token = match.group(0)
        core = re.sub(r"\((?:aq|s|l|g)\)$", "", token)
        symbols = re.findall(r"[A-Z][a-z]?", core)
        if not any(character.isdigit() for character in core):
            return token
        if not symbols or any(symbol not in _CHEMICAL_ELEMENTS for symbol in symbols):
            return token
        return token.translate(_CHEMICAL_SUBSCRIPTS)

    return re.sub(
        r"(?<![A-Za-z0-9])(?:[A-Z][a-z]?\d*)+(?:\((?:aq|s|l|g)\))?"
        r"(?![A-Za-z0-9])",
        convert,
        value,
    )


def _plain_math(value: str) -> str:
    """Make TeX-like fallback text readable when no source PDF is available."""
    text = str(value or "")
    text = text.replace(r"\(", "").replace(r"\)", "")
    text = text.replace(r"\[", "").replace(r"\]", "")
    text = text.replace("$$", "").replace(r"\$", "").replace("$", "")
    text = text.replace("**", "").replace("`", "")
    # Flatten textual subscripts before handling fractions so nested braces do
    # not prevent a readable fallback such as m(溶质)/m(溶液).
    text = re.sub(
        r"_\{\\(?:text|mathrm|mathbf)\{([^{}]+)\}\}",
        r"(\1)",
        text,
    )
    for _ in range(3):
        text = re.sub(
            r"\\(?:dfrac|tfrac|frac)\{([^{}]+)\}\{([^{}]+)\}",
            r"(\1)/(\2)",
            text,
        )
        text = re.sub(r"\\boxed\{([^{}]+)\}", r"\1", text)
        text = re.sub(r"\\(?:mathrm|mathbf)\{([^{}]+)\}", r"\1", text)
    replacements = {
        r"\leq": "≤",
        r"\le": "≤",
        r"\geq": "≥",
        r"\ge": "≥",
        r"\neq": "≠",
        r"\times": "×",
        r"\div": "÷",
        r"\pm": "±",
        r"\infty": "∞",
        r"\theta": "θ",
        r"\pi": "π",
        r"\sqrt": "√",
        r"\sum": "Σ",
        r"\therefore": "∴",
        r"\in": "∈",
        r"\cdot": "·",
        r"\rightarrow": "→",
        r"\to": "→",
        r"\approx": "≈",
        r"\circ": "°",
        r"\,": " ",
        r"\;": " ",
        r"\left": "",
        r"\right": "",
    }
    for source, target in replacements.items():
        text = text.replace(source, target)
    text = re.sub(r"\^\{?°\}?", "°", text)
    # A provider can occasionally return a malformed fraction whose braces or
    # math delimiters do not balance.  Never expose raw TeX commands in a
    # printable booklet even when the richer renderer cannot parse it.
    text = re.sub(r"\\(?:dfrac|tfrac|frac)", " / ", text)
    text = text.replace(r"\%", "%")
    text = re.sub(r"\\text\{([^{}]*)\}", r"\1", text)
    text = re.sub(
        r"\^\{([0-9+\-=()]+)\}",
        lambda match: match.group(1).translate(_SUPERSCRIPTS),
        text,
    )
    text = re.sub(
        r"\^([0-9])",
        lambda match: match.group(1).translate(_SUPERSCRIPTS),
        text,
    )
    text = re.sub(
        r"_\{([0-9+\-=()]+)\}",
        lambda match: match.group(1).translate(_SUBSCRIPTS),
        text,
    )
    text = re.sub(
        r"_([0-9])",
        lambda match: match.group(1).translate(_SUBSCRIPTS),
        text,
    )
    # Script conversion can remove the nested braces that initially prevented
    # these wrappers from matching (for example L\,mol^{-1}).
    text = re.sub(r"\\(?:text|mathrm|mathbf)\{([^{}]*)\}", r"\1", text)
    text = re.sub(r"\\([A-Za-z]+)", r"\1", text)
    # At this point every supported TeX command has already been converted.
    # Any remaining slash is a malformed delimiter emitted by the provider
    # (for example ``\H2O2(aq)\``) and must never reach a printable booklet.
    text = text.replace("\\", "")
    text = re.sub(r"\b(L|mol)\s*[−-]1\b", r"\1⁻¹", text)
    text = re.sub(r"\b(cm|dm|m)\s*[−-]3\b", r"\1⁻³", text)
    text = re.sub(r"\b(cm|dm|m)3\b", r"\1³", text)
    text = _plain_chemical_formulae(text)
    text = re.sub(
        r"(?<=\d)(?=(?:cm³|dm³|m³|cm⁻³|dm⁻³|m⁻³|mol|min|ms|kg|mg|µg|μg|"
        r"mL|kJ|kPa|Pa|Hz|g|L|J|K|V|A|W|N|h|s)(?![A-Za-z0-9]))",
        " ",
        text,
    )
    unit_pattern = (
        r"cm³|dm³|m³|cm⁻³|dm⁻³|m⁻³|mol|min|ms|kg|mg|µg|μg|mL|kJ|kPa|"
        r"Pa|Hz|g|L|J|K|V|A|W|N|h|s"
    )
    text = re.sub(
        rf"\b({unit_pattern})(?=[\u3400-\u9fff])",
        r"\1 ",
        text,
    )
    text = re.sub(
        r"((?:[A-Z][a-z]?[₀-₉]*)+(?:\((?:aq|s|l|g)\))?)"
        r"(?=[\u3400-\u9fff])",
        r"\1 ",
        text,
    )
    text = re.sub(r"°\s*C\b", "°C", text)
    text = text.replace("{", "").replace("}", "")
    return re.sub(r"[ \t]+", " ", text).strip()


def _clean_generated_practice_body(value: str) -> str:
    """Remove model boilerplate that should not appear in student booklets."""
    text = str(value or "")
    boilerplate = (
        r"请?只(?:使用|根据)题目所给(?:的)?(?:信息|内容)(?:作答|回答)[。.!！]?",
        r"(?:Use|Answer using) only the (?:information|content) "
        r"(?:given|provided) in (?:the|this) question[.!]?",
        r"AI\s*生成练习\s*[·•-]?\s*已独立解答并校验",
        r"AI-generated practice\s*[·•-]?\s*independently solved and validated",
    )
    for pattern in boilerplate:
        text = re.sub(rf"(?im)^\s*(?:{pattern})\s*$", "", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _readable_markdown_tables(value: str, lang: str) -> str:
    """Turn provider Markdown tables into compact, readable PDF rows."""
    lines = str(value or "").splitlines()
    output: list[str] = []
    index = 0

    def cells(line: str) -> list[str]:
        return [part.strip() for part in line.strip().strip("|").split("|")]

    def divider(line: str) -> bool:
        parts = cells(line)
        return bool(parts) and all(re.fullmatch(r":?-{3,}:?", part) for part in parts)

    while index < len(lines):
        stripped = lines[index].strip()
        if (
            stripped.startswith("|")
            and stripped.endswith("|")
            and index + 1 < len(lines)
            and divider(lines[index + 1].strip())
        ):
            headers = cells(stripped)
            index += 2
            if output and output[-1] != "":
                output.append("")
            while index < len(lines):
                row_line = lines[index].strip()
                if not (row_line.startswith("|") and row_line.endswith("|")):
                    break
                row = cells(row_line)
                fields = []
                for column, cell in enumerate(row):
                    if not cell:
                        continue
                    header = headers[column] if column < len(headers) else ""
                    if header:
                        separator = "：" if lang == "zh" else ": "
                        fields.append(f"{header}{separator}{cell}")
                    else:
                        fields.append(cell)
                if fields:
                    output.append("  ·  ".join(fields))
                    # A blank line is intentional: PDF rich-text layout treats
                    # adjacent non-empty source lines as one flowing paragraph.
                    # Separating generated rows keeps each record visually
                    # distinct and prevents the next row from touching it.
                    output.append("")
                index += 1
            if output and output[-1] != "":
                output.append("")
            continue
        if divider(stripped):
            index += 1
            continue
        output.append(lines[index])
        index += 1
    return "\n".join(output)


_MATH_IMAGE_CACHE: dict[str, tuple[bytes, float, float]] = {}
_MATH_CHUNK_RE = re.compile(
    r"(\\\[(?:.|\n)*?\\\]|\\\((?:.|\n)*?\\\)|\$\$(?:.|\n)*?\$\$|\$[^$\n]+\$)"
)


def _math_image(expression: str) -> tuple[bytes, float, float] | None:
    """Render one TeX expression to a tightly cropped transparent PNG."""
    value = expression.strip()
    if value.startswith(r"\(") and value.endswith(r"\)"):
        value = value[2:-2]
    elif value.startswith(r"\[") and value.endswith(r"\]"):
        value = value[2:-2]
    elif value.startswith("$$") and value.endswith("$$"):
        value = value[2:-2]
    elif value.startswith("$") and value.endswith("$"):
        value = value[1:-1]
    value = value.strip()
    if not value:
        return None
    # Matplotlib's math font cannot display CJK glyphs.  Let the PDF's
    # embedded Simplified-Chinese font handle mixed prose/math instead.
    if re.search(r"[\u3400-\u9fff]", value):
        return None
    # Quantities, units, elementary powers and chemical formulae are sharper
    # as native PDF text.  Tiny transparent images for strings such as
    # ``0.65\,\mathrm{g}`` can acquire overlapping glyphs in Safari's PDF
    # renderer.  Reserve MathText images for notation that genuinely needs a
    # mathematical compositor.
    complex_math = re.search(
        r"\\(?:dfrac|tfrac|frac|sqrt|lim|sum|int|prod|binom|begin|overline|vec)(?![A-Za-z])",
        value,
    )
    symbolic_script = re.search(r"[_^]\{[^0-9+\-=()\\,\s]+\}", value)
    if not complex_math and not symbolic_script:
        return None
    cached = _MATH_IMAGE_CACHE.get(value)
    if cached:
        return cached
    # MathText supports \mathrm but not the full LaTeX \text command.
    normalised = re.sub(r"\\text\{([^{}]*)\}", r"\\mathrm{\1}", value)
    try:
        from matplotlib.mathtext import math_to_image

        buffer = BytesIO()
        dpi = 220
        math_to_image(
            f"${normalised}$",
            buffer,
            dpi=dpi,
            format="png",
            color="#202334",
        )
        payload = buffer.getvalue()
        pixmap = fitz.Pixmap(payload)
        rendered = (
            payload,
            max(7.0, pixmap.width * 72 / dpi),
            max(7.0, pixmap.height * 72 / dpi),
        )
    except Exception:
        return None
    _MATH_IMAGE_CACHE[value] = rendered
    return rendered


class _PdfFlow:
    """Compact, vector-preserving A4 compositor for printable learning packs."""

    def __init__(self, *, title: str, subtitle: str, lang: str):
        self.document = fitz.open()
        self.title = title
        self.subtitle = subtitle
        self.lang = lang
        self.margin_x = 42
        self.bottom = fitz.paper_rect("a4").height - 42
        self.page: fitz.Page | None = None
        self.font = "helv"
        self.font_metrics = fitz.Font(
            fontname="china-s" if lang == "zh" else "helv"
        )
        self.latin_metrics = fitz.Font(fontbuffer=_latin_font_buffer())
        self.latin_font = "helv"
        self.y = 0.0
        self._new_page(first=True)

    def _text_width(self, value: str, size: float) -> float:
        return self.font_metrics.text_length(str(value), fontsize=size)

    def _latin_width(self, value: str, size: float) -> float:
        return self.latin_metrics.text_length(str(value), fontsize=size)

    def _new_page(self, *, first: bool = False) -> None:
        self.page = self.document.new_page(
            width=fitz.paper_rect("a4").width,
            height=fitz.paper_rect("a4").height,
        )
        self.font = _font_name(self.page, self.lang)
        self.latin_font = _latin_font_name(self.page)
        if first:
            self.page.draw_rect(
                fitz.Rect(self.margin_x, 28, self.margin_x + 24, 31),
                color=(0.35, 0.30, 0.91),
                fill=(0.35, 0.30, 0.91),
                width=0,
            )
            self.page.insert_text(
                (self.margin_x, 48),
                self.title,
                fontname=self.font,
                fontsize=17,
                color=(0.08, 0.10, 0.17),
            )
            self.page.insert_textbox(
                fitz.Rect(
                    self.margin_x,
                    60,
                    self.page.rect.width - self.margin_x,
                    88,
                ),
                self.subtitle,
                fontname=self.font,
                fontsize=8.8,
                color=(0.38, 0.42, 0.50),
            )
            self.page.draw_line(
                (self.margin_x, 94),
                (self.page.rect.width - self.margin_x, 94),
                color=(0.84, 0.83, 0.96),
                width=0.8,
            )
            self.y = 112
        else:
            self.y = 42

    def _ensure(self, height: float) -> None:
        if self.y + height > self.bottom and self.y > 60:
            self._new_page()

    def add_asset(
        self,
        path: str | None,
        *,
        label: str,
        source_label: str,
    ) -> bool:
        if not path or not os.path.isfile(path):
            return False
        try:
            source = fitz.open(path)
        except (fitz.FileDataError, RuntimeError):
            return False
        try:
            for source_index, source_page in enumerate(source):
                available_width = self.page.rect.width - 2 * self.margin_x
                header_height = 24
                scale = min(available_width / source_page.rect.width, 1.0)
                rendered_height = source_page.rect.height * scale
                remaining = self.bottom - self.y - header_height - 10
                minimum_readable_height = min(260, rendered_height * 0.55)
                if remaining < minimum_readable_height and self.y > 60:
                    self._new_page()
                    remaining = self.bottom - self.y - header_height - 10
                if rendered_height > remaining:
                    scale = min(scale, remaining / source_page.rect.height)
                    rendered_height = source_page.rect.height * scale
                continuation = (
                    f" ({'continued' if self.lang == 'en' else '续'})"
                    if source_index
                    else ""
                )
                self.page.insert_text(
                    (self.margin_x, self.y + 10),
                    f"{label}{continuation}",
                    fontname=self.font,
                    fontsize=10.2,
                    color=(0.10, 0.12, 0.20),
                )
                if source_label:
                    source_width = self._text_width(source_label, 7.5)
                    self.page.insert_text(
                        (
                            max(
                                self.margin_x + 120,
                                self.page.rect.width - self.margin_x - source_width,
                            ),
                            self.y + 10,
                        ),
                        source_label,
                        fontname=self.font,
                        fontsize=7.5,
                        color=(0.46, 0.49, 0.56),
                    )
                top = self.y + header_height
                target = fitz.Rect(
                    self.margin_x,
                    top,
                    self.margin_x + source_page.rect.width * scale,
                    top + rendered_height,
                )
                self.page.show_pdf_page(target, source, source_index)
                self.y = target.y1 + 16
            return True
        finally:
            source.close()

    def add_text(
        self,
        *,
        label: str,
        body: str,
        source_label: str,
    ) -> None:
        readable = _plain_math(body)
        wrapped: list[str] = []
        for paragraph in readable.splitlines() or [""]:
            wrapped.extend(
                textwrap.wrap(
                    paragraph,
                    width=84 if self.lang == "en" else 45,
                    break_long_words=False,
                    break_on_hyphens=False,
                )
                or [""]
            )
        continuation = False
        while wrapped:
            available_lines = max(int((self.bottom - self.y - 38) / 14), 1)
            if available_lines < 3:
                self._new_page()
                available_lines = max(int((self.bottom - self.y - 38) / 14), 1)
            chunk = wrapped[:available_lines]
            wrapped = wrapped[available_lines:]
            heading = (
                f"{label} ({'continued' if self.lang == 'en' else '续'})"
                if continuation
                else label
            )
            self.page.insert_text(
                (self.margin_x, self.y + 10),
                heading,
                fontname=self.font,
                fontsize=10.2,
                color=(0.10, 0.12, 0.20),
            )
            self.page.insert_textbox(
                fitz.Rect(
                    self.margin_x,
                    self.y + 23,
                    self.page.rect.width - self.margin_x,
                    self.y + 25 + len(chunk) * 14,
                ),
                "\n".join(chunk),
                fontname=self.font,
                fontsize=10,
                lineheight=1.3,
                color=(0.15, 0.17, 0.23),
            )
            self.y += 29 + len(chunk) * 14
            if not wrapped and source_label:
                self.page.insert_text(
                    (self.margin_x, self.y),
                    source_label,
                    fontname=self.font,
                    fontsize=7.5,
                    color=(0.46, 0.49, 0.56),
                )
                self.y += 18
            continuation = True

    def add_rich_text(
        self,
        *,
        label: str,
        body: str,
        source_label: str,
    ) -> None:
        """Lay out Chinese text and genuinely rendered TeX mathematics."""
        max_width = self.page.rect.width - 2 * self.margin_x
        continuation = False

        def add_heading() -> None:
            heading = (
                f"{label} ({'continued' if self.lang == 'en' else '续'})"
                if continuation
                else label
            )
            self.page.draw_rect(
                fitz.Rect(self.margin_x, self.y + 1, self.margin_x + 3, self.y + 15),
                color=(0.35, 0.30, 0.91),
                fill=(0.35, 0.30, 0.91),
                width=0,
            )
            self.page.insert_text(
                (self.margin_x + 10, self.y + 11),
                heading,
                fontname=self.font,
                fontsize=10.8,
                color=(0.18, 0.16, 0.39),
            )
            self.y += 25

        self._ensure(58)
        add_heading()
        line: list[tuple[str, object, float, float]] = []
        line_width = 0.0
        line_height = 15.0

        def new_continuation_page() -> None:
            nonlocal continuation
            continuation = True
            self._new_page()
            add_heading()

        def flush_line(*, paragraph_gap: bool = False) -> None:
            nonlocal line, line_width, line_height
            if not line:
                if paragraph_gap:
                    self.y += 5
                return
            if self.y + line_height + 5 > self.bottom:
                new_continuation_page()
            x = self.margin_x
            baseline = self.y + max(10.8, (line_height + 9.3) / 2)
            for kind, value, width, height in line:
                if kind == "spacer":
                    pass
                elif kind == "math":
                    top = self.y + max(0.0, (line_height - height) / 2)
                    self.page.insert_image(
                        fitz.Rect(x, top, x + width, top + height),
                        stream=value,
                        keep_proportion=True,
                    )
                else:
                    self.page.insert_text(
                        (x, baseline),
                        str(value),
                        fontname=self.latin_font if kind == "latin" else self.font,
                        fontsize=10.35,
                        color=(0.15, 0.17, 0.23),
                    )
                x += width
            self.y += line_height + (8 if paragraph_gap else 3.5)
            line = []
            line_width = 0.0
            line_height = 15.0

        def append_atom(kind: str, value: object, width: float, height: float) -> None:
            nonlocal line_width, line_height
            if line and line_width + width > max_width:
                flush_line()
            if width > max_width and kind == "math":
                scale = max_width / width
                width *= scale
                height *= scale
            line.append((kind, value, width, height))
            line_width += width
            line_height = max(line_height, height)

        def append_spacer(width: float = 4.5) -> None:
            append_atom("spacer", "", width, 15.0)

        prepared_body = _readable_markdown_tables(str(body or ""), self.lang)
        chunks = _MATH_CHUNK_RE.split(prepared_body)
        for chunk_index, chunk in enumerate(chunks):
            if not chunk:
                continue
            if _MATH_CHUNK_RE.fullmatch(chunk):
                rendered = _math_image(chunk)
                if line:
                    append_spacer()
                if rendered:
                    payload, width, height = rendered
                    append_atom("math", payload, width, height)
                    following = chunks[chunk_index + 1] if chunk_index + 1 < len(chunks) else ""
                    if following and not re.match(r"^\s*[,.;:!?)}\]]", following):
                        append_spacer()
                    continue
                math_text = _plain_math(chunk).strip()
                math_is_latin = bool(
                    re.fullmatch(
                        r"[\x20-\x7e⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻⁼⁽⁾₀₁₂₃₄₅₆₇₈₉₊₋₌₍₎"
                        r"≤≥≠×÷±∞θπ√Σ∴∈·→≈]+",
                        math_text,
                    )
                )
                math_kind = "latin" if math_is_latin else "text"
                math_width = (
                    self._latin_width(math_text, 10.35)
                    if math_is_latin
                    else self._text_width(math_text, 10.35)
                )
                append_atom(math_kind, math_text, math_width, 15.0)
                following = chunks[chunk_index + 1] if chunk_index + 1 < len(chunks) else ""
                if following and not re.match(r"^\s*[,.;:!?)}\]]", following):
                    append_spacer()
                continue
            plain = _plain_math(chunk)
            segments = plain.split("\n")
            for segment_index, segment in enumerate(segments):
                tokens = re.findall(
                    r"[\u3400-\u9fff]|\s+|[^\s\u3400-\u9fff]+",
                    segment,
                )
                for token in tokens:
                    if token.isspace():
                        if not line:
                            continue
                        token = " "
                    latin_token = bool(
                        re.fullmatch(
                            r"[\x20-\x7e⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻⁼⁽⁾₀₁₂₃₄₅₆₇₈₉₊₋₌₍₎"
                            r"≤≥≠×÷±∞θπ√Σ∴∈·→≈]+",
                            token,
                        )
                    )
                    kind = "latin" if latin_token else "text"
                    width = (
                        self._latin_width(token, 10.35)
                        if latin_token
                        else self._text_width(token, 10.35)
                    )
                    if token == " ":
                        # Some embedded font metric providers report a zero
                        # advance for a standalone space. Preserve a normal
                        # word gap explicitly so prose never collides with
                        # adjacent formulae in Safari or printed output.
                        width = max(width, 3.1)
                    append_atom(kind, token, width, 15.0)
                if segment_index < len(segments) - 1:
                    flush_line(paragraph_gap=not segment.strip())
        flush_line()
        if source_label:
            if self.y + 18 > self.bottom:
                new_continuation_page()
            self.page.insert_text(
                (self.margin_x, self.y + 8),
                source_label,
                fontname=self.font,
                fontsize=7.5,
                color=(0.46, 0.49, 0.56),
            )
            self.y += 26
        else:
            self.y += 12

    def finish(self) -> bytes:
        for page_number, page in enumerate(self.document, start=1):
            font = _font_name(page, self.lang)
            footer = f"Sumkora  ·  {page_number}"
            page.insert_text(
                (self.margin_x, page.rect.height - 20),
                footer,
                fontname=font,
                fontsize=7.5,
                color=(0.48, 0.51, 0.58),
            )
        payload = self.document.tobytes(garbage=3, deflate=True)
        self.document.close()
        return payload


def practice_pdf(student_id: int, set_id: int, kind: str, lang: str) -> bytes | None:
    detail = practice_set_detail(student_id, set_id)
    if not detail or kind not in {"questions", "answers"}:
        return None
    practice = detail["set"]
    if lang == "zh":
        title = "Sumkora 练习题" if kind == "questions" else "Sumkora 答案册"
        difficulty = {
            "mixed": "混合",
            "standard": "标准",
            "challenging": "挑战",
        }.get(practice["difficulty"], practice["difficulty"])
        calculator = {
            "any": "不限",
            "calculator": "可使用",
            "non-calculator": "不可使用",
        }.get(practice["calculator_policy"], practice["calculator_policy"])
        practice_title = (
            f"{topic_label('zh', practice['topic'])}专项练习"
            if practice.get("topic")
            else "综合练习"
        )
        subtitle = (
            f"{practice_title}  ·  共 {practice['actual_count']} 道题  ·  "
            f"难度：{difficulty}  ·  计算器：{calculator}"
        )
    else:
        title = "Sumkora worksheet" if kind == "questions" else "Sumkora answer booklet"
        subtitle = (
            f"{practice['title']}  ·  {practice['actual_count']} questions  ·  "
            f"{practice['difficulty']}  ·  {practice['calculator_policy']}"
        )
    flow = _PdfFlow(title=title, subtitle=subtitle, lang=lang)
    for item in detail["items"]:
        if practice.get("source_mode") == "generated":
            label = (
                f"第 {item['order_index']} 题  ·  {topic_label(lang, item['topic'])}"
                if lang == "zh"
                else f"Question {item['order_index']}  ·  {topic_label(lang, item['topic'])}"
            )
            # Generated worksheet and answer-booklet entries do not need a
            # repeated provenance footnote beneath every question.
            source = ""
            if kind == "questions":
                body = item["prompt_zh"] if lang == "zh" else item["prompt_en"]
            else:
                solution = (
                    item["solution_zh"] if lang == "zh" else item["solution_en"]
                )
                final_answer = (
                    item["final_answer_zh"]
                    if lang == "zh"
                    else item["final_answer_en"]
                )
                final_label = "最终答案" if lang == "zh" else "Final answer"
                body = f"{solution}\n\n{final_label}: {final_answer}"
            body = _clean_generated_practice_body(body)
            flow.add_rich_text(label=label, body=body, source_label=source)
            continue
        source = (
            f"{item['syllabus_code']} {item['examination_session']} "
            f"{item['year']} / {item['component']} / {item['question_number']}"
        )
        label = f"{item['order_index']}. Q{item['question_number']}"
        if kind == "questions":
            if flow.add_asset(
                item["question_asset_path"],
                label=label,
                source_label=source,
            ):
                continue
            flow.add_text(
                label=label,
                body=item["prompt_latex"] or item["prompt_text"],
                source_label=source,
            )
        else:
            if flow.add_asset(
                item["answer_asset_path"],
                label=label,
                source_label=source,
            ):
                continue
            answer = item["answer_text"] or item["raw_source_text"] or (
                "Answer unavailable." if lang == "en" else "暂无答案。"
            )
            flow.add_text(
                label=label,
                body=f"{answer}\n\nSource: {source}",
                source_label=source,
            )
    return flow.finish()


def _fallback_worked_solution(item: dict, lang: str) -> str:
    """Keep the answer PDF useful if the tutoring model is unavailable."""
    if lang == "zh":
        rationale = item.get("ai_rationale_zh")
        guidance = item.get("error_mechanism_zh")
        heading = "解题过程"
    else:
        rationale = item.get("ai_rationale")
        guidance = item.get("error_mechanism")
        heading = "Worked process"
    parts = [f"{heading}:"]
    if rationale:
        parts.append(str(rationale).strip())
    if guidance and str(guidance).strip() != str(rationale or "").strip():
        parts.append(str(guidance).strip())
    if len(parts) == 1:
        parts.append(
            "请根据题目中的已知量列式，并逐步化简至最终答案。"
            if lang == "zh"
            else "Set up the mathematics from the given information, then "
            "simplify each step to the final answer."
        )
    return "\n\n".join(parts)


def prepare_mistake_worked_solutions(
    items: list[dict], curriculum: dict | None = None
) -> None:
    """Generate and cache worked solutions without changing assessment results."""
    pending = [
        item
        for item in items
        if int(item.get("id") or 0) > 0
        and not (
            str(item.get("worked_solution_en") or "").strip()
            and str(item.get("worked_solution_zh") or "").strip()
        )
        and str(item.get("complete_question_text") or "").strip()
    ]
    if not pending:
        return

    import config

    if not config.CXSEE_API_KEY:
        return
    from question_solver import solve_question_texts

    batches = [pending[index:index + 8] for index in range(0, len(pending), 8)]

    def generate(batch: list[dict]) -> dict:
        return solve_question_texts(
            [
                {
                    "id": int(item["id"]),
                    "question": item["complete_question_text"],
                    "reference_answer": (
                        item.get("answer_text")
                        or item.get("mark_scheme_text")
                        or ""
                    ),
                }
                for item in batch
            ],
            curriculum=curriculum,
        )

    generated: list[dict] = []
    model_by_id: dict[int, str] = {}
    with ThreadPoolExecutor(max_workers=min(3, len(batches))) as pool:
        futures = {pool.submit(generate, batch): batch for batch in batches}
        for future in as_completed(futures):
            try:
                result = future.result()
            except Exception:
                continue
            model = str(result.get("model") or "")
            for solution in result.get("solutions") or []:
                generated.append(solution)
                model_by_id[int(solution["id"])] = model

    by_id = {int(item["id"]): item for item in items}
    for solution in generated:
        entry_id = int(solution["id"])
        solution_en = str(solution.get("solution_en") or "").strip()
        solution_zh = str(solution.get("solution_zh") or "").strip()
        if not solution_en and not solution_zh:
            continue
        execute(
            """
            UPDATE mistake_book_entries
            SET worked_solution_en = ?, worked_solution_zh = ?,
                worked_solution_model = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                solution_en,
                solution_zh,
                model_by_id.get(entry_id, ""),
                _now(),
                entry_id,
            ),
        )
        if entry_id in by_id:
            by_id[entry_id]["worked_solution_en"] = solution_en
            by_id[entry_id]["worked_solution_zh"] = solution_zh
            by_id[entry_id]["worked_solution_model"] = model_by_id.get(entry_id, "")


def _recover_mistake_from_source(item: dict, curriculum: dict) -> bool:
    """Recover one full printed question and solution from its cited page."""
    path = str(item.get("answer_script_path") or "")
    if not path or not os.path.isfile(path):
        return False

    try:
        with fitz.open(path) as document:
            if not document.page_count:
                return False
            page_number = max(1, int(item.get("source_page") or 1))
            page = document.load_page(min(page_number - 1, document.page_count - 1))
            # The previous 160-DPI lossless PNG regularly exceeded the
            # provider proxy's upload window in production.  A full A4 page
            # was several megabytes after base64 encoding, which caused
            # ``write operation timed out`` before the model even saw it.
            # A 120-DPI JPEG is still comfortably readable for printed maths
            # and handwriting, while typically being 8-15x smaller.
            scale = 120 / 72
            image_bytes = page.get_pixmap(
                matrix=fitz.Matrix(scale, scale),
                alpha=False,
            ).tobytes("jpeg", jpg_quality=82)

        from question_solver import transcribe_question_image_bytes

        # A foreground card may arrive while the post-analysis warmer occupies
        # all three slots.  Wait briefly for the fast OCR call instead of
        # incorrectly declaring the question unavailable after one second.
        acquired = _MISTAKE_RECOVERY_SEMAPHORE.acquire(timeout=8.0)
        if not acquired:
            return False
        try:
            result = transcribe_question_image_bytes(
                image_bytes,
                mime_type="image/jpeg",
                target_label=str(item.get("question_label") or ""),
                timeout_seconds=min(
                    18, config.MISTAKE_RECOVERY_TIMEOUT_SECONDS
                ),
            )
        finally:
            _MISTAKE_RECOVERY_SEMAPHORE.release()
    except Exception as exc:
        print(
            "Mistake question recovery failed "
            f"for entry {item.get('id')}: {type(exc).__name__}: "
            f"{str(exc)[:180]}",
            flush=True,
        )
        return False

    question_text = str(result.get("transcription") or "").strip()
    question_latex = str(
        result.get("question_latex") or question_text
    ).strip()
    substantive = question_latex or question_text
    if not _is_substantive_question_text(
        str(item.get("question_label") or ""), substantive
    ):
        return False

    execute(
        """
        UPDATE analysis_question_results
        SET question_text = ?, question_latex = ?
        WHERE id = ?
        """,
        (question_text, question_latex, item["question_result_id"]),
    )
    execute(
        """
        UPDATE mistake_book_entries
        SET worked_solution_en = '', worked_solution_zh = '',
            worked_solution_model = '', updated_at = ?
        WHERE id = ?
        """,
        (_now(), item["id"]),
    )
    item.update(
        {
            "question_text": question_text,
            "question_latex": question_latex,
            "complete_question_text": question_latex or question_text,
            "needs_question_recovery": False,
            "worked_solution_en": "",
            "worked_solution_zh": "",
            "worked_solution_model": "",
        }
    )
    return True


def _mistake_recovery_payload(item: dict, lang: str) -> dict:
    solution = (
        item.get("worked_solution_zh")
        if lang == "zh"
        else item.get("worked_solution_en")
    ) or _fallback_worked_solution(item, lang)
    return {
        "id": int(item["id"]),
        "ok": not item.get("needs_question_recovery"),
        "question": str(item.get("complete_question_text") or "").strip(),
        "solution": str(solution or "").strip(),
        "model": item.get("worked_solution_model") or "",
    }


def prepare_mistake_recovery_batch(
    student_id: int,
    *,
    lang: str = "en",
    entry_ids: list[int] | None = None,
    analysis_version_id: int | None = None,
    limit: int = 3,
) -> list[dict]:
    """Recover a small visible batch and permanently cache every success.

    The browser calls this once for the first three incomplete cards instead
    of starting one request for every item in a large Mistake Book.  Parallel
    calls use compressed page images and each has a hard provider timeout, so
    the whole visible batch stays within the interaction budget.
    """
    data = mistake_book(student_id)
    allowed_ids = {int(value) for value in (entry_ids or []) if int(value) > 0}
    pending = [
        item
        for item in data["items"]
        if int(item.get("id") or 0) > 0
        and item.get("needs_question_recovery")
        and (not allowed_ids or int(item["id"]) in allowed_ids)
        and (
            analysis_version_id is None
            or int(item.get("analysis_version_id") or 0) == analysis_version_id
        )
    ][: max(0, min(int(limit), 3))]
    if not pending:
        return []

    curriculum = _student_curriculum(student_id)
    workers = min(3, len(pending))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(_recover_mistake_from_source, item, curriculum): item
            for item in pending
        }
        for future, item in futures.items():
            try:
                future.result()
            except Exception as exc:
                print(
                    "Mistake recovery batch item failed "
                    f"for entry {item.get('id')}: {type(exc).__name__}: "
                    f"{str(exc)[:180]}",
                    flush=True,
                )
    return [_mistake_recovery_payload(item, lang) for item in pending]


def warm_analysis_mistakes(student_id: int, analysis_version_id: int) -> None:
    """Prepare every new mistake and atomically refresh all PDF booklets."""
    # One retry pass handles a transient provider failure without making any
    # individual call exceed its 28-second hard ceiling.
    for _attempt in range(2):
        data = mistake_book(student_id)
        pending_ids = [
            int(item["id"])
            for item in data["items"]
            if int(item.get("id") or 0) > 0
            and item.get("needs_question_recovery")
            and int(item.get("analysis_version_id") or 0) == analysis_version_id
        ]
        if not pending_ids:
            break
        for index in range(0, len(pending_ids), 3):
            prepare_mistake_recovery_batch(
                student_id,
                entry_ids=pending_ids[index:index + 3],
                analysis_version_id=analysis_version_id,
                limit=3,
            )

    refreshed = mistake_book(student_id)
    new_items = [
        item
        for item in refreshed["items"]
        if int(item.get("analysis_version_id") or 0) == analysis_version_id
        and not item.get("needs_question_recovery")
    ]
    prepare_mistake_worked_solutions(
        new_items, curriculum=_student_curriculum(student_id)
    )
    refresh_mistake_book_pdf_cache(student_id)


def mistake_worked_solution(
    student_id: int,
    entry_id: int,
    lang: str,
) -> dict | None:
    """Return one owned mistake's cached or freshly generated worked solution."""
    data = mistake_book(student_id)
    item = next(
        (row for row in data["items"] if int(row.get("id") or 0) == entry_id),
        None,
    )
    if not item:
        return None
    cache_changed = bool(
        item.get("needs_question_recovery")
        or not item.get("worked_solution_en")
        or not item.get("worked_solution_zh")
    )
    if item.get("needs_question_recovery"):
        recovered = _recover_mistake_from_source(
            item, _student_curriculum(student_id)
        )
        if not recovered:
            return None
    prepare_mistake_worked_solutions(
        [item], curriculum=_student_curriculum(student_id)
    )
    solution = (
        item.get("worked_solution_zh")
        if lang == "zh"
        else item.get("worked_solution_en")
    ) or _fallback_worked_solution(item, lang)
    if cache_changed:
        refresh_mistake_book_pdfs_in_background(student_id)
    return {
        "question": str(item.get("complete_question_text") or "").strip(),
        "solution": str(solution).strip(),
        "model": item.get("worked_solution_model") or "",
    }


def mistake_book_pdf(
    student_id: int,
    kind: str,
    lang: str,
    *,
    allow_ai: bool = True,
) -> bytes:
    data = mistake_book(student_id)
    curriculum = _student_curriculum(student_id)
    if allow_ai:
        for item in data["items"]:
            if item.get("needs_question_recovery"):
                _recover_mistake_from_source(item, curriculum)
    is_questions = kind == "questions"
    if not is_questions and allow_ai:
        prepare_mistake_worked_solutions(data["items"], curriculum=curriculum)
    if lang == "zh":
        title = "Sumkora 错题本" if is_questions else "Sumkora 错题答案"
        subtitle = (
            "本册包含尚未完全掌握的题目。请重新作答，并写出完整过程。"
            if is_questions
            else "每道题均提供完整的分步解题过程和最终答案。"
        )
    else:
        title = "Sumkora Mistake Book" if is_questions else "Sumkora Worked Solutions"
        subtitle = (
            "Retry these questions and show complete working."
            if is_questions
            else "A step-by-step worked solution and final answer for every question."
        )
    item_count = len(data["items"])
    count_text = (
        f"共 {item_count} 道题"
        if lang == "zh"
        else f"{item_count} {'question' if item_count == 1 else 'questions'}"
    )
    flow = _PdfFlow(title=title, subtitle=f"{count_text}  ·  {subtitle}", lang=lang)
    for index, item in enumerate(data["items"], start=1):
        heading = f"{index}. {item['paper_title']} - {item['question_label']}"
        unavailable = "暂无题目文本。" if lang == "zh" else "Question text unavailable."
        question = item["complete_question_text"] or unavailable
        question_label = str(item.get("question_label") or "").strip()
        if question_label:
            question = re.sub(
                rf"^\s*{re.escape(question_label)}\s*(?:[-:—]\s*)?",
                "",
                str(question),
                count=1,
                flags=re.IGNORECASE,
            ).strip() or question
        # Both booklets are deliberately text-first. Source-page screenshots
        # remain available in the interactive Mistake Book, while printable
        # pages use the reconstructed question so mathematics can be rendered
        # cleanly and spacing remains consistent.
        flow.add_rich_text(label=heading, body=question, source_label="")
        if not is_questions:
            solution = (
                item.get("worked_solution_zh")
                if lang == "zh"
                else item.get("worked_solution_en")
            ) or _fallback_worked_solution(item, lang)
            solution_heading = "完整解答" if lang == "zh" else "Worked solution"
            flow.add_rich_text(
                label=solution_heading,
                body=solution,
                source_label="",
            )
    return flow.finish()


def _mistake_pdf_cache_path(student_id: int, kind: str, lang: str) -> Path:
    root = Path(config.DB_PATH).resolve().parent / "generated" / "mistake-books"
    return root / str(student_id) / f"{kind}-{lang}.pdf"


def refresh_mistake_book_pdf_cache(
    student_id: int,
    *,
    languages: tuple[str, ...] = ("en", "zh"),
) -> None:
    """Atomically replace cached question and answer booklets."""
    with _MISTAKE_PDF_LOCK:
        for lang in languages:
            for kind in ("questions", "answers"):
                content = mistake_book_pdf(
                    student_id, kind, lang, allow_ai=False
                )
                path = _mistake_pdf_cache_path(student_id, kind, lang)
                path.parent.mkdir(parents=True, exist_ok=True)
                temporary = path.with_suffix(".pdf.tmp")
                temporary.write_bytes(content)
                temporary.replace(path)


def cached_mistake_book_pdf(student_id: int, kind: str, lang: str) -> bytes:
    """Return an instant cached booklet, creating a non-AI snapshot if absent."""
    path = _mistake_pdf_cache_path(student_id, kind, lang)
    if path.is_file():
        return path.read_bytes()
    with _MISTAKE_PDF_LOCK:
        if path.is_file():
            return path.read_bytes()
        content = mistake_book_pdf(student_id, kind, lang, allow_ai=False)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".pdf.tmp")
        temporary.write_bytes(content)
        temporary.replace(path)
        return content


def refresh_mistake_book_pdfs_in_background(student_id: int) -> None:
    """Refresh download caches after a manual legacy-item recovery."""
    Thread(
        target=refresh_mistake_book_pdf_cache,
        args=(student_id,),
        name=f"mistake-pdf-refresh-{student_id}",
        daemon=True,
    ).start()
