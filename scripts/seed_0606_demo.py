"""Add a deterministic three-paper 0606 longitudinal demo.

The script is additive: it does not rewrite inherited 0580 prototype records.
It is safe to run repeatedly against the local development database.
"""

import os
import sys
from datetime import datetime, timedelta, timezone

import fitz

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from assessment import sync_submission_evidence
from db import connect, execute, init_db, query_one, seed_if_empty
from pdf_utils import save_upload


DEMO_CLASS = "0606 Longitudinal Demo"
PAPERS = [
    ("A", 60, (0, 1, 3)),
    ("B", 30, (0, 2, 3)),
    ("C", 0, (4, 3, 4)),
]
QUESTIONS = [
    (
        "Q1",
        "Calculus",
        "differentiation",
        "Differentiate y = x^3 - 4x.",
        "M1 apply the power rule; A1 derivative terms; A1 combine correctly; A1 final answer.",
    ),
    (
        "Q2",
        "Calculus",
        "integration",
        "Find the indefinite integral of 6x - 4.",
        "M1 integrate term by term; A1 3x^2; A1 -4x; B1 constant of integration.",
    ),
    (
        "Q3",
        "Algebra and graphs",
        "equations and inequalities",
        "Solve x^2 - 5x + 6 = 0.",
        "M1 valid factorisation method; A1 factors; A1 first root; A1 second root.",
    ),
]
PRACTICE = [
    ("Calculus", "0606-PRACTICE-D1", "Differentiate y=x^3-5x and find its stationary points."),
    ("Calculus", "0606-PRACTICE-I1", "Evaluate the definite integral of 3x^2-4 from 0 to 2."),
    ("Algebra and graphs", "0606-PRACTICE-A1", "Solve x^2-7x+10=0 and verify both roots."),
    ("Trigonometry", "0606-PRACTICE-T1", "Solve 2 sin x=1 for 0 ≤ x ≤ 360°."),
]


def demo_pdf(component: str) -> bytes:
    document = fitz.open()
    page = document.new_page()
    page.insert_text(
        (72, 72),
        (
            f"Sumkora 0606 synthetic paper {component}\n"
            "Q1: differentiation working\n"
            "Q2: integration working\n"
            "Q3: algebra working\n"
        ),
    )
    payload = document.tobytes()
    document.close()
    return payload


def ensure_demo_class(teacher_id: int, student_id: int) -> int:
    row = query_one(
        "SELECT id FROM classes WHERE teacher_id = ? AND name = ?",
        (teacher_id, DEMO_CLASS),
    )
    class_id = row["id"] if row else execute(
        "INSERT INTO classes (name, teacher_id) VALUES (?, ?)",
        (DEMO_CLASS, teacher_id),
    )
    execute(
        "INSERT OR IGNORE INTO class_enrollments (class_id, student_id) VALUES (?, ?)",
        (class_id, student_id),
    )
    return class_id


def seed_paper(
    class_id: int,
    student_id: int,
    component: str,
    days_ago: int,
    marks: tuple[int, int, int],
) -> int:
    title = f"[Sumkora 0606 Demo] Paper {component}"
    assignment = query_one(
        "SELECT id FROM assignments WHERE class_id = ? AND title = ?",
        (class_id, title),
    )
    observed_at = (
        datetime.now(timezone.utc) - timedelta(days=days_ago)
    ).replace(microsecond=0).isoformat()
    if assignment:
        assignment_id = assignment["id"]
    else:
        assignment_id = execute(
            """
            INSERT INTO assignments
            (class_id, title, type, total_marks, status, created_at,
             syllabus_code, syllabus_version, paper_component,
             calculator_policy)
            VALUES (?, ?, 'past_paper', 12, 'published', ?, '0606',
                    '2025-2027', ?, 'non-calculator')
            """,
            (class_id, title, observed_at, component),
        )
        for order_index, (label, topic, subtopic, text, scheme) in enumerate(
            QUESTIONS
        ):
            execute(
                """
                INSERT INTO questions
                (assignment_id, label, topic, subtopic, question_text,
                 max_marks, mark_scheme_text, page_number, order_index,
                 syllabus_code, paper_component, question_number,
                 assessment_objective, requires_method_marks,
                 answer_only_eligible)
                VALUES (?, ?, ?, ?, ?, 4, ?, 1, ?, '0606', ?, ?, ?,
                        1, 0)
                """,
                (
                    assignment_id,
                    label,
                    topic,
                    subtopic,
                    text,
                    scheme,
                    order_index,
                    component,
                    label,
                    subtopic,
                ),
            )

    submission = query_one(
        """
        SELECT id FROM submissions
        WHERE assignment_id = ? AND student_id = ?
        """,
        (assignment_id, student_id),
    )
    if submission:
        submission_id = submission["id"]
        execute(
            """
            UPDATE submissions
            SET status = 'final', uploaded_at = ?
            WHERE id = ?
            """,
            (observed_at, submission_id),
        )
        conn = connect()
        questions = conn.execute(
            """
            SELECT q.id
            FROM questions q
            WHERE q.assignment_id = ?
            ORDER BY q.order_index
            """,
            (assignment_id,),
        ).fetchall()
        for question, mark in zip(questions, marks):
            conn.execute(
                """
                UPDATE grade_drafts
                SET ai_mark = ?, ai_confidence = 0.92,
                    ai_notes = 'Synthetic 0606 longitudinal evidence',
                    final_mark = ?, risk_flags = '[]',
                    needs_exception_review = 0, auto_finalized_at = ?,
                    auto_finalize_reason = 'deterministic demo fixture'
                WHERE submission_id = ? AND question_id = ?
                """,
                (
                    mark,
                    mark,
                    observed_at,
                    submission_id,
                    question["id"],
                ),
            )
        conn.commit()
        conn.close()
    else:
        path = save_upload(
            f"sumkora_0606_demo_{component}.pdf",
            demo_pdf(component),
        )
        submission_id = execute(
            """
            INSERT INTO submissions
            (assignment_id, student_id, file_path, status, uploaded_at)
            VALUES (?, ?, ?, 'final', ?)
            """,
            (assignment_id, student_id, path, observed_at),
        )
        conn = connect()
        questions = conn.execute(
            """
            SELECT id FROM questions
            WHERE assignment_id = ?
            ORDER BY order_index
            """,
            (assignment_id,),
        ).fetchall()
        for question, mark in zip(questions, marks):
            conn.execute(
                """
                INSERT INTO grade_drafts
                (submission_id, question_id, ai_mark, ai_confidence,
                 ai_notes, final_mark, risk_flags, needs_exception_review,
                 auto_finalized_at, auto_finalize_reason)
                VALUES (?, ?, ?, 0.92, 'Synthetic 0606 longitudinal evidence',
                        ?, '[]', 0, ?, 'deterministic demo fixture')
                """,
                (submission_id, question["id"], mark, mark, observed_at),
            )
        conn.commit()
        conn.close()

    sync_submission_evidence(submission_id)
    return submission_id


def main():
    init_db()
    seed_if_empty()
    teacher = query_one(
        "SELECT id FROM users WHERE email = 'teacher@school.edu'"
    )
    student = query_one(
        "SELECT id FROM users WHERE email = 'student@school.edu'"
    )
    if not teacher or not student:
        raise RuntimeError("Expected local demo teacher and student accounts.")
    class_id = ensure_demo_class(teacher["id"], student["id"])
    for topic, label, text in PRACTICE:
        execute(
            """
            INSERT INTO practice_questions (topic, label, text, source)
            SELECT ?, ?, ?, '0606-seed'
            WHERE NOT EXISTS (
                SELECT 1 FROM practice_questions WHERE label = ?
            )
            """,
            (topic, label, text, label),
        )
    submission_ids = [
        seed_paper(class_id, student["id"], *paper)
        for paper in PAPERS
    ]
    print(
        "Seeded Sumkora 0606 longitudinal demo submissions: "
        + ", ".join(str(item) for item in submission_ids)
    )


if __name__ == "__main__":
    main()
