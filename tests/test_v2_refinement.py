import base64
import json
import os
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path

import fitz
import pytest
from fastapi.testclient import TestClient

from db import execute, hash_password, query_all, query_one
from main import app
from pdf_utils import get_page_image_base64
import self_service


client = TestClient(app)


def pdf_bytes(text: str) -> bytes:
    document = fitz.open()
    page = document.new_page()
    page.insert_text((72, 72), text)
    payload = document.tobytes()
    document.close()
    return payload


def image_bytes(width: int, height: int, text: str) -> bytes:
    document = fitz.open()
    page = document.new_page(width=width, height=height)
    page.insert_text((24, 40), text)
    payload = page.get_pixmap(alpha=False).tobytes("png")
    document.close()
    return payload


def test_ordered_gallery_images_become_one_pdf():
    uploads = [
        ("page-1.png", image_bytes(300, 500, "First page")),
        ("page-2.png", image_bytes(500, 300, "Second page")),
        ("page-3.png", image_bytes(320, 520, "Third page")),
    ]
    filename, payload = self_service.normalize_answer_uploads(uploads)
    assert filename == "completed-work-pages.pdf"
    with fitz.open(stream=payload, filetype="pdf") as document:
        assert len(document) == 3
        assert document[0].rect.height > document[0].rect.width
        assert document[1].rect.width > document[1].rect.height
        assert document[2].rect.height > document[2].rect.width

    with pytest.raises(ValueError, match="not both"):
        self_service.normalize_answer_uploads(
            [("paper.pdf", pdf_bytes("PDF")), uploads[0]]
        )
    with pytest.raises(ValueError, match="no more than"):
        self_service.normalize_answer_uploads([uploads[0]] * 31)


def test_student_can_upload_multiple_gallery_pages():
    create_user("gallery@student.local", "student")
    login("gallery@student.local")
    page = client.get("/student/analyse")
    assert 'name="answer_script"' in page.text
    assert "multiple" in page.text
    assert "capture=" not in page.text
    assert "/static/multi-page-upload.js" in page.text
    assert "img-src 'self' data: blob:" in page.headers["content-security-policy"]

    response = client.post(
        "/student/analyse",
        files=[
            (
                "answer_script",
                ("page-1.png", image_bytes(300, 500, "Page one"), "image/png"),
            ),
            (
                "answer_script",
                ("page-2.png", image_bytes(500, 300, "Page two"), "image/png"),
            ),
            (
                "answer_script",
                ("page-3.png", image_bytes(320, 520, "Page three"), "image/png"),
            ),
        ],
        follow_redirects=False,
    )
    assert response.status_code == 303
    version = query_one(
        """
        SELECT * FROM paper_analysis_versions
        ORDER BY id DESC LIMIT 1
        """
    )
    with fitz.open(version["answer_script_path"]) as document:
        assert len(document) == 3
        assert document[0].rect.height > document[0].rect.width
        assert document[1].rect.width > document[1].rect.height


def test_student_paper_name_is_preserved_and_maximum_is_paper_specific():
    create_user("named-paper@student.local", "student")
    login("named-paper@student.local")
    response = client.post(
        "/student/analyse",
        data={
            "paper_name": "October mock — Paper 1",
            "maximum_marks": "120",
        },
        files={
            "answer_script": (
                "generic-scan-name.pdf",
                pdf_bytes("Q1 visible working"),
                "application/pdf",
            )
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
    assert paper["title"] == "October mock — Paper 1"
    assert version["expected_maximum_marks"] == 120


def test_processing_status_reports_real_heartbeat_and_elapsed_time():
    create_user("heartbeat@student.local", "student")
    paper, version, _ = upload_direct_paper("heartbeat@student.local")
    timestamp = datetime.now().astimezone().isoformat()
    execute(
        """
        UPDATE paper_analysis_versions
        SET status = 'processing', current_stage = 'whole_document_reasoning',
            stage_index = 2, progress_percent = 42,
            progress_message = 'Reading every page and applying the marking evidence',
            progress_detail = '1 completed-work pages',
            heartbeat_at = ?, started_at = ?
        WHERE id = ?
        """,
        (timestamp, timestamp, version["id"]),
    )
    response = client.get(f"/student/analysis/{version['id']}/status")
    assert response.status_code == 200
    payload = response.json()
    assert payload["connection_state"] == "working"
    assert payload["progress_percent"] == 42
    assert payload["heartbeat_age_seconds"] <= 2
    assert payload["elapsed_seconds"] <= 2
    page = client.get(f"/student/analysis/{version['id']}/processing")
    assert "real server heartbeat" in page.text
    assert 'id="elapsed-time"' in page.text

    old_heartbeat = (
        datetime.now().astimezone() - timedelta(seconds=45)
    ).isoformat()
    execute(
        "UPDATE paper_analysis_versions SET heartbeat_at = ? WHERE id = ?",
        (old_heartbeat, version["id"]),
    )
    stalled = client.get(f"/student/analysis/{version['id']}/status").json()
    assert stalled["connection_state"] == "stalled"
    assert stalled["heartbeat_age_seconds"] >= 44


def test_researcher_can_inspect_active_time_and_downloads():
    create_user("tracked@student.local", "student")
    paper, _, _ = upload_direct_paper("tracked@student.local")
    ping = client.post(
        "/student/activity",
        data={"path": "/student/papers", "active_seconds": "61"},
    )
    assert ping.status_code == 200
    report = client.get(f"/student/papers/{paper['id']}/report")
    assert report.status_code == 200
    events = query_all(
        """
        SELECT * FROM student_activity_events
        WHERE student_id = (SELECT id FROM users WHERE email = ?)
        ORDER BY id
        """,
        ("tracked@student.local",),
    )
    assert [event["event_type"] for event in events] == [
        "active_time",
        "download",
    ]
    assert events[0]["active_seconds"] == 61
    assert events[1]["entity_type"] == "paper_report"

    researcher_id = create_user("activity@research.local", "teacher")
    execute(
        "INSERT INTO user_roles (user_id, role, created_at) VALUES (?, 'researcher', ?)",
        (researcher_id, datetime.now().isoformat()),
    )
    hybrid_researcher_id = create_user(
        "hybrid-research@research.local",
        "student",
    )
    execute(
        "INSERT INTO user_roles (user_id, role, created_at) VALUES (?, 'researcher', ?)",
        (hybrid_researcher_id, datetime.now().isoformat()),
    )
    login("activity@research.local")
    dashboard = client.get("/research")
    assert dashboard.status_code == 200
    assert "Student activity" in dashboard.text
    assert "tracked" in dashboard.text
    assert "Paper report" in dashboard.text
    assert "hybrid-research" not in dashboard.text


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


def test_analysis_ocr_processes_pages_concurrently_and_preserves_order(
    tmp_path, monkeypatch
):
    path = tmp_path / "long-scan.pdf"
    document = fitz.open()
    for page_number in range(1, 9):
        page = document.new_page()
        page.insert_text((72, 72), f"Page {page_number}")
    document.save(path)
    document.close()

    state = {"active": 0, "peak": 0}
    lock = threading.Lock()

    def fake_ocr(_image):
        with lock:
            state["active"] += 1
            state["peak"] = max(state["peak"], state["active"])
        time.sleep(0.08)
        with lock:
            state["active"] -= 1
        return "OCR text", 0.95, {
            "_sumkora": {"used_model": "test-ocr"}
        }

    monkeypatch.setattr(self_service.config, "OCR_ENABLED", True)
    monkeypatch.setattr(self_service.config, "OCR_PAGE_CONCURRENCY", 4)
    monkeypatch.setattr(
        self_service,
        "get_page_image_base64",
        lambda *_args, **_kwargs: "image",
    )
    monkeypatch.setattr(self_service, "cxsee_vl_ocr_detailed", fake_ocr)
    monkeypatch.setattr(self_service, "execute", lambda *_args, **_kwargs: 1)

    started = time.monotonic()
    pages, confidences = self_service._extract_analysis_document(
        {
            "id": 999,
            "image_resolution": 200,
            "ocr_model": "test-ocr",
            "ocr_prompt_version": "test-prompt",
        },
        "answer_script",
        str(path),
        force_vision=True,
    )
    duration = time.monotonic() - started

    assert list(sorted(pages)) == list(range(1, 9))
    assert list(sorted(confidences)) == list(range(1, 9))
    assert 2 <= state["peak"] <= 4
    assert duration < 0.45


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


def test_active_whole_document_analysis_never_runs_page_ocr(monkeypatch):
    create_user("direct-pdf@student.local", "student")

    def fail_if_called(*_args, **_kwargs):
        raise AssertionError("the active direct-PDF path must not run page OCR")

    monkeypatch.setattr(
        self_service,
        "_extract_analysis_document",
        fail_if_called,
    )
    paper, version, _ = upload_direct_paper("direct-pdf@student.local")
    assert paper["status"] == "completed"
    assert version["status"] == "completed"


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
