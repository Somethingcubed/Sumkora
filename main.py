import os
import json
import uuid
from datetime import datetime
from typing import Optional
from urllib.parse import urlsplit

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

import config
from analytics import (
    analytics_practice,
    grading_audit_summary,
    student_analytics_summary,
    teacher_analytics_summary,
)
from auth import create_session_token, get_current_user, require_role
from db import (
    compute_topic_mastery,
    execute,
    init_db,
    query_all,
    query_one,
    recommend_practice,
    seed_if_empty,
    update_assignment_total_marks,
    verify_password,
    weak_topics,
)
from grading import ensure_grade_rows, finalize_submission, reset_grade_rows, run_grading_job
from i18n import (
    get_lang,
    other_lang,
    role_label,
    status_label,
    strings,
    question_type_label,
    topic_label,
    type_label,
)
from ocr import ocr_pages_for_submission, reset_ocr_cache
from pdf_utils import is_valid_pdf, pdf_to_page_images, save_upload
from reports import assessment_report, profile_report, safe_filename
from topics import TOPICS

init_db()
seed_if_empty()
for warning in getattr(config, "CONFIG_WARNINGS", []):
    print(f"CONFIG WARNING: {warning}")

app = FastAPI(title="IGCSE 0580 Math Tracker")
templates = Jinja2Templates(directory="templates")
os.makedirs("static", exist_ok=True)
app.mount("/static", StaticFiles(directory="static"), name="static")
os.makedirs(config.UPLOAD_DIR, exist_ok=True)


def redirect_login():
    return RedirectResponse("/login", status_code=303)


def render(request: Request, name: str, context: dict, status_code: int = 200):
    lang = get_lang(request)
    context = {
        **context,
        "lang": lang,
        "t": strings(lang),
        "other_lang": other_lang(lang),
        "status_label": lambda s: status_label(lang, s),
        "type_label": lambda ty: type_label(lang, ty),
        "role_label": lambda r: role_label(lang, r),
        "topic_label": lambda top: topic_label(lang, top),
        "question_type_label": lambda key: question_type_label(lang, key),
    }
    return templates.TemplateResponse(request, name, context, status_code=status_code)


def local_redirect_target(request: Request, fallback: str = "/login") -> str:
    referer = request.headers.get("referer") or fallback
    parsed = urlsplit(referer)
    if parsed.scheme or parsed.netloc:
        host = request.headers.get("host", "")
        if parsed.netloc != host:
            return fallback
        return parsed.path or fallback
    return referer if referer.startswith("/") else fallback


def teacher_assignment(request: Request, assignment_id: int):
    user = require_role(request, "teacher")
    if not user:
        return None, None
    assignment = query_one(
        """
        SELECT a.*, c.teacher_id
        FROM assignments a
        JOIN classes c ON c.id = a.class_id
        WHERE a.id = ? AND c.teacher_id = ?
        """,
        (assignment_id, user["id"]),
    )
    return user, assignment


def teacher_submission(request: Request, submission_id: int):
    user = require_role(request, "teacher")
    if not user:
        return None, None
    submission = query_one(
        """
        SELECT s.*, a.class_id, c.teacher_id
        FROM submissions s
        JOIN assignments a ON a.id = s.assignment_id
        JOIN classes c ON c.id = a.class_id
        WHERE s.id = ? AND c.teacher_id = ?
        """,
        (submission_id, user["id"]),
    )
    return user, submission


def teacher_student(request: Request, student_id: int):
    user = require_role(request, "teacher")
    if not user:
        return None, None
    student = query_one(
        """
        SELECT u.*
        FROM users u
        JOIN class_enrollments ce ON ce.student_id = u.id
        JOIN classes c ON c.id = ce.class_id
        WHERE u.id = ? AND c.teacher_id = ? AND u.role = 'student'
        """,
        (student_id, user["id"]),
    )
    return user, student


def pdf_response(content: bytes, filename: str):
    return StreamingResponse(
        iter([content]),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/lang/{lang_code}")
def switch_language(lang_code: str, request: Request):
    target = local_redirect_target(request)
    response = RedirectResponse(target, status_code=303)
    code = lang_code if lang_code in ("en", "zh") else "en"
    response.set_cookie("lang", code, max_age=86400 * 365)
    return response


@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    user = get_current_user(request)
    if not user:
        return redirect_login()
    if user["role"] == "teacher":
        return RedirectResponse("/teacher", status_code=303)
    return RedirectResponse("/student", status_code=303)


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    return render(request, "login.html", {"error": None, "user": None})


@app.post("/login")
def login_submit(request: Request, email: str = Form(...), password: str = Form(...)):
    user = query_one("SELECT * FROM users WHERE email = ?", (email.strip(),))
    if not user or not verify_password(password, user["password_hash"]):
        return render(
            request,
            "login.html",
            {"error": strings(get_lang(request))["invalid_login"], "user": None},
            status_code=400,
        )
    token = create_session_token(user["id"])
    response = RedirectResponse("/", status_code=303)
    response.set_cookie("session", token, httponly=True, max_age=86400 * 7)
    return response


@app.get("/logout")
def logout():
    response = RedirectResponse("/login", status_code=303)
    response.delete_cookie("session")
    return response


@app.get("/teacher", response_class=HTMLResponse)
def teacher_dashboard(request: Request):
    user = require_role(request, "teacher")
    if not user:
        return redirect_login()

    classes = query_all(
        "SELECT c.*, (SELECT COUNT(*) FROM class_enrollments ce WHERE ce.class_id = c.id) AS student_count "
        "FROM classes c WHERE c.teacher_id = ?",
        (user["id"],),
    )
    assignments = query_all(
        """
        SELECT a.*, c.name AS class_name,
               (SELECT COUNT(*) FROM submissions s WHERE s.assignment_id = a.id) AS submission_count
        FROM assignments a
        JOIN classes c ON c.id = a.class_id
        WHERE c.teacher_id = ?
        ORDER BY a.created_at DESC
        """,
        (user["id"],),
    )
    pending_review = query_all(
        """
        SELECT s.*, a.title AS assignment_title, u.name AS student_name,
               (SELECT COUNT(*)
                FROM grade_drafts gd
                WHERE gd.submission_id = s.id AND gd.needs_exception_review = 1) AS exception_count
        FROM submissions s
        JOIN assignments a ON a.id = s.assignment_id
        JOIN classes c ON c.id = a.class_id
        JOIN users u ON u.id = s.student_id
        WHERE c.teacher_id = ?
          AND (
            s.status = 'review'
            OR EXISTS (
              SELECT 1 FROM grade_drafts gd
              WHERE gd.submission_id = s.id
                AND gd.needs_exception_review = 1
            )
          )
        ORDER BY s.uploaded_at DESC
        """,
        (user["id"],),
    )
    grading_quality = query_one(
        """
        SELECT
            COUNT(*) AS grade_rows,
            SUM(CASE WHEN gd.auto_finalized_at IS NOT NULL THEN 1 ELSE 0 END) AS auto_finalized,
            SUM(CASE WHEN gd.needs_exception_review = 1 THEN 1 ELSE 0 END) AS exceptions,
            SUM(CASE WHEN gd.teacher_override_mark IS NOT NULL THEN 1 ELSE 0 END) AS overrides,
            AVG(CASE WHEN gd.auto_finalized_at IS NOT NULL THEN gd.ai_confidence END) AS average_confidence
        FROM grade_drafts gd
        JOIN submissions s ON s.id = gd.submission_id
        JOIN assignments a ON a.id = s.assignment_id
        JOIN classes c ON c.id = a.class_id
        WHERE c.teacher_id = ?
        """,
        (user["id"],),
    )
    return render(
        request,
        "teacher/dashboard.html",
        {
            "user": user,
            "classes": classes,
            "assignments": assignments,
            "pending_review": pending_review,
            "grading_quality": grading_quality,
            "ai_mode": strings(get_lang(request))[
                "ai_mode_cxsee_qwen"
                if getattr(config, "AI_PROVIDER", "") == "cxsee_qwen" and config.CXSEE_API_KEY
                else "ai_mode_deepseek"
                if getattr(config, "AI_PROVIDER", "") == "deepseek" and config.DEEPSEEK_API_KEY
                else "ai_mode_openai"
                if config.OPENAI_API_KEY
                else "ai_mode_mock"
            ],
        },
    )


@app.get("/teacher/calibration", response_class=HTMLResponse)
def teacher_calibration(request: Request):
    user = require_role(request, "teacher")
    if not user:
        return redirect_login()
    audit = grading_audit_summary(user["id"])
    return render(
        request,
        "teacher/calibration.html",
        {"user": user, "audit": audit},
    )


@app.get("/teacher/classes", response_class=HTMLResponse)
def teacher_classes(request: Request):
    user = require_role(request, "teacher")
    if not user:
        return redirect_login()

    classes = query_all(
        """
        SELECT c.*,
               (SELECT COUNT(*) FROM class_enrollments ce WHERE ce.class_id = c.id) AS student_count
        FROM classes c WHERE c.teacher_id = ?
        """,
        (user["id"],),
    )
    students = query_all("SELECT * FROM users WHERE role = 'student' ORDER BY name")
    return render(
        request,
        "teacher/classes.html",
        {"user": user, "classes": classes, "students": students},
    )


@app.get("/teacher/classes/{class_id}", response_class=HTMLResponse)
def teacher_class_detail(request: Request, class_id: int):
    user = require_role(request, "teacher")
    if not user:
        return redirect_login()
    class_row = query_one(
        "SELECT * FROM classes WHERE id = ? AND teacher_id = ?",
        (class_id, user["id"]),
    )
    if not class_row:
        return RedirectResponse("/teacher/classes", status_code=303)
    students = query_all(
        """
        SELECT u.*,
               (SELECT COUNT(*)
                FROM submissions s
                JOIN assignments a ON a.id = s.assignment_id
                WHERE s.student_id = u.id AND a.class_id = ? AND s.status = 'final') AS finalized_count
        FROM users u
        JOIN class_enrollments ce ON ce.student_id = u.id
        WHERE ce.class_id = ?
        ORDER BY u.name
        """,
        (class_id, class_id),
    )
    submissions = query_all(
        """
        SELECT s.*, a.title AS assignment_title, u.name AS student_name
        FROM submissions s
        JOIN assignments a ON a.id = s.assignment_id
        JOIN users u ON u.id = s.student_id
        WHERE a.class_id = ? AND s.status = 'final'
        ORDER BY a.due_date DESC, s.uploaded_at DESC
        """,
        (class_id,),
    )
    return render(
        request,
        "teacher/class_detail.html",
        {"user": user, "class_row": class_row, "students": students, "submissions": submissions},
    )


@app.post("/teacher/classes")
def create_class(request: Request, name: str = Form(...)):
    user = require_role(request, "teacher")
    if not user:
        return redirect_login()
    execute(
        "INSERT INTO classes (name, teacher_id) VALUES (?, ?)",
        (name.strip(), user["id"]),
    )
    return RedirectResponse("/teacher/classes", status_code=303)


@app.post("/teacher/classes/{class_id}/enroll")
def enroll_student(request: Request, class_id: int, student_id: int = Form(...)):
    user = require_role(request, "teacher")
    if not user:
        return redirect_login()
    class_row = query_one(
        "SELECT id FROM classes WHERE id = ? AND teacher_id = ?",
        (class_id, user["id"]),
    )
    student = query_one(
        "SELECT id FROM users WHERE id = ? AND role = 'student'",
        (student_id,),
    )
    if not class_row or not student:
        return RedirectResponse("/teacher/classes", status_code=303)
    existing = query_one(
        "SELECT 1 FROM class_enrollments WHERE class_id = ? AND student_id = ?",
        (class_id, student_id),
    )
    if not existing:
        execute(
            "INSERT INTO class_enrollments (class_id, student_id) VALUES (?, ?)",
            (class_id, student_id),
        )
    return RedirectResponse("/teacher/classes", status_code=303)


@app.get("/teacher/assignments/new", response_class=HTMLResponse)
def new_assignment(request: Request):
    user = require_role(request, "teacher")
    if not user:
        return redirect_login()
    classes = query_all(
        "SELECT * FROM classes WHERE teacher_id = ?",
        (user["id"],),
    )
    return render(
        request,
        "teacher/assignment_form.html",
        {
            "user": user,
            "classes": classes,
            "topics": TOPICS,
            "assignment": None,
            "questions": [],
        },
    )


@app.post("/teacher/assignments")
async def create_assignment(
    request: Request,
    title: str = Form(...),
    class_id: int = Form(...),
    type: str = Form(...),
    due_date: str = Form(""),
    question_paper: UploadFile = File(None),
    mark_scheme: UploadFile = File(None),
):
    user = require_role(request, "teacher")
    if not user:
        return redirect_login()

    class_row = query_one(
        "SELECT id FROM classes WHERE id = ? AND teacher_id = ?",
        (class_id, user["id"]),
    )
    if not class_row:
        return RedirectResponse("/teacher/assignments/new", status_code=303)

    qp_path = None
    ms_path = None
    if question_paper and question_paper.filename:
        content = await question_paper.read()
        if is_valid_pdf(content):
            qp_path = save_upload(f"qp_{uuid.uuid4().hex}_{question_paper.filename}", content)
    if mark_scheme and mark_scheme.filename:
        content = await mark_scheme.read()
        if is_valid_pdf(content):
            ms_path = save_upload(f"ms_{uuid.uuid4().hex}_{mark_scheme.filename}", content)

    assignment_id = execute(
        """
        INSERT INTO assignments
        (class_id, title, type, due_date, status, question_paper_path, mark_scheme_path, created_at)
        VALUES (?, ?, ?, ?, 'draft', ?, ?, ?)
        """,
        (
            class_id,
            title.strip(),
            type,
            due_date or None,
            qp_path,
            ms_path,
            datetime.now().isoformat(),
        ),
    )
    return RedirectResponse(f"/teacher/assignments/{assignment_id}", status_code=303)


@app.get("/teacher/assignments/{assignment_id}", response_class=HTMLResponse)
def assignment_detail(request: Request, assignment_id: int):
    user = require_role(request, "teacher")
    if not user:
        return redirect_login()

    assignment = query_one(
        """
        SELECT a.*, c.name AS class_name
        FROM assignments a
        JOIN classes c ON c.id = a.class_id
        WHERE a.id = ? AND c.teacher_id = ?
        """,
        (assignment_id, user["id"]),
    )
    if not assignment:
        return RedirectResponse("/teacher", status_code=303)

    questions = query_all(
        "SELECT * FROM questions WHERE assignment_id = ? ORDER BY order_index",
        (assignment_id,),
    )
    submissions = query_all(
        """
        SELECT s.*, u.name AS student_name,
               (SELECT COUNT(*)
                FROM grade_drafts gd
                WHERE gd.submission_id = s.id AND gd.needs_exception_review = 1) AS exception_count,
               (SELECT COUNT(*)
                FROM grade_drafts gd
                WHERE gd.submission_id = s.id AND gd.teacher_override_mark IS NOT NULL) AS override_count,
               (SELECT AVG(CASE WHEN gd.auto_finalized_at IS NOT NULL THEN gd.ai_confidence END)
                FROM grade_drafts gd
                WHERE gd.submission_id = s.id AND gd.ai_confidence IS NOT NULL) AS average_confidence
        FROM submissions s
        JOIN users u ON u.id = s.student_id
        WHERE s.assignment_id = ?
        ORDER BY s.uploaded_at DESC
        """,
        (assignment_id,),
    )
    students = query_all(
        """
        SELECT u.*
        FROM users u
        JOIN class_enrollments ce ON ce.student_id = u.id
        WHERE ce.class_id = ?
        ORDER BY u.name
        """,
        (assignment["class_id"],),
    )
    return render(
        request,
        "teacher/assignment_detail.html",
        {
            "user": user,
            "assignment": assignment,
            "questions": questions,
            "submissions": submissions,
            "students": students,
            "topics": TOPICS,
        },
    )


@app.post("/teacher/assignments/{assignment_id}/questions")
def add_question(
    request: Request,
    assignment_id: int,
    label: str = Form(...),
    topic: str = Form(...),
    question_text: str = Form(""),
    max_marks: int = Form(...),
    mark_scheme_text: str = Form(""),
    page_number: int = Form(1),
):
    user, assignment = teacher_assignment(request, assignment_id)
    if not user:
        return redirect_login()
    if not assignment:
        return RedirectResponse("/teacher", status_code=303)
    order = query_one(
        "SELECT COALESCE(MAX(order_index), -1) + 1 AS next_order FROM questions WHERE assignment_id = ?",
        (assignment_id,),
    )["next_order"]
    execute(
        """
        INSERT INTO questions
        (assignment_id, label, topic, question_text, max_marks, mark_scheme_text, page_number, order_index)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            assignment_id,
            label.strip(),
            topic,
            question_text.strip(),
            max_marks,
            mark_scheme_text.strip(),
            page_number,
            order,
        ),
    )
    update_assignment_total_marks(assignment_id)
    return RedirectResponse(f"/teacher/assignments/{assignment_id}", status_code=303)


@app.post("/teacher/assignments/{assignment_id}/publish")
def publish_assignment(request: Request, assignment_id: int):
    user, assignment = teacher_assignment(request, assignment_id)
    if not user:
        return redirect_login()
    if not assignment:
        return RedirectResponse("/teacher", status_code=303)
    execute(
        "UPDATE assignments SET status = 'published' WHERE id = ?",
        (assignment_id,),
    )
    return RedirectResponse(f"/teacher/assignments/{assignment_id}", status_code=303)


@app.post("/teacher/assignments/{assignment_id}/upload")
async def teacher_bulk_upload(
    request: Request,
    assignment_id: int,
    student_id: Optional[int] = Form(default=None),
    files: list[UploadFile] = File(...),
):
    user, assignment = teacher_assignment(request, assignment_id)
    if not user:
        return redirect_login()
    if not assignment:
        return RedirectResponse("/teacher", status_code=303)
    for f in files:
        if not f.filename:
            continue
        content = await f.read()
        if not is_valid_pdf(content):
            continue
        path = save_upload(f"sub_{uuid.uuid4().hex}_{f.filename}", content)
        sid = student_id
        if not sid:
            name_part = f.filename.rsplit(".", 1)[0].lower()
            student = query_one(
                "SELECT u.id FROM users u WHERE lower(u.name) LIKE ? OR lower(u.email) LIKE ?",
                (f"%{name_part}%", f"%{name_part}%"),
            )
            sid = student["id"] if student else None
        if not sid:
            continue
        enrolled = query_one(
            """
            SELECT 1 FROM class_enrollments
            WHERE class_id = ? AND student_id = ?
            """,
            (assignment["class_id"], sid),
        )
        if not enrolled:
            continue
        existing = query_one(
            "SELECT id FROM submissions WHERE assignment_id = ? AND student_id = ?",
            (assignment_id, sid),
        )
        if existing:
            execute(
                "UPDATE submissions SET file_path = ?, status = 'pending', uploaded_at = ? WHERE id = ?",
                (path, datetime.now().isoformat(), existing["id"]),
            )
            submission_id = existing["id"]
            reset_grade_rows(submission_id)
            reset_ocr_cache(submission_id)
        else:
            submission_id = execute(
                """
                INSERT INTO submissions (assignment_id, student_id, file_path, status, uploaded_at)
                VALUES (?, ?, ?, 'pending', ?)
                """,
                (assignment_id, sid, path, datetime.now().isoformat()),
            )
        ensure_grade_rows(submission_id, assignment_id)
    return RedirectResponse(f"/teacher/assignments/{assignment_id}", status_code=303)


@app.post("/teacher/submissions/{submission_id}/grade-manual")
def manual_grade(
    request: Request,
    submission_id: int,
    question_id: int = Form(...),
    final_mark: float = Form(...),
    teacher_comment: str = Form(""),
):
    user, submission = teacher_submission(request, submission_id)
    if not user:
        return redirect_login()
    if not submission:
        return RedirectResponse("/teacher", status_code=303)
    question = query_one(
        "SELECT id, max_marks FROM questions WHERE id = ? AND assignment_id = ?",
        (question_id, submission["assignment_id"]),
    )
    if not question:
        return RedirectResponse(f"/teacher/submissions/{submission_id}/review", status_code=303)
    final_mark = max(0, min(final_mark, float(question["max_marks"])))
    existing = query_one(
        "SELECT id FROM grade_drafts WHERE submission_id = ? AND question_id = ?",
        (submission_id, question_id),
    )
    if existing:
        execute(
            """
            UPDATE grade_drafts
            SET final_mark = ?, teacher_comment = ?,
                teacher_override_mark = ?, teacher_override_comment = ?,
                teacher_override_at = ?, teacher_override_by = ?,
                needs_exception_review = 0
            WHERE submission_id = ? AND question_id = ?
            """,
            (
                final_mark,
                teacher_comment,
                final_mark,
                teacher_comment,
                datetime.now().isoformat(),
                user["id"],
                submission_id,
                question_id,
            ),
        )
    else:
        execute(
            """
            INSERT INTO grade_drafts
            (submission_id, question_id, final_mark, teacher_comment,
             teacher_override_mark, teacher_override_comment,
             teacher_override_at, teacher_override_by)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                submission_id,
                question_id,
                final_mark,
                teacher_comment,
                final_mark,
                teacher_comment,
                datetime.now().isoformat(),
                user["id"],
            ),
        )
    if submission and submission["status"] == "pending":
        execute(
            "UPDATE submissions SET status = 'review' WHERE id = ?",
            (submission_id,),
        )
    return RedirectResponse(f"/teacher/submissions/{submission_id}/review", status_code=303)


@app.post("/teacher/submissions/{submission_id}/ai-grade")
def ai_grade_submission(request: Request, submission_id: int):
    user, submission = teacher_submission(request, submission_id)
    if not user:
        return redirect_login()
    if not submission:
        return RedirectResponse("/teacher", status_code=303)
    run_grading_job(submission_id)
    return RedirectResponse(f"/teacher/submissions/{submission_id}/review", status_code=303)


@app.get("/teacher/submissions/{submission_id}/file")
def teacher_submission_file(request: Request, submission_id: int):
    user, submission = teacher_submission(request, submission_id)
    if not user:
        return redirect_login()
    if not submission or not os.path.exists(submission["file_path"]):
        return RedirectResponse("/teacher", status_code=303)
    return FileResponse(
        submission["file_path"],
        media_type="application/pdf",
        filename=os.path.basename(submission["file_path"]),
    )


@app.get("/teacher/students/{student_id}/report")
def teacher_student_report(request: Request, student_id: int, variant: str = "teacher"):
    user, student = teacher_student(request, student_id)
    if not user:
        return redirect_login()
    if not student:
        return RedirectResponse("/teacher/classes", status_code=303)
    variant = variant if variant in ("teacher", "student") else "teacher"
    content = profile_report(
        student_id,
        lang=get_lang(request),
        variant=variant,
        teacher_id=user["id"],
    )
    return pdf_response(
        content,
        f"{safe_filename(student['name'])}-profile-{variant}.pdf",
    )


@app.get("/teacher/submissions/{submission_id}/report")
def teacher_submission_report(request: Request, submission_id: int, variant: str = "teacher"):
    user, submission = teacher_submission(request, submission_id)
    if not user:
        return redirect_login()
    if not submission:
        return RedirectResponse("/teacher", status_code=303)
    if submission["status"] != "final":
        return RedirectResponse(f"/teacher/submissions/{submission_id}/review", status_code=303)
    variant = variant if variant in ("teacher", "student") else "teacher"
    details = query_one(
        """
        SELECT u.name AS student_name, a.title AS assignment_title
        FROM submissions s
        JOIN users u ON u.id = s.student_id
        JOIN assignments a ON a.id = s.assignment_id
        WHERE s.id = ?
        """,
        (submission_id,),
    )
    content = assessment_report(submission_id, lang=get_lang(request), variant=variant)
    return pdf_response(
        content,
        f"{safe_filename(details['student_name'])}-{safe_filename(details['assignment_title'])}-{variant}.pdf",
    )


@app.get("/teacher/submissions/{submission_id}/review", response_class=HTMLResponse)
def review_submission(request: Request, submission_id: int):
    user = require_role(request, "teacher")
    if not user:
        return redirect_login()

    submission = query_one(
        """
        SELECT s.*, a.title AS assignment_title, a.id AS assignment_id,
               u.name AS student_name, c.teacher_id
        FROM submissions s
        JOIN assignments a ON a.id = s.assignment_id
        JOIN classes c ON c.id = a.class_id
        JOIN users u ON u.id = s.student_id
        WHERE s.id = ?
        """,
        (submission_id,),
    )
    if not submission or submission["teacher_id"] != user["id"]:
        return RedirectResponse("/teacher", status_code=303)

    grades = query_all(
        """
        SELECT gd.*, q.label, q.topic, q.question_text, q.max_marks, q.mark_scheme_text, q.page_number
        FROM grade_drafts gd
        JOIN questions q ON q.id = gd.question_id
        WHERE gd.submission_id = ?
        ORDER BY q.order_index
        """,
        (submission_id,),
    )
    ensure_grade_rows(submission_id, submission["assignment_id"])
    if not grades:
        grades = query_all(
            """
            SELECT gd.*, q.label, q.topic, q.question_text, q.max_marks, q.mark_scheme_text, q.page_number
            FROM grade_drafts gd
            JOIN questions q ON q.id = gd.question_id
            WHERE gd.submission_id = ?
            ORDER BY q.order_index
            """,
            (submission_id,),
        )
    display_grades = []
    for grade in grades:
        item = dict(grade)
        try:
            flags = json.loads(item.get("risk_flags") or "[]")
        except json.JSONDecodeError:
            flags = [item.get("risk_flags") or ""]
        item["risk_flags_text"] = ", ".join(flag for flag in flags if flag)
        display_grades.append(item)

    total_earned = sum(g["final_mark"] or g["ai_mark"] or 0 for g in display_grades)
    total_possible = sum(g["max_marks"] for g in display_grades)
    exception_count = sum(1 for g in display_grades if g["needs_exception_review"])
    ocr_pages = ocr_pages_for_submission(submission_id, submission["file_path"])
    ocr_by_page = {page["page_number"]: page for page in ocr_pages}
    page_images = pdf_to_page_images(submission["file_path"], dpi=120)

    return render(
        request,
        "teacher/review.html",
        {
            "user": user,
            "submission": submission,
            "grades": display_grades,
            "ocr_pages": ocr_pages,
            "ocr_by_page": ocr_by_page,
            "page_images": page_images,
            "total_earned": total_earned,
            "total_possible": total_possible,
            "exception_count": exception_count,
        },
    )


@app.post("/teacher/submissions/{submission_id}/finalize")
def finalize(request: Request, submission_id: int):
    user, submission = teacher_submission(request, submission_id)
    if not user:
        return redirect_login()
    if not submission:
        return RedirectResponse("/teacher", status_code=303)
    grades = query_all(
        "SELECT * FROM grade_drafts WHERE submission_id = ?",
        (submission_id,),
    )
    for g in grades:
        if g["final_mark"] is None and g["ai_mark"] is not None:
            execute(
                "UPDATE grade_drafts SET final_mark = ? WHERE id = ?",
                (g["ai_mark"], g["id"]),
            )
    finalize_submission(submission_id)
    return RedirectResponse(f"/teacher/submissions/{submission_id}/review", status_code=303)


@app.get("/teacher/analytics", response_class=HTMLResponse)
def teacher_analytics(request: Request):
    user = require_role(request, "teacher")
    if not user:
        return redirect_login()

    class_stats = query_all(
        """
        SELECT c.id, c.name,
               COUNT(DISTINCT ce.student_id) AS students,
               COUNT(DISTINCT s.id) AS submissions
        FROM classes c
        LEFT JOIN class_enrollments ce ON ce.class_id = c.id
        LEFT JOIN assignments a ON a.class_id = c.id
        LEFT JOIN submissions s ON s.assignment_id = a.id AND s.status = 'final'
        WHERE c.teacher_id = ?
        GROUP BY c.id
        """,
        (user["id"],),
    )

    raw_topics = query_all(
        """
        SELECT q.topic,
               SUM(COALESCE(gd.final_mark, 0)) AS earned,
               SUM(q.max_marks) AS possible
        FROM grade_drafts gd
        JOIN questions q ON q.id = gd.question_id
        JOIN submissions s ON s.id = gd.submission_id
        JOIN assignments a ON a.id = s.assignment_id
        JOIN classes c ON c.id = a.class_id
        WHERE c.teacher_id = ? AND s.status = 'final'
        GROUP BY q.topic
        ORDER BY earned * 1.0 / possible ASC
        """,
        (user["id"],),
    )
    topic_breakdown = []
    for row in raw_topics:
        possible = row["possible"] or 1
        earned = row["earned"] or 0
        topic_breakdown.append(
            {
                "topic": row["topic"],
                "earned": earned,
                "possible": row["possible"],
                "accuracy": round(100 * earned / possible, 1),
            }
        )

    analytics = teacher_analytics_summary(user["id"])

    return render(
        request,
        "teacher/analytics.html",
        {
            "user": user,
            "class_stats": class_stats,
            "topic_breakdown": topic_breakdown,
            "analytics": analytics,
        },
    )


@app.get("/teacher/exceptions", response_class=HTMLResponse)
def teacher_exceptions(request: Request):
    user = require_role(request, "teacher")
    if not user:
        return redirect_login()

    rows = query_all(
        """
        SELECT gd.*, q.label, q.topic, q.max_marks, q.question_text,
               s.id AS submission_id, s.uploaded_at, s.status AS submission_status,
               a.title AS assignment_title, u.name AS student_name, c.name AS class_name
        FROM grade_drafts gd
        JOIN questions q ON q.id = gd.question_id
        JOIN submissions s ON s.id = gd.submission_id
        JOIN assignments a ON a.id = s.assignment_id
        JOIN classes c ON c.id = a.class_id
        JOIN users u ON u.id = s.student_id
        WHERE c.teacher_id = ? AND gd.needs_exception_review = 1
        ORDER BY s.uploaded_at DESC, a.title, u.name, q.order_index
        """,
        (user["id"],),
    )
    exceptions = []
    for row in rows:
        item = dict(row)
        try:
            flags = json.loads(item.get("risk_flags") or "[]")
        except json.JSONDecodeError:
            flags = [item.get("risk_flags") or ""]
        item["risk_flags_text"] = ", ".join(flag for flag in flags if flag)
        exceptions.append(item)

    quality = query_one(
        """
        SELECT
            COUNT(*) AS grade_rows,
            SUM(CASE WHEN gd.auto_finalized_at IS NOT NULL THEN 1 ELSE 0 END) AS auto_finalized,
            SUM(CASE WHEN gd.needs_exception_review = 1 THEN 1 ELSE 0 END) AS exceptions,
            SUM(CASE WHEN gd.teacher_override_mark IS NOT NULL THEN 1 ELSE 0 END) AS overrides,
            AVG(CASE WHEN gd.auto_finalized_at IS NOT NULL THEN gd.ai_confidence END) AS average_confidence
        FROM grade_drafts gd
        JOIN submissions s ON s.id = gd.submission_id
        JOIN assignments a ON a.id = s.assignment_id
        JOIN classes c ON c.id = a.class_id
        WHERE c.teacher_id = ?
        """,
        (user["id"],),
    )
    return render(
        request,
        "teacher/exceptions.html",
        {"user": user, "exceptions": exceptions, "quality": quality},
    )


@app.get("/student", response_class=HTMLResponse)
def student_dashboard(request: Request):
    user = require_role(request, "student")
    if not user:
        return redirect_login()

    assignments = query_all(
        """
        SELECT a.*, c.name AS class_name, s.id AS submission_id, s.status AS submission_status,
               (SELECT SUM(COALESCE(gd.final_mark, 0))
                FROM grade_drafts gd WHERE gd.submission_id = s.id) AS score
        FROM assignments a
        JOIN classes c ON c.id = a.class_id
        JOIN class_enrollments ce ON ce.class_id = c.id
        LEFT JOIN submissions s ON s.assignment_id = a.id AND s.student_id = ?
        WHERE ce.student_id = ? AND a.status = 'published'
        ORDER BY a.due_date DESC
        """,
        (user["id"], user["id"]),
    )
    mastery = compute_topic_mastery(user["id"])
    analytics = student_analytics_summary(user["id"])
    recommendations = analytics_practice(user["id"], limit=5)
    weak = weak_topics(user["id"])

    return render(
        request,
        "student/dashboard.html",
        {
            "user": user,
            "assignments": assignments,
            "mastery": mastery,
            "weak_topics": weak,
            "recommendations": recommendations,
            "analytics": analytics,
        },
    )


@app.get("/student/report")
def student_profile_report(request: Request):
    user = require_role(request, "student")
    if not user:
        return redirect_login()
    content = profile_report(user["id"], lang=get_lang(request), variant="student")
    return pdf_response(content, f"{safe_filename(user['name'])}-profile.pdf")


@app.get("/student/assignments/{assignment_id}", response_class=HTMLResponse)
def student_assignment(request: Request, assignment_id: int):
    user = require_role(request, "student")
    if not user:
        return redirect_login()

    assignment = query_one(
        """
        SELECT a.*, c.name AS class_name
        FROM assignments a
        JOIN classes c ON c.id = a.class_id
        JOIN class_enrollments ce ON ce.class_id = c.id
        WHERE a.id = ? AND ce.student_id = ? AND a.status = 'published'
        """,
        (assignment_id, user["id"]),
    )
    if not assignment:
        return RedirectResponse("/student", status_code=303)

    submission = query_one(
        "SELECT * FROM submissions WHERE assignment_id = ? AND student_id = ?",
        (assignment_id, user["id"]),
    )
    questions = query_all(
        "SELECT label, topic, question_text, max_marks FROM questions WHERE assignment_id = ? ORDER BY order_index",
        (assignment_id,),
    )
    return render(
        request,
        "student/assignment.html",
        {
            "user": user,
            "assignment": assignment,
            "submission": submission,
            "questions": questions,
        },
    )


@app.post("/student/assignments/{assignment_id}/upload")
async def student_upload(request: Request, assignment_id: int, file: UploadFile = File(...)):
    user = require_role(request, "student")
    if not user:
        return redirect_login()

    enrolled = query_one(
        """
        SELECT 1 FROM class_enrollments ce
        JOIN assignments a ON a.class_id = ce.class_id
        WHERE a.id = ? AND ce.student_id = ? AND a.status = 'published'
        """,
        (assignment_id, user["id"]),
    )
    if not enrolled:
        return RedirectResponse("/student", status_code=303)

    content = await file.read()
    if not is_valid_pdf(content):
        return RedirectResponse(f"/student/assignments/{assignment_id}", status_code=303)
    path = save_upload(f"sub_{uuid.uuid4().hex}_{file.filename}", content)

    submission = query_one(
        "SELECT id FROM submissions WHERE assignment_id = ? AND student_id = ?",
        (assignment_id, user["id"]),
    )
    student_id = user["id"]

    if submission:
        execute(
            "UPDATE submissions SET file_path = ?, status = 'pending', uploaded_at = ? WHERE id = ?",
            (path, datetime.now().isoformat(), submission["id"]),
        )
        sid = submission["id"]
        reset_grade_rows(sid)
        reset_ocr_cache(sid)
    else:
        sid = execute(
            """
            INSERT INTO submissions (assignment_id, student_id, file_path, status, uploaded_at)
            VALUES (?, ?, ?, 'pending', ?)
            """,
            (assignment_id, student_id, path, datetime.now().isoformat()),
        )
    ensure_grade_rows(sid, assignment_id)
    return RedirectResponse(f"/student/assignments/{assignment_id}", status_code=303)


@app.get("/student/results/{submission_id}", response_class=HTMLResponse)
def student_results(request: Request, submission_id: int):
    user = require_role(request, "student")
    if not user:
        return redirect_login()

    submission = query_one(
        """
        SELECT s.*, a.title AS assignment_title
        FROM submissions s
        JOIN assignments a ON a.id = s.assignment_id
        WHERE s.id = ? AND s.student_id = ? AND s.status = 'final'
        """,
        (submission_id, user["id"]),
    )
    if not submission:
        return RedirectResponse("/student", status_code=303)

    grades = query_all(
        """
        SELECT gd.*, q.label, q.topic, q.question_text, q.max_marks, q.mark_scheme_text
        FROM grade_drafts gd
        JOIN questions q ON q.id = gd.question_id
        WHERE gd.submission_id = ?
        ORDER BY q.order_index
        """,
        (submission_id,),
    )
    total_earned = sum(g["final_mark"] or 0 for g in grades)
    total_possible = sum(g["max_marks"] for g in grades)
    recommendations = recommend_practice(user["id"], limit=3)

    return render(
        request,
        "student/results.html",
        {
            "user": user,
            "submission": submission,
            "grades": grades,
            "total_earned": total_earned,
            "total_possible": total_possible,
            "recommendations": recommendations,
        },
    )


@app.get("/student/results/{submission_id}/report")
def student_assessment_report(request: Request, submission_id: int):
    user = require_role(request, "student")
    if not user:
        return redirect_login()
    submission = query_one(
        """
        SELECT s.*, a.title AS assignment_title
        FROM submissions s
        JOIN assignments a ON a.id = s.assignment_id
        WHERE s.id = ? AND s.student_id = ? AND s.status = 'final'
        """,
        (submission_id, user["id"]),
    )
    if not submission:
        return RedirectResponse("/student", status_code=303)
    content = assessment_report(submission_id, lang=get_lang(request), variant="student")
    return pdf_response(
        content,
        f"{safe_filename(user['name'])}-{safe_filename(submission['assignment_title'])}.pdf",
    )
