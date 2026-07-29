import hashlib
import json
import math
import os
from collections import defaultdict
from datetime import datetime, timezone
from typing import Iterable

from db import execute, query_all, query_one
from taxonomy import (
    CORE_0606_TOPICS,
    GENERAL_MATH_TOPICS,
    canonical_skill,
    canonical_topic,
)


RECENCY_HALF_LIFE_DAYS = 25.0
CALCULATION_VERSION = "beta-recency-25d-v3"
TAXONOMY_VERSION = "0606-v1"

CORE_0606_SKILLS = [
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


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _json(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _flags(raw: str) -> list[str]:
    try:
        value = json.loads(raw or "[]")
        return value if isinstance(value, list) else [str(value)]
    except json.JSONDecodeError:
        return [raw] if raw else []


def _error_diagnosis(earned: float, available: float, notes: str, flags: list[str]):
    if earned >= available:
        return None, None
    lower = (notes or "").lower()
    flag_set = set(flags)
    if {"model_error", "no_readable_text", "no_ocr_text"} & flag_set:
        return "unreadable or uncertain work", "insufficient readable evidence"
    if "label_not_found" in flag_set:
        return "omission", "response could not be mapped to the question"
    if "answer_mismatch" in flag_set or "did not match" in lower:
        return "procedural execution", "final answer did not match the required result"
    if "unsafe_exact_match_multi_mark" in flag_set:
        return "missing justification", "answer present without enough verified method evidence"
    if earned <= 0:
        return "method selection", "required criterion not demonstrated in available evidence"
    return "procedural execution", "method was only partially completed"


def _legacy_criterion(question) -> int:
    existing = query_one(
        """
        SELECT id FROM marking_criteria
        WHERE legacy_question_id = ? AND is_active = 1
        ORDER BY version DESC, order_index
        LIMIT 1
        """,
        (question["id"],),
    )
    if existing:
        return existing["id"]
    return execute(
        """
        INSERT INTO marking_criteria
        (legacy_question_id, criterion_code, mark_type, marks, description,
         raw_mark_scheme_text, source_page, source_confidence, order_index)
        VALUES (?, ?, 'TOTAL', ?, ?, ?, ?, 0.5, 0)
        """,
        (
            question["id"],
            f"{question['label']}-TOTAL",
            float(question["max_marks"]),
            "Legacy whole-question decision; requires criterion-level paper-pack parsing.",
            question["mark_scheme_text"] or "",
            question["page_number"],
        ),
    )


def _submission_rows(submission_id: int):
    return query_all(
        """
        SELECT gd.*, q.id AS question_id, q.label, q.topic, q.subtopic,
               q.assessment_objective, q.max_marks, q.mark_scheme_text,
               q.page_number, q.calculator_allowed,
               s.student_id, s.uploaded_at, s.file_path,
               a.paper_pack_id, a.calculator_policy, a.paper_component
        FROM grade_drafts gd
        JOIN questions q ON q.id = gd.question_id
        JOIN submissions s ON s.id = gd.submission_id
        JOIN assignments a ON a.id = s.assignment_id
        WHERE gd.submission_id = ?
        ORDER BY q.order_index
        """,
        (submission_id,),
    )


def sync_submission_evidence(submission_id: int) -> dict:
    rows = _submission_rows(submission_id)
    if not rows:
        return {"submission_id": submission_id, "observations": 0}

    confirmed = 0.0
    provisional = 0.0
    possible = 0.0
    affected_students = set()
    observation_count = 0

    for row in rows:
        question = {
            "id": row["question_id"],
            "label": row["label"],
            "max_marks": row["max_marks"],
            "mark_scheme_text": row["mark_scheme_text"],
            "page_number": row["page_number"],
        }
        criterion_id = _legacy_criterion(question)
        available = float(row["max_marks"] or 0)
        awarded = float(row["final_mark"] if row["final_mark"] is not None else row["ai_mark"] or 0)
        confidence = float(row["ai_confidence"] or 0.5)
        flags = _flags(row["risk_flags"])
        uncertain = bool(row["needs_exception_review"] or confidence < 0.65)
        decision = "uncertain" if uncertain else ("awarded" if awarded else "not_awarded")
        evidence = row["ai_notes"] or row["teacher_comment"] or ""
        warning_flags = list(flags)
        if "legacy_whole_question" not in warning_flags:
            warning_flags.append("legacy_whole_question")

        current = query_one(
            """
            SELECT id FROM criterion_decisions
            WHERE submission_id = ? AND criterion_id = ? AND is_current = 1
            ORDER BY id DESC LIMIT 1
            """,
            (submission_id, criterion_id),
        )
        params = (
            awarded,
            available,
            decision,
            evidence,
            row["page_number"],
            evidence,
            confidence,
            "Uncertain decision; owner review recommended." if uncertain else "",
            "cxsee" if (row["ai_notes"] or "").startswith("CXSee") else "legacy",
            "legacy-question-grader",
            "legacy-adapter-v1",
            _json(warning_flags),
            _now(),
        )
        if current:
            execute(
                """
                UPDATE criterion_decisions
                SET awarded_marks = ?, available_marks = ?, decision = ?,
                    evidence_text = ?, evidence_page = ?, rationale = ?,
                    confidence = ?, ambiguity = ?, provider = ?, model = ?,
                    prompt_version = ?, warning_flags = ?, created_at = ?
                WHERE id = ?
                """,
                (*params, current["id"]),
            )
            decision_id = current["id"]
        else:
            decision_id = execute(
                """
                INSERT INTO criterion_decisions
                (submission_id, question_id, criterion_id, awarded_marks,
                 available_marks, decision, evidence_text, evidence_page,
                 rationale, confidence, extraction_confidence, ambiguity,
                 provider, model, prompt_version, warning_flags, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0.5, ?, ?, ?, ?, ?, ?)
                """,
                (submission_id, row["question_id"], criterion_id, *params),
            )

        if uncertain:
            possible += available
        else:
            confirmed += awarded
            possible += awarded
        provisional += awarded

        category, mechanism = _error_diagnosis(awarded, available, evidence, flags)
        skill = (
            row["subtopic"]
            or row["assessment_objective"]
            or row["topic"]
            or "unclassified"
        )
        extraction_confidence = 0.5
        ocr = query_one(
            """
            SELECT confidence, status FROM ocr_pages
            WHERE submission_id = ? AND page_number = ?
            ORDER BY updated_at DESC LIMIT 1
            """,
            (submission_id, row["page_number"]),
        )
        if ocr:
            extraction_confidence = (
                float(ocr["confidence"])
                if ocr["confidence"] is not None
                else (0.65 if ocr["status"] == "done" else 0.25)
            )
        weight = max(available, 1.0) * max(confidence, 0.1) * max(extraction_confidence, 0.1)
        success = awarded / available if available else 0.0
        existing_observation = query_one(
            """
            SELECT id FROM skill_observations
            WHERE submission_id = ? AND question_id = ? AND skill = ?
            """,
            (submission_id, row["question_id"], skill),
        )
        observation_values = (
            row["student_id"],
            row["paper_pack_id"],
            submission_id,
            row["question_id"],
            decision_id,
            row["uploaded_at"],
            row["topic"] or "Unclassified",
            row["subtopic"] or "",
            skill,
            awarded,
            available,
            success,
            confidence,
            extraction_confidence,
            row["calculator_policy"] or (
                "calculator" if row["calculator_allowed"] else "unknown"
            ),
            category,
            mechanism,
            weight,
        )
        if existing_observation:
            execute(
                """
                UPDATE skill_observations
                SET student_id = ?, paper_pack_id = ?, submission_id = ?,
                    question_id = ?, criterion_decision_id = ?, observed_at = ?,
                    topic = ?, subtopic = ?, skill = ?, marks_earned = ?,
                    marks_available = ?, success_fraction = ?,
                    grading_confidence = ?, extraction_confidence = ?,
                    calculator_policy = ?, error_category = ?,
                    error_mechanism = ?, evidence_weight = ?,
                    model_version = 'legacy-adapter-v1'
                WHERE id = ?
                """,
                (*observation_values, existing_observation["id"]),
            )
        else:
            execute(
                """
                INSERT INTO skill_observations
                (student_id, paper_pack_id, submission_id, question_id,
                 criterion_decision_id, observed_at, topic, subtopic, skill,
                 marks_earned, marks_available, success_fraction,
                 grading_confidence, extraction_confidence, calculator_policy,
                 error_category, error_mechanism, evidence_weight, model_version)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                        'legacy-adapter-v1')
                """,
                observation_values,
            )
        affected_students.add(row["student_id"])
        observation_count += 1

    execute(
        """
        UPDATE submissions
        SET confirmed_min_score = ?, provisional_score = ?, possible_max_score = ?
        WHERE id = ?
        """,
        (round(confirmed, 2), round(provisional, 2), round(possible, 2), submission_id),
    )
    for student_id in affected_students:
        rebuild_student_profile(student_id)
    return {
        "submission_id": submission_id,
        "observations": observation_count,
        "confirmed_min": round(confirmed, 2),
        "provisional": round(provisional, 2),
        "possible_max": round(possible, 2),
    }


def _parse_date(value: str) -> datetime:
    try:
        return datetime.fromisoformat((value or "").replace("Z", "+00:00")).replace(
            tzinfo=timezone.utc
        )
    except ValueError:
        return datetime.now(timezone.utc)


def _state_for_observations(rows: Iterable) -> dict:
    observations = list(rows)
    now = datetime.now(timezone.utc)
    all_alpha = all_beta = 1.0
    current_alpha = current_beta = 1.0
    papers = set()
    failures = []
    successes = []
    for index, row in enumerate(observations):
        success = max(0.0, min(1.0, float(row["success_fraction"])))
        weight = max(0.1, float(row["evidence_weight"] or 1))
        all_alpha += success * weight
        all_beta += (1 - success) * weight
        age_days = max(0.0, (now - _parse_date(row["observed_at"])).total_seconds() / 86400)
        recency = math.exp(
            -math.log(2) * age_days / RECENCY_HALF_LIFE_DAYS
        )
        current_alpha += success * weight * recency
        current_beta += (1 - success) * weight * recency
        papers.add(row["submission_id"])
        if success < 0.5:
            failures.append(index)
        if success >= 0.75:
            successes.append(index)

    all_estimate = all_alpha / (all_alpha + all_beta)
    current_estimate = current_alpha / (current_alpha + current_beta)
    uncertainty = math.sqrt(
        current_estimate
        * (1 - current_estimate)
        / max(current_alpha + current_beta + 1, 1)
    )
    count = len(observations)
    distinct = len(papers)
    status = "insufficient evidence"
    trend = "stable"
    if count == 1:
        status = "early signal"
        trend = "early positive signal" if observations[0]["success_fraction"] >= 0.6 else "early concern"
    elif failures and successes and max(successes) > max(failures):
        recent = observations[-1]["success_fraction"]
        if recent >= 0.75 and len(failures) >= 2:
            status = "improving"
            trend = "improving"
        elif recent < 0.5 and successes[-1] < len(observations) - 1:
            status = "resurfaced"
            trend = "declining"
    elif distinct >= 2 and len(failures) >= 2:
        status = "recurring concern"
        trend = "recurring"
    elif distinct >= 3 and current_estimate >= 0.85:
        status = "strong"
        trend = "stable"
    elif distinct >= 2 and current_estimate >= 0.72:
        status = "secure"
        trend = "stable"
    else:
        status = "developing"

    return {
        "evidence_count": count,
        "distinct_papers": distinct,
        "total_marks_earned": sum(float(row["marks_earned"]) for row in observations),
        "total_marks_available": sum(float(row["marks_available"]) for row in observations),
        "all_time_estimate": all_estimate,
        "current_estimate": current_estimate,
        "uncertainty": uncertainty,
        "status": status,
        "trend": trend,
        "first_observed": observations[0]["observed_at"],
        "last_observed": observations[-1]["observed_at"],
    }


def rebuild_student_profile(student_id: int) -> list[dict]:
    user = query_one("SELECT math_mode FROM users WHERE id = ?", (student_id,))
    math_mode = "general" if user and user["math_mode"] == "general" else "0606"
    rows = query_all(
        """
        SELECT so.id, so.student_id, so.submission_id, so.observed_at,
               so.topic, so.subtopic, so.skill, so.marks_earned,
               so.marks_available, so.success_fraction,
               so.grading_confidence, so.extraction_confidence,
               so.evidence_weight
        FROM skill_observations so
        JOIN submissions s ON s.id = so.submission_id
        JOIN assignments a ON a.id = s.assignment_id
        WHERE so.student_id = ? AND a.syllabus_code = '0606' AND ? = '0606'
        UNION ALL
        SELECT 1000000000 + aso.id AS id, aso.student_id,
               1000000000 + aso.paper_id AS submission_id, aso.observed_at,
               aso.topic, aso.subtopic, aso.skill, aso.marks_earned,
               aso.marks_available, aso.success_fraction,
               aso.grading_confidence, aso.extraction_confidence,
               aso.evidence_weight
        FROM analysis_skill_observations aso
        JOIN student_papers sp ON sp.id = aso.paper_id
        WHERE aso.student_id = ? AND aso.is_current = 1
          AND sp.curriculum_mode = ?
        ORDER BY skill, observed_at, id
        """,
        (student_id, math_mode, student_id, math_mode),
    )
    grouped = defaultdict(list)
    for row in rows:
        normalised = dict(row)
        normalised["topic"] = canonical_topic(row["topic"], row["skill"])
        normalised["skill"] = canonical_skill(row["skill"], normalised["topic"])
        grouped[normalised["skill"]].append(normalised)
    execute("DELETE FROM student_skill_states WHERE student_id = ?", (student_id,))
    result = []
    for skill, observations in grouped.items():
        state = _state_for_observations(observations)
        topic = observations[-1]["topic"]
        execute(
            """
            INSERT INTO student_skill_states
            (student_id, skill, topic, evidence_count, distinct_papers,
             total_marks_earned, total_marks_available, all_time_estimate,
             current_estimate, uncertainty, status, trend, first_observed,
             last_observed, calculation_version, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                student_id,
                skill,
                topic,
                state["evidence_count"],
                state["distinct_papers"],
                state["total_marks_earned"],
                state["total_marks_available"],
                state["all_time_estimate"],
                state["current_estimate"],
                state["uncertainty"],
                state["status"],
                state["trend"],
                state["first_observed"],
                state["last_observed"],
                CALCULATION_VERSION,
                _now(),
            ),
        )
        result.append({"skill": skill, "topic": topic, **state})
    return result


def refresh_outdated_student_profiles() -> int:
    """Recalculate persisted profiles when the evidence formula changes."""
    students = query_all(
        """
        SELECT DISTINCT student_id
        FROM student_skill_states
        WHERE calculation_version != ?
        UNION
        SELECT DISTINCT observed.student_id
        FROM (
            SELECT student_id FROM skill_observations
            UNION
            SELECT student_id FROM analysis_skill_observations
            WHERE is_current = 1
        ) AS observed
        WHERE NOT EXISTS (
            SELECT 1 FROM student_skill_states states
            WHERE states.student_id = observed.student_id
        )
        """,
        (CALCULATION_VERSION,),
    )
    for row in students:
        rebuild_student_profile(row["student_id"])
    return len(students)


def student_skill_profile(student_id: int) -> dict:
    user = query_one("SELECT math_mode FROM users WHERE id = ?", (student_id,))
    math_mode = "general" if user and user["math_mode"] == "general" else "0606"
    states = [dict(row) for row in query_all(
        """
        SELECT * FROM student_skill_states
        WHERE student_id = ?
        ORDER BY current_estimate DESC, evidence_count DESC
        """,
        (student_id,),
    )]
    observed = {row["skill"].lower() for row in states}
    untested = [
        {"topic": topic, "skill": skill, "status": "untested"}
        for topic, skill in CORE_0606_SKILLS
        if math_mode == "0606" and skill.lower() not in observed
    ]
    strengths = [
        row for row in states
        if row["status"] in {"strong", "secure", "improving"}
    ]
    concerns = [
        row for row in states
        if row["status"] in {"recurring concern", "resurfaced", "early signal"}
        and row["current_estimate"] < 0.65
    ]
    topic_rows = query_all(
        """
        SELECT * FROM (
            SELECT so.id AS observation_id, so.submission_id,
                   so.observed_at, so.topic, so.skill, so.marks_earned,
                   so.marks_available, so.success_fraction, so.evidence_weight
            FROM skill_observations so
            JOIN submissions s ON s.id = so.submission_id
            JOIN assignments a ON a.id = s.assignment_id
            WHERE so.student_id = ? AND a.syllabus_code = '0606'
              AND ? = '0606'
            UNION ALL
            SELECT 1000000000 + aso.id, 1000000000 + aso.paper_id,
                   aso.observed_at, aso.topic, aso.skill, aso.marks_earned,
                   aso.marks_available, aso.success_fraction, aso.evidence_weight
            FROM analysis_skill_observations aso
            JOIN student_papers sp ON sp.id = aso.paper_id
            WHERE aso.student_id = ? AND aso.is_current = 1
              AND sp.curriculum_mode = ?
            UNION ALL
            SELECT 2000000000 + shq.id, 2000000000 + shq.id, shq.created_at,
                   shq.topic, shq.skill, 0.0, 2.0, 0.0,
                   MAX(0.5, 2.0 * shq.classification_confidence)
            FROM student_help_questions shq
            WHERE shq.student_id = ? AND shq.status = 'completed'
              AND shq.curriculum_mode = ?
        )
        ORDER BY observed_at, observation_id
        """,
        (
            student_id,
            math_mode,
            student_id,
            math_mode,
            student_id,
            math_mode,
        ),
    )
    grouped_topics = defaultdict(list)
    for raw in topic_rows:
        item = dict(raw)
        item["topic"] = canonical_topic(item["topic"], item["skill"])
        grouped_topics[item["topic"]].append(item)
    topic_states = []
    for topic_name, observations in grouped_topics.items():
        state = _state_for_observations(observations)
        confidence = max(0.0, min(1.0, 1.0 - 2.0 * state["uncertainty"]))
        level = (
            "weak"
            if state["current_estimate"] < 0.5
            else "developing"
            if state["current_estimate"] < 0.75
            else "secure"
        )
        topic_states.append(
            {
                "topic": topic_name,
                **state,
                "percentage": round(100 * state["current_estimate"], 1),
                "confidence": round(confidence, 2),
                "level": level,
            }
        )
    topic_states.sort(key=lambda row: (row["current_estimate"], -row["evidence_count"], row["topic"]))
    tested_topics = {row["topic"] for row in topic_states}
    untested_topics = [
        {"topic": topic, "status": "untested"}
        for topic in (
            GENERAL_MATH_TOPICS if math_mode == "general" else CORE_0606_TOPICS
        )
        if topic not in tested_topics
    ]
    return {
        "states": states,
        "strengths": strengths,
        "concerns": concerns,
        "untested": untested,
        "topic_states": topic_states,
        "untested_topics": untested_topics,
        "calculation_version": CALCULATION_VERSION,
        "math_mode": math_mode,
    }


def marks_lost_breakdown(submission_id: int) -> dict:
    rows = query_all(
        """
        SELECT cd.*, q.topic, q.subtopic,
               COALESCE(q.subtopic, q.assessment_objective, q.topic) AS skill,
               so.error_category, so.error_mechanism
        FROM criterion_decisions cd
        LEFT JOIN questions q ON q.id = cd.question_id
        LEFT JOIN skill_observations so
          ON so.criterion_decision_id = cd.id
        WHERE cd.submission_id = ? AND cd.is_current = 1
        """,
        (submission_id,),
    )
    result = {
        "total": 0.0,
        "by_topic": defaultdict(float),
        "by_subtopic": defaultdict(float),
        "by_skill": defaultdict(float),
        "by_category": defaultdict(float),
        "by_mechanism": defaultdict(float),
    }
    for row in rows:
        lost = max(0.0, float(row["available_marks"]) - float(row["awarded_marks"]))
        result["total"] += lost
        result["by_topic"][row["topic"] or "Unclassified"] += lost
        result["by_subtopic"][row["subtopic"] or "Unclassified"] += lost
        result["by_skill"][row["skill"] or "Unclassified"] += lost
        if row["error_category"]:
            result["by_category"][row["error_category"]] += lost
        if row["error_mechanism"]:
            result["by_mechanism"][row["error_mechanism"]] += lost
    return {
        key: (round(value, 2) if isinstance(value, float) else dict(value))
        for key, value in result.items()
    }


def paper_summary(student_id: int, submission_id: int):
    submission = query_one(
        """
        SELECT s.*, a.title, a.total_marks, a.syllabus_code, a.syllabus_version,
               a.examination_session, a.paper_component, a.calculator_policy,
               pp.year AS paper_year, pp.component AS pack_component
        FROM submissions s
        JOIN assignments a ON a.id = s.assignment_id
        LEFT JOIN paper_packs pp ON pp.id = a.paper_pack_id
        WHERE s.id = ? AND s.student_id = ?
        """,
        (submission_id, student_id),
    )
    if not submission:
        return None
    totals = query_one(
        """
        SELECT COALESCE(SUM(final_mark), 0) AS earned,
               COALESCE(SUM(q.max_marks), 0) AS possible,
               AVG(COALESCE(gd.ai_confidence, 0.5)) AS confidence
        FROM grade_drafts gd
        JOIN questions q ON q.id = gd.question_id
        WHERE gd.submission_id = ?
        """,
        (submission_id,),
    )
    return {
        **dict(submission),
        "earned": round(float(totals["earned"] or 0), 2),
        "possible": round(float(totals["possible"] or 0), 2),
        "percentage": round(100 * float(totals["earned"] or 0) / float(totals["possible"]), 1)
        if totals["possible"]
        else 0,
        "confidence": round(float(totals["confidence"] or 0.5), 2),
        "marks_lost": marks_lost_breakdown(submission_id),
    }


def compare_papers(student_id: int, submission_ids: list[int]) -> dict:
    papers = [
        summary
        for sid in submission_ids
        if (summary := paper_summary(student_id, sid)) is not None
    ]
    warnings = []
    if len({paper["possible"] for paper in papers}) > 1:
        warnings.append("Maximum marks differ; percentages are more comparable than raw totals.")
    if len({paper["calculator_policy"] for paper in papers}) > 1:
        warnings.append("Calculator policy differs between selected papers.")
    if len({paper["syllabus_version"] for paper in papers}) > 1:
        warnings.append("Syllabus versions differ between selected papers.")
    topic_sets = []
    for paper in papers:
        topic_sets.append(set(paper["marks_lost"]["by_topic"]))
    if len(topic_sets) >= 2 and not set.intersection(*topic_sets):
        warnings.append("The papers have no overlapping assessed topics.")
    if len(papers) < 2:
        warnings.append("Select at least two completed papers for a meaningful comparison.")
    return {"papers": papers, "warnings": warnings}


def file_sha256(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def student_attempts(student_id: int):
    return query_all(
        """
        SELECT s.id, s.uploaded_at, s.status, a.title, a.paper_component,
               a.calculator_policy, a.syllabus_code,
               COALESCE(s.provisional_score, SUM(gd.final_mark), 0) AS score,
               COALESCE(SUM(q.max_marks), a.total_marks, 0) AS maximum_marks,
               AVG(COALESCE(gd.ai_confidence, 0.5)) AS confidence
        FROM submissions s
        JOIN assignments a ON a.id = s.assignment_id
        LEFT JOIN grade_drafts gd ON gd.submission_id = s.id
        LEFT JOIN questions q ON q.id = gd.question_id
        WHERE s.student_id = ? AND a.syllabus_code = '0606'
        GROUP BY s.id
        ORDER BY s.uploaded_at DESC
        """,
        (student_id,),
    )
