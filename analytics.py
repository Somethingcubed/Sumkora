import json
import re
from collections import defaultdict

from db import query_all


QUESTION_TYPE_KEYS = {
    "number": ("standard form", "percentage", "percent", "reciprocal", "round", "nearest"),
    "solve_equation": ("solve", "equation", "rearrange", "x ="),
    "expand_factorise": ("expand", "factorise", "factorize", "bracket"),
    "graph_sketch": ("graph", "sketch", "intercept", "gradient", "curve"),
    "trigonometry": ("sin", "cos", "tan", "trigonometry", "bearing"),
    "angle_geometry": ("angle", "parallel", "triangle", "polygon", "circle theorem"),
    "probability": ("probability", "prob", "chance", "without replacement"),
    "statistics": ("mean", "median", "mode", "frequency", "histogram", "chart", "table"),
    "sequences": ("sequence", "nth term", "term-to-term"),
    "mensuration": ("area", "volume", "surface area", "perimeter", "arc", "sector"),
}


def pct(earned, possible):
    return round(100 * earned / possible, 1) if possible else 0


def difficulty_label(max_marks, assignment_title=""):
    level = 0 if max_marks <= 2 else 1 if max_marks <= 4 else 2
    if re.search(r"\bpaper\s+[34]\b", assignment_title or "", re.I):
        level = min(2, level + 1)
    return ["easy", "medium", "hard"][level]


def stored_difficulty(row):
    value = (row["difficulty_teacher"] or "").strip() if "difficulty_teacher" in row.keys() else ""
    if value in {"easy", "medium", "hard"}:
        return value
    return difficulty_label(row["max_marks"], row["assignment_title"])


def keyword_matches(text, keyword):
    if re.fullmatch(r"[a-z0-9]+", keyword):
        return re.search(rf"\b{re.escape(keyword)}\b", text) is not None
    return keyword in text


def question_type(question_text="", mark_scheme_text="", topic=""):
    text = f"{question_text} {mark_scheme_text} {topic}".lower()
    for label, words in QUESTION_TYPE_KEYS.items():
        if any(keyword_matches(text, word) for word in words):
            return label
    return "mixed_skill"


def stored_question_type(row):
    value = (row["question_type_tag"] or "").strip() if "question_type_tag" in row.keys() else ""
    if value:
        return value
    return question_type(row["question_text"], row["mark_scheme_text"], row["topic"])


def finalized_question_rows(student_id=None, teacher_id=None):
    filters = ["s.status = 'final'", "gd.final_mark IS NOT NULL"]
    params = []
    if student_id is not None:
        filters.append("s.student_id = ?")
        params.append(student_id)
    if teacher_id is not None:
        filters.append("c.teacher_id = ?")
        params.append(teacher_id)

    where = " AND ".join(filters)
    return query_all(
        f"""
        SELECT gd.final_mark, q.max_marks, q.label, q.topic, q.subtopic,
               q.question_text, q.mark_scheme_text, q.difficulty_teacher,
               q.question_type_tag, q.order_index, a.title AS assignment_title,
               a.due_date, s.uploaded_at, s.id AS submission_id,
               u.id AS student_id, u.name AS student_name, c.name AS class_name
        FROM grade_drafts gd
        JOIN questions q ON q.id = gd.question_id
        JOIN submissions s ON s.id = gd.submission_id
        JOIN assignments a ON a.id = s.assignment_id
        JOIN classes c ON c.id = a.class_id
        JOIN users u ON u.id = s.student_id
        WHERE {where}
        ORDER BY COALESCE(a.due_date, s.uploaded_at), s.id, q.order_index
        """,
        tuple(params),
    )


def student_score_history(student_id, teacher_id=None):
    filters = ["s.student_id = ?", "s.status = 'final'", "gd.final_mark IS NOT NULL"]
    params = [student_id]
    if teacher_id is not None:
        filters.append("c.teacher_id = ?")
        params.append(teacher_id)
    where = " AND ".join(filters)
    rows = query_all(
        f"""
        SELECT s.id AS submission_id, a.title, a.due_date, s.uploaded_at,
               SUM(COALESCE(gd.final_mark, 0)) AS earned,
               SUM(q.max_marks) AS possible
        FROM submissions s
        JOIN assignments a ON a.id = s.assignment_id
        JOIN classes c ON c.id = a.class_id
        JOIN grade_drafts gd ON gd.submission_id = s.id
        JOIN questions q ON q.id = gd.question_id
        WHERE {where}
        GROUP BY s.id, a.title, a.due_date, s.uploaded_at
        ORDER BY COALESCE(a.due_date, s.uploaded_at), s.id
        """,
        tuple(params),
    )
    history = []
    for row in rows:
        earned = row["earned"] or 0
        possible = row["possible"] or 0
        history.append(
            {
                "submission_id": row["submission_id"],
                "title": row["title"],
                "date": row["due_date"] or (row["uploaded_at"] or "")[:10],
                "earned": round(earned, 1),
                "possible": possible,
                "accuracy": pct(earned, possible),
            }
        )
    return history


def aggregate_breakdown(rows, key_fn):
    grouped = defaultdict(lambda: {"earned": 0, "possible": 0, "question_count": 0})
    for row in rows:
        key = key_fn(row)
        grouped[key]["earned"] += row["final_mark"] or 0
        grouped[key]["possible"] += row["max_marks"] or 0
        grouped[key]["question_count"] += 1

    result = []
    for key, data in grouped.items():
        result.append(
            {
                "key": key,
                "earned": round(data["earned"], 1),
                "possible": data["possible"],
                "question_count": data["question_count"],
                "accuracy": pct(data["earned"], data["possible"]),
            }
        )
    result.sort(key=lambda item: item["accuracy"])
    return result


def student_difficulty_breakdown(student_id, teacher_id=None):
    rows = finalized_question_rows(student_id=student_id, teacher_id=teacher_id)
    return aggregate_breakdown(
        rows,
        stored_difficulty,
    )


def student_type_breakdown(student_id, teacher_id=None):
    rows = finalized_question_rows(student_id=student_id, teacher_id=teacher_id)
    return aggregate_breakdown(
        rows,
        stored_question_type,
    )


def student_topic_difficulty_breakdown(student_id, limit=8, teacher_id=None):
    rows = finalized_question_rows(student_id=student_id, teacher_id=teacher_id)
    result = aggregate_breakdown(
        rows,
        lambda row: (row["topic"], stored_difficulty(row)),
    )
    for item in result:
        item["topic"], item["difficulty"] = item["key"]
    return result[:limit]


def student_review_questions(student_id, limit=8, teacher_id=None):
    rows = finalized_question_rows(student_id=student_id, teacher_id=teacher_id)
    review = []
    for row in rows:
        possible = row["max_marks"] or 0
        earned = row["final_mark"] or 0
        accuracy = pct(earned, possible)
        if possible and accuracy < 60:
            review.append(
                {
                    "submission_id": row["submission_id"],
                    "assignment_title": row["assignment_title"],
                    "label": row["label"],
                    "topic": row["topic"],
                    "difficulty": stored_difficulty(row),
                    "question_type": stored_question_type(row),
                    "question_text": row["question_text"],
                    "earned": round(earned, 1),
                    "possible": possible,
                    "accuracy": accuracy,
                    "date": row["due_date"] or (row["uploaded_at"] or "")[:10],
                }
            )
    review.sort(key=lambda item: (item["accuracy"], item["date"]), reverse=False)
    return review[:limit]


def predict_student_score(student_id, teacher_id=None):
    history = student_score_history(student_id, teacher_id=teacher_id)
    if len(history) < 4:
        return {
            "available": False,
            "label": "not_enough_data",
            "confidence": "low",
            "trend": "not_enough_data",
            "explanation": "Complete and finalize at least four comparable assessments.",
        }

    recent = history[-4:]
    weights = list(range(1, len(recent) + 1))
    weighted = sum(item["accuracy"] * weight for item, weight in zip(recent, weights))
    base = weighted / sum(weights)

    weak = student_topic_difficulty_breakdown(student_id, limit=1, teacher_id=teacher_id)
    penalty = 0
    weak_topic = ""
    weak_difficulty = ""
    if weak and weak[0]["accuracy"] < 50:
        penalty = 4
        weak_topic = weak[0]["topic"]
        weak_difficulty = weak[0]["difficulty"]
    elif weak and weak[0]["accuracy"] < 65:
        penalty = 2
        weak_topic = weak[0]["topic"]
        weak_difficulty = weak[0]["difficulty"]

    trend = "stable"
    adjustment = 0
    if len(history) >= 2:
        delta = history[-1]["accuracy"] - history[-2]["accuracy"]
        if delta >= 5:
            trend = "improving"
            adjustment = 2
        elif delta <= -5:
            trend = "declining"
            adjustment = -2

    predicted = max(0, min(100, round(base + adjustment - penalty, 1)))
    confidence = "high" if len(history) >= 6 else "medium"
    if predicted >= 85:
        band = "strong"
    elif predicted >= 70:
        band = "secure"
    elif predicted >= 50:
        band = "developing"
    else:
        band = "needs_support"
    return {
        "available": True,
        "score": predicted,
        "band": band,
        "confidence": confidence,
        "trend": trend,
        "weak_topic": weak_topic,
        "weak_difficulty": weak_difficulty,
    }


def grading_audit_summary(teacher_id):
    rows = query_all(
        """
        SELECT gd.ai_mark, gd.final_mark, gd.ai_confidence, gd.risk_flags,
               gd.needs_exception_review, gd.auto_finalized_at,
               gd.auto_finalize_reason, gd.teacher_override_mark,
               q.topic, q.max_marks, q.question_type_tag, q.question_text,
               q.mark_scheme_text
        FROM grade_drafts gd
        JOIN questions q ON q.id = gd.question_id
        JOIN submissions s ON s.id = gd.submission_id
        JOIN assignments a ON a.id = s.assignment_id
        JOIN classes c ON c.id = a.class_id
        WHERE c.teacher_id = ?
        """,
        (teacher_id,),
    )
    total_rows = len(rows)
    auto_rows = [row for row in rows if row["auto_finalized_at"]]
    override_rows = [
        row for row in rows
        if row["teacher_override_mark"] is not None and row["ai_mark"] is not None
    ]
    differences = [
        abs(float(row["teacher_override_mark"]) - float(row["ai_mark"]))
        for row in override_rows
    ]

    def grouped(key_fn):
        data = defaultdict(lambda: {"rows": 0, "overrides": 0, "abs_error": 0.0})
        for row in rows:
            key = key_fn(row)
            data[key]["rows"] += 1
            if row["teacher_override_mark"] is not None and row["ai_mark"] is not None:
                data[key]["overrides"] += 1
                data[key]["abs_error"] += abs(
                    float(row["teacher_override_mark"]) - float(row["ai_mark"])
                )
        result = []
        for key, value in data.items():
            overrides = value["overrides"]
            result.append(
                {
                    "key": key,
                    "rows": value["rows"],
                    "overrides": overrides,
                    "override_rate": pct(overrides, value["rows"]),
                    "mean_abs_error": round(value["abs_error"] / overrides, 2)
                    if overrides
                    else None,
                }
            )
        result.sort(key=lambda item: (item["overrides"], item["override_rate"]), reverse=True)
        return result

    flag_data = defaultdict(lambda: {"rows": 0, "overrides": 0, "abs_error": 0.0})
    for row in rows:
        try:
            flags = [flag for flag in json.loads(row["risk_flags"] or "[]") if flag]
        except Exception:
            flags = [row["risk_flags"]] if row["risk_flags"] else ["none"]
        if not flags:
            flags = ["none"]
        for flag in flags:
            flag_data[flag]["rows"] += 1
            if row["teacher_override_mark"] is not None and row["ai_mark"] is not None:
                flag_data[flag]["overrides"] += 1
                flag_data[flag]["abs_error"] += abs(
                    float(row["teacher_override_mark"]) - float(row["ai_mark"])
                )
    flag_rows = []
    for flag, value in flag_data.items():
        overrides = value["overrides"]
        flag_rows.append(
            {
                "key": flag,
                "rows": value["rows"],
                "overrides": overrides,
                "override_rate": pct(overrides, value["rows"]),
                "mean_abs_error": round(value["abs_error"] / overrides, 2)
                if overrides
                else None,
            }
        )
    flag_rows.sort(key=lambda item: (item["overrides"], item["override_rate"]), reverse=True)

    return {
        "total_rows": total_rows,
        "auto_finalized": len(auto_rows),
        "overrides": len(override_rows),
        "override_rate": pct(len(override_rows), len(auto_rows) or total_rows),
        "mean_abs_error": round(sum(differences) / len(differences), 2)
        if differences
        else None,
        "by_topic": grouped(lambda row: row["topic"])[:10],
        "by_marks": grouped(lambda row: f"{row['max_marks']} mark(s)")[:10],
        "by_type": grouped(lambda row: stored_question_type(row))[:10],
        "by_flag": flag_rows[:10],
    }


def student_analytics_summary(student_id, teacher_id=None):
    history = student_score_history(student_id, teacher_id=teacher_id)
    latest = history[-1] if history else None
    average = (
        round(sum(item["accuracy"] for item in history) / len(history), 1)
        if history
        else None
    )
    rows = finalized_question_rows(student_id=student_id, teacher_id=teacher_id)
    topics = aggregate_breakdown(rows, lambda row: row["topic"])
    strongest = max(topics, key=lambda item: item["accuracy"]) if topics else None
    weakest = min(topics, key=lambda item: item["accuracy"]) if topics else None
    return {
        "latest": latest,
        "average": average,
        "strongest_topic": strongest,
        "weakest_topic": weakest,
        "prediction": predict_student_score(student_id, teacher_id=teacher_id),
        "score_history": history,
        "difficulty_breakdown": student_difficulty_breakdown(student_id, teacher_id=teacher_id),
        "type_breakdown": student_type_breakdown(student_id, teacher_id=teacher_id),
        "topic_difficulty": student_topic_difficulty_breakdown(student_id, teacher_id=teacher_id),
        "review_questions": student_review_questions(student_id, teacher_id=teacher_id),
    }


def analytics_practice(student_id, limit=5):
    review = student_review_questions(student_id, limit=1)
    if review:
        return query_all(
            "SELECT * FROM practice_questions WHERE topic = ? ORDER BY id LIMIT ?",
            (review[0]["topic"], limit),
        )
    rows = finalized_question_rows(student_id=student_id)
    topics = aggregate_breakdown(rows, lambda row: row["topic"])
    if topics:
        return query_all(
            "SELECT * FROM practice_questions WHERE topic = ? ORDER BY id LIMIT ?",
            (topics[0]["key"], limit),
        )
    return query_all("SELECT * FROM practice_questions ORDER BY id LIMIT ?", (limit,))


def teacher_analytics_summary(teacher_id):
    rows = finalized_question_rows(teacher_id=teacher_id)
    student_rows = aggregate_breakdown(
        rows,
        lambda row: (row["class_name"], row["student_id"], row["student_name"]),
    )
    students = []
    for item in student_rows:
        class_name, student_id, student_name = item["key"]
        history = student_score_history(student_id, teacher_id=teacher_id)
        trend = "stable"
        if len(history) >= 2:
            delta = history[-1]["accuracy"] - history[-2]["accuracy"]
            if delta >= 5:
                trend = "improving"
            elif delta <= -5:
                trend = "declining"
        students.append(
            {
                **item,
                "class_name": class_name,
                "student_id": student_id,
                "student_name": student_name,
                "trend": trend,
            }
        )
    students.sort(key=lambda item: item["accuracy"])
    all_students = sorted(students, key=lambda item: item["accuracy"], reverse=True)

    return {
        "students": all_students,
        "support_students": [
            item for item in students
            if item["accuracy"] < 60 or (item["trend"] == "declining" and item["accuracy"] < 75)
        ][:8],
        "topics": aggregate_breakdown(rows, lambda row: row["topic"]),
        "difficulty": aggregate_breakdown(
            rows,
            stored_difficulty,
        ),
        "types": aggregate_breakdown(
            rows,
            stored_question_type,
        ),
    }
