import re

import fitz
from fastapi.testclient import TestClient

from accounts import count_label
from db import query_all, query_one, verify_password
from main import app


client = TestClient(app)


def sign_up(username: str, password: str = "calculus café"):
    client.cookies.clear()
    return client.post(
        "/signup",
        data={
            "username": username,
            "password": password,
            "password_confirmation": password,
            "display_name": "",
        },
        follow_redirects=False,
    )


def log_in(identifier: str, password: str):
    client.cookies.clear()
    response = client.post(
        "/login",
        data={"identifier": identifier, "password": password},
        follow_redirects=False,
    )
    if response.status_code == 303:
        client.cookies.update(response.cookies)
    return response


def make_pdf(text: str) -> bytes:
    document = fitz.open()
    page = document.new_page()
    page.insert_text((72, 72), text)
    content = document.tobytes()
    document.close()
    return content


def test_student_signup_needs_no_email_and_creates_only_student_access():
    response = sign_up("PaperPilot")
    assert response.status_code == 200
    assert "Account created" in response.text
    assert client.get("/student").status_code == 200

    user = query_one(
        "SELECT * FROM users WHERE username_normalized = 'paperpilot'"
    )
    assert user["role"] == "student"
    assert user["email"].endswith("@accounts.numera.invalid")
    roles = [
        row["role"]
        for row in query_all(
            "SELECT role FROM user_roles WHERE user_id = ?",
            (user["id"],),
        )
    ]
    assert roles == ["student"]
    assert client.get("/research", follow_redirects=False).status_code == 303


def test_username_uniqueness_login_case_and_trim_normalization():
    assert sign_up("  VectorFox  ").status_code == 200
    duplicate = sign_up("VECTORFOX")
    assert duplicate.status_code == 400
    assert "already taken" in duplicate.text

    login = log_in("  vEcToRfOx  ", "calculus café")
    assert login.status_code == 303
    assert login.headers["location"] == "/"


def test_username_and_password_validation_messages():
    spaced = sign_up("bad name")
    assert spaced.status_code == 400
    assert "cannot contain spaces" in spaced.text

    invalid = sign_up("bad.name")
    assert invalid.status_code == 400
    assert "3–24 letters" in invalid.text

    client.cookies.clear()
    mismatch = client.post(
        "/signup",
        data={
            "username": "MismatchUser",
            "password": "abcdefgh",
            "password_confirmation": "abcdefgi",
        },
    )
    assert mismatch.status_code == 400
    assert "Passwords do not match" in mismatch.text

    short = sign_up("ShortPassword", password="short")
    assert short.status_code == 400
    assert "at least 8 characters" in short.text


def test_password_is_hashed_and_unicode_safe():
    password = "数学习题 café 🔐"
    assert sign_up("UnicodeMath", password=password).status_code == 200
    user = query_one(
        "SELECT password_hash FROM users WHERE username_normalized = 'unicodemath'"
    )
    assert password not in user["password_hash"]
    assert user["password_hash"].startswith("bcrypt-sha256$")
    assert verify_password(password, user["password_hash"])


def test_recovery_code_is_one_time_and_resets_password():
    response = sign_up("Recoverable")
    code = re.search(r"[A-F0-9]{4}(?:-[A-F0-9]{4}){5}", response.text).group(0)
    client.cookies.clear()
    reset = client.post(
        "/recover",
        data={
            "username": "RECOVERABLE",
            "recovery_code": code,
            "password": "new password ✓",
            "password_confirmation": "new password ✓",
        },
        follow_redirects=False,
    )
    assert reset.status_code == 303
    assert log_in("recoverable", "new password ✓").status_code == 303
    assert query_one(
        "SELECT recovery_code_hash FROM users WHERE username_normalized = 'recoverable'"
    )["recovery_code_hash"] is None

    client.cookies.clear()
    reused = client.post(
        "/recover",
        data={
            "username": "recoverable",
            "recovery_code": code,
            "password": "another password",
            "password_confirmation": "another password",
        },
    )
    assert reused.status_code == 400


def test_new_student_can_upload_three_files_without_a_class():
    assert sign_up("UploadReady").status_code == 200
    user = query_one(
        "SELECT id FROM users WHERE username_normalized = 'uploadready'"
    )
    assert query_one(
        "SELECT COUNT(*) AS n FROM class_enrollments WHERE student_id = ?",
        (user["id"],),
    )["n"] == 0
    response = client.post(
        "/student/analyse",
        data={"title": "My first paper"},
        files={
            "question_paper": (
                "questions.pdf",
                make_pdf("Q1 Differentiate x squared [2]"),
                "application/pdf",
            ),
            "answer_script": (
                "work.pdf",
                make_pdf("Q1 2x"),
                "application/pdf",
            ),
            "mark_scheme": (
                "scheme.pdf",
                make_pdf("Q1 A1 2x [2]"),
                "application/pdf",
            ),
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert "/review" in response.headers["location"]


def test_existing_student_and_researcher_logins_still_work():
    assert log_in("STUDENT", "student123").status_code == 303
    assert client.get("/student").status_code == 200
    assert log_in("TEACHER@SCHOOL.EDU", "teacher123").status_code == 303
    assert client.get("/", follow_redirects=False).headers["location"] == "/research"


def test_pluralization_and_student_copy_audit():
    assert count_label(0, "paper") == "0 papers"
    assert count_label(1, "paper") == "1 paper"
    assert count_label(2, "analysis", "analyses") == "2 analyses"

    client.cookies.clear()
    signup = client.get("/signup")
    assert 'name="email"' not in signup.text
    assert 'name="username"' in signup.text

    sign_up("CleanCopy")
    dashboard = client.get("/student")
    upload = client.get("/student/analyse")
    combined = f"{dashboard.text}\n{upload.text}".lower()
    assert "teacher dashboard" not in combined
    assert ">classes<" not in combined
    assert ">assignments<" not in combined
    assert "database" not in combined
    assert "pipeline" not in combined
    assert "model output" not in combined
