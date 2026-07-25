import os
import re
import sys
import unicodedata

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import fitz

from db import connect, execute, init_db, query_one, update_assignment_total_marks
from topics import TOPICS

ROOT = os.path.dirname(os.path.dirname(__file__))
PAPERS_DIR = os.path.join(ROOT, "Past Papers")

SESSION_NAMES = {
    "w": "Oct/Nov",
    "s": "May/June",
    "m": "March",
}

PAPER_NAMES = {
    "1": "Paper 1 (Core)",
    "2": "Paper 2 (Extended, non-calculator)",
    "3": "Paper 3 (Core)",
    "4": "Paper 4 (Extended, calculator)",
}

MAX_QUESTION = {
    "1": 30,
    "2": 30,
    "3": 30,
    "4": 30,
}

QID_RE = re.compile(r"^\d{1,2}(?:\([a-z]+\)|\([ivx]+\))*$", re.I)
PART_RE = re.compile(r"(?m)(?:^|\n)\s*\(([a-z]+|[ivx]+)\)\s*")


def valid_pdf(path: str) -> bool:
    if os.path.getsize(path) < 500:
        return False
    doc = fitz.open(path)
    ok = len(doc) > 0
    doc.close()
    return ok


def pdf_text(path: str) -> str:
    doc = fitz.open(path)
    parts = []
    for page in doc:
        parts.append(page.get_text())
    doc.close()
    return "\n".join(parts)


def cover_total_marks(path: str) -> int | None:
    doc = fitz.open(path)
    text = doc[0].get_text() if len(doc) else ""
    doc.close()
    match = re.search(r"total mark for this paper is (\d+)", text, re.I)
    return int(match.group(1)) if match else None


def normalize_pdf_text(text: str) -> str:
    text = unicodedata.normalize("NFKC", text)
    cleaned = []
    for ch in text:
        if ch == "\n" or ch == "\t" or ord(ch) >= 32:
            cleaned.append(ch)
    text = "".join(cleaned)
    text = text.replace("\uf0b4", "x")
    text = text.replace("\uf0e6", "(").replace("\uf0f6", ")")
    text = text.replace("\uf0e7", "(").replace("\uf0f7", ")")
    text = text.replace("\uf0e8", "(").replace("\uf0f8", ")")
    return text


def clean_text(text: str) -> str:
    text = normalize_pdf_text(text)
    text = re.sub(r"DO NOT WRITE IN THIS MARGIN.*", "", text)
    text = re.sub(r"\* 0+\d+ \*", "", text)
    text = re.sub(r"0580/\d+/[A-Z]/[A-Z]/\d+", "", text)
    text = re.sub(r"© UCLES \d+", "", text)
    text = re.sub(r"© Cambridge University Press.*", "", text)
    text = re.sub(r"Cambridge IGCSE.*", "", text)
    text = re.sub(r"\bDFD\b", "", text)
    text = re.sub(r"[¬¥ĬĤĥ][^\n]*", "", text)
    return text


def guess_topic(text: str) -> str:
    lower = text.lower()
    keywords = {
        "Trigonometry": ["sin", "cos", "tan", "triangle", "bearing", "sine rule"],
        "Statistics": ["mean", "median", "frequency", "histogram", "cumulative", "pie chart"],
        "Probability": ["probability", "tree diagram", "without replacement", "venn"],
        "Algebra": ["solve", "factorise", "expand", "quadratic", "simultaneous", "inequalit"],
        "Geometry": ["angle", "parallel", "polygon", "circle", "tangent", "congruent"],
        "Number": ["prime", "lcm", "hcf", "standard form", "percentage", "factor"],
        "Graphs": ["gradient", "y-intercept", "coordinates", "straight line", "y ="],
        "Mensuration": ["volume", "surface area", "cylinder", "sphere", "cuboid", "cm3"],
        "Functions": ["function", "f(x)", "inverse"],
        "Sequences": ["sequence", "nth term"],
        "Vectors": ["vector"],
    }
    for topic, words in keywords.items():
        if any(w in lower for w in words):
            return topic
    return TOPICS[0]


def parse_marks(text: str) -> int:
    found = re.findall(r"\[(\d+)\]", text)
    if found:
        return int(found[-1])
    return 1


def parse_scheme_marks(text: str) -> int:
    partial_candidates = []
    standalone_candidates = []
    for line in text.splitlines():
        line = line.strip()
        m = re.match(r"^([1-9])\s+(?:[MAB]\d|FT|B\d|M\d|A\d|If|Strict|SC)", line)
        if m:
            partial_candidates.append(int(m.group(1)))
            continue
        m = re.fullmatch(r"([1-9])", line)
        if m:
            standalone_candidates.append(int(m.group(1)))
            continue
        m = re.match(r"^[MAB](\d)", line)
        if m:
            partial_candidates.append(int(m.group(1)))
    if partial_candidates:
        return partial_candidates[0]
    if standalone_candidates:
        return standalone_candidates[-1]
    return 1


def ms_id_to_label(qid: str) -> str:
    qid = qid.strip()
    m = re.match(r"^(\d{1,2})(.*)$", qid)
    if not m:
        return f"Q{qid}"
    num = m.group(1)
    rest = m.group(2)
    parts = re.findall(r"\(([a-z]+|[ivx]+)\)", rest, flags=re.I)
    suffix = "".join(p.lower() for p in parts)
    return f"Q{num}{suffix}"


def squash_whitespace(text: str) -> str:
    text = clean_text(text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def is_noise_block(text: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return True
    noise_bits = [
        "DO NOT WRITE IN THIS MARGIN",
        "This document has",
        "Cambridge IGCSE",
        "INSTRUCTIONS",
        "INFORMATION",
        "List of formulas",
        "© UCLES",
        "DFD",
        "Permission to reproduce items",
        "To avoid the issue of disclosure",
        "Cambridge Assessment International Education is part",
    ]
    if any(bit in stripped for bit in noise_bits):
        return True
    if re.fullmatch(r"[\W_]+", stripped):
        return True
    if re.match(r"^[¬¥ĬĤĥ]", stripped):
        return True
    if re.match(r"^\*?\s*0{4,}", stripped):
        return True
    return False


def first_clean_line(text: str) -> str:
    for line in normalize_pdf_text(text).splitlines():
        line = line.strip()
        if line:
            return line
    return ""


def is_question_start_block(x0: float, y0: float, text: str) -> bool:
    if x0 > 90 or y0 < 60:
        return False
    first = first_clean_line(text)
    match = re.match(r"^(\d{1,2})(?:\s+\S|$)", first)
    return bool(match and 1 <= int(match.group(1)) <= 30)


def question_blocks(pdf_path: str) -> list[dict]:
    doc = fitz.open(pdf_path)
    questions = []
    current = None
    highest_number = 0

    def flush():
        nonlocal current
        if current:
            current["text"] = squash_whitespace("\n".join(current["parts"]))
            if current["text"]:
                questions.append(current)
        current = None

    for page_index, page in enumerate(doc):
        if page_index < 2:
            continue
        blocks = sorted(page.get_text("blocks"), key=lambda b: (b[1], b[0]))
        for block in blocks:
            x0, y0, x1, y1, text = block[:5]
            if y0 < 60 or y0 > 780:
                continue
            text = normalize_pdf_text(text)
            if is_noise_block(text):
                continue
            if is_question_start_block(x0, y0, text):
                first = first_clean_line(text)
                number = int(re.match(r"^(\d{1,2})", first).group(1))
                if number < 1 or number > 30:
                    continue
                if number <= highest_number:
                    if current:
                        current["parts"].append(text.strip())
                    continue
                flush()
                highest_number = number
                current = {
                    "number": number,
                    "page_number": page_index + 1,
                    "parts": [re.sub(r"^\s*\d{1,2}\s*", "", text, count=1).strip()],
                }
            elif current:
                current["parts"].append(text.strip())

    flush()
    doc.close()
    questions.sort(key=lambda q: (q["number"], q["page_number"]))
    return questions


def is_real_question_body(body: str) -> bool:
    if len(body) < 12:
        return False
    if "List of formulas" in body:
        return False
    if re.search(r"\[\d+\]", body):
        return True
    words = re.findall(r"[A-Za-z]{4,}", body)
    return len(words) >= 4


def parse_marks(text: str) -> int:
    found = re.findall(r"\[(\d+)\]", text)
    if found:
        return int(found[-1])
    return 1


def part_matches_for_level(text: str, prefix: str = ""):
    matches = list(PART_RE.finditer(text))
    if not matches:
        return []
    alpha = [m for m in matches if re.fullmatch(r"[a-z]+", m.group(1), flags=re.I)]
    roman = [m for m in matches if re.fullmatch(r"[ivx]+", m.group(1), flags=re.I)]
    if not prefix and alpha:
        return alpha
    if prefix and roman:
        return roman
    if not prefix:
        return roman
    return []


def split_part_questions(qnum: int, text: str, page_number: int, prefix: str = "") -> list[dict]:
    matches = part_matches_for_level(text, prefix)
    if not matches:
        body = squash_whitespace(text)
        if not is_real_question_body(body):
            return []
        return [
            {
                "label": f"Q{qnum}{prefix}",
                "text": body[:1600],
                "max_marks": parse_marks(body),
                "topic": guess_topic(body),
                "page_number": page_number,
            }
        ]

    intro = text[: matches[0].start()].strip()
    parts = []
    for idx, match in enumerate(matches):
        marker = match.group(1).lower()
        start = match.end()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)
        part_body = text[start:end].strip()
        full = f"{intro}\n{part_body}".strip() if intro else part_body
        nested = split_part_questions(qnum, full, page_number, prefix + marker)
        parts.extend(nested)
    return parts


def parse_question_paper_path(path: str) -> list[dict]:
    seen = {}
    for block in question_blocks(path):
        body = block["text"]
        if not is_real_question_body(body):
            continue
        for q in split_part_questions(block["number"], body, block["page_number"]):
            if q["label"] not in seen:
                seen[q["label"]] = q

    questions = list(seen.values())
    questions.sort(key=lambda q: (int(re.match(r"Q(\d+)", q["label"]).group(1)), q["label"]))
    return questions


def parse_question_paper(text: str) -> list[dict]:
    """Fallback parser for callers that only have extracted text."""
    text = clean_text(text)
    starts = []
    for m in re.finditer(r"(?m)^\s*(\d{1,2})\s*$", text):
        number = int(m.group(1))
        if 1 <= number <= 30:
            starts.append((m.start(), str(number)))
    seen = {}
    for i, (pos, qnum) in enumerate(starts):
        end = starts[i + 1][0] if i + 1 < len(starts) else len(text)
        body = text[pos:end]
        body = re.sub(r"^\s*\d{1,2}\s*", "", body, count=1).strip()
        for q in split_part_questions(int(qnum), body, 1):
            seen.setdefault(q["label"], q)
    return sorted(seen.values(), key=lambda q: (int(re.match(r"Q(\d+)", q["label"]).group(1)), q["label"]))


def filter_questions_for_variant(questions: list[dict], variant: str) -> list[dict]:
    limit = MAX_QUESTION.get(variant[0], 25)
    kept = []
    for q in questions:
        num = int(re.match(r"Q(\d+)", q["label"]).group(1))
        if num <= limit:
            kept.append(q)
    return kept


def refresh_assignment_questions(assignment_id: int, questions: list[dict], schemes: dict[str, dict]) -> int:
    execute("DELETE FROM questions WHERE assignment_id = ?", (assignment_id,))
    added = 0
    for idx, q in enumerate(questions):
        scheme = schemes.get(q["label"], {})
        mark_text = scheme.get("answer", "")
        if mark_text:
            mark_text = f"Answer / marking notes: {mark_text}"
        execute(
            """
            INSERT INTO questions
            (assignment_id, label, topic, question_text, max_marks, mark_scheme_text, page_number, order_index)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                assignment_id,
                q["label"],
                q["topic"],
                q["text"],
                q["max_marks"],
                mark_text,
                q.get("page_number", 1),
                idx,
            ),
        )
        added += 1
    update_assignment_total_marks(assignment_id)
    return added


def refresh_practice_entries(source_key: str, questions: list[dict], schemes: dict[str, dict]) -> int:
    execute("DELETE FROM practice_questions WHERE source = ?", (source_key,))
    added = 0
    for q in questions:
        label = f"{source_key}-{q['label']}"
        scheme = schemes.get(q["label"], {})
        extra = ""
        if scheme.get("answer"):
            extra = f" | MS: {scheme['answer'][:260]}"
        execute(
            """
            INSERT INTO practice_questions (topic, label, text, source)
            VALUES (?, ?, ?, ?)
            """,
            (q["topic"], label, q["text"] + extra, source_key),
        )
        added += 1
    return added


def parse_mark_scheme_path(path: str) -> dict[str, dict]:
    doc = fitz.open(path)
    rows = {}
    current = None
    in_table = False

    def flush():
        nonlocal current
        if not current:
            return
        text = squash_whitespace("\n".join(current["parts"]))
        if text:
            rows[current["label"]] = {
                "answer": text[:1200],
                "max_marks": parse_scheme_marks(text),
            }
        current = None

    for page in doc:
        page_text = normalize_pdf_text(page.get_text())
        if "Question" in page_text and "Answer" in page_text and "Partial Marks" in page_text:
            in_table = True
        if not in_table:
            continue
        blocks = sorted(page.get_text("blocks"), key=lambda b: (b[1], b[0]))
        for block in blocks:
            x0, y0, x1, y1, text = block[:5]
            if y0 < 70 or y0 > 770:
                continue
            text = normalize_pdf_text(text)
            if is_noise_block(text):
                continue
            first = first_clean_line(text)
            if x0 <= 95 and QID_RE.fullmatch(first):
                if int(re.match(r"^\d{1,2}", first).group(0)) > 30:
                    continue
                flush()
                label = ms_id_to_label(first)
                remainder = re.sub(r"^\s*" + re.escape(first) + r"\s*", "", text, count=1).strip()
                current = {"label": label, "parts": [remainder] if remainder else []}
            elif current:
                current["parts"].append(text.strip())
    flush()
    doc.close()
    return rows


def sort_label_key(label: str):
    m = re.match(r"Q(\d+)(.*)", label)
    if not m:
        return (999, label)
    return (int(m.group(1)), m.group(2))


def best_question_match(label: str, parsed: dict[str, dict]) -> dict | None:
    if label in parsed:
        return parsed[label]
    m = re.match(r"Q(\d+)(.*)", label)
    if not m:
        return None
    number = m.group(1)
    suffix = m.group(2)
    while suffix:
        suffix = suffix[:-1]
        candidate = f"Q{number}{suffix}"
        if candidate in parsed:
            return parsed[candidate]
    for qlabel, question in parsed.items():
        if re.match(rf"Q{number}(?:\D|$)", qlabel):
            return question
    return None


def questions_from_schemes(parsed_questions: list[dict], schemes: dict[str, dict]) -> list[dict]:
    parsed = {q["label"]: q for q in parsed_questions}
    questions = []
    for label, scheme in schemes.items():
        exact = label in parsed
        match = best_question_match(label, parsed)
        text = match["text"] if match else ""
        topic = match["topic"] if match else guess_topic(text)
        page_number = match["page_number"] if match else 1
        max_marks = match["max_marks"] if exact and match else scheme.get("max_marks", 1)
        questions.append(
            {
                "label": label,
                "text": text,
                "max_marks": max_marks,
                "topic": topic,
                "page_number": page_number,
            }
        )
    questions.sort(key=lambda q: sort_label_key(q["label"]))
    return questions


def parse_mark_scheme(text: str) -> dict[str, dict]:
    """Fallback parser for callers that only have extracted text."""
    text = clean_text(text)
    rows = {}
    for match in re.finditer(r"(?ms)^\s*(\d{1,2}(?:\([a-z]+\)|\([ivx]+\))*)\s*\n(.*?)(?=^\s*\d{1,2}(?:\([a-z]+\)|\([ivx]+\))*\s*$|\Z)", text):
        qid = match.group(1).strip()
        answer = squash_whitespace(match.group(2))
        if answer:
            rows[ms_id_to_label(qid)] = {
                "answer": answer[:1200],
                "max_marks": parse_scheme_marks(answer),
            }
    return rows


def parse_filename(name: str):
    m = re.match(r"0580_([wsm])(\d{2})_(qp|ms|gt|er|in)(?:_(\d{2}))?\.pdf", name, re.I)
    if not m:
        return None
    session, year, kind, variant = m.groups()
    return {
        "session": session,
        "year": f"20{year}",
        "kind": kind.lower(),
        "variant": variant,
        "session_name": SESSION_NAMES.get(session, session),
    }


def paper_title(meta: dict) -> str:
    paper_digit = meta["variant"][0]
    paper_label = PAPER_NAMES.get(paper_digit, f"Paper {paper_digit}")
    return f"{meta['session_name']} {meta['year']} — {paper_label} (Variant {meta['variant']})"


def scan_files():
    qp_files = {}
    ms_files = {}
    skipped = []

    for name in os.listdir(PAPERS_DIR):
        if not name.lower().endswith(".pdf"):
            continue
        path = os.path.join(PAPERS_DIR, name)
        meta = parse_filename(name)
        if not meta:
            skipped.append((name, "unrecognized filename"))
            continue
        if meta["kind"] in ("gt", "er", "in"):
            skipped.append((name, f"{meta['kind']} file not used for questions"))
            continue
        if not valid_pdf(path):
            skipped.append((name, "empty or invalid PDF"))
            continue
        rel = os.path.join("Past Papers", name)
        if meta["kind"] == "qp" and meta["variant"]:
            qp_files[meta["variant"]] = {"path": rel, "meta": meta, "name": name}
        elif meta["kind"] == "ms" and meta["variant"]:
            ms_files[meta["variant"]] = {"path": rel, "meta": meta, "name": name}
    return qp_files, ms_files, skipped


def get_teacher_class():
    row = query_one(
        """
        SELECT c.id AS class_id, c.teacher_id
        FROM classes c
        ORDER BY c.id LIMIT 1
        """
    )
    return row


def ingest():
    init_db()
    if not os.path.isdir(PAPERS_DIR):
        print(f"Missing folder: {PAPERS_DIR}")
        return

    qp_files, ms_files, skipped = scan_files()
    teacher_class = get_teacher_class()
    if not teacher_class:
        print("No class found. Run the app once to seed demo data.")
        return

    class_id = teacher_class["class_id"]
    practice_added = 0
    assignments_added = 0
    questions_added = 0
    assignments_refreshed = 0
    submissions_reset = 0
    missing_ms = []
    quality_warnings = []

    for variant in sorted(qp_files.keys()):
        qp = qp_files[variant]
        ms = ms_files.get(variant)
        if not ms:
            missing_ms.append(qp["name"])
            continue

        qp_abs = os.path.join(ROOT, qp["path"])
        ms_abs = os.path.join(ROOT, ms["path"])
        parsed_questions = filter_questions_for_variant(
            parse_question_paper_path(qp_abs), variant
        )
        schemes = parse_mark_scheme_path(ms_abs)
        questions = questions_from_schemes(parsed_questions, schemes)

        if not questions:
            skipped.append((qp["name"], "no questions parsed"))
            continue
        expected_total = cover_total_marks(qp_abs)
        parsed_total = sum(q["max_marks"] for q in questions)
        blank_text = sum(1 for q in questions if not q.get("text"))
        if expected_total and parsed_total != expected_total:
            quality_warnings.append(
                f"{qp['name']}: parsed {parsed_total} marks, cover says {expected_total}"
            )
        if blank_text:
            quality_warnings.append(
                f"{qp['name']}: {blank_text} question rows have no extracted question text"
            )

        title = paper_title(qp["meta"])
        source_key = qp["name"].replace(".pdf", "")

        existing_assignment = query_one(
            "SELECT id FROM assignments WHERE title = ?",
            (title,),
        )
        if existing_assignment:
            assignment_id = existing_assignment["id"]
            execute(
                """
                UPDATE assignments
                SET question_paper_path = ?, mark_scheme_path = ?, status = 'published'
                WHERE id = ?
                """,
                (qp["path"], ms["path"], assignment_id),
            )
            assignments_refreshed += 1
        else:
            assignment_id = execute(
                """
                INSERT INTO assignments
                (class_id, title, type, status, question_paper_path, mark_scheme_path, created_at)
                VALUES (?, ?, 'past_paper', 'published', ?, ?, datetime('now'))
                """,
                (class_id, title, qp["path"], ms["path"]),
            )
            assignments_added += 1

        questions_added += refresh_assignment_questions(assignment_id, questions, schemes)
        practice_added += refresh_practice_entries(source_key, questions, schemes)

        reset_count = query_one(
            "SELECT COUNT(*) AS c FROM submissions WHERE assignment_id = ?",
            (assignment_id,),
        )["c"]
        if reset_count:
            execute(
                "UPDATE submissions SET status = 'pending' WHERE assignment_id = ?",
                (assignment_id,),
            )
            submissions_reset += reset_count

    print("=== Ingest complete ===")
    print(f"Assignments added: {assignments_added}")
    print(f"Assignments refreshed: {assignments_refreshed}")
    print(f"Questions refreshed: {questions_added}")
    print(f"Practice bank entries refreshed: {practice_added}")
    print(f"Submissions reset for review after question refresh: {submissions_reset}")
    print(f"Question papers processed: {len(qp_files)}")
    print(f"Mark schemes available: {len(ms_files)}")

    if skipped:
        print("\nSkipped files:")
        for name, reason in skipped:
            print(f"  - {name}: {reason}")

    if missing_ms:
        print("\nMissing mark schemes (add these yourself):")
        for name in missing_ms:
            variant = parse_filename(name)["variant"]
            print(f"  - 0580_*_ms_{variant}.pdf for {name}")

    if quality_warnings:
        print("\nExtraction warnings (teacher should review these in the UI):")
        for warning in quality_warnings:
            print(f"  - {warning}")

    all_variants = {f"{s}{y}" for s in "wsm" for y in range(2, 26)}
    found_sessions = {f"{qp['meta']['session']}{qp['meta']['year'][-2:]}" for qp in qp_files.values()}
    print(f"\nSessions in folder: {sorted(found_sessions)}")
    print("Other years/sessions not in folder — add PDFs when you have them; ingest will pick them up.")


if __name__ == "__main__":
    ingest()
