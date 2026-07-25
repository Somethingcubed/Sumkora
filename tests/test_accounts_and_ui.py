import re

import fitz
from fastapi.testclient import TestClient

from accounts import count_label
from db import query_all, query_one, verify_password
from main import app
from self_service import detect_document_texts, detect_documents


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
    assert user["email"].endswith("@accounts.sumkora.invalid")
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
    assert "/processing" in response.headers["location"]
    assert query_one(
        """
        SELECT status FROM paper_analysis_versions
        WHERE paper_id = (
            SELECT id FROM student_papers
            WHERE student_id = ? ORDER BY id DESC LIMIT 1
        )
        """,
        (user["id"],),
    )["status"] == "completed"


def test_question_detection_is_automatic_sorted_and_merges_sources():
    detected = detect_document_texts(
        """
        Q2 Solve the quadratic equation. [3]
        Q1 Simplify the algebraic expression. [2]
        Q6 (a) Differentiate the function. [2]
        Q6 (b) Find the stationary point. [3]
        """,
        """
        Q3 Sketch the graph and state the range. [4]
        Q1 A1 simplified expression [2]
        """,
    )
    assert [item["label"] for item in detected["questions"]] == [
        "Q1",
        "Q2",
        "Q3",
        "Q6",
    ]
    q6 = next(item for item in detected["questions"] if item["label"] == "Q6")
    assert q6["maximum_marks"] == 5


def test_cambridge_layout_ignores_page_numbers_and_marking_principles(tmp_path):
    question_path = tmp_path / "question.pdf"
    document = fitz.open()
    cover = document.new_page()
    cover.insert_text((50, 90), "2 hours")
    cover.insert_text((50, 120), "1 Answer every question in the spaces provided.")
    formula = document.new_page()
    formula.insert_text((295, 40), "2")
    formula.insert_text((200, 100), "1")
    page = document.new_page()
    page.insert_text((295, 40), "3")
    page.insert_text((50, 90), "1 Solve the inequality. [3]")
    page = document.new_page()
    page.insert_text((295, 40), "4")
    page.insert_text((50, 70), "2 Differentiate the function. [2]")
    page.insert_text((50, 260), "3 Find the area under the curve. [4]")
    document.save(question_path)
    document.close()

    scheme_path = tmp_path / "scheme.pdf"
    document = fitz.open()
    principles = document.new_page()
    principles.insert_text((50, 90), "Generic Marking Principles")
    principles.insert_text((50, 120), "1 Award marks positively.")
    table = document.new_page()
    table.insert_text((58, 70), "Question Answer Marks Guidance")
    table.insert_text((70, 100), "1 x > 3 M1 A1")
    table.insert_text((70, 180), "2 derivative M1 A1")
    table.insert_text((70, 260), "3 integral M1 A1 A1 A1")
    document.save(scheme_path)
    document.close()

    detected = detect_documents(str(question_path), str(scheme_path))
    assert [item["label"] for item in detected["questions"]] == ["Q1", "Q2", "Q3"]
    assert [item["maximum_marks"] for item in detected["questions"]] == [3, 2, 4]
    assert all(item["mark_scheme_text"] for item in detected["questions"])


def test_language_switch_translates_the_student_product():
    client.cookies.clear()
    client.get("/lang/zh", headers={"referer": "http://testserver/signup"})
    signup = client.get("/signup")
    assert "创建 Sumkora 账号" in signup.text
    assert 'href="/lang/en"' in signup.text
    assert 'href="/lang/zh"' in signup.text

    assert sign_up("ChineseStudent").status_code == 200
    client.cookies.set("lang", "zh")
    dashboard = client.get("/student")
    assert "从一份已完成的试卷开始" in dashboard.text
    assert "分析试卷" in dashboard.text


def test_sumkora_branding_metadata_and_assets_are_consistent():
    client.cookies.clear()
    login_page = client.get("/login")
    assert login_page.status_code == 200
    assert "<title>Log in — Sumkora</title>" in login_page.text
    assert 'rel="canonical" href="https://sumkora.com/login"' in login_page.text
    assert 'property="og:site_name" content="Sumkora"' in login_page.text
    assert "Numera" not in login_page.text
    assert client.get("/static/favicon.svg").status_code == 200
    manifest = client.get("/static/site.webmanifest")
    assert manifest.status_code == 200
    assert manifest.json()["name"] == "Sumkora"


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
