"""Regression coverage for the multi-curriculum boundary."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import fitz
from fastapi.testclient import TestClient

from curricula import curriculum_profile, topics_for_curriculum
from db import execute, hash_password, query_one
from document_assessment import _prompt
from learning import (
    create_generated_practice_set,
    practice_pdf,
    practice_set_detail,
)
from main import app
from taxonomy import canonical_topic_for_curriculum


client = TestClient(app)


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _student() -> tuple[int, str]:
    username = f"multi-{uuid4().hex[:10]}"
    email = f"{username}@accounts.sumkora.invalid"
    student_id = execute(
        """
        INSERT INTO users
        (email, username, username_normalized, password_hash, name, role)
        VALUES (?, ?, ?, ?, 'Multi Student', 'student')
        """,
        (email, username, username, hash_password("pass12345")),
    )
    execute(
        "INSERT INTO user_roles (user_id, role, created_at) VALUES (?, 'student', ?)",
        (student_id, _now()),
    )
    return student_id, username


def _login(username: str):
    client.cookies.clear()
    response = client.post(
        "/login",
        data={"identifier": username, "password": "pass12345"},
        follow_redirects=False,
    )
    assert response.status_code == 303


def test_curriculum_registry_covers_requested_subjects_and_levels():
    general = curriculum_profile("general-mathematics", "grade-7", "zh")
    assert general["subject"] == "mathematics"
    assert general["level"] == "grade-7"
    assert general["study_language"] == "zh"
    assert "Algebra" in general["topics"]

    physics = curriculum_profile(
        "cambridge-igcse-physics-0625", "core", "en"
    )
    assert physics["subject"] == "physics"
    assert physics["version"] == "2026-2028"
    assert "Experimental skills and investigations" in physics["topics"]
    assert topics_for_curriculum("ap-calculus-bc")[-1] == (
        "Infinite sequences and series"
    )
    assert topics_for_curriculum("ap-physics-1")[-1] == "Fluids"
    assert "Modern physics" in topics_for_curriculum("ap-physics-2")
    assert "Oscillations" in topics_for_curriculum("ap-physics-c-mechanics")
    assert "Electromagnetic induction" in topics_for_curriculum(
        "ap-physics-c-electricity-and-magnetism"
    )

    chemistry = curriculum_profile(
        "shanghai-education-grade-9-chemistry-2026", "grade-9", "zh"
    )
    assert chemistry["subject"] == "chemistry"
    assert chemistry["name_zh"] == "沪科版（五四制）九年级化学（2026新版）"
    assert chemistry["level"] == "grade-9"
    assert chemistry["topics"] == (
        "专题7 溶液",
        "专题8 酸、碱、盐",
        "专题9 化学反应的调控",
        "专题10 化学与人类社会进步",
    )


def test_scottish_pre_release_profile_is_hidden_and_migrates_safely():
    from curricula import curriculum_options

    assert all(
        item["id"] != "scottish-higher-physics"
        for item in curriculum_options()
    )
    profile = curriculum_profile("scottish-higher-physics", "higher", "en")
    assert profile["id"] == "ap-physics-1"
    assert profile["level"] == "course"


def test_signup_saves_the_selected_curriculum_and_level():
    client.cookies.clear()
    username = f"signup-{uuid4().hex[:10]}"
    response = client.post(
        "/signup",
        data={
            "username": username,
            "display_name": "Physics Student",
            "password": "pass12345",
            "password_confirmation": "pass12345",
            "curriculum_id": "cambridge-igcse-physics-0625",
            "curriculum_level": "core",
        },
    )
    assert response.status_code == 200
    user = query_one("SELECT * FROM users WHERE username = ?", (username,))
    assert user["curriculum_id"] == "cambridge-igcse-physics-0625"
    assert user["curriculum_level"] == "core"


def test_student_can_save_curriculum_level_and_language():
    student_id, username = _student()
    _login(username)
    response = client.post(
        "/student/settings/curriculum",
        data={
            "curriculum_id": "china-national-mathematics",
            "curriculum_level": "grade-8",
            "study_language": "zh",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    user = query_one("SELECT * FROM users WHERE id = ?", (student_id,))
    assert user["curriculum_id"] == "china-national-mathematics"
    assert user["curriculum_level"] == "grade-8"
    assert user["study_language"] == "zh"

    settings = client.get("/student/settings")
    assert "Chinese National Mathematics" in settings.text
    assert 'value="grade-8" selected' in settings.text
    assert 'value="zh" selected' in settings.text


def test_physics_assessment_prompt_has_science_specific_checks():
    physics = curriculum_profile(
        "cambridge-igcse-physics-0625", "extended", "auto"
    )
    prompt = _prompt("estimate", curriculum=physics)
    assert "Motion, forces and energy" in prompt
    assert "significant figures" in prompt
    assert "experimental skills" in prompt.lower()
    assert "senior physics assessor" in prompt


def test_chemistry_pathway_is_visible_and_uses_chemistry_specific_checks():
    client.cookies.clear()
    client.cookies.set("lang", "zh")
    page = client.get("/signup")
    assert page.status_code == 200
    assert "沪科版（五四制）九年级化学（2026新版）" in page.text
    client.cookies.delete("lang")

    chemistry = curriculum_profile(
        "shanghai-education-grade-9-chemistry-2026", "grade-9", "zh"
    )
    prompt = _prompt("estimate", curriculum=chemistry)
    assert "senior chemistry assessor" in prompt
    assert "balanced symbol and ionic equations" in prompt
    assert "laboratory safety" in prompt
    assert "专题8 酸、碱、盐" in prompt

    assert canonical_topic_for_curriculum(
        chemistry["id"],
        "酸碱反应",
        "用指示剂判断溶液酸碱性",
        "向溶液中滴加紫色石蕊试液",
    ) == "专题8 酸、碱、盐"
    assert canonical_topic_for_curriculum(
        chemistry["id"],
        "metal chemistry",
        "iron extraction",
        "冶炼铁并解释金属锈蚀",
    ) == "专题9 化学反应的调控"

    assert canonical_topic_for_curriculum(
        chemistry["id"],
        "新能源",
        "氢能的开发",
        "分析氢气作为清洁能源的优点",
    ) == "专题10 化学与人类社会进步"


def test_generated_practice_is_saved_only_after_validation(monkeypatch):
    student_id, _username = _student()
    execute(
        """
        UPDATE users SET curriculum_id = 'ap-calculus-ab',
            curriculum_level = 'course', study_language = 'en'
        WHERE id = ?
        """,
        (student_id,),
    )

    def fake_generator(**kwargs):
        assert kwargs["curriculum"]["id"] == "ap-calculus-ab"
        questions = []
        for order in range(1, kwargs["count"] + 1):
            questions.append(
                {
                    "order": order,
                    "topic": kwargs["topic"],
                    "skill": "evaluating limits",
                    "difficulty": "standard",
                    "prompt_en": rf"Evaluate \(\lim_{{x\to {order}}}x\).",
                    "prompt_zh": rf"求 \(\lim_{{x\to {order}}}x\)。",
                    "solution_en": rf"By continuity, the limit is \({order}\).",
                    "solution_zh": rf"由连续性可知，极限为 \({order}\)。",
                    "final_answer_en": rf"\({order}\)",
                    "final_answer_zh": rf"\({order}\)",
                    "maximum_marks": 1,
                    "validation_notes": "Independently solved.",
                }
            )
        return questions, {
            "generation_model": "generator-test",
            "validation_model": "validator-test",
        }

    monkeypatch.setattr(
        "learning.generate_validated_practice_questions", fake_generator
    )
    set_id = create_generated_practice_set(
        student_id,
        count=10,
        selection_mode="topic",
        topic="Limits and continuity",
        difficulty="standard",
        calculator_policy="non-calculator",
        lang="en",
    )
    detail = practice_set_detail(student_id, set_id)
    assert detail["set"]["source_mode"] == "generated"
    assert detail["set"]["generation_model"] == "generator-test/validator-test"
    assert len(detail["items"]) == 10
    assert all(item["validation_status"] == "validated" for item in detail["items"])

    with fitz.open(stream=practice_pdf(student_id, set_id, "questions", "en"), filetype="pdf") as document:
        text = "".join(page.get_text() for page in document)
        assert "AI-generated practice" in text
        assert "Evaluate" in text
    with fitz.open(stream=practice_pdf(student_id, set_id, "answers", "en"), filetype="pdf") as document:
        text = "".join(page.get_text() for page in document)
        assert "By continuity" in text
        assert "Final answer" in text
