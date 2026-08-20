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
    "ap-physics-1": (
        ("Energy and momentum of rotating systems", r"angular momentum|rotational energy|rolling|角动量|转动能"),
        ("Torque and rotational dynamics", r"torque|rotational dynamics|moment of inertia|力矩|转动惯量"),
        ("Linear momentum", r"linear momentum|impulse|collision|线动量|冲量|碰撞"),
        ("Work, energy and power", r"work|energy|power|功|能量|功率"),
        ("Force and translational dynamics", r"force|newton|friction|translational|力|牛顿|摩擦"),
        ("Kinematics", r"kinematic|position|velocity|acceleration|projectile|位移|速度|加速度|抛体"),
        ("Oscillations", r"oscillat|simple harmonic|pendulum|振动|简谐|摆"),
        ("Fluids", r"fluid|pressure|buoy|continuity|bernoulli|流体|浮力|伯努利"),
    ),
    "ap-physics-2": (
        ("Thermodynamics", r"thermodynamic|temperature|heat|entropy|ideal gas|热力学|温度|熵"),
        ("Electric force, field and potential", r"electric force|electric field|electric potential|coulomb|电场|电势|库仑"),
        ("Electric circuits", r"circuit|current|resistance|kirchhoff|电路|电流|电阻"),
        ("Magnetism and electromagnetism", r"magnet|electromagnet|magnetic field|磁场|电磁"),
        ("Geometric optics", r"geometric optic|mirror|lens|ray|几何光学|透镜|光线"),
        ("Waves, sound and physical optics", r"wave|sound|interference|diffraction|波|声音|干涉|衍射"),
        ("Modern physics", r"modern physics|quantum|nuclear|relativity|photoelectric|量子|核物理|相对论|光电"),
    ),
    "ap-physics-c-mechanics": (
        ("Energy and momentum of rotating systems", r"angular momentum|rotational energy|rolling|角动量|转动能"),
        ("Torque and rotational dynamics", r"torque|rotational dynamics|moment of inertia|力矩|转动惯量"),
        ("Linear momentum", r"linear momentum|impulse|collision|线动量|冲量|碰撞"),
        ("Work, energy and power", r"work|energy|power|功|能量|功率"),
        ("Force and translational dynamics", r"force|newton|friction|translational|力|牛顿|摩擦"),
        ("Kinematics", r"kinematic|position|velocity|acceleration|projectile|位移|速度|加速度|抛体"),
        ("Oscillations", r"oscillat|simple harmonic|pendulum|振动|简谐|摆"),
    ),
    "ap-physics-c-electricity-and-magnetism": (
        ("Electric charges, fields and Gauss's law", r"gauss|electric charge|electric field|flux|高斯|电荷|电通量"),
        ("Electric potential", r"electric potential|potential energy|电势|电势能"),
        ("Conductors and capacitors", r"conductor|capacitor|capacitance|dielectric|导体|电容|介电"),
        ("Electric circuits", r"circuit|current|resistance|kirchhoff|电路|电流|电阻"),
        ("Magnetic fields and electromagnetism", r"magnetic field|lorentz|ampere|磁场|洛伦兹|安培"),
        ("Electromagnetic induction", r"induction|faraday|lenz|inductance|电磁感应|法拉第|楞次"),
    ),
    "shanghai-education-grade-9-chemistry-2026": (
        ("第1章 开启化学之门", r"化学科学|物理变化|化学变化|物理性质|化学性质|实验基本操作|实验安全|开启化学|chemical science|physical change|chemical change|laboratory safety"),
        ("第2章 空气与水资源", r"空气|氧气|氮气|稀有气体|水的组成|水的净化|电解水|制取氧气|air|oxygen|nitrogen|water purification|electrolysis of water"),
        ("第3章 物质构成的奥秘", r"分子|原子|离子|元素|元素符号|化学式|相对原子质量|相对分子质量|化合价|\b(?:molecule|atom|ion|element|chemical formula|relative atomic mass|valency)\b"),
        ("第4章 认识化学反应", r"反应条件|质量守恒|化学方程式|燃烧条件|化学反应|mass conservation|chemical equation|reaction condition|combustion condition"),
        ("第5章 奇妙的二氧化碳", r"二氧化碳|碳循环|温室效应|实验室制取.*二氧化碳|carbon dioxide|carbon cycle|greenhouse effect"),
        ("第6章 金属资源综合利用", r"金属|合金|铁的冶炼|金属活动性|金属腐蚀|金属防护|废金属|metal|alloy|iron extraction|reactivity series|corrosion"),
        ("第8章 酸、碱、盐及其应用", r"酸碱性|酸|碱|盐|pH|指示剂|中和反应|复分解|acid|alkali|base|salt|indicator|neutralisation|neutralization"),
        ("第7章 探索溶解现象", r"溶液|溶质|溶剂|溶解度|饱和溶液|不饱和溶液|溶质质量分数|结晶|solution|solute|solvent|solubility|saturated|mass fraction|crystalli[sz]ation"),
        ("第9章 化学与社会可持续发展", r"人类健康|营养素|能源|材料|环境污染|可持续发展|health|nutrient|energy resource|material|pollution|sustainable development"),
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
