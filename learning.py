"""Student progress, mistake-book, and targeted-practice services."""

from __future__ import annotations

import json
import os
import re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

import fitz

from db import execute, query_all, query_one


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _json(value, fallback):
    try:
        return json.loads(value or "")
    except (TypeError, ValueError, json.JSONDecodeError):
        return fallback


def _display_skill(value: str) -> str:
    return (value or "Unclassified").replace("_", " ").strip()


def skill_url(skill: str) -> str:
    return f"/student/skills/detail?skill={quote(skill or '', safe='')}"


def skill_detail(student_id: int, skill: str) -> dict | None:
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
               aqr.question_label, aqr.question_text, aqr.ai_rationale,
               aqr.ai_rationale_zh, aqr.assessment_status,
               aqr.paper_question_id
        FROM analysis_skill_observations aso
        JOIN student_papers sp ON sp.id = aso.paper_id
        JOIN paper_analysis_versions pav ON pav.id = aso.analysis_version_id
        JOIN analysis_question_results aqr ON aqr.id = aso.question_result_id
        WHERE aso.student_id = ? AND aso.is_current = 1
          AND lower(aso.skill) = lower(?)
        ORDER BY aso.observed_at, aso.id
        """,
        (student_id, skill),
    )
    legacy = query_all(
        """
        SELECT so.*, a.title AS paper_title, s.id AS source_id,
               s.uploaded_at AS paper_date, 'detailed' AS assessment_mode,
               q.label AS question_label, q.question_text,
               gd.ai_notes AS ai_rationale, '' AS ai_rationale_zh,
               'graded' AS assessment_status, NULL AS paper_question_id
        FROM skill_observations so
        JOIN submissions s ON s.id = so.submission_id
        JOIN assignments a ON a.id = s.assignment_id
        LEFT JOIN questions q ON q.id = so.question_id
        LEFT JOIN grade_drafts gd
          ON gd.submission_id = s.id AND gd.question_id = q.id
        WHERE so.student_id = ? AND lower(so.skill) = lower(?)
        ORDER BY so.observed_at, so.id
        """,
        (student_id, skill),
    )
    rows = [dict(row) for row in observations] + [dict(row) for row in legacy]
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
                "question_text": row["question_text"],
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
        "skill": state["skill"] if state else skill,
        "display_skill": _display_skill(state["skill"] if state else skill),
        "topic": state["topic"] if state else (rows[-1]["topic"] if rows else ""),
        "state": dict(state) if state else None,
        "papers": trend,
        "paper_count": len(trend),
    }


def sync_mistake_book(student_id: int) -> int:
    """Materialize current lost-mark results without duplicating entries."""
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
          AND pav.version_number = sp.latest_version_number
          AND pav.status = 'completed'
        """,
        (student_id,),
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


def mistake_book(
    student_id: int,
    *,
    topic: str = "",
    status: str = "",
) -> dict:
    sync_mistake_book(student_id)
    rows = query_all(
        """
        SELECT mbe.*, aqr.question_label, aqr.question_text,
               aqr.maximum_marks, aqr.awarded_mark, aqr.ai_mark,
               aqr.ai_rationale, aqr.ai_rationale_zh,
               aqr.mark_scheme_text, aqr.topic, aqr.skill,
               aqr.error_category, aqr.error_mechanism,
               aqr.error_mechanism_zh, aqr.assessment_status,
               sp.id AS paper_id, sp.title AS paper_title,
               sp.updated_at AS paper_date, pav.assessment_mode,
               pq.question_asset_path, pq.answer_asset_path,
               pq.answer_text, pq.source_key
        FROM mistake_book_entries mbe
        JOIN analysis_question_results aqr
          ON aqr.id = mbe.analysis_question_result_id
        JOIN paper_analysis_versions pav ON pav.id = aqr.analysis_version_id
        JOIN student_papers sp ON sp.id = pav.paper_id
        LEFT JOIN paper_questions pq ON pq.id = mbe.paper_question_id
        WHERE mbe.student_id = ?
        ORDER BY sp.updated_at DESC, aqr.id
        """,
        (student_id,),
    )
    items = []
    topics = set()
    for raw in rows:
        item = dict(raw)
        topics.add(item["topic"] or "Unclassified")
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
        items.append(item)
    return {
        "items": items,
        "topics": sorted(topics),
        "selected_topic": topic,
        "selected_status": status,
        "counts": {
            "total": len(rows),
            "not_retried": sum(row["status"] == "not_retried" for row in rows),
            "improving": sum(row["status"] == "improving" for row in rows),
            "mastered": sum(row["status"] == "mastered" for row in rows),
        },
    }


def update_mistake_status(student_id: int, entry_id: int, status: str) -> bool:
    if status not in {"not_retried", "improving", "mastered"}:
        return False
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
          AND (pq.question_asset_path IS NOT NULL OR pq.prompt_text != '')
        ORDER BY pp.year DESC, pp.component, pq.order_index
        """
    )
    result = []
    for row in rows:
        item = dict(row)
        item["skill_list"] = [
            str(value).lower() for value in _json(item["skills"], [])
        ]
        result.append(item)
    return result


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
    states = [
        dict(row)
        for row in query_all(
            """
            SELECT * FROM student_skill_states
            WHERE student_id = ?
            ORDER BY current_estimate, evidence_count DESC
            """,
            (student_id,),
        )
    ]
    weak_topics = [row["topic"].lower() for row in states[:4]]
    weak_skills = [row["skill"].lower() for row in states[:8]]
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
        item_topic = (item["topic"] or "").lower()
        item_skills = item["skill_list"]
        score = 0
        reason = "Mixed revision"
        if selection_mode == "topic":
            if not topic or item_topic != topic.lower():
                continue
            score = 100
            reason = f"Selected topic: {topic}"
        elif selection_mode == "mistakes":
            if item["id"] not in mistake_question_ids:
                continue
            score = 120
            reason = "Retry an earlier mistake"
        elif selection_mode == "weaknesses":
            if item_topic in weak_topics:
                score += 80 - 5 * weak_topics.index(item_topic)
                reason = f"Current priority: {item['topic']}"
            overlap = [skill for skill in item_skills if skill in weak_skills]
            if overlap:
                score += 50
                reason = f"Current priority: {overlap[0]}"
            if not states:
                score += 10
                reason = "Build initial evidence"
        else:
            score = 20
        if item["id"] in recent:
            score -= 35
        score += min(int(item["year"] or 0) - 2020, 10)
        scored.append((score, item["id"], item, reason))

    scored.sort(key=lambda value: (-value[0], value[1]))
    selected = scored[:count]
    now = _now()
    title_en = {
        "weaknesses": "Targeted weakness practice",
        "topic": f"{topic or 'Topic'} practice",
        "mixed": "Mixed revision worksheet",
        "mistakes": "Mistake retry worksheet",
    }[selection_mode]
    title_zh = {
        "weaknesses": "薄弱项针对练习",
        "topic": f"{topic or '专题'}练习",
        "mixed": "综合复习练习",
        "mistakes": "错题重练",
    }[selection_mode]
    explanation_en = (
        f"Selected {len(selected)} non-repeating questions from the approved "
        f"question bank for {title_en.lower()}."
    )
    explanation_zh = (
        f"已从审核通过的题库中选择 {len(selected)} 道不重复题目，用于{title_zh}。"
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


def practice_sets(student_id: int) -> list[dict]:
    return [
        dict(row)
        for row in query_all(
            """
            SELECT * FROM practice_sets
            WHERE student_id = ?
            ORDER BY created_at DESC
            """,
            (student_id,),
        )
    ]


def practice_set_detail(student_id: int, set_id: int) -> dict | None:
    practice = query_one(
        "SELECT * FROM practice_sets WHERE id = ? AND student_id = ?",
        (set_id, student_id),
    )
    if not practice:
        return None
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


def _font_name(page: fitz.Page, lang: str) -> str:
    if lang != "zh":
        return "helv"
    global _CJK_FONT_BUFFER
    if _CJK_FONT_BUFFER is None:
        _CJK_FONT_BUFFER = fitz.Font(fontname="china-s").buffer
    font_name = "sumkoracjk"
    page.insert_font(fontname=font_name, fontbuffer=_CJK_FONT_BUFFER)
    return font_name


def _text_page(
    document: fitz.Document,
    *,
    title: str,
    body: str,
    lang: str,
    footer: str = "Sumkora",
) -> None:
    page = document.new_page(width=fitz.paper_rect("a4").width, height=fitz.paper_rect("a4").height)
    font = _font_name(page, lang)
    page.insert_textbox(
        fitz.Rect(54, 48, page.rect.width - 54, 94),
        title,
        fontname=font,
        fontsize=17,
        color=(0.12, 0.11, 0.29),
    )
    page.insert_textbox(
        fitz.Rect(54, 108, page.rect.width - 54, page.rect.height - 58),
        body,
        fontname=font,
        fontsize=10.5,
        lineheight=1.35,
        color=(0.15, 0.18, 0.25),
    )
    page.insert_text(
        (54, page.rect.height - 28),
        footer,
        fontname=font,
        fontsize=8,
        color=(0.4, 0.45, 0.55),
    )


def _append_asset(target: fitz.Document, path: str | None) -> bool:
    if not path or not os.path.isfile(path):
        return False
    try:
        with fitz.open(path) as source:
            target.insert_pdf(source)
        return True
    except (fitz.FileDataError, RuntimeError):
        return False


def practice_pdf(student_id: int, set_id: int, kind: str, lang: str) -> bytes | None:
    detail = practice_set_detail(student_id, set_id)
    if not detail or kind not in {"questions", "answers"}:
        return None
    practice = detail["set"]
    target = fitz.open()
    if lang == "zh":
        cover_title = "Sumkora 练习题" if kind == "questions" else "Sumkora 答案册"
        cover_body = (
            f"{practice['title']}\n\n共 {practice['actual_count']} 道题\n"
            f"难度：{practice['difficulty']}\n"
            f"计算器：{practice['calculator_policy']}\n\n"
            + (
                "请写出完整过程。答案请查看单独的答案册。"
                if kind == "questions"
                else "每道题均列出来源和评分要点。"
            )
        )
    else:
        cover_title = "Sumkora worksheet" if kind == "questions" else "Sumkora answer booklet"
        cover_body = (
            f"{practice['title']}\n\n{practice['actual_count']} questions\n"
            f"Difficulty: {practice['difficulty']}\n"
            f"Calculator: {practice['calculator_policy']}\n\n"
            + (
                "Show complete working. Answers are provided in the separate answer booklet."
                if kind == "questions"
                else "Each item includes its source and marking guidance."
            )
        )
    _text_page(target, title=cover_title, body=cover_body, lang=lang)
    for item in detail["items"]:
        source = (
            f"{item['syllabus_code']} {item['examination_session']} "
            f"{item['year']} / {item['component']} / {item['question_number']}"
        )
        if kind == "questions":
            if _append_asset(target, item["question_asset_path"]):
                continue
            body = f"{item['prompt_text']}\n\n\n\n\n\n\n\n\n\nSource: {source}"
            _text_page(
                target,
                title=f"{item['order_index']}. {item['question_number']}",
                body=body,
                lang=lang,
            )
        else:
            if _append_asset(target, item["answer_asset_path"]):
                continue
            answer = item["answer_text"] or item["raw_source_text"] or (
                "Answer unavailable." if lang == "en" else "暂无答案。"
            )
            _text_page(
                target,
                title=f"{item['order_index']}. {item['question_number']}",
                body=f"{answer}\n\nSource: {source}",
                lang=lang,
            )
    payload = target.tobytes(garbage=3, deflate=True)
    target.close()
    return payload


def mistake_book_pdf(student_id: int, kind: str, lang: str) -> bytes:
    data = mistake_book(student_id)
    target = fitz.open()
    is_questions = kind == "questions"
    if lang == "zh":
        title = "Sumkora 错题本" if is_questions else "Sumkora 错题答案"
        intro = (
            "本册包含尚未完全掌握的题目。请重新作答，并写出完整过程。"
            if is_questions
            else "本册包含对应的答案、评分依据和改进建议。"
        )
    else:
        title = "Sumkora Mistake Book" if is_questions else "Sumkora Mistake Book Answers"
        intro = (
            "Retry these questions and show complete working."
            if is_questions
            else "Answers, marking evidence, and improvement guidance."
        )
    count_text = (
        f"共 {len(data['items'])} 道题"
        if lang == "zh"
        else f"{len(data['items'])} questions"
    )
    _text_page(target, title=title, body=f"{intro}\n\n{count_text}", lang=lang)
    for index, item in enumerate(data["items"], start=1):
        if is_questions and _append_asset(target, item["question_asset_path"]):
            continue
        if not is_questions and _append_asset(target, item["answer_asset_path"]):
            continue
        heading = f"{index}. {item['paper_title']} - {item['question_label']}"
        if is_questions:
            unavailable = "暂无题目文本。" if lang == "zh" else "Question text unavailable."
            body = (
                f"{item['question_text'] or unavailable}"
                "\n\n\n\n\n\n\n\n\n\n"
            )
        else:
            rationale = (
                item["error_mechanism_zh"] or item["ai_rationale_zh"]
                if lang == "zh"
                else item["error_mechanism"] or item["ai_rationale"]
            )
            answer = item["answer_text"] or item["mark_scheme_text"]
            body = (
                f"{'答案' if lang == 'zh' else 'Answer'}: "
                f"{answer or rationale}\n\n"
                f"{'反馈' if lang == 'zh' else 'Feedback'}: {rationale}"
            )
        _text_page(target, title=heading, body=body, lang=lang)
    payload = target.tobytes(garbage=3, deflate=True)
    target.close()
    return payload
