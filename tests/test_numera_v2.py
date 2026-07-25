from datetime import datetime, timedelta

import fitz
from fastapi.testclient import TestClient

from assessment import (
    compare_papers,
    student_skill_profile,
    sync_submission_evidence,
)
from db import execute, hash_password, init_db, query_one
from main import app
from math_checks import (
    antiderivative_equivalence,
    derivative_equivalence,
    numerical_equivalence,
    symbolic_equivalence,
)
from pdf_utils import save_upload


client = TestClient(app)


def make_pdf(text: str) -> bytes:
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), text)
    payload = doc.tobytes()
    doc.close()
    return payload


def seed_user(email: str, role: str, name: str = "Test User"):
    user_id = execute(
        "INSERT INTO users (email, password_hash, name, role) VALUES (?, ?, ?, ?)",
        (email, hash_password("pass123"), name, role),
    )
    execute(
        "INSERT INTO user_roles (user_id, role, created_at) VALUES (?, ?, ?)",
        (user_id, role, datetime.now().isoformat()),
    )
    return user_id


def login(email: str):
    response = client.post(
        "/login",
        data={"email": email, "password": "pass123"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    return response.cookies


def create_attempt(student_id: int, teacher_id: int, suffix: str, mark: float, when: datetime):
    class_id = execute(
        "INSERT INTO classes (name, teacher_id) VALUES (?, ?)",
        (f"Class {suffix}", teacher_id),
    )
    execute(
        "INSERT INTO class_enrollments (class_id, student_id) VALUES (?, ?)",
        (class_id, student_id),
    )
    assignment_id = execute(
        """
        INSERT INTO assignments
        (class_id, title, type, total_marks, status, created_at, syllabus_code,
         syllabus_version, paper_component, calculator_policy)
        VALUES (?, ?, 'past_paper', 4, 'published', ?, '0606', '2025-2027', ?,
                'non-calculator')
        """,
        (class_id, f"0606 Paper {suffix}", when.isoformat(), suffix),
    )
    question_id = execute(
        """
        INSERT INTO questions
        (assignment_id, label, topic, subtopic, question_text, max_marks,
         mark_scheme_text, page_number, order_index)
        VALUES (?, 'Q1', 'Calculus', 'differentiation', 'Differentiate x^2.',
                4, 'M1 method A1 accuracy', 1, 0)
        """,
        (assignment_id,),
    )
    path = save_upload(f"{suffix}.pdf", make_pdf("Q1: 2x"))
    submission_id = execute(
        """
        INSERT INTO submissions
        (assignment_id, student_id, file_path, status, uploaded_at)
        VALUES (?, ?, ?, 'final', ?)
        """,
        (assignment_id, student_id, path, when.isoformat()),
    )
    execute(
        """
        INSERT INTO grade_drafts
        (submission_id, question_id, ai_mark, ai_confidence, ai_notes,
         final_mark, risk_flags, needs_exception_review, auto_finalized_at)
        VALUES (?, ?, ?, 0.9, 'Synthetic evidence', ?, '[]', 0, ?)
        """,
        (submission_id, question_id, mark, mark, when.isoformat()),
    )
    return submission_id, question_id


def test_auth_ownership_and_research_authorization():
    init_db()
    teacher = seed_user("owner@test.local", "teacher", "Owner")
    execute(
        "INSERT INTO user_roles (user_id, role, created_at) VALUES (?, 'researcher', ?)",
        (teacher, datetime.now().isoformat()),
    )
    student_a = seed_user("student-a@test.local", "student")
    student_b = seed_user("student-b@test.local", "student")
    attempt_b, _ = create_attempt(
        student_b, teacher, "11", 2, datetime.now() - timedelta(days=1)
    )

    cookies_a = login("student-a@test.local")
    assert client.get("/student", cookies=cookies_a).status_code == 200
    blocked_result = client.get(
        f"/student/results/{attempt_b}", cookies=cookies_a, follow_redirects=False
    )
    assert blocked_result.status_code == 303
    assert blocked_result.headers["location"] == "/student"
    assert client.get(
        f"/student/submissions/{attempt_b}/file", cookies=cookies_a
    ).status_code == 404
    assert client.get(
        "/research", cookies=cookies_a, follow_redirects=False
    ).status_code == 303
    client.cookies.clear()
    assert client.get("/student", follow_redirects=False).status_code == 303

    owner_cookies = login("owner@test.local")
    assert client.get("/research", cookies=owner_cookies).status_code == 200


def test_cross_site_post_is_rejected():
    response = client.post(
        "/login",
        data={"email": "nobody@example.com", "password": "bad"},
        headers={"Origin": "https://attacker.example"},
    )
    assert response.status_code == 403


def test_three_paper_longitudinal_scenario_and_comparison():
    teacher = seed_user("long-owner@test.local", "teacher")
    student = seed_user("long-student@test.local", "student")
    start = datetime.now() - timedelta(days=60)

    first, _ = create_attempt(student, teacher, "A", 0, start)
    sync_submission_evidence(first)
    state = query_one(
        "SELECT * FROM student_skill_states WHERE student_id = ? AND skill = 'differentiation'",
        (student,),
    )
    assert state["status"] == "early signal"

    second, _ = create_attempt(student, teacher, "B", 0, start + timedelta(days=30))
    sync_submission_evidence(second)
    state = query_one(
        "SELECT * FROM student_skill_states WHERE student_id = ? AND skill = 'differentiation'",
        (student,),
    )
    assert state["status"] == "recurring concern"

    third, _ = create_attempt(student, teacher, "C", 4, start + timedelta(days=60))
    sync_submission_evidence(third)
    state = query_one(
        "SELECT * FROM student_skill_states WHERE student_id = ? AND skill = 'differentiation'",
        (student,),
    )
    assert state["status"] == "improving"
    assert state["evidence_count"] == 3

    profile = student_skill_profile(student)
    assert any(item["skill"] == "integration" for item in profile["untested"])
    comparison = compare_papers(student, [first, third])
    assert len(comparison["papers"]) == 2
    assert comparison["papers"][0]["percentage"] == 0
    assert comparison["papers"][1]["percentage"] == 100


def test_score_ranges_and_criterion_decisions():
    teacher = seed_user("range-owner@test.local", "teacher")
    student = seed_user("range-student@test.local", "student")
    submission, _ = create_attempt(student, teacher, "R", 2, datetime.now())
    execute(
        """
        UPDATE grade_drafts
        SET ai_confidence = 0.4, needs_exception_review = 1,
            risk_flags = '["low_model_confidence"]'
        WHERE submission_id = ?
        """,
        (submission,),
    )
    result = sync_submission_evidence(submission)
    assert result["confirmed_min"] == 0
    assert result["provisional"] == 2
    assert result["possible_max"] == 4
    decision = query_one(
        "SELECT * FROM criterion_decisions WHERE submission_id = ?",
        (submission,),
    )
    assert decision["decision"] == "uncertain"
    assert decision["available_marks"] == 4


def test_research_exports_are_protected_and_pseudonymized():
    owner = seed_user("export-owner@test.local", "teacher")
    execute(
        "INSERT INTO user_roles (user_id, role, created_at) VALUES (?, 'researcher', ?)",
        (owner, datetime.now().isoformat()),
    )
    cookies = login("export-owner@test.local")
    response = client.get(
        "/research/export?format=json&mode=pseudonymized", cookies=cookies
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    client.cookies.clear()
    assert client.get(
        "/research/export?format=json", follow_redirects=False
    ).status_code == 303


def test_deterministic_math_checks():
    assert symbolic_equivalence("(x+1)^2", "x^2+2*x+1").equivalent is True
    assert numerical_equivalence("sqrt(2)^2", "2").equivalent is True
    assert derivative_equivalence("3*x^2", "x^3").equivalent is True
    assert antiderivative_equivalence("x^3/3 + 7", "x^2").equivalent is True
