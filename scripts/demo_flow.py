import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from datetime import datetime

from db import connect, execute, init_db, query_one, seed_if_empty
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
    "SELECT id FROM assignments ORDER BY id LIMIT 1"
).fetchone()
student = conn.execute(
    "SELECT id FROM users WHERE email = 'student@school.edu'"
).fetchone()
conn.close()

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
