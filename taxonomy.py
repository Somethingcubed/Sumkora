"""Shared, conservative topic normalisation for assessment and practice."""

from __future__ import annotations

import re

from curricula import topics_for_curriculum


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
    ("Number", r"\b(?:number|integer|fraction|decimal|percentage|ratio|proportion|standard form|prime|hcf|lcm)\b"),
    ("Probability", r"\b(?:probability|random variable|distribution|sample space|independent events?|conditional)\b"),
    ("Statistics", r"\b(?:statistics?|mean|median|mode|frequency|histogram|regression|inference|sampling|data)\b"),
)


_CURRICULUM_TOPIC_PATTERNS = {
    "china-national-mathematics": (
        ("Statistics and probability", r"统计|概率|数据|抽样|statistics|probability|data|sampling"),
        ("Graphics and geometry", r"图形|几何|圆|角|面积|体积|geometry|circle|angle|area|volume"),
        ("Functions", r"函数|function|graph"),
        ("Mathematical modelling and practice", r"建模|综合实践|modelling|modeling|investigation|project"),
        ("Number and algebra", r"数与代数|方程|不等式|数列|代数|equation|inequalit|algebra|number|sequence"),
    ),
    "cambridge-igcse-physics-0625": (
        ("Experimental skills and investigations", r"experiment|practical|apparatus|uncertaint|variable|误差|实验"),
        ("Motion, forces and energy", r"motion|speed|velocity|acceleration|force|momentum|energy|power|运动|力|能量"),
        ("Thermal physics", r"thermal|temperature|heat|gas|specific heat|latent|热|温度"),
        ("Waves", r"wave|light|sound|frequency|wavelength|refraction|波|光|声音"),
        ("Electricity and magnetism", r"electric|current|voltage|resistance|circuit|magnet|电|磁"),
        ("Nuclear physics", r"nuclear|radioactive|half-life|atom|radiation|核|放射"),
        ("Space physics", r"space|orbit|planet|star|universe|redshift|宇宙|恒星|行星"),
    ),
    "scottish-higher-physics": (
        ("Experimental and investigative skills", r"experiment|investigat|uncertaint|practical|实验|误差"),
        ("Our dynamic Universe", r"motion|force|energy|impulse|gravitation|relativity|universe|运动|力|宇宙"),
        ("Particles and waves", r"particle|wave|nuclear|interference|spectr|refraction|粒子|波|光谱"),
        ("Electricity", r"electric|current|voltage|resistance|capacitor|semiconductor|电|电容|半导体"),
    ),
}


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


def canonical_topic_for_curriculum(
    curriculum_id: str,
    topic: str = "",
    skill: str = "",
    text: str = "",
) -> str:
    """Return a topic from the selected curriculum without inventing evidence."""
    allowed = topics_for_curriculum(curriculum_id)
    if not allowed:
        return canonical_topic(topic, skill, text)
    candidate = _normalise(topic)
    for allowed_topic in allowed:
        if candidate == _normalise(allowed_topic):
            return allowed_topic

    combined = " ".join(str(value or "") for value in (topic, skill, text))
    for allowed_topic, pattern in _CURRICULUM_TOPIC_PATTERNS.get(
        curriculum_id, ()
    ):
        if re.search(pattern, combined, re.I):
            return allowed_topic

    broad = canonical_topic(topic, skill, text)
    for allowed_topic in allowed:
        left = set(_normalise(allowed_topic).split())
        right = set(_normalise(broad).split())
        if left & right:
            return allowed_topic
    return "Unclassified"


def topic_slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", canonical_topic(value).lower()).strip("-")
