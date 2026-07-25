from dataclasses import asdict, dataclass
from typing import Optional

import sympy as sp


@dataclass
class MathCheckResult:
    equivalent: Optional[bool]
    check_type: str
    normalized_student: str
    normalized_expected: str
    warning: str = ""

    def as_dict(self):
        return asdict(self)


def _parse(value: str, symbol: str = "x"):
    local = {symbol: sp.Symbol(symbol), "e": sp.E, "pi": sp.pi}
    cleaned = (value or "").replace("^", "**").replace("−", "-")
    return sp.sympify(cleaned, locals=local)


def symbolic_equivalence(student: str, expected: str, symbol: str = "x") -> MathCheckResult:
    try:
        left = _parse(student, symbol)
        right = _parse(expected, symbol)
        equivalent = sp.simplify(left - right) == 0
        return MathCheckResult(
            equivalent,
            "symbolic_equivalence",
            str(sp.simplify(left)),
            str(sp.simplify(right)),
        )
    except Exception as exc:
        return MathCheckResult(
            None,
            "symbolic_equivalence",
            student,
            expected,
            f"parse_failed:{type(exc).__name__}",
        )


def numerical_equivalence(
    student: str, expected: str, tolerance: float = 1e-9
) -> MathCheckResult:
    try:
        left = float(sp.N(_parse(student)))
        right = float(sp.N(_parse(expected)))
        equivalent = abs(left - right) <= tolerance
        return MathCheckResult(
            equivalent,
            "numerical_equivalence",
            f"{left:.12g}",
            f"{right:.12g}",
        )
    except Exception as exc:
        return MathCheckResult(
            None,
            "numerical_equivalence",
            student,
            expected,
            f"parse_failed:{type(exc).__name__}",
        )


def derivative_equivalence(
    student_derivative: str, original_expression: str, symbol: str = "x"
) -> MathCheckResult:
    try:
        variable = sp.Symbol(symbol)
        student = _parse(student_derivative, symbol)
        expected = sp.diff(_parse(original_expression, symbol), variable)
        return MathCheckResult(
            sp.simplify(student - expected) == 0,
            "derivative_equivalence",
            str(sp.simplify(student)),
            str(sp.simplify(expected)),
        )
    except Exception as exc:
        return MathCheckResult(
            None,
            "derivative_equivalence",
            student_derivative,
            original_expression,
            f"parse_failed:{type(exc).__name__}",
        )


def antiderivative_equivalence(
    student_antiderivative: str, integrand: str, symbol: str = "x"
) -> MathCheckResult:
    try:
        variable = sp.Symbol(symbol)
        student = _parse(student_antiderivative, symbol)
        expected_integrand = _parse(integrand, symbol)
        equivalent = sp.simplify(sp.diff(student, variable) - expected_integrand) == 0
        return MathCheckResult(
            equivalent,
            "antiderivative_equivalence",
            str(sp.simplify(student)),
            str(sp.simplify(expected_integrand)),
        )
    except Exception as exc:
        return MathCheckResult(
            None,
            "antiderivative_equivalence",
            student_antiderivative,
            integrand,
            f"parse_failed:{type(exc).__name__}",
        )
