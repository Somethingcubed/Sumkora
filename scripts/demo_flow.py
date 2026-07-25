import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from datetime import datetime

import config

# This script is a deterministic local smoke test, not a live-provider demo.
config.OCR_ENABLED = False
config.CXSEE_API_KEY = ""
config.OPENAI_API_KEY = ""
config.DEEPSEEK_API_KEY = ""

from db import connect, execute, hash_password, init_db, query_one, seed_if_empty
from grading import ensure_grade_rows, finalize_submission, reset_grade_rows, run_grading_job
import fitz

from pdf_utils import save_upload

init_db()
seed_if_empty()

doc = fitz.open()
page = doc.new_page()
page.insert_text((72, 72), "Student submission sample\nQ1a: 2^3 x 3^2 x 5\nQ2b: x = 6")
sample_pdf = doc.tobytes()
doc.close()

conn = connect()
assignment = conn.execute(
    """
    SELECT id FROM assignments
    WHERE syllabus_code = '0606' AND title = '0606 Local Smoke Test'
    ORDER BY id
    LIMIT 1
    """
).fetchone()
student = conn.execute(
    "SELECT id FROM users WHERE email = 'smoke@school.edu'"
).fetchone()
conn.close()

if not assignment:
    teacher_row = query_one(
        """
        SELECT id FROM users WHERE email = 'teacher@school.edu'
        """
    )
    if not teacher_row:
        raise RuntimeError("No demo teacher is available for the smoke test.")
    class_row = query_one(
        """
        SELECT id FROM classes
        WHERE teacher_id = ? AND name = '0606 Smoke Test Class'
        """,
        (teacher_row["id"],),
    )
    class_id = class_row["id"] if class_row else execute(
        "INSERT INTO classes (name, teacher_id) VALUES ('0606 Smoke Test Class', ?)",
        (teacher_row["id"],),
    )
    assignment_id = execute(
        """
        INSERT INTO assignments
        (class_id, title, type, total_marks, status, created_at,
         syllabus_code, syllabus_version, paper_component, calculator_policy)
        VALUES (?, '0606 Local Smoke Test', 'practice', 4, 'published', ?,
                '0606', '2025-2027', 'smoke', 'non-calculator')
        """,
        (class_id, datetime.now().isoformat()),
    )
    execute(
        """
        INSERT INTO questions
        (assignment_id, label, topic, subtopic, question_text, max_marks,
         mark_scheme_text, page_number, order_index, syllabus_code)
        VALUES (?, 'Q1', 'Algebra and graphs', 'algebraic manipulation',
                'Factorise 360 into prime factors.', 2,
                'M1 valid factor tree; A1 complete factorisation.', 1, 0,
                '0606')
        """,
        (assignment_id,),
    )
    execute(
        """
        INSERT INTO questions
        (assignment_id, label, topic, subtopic, question_text, max_marks,
         mark_scheme_text, page_number, order_index, syllabus_code)
        VALUES (?, 'Q2', 'Algebra and graphs', 'equations and inequalities',
                'Solve 3x - 7 = 11.', 2,
                'M1 rearrangement; A1 x = 6.', 1, 1, '0606')
        """,
        (assignment_id,),
    )
    assignment = {"id": assignment_id}

if not student:
    student_id = execute(
        "INSERT INTO users (email, password_hash, name, role) VALUES (?, ?, ?, 'student')",
        (
            "smoke@school.edu",
            hash_password("student123"),
            "Smoke Test Student",
        ),
    )
    execute(
        "INSERT OR IGNORE INTO user_roles (user_id, role, created_at) VALUES (?, 'student', ?)",
        (student_id, datetime.now().isoformat()),
    )
    class_id = query_one(
        "SELECT class_id FROM assignments WHERE id = ?",
        (assignment["id"],),
    )
    execute(
        "INSERT OR IGNORE INTO class_enrollments (class_id, student_id) VALUES (?, ?)",
        (class_id["class_id"], student_id),
    )
    student = {"id": student_id}

path = save_upload("demo_student_submission.pdf", sample_pdf)

existing = query_one(
    "SELECT id FROM submissions WHERE assignment_id = ? AND student_id = ?",
    (assignment["id"], student["id"]),
)
if existing:
    execute(
        "UPDATE submissions SET file_path = ?, status = 'pending', uploaded_at = ? WHERE id = ?",
        (path, datetime.now().isoformat(), existing["id"]),
    )
    submission_id = existing["id"]
    reset_grade_rows(submission_id)
else:
    submission_id = execute(
        """
        INSERT INTO submissions (assignment_id, student_id, file_path, status, uploaded_at)
        VALUES (?, ?, ?, 'pending', ?)
        """,
        (assignment["id"], student["id"], path, datetime.now().isoformat()),
    )

ensure_grade_rows(submission_id, assignment["id"])
run_grading_job(submission_id)
finalize_submission(submission_id)
print(f"Demo submission {submission_id} graded and finalized.")
