import os
import sys
import tempfile
from datetime import datetime

import fitz
from fastapi.testclient import TestClient

ROOT = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, ROOT)

import config


tmpdir = tempfile.TemporaryDirectory()
config.DB_PATH = os.path.join(tmpdir.name, "test.db")
config.UPLOAD_DIR = os.path.join(tmpdir.name, "uploads")
config.OCR_ENABLED = False
config.CXSEE_API_KEY = ''
config.OPENAI_API_KEY = ''
config.DEEPSEEK_API_KEY = ''

from db import connect, execute, hash_password, init_db, query_one
from grading import exact_answer_grade, run_grading_job
from main import app
from pdf_utils import save_upload
from analytics import predict_student_score


def assert_true(condition, message):
    if not condition:
        raise AssertionError(message)


def make_pdf(text):
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), text)
    content = doc.tobytes()
    doc.close()
    return content


def seed_user(email, name, role, password="pass123"):
    return execute(
        "INSERT INTO users (email, password_hash, name, role) VALUES (?, ?, ?, ?)",
        (email, hash_password(password), name, role),
    )


def login(client, email, password="pass123"):
    response = client.post(
        "/login",
        data={"email": email, "password": password},
        follow_redirects=False,
    )
    assert_true(response.status_code == 303, f"login failed for {email}")
    return response.cookies


def test_cross_teacher_assignment_blocked(client):
    teacher_a = seed_user("teacher-a@test.local", "Teacher A", "teacher")
    teacher_b = seed_user("teacher-b@test.local", "Teacher B", "teacher")
    class_b = execute(
        "INSERT INTO classes (name, teacher_id) VALUES (?, ?)",
        ("Teacher B Class", teacher_b),
    )
    cookies = login(client, "teacher-a@test.local")
    response = client.post(
        "/teacher/assignments",
        data={
            "title": "Forged Assignment",
            "class_id": class_b,
            "type": "worksheet",
            "due_date": "",
        },
        cookies=cookies,
        follow_redirects=False,
    )
    created = query_one(
        "SELECT id FROM assignments WHERE title = ?",
        ("Forged Assignment",),
    )
    assert_true(response.status_code == 303, "unexpected response status")
    assert_true(created is None, "cross-teacher assignment was created")
    print("PASS cross-teacher assignment blocked")


def test_student_cannot_upload_to_draft(client):
    teacher = seed_user("draft-teacher@test.local", "Draft Teacher", "teacher")
    student = seed_user("draft-student@test.local", "Draft Student", "student")
    class_id = execute(
        "INSERT INTO classes (name, teacher_id) VALUES (?, ?)",
        ("Draft Class", teacher),
    )
    execute(
        "INSERT INTO class_enrollments (class_id, student_id) VALUES (?, ?)",
        (class_id, student),
    )
    assignment = execute(
        """
        INSERT INTO assignments (class_id, title, type, status, created_at)
        VALUES (?, 'Draft Only', 'worksheet', 'draft', ?)
        """,
        (class_id, datetime.now().isoformat()),
    )
    cookies = login(client, "draft-student@test.local")
    response = client.post(
        f"/student/assignments/{assignment}/upload",
        files={"file": ("work.pdf", make_pdf("Q1: 1"), "application/pdf")},
        cookies=cookies,
        follow_redirects=False,
    )
    submission = query_one(
        "SELECT id FROM submissions WHERE assignment_id = ? AND student_id = ?",
        (assignment, student),
    )
    assert_true(response.status_code == 303, "unexpected upload response")
    assert_true(submission is None, "student uploaded to draft assignment")
    print("PASS draft assignment upload blocked")


def test_exact_checker_does_not_full_credit_multi_mark():
    question = {
        "label": "Q1",
        "mark_scheme_text": "M1 rearrange, A1 final answer x = 6",
        "max_marks": 3,
    }
    result = exact_answer_grade(question, "Q1: x = 7, but I wrote 6 in working")
    assert_true(result is not None, "expected exact-check result")
    assert_true(result["ai_mark"] == 0.0, "multi-mark exact check over-credited")
    assert_true(
        result["needs_exception_review"],
        "multi-mark exact check was not flagged",
    )
    print("PASS multi-mark exact check does not over-credit")


def test_one_mark_mismatch_auto_zero_without_exception():
    question = {
        "label": "Q1",
        "mark_scheme_text": "Answer: 5",
        "max_marks": 1,
    }
    result = exact_answer_grade(question, "Q1: 6")
    assert_true(result is not None, "expected exact-check result")
    assert_true(result["ai_mark"] == 0.0, "wrong one-mark answer was not zero")
    assert_true(
        not result["needs_exception_review"],
        "clear one-mark mismatch should not enter exception queue",
    )
    print("PASS one-mark mismatch auto-zeroes without exception")


def test_auto_grading_finalizes_with_risk_flags():
    teacher = seed_user("auto-teacher@test.local", "Auto Teacher", "teacher")
    student = seed_user("auto-student@test.local", "Auto Student", "student")
    class_id = execute(
        "INSERT INTO classes (name, teacher_id) VALUES (?, ?)",
        ("Auto Class", teacher),
    )
    execute(
        "INSERT INTO class_enrollments (class_id, student_id) VALUES (?, ?)",
        (class_id, student),
    )
    assignment = execute(
        """
        INSERT INTO assignments (class_id, title, type, status, created_at)
        VALUES (?, 'Auto Grade', 'worksheet', 'published', ?)
        """,
        (class_id, datetime.now().isoformat()),
    )
    question = execute(
        """
        INSERT INTO questions
        (assignment_id, label, topic, question_text, max_marks, mark_scheme_text, page_number, order_index)
        VALUES (?, 'Q1', 'Algebra', 'Solve x.', 3, 'M1 rearrange, A1 final answer x = 6', 1, 0)
        """,
        (assignment,),
    )
    path = save_upload(
        "auto_grade_submission.pdf",
        make_pdf("Q1: x = 7, but I wrote 6 in working"),
    )
    submission = execute(
        """
        INSERT INTO submissions (assignment_id, student_id, file_path, status, uploaded_at)
        VALUES (?, ?, ?, 'pending', ?)
        """,
        (assignment, student, path, datetime.now().isoformat()),
    )
    execute(
        "INSERT INTO grade_drafts (submission_id, question_id) VALUES (?, ?)",
        (submission, question),
    )
    run_grading_job(submission)
    sub = query_one("SELECT status FROM submissions WHERE id = ?", (submission,))
    grade = query_one(
        """
        SELECT final_mark, needs_exception_review, risk_flags
        FROM grade_drafts WHERE submission_id = ? AND question_id = ?
        """,
        (submission, question),
    )
    assert_true(sub["status"] == "final", "AI grading did not auto-finalize")
    assert_true(grade["final_mark"] == 0.0, "unsafe exact match was not conservative")
    assert_true(
        grade["needs_exception_review"] == 1,
        "unsafe exact match was not put in exception queue",
    )
    assert_true("unsafe_exact_match_multi_mark" in grade["risk_flags"], "missing risk flag")
    print("PASS auto grading finalizes and flags risky row")
    return {
        "teacher_email": "auto-teacher@test.local",
        "submission_id": submission,
        "question_id": question,
    }


def test_exception_queue_route(client, teacher_email):
    cookies = login(client, teacher_email)
    response = client.get("/teacher/exceptions", cookies=cookies)
    assert_true(response.status_code == 200, "exception queue route failed")
    assert_true(
        "unsafe_exact_match_multi_mark" in response.text,
        "exception queue did not show risk flag",
    )
    print("PASS exception queue route shows risky rows")


def test_calibration_route_shows_overrides(client, teacher_email):
    cookies = login(client, teacher_email)
    response = client.get("/teacher/calibration", cookies=cookies)
    assert_true(response.status_code == 200, "calibration route failed")
    assert_true("AI calibration" in response.text, "calibration page title missing")
    assert_true("Correction rate" in response.text, "calibration metrics missing")
    print("PASS calibration route shows correction metrics")


def test_non_final_report_blocked(client):
    teacher = seed_user("report-teacher@test.local", "Report Teacher", "teacher")
    student = seed_user("report-student@test.local", "Report Student", "student")
    class_id = execute(
        "INSERT INTO classes (name, teacher_id) VALUES (?, ?)",
        ("Report Class", teacher),
    )
    execute(
        "INSERT INTO class_enrollments (class_id, student_id) VALUES (?, ?)",
        (class_id, student),
    )
    assignment = execute(
        """
        INSERT INTO assignments (class_id, title, type, status, created_at)
        VALUES (?, 'Report Draft', 'worksheet', 'published', ?)
        """,
        (class_id, datetime.now().isoformat()),
    )
    path = save_upload("report_pending.pdf", make_pdf("Q1: 1"))
    submission = execute(
        """
        INSERT INTO submissions (assignment_id, student_id, file_path, status, uploaded_at)
        VALUES (?, ?, ?, 'pending', ?)
        """,
        (assignment, student, path, datetime.now().isoformat()),
    )
    cookies = login(client, "report-teacher@test.local")
    response = client.get(
        f"/teacher/submissions/{submission}/report",
        cookies=cookies,
        follow_redirects=False,
    )
    assert_true(response.status_code == 303, "non-final report was not blocked")
    assert_true(
        response.headers.get("location", "").endswith(f"/teacher/submissions/{submission}/review"),
        "non-final report did not redirect to review",
    )
    print("PASS non-final assessment report blocked")


def test_teacher_override_survives_ai_rerun(client, teacher_email, submission_id, question_id):
    cookies = login(client, teacher_email)
    response = client.post(
        f"/teacher/submissions/{submission_id}/grade-manual",
        data={
            "question_id": question_id,
            "final_mark": "2",
            "teacher_comment": "Manual correction",
        },
        cookies=cookies,
        follow_redirects=False,
    )
    assert_true(response.status_code == 303, "manual override failed")
    run_grading_job(submission_id)
    grade = query_one(
        """
        SELECT final_mark, teacher_override_mark, needs_exception_review
        FROM grade_drafts WHERE submission_id = ? AND question_id = ?
        """,
        (submission_id, question_id),
    )
    assert_true(grade["final_mark"] == 2.0, "AI rerun overwrote teacher override")
    assert_true(grade["teacher_override_mark"] == 2.0, "override mark was not recorded")
    assert_true(grade["needs_exception_review"] == 0, "override did not clear exception")
    execute(
        """
        UPDATE grade_drafts
        SET ai_notes = 'failed old attempt', auto_finalized_at = NULL,
            risk_flags = '["stale"]', needs_exception_review = 1
        WHERE submission_id = ? AND question_id = ?
        """,
        (submission_id, question_id),
    )
    run_grading_job(submission_id)
    grade = query_one(
        """
        SELECT final_mark, teacher_override_mark, needs_exception_review, risk_flags
        FROM grade_drafts WHERE submission_id = ? AND question_id = ?
        """,
        (submission_id, question_id),
    )
    assert_true(grade["final_mark"] == 2.0, "forced AI rerun overwrote teacher override")
    assert_true(grade["teacher_override_mark"] == 2.0, "forced rerun lost override mark")
    assert_true(grade["needs_exception_review"] == 0, "override row stayed in exception queue")
    assert_true(not grade["risk_flags"], "override row kept stale risk flags")
    print("PASS teacher override survives AI rerun")


def test_reusable_ai_suggestion_backfills_auto_finalized():
    teacher = seed_user("reuse-teacher@test.local", "Reuse Teacher", "teacher")
    student = seed_user("reuse-student@test.local", "Reuse Student", "student")
    class_id = execute(
        "INSERT INTO classes (name, teacher_id) VALUES (?, ?)",
        ("Reuse Class", teacher),
    )
    execute(
        "INSERT INTO class_enrollments (class_id, student_id) VALUES (?, ?)",
        (class_id, student),
    )
    assignment = execute(
        """
        INSERT INTO assignments (class_id, title, type, status, created_at)
        VALUES (?, 'Reuse AI', 'worksheet', 'published', ?)
        """,
        (class_id, datetime.now().isoformat()),
    )
    question = execute(
        """
        INSERT INTO questions
        (assignment_id, label, topic, question_text, max_marks, mark_scheme_text, page_number, order_index)
        VALUES (?, 'Q1', 'Number', 'Calculate.', 1, 'Answer: 5', 1, 0)
        """,
        (assignment,),
    )
    path = save_upload("reuse_submission.pdf", make_pdf("Q1: 5"))
    submission = execute(
        """
        INSERT INTO submissions (assignment_id, student_id, file_path, status, uploaded_at)
        VALUES (?, ?, ?, 'pending', ?)
        """,
        (assignment, student, path, datetime.now().isoformat()),
    )
    execute(
        """
        INSERT INTO grade_drafts
        (submission_id, question_id, ai_mark, ai_confidence, ai_notes)
        VALUES (?, ?, 1, 0.9, 'Useful old AI suggestion')
        """,
        (submission, question),
    )
    run_grading_job(submission)
    grade = query_one(
        """
        SELECT final_mark, auto_finalized_at, auto_finalize_reason
        FROM grade_drafts WHERE submission_id = ? AND question_id = ?
        """,
        (submission, question),
    )
    sub = query_one("SELECT status FROM submissions WHERE id = ?", (submission,))
    assert_true(sub["status"] == "final", "reused suggestion did not finalize submission")
    assert_true(grade["final_mark"] == 1.0, "reused suggestion did not set final mark")
    assert_true(grade["auto_finalized_at"], "reused suggestion did not backfill auto_finalized_at")
    assert_true(
        grade["auto_finalize_reason"] == "reused_ai_suggestion",
        "reused suggestion did not record reason",
    )
    print("PASS reusable AI suggestion backfills auto-finalized fields")


def test_prediction_requires_four_assessments():
    teacher = seed_user("trajectory-teacher@test.local", "Trajectory Teacher", "teacher")
    student = seed_user("trajectory-student@test.local", "Trajectory Student", "student")
    class_id = execute(
        "INSERT INTO classes (name, teacher_id) VALUES (?, ?)",
        ("Trajectory Class", teacher),
    )
    execute(
        "INSERT INTO class_enrollments (class_id, student_id) VALUES (?, ?)",
        (class_id, student),
    )
    for index, mark in enumerate([4, 5, 6], start=1):
        assignment = execute(
            """
            INSERT INTO assignments (class_id, title, type, status, due_date, created_at)
            VALUES (?, ?, 'worksheet', 'published', ?, ?)
            """,
            (
                class_id,
                f"Trajectory {index}",
                f"2026-06-0{index}",
                datetime.now().isoformat(),
            ),
        )
        question = execute(
            """
            INSERT INTO questions
            (assignment_id, label, topic, max_marks, page_number, order_index)
            VALUES (?, 'Q1', 'Algebra', 10, 1, 0)
            """,
            (assignment,),
        )
        submission = execute(
            """
            INSERT INTO submissions (assignment_id, student_id, file_path, status, uploaded_at)
            VALUES (?, ?, ?, 'final', ?)
            """,
            (assignment, student, "test.pdf", datetime.now().isoformat()),
        )
        execute(
            """
            INSERT INTO grade_drafts
            (submission_id, question_id, ai_mark, final_mark, auto_finalized_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (submission, question, mark, mark, datetime.now().isoformat()),
        )
    assert_true(
        not predict_student_score(student, teacher_id=teacher)["available"],
        "trajectory should be hidden before four assessments",
    )
    assignment = execute(
        """
        INSERT INTO assignments (class_id, title, type, status, due_date, created_at)
        VALUES (?, 'Trajectory 4', 'worksheet', 'published', '2026-06-04', ?)
        """,
        (class_id, datetime.now().isoformat()),
    )
    question = execute(
        """
        INSERT INTO questions
        (assignment_id, label, topic, max_marks, page_number, order_index)
        VALUES (?, 'Q1', 'Algebra', 10, 1, 0)
        """,
        (assignment,),
    )
    submission = execute(
        """
        INSERT INTO submissions (assignment_id, student_id, file_path, status, uploaded_at)
        VALUES (?, ?, 'test.pdf', 'final', ?)
        """,
        (assignment, student, datetime.now().isoformat()),
    )
    execute(
        """
        INSERT INTO grade_drafts
        (submission_id, question_id, ai_mark, final_mark, auto_finalized_at)
        VALUES (?, ?, 7, 7, ?)
        """,
        (submission, question, datetime.now().isoformat()),
    )
    prediction = predict_student_score(student, teacher_id=teacher)
    assert_true(prediction["available"], "trajectory should appear after four assessments")
    assert_true("band" in prediction, "trajectory should expose a band")
    print("PASS trajectory hidden until four assessments")


def main():
    init_db()
    client = TestClient(app)
    test_cross_teacher_assignment_blocked(client)
    test_student_cannot_upload_to_draft(client)
    test_exact_checker_does_not_full_credit_multi_mark()
    test_one_mark_mismatch_auto_zero_without_exception()
    auto_case = test_auto_grading_finalizes_with_risk_flags()
    test_exception_queue_route(client, auto_case["teacher_email"])
    test_non_final_report_blocked(client)
    test_teacher_override_survives_ai_rerun(
        client,
        auto_case["teacher_email"],
        auto_case["submission_id"],
        auto_case["question_id"],
    )
    test_calibration_route_shows_overrides(client, auto_case["teacher_email"])
    test_reusable_ai_suggestion_backfills_auto_finalized()
    test_prediction_requires_four_assessments()
    print("All regression checks passed.")
    tmpdir.cleanup()


if __name__ == "__main__":
    main()
