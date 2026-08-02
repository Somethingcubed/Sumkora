"""Shared, conservative topic normalisation for assessment and practice."""

from __future__ import annotations

import re


CANONICAL_TOPICS = (
    "Algebra",
    "Functions and graphs",
    "Coordinate geometry",
    "Geometry",
    "Trigonometry",
    "Calculus",
    "Sequences and series",
    "Vectors",
)


_TOPIC_PATTERNS = (
    ("Calculus", r"\b(?:calculus|differentiat\w*|derivative|integrat\w*|gradient function|rate of change)\b"),
    ("Trigonometry", r"\b(?:trigonom|sine|cosine|tangent function|radian|sin\b|cos\b|tan\b)\b"),
    ("Vectors", r"\b(?:vector|magnitude|column vector)\b"),
    ("Sequences and series", r"\b(?:sequences?|series|progressions?|binomial)\b"),
    ("Coordinate geometry", r"\b(?:coordinate geometry|straight line|line equation|midpoint|perpendicular bisector)\b"),
    ("Functions and graphs", r"\b(?:function|graph|transform|asymptote|domain|range|inverse function|composite function)\b"),
    ("Geometry", r"\b(?:geometry|circle|circular measure|tangent|chord|arc|sector|similar|congruen|area|volume|mensuration)\b"),
    ("Algebra", r"\b(?:algebra|equation|inequalit|exponential|logarithm|quadratic|polynomial|factor|indices|surd|partial fraction)\b"),
)


def _normalise(value: str) -> str:
    return re.sub(r"[_\-/]+", " ", str(value or "")).strip().lower()


def canonical_topic(topic: str = "", skill: str = "", text: str = "") -> str:
    """Return one stable, broad topic without inventing a specific classification."""
    combined = " ".join(_normalise(value) for value in (topic, skill, text) if value)
    for canonical, pattern in _TOPIC_PATTERNS:
        if re.search(pattern, combined, re.I):
            return canonical
    cleaned = str(topic or skill or "").replace("_", " ").strip()
    if not cleaned:
        return "Unclassified"
    return cleaned[:1].upper() + cleaned[1:]


def canonical_skill(skill: str = "", topic: str = "") -> str:
    cleaned = re.sub(r"\s+", " ", str(skill or "").replace("_", " ")).strip()
    if not cleaned or cleaned.lower() in {"other", "unknown", "unclassified"}:
        return canonical_topic(topic, cleaned)
    return cleaned[:1].lower() + cleaned[1:]


def topic_slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", canonical_topic(value).lower()).strip("-")
