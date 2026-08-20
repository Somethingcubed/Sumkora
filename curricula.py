"""Versioned curriculum registry for student analysis and practice.

The registry keeps curriculum identity, level, subject, language, taxonomy,
and practice source separate.  This is important because a Chinese-language
question is not necessarily from the Chinese national curriculum, and because
physics requires different assessment instructions from mathematics.

The long-standing Cambridge 0606 route remains the only ``verified`` module.
New routes are explicitly labelled ``beta`` and use original, independently
checked AI practice rather than pretending to be official past papers.
"""

from __future__ import annotations

from typing import Mapping


GENERAL_MATH_TOPICS = (
    "Number",
    "Algebra",
    "Functions and graphs",
    "Coordinate geometry",
    "Geometry and measurement",
    "Trigonometry",
    "Sequences and series",
    "Vectors and matrices",
    "Probability",
    "Statistics",
    "Calculus",
    "Mathematical modelling",
)

CHINESE_MATH_TOPICS = (
    "Number and algebra",
    "Functions",
    "Graphics and geometry",
    "Statistics and probability",
    "Mathematical modelling and practice",
)

CAMBRIDGE_0580_TOPICS = (
    "Number",
    "Algebra and graphs",
    "Coordinate geometry",
    "Geometry",
    "Mensuration",
    "Trigonometry",
    "Transformations and vectors",
    "Probability",
    "Statistics",
)

CAMBRIDGE_0606_TOPICS = (
    "Functions",
    "Quadratic functions",
    "Factors of polynomials",
    "Equations, inequalities and graphs",
    "Simultaneous equations",
    "Logarithmic and exponential functions",
    "Straight-line graphs",
    "Coordinate geometry of the circle",
    "Circular measure",
    "Trigonometry",
    "Permutations and combinations",
    "Series",
    "Vectors in two dimensions",
    "Calculus",
)

AP_PRECALCULUS_TOPICS = (
    "Polynomial and rational functions",
    "Exponential and logarithmic functions",
    "Trigonometric and polar functions",
    "Parameters, vectors and matrices",
)

AP_CALCULUS_AB_TOPICS = (
    "Limits and continuity",
    "Differentiation fundamentals",
    "Composite, implicit and inverse differentiation",
    "Contextual applications of differentiation",
    "Analytical applications of differentiation",
    "Integration and accumulation of change",
    "Differential equations",
    "Applications of integration",
)

AP_CALCULUS_BC_TOPICS = AP_CALCULUS_AB_TOPICS + (
    "Parametric, polar and vector-valued functions",
    "Infinite sequences and series",
)

AP_STATISTICS_TOPICS = (
    "One-variable data and data collection",
    "Probability and probability distributions",
    "Inference for proportions",
    "Inference for means",
    "Regression analysis",
)

IGCSE_PHYSICS_0625_TOPICS = (
    "Motion, forces and energy",
    "Thermal physics",
    "Waves",
    "Electricity and magnetism",
    "Nuclear physics",
    "Space physics",
    "Experimental skills and investigations",
)

AP_PHYSICS_1_TOPICS = (
    "Kinematics",
    "Force and translational dynamics",
    "Work, energy and power",
    "Linear momentum",
    "Torque and rotational dynamics",
    "Energy and momentum of rotating systems",
    "Oscillations",
    "Fluids",
)

AP_PHYSICS_2_TOPICS = (
    "Thermodynamics",
    "Electric force, field and potential",
    "Electric circuits",
    "Magnetism and electromagnetism",
    "Geometric optics",
    "Waves, sound and physical optics",
    "Modern physics",
)

AP_PHYSICS_C_MECHANICS_TOPICS = (
    "Kinematics",
    "Force and translational dynamics",
    "Work, energy and power",
    "Linear momentum",
    "Torque and rotational dynamics",
    "Energy and momentum of rotating systems",
    "Oscillations",
)

AP_PHYSICS_C_EM_TOPICS = (
    "Electric charges, fields and Gauss's law",
    "Electric potential",
    "Conductors and capacitors",
    "Electric circuits",
    "Magnetic fields and electromagnetism",
    "Electromagnetic induction",
)

SHANGHAI_SCIENCE_TECH_GRADE_9_CHEMISTRY_TOPICS = (
    "专题7 溶液",
    "专题8 酸、碱、盐",
    "专题9 化学反应的调控",
    "专题10 化学与人类社会进步",
)


def _grade_levels(start: int = 1, end: int = 12) -> tuple[dict, ...]:
    return tuple(
        {
            "id": f"grade-{grade}",
            "name": f"Grade {grade}",
            "name_zh": f"{grade} 年级",
        }
        for grade in range(start, end + 1)
    )


def _single_level(level_id: str, name: str, name_zh: str) -> tuple[dict, ...]:
    return ({"id": level_id, "name": name, "name_zh": name_zh},)


CURRICULA = (
    {
        "id": "cambridge-igcse-additional-mathematics-0606",
        "code": "0606",
        "name": "Cambridge IGCSE Additional Mathematics",
        "name_zh": "剑桥 IGCSE 附加数学",
        "subject": "mathematics",
        "status": "verified",
        "version": "2025-2027",
        "module": "0606",
        "practice_source": "bank",
        "levels": _single_level("standard", "Standard", "标准"),
        "default_level": "standard",
        "topics": CAMBRIDGE_0606_TOPICS,
    },
    {
        "id": "general-mathematics",
        "code": "General",
        "name": "General Mathematics",
        "name_zh": "通用数学",
        "subject": "mathematics",
        "status": "beta",
        "version": "grade-bands-v1",
        "module": "generated-mathematics",
        "practice_source": "generated",
        "levels": _grade_levels(),
        "default_level": "grade-9",
        "topics": GENERAL_MATH_TOPICS,
    },
    {
        "id": "china-national-mathematics",
        "code": "CN Math",
        "name": "Chinese National Mathematics",
        "name_zh": "中国国家课程数学",
        "subject": "mathematics",
        "status": "beta",
        "version": "2022-compulsory-2017-2020-senior",
        "module": "generated-mathematics",
        "practice_source": "generated",
        "levels": _grade_levels(),
        "default_level": "grade-9",
        "topics": CHINESE_MATH_TOPICS,
    },
    {
        "id": "cambridge-igcse-mathematics-0580",
        "code": "0580",
        "name": "Cambridge IGCSE Mathematics",
        "name_zh": "剑桥 IGCSE 数学",
        "subject": "mathematics",
        "status": "beta",
        "version": "2025-2027",
        "module": "generated-mathematics",
        "practice_source": "generated",
        "levels": (
            {"id": "core", "name": "Core", "name_zh": "核心"},
            {"id": "extended", "name": "Extended", "name_zh": "扩展"},
        ),
        "default_level": "extended",
        "topics": CAMBRIDGE_0580_TOPICS,
    },
    {
        "id": "ap-precalculus",
        "code": "AP",
        "name": "AP Precalculus",
        "name_zh": "AP 预备微积分",
        "subject": "mathematics",
        "status": "beta",
        "version": "2026-2027",
        "module": "generated-mathematics",
        "practice_source": "generated",
        "levels": _single_level("course", "Full course", "完整课程"),
        "default_level": "course",
        "topics": AP_PRECALCULUS_TOPICS,
    },
    {
        "id": "ap-calculus-ab",
        "code": "AP",
        "name": "AP Calculus AB",
        "name_zh": "AP 微积分 AB",
        "subject": "mathematics",
        "status": "beta",
        "version": "2026-2027",
        "module": "generated-mathematics",
        "practice_source": "generated",
        "levels": _single_level("course", "Full course", "完整课程"),
        "default_level": "course",
        "topics": AP_CALCULUS_AB_TOPICS,
    },
    {
        "id": "ap-calculus-bc",
        "code": "AP",
        "name": "AP Calculus BC",
        "name_zh": "AP 微积分 BC",
        "subject": "mathematics",
        "status": "beta",
        "version": "2026-2027",
        "module": "generated-mathematics",
        "practice_source": "generated",
        "levels": _single_level("course", "Full course", "完整课程"),
        "default_level": "course",
        "topics": AP_CALCULUS_BC_TOPICS,
    },
    {
        "id": "ap-statistics",
        "code": "AP",
        "name": "AP Statistics",
        "name_zh": "AP 统计学",
        "subject": "mathematics",
        "status": "beta",
        "version": "2026-2027-revised",
        "module": "generated-statistics",
        "practice_source": "generated",
        "levels": _single_level("course", "Full course", "完整课程"),
        "default_level": "course",
        "topics": AP_STATISTICS_TOPICS,
    },
    {
        "id": "cambridge-igcse-physics-0625",
        "code": "0625",
        "name": "Cambridge IGCSE Physics",
        "name_zh": "剑桥 IGCSE 物理",
        "subject": "physics",
        "status": "beta",
        "version": "2026-2028",
        "module": "generated-physics",
        "practice_source": "generated",
        "levels": (
            {"id": "core", "name": "Core", "name_zh": "核心"},
            {"id": "extended", "name": "Extended", "name_zh": "扩展"},
        ),
        "default_level": "extended",
        "topics": IGCSE_PHYSICS_0625_TOPICS,
    },
    {
        "id": "ap-physics-1",
        "code": "AP",
        "name": "AP Physics 1: Algebra-Based",
        "name_zh": "AP 物理 1（代数基础）",
        "subject": "physics",
        "status": "beta",
        "version": "2026-2027",
        "module": "generated-physics",
        "practice_source": "generated",
        "levels": _single_level("course", "Full course", "完整课程"),
        "default_level": "course",
        "topics": AP_PHYSICS_1_TOPICS,
    },
    {
        "id": "ap-physics-2",
        "code": "AP",
        "name": "AP Physics 2: Algebra-Based",
        "name_zh": "AP 物理 2（代数基础）",
        "subject": "physics",
        "status": "beta",
        "version": "2026-2027",
        "module": "generated-physics",
        "practice_source": "generated",
        "levels": _single_level("course", "Full course", "完整课程"),
        "default_level": "course",
        "topics": AP_PHYSICS_2_TOPICS,
    },
    {
        "id": "ap-physics-c-mechanics",
        "code": "AP",
        "name": "AP Physics C: Mechanics",
        "name_zh": "AP 物理 C：力学",
        "subject": "physics",
        "status": "beta",
        "version": "2026-2027",
        "module": "generated-physics",
        "practice_source": "generated",
        "levels": _single_level("course", "Full course", "完整课程"),
        "default_level": "course",
        "topics": AP_PHYSICS_C_MECHANICS_TOPICS,
    },
    {
        "id": "ap-physics-c-electricity-and-magnetism",
        "code": "AP",
        "name": "AP Physics C: Electricity and Magnetism",
        "name_zh": "AP 物理 C：电磁学",
        "subject": "physics",
        "status": "beta",
        "version": "2026-2027",
        "module": "generated-physics",
        "practice_source": "generated",
        "levels": _single_level("course", "Full course", "完整课程"),
        "default_level": "course",
        "topics": AP_PHYSICS_C_EM_TOPICS,
    },
    {
        "id": "shanghai-education-grade-9-chemistry-2026",
        "code": "沪科版",
        "name": "Shanghai Science and Technology Grade 9 Chemistry (Five-Four system, 2026 edition)",
        "name_zh": "沪科版（五四制）九年级化学（2026新版）",
        "subject": "chemistry",
        "status": "beta",
        "version": "2026-five-four-system-2025-revision",
        "module": "generated-chemistry",
        "practice_source": "generated",
        "levels": _single_level("grade-9", "Grade 9", "九年级"),
        "default_level": "grade-9",
        "topics": SHANGHAI_SCIENCE_TECH_GRADE_9_CHEMISTRY_TOPICS,
    },
)

DEFAULT_CURRICULUM_ID = CURRICULA[0]["id"]
DEFAULT_STUDY_LANGUAGE = "auto"
LEGACY_CURRICULUM_ALIASES = {
    "scottish-higher-physics": "ap-physics-1",
}


def curriculum_options() -> tuple[dict, ...]:
    return CURRICULA


def curriculum_by_id(curriculum_id: str | None) -> dict | None:
    selected = curriculum_id or DEFAULT_CURRICULUM_ID
    selected = LEGACY_CURRICULUM_ALIASES.get(selected, selected)
    return next(
        (curriculum for curriculum in CURRICULA if curriculum["id"] == selected),
        None,
    )


def available_curriculum(curriculum_id: str | None) -> dict:
    curriculum = curriculum_by_id(curriculum_id)
    if not curriculum or curriculum["status"] not in {"verified", "beta"}:
        raise ValueError("That curriculum is not available for analysis.")
    return curriculum


def verified_curriculum(curriculum_id: str | None) -> dict:
    """Compatibility name used by existing routes.

    Availability is now explicit in ``status``.  The name is kept so older
    imports and tests do not require a risky broad rename.
    """
    return available_curriculum(curriculum_id)


def normalise_level(curriculum: Mapping, level: str | None) -> str:
    level_ids = {str(item["id"]) for item in curriculum.get("levels", ())}
    candidate = str(level or "").strip()
    if candidate in level_ids:
        return candidate
    return str(curriculum.get("default_level") or next(iter(level_ids), "standard"))


def normalise_study_language(value: str | None) -> str:
    candidate = str(value or "auto").strip().lower()
    return candidate if candidate in {"auto", "en", "zh"} else "auto"


def curriculum_profile(
    curriculum_id: str | None,
    level: str | None = None,
    study_language: str | None = None,
) -> dict:
    curriculum = available_curriculum(curriculum_id)
    selected_level = normalise_level(curriculum, level)
    level_row = next(
        item for item in curriculum["levels"] if item["id"] == selected_level
    )
    return {
        **curriculum,
        "level": selected_level,
        "level_name": level_row["name"],
        "level_name_zh": level_row["name_zh"],
        "study_language": normalise_study_language(study_language),
    }


def profile_from_user(user: Mapping | None) -> dict:
    if not user:
        return curriculum_profile(DEFAULT_CURRICULUM_ID)
    keys = set(user.keys()) if hasattr(user, "keys") else set()
    curriculum_id = (
        user["curriculum_id"] if "curriculum_id" in keys else DEFAULT_CURRICULUM_ID
    )
    level = user["curriculum_level"] if "curriculum_level" in keys else None
    language = user["study_language"] if "study_language" in keys else None
    return curriculum_profile(curriculum_id, level, language)


def topics_for_curriculum(curriculum_id: str | None) -> tuple[str, ...]:
    curriculum = curriculum_by_id(curriculum_id)
    return tuple(curriculum.get("topics", ())) if curriculum else ()


def curriculum_prompt_context(profile: Mapping) -> str:
    language = {
        "auto": "Detect the language of each question and preserve it.",
        "en": "Questions and student-facing feedback should be in English.",
        "zh": "Questions may be Chinese; provide student-facing feedback in Simplified Chinese.",
    }[normalise_study_language(profile.get("study_language"))]
    topic_list = ", ".join(str(topic) for topic in profile.get("topics", ()))
    return (
        f"Subject: {profile['subject']}. Curriculum: {profile['name']} "
        f"({profile['code']}), version {profile['version']}. "
        f"Level: {profile['level_name']}. {language} "
        f"Classify every observed question into exactly one of these topics: "
        f"{topic_list}."
    )
