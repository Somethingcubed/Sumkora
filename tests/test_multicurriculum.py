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
    _clean_generated_practice_body,
    _plain_math,
    _readable_markdown_tables,
    create_generated_practice_set,
    practice_pdf,
    practice_set_detail,
)
from main import app
import practice_generator
from taxonomy import canonical_topic_for_curriculum


client = TestClient(app)


def test_pdf_math_fallback_keeps_chemistry_quantities_readable():
    assert _plain_math(r"\(0.65\,\mathrm{g}\)") == "0.65 g"
    assert _plain_math(r"\(H_2+Cl_2\rightarrow 2HCl\)") == "H₂+Cl₂→ 2HCl"
    assert _plain_math(r"\(22.4\,\mathrm{L\,mol^{-1}}\)") == "22.4 L mol⁻¹"
    assert _plain_math("0.0200 mol L−1; 25.0 cm3") == "0.0200 mol L⁻¹; 25.0 cm³"
    assert _plain_math(r"$25.0\,cm^3$; $15\,^\circ C$") == "25.0 cm³; 15 °C"
    assert _plain_math("0.40mol dm−3") == "0.40 mol dm⁻³"
    assert _plain_math(r"\H2O2(aq)\; \MnO2(s)\; CO2") == "H₂O₂(aq) MnO₂(s) CO₂"
    assert _plain_math("1.0min; 1.4g; 25mL") == "1.0 min; 1.4 g; 25 mL"
    assert _plain_math("研究H2O2(aq)在1.0min内生成1.4g的CO2。") == (
        "研究H₂O₂(aq) 在1.0 min 内生成1.4 g 的CO₂。"
    )


def test_generated_pdf_boilerplate_is_removed():
    source = """写出反应方程式。

只使用题目所给的信息作答。
AI 生成练习 · 已独立解答并校验
"""
    assert _clean_generated_practice_body(source) == "写出反应方程式。"


def test_markdown_tables_become_readable_rows_without_pipe_syntax():
    source = """结果如下：

| 温度 / $^\\circ C$ | 时间 / s |
|---|---|
| 15 | 84 |
| 25 | 52 |
| 35 | 31 |
"""
    readable = _readable_markdown_tables(source, "zh")
    assert "|" not in readable
    assert "温度 / $^\\circ C$：15  ·  时间 / s：84" in readable
    assert "时间 / s：84\n\n温度 / $^\\circ C$：25" in readable


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
        assert "AI-generated practice" not in text
        assert "Evaluate" in text
        assert sum(len(page.get_images(full=True)) for page in document) >= 10
    with fitz.open(stream=practice_pdf(student_id, set_id, "answers", "en"), filetype="pdf") as document:
        text = "".join(page.get_text() for page in document)
        assert "By continuity" in text
        assert "Final answer" in text
    with fitz.open(
        stream=practice_pdf(student_id, set_id, "answers", "zh"),
        filetype="pdf",
    ) as document:
        text = "".join(page.get_text() for page in document)
        assert "答案册" in text
        assert "由连续性可知" in text
        assert r"\lim" not in text
        # Simple quantities stay as sharp, searchable native text. Complex
        # notation such as the limits above still uses rendered equations.
        assert sum(len(page.get_images(full=True)) for page in document) == 0


def test_ten_question_generation_uses_timeout_safe_concurrent_batches(
    monkeypatch,
):
    curriculum = curriculum_profile("ap-calculus-ab", "course", "en")
    generated_batch_sizes = []
    validated_batch_sizes = []

    def fake_generate_batch(**kwargs):
        generated_batch_sizes.append(kwargs["count"])
        questions = []
        for offset in range(kwargs["count"]):
            order = kwargs["start_order"] + offset
            questions.append(
                {
                    "order": order,
                    "topic": "Limits and continuity",
                    "skill": "evaluating limits",
                    "difficulty": "standard",
                    "prompt_en": f"Evaluate the complete limit number {order}.",
                    "prompt_zh": f"求第 {order} 个完整极限。",
                    "solution_en": f"The limit is {order}.",
                    "solution_zh": f"极限为 {order}。",
                    "final_answer_en": str(order),
                    "final_answer_zh": str(order),
                    "maximum_marks": 1.0,
                    "valid": True,
                    "validation_notes": "",
                    "signature": f"unique question {order}",
                }
            )
        return questions, "generator-test"

    def fake_validate_batch(questions, **_kwargs):
        validated_batch_sizes.append(len(questions))
        return questions, "validator-test"

    monkeypatch.setattr(practice_generator, "_generate_batch", fake_generate_batch)
    monkeypatch.setattr(practice_generator, "_validate_batch", fake_validate_batch)

    questions, metadata = practice_generator.generate_validated_practice_questions(
        curriculum=curriculum,
        topic="Limits and continuity",
        count=10,
        difficulty="mixed",
        calculator_policy="any",
    )

    assert sorted(generated_batch_sizes) == [2, 2, 2, 2, 2, 2]
    assert sorted(validated_batch_sizes) == [2, 2, 2, 2, 2, 2]
    assert len(questions) == 10
    assert metadata["generated_count"] == 12
    assert metadata["validated_count"] == 10


def test_validator_rejections_receive_one_bounded_replacement_pass(
    monkeypatch,
):
    curriculum = curriculum_profile("ap-calculus-ab", "course", "en")
    generated_orders = []
    validation_calls = 0

    def fake_generate_batch(**kwargs):
        questions = []
        for offset in range(kwargs["count"]):
            order = kwargs["start_order"] + offset
            generated_orders.append(order)
            questions.append(
                {
                    "order": order,
                    "topic": "Limits and continuity",
                    "skill": "evaluating limits",
                    "difficulty": "standard",
                    "prompt_en": f"Evaluate replacement-safe limit {order}.",
                    "prompt_zh": f"求可替换极限 {order}。",
                    "solution_en": f"The limit is {order}.",
                    "solution_zh": f"极限为 {order}。",
                    "final_answer_en": str(order),
                    "final_answer_zh": str(order),
                    "maximum_marks": 1.0,
                    "valid": True,
                    "validation_notes": "",
                    "signature": f"replacement-safe {order}",
                }
            )
        return questions, "generator-test"

    def fake_validate_batch(questions, **_kwargs):
        nonlocal validation_calls
        validation_calls += 1
        # Reject all but eight items from the initial reserve. The bounded
        # pass must create enough fresh candidates to reach ten.
        if max(item["order"] for item in questions) <= 12:
            return [item for item in questions if item["order"] <= 8], "validator-test"
        return questions, "validator-test"

    monkeypatch.setattr(practice_generator, "_generate_batch", fake_generate_batch)
    monkeypatch.setattr(practice_generator, "_validate_batch", fake_validate_batch)

    questions, metadata = practice_generator.generate_validated_practice_questions(
        curriculum=curriculum,
        topic="Limits and continuity",
        count=10,
        difficulty="mixed",
        calculator_policy="any",
    )

    assert len(questions) == 10
    assert max(generated_orders) > 12
    assert validation_calls > 4
    assert metadata["validated_count"] == 10


def test_timed_out_batches_are_split_without_discarding_completed_work(
    monkeypatch,
):
    curriculum = curriculum_profile("ap-calculus-ab", "course", "en")
    generation_calls = []
    validation_calls = []
    failed_generation_batch = False
    failed_validation_batch = False

    def fake_generate_batch(**kwargs):
        nonlocal failed_generation_batch
        generation_calls.append((kwargs["start_order"], kwargs["count"]))
        if (
            kwargs["start_order"] == 1
            and kwargs["count"] == 2
            and not failed_generation_batch
        ):
            failed_generation_batch = True
            raise TimeoutError("provider read timed out")
        questions = []
        for offset in range(kwargs["count"]):
            order = kwargs["start_order"] + offset
            questions.append(
                {
                    "order": order,
                    "topic": "Limits and continuity",
                    "skill": "evaluating limits",
                    "difficulty": "standard",
                    "prompt_en": f"Evaluate resilient limit {order} completely.",
                    "prompt_zh": f"完整求可恢复极限 {order}。",
                    "solution_en": f"The limit is {order}.",
                    "solution_zh": f"极限为 {order}。",
                    "final_answer_en": str(order),
                    "final_answer_zh": str(order),
                    "maximum_marks": 1.0,
                    "valid": True,
                    "validation_notes": "",
                    "signature": f"resilient limit {order}",
                }
            )
        return questions, "generator-test"

    def fake_validate_batch(questions, **_kwargs):
        nonlocal failed_validation_batch
        validation_calls.append(len(questions))
        if len(questions) == 2 and not failed_validation_batch:
            failed_validation_batch = True
            raise TimeoutError("validator read timed out")
        return questions, "validator-test"

    monkeypatch.setattr(practice_generator, "_generate_batch", fake_generate_batch)
    monkeypatch.setattr(practice_generator, "_validate_batch", fake_validate_batch)

    questions, metadata = practice_generator.generate_validated_practice_questions(
        curriculum=curriculum,
        topic="Limits and continuity",
        count=10,
        difficulty="mixed",
        calculator_policy="any",
    )

    assert len(questions) == 10
    assert (1, 1) in generation_calls
    assert (2, 1) in generation_calls
    assert 1 in validation_calls
    assert metadata["validated_count"] == 10


def test_compact_validator_reuses_correct_items_and_applies_repairs(
    monkeypatch,
):
    curriculum = curriculum_profile("ap-calculus-ab", "course", "en")
    questions = []
    for order in (1, 2):
        questions.append(
            {
                "order": order,
                "topic": "Limits and continuity",
                "skill": "evaluating limits",
                "difficulty": "standard",
                "prompt_en": f"Evaluate compact limit {order} completely.",
                "prompt_zh": f"完整求精简极限 {order}。",
                "solution_en": f"The limit is {order}.",
                "solution_zh": f"极限为 {order}。",
                "final_answer_en": str(order),
                "final_answer_zh": str(order),
                "maximum_marks": 1.0,
                "valid": True,
                "validation_notes": "",
                "signature": f"compact limit {order}",
            }
        )

    repaired = {
        key: value
        for key, value in questions[1].items()
        if key not in {"valid", "validation_notes", "signature"}
    }
    repaired["final_answer_en"] = "2 (checked)"

    def fake_call_model(*_args, **_kwargs):
        return (
            {
                "questions": [
                    {
                        "order": 1,
                        "valid": True,
                        "validation_notes": "Correct as supplied.",
                        "replacement": None,
                    },
                    {
                        "order": 2,
                        "valid": True,
                        "validation_notes": "Final wording repaired.",
                        "replacement": repaired,
                    },
                ]
            },
            "validator-test",
        )

    monkeypatch.setattr(practice_generator, "_call_model", fake_call_model)

    validated, model = practice_generator._validate_batch(
        questions,
        curriculum=curriculum,
        difficulty="mixed",
        calculator_policy="any",
    )

    assert model == "validator-test"
    assert len(validated) == 2
    assert validated[0]["prompt_en"] == questions[0]["prompt_en"]
    assert validated[0]["validation_notes"] == "Correct as supplied."
    assert validated[1]["final_answer_en"] == "2 (checked)"
