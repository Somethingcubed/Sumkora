"""Focused checks for the student refinement session."""

from learning import _choose_weak_topic
from question_solver import _enforce_solution_consistency
from taxonomy import canonical_topic


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
