import base64
import json
import os
from datetime import datetime
from pathlib import Path

import fitz
from fastapi.testclient import TestClient

from db import execute, hash_password, query_all, query_one
from main import app
from pdf_utils import get_page_image_base64


client = TestClient(app)


def pdf_bytes(text: str) -> bytes:
    document = fitz.open()
    page = document.new_page()
    page.insert_text((72, 72), text)
    payload = document.tobytes()
    document.close()
    return payload


def test_metadata_rotated_scans_render_upright(tmp_path):
    path = tmp_path / "rotated-scan.pdf"
    document = fitz.open()
    page = document.new_page(width=842, height=1191)
    page.insert_text((72, 120), "Question 1")
    page.set_rotation(270)
    document.save(path)
    document.close()

    rendered = fitz.Pixmap(
        base64.b64decode(get_page_image_base64(str(path), 1, 90))
    )
    assert rendered.height > rendered.width


def create_user(email: str, role: str):
    user_id = execute(
        """
        INSERT INTO users (email, password_hash, name, role)
        VALUES (?, ?, ?, ?)
        """,
        (email, hash_password("pass123"), email.split("@")[0], role),
    )
    execute(
        """
        INSERT INTO user_roles (user_id, role, created_at)
        VALUES (?, ?, ?)
        """,
        (user_id, role, datetime.now().isoformat()),
    )
    return user_id


def login(email: str):
    client.cookies.clear()
    response = client.post(
        "/login",
        data={"email": email, "password": "pass123"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    client.cookies.update(response.cookies)


def upload_direct_paper(email: str, title: str = "Independent Paper"):
    login(email)
    response = client.post(
        "/student/analyse",
        data={"title": title},
        files={
            "answer_script": (
                "answers.pdf",
                pdf_bytes("Q1: derivative is 2x"),
                "application/pdf",
            ),
            "mark_scheme": (
                "scheme.pdf",
                pdf_bytes("1 Differentiate x squared. M1 apply power rule A1 2x [4]"),
                "application/pdf",
            ),
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    version_id = int(response.headers["location"].split("/")[3])
    version = query_one(
        "SELECT * FROM paper_analysis_versions WHERE id = ?",
        (version_id,),
    )
    paper = query_one(
        "SELECT * FROM student_papers WHERE id = ?",
        (version["paper_id"],),
    )
    questions = json.loads(version["question_plan"])
    return paper, version, questions


def confirm_and_run(version_id: int, questions: list[dict], title: str):
    current = query_one(
        "SELECT status FROM paper_analysis_versions WHERE id = ?",
        (version_id,),
    )
    if current["status"] == "completed":
        return
    response = client.post(
        f"/student/analysis/{version_id}/run",
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert query_one(
        "SELECT status FROM paper_analysis_versions WHERE id = ?",
        (version_id,),
    )["status"] == "completed"


def test_student_self_service_without_class_and_question_paper():
    student_id = create_user("independent@student.local", "student")
    assert query_one(
        "SELECT COUNT(*) AS n FROM class_enrollments WHERE student_id = ?",
        (student_id,),
    )["n"] == 0
    paper, version, questions = upload_direct_paper(
        "independent@student.local"
    )
    assert paper["student_id"] == student_id
    assert not version["question_paper_path"]
    assert version["answer_script_path"]
    assert version["mark_scheme_path"]
    assert version["status"] == "completed"
    confirm_and_run(version["id"], questions, paper["title"])
    assert query_one(
        "SELECT COUNT(*) AS n FROM analysis_question_results WHERE analysis_version_id = ?",
        (version["id"],),
    )["n"] >= 1


def test_optional_maximum_marks_is_stored_for_estimate_coverage_checks():
    create_user("maximum@student.local", "student")
    login("maximum@student.local")
    page = client.get("/student/analyse")
    assert 'name="maximum_marks"' in page.text
    assert "Maximum marks on the paper" in page.text

    response = client.post(
        "/student/analyse",
        data={"maximum_marks": "80"},
        files={
            "answer_script": (
                "answers.pdf",
                pdf_bytes("Q1 visible work"),
                "application/pdf",
            )
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    version_id = int(response.headers["location"].split("/")[3])
    version = query_one(
        "SELECT expected_maximum_marks FROM paper_analysis_versions WHERE id = ?",
        (version_id,),
    )
    assert version["expected_maximum_marks"] == 80

    invalid = client.post(
        "/student/analyse",
        data={"maximum_marks": "80.5"},
        files={
            "answer_script": (
                "answers.pdf",
                pdf_bytes("Q1 visible work"),
                "application/pdf",
            )
        },
    )
    assert invalid.status_code == 400
    assert "whole number from 1 to 500" in invalid.text


def test_upload_validation_handles_duplicates_invalid_and_unicode_files():
    create_user("validation@student.local", "student")
    login("validation@student.local")
    repeated = pdf_bytes("Repeated document")
    duplicate = client.post(
        "/student/analyse",
        files={
            "answer_script": ("answers.pdf", repeated, "application/pdf"),
            "mark_scheme": ("scheme.pdf", repeated, "application/pdf"),
        },
        follow_redirects=False,
    )
    assert duplicate.status_code == 400
    assert "different document" in duplicate.text

    invalid = client.post(
        "/student/analyse",
        files={
            "answer_script": ("answers.pdf", b"not a pdf", "application/pdf"),
            "mark_scheme": (
                "scheme.pdf",
                pdf_bytes("Q1 mark scheme"),
                "application/pdf",
            ),
        },
        follow_redirects=False,
    )
    assert invalid.status_code == 400
    assert "PDF, PNG, JPEG, or WebP" in invalid.text

    unicode_upload = client.post(
        "/student/analyse",
        files={
            "answer_script": (
                "已完成的答卷.pdf",
                pdf_bytes("Q1 2x"),
                "application/pdf",
            ),
            "mark_scheme": (
                "评分标准.pdf",
                pdf_bytes("Q1 M1 power rule A1 2x [2]"),
                "application/pdf",
            ),
        },
        follow_redirects=False,
    )
    assert unicode_upload.status_code == 303


def test_direct_results_are_owned_and_legacy_teacher_routes_are_archived():
    owner_id = create_user("owner-v2@research.local", "teacher")
    execute(
        """
        INSERT INTO user_roles (user_id, role, created_at)
        VALUES (?, 'researcher', ?)
        """,
        (owner_id, datetime.now().isoformat()),
    )
    student_a = create_user("owner-a@student.local", "student")
    create_user("owner-b@student.local", "student")
    paper, version, questions = upload_direct_paper("owner-a@student.local")
    confirm_and_run(version["id"], questions, paper["title"])

    login("owner-b@student.local")
    assert client.get(
        f"/student/papers/{paper['id']}", follow_redirects=False
    ).status_code == 303
    assert client.get(
        f"/student/papers/{paper['id']}/documents/answers"
    ).status_code == 404
    assert client.get("/research", follow_redirects=False).status_code == 303

    login("owner-v2@research.local")
    assert client.get("/", follow_redirects=False).headers["location"] == "/research"
    response = client.get("/teacher/classes", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/research"
    assert client.get("/research").status_code == 200


def test_rerun_preserves_versions_and_original_results():
    create_user("versions@student.local", "student")
    paper, version_one, questions = upload_direct_paper("versions@student.local")
    confirm_and_run(version_one["id"], questions, paper["title"])
    original_results = [
        dict(row)
        for row in query_all(
            "SELECT * FROM analysis_question_results WHERE analysis_version_id = ?",
            (version_one["id"],),
        )
    ]
    response = client.post(
        f"/student/papers/{paper['id']}/rerun",
        files={
            "answer_script": (
                "clearer.pdf",
                pdf_bytes("Q1: clearer working gives 2x"),
                "application/pdf",
            )
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    version_two_id = int(response.headers["location"].split("/")[3])
    version_two = query_one(
        "SELECT * FROM paper_analysis_versions WHERE id = ?",
        (version_two_id,),
    )
    confirm_and_run(
        version_two_id,
        json.loads(version_two["question_plan"]),
        paper["title"],
    )
    assert query_one(
        "SELECT COUNT(*) AS n FROM paper_analysis_versions WHERE paper_id = ?",
        (paper["id"],),
    )["n"] == 2
    preserved = [
        dict(row)
        for row in query_all(
            "SELECT * FROM analysis_question_results WHERE analysis_version_id = ?",
            (version_one["id"],),
        )
    ]
    assert preserved == original_results


def test_failed_analysis_hides_provider_details_and_offers_retry():
    create_user("retry@student.local", "student")
    paper, version, _ = upload_direct_paper("retry@student.local")
    execute(
        """
        UPDATE paper_analysis_versions
        SET status = 'failed',
            failure_message = 'HTTP 503 from provider-internal.example'
        WHERE id = ?
        """,
        (version["id"],),
    )

    status = client.get(f"/student/analysis/{version['id']}/status")
    assert status.status_code == 200
    assert status.json()["status"] == "failed"
    assert "provider-internal" not in status.json()["failure_message"]
    assert "Try again" in status.json()["failure_message"]

    page = client.get(f"/student/analysis/{version['id']}/processing")
    assert page.status_code == 200
    assert f'href="/student/papers/{paper["id"]}/rerun"' in page.text
    assert "Try again" in page.text


def test_provider_failure_records_no_question_zero_marks(monkeypatch):
    import self_service

    create_user("no-false-zero@student.local", "student")
    login("no-false-zero@student.local")

    def fail_provider(*_args, **_kwargs):
        raise RuntimeError("synthetic provider outage")

    monkeypatch.setattr(self_service, "assess_documents", fail_provider)
    response = client.post(
        "/student/analyse",
        files={
            "answer_script": (
                "answers.pdf",
                pdf_bytes("Q1 visible work"),
                "application/pdf",
            )
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    version_id = int(response.headers["location"].split("/")[3])
    version = query_one(
        "SELECT status, failure_message FROM paper_analysis_versions WHERE id = ?",
        (version_id,),
    )
    assert version["status"] == "failed"
    assert "No zero marks were recorded" in version["failure_message"]
    assert query_one(
        """
        SELECT COUNT(*) AS n FROM analysis_question_results
        WHERE analysis_version_id = ?
        """,
        (version_id,),
    )["n"] == 0


def test_multiple_experiments_edit_run_and_separate_human_label():
    owner_id = create_user("lab-owner@research.local", "teacher")
    execute(
        "INSERT INTO user_roles (user_id, role, created_at) VALUES (?, 'researcher', ?)",
        (owner_id, datetime.now().isoformat()),
    )
    create_user("labelled@student.local", "student")
    paper, version, questions = upload_direct_paper("labelled@student.local")
    confirm_and_run(version["id"], questions, paper["title"])
    result = query_one(
        "SELECT * FROM analysis_question_results WHERE analysis_version_id = ? LIMIT 1",
        (version["id"],),
    )
    original_mark = result["ai_mark"]

    login("lab-owner@research.local")
    experiment_ids = []
    for suffix in ("A", "B"):
        response = client.post(
            "/research/experiments",
            data={
                "title": f"Prompt experiment {suffix}",
                "research_question": "Which prompt agrees with labels?",
                "hypothesis": f"Variant {suffix} improves agreement.",
            },
            follow_redirects=False,
        )
        assert response.status_code == 303
        experiment_ids.append(int(response.headers["location"].split("/")[-1]))
    assert len(set(experiment_ids)) == 2
    detail = client.get(f"/research/experiments/{experiment_ids[0]}")
    assert detail.status_code == 200
    assert "Prompt experiment A" in detail.text
    assert "<main" in detail.text
    response = client.post(
        f"/research/experiments/{experiment_ids[0]}/edit",
        data={
            "title": "Edited prompt experiment",
            "status": "ready",
            "dataset_selection": "{}",
            "preprocessing_config": "{}",
            "longitudinal_config": "{}",
            "evaluation_metrics": "[]",
            "confidence_threshold": ".8",
            "image_resolution": "220",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert query_one(
        "SELECT title FROM research_experiments WHERE id = ?",
        (experiment_ids[0],),
    )["title"] == "Edited prompt experiment"

    client.post(
        f"/research/grading/{result['id']}/correct",
        data={
            "corrected_mark": "1",
            "corrected_decision": "awarded",
            "failure_explanation": "Synthetic human label",
        },
    )
    assert query_one(
        "SELECT ai_mark FROM analysis_question_results WHERE id = ?",
        (result["id"],),
    )["ai_mark"] == original_mark
    assert query_one(
        "SELECT COUNT(*) AS n FROM analysis_human_corrections WHERE analysis_question_result_id = ?",
        (result["id"],),
    )["n"] == 1

    client.post(
        f"/research/experiments/{experiment_ids[0]}/run",
        follow_redirects=False,
    )
    assert query_one(
        "SELECT COUNT(*) AS n FROM research_experiment_runs WHERE experiment_id = ?",
        (experiment_ids[0],),
    )["n"] == 1


def test_student_and_research_pdfs_render():
    create_user("pdf@student.local", "student")
    paper, version, questions = upload_direct_paper("pdf@student.local")
    confirm_and_run(version["id"], questions, paper["title"])
    response = client.get(
        f"/student/papers/{paper['id']}/report?version={version['id']}"
    )
    assert response.status_code == 200
    disposition = response.headers["content-disposition"]
    assert 'filename="sumkora-' in disposition
    assert disposition.endswith('-paper-report.pdf"')
    student_pdf = fitz.open(stream=response.content, filetype="pdf")
    assert len(student_pdf) >= 1
    assert all(page.rect.width > 500 and page.rect.height > 700 for page in student_pdf)
    student_text = "".join(page.get_text() for page in student_pdf)
    assert "Paper analysis" in student_text
    assert "Sumkora" in student_text
    assert all(
        0 <= block[0] <= block[2] <= page.rect.width
        and 0 <= block[1] <= block[3] <= page.rect.height
        for page in student_pdf
        for block in page.get_text("blocks")
    )
    qa_dir = os.getenv("SUMKORA_PDF_QA_DIR") or os.getenv("NUMERA_PDF_QA_DIR")
    if qa_dir:
        Path(qa_dir).mkdir(parents=True, exist_ok=True)
        Path(qa_dir, "student-report.pdf").write_bytes(response.content)
    student_pdf.close()

    owner_id = create_user("pdf-owner@research.local", "teacher")
    execute(
        "INSERT INTO user_roles (user_id, role, created_at) VALUES (?, 'researcher', ?)",
        (owner_id, datetime.now().isoformat()),
    )
    login("pdf-owner@research.local")
    response = client.post(
        "/research/experiments",
        data={"title": "PDF experiment"},
        follow_redirects=False,
    )
    experiment_id = int(response.headers["location"].split("/")[-1])
    research_pdf = client.get(
        f"/research/experiments/{experiment_id}/report"
    )
    assert research_pdf.status_code == 200
    assert (
        f"sumkora-research-experiment-{experiment_id}-report.pdf"
        in research_pdf.headers["content-disposition"]
    )
    document = fitz.open(stream=research_pdf.content, filetype="pdf")
    assert len(document) >= 1
    research_text = "".join(page.get_text() for page in document)
    assert "Research experiment" in research_text
    assert "Sumkora" in research_text
    assert all(
        0 <= block[0] <= block[2] <= page.rect.width
        and 0 <= block[1] <= block[3] <= page.rect.height
        for page in document
        for block in page.get_text("blocks")
    )
    if qa_dir:
        Path(qa_dir, "research-report.pdf").write_bytes(research_pdf.content)
    document.close()
