"""End-to-end checks for progress, mistakes, worksheets, and ZIP ingestion."""

import io
import json
import zipfile
from datetime import datetime, timezone

import fitz
from fastapi.testclient import TestClient
import learning
import question_solver

from assessment import rebuild_student_profile, student_skill_profile
from auth import create_session_token
from db import execute, hash_password, query_one
from learning import (
    _PdfFlow,
    cached_mistake_book_pdf,
    create_practice_set,
    mistake_book,
    mistake_book_pdf,
    prepare_mistake_recovery_batch,
    practice_pdf,
    practice_set_detail,
    refresh_mistake_book_pdf_cache,
    skill_detail,
)
from main import app
from question_bank import _question_labels, ingest_question_bank_zip
from reports import profile_report
from self_service import _match_question_bank_parent


client = TestClient(app)


def now():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def create_student(email: str):
    student_id = execute(
        "INSERT INTO users (email, password_hash, name, role) VALUES (?, ?, ?, 'student')",
        (email, hash_password("pass123"), "Learning Student"),
    )
    execute(
        "INSERT INTO user_roles (user_id, role, created_at) VALUES (?, 'student', ?)",
        (student_id, now()),
    )
    return student_id


def create_researcher(email: str):
    researcher_id = execute(
        "INSERT INTO users (email, password_hash, name, role) VALUES (?, ?, ?, 'teacher')",
        (email, hash_password("pass123"), "Question Bank Researcher"),
    )
    execute(
        "INSERT INTO user_roles (user_id, role, created_at) VALUES (?, 'researcher', ?)",
        (researcher_id, now()),
    )
    return researcher_id


def login(email: str):
    client.cookies.clear()
    response = client.post(
        "/login",
        data={"email": email, "password": "pass123"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    return response.cookies


def seed_direct_observation(student_id: int):
    paper_id = execute(
        """
        INSERT INTO student_papers
        (student_id, title, syllabus_code, paper_number, calculator_policy,
         maximum_marks, source_type, status, latest_version_number,
         created_at, updated_at)
        VALUES (?, '0606/11/O/N/25', '0606', '11', 'non-calculator',
                5, 'official', 'completed', 1, ?, ?)
        """,
        (student_id, now(), now()),
    )
    version_id = execute(
        """
        INSERT INTO paper_analysis_versions
        (paper_id, version_number, question_paper_path, answer_script_path,
         status, current_stage, assessment_mode, assessment_summary,
         created_at, updated_at)
        VALUES (?, 1, '', 'test.pdf', 'completed', 'completed', 'detailed',
                '{"paper_reference":"0606/11/O/N/25"}', ?, ?)
        """,
        (paper_id, now(), now()),
    )
    result_id = execute(
        """
        INSERT INTO analysis_question_results
        (analysis_version_id, question_label, question_text, maximum_marks,
         topic, skill, ai_mark, ai_confidence, ai_rationale,
         ai_rationale_zh, error_mechanism, error_mechanism_zh,
         assessment_status, awarded_mark, created_at)
        VALUES (?, 'Q1', 'Sketch the trigonometric graph.', 5,
                'Trigonometry', 'trigonometric graphs', 2, 0.9,
                'The period is correct but the amplitude is not.',
                '周期正确，但振幅错误。', 'Incorrect amplitude',
                '振幅错误', 'graded', 2, ?)
        """,
        (version_id, now()),
    )
    execute(
        """
        INSERT INTO analysis_skill_observations
        (student_id, paper_id, analysis_version_id, question_result_id,
         observed_at, topic, skill, marks_earned, marks_available,
         success_fraction, grading_confidence, extraction_confidence,
         evidence_weight, is_current)
        VALUES (?, ?, ?, ?, ?, 'Trigonometry', 'trigonometric graphs',
                2, 5, 0.4, 0.9, 0.9, 4.5, 1)
        """,
        (student_id, paper_id, version_id, result_id, now()),
    )
    rebuild_student_profile(student_id)
    return paper_id, result_id


def seed_bank_questions(count=15):
    pack_id = execute(
        """
        INSERT INTO paper_packs
        (syllabus_code, year, examination_session, component, paper_number,
         calculator_policy, ingestion_status, created_at, updated_at)
        VALUES ('0606', 2025, 'October/November', '11', '1',
                'non-calculator', 'ready', ?, ?)
        """,
        (now(), now()),
    )
    ids = []
    for index in range(1, count + 1):
        ids.append(
            execute(
                """
                INSERT INTO paper_questions
                (paper_pack_id, question_number, prompt_text, maximum_marks,
                 topic, skills, calculator_policy, question_demand,
                 parsing_confidence, answer_text, source_key,
                 dependency_group, review_status, order_index)
                VALUES (?, ?, ?, 5, 'Trigonometry',
                        '["trigonometric graphs"]', 'non-calculator',
                        'standard', 1, ?, ?, ?, 'ready', ?)
                """,
                (
                    pack_id,
                    str(index),
                    f"Question {index}: Sketch a trigonometric graph.",
                    f"Answer {index}: correct graph with labelled amplitude and period.",
                    f"0606_w25_11_q{index}",
                    f"0606_w25_11_q{index}",
                    index,
                ),
            )
        )
    return ids


def test_clickable_skill_mistake_book_and_worksheet_pdfs():
    email = "learning-loop@student.local"
    student_id = create_student(email)
    seed_direct_observation(student_id)
    seed_bank_questions()

    detail = skill_detail(student_id, "trigonometric graphs")
    assert detail["papers"][0]["percentage"] == 40
    assert detail["papers"][0]["partial"] == 1

    book = mistake_book(student_id)
    assert book["counts"]["total"] == 1
    assert book["items"][0]["outcome"] == "partial"
    chinese_book = mistake_book_pdf(student_id, "questions", "zh")
    with fitz.open(stream=chinese_book, filetype="pdf") as document:
        question_text = "\n".join(page.get_text() for page in document)
    assert "错题本" in question_text
    assert "共 1 道题" in question_text
    assert "Sketch the trigonometric graph" in question_text
    answer_book = mistake_book_pdf(student_id, "answers", "en")
    with fitz.open(stream=answer_book, filetype="pdf") as document:
        answer_text = "\n".join(page.get_text() for page in document)
    assert "Sumkora Worked Solutions" in answer_text
    assert answer_text.index("Sketch the trigonometric graph") < answer_text.index(
        "Worked solution"
    )
    assert "Worked process" in answer_text
    assert "Incorrect amplitude" in answer_text
    assert "mark scheme" not in answer_text.lower()
    assert "supplied as a complete document" not in answer_text

    set_id = create_practice_set(
        student_id,
        count=10,
        selection_mode="weaknesses",
        topic="",
        difficulty="mixed",
        calculator_policy="any",
        lang="en",
    )
    practice = practice_set_detail(student_id, set_id)
    assert practice["set"]["requested_count"] == 10
    assert len(practice["items"]) == 10
    question_pdf = practice_pdf(student_id, set_id, "questions", "en")
    assert question_pdf.startswith(b"%PDF")
    with fitz.open(stream=question_pdf, filetype="pdf") as document:
        assert len(document) < 11
        assert "Sumkora worksheet" in document[0].get_text()
    assert practice_pdf(student_id, set_id, "answers", "zh").startswith(b"%PDF")

    cookies = login(email)
    dashboard = client.get("/student", cookies=cookies)
    assert "/static/style.css?v=20260825-2" in dashboard.text
    assert 'width="24" height="24" fill="none"' in dashboard.text
    assert client.get(
        "/student/skills/detail?skill=trigonometric%20graphs", cookies=cookies
    ).status_code == 200
    assert client.get("/student/mistakes", cookies=cookies).status_code == 200
    assert client.get("/student/practice", cookies=cookies).status_code == 200
    assert client.get(
        f"/student/practice/{set_id}/questions.pdf", cookies=cookies
    ).headers["content-type"].startswith("application/pdf")
    mistake_page = client.get("/student/mistakes", cookies=cookies)
    assert 'download="sumkora-mistake-book-questions.pdf"' in mistake_page.text
    assert "Download worked solutions" in mistake_page.text
    assert "Picture of the original question and your work" not in mistake_page.text
    assert "Have you tried this question again?" in mistake_page.text
    assert "Show the fully worked solution" in mistake_page.text
    assert "/static/mistakes.js?v=20260825-4" in mistake_page.text
    solution = client.post(
        f"/student/mistakes/{book['items'][0]['id']}/solution",
        cookies=cookies,
    )
    assert solution.status_code == 200
    assert "Worked process" in solution.json()["solution"]
    assert "mark scheme" not in solution.json()["solution"].lower()
    practice_page = client.get(f"/student/practice/{set_id}", cookies=cookies)
    assert f"/student/practice/{set_id}/submit" not in practice_page.text
    assert "Analyse completed worksheet" not in practice_page.text
    assert client.post(
        f"/student/practice/{set_id}/submit", cookies=cookies
    ).status_code == 404


def test_mistake_book_pdf_download_uses_prebuilt_cache(monkeypatch):
    student_id = create_student("mistake-pdf-cache@student.local")
    seed_direct_observation(student_id)
    refresh_mistake_book_pdf_cache(student_id, languages=("en",))
    expected = cached_mistake_book_pdf(student_id, "questions", "en")
    assert expected.startswith(b"%PDF")

    def must_not_render(*_args, **_kwargs):
        raise AssertionError("a cached download must not regenerate the PDF")

    monkeypatch.setattr(learning, "mistake_book_pdf", must_not_render)
    assert cached_mistake_book_pdf(student_id, "questions", "en") == expected


def test_completed_analysis_warms_solutions_and_every_booklet(monkeypatch):
    student_id = create_student("mistake-background-warm@student.local")
    seed_direct_observation(student_id)
    book = mistake_book(student_id)
    version_id = int(book["items"][0]["analysis_version_id"])

    def generate_without_provider(items, curriculum=None):
        assert curriculum
        for item in items:
            execute(
                """
                UPDATE mistake_book_entries
                SET worked_solution_en = ?, worked_solution_zh = ?,
                    worked_solution_model = 'test-fast', updated_at = ?
                WHERE id = ?
                """,
                (
                    "Use the graph period, then correct the amplitude.",
                    "先确定图像周期，再修正振幅。",
                    now(),
                    item["id"],
                ),
            )
            item["worked_solution_en"] = (
                "Use the graph period, then correct the amplitude."
            )
            item["worked_solution_zh"] = "先确定图像周期，再修正振幅。"

    monkeypatch.setattr(
        learning, "prepare_mistake_worked_solutions", generate_without_provider
    )
    learning.warm_analysis_mistakes(student_id, version_id)

    for language in ("en", "zh"):
        for kind in ("questions", "answers"):
            content = cached_mistake_book_pdf(student_id, kind, language)
            assert content.startswith(b"%PDF")
            assert len(content) > 1_000
    answer_text = "".join(
        page.get_text()
        for page in fitz.open(
            stream=cached_mistake_book_pdf(student_id, "answers", "en"),
            filetype="pdf",
        )
    )
    assert "correct the amplitude" in answer_text


def test_progress_report_uses_current_paper_analysis_data():
    email = "progress-report@student.local"
    student_id = create_student(email)
    paper_id, _ = seed_direct_observation(student_id)
    execute(
        """
        UPDATE paper_analysis_versions
        SET provisional_score = 2, confirmed_min_score = 2,
            possible_max_score = 2, finished_at = ?
        WHERE paper_id = ?
        """,
        (now(), paper_id),
    )

    payload = profile_report(student_id, lang="en", variant="student")
    with fitz.open(stream=payload, filetype="pdf") as document:
        text = "\n".join(page.get_text() for page in document)
    assert "0606/11/O/N/25" in text
    assert "2.0/5.0 (40.0%)" in text
    assert "Trigonometry" in text
    assert "Q1" in text
    assert "Not enough data" not in text

    cookies = login(email)
    response = client.get("/student/report", cookies=cookies)
    assert response.status_code == 200, response.text
    assert response.headers["content-disposition"].endswith(
        'sumkora-learning-student-progress-report.pdf"'
    )


def test_mistake_book_recombines_sibling_subquestions_for_context():
    student_id = create_student("question-context@student.local")
    paper_id = execute(
        """
        INSERT INTO student_papers
        (student_id, title, syllabus_code, paper_number, maximum_marks,
         source_type, status, latest_version_number, created_at, updated_at)
        VALUES (?, 'Context paper', '0606', '13', 5, 'official',
                'completed', 1, ?, ?)
        """,
        (student_id, now(), now()),
    )
    version_id = execute(
        """
        INSERT INTO paper_analysis_versions
        (paper_id, version_number, question_paper_path, answer_script_path,
         status, current_stage, assessment_mode, created_at, updated_at)
        VALUES (?, 1, '', 'work.pdf', 'completed', 'completed', 'detailed', ?, ?)
        """,
        (paper_id, now(), now()),
    )
    for label, text, latex, earned, available in [
        (
            "Q12(a)",
            "In the expansion of (2 + x)^59, write down the coefficient.",
            r"In the expansion of \((2+x)^{59}\), write down the coefficient.",
            1,
            1,
        ),
        (
            "Q12(b)",
            "For this expansion, find r.",
            r"For this expansion, find \(r\).",
            1,
            4,
        ),
    ]:
        execute(
            """
            INSERT INTO analysis_question_results
            (analysis_version_id, question_label, question_text,
             question_latex, maximum_marks, topic, skill, ai_mark,
             ai_confidence, ai_rationale, assessment_status, awarded_mark,
             created_at)
            VALUES (?, ?, ?, ?, ?, 'Sequences and series',
                    'binomial theorem', ?, 0.9, 'Check the coefficient.',
                    'graded', ?, ?)
            """,
            (
                version_id,
                label,
                text,
                latex,
                available,
                earned,
                earned,
                now(),
            ),
        )
    book = mistake_book(student_id)
    assert book["counts"]["total"] == 1
    question = book["items"][0]["complete_question_text"]
    assert "Q12(a)" in question
    assert r"\((2+x)^{59}\)" in question
    assert "Q12(b)" in question


def test_mistake_book_reconnects_fast_results_to_original_page(tmp_path):
    email = "mistake-source@student.local"
    student_id = create_student(email)
    paper_id, result_id = seed_direct_observation(student_id)
    source_path = tmp_path / "completed-work.pdf"
    document = fitz.open()
    page = document.new_page()
    page.insert_text((72, 90), "Q1 Sketch the trigonometric graph.")
    document.save(source_path)
    document.close()
    version = query_one(
        "SELECT id FROM paper_analysis_versions WHERE paper_id = ?",
        (paper_id,),
    )
    execute(
        "UPDATE paper_analysis_versions SET answer_script_path = ? WHERE id = ?",
        (str(source_path), version["id"]),
    )
    execute(
        "UPDATE analysis_question_results SET evidence_pages = '[1]' WHERE id = ?",
        (result_id,),
    )

    book = mistake_book(student_id)
    assert book["items"][0]["has_source_image"] is True
    with TestClient(app) as isolated_client:
        isolated_client.cookies.set("session", create_session_token(student_id))
        response = isolated_client.get(
            f"/student/mistakes/{book['items'][0]['id']}/source-image"
        )
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    assert response.content.startswith(b"\x89PNG")


def test_mistake_book_recovers_full_question_and_replaces_stale_solution(
    tmp_path, monkeypatch
):
    student_id = create_student("mistake-recovery@student.local")
    paper_id, result_id = seed_direct_observation(student_id)
    source_path = tmp_path / "completed-work-recovery.pdf"
    document = fitz.open()
    page = document.new_page()
    page.insert_text((72, 90), "2 Differentiate x^2 e^(3x) with respect to x. [3]")
    document.save(source_path)
    document.close()
    version = query_one(
        "SELECT id FROM paper_analysis_versions WHERE paper_id = ?",
        (paper_id,),
    )
    execute(
        """
        UPDATE student_papers
        SET title = 'Uncatalogued photographed paper', paper_number = ''
        WHERE id = ?
        """,
        (paper_id,),
    )
    execute(
        """
        UPDATE paper_analysis_versions
        SET answer_script_path = ?, assessment_summary = '{}'
        WHERE id = ?
        """,
        (str(source_path), version["id"]),
    )
    execute(
        """
        UPDATE analysis_question_results
        SET question_label = 'Q2', question_text = 'Q2 — Calculus',
            question_latex = 'Q2 — Calculus', evidence_pages = '[1]'
        WHERE id = ?
        """,
        (result_id,),
    )
    book = mistake_book(student_id)
    entry = book["items"][0]
    execute(
        """
        UPDATE mistake_book_entries
        SET worked_solution_en = 'Insufficient information.',
            worked_solution_zh = '信息不足。'
        WHERE id = ?
        """,
        (entry["id"],),
    )
    assert entry["needs_question_recovery"] is True
    assert entry["complete_question_text"] == ""

    seen = {}

    def fake_source_solver(
        payload,
        curriculum,
        *,
        mime_type="image/png",
        target_label="",
        **_kwargs,
    ):
        seen["payload"] = payload
        seen["target_label"] = target_label
        return {
            "transcription": "Differentiate x^2 e^(3x) with respect to x.",
            "question_latex": (
                r"Differentiate \(x^2e^{3x}\) with respect to \(x\)."
            ),
            "solution_en": (
                r"Using the product rule, \(\frac{d}{dx}(x^2e^{3x})"
                r"=2xe^{3x}+3x^2e^{3x}\)."
            ),
            "solution_zh": (
                r"使用乘积法则，\(\frac{d}{dx}(x^2e^{3x})"
                r"=2xe^{3x}+3x^2e^{3x}\)。"
            ),
            "model": "test-vision-model",
        }

    monkeypatch.setattr(
        question_solver, "solve_question_image_bytes", fake_source_solver
    )
    with TestClient(app) as isolated_client:
        isolated_client.cookies.set("session", create_session_token(student_id))
        response = isolated_client.post(
            f"/student/mistakes/{entry['id']}/solution"
        )
    assert response.status_code == 200
    assert seen["payload"].startswith(b"\xff\xd8\xff")
    assert response.elapsed.total_seconds() < 30
    assert seen["target_label"] == "Q2"
    assert r"Differentiate \(x^2e^{3x}\)" in response.json()["question"]
    assert "product rule" in response.json()["solution"]
    repaired = query_one(
        "SELECT question_latex FROM analysis_question_results WHERE id = ?",
        (result_id,),
    )
    cached = query_one(
        """
        SELECT worked_solution_en FROM mistake_book_entries
        WHERE id = ?
        """,
        (entry["id"],),
    )
    assert r"Differentiate \(x^2e^{3x}\)" in repaired["question_latex"]
    assert "Insufficient information" not in cached["worked_solution_en"]
    assert mistake_book(student_id)["items"][0]["needs_question_recovery"] is False


def test_mistake_book_prefetch_recovers_only_first_three_and_caches(
    tmp_path, monkeypatch
):
    student_id = create_student("mistake-prefetch@student.local")
    source_path = tmp_path / "prefetch-source.pdf"
    document = fitz.open()
    page = document.new_page()
    page.insert_text((72, 90), "2 Differentiate x^2 e^(3x) with respect to x. [3]")
    document.save(source_path)
    document.close()

    for index in range(4):
        paper_id, result_id = seed_direct_observation(student_id)
        version = query_one(
            "SELECT id FROM paper_analysis_versions WHERE paper_id = ?",
            (paper_id,),
        )
        execute(
            "UPDATE student_papers SET title = ?, paper_number = '' WHERE id = ?",
            (f"Uncatalogued paper {index}", paper_id),
        )
        execute(
            """
            UPDATE paper_analysis_versions
            SET answer_script_path = ?, assessment_summary = '{}'
            WHERE id = ?
            """,
            (str(source_path), version["id"]),
        )
        execute(
            """
            UPDATE analysis_question_results
            SET question_label = ?, question_text = ?, question_latex = ?,
                evidence_pages = '[1]'
            WHERE id = ?
            """,
            (f"Q{index + 1}", f"Q{index + 1} — Calculus", f"Q{index + 1} — Calculus", result_id),
        )

    seen = []

    def fake_source_solver(payload, _curriculum, **kwargs):
        assert kwargs["mime_type"] == "image/jpeg"
        assert payload.startswith(b"\xff\xd8\xff")
        label = kwargs["target_label"]
        seen.append(label)
        return {
            "transcription": f"{label} Differentiate x^2 e^(3x) with respect to x.",
            "question_latex": rf"{label} Differentiate \(x^2e^{{3x}}\) with respect to \(x\).",
            "solution_en": r"The derivative is \(2xe^{3x}+3x^2e^{3x}\).",
            "solution_zh": r"导数为 \(2xe^{3x}+3x^2e^{3x}\)。",
            "model": "test-fast-vision",
        }

    monkeypatch.setattr(
        question_solver, "solve_question_image_bytes", fake_source_solver
    )
    results = prepare_mistake_recovery_batch(student_id, limit=3)
    assert len(results) == 3
    assert all(item["ok"] for item in results)
    assert len(seen) == 3
    refreshed = mistake_book(student_id)["items"]
    assert sum(bool(item["needs_question_recovery"]) for item in refreshed) == 1


def test_unclassified_is_not_exposed_as_student_mastery():
    student_id = create_student("classified-progress@student.local")
    values = {
        "evidence_count": 2,
        "distinct_papers": 1,
        "total_marks_earned": 1,
        "total_marks_available": 2,
        "all_time_estimate": 0.5,
        "current_estimate": 0.5,
        "uncertainty": 0.1,
        "status": "early signal",
        "trend": "stable",
        "first_observed": now(),
        "last_observed": now(),
        "calculation_version": "test",
        "updated_at": now(),
    }
    for skill, topic in [
        ("unclassified", "Unclassified"),
        ("quadratic equations", "Algebra and graphs"),
    ]:
        execute(
            """
            INSERT INTO student_skill_states
            (student_id, skill, topic, evidence_count, distinct_papers,
             total_marks_earned, total_marks_available, all_time_estimate,
             current_estimate, uncertainty, status, trend, first_observed,
             last_observed, calculation_version, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (student_id, skill, topic, *values.values()),
        )
    profile = student_skill_profile(student_id)
    assert [item["topic"] for item in profile["states"]] == ["Algebra and graphs"]
    assert all(item["topic"] != "Unclassified" for item in profile["topic_states"])


def test_mistake_book_deduplicates_title_and_uses_full_bank_parent():
    email = "complete-parent@student.local"
    student_id = create_student(email)
    pack_id = execute(
        """
        INSERT INTO paper_packs
        (syllabus_code, year, examination_session, component, paper_number,
         calculator_policy, ingestion_status, created_at, updated_at)
        VALUES ('0606', 2025, 'October/November', '13', '1',
                'non-calculator', 'ready', ?, ?)
        """,
        (now(), now()),
    )
    bank_question_id = execute(
        """
        INSERT INTO paper_questions
        (paper_pack_id, question_number, prompt_text, maximum_marks,
         topic, skills, calculator_policy, question_demand,
         parsing_confidence, answer_text, source_key,
         dependency_group, review_status, order_index)
        VALUES (?, '9',
                'Q9 Solve the following equations. (a) Full logarithmic equation. (b) Full exponential equation.',
                11, 'Exponential equations', '["exponential equations"]',
                'non-calculator', 'challenging', 1, 'Complete answer',
                '0606_w25_13_q9', '0606_w25_13_q9', 'ready', 9)
        """,
        (pack_id,),
    )
    paper_id = execute(
        """
        INSERT INTO student_papers
        (student_id, title, syllabus_code, paper_number, maximum_marks,
         source_type, status, latest_version_number, created_at, updated_at)
        VALUES (?, 'Paper', '0606', '13', 80, 'official',
                'completed', 1, ?, ?)
        """,
        (student_id, now(), now()),
    )
    version_id = execute(
        """
        INSERT INTO paper_analysis_versions
        (paper_id, version_number, question_paper_path, answer_script_path,
         status, current_stage, assessment_mode, assessment_summary,
         created_at, updated_at)
        VALUES (?, 1, '', 'work.pdf', 'completed', 'completed', 'estimate',
                '{"paper_reference":"0606/13/O/N/25"}', ?, ?)
        """,
        (paper_id, now(), now()),
    )
    for label, text, awarded, maximum in [
        ("Q9(a)", "Logarithmic equations", 5, 5),
        (
            "Q9(b)",
            r"Solve the equation \(e^{3y-7}+\frac{4}{e^3}=\frac{5}{e^{3y-1}}\).",
            0,
            6,
        ),
    ]:
        execute(
            """
            INSERT INTO analysis_question_results
            (analysis_version_id, question_label, question_text,
             question_latex, maximum_marks, topic, skill, ai_mark,
             ai_confidence, ai_rationale, assessment_status, awarded_mark,
             created_at)
            VALUES (?, ?, ?, ?, ?, 'Exponential equations',
                    'Exponential equations', ?, 0.9, 'Check the method.',
                    'graded', ?, ?)
            """,
            (
                version_id,
                label,
                text,
                text,
                maximum,
                awarded,
                awarded,
                now(),
            ),
        )

    book = mistake_book(student_id)
    assert len(book["items"]) == 1
    item = book["items"][0]
    assert "Full logarithmic equation" in item["complete_question_text"]
    assert "Full exponential equation" in item["complete_question_text"]
    assert item["has_parent_context"] is True
    assert query_one(
        """
        SELECT paper_question_id FROM analysis_question_results
        WHERE analysis_version_id = ? AND question_label = 'Q9(b)'
        """,
        (version_id,),
    )["paper_question_id"] == bank_question_id

    page = client.get("/student/mistakes", cookies=login(email))
    assert page.status_code == 200
    assert "Exponential equations · Exponential equations" not in page.text
    assert "Full logarithmic equation" in page.text


def test_analysis_links_only_one_complete_approved_parent_question():
    pack_id = execute(
        """
        INSERT INTO paper_packs
        (syllabus_code, year, examination_session, component, paper_number,
         calculator_policy, ingestion_status, created_at, updated_at)
        VALUES ('0606', 2023, 'February/March', '12', '1',
                'non-calculator', 'ready', ?, ?)
        """,
        (now(), now()),
    )
    question_id = execute(
        """
        INSERT INTO paper_questions
        (paper_pack_id, question_number, prompt_text, maximum_marks,
         topic, skills, calculator_policy, question_demand,
         parsing_confidence, answer_text, source_key, question_asset_path,
         dependency_group, review_status, order_index)
        VALUES (?, '1', 'Complete parent question.', 4, 'Algebra',
                '["equations"]', 'non-calculator', 'standard', 1,
                'Answer', '0606_m23_12_q1', 'complete-q1.pdf',
                '0606_m23_12_q1', 'ready', 1)
        """,
        (pack_id,),
    )
    matched = _match_question_bank_parent(
        {
            "syllabus_code": "0606",
            "paper_reference": "0606/12/F/M/23",
            "paper_title": "Additional Mathematics",
        },
        {"label": "Q1(a)"},
    )
    assert matched == question_id
    assert (
        _match_question_bank_parent(
            {
                "syllabus_code": "0606",
                "paper_reference": "unknown paper",
                "paper_title": "Additional Mathematics",
            },
            {"label": "Q1(a)"},
        )
        is None
    )


def _pdf(pages):
    document = fitz.open()
    for lines in pages:
        page = document.new_page()
        for index, line in enumerate(lines):
            x, text = line if isinstance(line, tuple) else (50, line)
            page.insert_text((x, 70 + index * 28), text, fontsize=11)
    payload = document.tobytes()
    document.close()
    return payload


def test_zip_import_pairs_extracts_and_totals_questions():
    question_paper = _pdf(
        [
            ["Cambridge IGCSE", "0606/11"],
            ["Formula page"],
            ["1 Differentiate x squared. [2]"],
            ["2 Solve the equation x + 3 = 7. [2]"],
        ]
    )
    mark_scheme = _pdf(
        [
            ["Cover"],
            [
                "General principles",
                "1 Award marks positively.",
                "2 Follow through where appropriate.",
            ],
            ["Annotations"],
            ["Notes"],
            ["More notes"],
            [
                "Question Answer Marks Partial Marks",
                "1 2x M1 A1",
                (110, "2/7 <= x <= 6 A1"),
                "2 x = 4 M1 A1",
            ],
        ]
    )
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as zipped:
        zipped.writestr("0606_s24_qp_11.pdf", question_paper)
        zipped.writestr("0606_s24_ms_11.pdf", mark_scheme)
        zipped.writestr("__MACOSX/._0606_s24_qp_11.pdf", b"appledouble")
        zipped.writestr("__MACOSX/._0606_s24_ms_11.pdf", b"appledouble")
    result = ingest_question_bank_zip(archive.getvalue(), "papers.zip")
    assert result["pair_count"] == 1
    assert result["papers"][0]["questions"] == 2
    pack_id = result["papers"][0]["paper_pack_id"]
    total = query_one(
        "SELECT SUM(maximum_marks) AS total FROM paper_questions WHERE paper_pack_id = ?",
        (pack_id,),
    )["total"]
    assert total == 4
    first = query_one(
        "SELECT * FROM paper_questions WHERE paper_pack_id = ? ORDER BY order_index LIMIT 1",
        (pack_id,),
    )
    assert first["question_asset_path"]
    assert first["answer_asset_path"]
    assert "2x" in first["answer_text"]
    assert "Award marks positively" not in first["answer_text"]
    assert json.loads(first["source_pages"]) == [3]
    second = query_one(
        """
        SELECT * FROM paper_questions
        WHERE paper_pack_id = ? ORDER BY order_index LIMIT 1 OFFSET 1
        """,
        (pack_id,),
    )
    assert "x = 4" in second["answer_text"]
    assert "2/7" not in second["answer_text"]

    researcher_email = "question-bank@research.local"
    create_researcher(researcher_email)
    cookies = login(researcher_email)
    page = client.get("/research/question-bank", cookies=cookies)
    assert page.status_code == 200
    assert "0606" in page.text
    assert "Question bank" in page.text


def test_question_labels_ignore_body_numbers_that_appear_early(tmp_path):
    paper = _pdf(
        [
            ["Cambridge IGCSE", "0606/11"],
            ["Formula page"],
            ["1 First question. [1]"],
            ["2 Choose from the available characters. [1]", "7 different letters remain."],
            ["3 Third question. [1]"],
            ["4 Fourth question. [1]"],
            ["5 Fifth question. [1]"],
            ["6 Sixth question. [1]"],
            ["7 Seventh question. [1]"],
        ]
    )
    path = tmp_path / "0606_s24_qp_11.pdf"
    path.write_bytes(paper)
    assert _question_labels(path) == ["1", "2", "3", "4", "5", "6", "7"]


def test_tall_question_asset_uses_the_worksheet_title_page(tmp_path):
    source = fitz.open()
    page = source.new_page(width=540, height=750)
    page.insert_text((50, 70), "A complete tall question asset.", fontsize=12)
    asset_path = tmp_path / "question.pdf"
    source.save(asset_path)
    source.close()

    flow = _PdfFlow(title="Sumkora worksheet", subtitle="10 questions", lang="en")
    assert flow.add_asset(
        str(asset_path),
        label="1. Q1",
        source_label="0606 May/June 2025 / 11 / 1",
    )
    with fitz.open(stream=flow.finish(), filetype="pdf") as document:
        assert "1. Q1" in document[0].get_text()
        assert "A complete tall question asset." in document[0].get_text()
