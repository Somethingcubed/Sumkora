"""Curriculum registry for the Sumkora assessment boundary.

Only curricula with ``status='verified'`` may be submitted to the active
assessment pipeline. Planned entries make the product direction visible
without claiming that untested marking and practice content already work.
"""

from __future__ import annotations


CURRICULA = (
    {
        "id": "cambridge-igcse-additional-mathematics-0606",
        "code": "0606",
        "name": "Cambridge IGCSE Additional Mathematics",
        "status": "verified",
        "module": "0606",
    },
    {
        "id": "cambridge-igcse-mathematics-0580",
        "code": "0580",
        "name": "Cambridge IGCSE Mathematics",
        "status": "planned",
        "module": None,
    },
    {"id": "ap-calculus-ab", "code": "AP", "name": "AP Calculus AB", "status": "planned", "module": None},
    {"id": "ap-calculus-bc", "code": "AP", "name": "AP Calculus BC", "status": "planned", "module": None},
    {"id": "ib-mathematics", "code": "IB", "name": "IB Mathematics", "status": "planned", "module": None},
    {"id": "a-level-mathematics", "code": "A Level", "name": "A-Level Mathematics", "status": "planned", "module": None},
    {"id": "general-mathematics", "code": "General", "name": "General Mathematics", "status": "planned", "module": None},
)

DEFAULT_CURRICULUM_ID = CURRICULA[0]["id"]


def curriculum_options() -> tuple[dict, ...]:
    return CURRICULA


def verified_curriculum(curriculum_id: str | None) -> dict:
    selected = curriculum_id or DEFAULT_CURRICULUM_ID
    for curriculum in CURRICULA:
        if curriculum["id"] == selected and curriculum["status"] == "verified":
            return curriculum
    raise ValueError("That curriculum is not yet available for paper analysis.")
