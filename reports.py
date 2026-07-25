import json
import re
from html import escape
from datetime import datetime
from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)

from analytics import (
    analytics_practice,
    difficulty_label,
    question_type,
    student_analytics_summary,
)
from db import query_all, query_one
from i18n import question_type_label, strings, topic_label

pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))


def clean_text(text):
    text = re.sub(r"\\\((.*?)\\\)", r"\1", text or "")
    text = re.sub(r"\\\[(.*?)\\\]", r"\1", text)
    text = text.replace("\\text", "")
    text = text.replace("\\circ", "deg")
    text = text.replace("\\times", "x")
    text = text.replace("\\ldots", "...")
    text = text.replace("\\pi", "pi")
    text = text.replace("\\", "")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def practice_question_text(text):
    text = text or ""
    text = re.split(r"\|\s*MS:|MS:", text, maxsplit=1)[0]
    return clean_text(text)


def safe_filename(text):
    text = re.sub(r"[^A-Za-z0-9]+", "-", text or "report").strip("-").lower()
    return text[:80] or "report"


def pct(earned, possible):
    return round(100 * earned / possible, 1) if possible else 0


def font_for_lang(lang):
    return "STSong-Light" if lang == "zh" else "Helvetica"


def bold_font_for_lang(lang):
    return "STSong-Light" if lang == "zh" else "Helvetica-Bold"


def report_styles(lang="en"):
    base = getSampleStyleSheet()
    font = font_for_lang(lang)
    bold = bold_font_for_lang(lang)
    return {
        "title": ParagraphStyle(
            "ReportTitle",
            parent=base["Title"],
            fontName=bold,
            fontSize=18,
            leading=22,
            textColor=colors.HexColor("#1e1b4b"),
            spaceAfter=8,
        ),
        "h2": ParagraphStyle(
            "ReportH2",
            parent=base["Heading2"],
            fontName=bold,
            fontSize=12,
            leading=15,
            textColor=colors.HexColor("#312e81"),
            spaceBefore=10,
            spaceAfter=6,
        ),
        "body": ParagraphStyle(
            "ReportBody",
            parent=base["BodyText"],
            fontName=font,
            fontSize=9,
            leading=12,
            spaceAfter=4,
        ),
        "small": ParagraphStyle(
            "ReportSmall",
            parent=base["BodyText"],
            fontName=font,
            fontSize=8,
            leading=10,
            textColor=colors.HexColor("#475569"),
        ),
    }


def draw_footer(canvas, doc):
    canvas.saveState()
    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(colors.HexColor("#64748b"))
    canvas.drawString(1.5 * cm, 1.0 * cm, "Numera")
    canvas.drawRightString(A4[0] - 1.5 * cm, 1.0 * cm, f"Page {doc.page}")
    canvas.restoreState()


def build_pdf(story, title):
    buffer = BytesIO()
    doc = BaseDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=1.5 * cm,
        rightMargin=1.5 * cm,
        topMargin=1.4 * cm,
        bottomMargin=1.6 * cm,
        title=title,
    )
    frame = Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height, id="normal")
    doc.addPageTemplates([PageTemplate(id="page", frames=[frame], onPage=draw_footer)])
    doc.build(story)
    buffer.seek(0)
    return buffer.getvalue()


def cell(value, style):
    return Paragraph(escape(clean_text(str(value))), style)


def table(data, widths=None, header=True, lang="en"):
    styles = report_styles(lang)
    wrapped = [[cell(value, styles["body"]) for value in row] for row in data]
    tbl = Table(wrapped, colWidths=widths, hAlign="LEFT", repeatRows=1 if header else 0)
    style = [
        ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#cbd5e1")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("FONT", (0, 0), (-1, -1), font_for_lang(lang)),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("LEADING", (0, 0), (-1, -1), 10),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]
    if header:
        style.extend([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eef2ff")),
            ("FONT", (0, 0), (-1, 0), bold_font_for_lang(lang)),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#111827")),
        ])
    tbl.setStyle(TableStyle(style))
    return tbl


def p(text, style):
    return Paragraph(escape(clean_text(str(text))), style)


def student_context(student_id, teacher_id=None):
    teacher_filter = "AND c.teacher_id = ?" if teacher_id is not None else ""
    params = (student_id, teacher_id) if teacher_id is not None else (student_id,)
    return query_one(
        f"""
        SELECT u.*, c.name AS class_name
        FROM users u
        LEFT JOIN class_enrollments ce ON ce.student_id = u.id
        LEFT JOIN classes c ON c.id = ce.class_id
        WHERE u.id = ?
        {teacher_filter}
        ORDER BY c.id
        LIMIT 1
        """,
        params,
    )


def submission_context(submission_id):
    return query_one(
        """
        SELECT s.*, a.title AS assignment_title, a.due_date, a.total_marks,
               u.name AS student_name, u.id AS student_id,
               c.name AS class_name, c.teacher_id
        FROM submissions s
        JOIN assignments a ON a.id = s.assignment_id
        JOIN users u ON u.id = s.student_id
        JOIN classes c ON c.id = a.class_id
        WHERE s.id = ?
        """,
        (submission_id,),
    )


def assessment_rows(submission_id):
    return query_all(
        """
        SELECT gd.ai_mark, gd.ai_confidence, gd.ai_notes, gd.final_mark,
               gd.teacher_comment, gd.risk_flags, gd.needs_exception_review,
               gd.auto_finalize_reason, gd.teacher_override_mark,
               gd.teacher_override_comment,
               q.label, q.topic, q.question_text,
               q.mark_scheme_text, q.max_marks, a.title AS assignment_title
        FROM grade_drafts gd
        JOIN questions q ON q.id = gd.question_id
        JOIN submissions s ON s.id = gd.submission_id
        JOIN assignments a ON a.id = s.assignment_id
        WHERE gd.submission_id = ?
        ORDER BY q.order_index
        """,
        (submission_id,),
    )


def profile_report(student_id, lang="en", variant="teacher", teacher_id=None):
    t = strings(lang)
    styles = report_styles(lang)
    student = student_context(student_id, teacher_id=teacher_id)
    analytics = student_analytics_summary(student_id, teacher_id=teacher_id)
    practice = analytics_practice(student_id, limit=6)
    title = f"{t['student_profile_report']} - {student['name']}"
    story = [p(title, styles["title"])]
    identity_line = f"{t['student']}: {student['name']}"
    if variant == "teacher":
        identity_line += f" | {t['class']}: {student['class_name'] or '-'}"
    identity_line += f" | {t['generated']}: {datetime.now().strftime('%Y-%m-%d')}"
    story.append(p(identity_line, styles["small"]))
    story.append(Spacer(1, 8))

    latest = analytics["latest"]
    prediction = analytics["prediction"]
    summary_data = [
        [t["latest_score"], f"{latest['accuracy']}%" if latest else t["not_enough_data"]],
        [t["average_score"], f"{analytics['average']}%" if analytics["average"] is not None else t["not_enough_data"]],
        [
            t["current_trajectory"],
            t.get(f"trajectory_band_{prediction.get('band')}", t["not_enough_data"])
            if prediction["available"]
            else t["not_enough_data"],
        ],
        [t["trend"], t.get(f"trend_{prediction['trend']}", prediction["trend"])],
    ]
    story.append(table(summary_data, widths=[5 * cm, 10 * cm], header=False, lang=lang))

    story.append(p(t["score_history"], styles["h2"]))
    score_rows = [[t["assignment"], t["score"], t["date"]]]
    for item in analytics["score_history"][-6:]:
        score_rows.append([item["title"], f"{item['earned']}/{item['possible']} ({item['accuracy']}%)", item["date"] or "-"])
    story.append(table(score_rows, widths=[9 * cm, 4 * cm, 3 * cm], lang=lang))

    story.append(p(t["topic_mastery"], styles["h2"]))
    topic_rows = [[t["topic"], t["earned"], t["possible"], t["accuracy"]]]
    for item in sorted(analytics["topic_difficulty"], key=lambda x: x["accuracy"])[:8]:
        topic_rows.append([f"{topic_label(lang, item['topic'])} / {t['difficulty_' + item['difficulty']]}", item["earned"], item["possible"], f"{item['accuracy']}%"])
    story.append(table(topic_rows, widths=[7 * cm, 2.5 * cm, 2.5 * cm, 3 * cm], lang=lang))

    story.append(p(t["review_questions"], styles["h2"]))
    review_rows = [[t["questions"], t["topic"], t["score"]]]
    for item in analytics["review_questions"][:8]:
        review_rows.append([f"{item['assignment_title']} - {item['label']}", topic_label(lang, item["topic"]), f"{item['earned']}/{item['possible']}"])
    story.append(table(review_rows, widths=[9 * cm, 4 * cm, 3 * cm], lang=lang))

    story.append(p(t["suggested_practice"], styles["h2"]))
    for item in practice:
        story.append(p(f"{item['label']} ({topic_label(lang, item['topic'])}): {practice_question_text(item['text'])}", styles["body"]))

    if variant == "teacher":
        story.append(p(t["teacher_diagnostics"], styles["h2"]))
        type_rows = [[t["type"], t["accuracy"], t["questions"]]]
        for item in analytics["type_breakdown"][:8]:
            type_rows.append([question_type_label(lang, item["key"]), f"{item['accuracy']}%", item["question_count"]])
        story.append(table(type_rows, widths=[7 * cm, 4 * cm, 4 * cm], lang=lang))

    return build_pdf(story, title)


def assessment_report(submission_id, lang="en", variant="teacher"):
    t = strings(lang)
    styles = report_styles(lang)
    sub = submission_context(submission_id)
    rows = assessment_rows(submission_id)
    earned = sum(row["final_mark"] or 0 for row in rows)
    possible = sum(row["max_marks"] or 0 for row in rows)
    practice = analytics_practice(sub["student_id"], limit=5)
    title = f"{t['assessment_report']} - {sub['student_name']}"

    story = [p(title, styles["title"])]
    story.append(p(f"{t['student']}: {sub['student_name']} | {t['class']}: {sub['class_name']} | {t['assignment']}: {sub['assignment_title']}", styles["small"]))
    story.append(Spacer(1, 8))
    story.append(table(
        [[t["score"], f"{earned}/{possible} ({pct(earned, possible)}%)"], [t["date"], sub["due_date"] or sub["uploaded_at"][:10]]],
        widths=[4 * cm, 11 * cm],
        header=False,
        lang=lang,
    ))

    strengths = []
    needs = []
    for row in rows:
        score_pct = pct(row["final_mark"] or 0, row["max_marks"] or 0)
        label = f"{row['label']} {topic_label(lang, row['topic'])}"
        if score_pct >= 80:
            strengths.append(label)
        elif score_pct < 60:
            needs.append(label)

    story.append(p(t["what_went_well"], styles["h2"]))
    story.append(p(", ".join(strengths[:6]) if strengths else t["not_enough_data"], styles["body"]))
    story.append(p(t["what_needs_work"], styles["h2"]))
    story.append(p(", ".join(needs[:8]) if needs else t["no_review_questions"], styles["body"]))

    story.append(p(t["question_breakdown"], styles["h2"]))
    headers = [t["questions"], t["topic"], t["score"]]
    if variant == "teacher":
        headers += [t["difficulty"], t["type"]]
    data = [headers]
    for row in rows:
        line = [row["label"], topic_label(lang, row["topic"]), f"{row['final_mark'] or 0}/{row['max_marks']}"]
        if variant == "teacher":
            line += [
                t["difficulty_" + difficulty_label(row["max_marks"], sub["assignment_title"])],
                question_type_label(lang, question_type(row["question_text"], row["mark_scheme_text"], row["topic"])),
            ]
        data.append(line)
    widths = [3 * cm, 4 * cm, 3 * cm, 3 * cm, 4 * cm] if variant == "teacher" else [6 * cm, 5 * cm, 4 * cm]
    story.append(table(data, widths=widths, lang=lang))

    story.append(p(t["suggested_practice"], styles["h2"]))
    for item in practice:
        story.append(p(f"{item['label']} ({topic_label(lang, item['topic'])}): {practice_question_text(item['text'])}", styles["body"]))

    if variant == "teacher":
        story.append(p(t["teacher_diagnostics"], styles["h2"]))
        for row in rows:
            diagnostics = []
            if row["needs_exception_review"]:
                diagnostics.append(f"{t['exception_review']}: {row['risk_flags'] or '-'}")
            if row["auto_finalize_reason"]:
                diagnostics.append(f"{t['auto_finalize_reason']}: {row['auto_finalize_reason']}")
            if row["teacher_override_mark"] is not None:
                diagnostics.append(f"{t['teacher_comment']}: override to {row['teacher_override_mark']}")
            if row["teacher_comment"]:
                diagnostics.append(row["teacher_comment"])
            if diagnostics:
                story.append(p(f"{row['label']}: {' | '.join(diagnostics)}", styles["small"]))

    return build_pdf(story, title)


def self_service_assessment_report(
    student_id: int,
    paper_id: int,
    version_id: int | None = None,
    lang: str = "en",
):
    styles = report_styles(lang)
    paper = query_one(
        """
        SELECT sp.*, u.name AS student_name
        FROM student_papers sp
        JOIN users u ON u.id = sp.student_id
        WHERE sp.id = ? AND sp.student_id = ?
        """,
        (paper_id, student_id),
    )
    if not paper:
        return None
    if version_id:
        version = query_one(
            """
            SELECT * FROM paper_analysis_versions
            WHERE id = ? AND paper_id = ?
            """,
            (version_id, paper_id),
        )
    else:
        version = query_one(
            """
            SELECT * FROM paper_analysis_versions
            WHERE paper_id = ? ORDER BY version_number DESC LIMIT 1
            """,
            (paper_id,),
        )
    if not version:
        return None
    rows = query_all(
        """
        SELECT aqr.*,
               (SELECT corrected_mark FROM analysis_human_corrections ahc
                WHERE ahc.analysis_question_result_id = aqr.id
                ORDER BY ahc.id DESC LIMIT 1) AS human_mark
        FROM analysis_question_results aqr
        WHERE aqr.analysis_version_id = ?
        ORDER BY aqr.id
        """,
        (version["id"],),
    )
    title = f"Paper analysis - {paper['title']}"
    story = [p(title, styles["title"])]
    story.append(
        p(
            (
                f"Student: {paper['student_name']} | Analysis v{version['version_number']} | "
                f"{paper['syllabus_code']} {paper['paper_number'] or 'custom paper'} | "
                f"Generated: {datetime.now().strftime('%Y-%m-%d')}"
            ),
            styles["small"],
        )
    )
    story.append(Spacer(1, 8))
    summary = [
        ["Confirmed minimum", version["confirmed_min_score"]],
        ["Provisional score", version["provisional_score"]],
        ["Possible maximum", version["possible_max_score"]],
        ["Paper maximum", paper["maximum_marks"]],
    ]
    story.append(table(summary, widths=[7 * cm, 8 * cm], header=False, lang=lang))

    strengths = []
    needs = []
    for row in rows:
        mark = row["human_mark"] if row["human_mark"] is not None else row["ai_mark"]
        accuracy = pct(float(mark or 0), float(row["maximum_marks"] or 0))
        label = f"{row['question_label']} - {row['skill'] or row['topic']}"
        if accuracy >= 80:
            strengths.append(label)
        elif accuracy < 60:
            needs.append(label)
    story.append(p("What went well", styles["h2"]))
    story.append(p(", ".join(strengths[:8]) or "More evidence is needed.", styles["body"]))
    story.append(p("What to work on", styles["h2"]))
    story.append(p(", ".join(needs[:8]) or "No clear priority from this paper.", styles["body"]))

    story.append(p("Question-by-question analysis", styles["h2"]))
    data = [["Question", "Topic / skill", "Mark", "Confidence", "Concise explanation"]]
    for row in rows:
        mark = row["human_mark"] if row["human_mark"] is not None else row["ai_mark"]
        explanation = row["ai_rationale"]
        if row["error_mechanism"]:
            explanation = f"{explanation} Lost marks: {row['error_mechanism']}"
        data.append(
            [
                row["question_label"],
                f"{row['topic']} / {row['skill']}",
                f"{mark}/{row['maximum_marks']}",
                f"{round(float(row['ai_confidence'] or 0) * 100)}%",
                explanation[:420],
            ]
        )
    story.append(
        table(
            data,
            widths=[2 * cm, 4.1 * cm, 2 * cm, 2.2 * cm, 6.1 * cm],
            lang=lang,
        )
    )
    story.append(p("Interpretation", styles["h2"]))
    story.append(
        p(
            "Scores with uncertainty are ranges, not hidden precision. Reanalyse with a clearer scan or corrected mapping when evidence is weak.",
            styles["body"],
        )
    )
    return build_pdf(story, title)


def research_experiment_report(experiment_id: int):
    styles = report_styles("en")
    experiment = query_one(
        "SELECT * FROM research_experiments WHERE id = ?",
        (experiment_id,),
    )
    if not experiment:
        return None
    runs = query_all(
        """
        SELECT * FROM research_experiment_runs
        WHERE experiment_id = ? ORDER BY run_number
        """,
        (experiment_id,),
    )
    title = f"Research experiment - {experiment['title']}"
    story = [p(title, styles["title"])]
    story.append(
        p(
            f"Status: {experiment['status']} | Created: {experiment['created_at'][:10]} | Updated: {experiment['updated_at'][:10]}",
            styles["small"],
        )
    )
    story.append(p("Research definition", styles["h2"]))
    story.append(
        table(
            [
                ["Research question", experiment["research_question"]],
                ["Hypothesis", experiment["hypothesis"]],
                ["Description", experiment["description"]],
            ],
            widths=[4 * cm, 11 * cm],
            header=False,
        )
    )
    story.append(p("Configuration", styles["h2"]))
    configuration = [
        ["OCR", experiment["ocr_model"], experiment["ocr_prompt_version"]],
        ["Grading", experiment["grading_model"], experiment["grading_prompt_version"]],
        ["Diagnosis", experiment["diagnosis_model"], "-"],
        ["Threshold", experiment["confidence_threshold"], "-"],
        ["Image resolution", f"{experiment['image_resolution']} DPI", "-"],
        [
            "Deterministic checks",
            "enabled" if experiment["deterministic_checks"] else "disabled",
            "-",
        ],
    ]
    story.append(table([["Variable", "Value", "Prompt"]] + configuration, widths=[4 * cm, 6 * cm, 6 * cm]))
    story.append(p("Dataset selection", styles["h2"]))
    story.append(p(experiment["dataset_selection"], styles["small"]))
    story.append(p("Experiment runs and metrics", styles["h2"]))
    run_rows = [["Run", "Status", "Baseline", "Sample size", "Metrics"]]
    for run in runs:
        metrics = json.loads(run["metrics"] or "{}")
        metric_text = "; ".join(f"{key}={value}" for key, value in metrics.items())
        run_rows.append(
            [
                run["run_number"],
                run["status"],
                "yes" if run["baseline"] else "variant",
                f"n={run['sample_size']}",
                metric_text or run["result_summary"],
            ]
        )
    story.append(
        table(
            run_rows,
            widths=[1.4 * cm, 2.2 * cm, 2.2 * cm, 2.3 * cm, 8.3 * cm],
        )
    )
    story.append(p("Limitations", styles["h2"]))
    story.append(
        p(
            "Metrics are meaningful only with the displayed sample size and representative human labels. This report does not imply statistical significance where none was established.",
            styles["body"],
        )
    )
    story.append(p("Research notes", styles["h2"]))
    story.append(p(experiment["notes"] or "No additional notes.", styles["body"]))
    return build_pdf(story, title)
