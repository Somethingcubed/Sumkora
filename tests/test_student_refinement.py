"""Focused checks for the student refinement session."""

import json
import re

from learning import _choose_weak_topic
from question_solver import (
    _enforce_solution_consistency,
    _restore_tex_control_escapes,
    _equation_rhs_signature,
    normalize_mathjax_text,
    solve_question_texts,
)
from question_solver import PROMPT
from taxonomy import canonical_topic


def test_question_solver_restores_json_damaged_tex_controls():
    damaged = "\textbf{Q2}: \frac{1}{2} \right) \neq \x01"
    repaired = _restore_tex_control_escapes(damaged)
    assert repaired == r"\textbf{Q2}: \frac{1}{2} \right) \neq "


def test_question_solver_wraps_bare_model_tex_deterministically():
    damaged = (
        r"Q2 \text{2 Differentiate } x^2 e^{3x}"
        r"\text{ with respect to } x. \ [3]"
    )
    normalized = normalize_mathjax_text(damaged)
    assert r"\text{" not in normalized
    assert r"\(x^2\)" in normalized
    assert r"\(e^{3x}\)" in normalized
    assert "Differentiate" in normalized


def test_question_solver_never_exposes_dollar_or_bare_tex_delimiters():
    damaged = (
        r"Find $x^2$ when \text{given } \left\frac{1}{2}\right. "
        r"and \ [3]."
    )
    normalized = normalize_mathjax_text(damaged)
    outside_math = re.sub(
        r"\\\((?:.|\n)*?\\\)|\\\[(?:.|\n)*?\\\]", "", normalized
    )
    assert "$" not in normalized
    assert "\\" not in outside_math
    assert r"\(x^2\)" in normalized
    assert r"\(\frac{1}{2}\)" in normalized


class FixedRandom:
    def __init__(self, value=0.0):
        self.value = value

    def random(self):
        return self.value


def test_topic_aliases_match_the_question_bank_taxonomy():
    assert canonical_topic("Exponential equations") == "Algebra"
    assert canonical_topic("Arithmetic progressions") == "Sequences and series"
    assert canonical_topic("Circular measure") == "Geometry"
    assert canonical_topic("", "differentiation") == "Calculus"


def test_weak_topic_choice_uses_one_topic_and_avoids_the_previous_one():
    states = [
        {
            "topic": "Algebra",
            "current_estimate": 0.2,
            "evidence_count": 10,
            "confidence": 0.9,
        },
        {
            "topic": "Calculus",
            "current_estimate": 0.3,
            "evidence_count": 8,
            "confidence": 0.9,
        },
    ]
    chosen = _choose_weak_topic(
        states,
        {"Algebra", "Calculus"},
        previous_topic="Algebra",
        rng=FixedRandom(),
    )
    assert chosen == "Calculus"


def test_solver_final_answer_cannot_contradict_its_worked_conclusion():
    result = {
        "solution_en": (
            "Using dy/dx gives dx = 0.01/(5/2). "
            "Therefore, the approximate change is 0.004 radians."
        ),
        "solution_zh": "由微分可得。因此，x 的近似改变量为 0.004 弧度。",
        "final_answer": "0.002 radians",
        "final_answer_zh": "0.002 弧度",
    }
    _enforce_solution_consistency(result)
    assert "0.004" in result["final_answer"]
    assert "0.004" in result["final_answer_zh"]


def test_solver_keeps_an_already_consistent_answer():
    result = {
        "solution_en": "Therefore, x <= -2 or x >= 3.",
        "solution_zh": "因此，x <= -2 或 x >= 3。",
        "final_answer": "x <= -2 or x >= 3",
        "final_answer_zh": "x <= -2 或 x >= 3",
    }
    _enforce_solution_consistency(result)
    assert result["final_answer"] == "x <= -2 or x >= 3"


def test_solver_catches_conflicting_radicals_even_when_coefficients_match():
    result = {
        "solution_en": (
            r"Therefore, the chord length is \(CD = 2\sqrt{6}\)."
        ),
        "solution_zh": r"所以弦长为 \(CD = 2\sqrt{6}\)。",
        "final_answer": r"The chord length is \(CD = 2\sqrt{7}\).",
        "final_answer_zh": r"弦长为 \(CD = 2\sqrt{7}\)。",
    }
    _enforce_solution_consistency(result)
    assert r"\sqrt{6}" in result["final_answer"]
    assert r"\sqrt{6}" in result["final_answer_zh"]
    assert r"\sqrt{7}" not in result["final_answer"]
    assert r"\sqrt{7}" not in result["final_answer_zh"]


def test_equation_signature_ignores_presentation_but_not_the_result():
    assert _equation_rhs_signature(
        r"Hence \(CD=2\sqrt{6}\)."
    ) == _equation_rhs_signature(r"所以 \[ CD = 2 \sqrt{6}. \]")
    assert _equation_rhs_signature(
        r"\(CD=2\sqrt{6}\)"
    ) != _equation_rhs_signature(r"\(CD=2\sqrt{7}\)")


def test_single_question_solver_requires_mathjax_delimiters():
    assert r"\( ... \)" in PROMPT
    assert r"\[ ... \]" in PROMPT
    assert r"\frac" in PROMPT


def test_text_solver_returns_worked_solutions_without_exposing_mark_schemes(
    monkeypatch,
):
    captured = {}

    def fake_post(_url, payload, **_kwargs):
        captured["payload"] = payload
        body = {
            "solutions": [
                {
                    "id": 7,
                    "solution_en": "Factor: (x - 3)(x + 2) >= 0. "
                    "Hence x <= -2 or x >= 3.",
                    "solution_zh": "因式分解得 (x - 3)(x + 2) >= 0，"
                    "所以 x <= -2 或 x >= 3。",
                }
            ]
        }
        return {
            "model": "test-tutor",
            "output": [
                {
                    "content": [
                        {"type": "output_text", "text": json.dumps(body)}
                    ]
                }
            ],
        }

    monkeypatch.setattr("question_solver.api_post_json", fake_post)
    result = solve_question_texts(
        [
            {
                "id": 7,
                "question": "Solve x^2 - x - 6 >= 0.",
                "reference_answer": "M1 factorisation; A1 correct intervals",
            }
        ]
    )
    assert result["solutions"][0]["id"] == 7
    assert "x <= -2 or x >= 3" in result["solutions"][0]["solution_en"]
    prompt = captured["payload"]["input"][0]["content"][0]["text"]
    assert "Do not mention a mark scheme" in prompt
    assert captured["payload"]["reasoning"]["effort"] == "low"
