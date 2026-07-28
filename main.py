import os
import json
import csv
import hashlib
import io
import mimetypes
import re
import sqlite3
import uuid
import zipfile
from collections import defaultdict, deque
from datetime import datetime
from time import monotonic
from typing import Optional
from urllib.parse import quote, urlsplit

from fastapi import BackgroundTasks, FastAPI, File, Form, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.exceptions import HTTPException as StarletteHTTPException

import config
from accounts import (
    count_label,
    generate_recovery_code,
    normalize_username,
    recovery_code_hash,
    recovery_code_matches,
    student_explanation,
    validate_password,
    validate_username,
)
from assessment import (
    compare_papers,
    marks_lost_breakdown,
    paper_summary,
    rebuild_student_profile,
    refresh_outdated_student_profiles,
    student_attempts,
    student_skill_profile,
    sync_submission_evidence,
)
from analytics import (
    analytics_practice,
    grading_audit_summary,
    student_analytics_summary,
    teacher_analytics_summary,
)
from auth import create_session_token, get_current_user, require_researcher, require_role
from db import (
    compute_topic_mastery,
    execute,
    hash_password,
    init_db,
    query_all,
    query_one,
    recommend_practice,
    seed_if_empty,
    update_assignment_total_marks,
    user_has_role,
    verify_password,
    weak_topics,
)
from grading import ensure_grade_rows, finalize_submission, reset_grade_rows, run_grading_job
from i18n import (
    get_lang,
    other_lang,
    role_label,
    skill_label,
    skill_status_label,
    status_label,
    strings,
    question_type_label,
    topic_label,
    type_label,
)
from ocr import cxsee_health_check, ocr_pages_for_submission, reset_ocr_cache
from paper_packs import ingest_0606_directory, paper_pack_inventory
from pipeline import PIPELINE_STAGES, create_processing_job, run_analysis_pipeline
from pdf_utils import get_page_image_base64, is_valid_pdf, pdf_to_page_images, save_upload
from reports import (
    assessment_report,
    profile_report,
    research_experiment_report,
    safe_filename,
    self_service_assessment_report,
)
from learning import (
    create_practice_set,
    mistake_book,
    mistake_book_pdf,
    practice_pdf,
    practice_set_detail,
    practice_sets,
    question_bank_inventory,
    skill_detail,
    skill_url,
    update_mistake_status,
)
from question_bank import (
    ingest_question_bank_zip,
    paper_bank_rows,
    review_questions,
    update_question_review,
)
from question_solver import solve_question_image
from self_service import (
    MAX_ANSWER_IMAGE_PAGES,
    SELF_SERVICE_STAGES,
    analysis_result,
    confirm_version,
    create_rerun_draft,
    create_student_paper_draft,
    direct_summary,
    normalize_answer_uploads,
    paper_with_versions,
    parse_json,
    purge_all_failed_papers,
    run_self_service_analysis,
    student_owned_papers,
)
from topics import TOPICS

init_db()
_refreshed_profiles = refresh_outdated_student_profiles()
if _refreshed_profiles:
    print(
        f"Refreshed {_refreshed_profiles} student skill profiles for "
        "the 25-day evidence half-life."
    )
_restart_time = datetime.now().isoformat()
execute(
    """
    UPDATE paper_analysis_versions
    SET status = 'failed', current_stage = 'interrupted',
        progress_message = 'Analysis interrupted by a server restart',
        failure_message = ?, failure_details = ?,
        heartbeat_at = ?, updated_at = ?, finished_at = ?
    WHERE status IN ('queued', 'processing')
    """,
    (
        "Analysis was interrupted by an application restart. Please rerun it; "
        "the uploaded files are still available.",
        json.dumps(
            {
                "error_type": "ApplicationRestart",
                "stage": "interrupted",
                "message": "The application restarted while this analysis was active.",
            }
        ),
        _restart_time,
        _restart_time,
        _restart_time,
    ),
)
execute(
    """
    UPDATE student_papers
    SET status = 'failed', updated_at = ?
    WHERE id IN (
        SELECT paper_id
        FROM paper_analysis_versions
        WHERE status = 'failed' AND current_stage = 'interrupted'
    )
    """,
    (_restart_time,),
)
_purged_failed_papers = purge_all_failed_papers()
if _purged_failed_papers:
    print(f"Removed {_purged_failed_papers} failed student paper records.")
seed_if_empty()
for warning in getattr(config, "CONFIG_WARNINGS", []):
    print(f"CONFIG WARNING: {warning}")

app = FastAPI(
    title="Sumkora - Cambridge IGCSE Additional Mathematics 0606",
    description=(
        "Private paper analysis and progress evidence for Cambridge IGCSE "
        "Additional Mathematics students."
    ),
)
templates = Jinja2Templates(directory="templates")
os.makedirs("static", exist_ok=True)
mimetypes.add_type("font/woff", ".woff")
app.mount("/static", StaticFiles(directory="static"), name="static")
os.makedirs(config.UPLOAD_DIR, exist_ok=True)
rate_limit_buckets: dict[str, deque[float]] = defaultdict(deque)


def rate_limited(
    request: Request,
    action: str,
    limit: int,
    window_seconds: int = 900,
) -> bool:
    client_host = request.client.host if request.client else "unknown"
    key = f"{action}:{client_host}"
    now = monotonic()
    attempts = rate_limit_buckets[key]
    while attempts and attempts[0] < now - window_seconds:
        attempts.popleft()
    if len(attempts) >= limit:
        return True
    attempts.append(now)
    return False


@app.exception_handler(StarletteHTTPException)
async def http_error_page(request: Request, exc: StarletteHTTPException):
    if "text/html" not in request.headers.get("accept", ""):
        return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)
    user = get_current_user(request)
    return render(
        request,
        "error.html",
        {
            "user": user,
            "status_code": exc.status_code,
            "heading": "Page not found" if exc.status_code == 404 else "Something went wrong",
            "message": (
                "The page you’re looking for does not exist."
                if exc.status_code == 404
                else "We couldn’t complete that request."
            ),
        },
        status_code=exc.status_code,
    )


@app.middleware("http")
async def security_middleware(request: Request, call_next):
    if request.url.path == "/teacher" or request.url.path.startswith("/teacher/"):
        user = get_current_user(request)
        if user and user_has_role(user["id"], "researcher", "owner"):
            return RedirectResponse("/research", status_code=303)
        return RedirectResponse("/login", status_code=303)
    if request.url.path == "/student/assignments" or request.url.path.startswith(
        "/student/assignments/"
    ):
        user = get_current_user(request)
        if user and require_role(request, "student"):
            return RedirectResponse("/student/analyse", status_code=303)
        return RedirectResponse("/login", status_code=303)
    if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
        origin = request.headers.get("origin")
        if origin:
            parsed = urlsplit(origin)
            if parsed.netloc != request.headers.get("host", ""):
                return JSONResponse({"detail": "Cross-site request blocked."}, status_code=403)
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "same-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; img-src 'self' data: blob:; style-src 'self' 'unsafe-inline'; "
        "script-src 'self' 'unsafe-inline'; "
        "font-src 'self' data:; connect-src 'self'; frame-ancestors 'none'"
    )
    if request.url.path.startswith("/static/"):
        response.headers["Cache-Control"] = "public, max-age=0, must-revalidate"
    return response


def redirect_login():
    return RedirectResponse("/login", status_code=303)


def render(request: Request, name: str, context: dict, status_code: int = 200):
    lang = get_lang(request)
    context = {
        **context,
        "lang": lang,
        "t": strings(lang),
        "tr": lambda english, chinese: chinese if lang == "zh" else english,
        "other_lang": other_lang(lang),
        "status_label": lambda s: status_label(lang, s),
        "type_label": lambda ty: type_label(lang, ty),
        "role_label": lambda r: role_label(lang, r),
        "topic_label": lambda top: topic_label(lang, top),
        "skill_label": lambda skill: skill_label(lang, skill),
        "skill_status_label": lambda status: skill_status_label(lang, status),
        "question_type_label": lambda key: question_type_label(lang, key),
        "count_label": count_label,
        "student_explanation": student_explanation,
        "skill_url": skill_url,
        "current_path": request.url.path,
        "is_researcher": bool(
            context.get("user")
            and user_has_role(context["user"]["id"], "researcher", "owner")
        ),
        "is_admin": bool(
            context.get("user")
            and user_has_role(context["user"]["id"], "owner")
        ),
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


def record_student_activity(
    student_id: int,
    event_type: str,
    *,
    path: str = "",
    entity_type: str = "",
    entity_id: str | int = "",
    active_seconds: int = 0,
    metadata: dict | None = None,
) -> None:
    safe_event = (
        event_type
        if event_type in {"page_open_time", "active_time", "download"}
        else "other"
    )
    execute(
        """
        INSERT INTO student_activity_events
        (student_id, event_type, path, entity_type, entity_id,
         active_seconds, metadata, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            student_id,
            safe_event,
            str(path or "")[:300],
            str(entity_type or "")[:80],
            str(entity_id or "")[:120],
            max(0, min(900, int(active_seconds or 0))),
            json.dumps(metadata or {}, ensure_ascii=False),
            datetime.now().astimezone().isoformat(),
        ),
    )


@app.post("/student/activity")
def student_activity_ping(
    request: Request,
    path: str = Form(""),
    active_seconds: int = Form(0),
):
    user = require_role(request, "student")
    if not user:
        return JSONResponse({"detail": "Authentication required."}, status_code=401)
    seconds = max(0, min(900, int(active_seconds or 0)))
    if seconds:
        record_student_activity(
            user["id"],
            "page_open_time",
            path=path,
            active_seconds=seconds,
        )
    return {"recorded": seconds}


def set_session_cookie(response, user_id: int):
    response.set_cookie(
        "session",
        create_session_token(user_id),
        httponly=True,
        secure=config.COOKIE_SECURE,
        samesite="lax",
        max_age=config.SESSION_MAX_AGE_SECONDS,
        path="/",
    )
    return response


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
    if user_has_role(user["id"], "researcher", "owner"):
        return RedirectResponse("/research", status_code=303)
    return RedirectResponse("/student", status_code=303)


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    return render(
        request,
        "login.html",
        {
            "error": None,
            "user": None,
            "identifier": "",
            "success": request.query_params.get("success"),
        },
    )


@app.post("/login")
def login_submit(
    request: Request,
    password: str = Form(...),
    identifier: str = Form(""),
    email: str = Form(""),
):
    supplied_identifier = (identifier or email).strip()
    if rate_limited(request, "login", limit=60):
        return render(
            request,
            "login.html",
            {
                "error": "Too many sign-in attempts. Please wait and try again.",
                "user": None,
                "identifier": supplied_identifier,
                "success": None,
            },
            status_code=429,
        )
    normalized = normalize_username(supplied_identifier)
    user = query_one(
        """
        SELECT * FROM users
        WHERE username_normalized = ? OR lower(email) = ?
        LIMIT 1
        """,
        (normalized, supplied_identifier.lower()),
    )
    if not user or not verify_password(password, user["password_hash"]):
        return render(
            request,
            "login.html",
            {
                "error": "That username or password is not correct.",
                "user": None,
                "identifier": supplied_identifier,
                "success": None,
            },
            status_code=400,
        )
    response = RedirectResponse("/", status_code=303)
    return set_session_cookie(response, user["id"])


@app.get("/signup", response_class=HTMLResponse)
def signup_page(request: Request):
    if get_current_user(request):
        return RedirectResponse("/", status_code=303)
    return render(
        request,
        "signup.html",
        {
            "user": None,
            "error": None,
            "error_field": None,
            "username": "",
            "display_name": "",
        },
    )


@app.post("/signup", response_class=HTMLResponse)
def signup_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    password_confirmation: str = Form(...),
    display_name: str = Form(""),
):
    form_context = {
        "user": None,
        "username": username.strip(),
        "display_name": display_name.strip(),
    }
    if rate_limited(request, "signup", limit=20):
        return render(
            request,
            "signup.html",
            {
                **form_context,
                "error": "Too many registration attempts. Please wait and try again.",
                "error_field": None,
            },
            status_code=429,
        )
    normalized, username_error = validate_username(username)
    if username_error:
        return render(
            request,
            "signup.html",
            {
                **form_context,
                "error": username_error,
                "error_field": "username",
            },
            status_code=400,
        )
    password_error = validate_password(password)
    if password_error:
        return render(
            request,
            "signup.html",
            {
                **form_context,
                "error": password_error,
                "error_field": "password",
            },
            status_code=400,
        )
    if password != password_confirmation:
        return render(
            request,
            "signup.html",
            {
                **form_context,
                "error": "Passwords do not match.",
                "error_field": "password_confirmation",
            },
            status_code=400,
        )
    if query_one(
        "SELECT 1 FROM users WHERE username_normalized = ?",
        (normalized,),
    ):
        return render(
            request,
            "signup.html",
            {
                **form_context,
                "error": "This username is already taken.",
                "error_field": "username",
            },
            status_code=400,
        )
    recovery_code = generate_recovery_code()
    internal_email = f"student-{uuid.uuid4().hex}@accounts.sumkora.invalid"
    original_username = username.strip()
    safe_display_name = display_name.strip()[:60] or original_username
    try:
        user_id = execute(
            """
            INSERT INTO users
            (email, username, username_normalized, password_hash, name, role,
             recovery_code_hash)
            VALUES (?, ?, ?, ?, ?, 'student', ?)
            """,
            (
                internal_email,
                original_username,
                normalized,
                hash_password(password),
                safe_display_name,
                recovery_code_hash(recovery_code),
            ),
        )
    except sqlite3.IntegrityError:
        return render(
            request,
            "signup.html",
            {
                **form_context,
                "error": "This username is already taken.",
                "error_field": "username",
            },
            status_code=400,
        )
    execute(
        """
        INSERT INTO user_roles (user_id, role, created_at)
        VALUES (?, 'student', ?)
        """,
        (user_id, datetime.now().isoformat()),
    )
    response = render(
        request,
        "signup_success.html",
        {
            "user": query_one("SELECT * FROM users WHERE id = ?", (user_id,)),
            "recovery_code": recovery_code,
        },
    )
    return set_session_cookie(response, user_id)


@app.get("/recover", response_class=HTMLResponse)
def recovery_page(request: Request):
    return render(
        request,
        "recover.html",
        {"user": None, "error": None, "username": ""},
    )


@app.post("/recover", response_class=HTMLResponse)
def recovery_submit(
    request: Request,
    username: str = Form(...),
    recovery_code: str = Form(...),
    password: str = Form(...),
    password_confirmation: str = Form(...),
):
    context = {"user": None, "username": username.strip()}
    if rate_limited(request, "recover", limit=12):
        return render(
            request,
            "recover.html",
            {
                **context,
                "error": "Too many recovery attempts. Please wait and try again.",
            },
            status_code=429,
        )
    password_error = validate_password(password)
    if password_error:
        return render(
            request,
            "recover.html",
            {**context, "error": password_error},
            status_code=400,
        )
    if password != password_confirmation:
        return render(
            request,
            "recover.html",
            {**context, "error": "Passwords do not match."},
            status_code=400,
        )
    user = query_one(
        """
        SELECT * FROM users
        WHERE username_normalized = ? AND role = 'student'
        """,
        (normalize_username(username),),
    )
    if not user or not recovery_code_matches(
        recovery_code,
        user["recovery_code_hash"],
    ):
        return render(
            request,
            "recover.html",
            {
                **context,
                "error": "We couldn’t verify that username and recovery code.",
            },
            status_code=400,
        )
    execute(
        """
        UPDATE users
        SET password_hash = ?, recovery_code_hash = NULL
        WHERE id = ?
        """,
        (hash_password(password), user["id"]),
    )
    response = RedirectResponse("/student?recovered=1", status_code=303)
    return set_session_cookie(response, user["id"])


@app.get("/logout")
def logout():
    response = RedirectResponse("/login", status_code=303)
    response.delete_cookie("session", path="/", samesite="lax")
    return response


@app.get("/health")
def health():
    db_ok = True
    try:
        query_one("SELECT 1 AS ok")
    except Exception:
        db_ok = False
    return {
        "status": "ok" if db_ok else "degraded",
        "database": db_ok,
        "ocr_provider": config.OCR_PROVIDER,
        "ocr_model": config.CXSEE_OCR_MODEL,
    }


def _owned_analysis_version(student_id: int, version_id: int):
    return query_one(
        """
        SELECT pav.*, sp.student_id, sp.title AS paper_title,
               sp.id AS student_paper_id
        FROM paper_analysis_versions pav
        JOIN student_papers sp ON sp.id = pav.paper_id
        WHERE pav.id = ? AND sp.student_id = ?
        """,
        (version_id, student_id),
    )


def _parse_expected_maximum_marks(raw_value: str) -> int | None:
    value = (raw_value or "").strip()
    if not value:
        return None
    try:
        number = float(value)
    except ValueError as exc:
        raise ValueError(
            "Maximum marks must be a whole number from 1 to 500."
        ) from exc
    if not number.is_integer() or not 1 <= number <= 500:
        raise ValueError("Maximum marks must be a whole number from 1 to 500.")
    return int(number)


async def _prepare_completed_work(
    uploads: list[UploadFile] | None,
) -> tuple[str, bytes]:
    selected = [upload for upload in uploads or [] if upload.filename]
    if not selected:
        raise ValueError("Completed work is required.")
    if len(selected) > MAX_ANSWER_IMAGE_PAGES:
        raise ValueError(
            f"Choose no more than {MAX_ANSWER_IMAGE_PAGES} completed-work images."
        )
    files: list[tuple[str, bytes]] = []
    total_size = 0
    for upload in selected:
        content = await upload.read()
        total_size += len(content)
        if not content or total_size > config.MAX_UPLOAD_BYTES:
            raise ValueError(
                "The completed-work files exceed the combined upload limit."
            )
        files.append((upload.filename or "completed-work", content))
    filename, payload = normalize_answer_uploads(files)
    if len(payload) > config.MAX_UPLOAD_BYTES:
        raise ValueError(
            "The prepared completed-work PDF exceeds the upload limit."
        )
    return filename, payload


def _localized_upload_error(request: Request, message: str) -> str:
    if get_lang(request) != "zh":
        return message
    if message.startswith("Choose no more than"):
        return f"最多可选择 {MAX_ANSWER_IMAGE_PAGES} 张答卷图片。"
    translations = {
        "Completed work is required.": "请上传已完成的答卷。",
        "Choose one PDF or multiple images, not both.": "请选择一个 PDF，或选择多张图片；请勿混合上传。",
        "Answer script must be a PDF, PNG, JPEG, or WebP image.": "答卷必须是 PDF、PNG、JPEG 或 WebP 文件。",
        "One of the completed-work images is unreadable.": "其中一张答卷图片无法读取。",
        "Not every completed-work image could be prepared.": "部分答卷图片无法转换。",
        "The completed-work files exceed the combined upload limit.": "答卷文件总大小超过上传限制。",
        "The prepared completed-work PDF exceeds the upload limit.": "合并后的答卷 PDF 超过上传限制。",
        "Paper name must be 160 characters or fewer.": "试卷名称不得超过 160 个字符。",
    }
    return translations.get(message, message)


@app.get("/student/analyse", response_class=HTMLResponse)
def student_analyse_page(request: Request):
    user = require_role(request, "student")
    if not user:
        return redirect_login()
    return render(
        request,
        "student/analyse.html",
        {
            "user": user,
            "error": None,
            "paper_name": "",
            "maximum_marks": "",
            "max_answer_pages": MAX_ANSWER_IMAGE_PAGES,
            "max_upload_bytes": config.MAX_UPLOAD_BYTES,
        },
    )


@app.post("/student/analyse")
async def student_analyse_upload(
    request: Request,
    background_tasks: BackgroundTasks,
    answer_script: list[UploadFile] = File(...),
    mark_scheme: UploadFile = File(None),
    paper_name: str = Form(""),
    maximum_marks: str = Form(""),
):
    user = require_role(request, "student")
    if not user:
        return redirect_login()
    try:
        expected_maximum_marks = _parse_expected_maximum_marks(maximum_marks)
    except ValueError as exc:
        return render(
            request,
            "student/analyse.html",
            {
                "user": user,
                "error": str(exc),
                "paper_name": paper_name,
                "maximum_marks": maximum_marks,
                "max_answer_pages": MAX_ANSWER_IMAGE_PAGES,
                "max_upload_bytes": config.MAX_UPLOAD_BYTES,
            },
            status_code=400,
        )
    scheme_content = (
        await mark_scheme.read()
        if mark_scheme and mark_scheme.filename
        else None
    )
    try:
        answer_filename, answer_content = await _prepare_completed_work(
            answer_script
        )
    except ValueError as exc:
        return render(
            request,
            "student/analyse.html",
            {
                "user": user,
                "error": _localized_upload_error(request, str(exc)),
                "paper_name": paper_name,
                "maximum_marks": maximum_marks,
                "max_answer_pages": MAX_ANSWER_IMAGE_PAGES,
                "max_upload_bytes": config.MAX_UPLOAD_BYTES,
            },
            status_code=400,
        )
    if scheme_content is not None and (
        len(scheme_content) <= 0
        or len(scheme_content) > config.MAX_UPLOAD_BYTES
    ):
        return render(
            request,
            "student/analyse.html",
            {
                "user": user,
                "error": (
                    "评分标准 PDF 超过上传限制。"
                    if get_lang(request) == "zh"
                    else "The mark-scheme PDF exceeds the upload limit."
                ),
                "paper_name": paper_name,
                "maximum_marks": maximum_marks,
                "max_answer_pages": MAX_ANSWER_IMAGE_PAGES,
                "max_upload_bytes": config.MAX_UPLOAD_BYTES,
            },
            status_code=400,
        )
    try:
        paper_id, version_id = create_student_paper_draft(
            user["id"],
            answer_filename,
            answer_content,
            mark_scheme.filename if mark_scheme and mark_scheme.filename else None,
            scheme_content,
            expected_maximum_marks=expected_maximum_marks,
            paper_name=paper_name,
        )
    except ValueError as exc:
        return render(
            request,
            "student/analyse.html",
            {
                "user": user,
                "error": _localized_upload_error(request, str(exc)),
                "paper_name": paper_name,
                "maximum_marks": maximum_marks,
                "max_answer_pages": MAX_ANSWER_IMAGE_PAGES,
                "max_upload_bytes": config.MAX_UPLOAD_BYTES,
            },
            status_code=400,
        )
    version = _owned_analysis_version(user["id"], version_id)
    metadata = parse_json(version["detected_metadata"], {})
    questions = parse_json(version["question_plan"], [])
    confirm_version(user["id"], version_id, metadata, questions)
    background_tasks.add_task(run_self_service_analysis, version_id)
    execute(
        """
        INSERT INTO audit_logs
        (actor_id, action, entity_type, entity_id, metadata, created_at)
        VALUES (?, 'student_paper_uploaded', 'student_paper', ?, ?, ?)
        """,
        (
            user["id"],
            str(paper_id),
            json.dumps(
                {
                    "analysis_version_id": version_id,
                    "expected_maximum_marks": expected_maximum_marks,
                    "paper_name": paper_name.strip() or None,
                }
            ),
            datetime.now().isoformat(),
        ),
    )
    return RedirectResponse(
        f"/student/analysis/{version_id}/processing",
        status_code=303,
    )


@app.get("/student/analysis/{version_id}/review", response_class=HTMLResponse)
def student_analysis_review(request: Request, version_id: int):
    user = require_role(request, "student")
    if not user:
        return redirect_login()
    version = _owned_analysis_version(user["id"], version_id)
    if not version:
        return RedirectResponse("/student/papers", status_code=303)
    if version["status"] in {"queued", "processing"}:
        return RedirectResponse(
            f"/student/analysis/{version_id}/processing",
            status_code=303,
        )
    if version["status"] == "completed":
        return RedirectResponse(
            f"/student/papers/{version['student_paper_id']}?version={version_id}",
            status_code=303,
        )
    return render(
        request,
        "student/analysis_review.html",
        {
            "user": user,
            "version": version,
            "error": None,
        },
    )


@app.post("/student/analysis/{version_id}/run")
async def student_analysis_run(
    request: Request,
    version_id: int,
    background_tasks: BackgroundTasks,
):
    user = require_role(request, "student")
    if not user:
        return redirect_login()
    version = _owned_analysis_version(user["id"], version_id)
    if not version:
        return RedirectResponse("/student/papers", status_code=303)
    metadata = parse_json(version["detected_metadata"], {})
    questions = parse_json(version["question_plan"], [])
    confirm_version(user["id"], version_id, metadata, questions)
    background_tasks.add_task(run_self_service_analysis, version_id)
    return RedirectResponse(
        f"/student/analysis/{version_id}/processing",
        status_code=303,
    )


@app.get(
    "/student/analysis/{version_id}/processing",
    response_class=HTMLResponse,
)
def student_self_service_processing(request: Request, version_id: int):
    user = require_role(request, "student")
    if not user:
        return redirect_login()
    version = _owned_analysis_version(user["id"], version_id)
    if not version:
        return RedirectResponse("/student/papers", status_code=303)
    return render(
        request,
        "student/self_processing.html",
        {
            "user": user,
            "version": version,
            "pipeline_stages": SELF_SERVICE_STAGES,
        },
    )


@app.get("/student/analysis/{version_id}/status")
def student_self_service_status(request: Request, version_id: int):
    user = require_role(request, "student")
    if not user:
        return JSONResponse({"detail": "Authentication required."}, status_code=401)
    version = _owned_analysis_version(user["id"], version_id)
    if not version:
        deleted_failure = query_one(
            """
            SELECT metadata
            FROM audit_logs
            WHERE actor_id = ?
              AND action = 'student_analysis_failed_and_deleted'
              AND entity_type = 'analysis_version'
              AND entity_id = ?
            ORDER BY id DESC LIMIT 1
            """,
            (user["id"], str(version_id)),
        )
        if deleted_failure:
            return {
                "status": "failed",
                "deleted": True,
                "current_stage": "failed",
                "stage_index": 0,
                "progress_percent": 0,
                "progress_message": "",
                "connection_state": "failed",
                "failure_message": (
                    "此次失败的分析已自动删除。请重新上传答卷后再试。"
                    if get_lang(request) == "zh"
                    else (
                        "The failed analysis was deleted automatically. "
                        "Please upload the paper again."
                    )
                ),
            }
        return JSONResponse({"detail": "Not found."}, status_code=404)
    failure_message = None
    if version["status"] == "failed":
        failure_message = (
            "无法完成此次分析。系统未记录任何零分。请重试；你的文件和之前的结果仍然安全。"
            if get_lang(request) == "zh"
            else (
                "We could not complete this analysis. No zero marks were "
                "recorded. Try again; your files and previous results are safe."
            )
        )
    now = datetime.now().astimezone()

    def age_seconds(value: str | None) -> int | None:
        if not value:
            return None
        try:
            parsed = datetime.fromisoformat(value)
            if parsed.tzinfo is None:
                parsed = parsed.astimezone()
            return max(0, int((now - parsed.astimezone()).total_seconds()))
        except (TypeError, ValueError):
            return None

    heartbeat_age = age_seconds(version["heartbeat_at"])
    elapsed = age_seconds(version["started_at"])
    if version["status"] == "completed":
        connection_state = "completed"
    elif version["status"] == "failed":
        connection_state = (
            "interrupted"
            if version["current_stage"] == "interrupted"
            else "failed"
        )
    elif version["status"] == "queued":
        connection_state = "queued"
    elif heartbeat_age is None or heartbeat_age > 30:
        connection_state = "stalled"
    elif elapsed is not None and elapsed >= 360:
        connection_state = "slow"
    else:
        connection_state = "working"

    progress_message = version["progress_message"] or ""
    progress_translations = {
        "Checking your files": "检查上传文件",
        "Preparing the complete documents": "准备完整文档",
        "Sending the complete paper to the assessor": "将完整试卷发送给批改模型",
        "Reading every page and applying the marking evidence": "逐页阅读并依据评分证据批改",
        "Checking the returned question inventory": "核对返回的题目清单",
        "Correcting an incomplete question inventory": "修正不完整的题目清单",
        "Cross-checking the detailed marks": "交叉核对详细得分",
        "Preparing complete text for missed questions": "整理失分题目的完整题干",
        "Writing your English and Chinese feedback": "生成中英文学习反馈",
        "Finalising the validated assessment": "完成已验证的分析结果",
        "Checking every question and mark total": "核对每道题与总分",
        "Building your question-by-question feedback": "整理逐题反馈",
        "Updating your strengths and weaknesses": "更新强项与待提升项",
        "Preparing your paper report": "生成试卷报告",
        "Analysis complete": "分析完成",
        "Analysis stopped before completion": "分析未能完成",
        "Analysis interrupted by a server restart": "服务器重启导致分析中断",
    }
    if get_lang(request) == "zh":
        progress_message = progress_translations.get(
            progress_message,
            progress_message,
        )
    progress_detail = version["progress_detail"] or ""
    if get_lang(request) == "zh" and progress_detail:
        detail_translations = {
            "The assessor responded; checking question coverage and totals": "批改模型已返回结果；正在检查题目覆盖与总分",
            "The first response was incomplete; requesting one corrected result": "第一次结果不完整；正在请求一次修正结果",
            "Cross-checking every detailed mark": "正在交叉核对每项详细得分",
            "Writing concise English and Chinese learning feedback": "正在生成简洁的中英文学习反馈",
        }
        attempt_match = re.fullmatch(
            r"Assessment attempt (\d+) of (\d+); (\d+) completed-work pages",
            progress_detail,
        )
        question_match = re.fullmatch(
            r"(\d+) question results validated",
            progress_detail,
        )
        context_match = re.fullmatch(
            r"Preparing complete text for (\d+) missed questions",
            progress_detail,
        )
        if attempt_match:
            progress_detail = (
                f"批改尝试 {attempt_match.group(1)}/{attempt_match.group(2)}；"
                f"共 {attempt_match.group(3)} 页答卷"
            )
        elif question_match:
            progress_detail = f"已验证 {question_match.group(1)} 项题目结果"
        elif context_match:
            progress_detail = (
                f"正在整理 {context_match.group(1)} 道失分题目的完整题干"
            )
        elif progress_detail in detail_translations:
            progress_detail = detail_translations[progress_detail]
        else:
            progress_detail = (
                progress_detail.replace(
                    " completed-work pages",
                    " 页答卷",
                ).replace(
                    " and ",
                    "，以及 ",
                ).replace(
                    " mark-scheme pages",
                    " 页评分标准",
                )
            )
    return {
        "status": version["status"],
        "current_stage": version["current_stage"],
        "stage_index": version["stage_index"],
        "progress_percent": version["progress_percent"],
        "progress_message": progress_message,
        "progress_detail": progress_detail,
        "heartbeat_at": version["heartbeat_at"],
        "heartbeat_age_seconds": heartbeat_age,
        "elapsed_seconds": elapsed,
        "connection_state": connection_state,
        "failure_message": failure_message,
        "paper_id": version["student_paper_id"],
        "version_number": version["version_number"],
    }


@app.get("/student/papers", response_class=HTMLResponse)
def student_papers_page(request: Request):
    user = require_role(request, "student")
    if not user:
        return redirect_login()
    legacy = student_attempts(user["id"])
    return render(
        request,
        "student/papers.html",
        {
            "user": user,
            "papers": student_owned_papers(user["id"]),
            "legacy_attempts": legacy,
        },
    )


@app.get("/student/papers/{paper_id}", response_class=HTMLResponse)
def student_paper_result(
    request: Request,
    paper_id: int,
    version: Optional[int] = None,
):
    user = require_role(request, "student")
    if not user:
        return redirect_login()
    result = analysis_result(user["id"], paper_id, version)
    if not result:
        return RedirectResponse("/student/papers", status_code=303)
    paper, versions = paper_with_versions(user["id"], paper_id)
    return render(
        request,
        "student/self_result.html",
        {
            "user": user,
            "result": result,
            "paper": paper,
            "versions": versions,
            "assessment_summary": parse_json(
                result["version"]["assessment_summary"],
                {},
            ),
        },
    )


@app.get("/student/papers/{paper_id}/report")
def student_self_service_report(
    request: Request,
    paper_id: int,
    version: Optional[int] = None,
):
    user = require_role(request, "student")
    if not user:
        return redirect_login()
    paper = query_one(
        "SELECT title FROM student_papers WHERE id = ? AND student_id = ?",
        (paper_id, user["id"]),
    )
    if not paper:
        return JSONResponse({"detail": "Not found."}, status_code=404)
    content = self_service_assessment_report(
        user["id"],
        paper_id,
        version_id=version,
        lang=get_lang(request),
    )
    if not content:
        return JSONResponse({"detail": "Report is not available."}, status_code=404)
    record_student_activity(
        user["id"],
        "download",
        path=request.url.path,
        entity_type="paper_report",
        entity_id=paper_id,
        metadata={"version": version},
    )
    return pdf_response(
        content,
        f"sumkora-{safe_filename(paper['title'])}-paper-report.pdf",
    )


@app.get("/student/papers/{paper_id}/rerun", response_class=HTMLResponse)
def student_paper_rerun_page(request: Request, paper_id: int):
    user = require_role(request, "student")
    if not user:
        return redirect_login()
    paper, versions = paper_with_versions(user["id"], paper_id)
    if not paper:
        return RedirectResponse("/student/papers", status_code=303)
    return render(
        request,
        "student/rerun.html",
        {
            "user": user,
            "paper": paper,
            "versions": versions,
            "error": None,
            "paper_name": paper["title"],
            "maximum_marks": (
                versions[0]["expected_maximum_marks"] if versions else ""
            ),
            "max_answer_pages": MAX_ANSWER_IMAGE_PAGES,
            "max_upload_bytes": config.MAX_UPLOAD_BYTES,
        },
    )


@app.post("/student/papers/{paper_id}/rerun")
async def student_paper_rerun(
    request: Request,
    paper_id: int,
    background_tasks: BackgroundTasks,
    answer_script: list[UploadFile] | None = File(None),
    mark_scheme: UploadFile = File(None),
    paper_name: str = Form(""),
    maximum_marks: str = Form(""),
):
    user = require_role(request, "student")
    if not user:
        return redirect_login()
    try:
        expected_maximum_marks = _parse_expected_maximum_marks(maximum_marks)
    except ValueError as exc:
        paper, versions = paper_with_versions(user["id"], paper_id)
        return render(
            request,
            "student/rerun.html",
            {
                "user": user,
                "paper": paper,
                "versions": versions,
                "error": str(exc),
                "paper_name": paper_name,
                "maximum_marks": maximum_marks,
                "max_answer_pages": MAX_ANSWER_IMAGE_PAGES,
                "max_upload_bytes": config.MAX_UPLOAD_BYTES,
            },
            status_code=400,
        )

    async def optional_file(upload: UploadFile | None):
        if not upload or not upload.filename:
            return None
        content = await upload.read()
        if len(content) > config.MAX_UPLOAD_BYTES:
            raise ValueError("A replacement file exceeds the upload limit.")
        return upload.filename, content

    try:
        replacement_answers = (
            await _prepare_completed_work(answer_script)
            if any(upload.filename for upload in answer_script or [])
            else None
        )
        version_id = create_rerun_draft(
            user["id"],
            paper_id,
            replacement_answers,
            await optional_file(mark_scheme),
            expected_maximum_marks=expected_maximum_marks,
            paper_name=paper_name,
        )
    except ValueError as exc:
        paper, versions = paper_with_versions(user["id"], paper_id)
        return render(
            request,
            "student/rerun.html",
            {
                "user": user,
                "paper": paper,
                "versions": versions,
                "error": _localized_upload_error(request, str(exc)),
                "paper_name": paper_name,
                "maximum_marks": maximum_marks,
                "max_answer_pages": MAX_ANSWER_IMAGE_PAGES,
                "max_upload_bytes": config.MAX_UPLOAD_BYTES,
            },
            status_code=400,
        )
    version = _owned_analysis_version(user["id"], version_id)
    confirm_version(
        user["id"],
        version_id,
        parse_json(version["detected_metadata"], {}),
        parse_json(version["question_plan"], []),
    )
    background_tasks.add_task(run_self_service_analysis, version_id)
    return RedirectResponse(
        f"/student/analysis/{version_id}/processing",
        status_code=303,
    )


@app.get("/student/papers/{paper_id}/documents/{document_type}")
def student_paper_document(
    request: Request,
    paper_id: int,
    document_type: str,
    version: Optional[int] = None,
):
    user = require_role(request, "student")
    if not user:
        return redirect_login()
    result = analysis_result(user["id"], paper_id, version)
    if not result:
        return JSONResponse({"detail": "Not found."}, status_code=404)
    fields = {
        "question": "question_paper_path",
        "answers": "answer_script_path",
        "scheme": "mark_scheme_path",
    }
    field = fields.get(document_type)
    path = result["version"][field] if field else None
    if not path or not os.path.isfile(path):
        return JSONResponse({"detail": "Not found."}, status_code=404)
    record_student_activity(
        user["id"],
        "download",
        path=request.url.path,
        entity_type=f"paper_source_{document_type}",
        entity_id=paper_id,
        metadata={"version": result["version"]["version_number"]},
    )
    return FileResponse(
        path,
        media_type="application/pdf",
        filename=(
            f"sumkora-{document_type}-"
            f"v{result['version']['version_number']}.pdf"
        ),
    )


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
        (class_id, title, type, due_date, status, question_paper_path,
         mark_scheme_path, created_at, syllabus_code, syllabus_version,
         calculator_policy)
        VALUES (?, ?, ?, ?, 'draft', ?, ?, ?, '0606', '2025-2027', 'unknown')
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
    sync_submission_evidence(submission_id)
    return RedirectResponse(f"/teacher/submissions/{submission_id}/review", status_code=303)


@app.post("/teacher/submissions/{submission_id}/ai-grade")
def ai_grade_submission(request: Request, submission_id: int):
    user, submission = teacher_submission(request, submission_id)
    if not user:
        return redirect_login()
    if not submission:
        return RedirectResponse("/teacher", status_code=303)
    job_id = create_processing_job(submission_id)
    run_analysis_pipeline(submission_id, job_id)
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
    sync_submission_evidence(submission_id)
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

    mastery = compute_topic_mastery(user["id"])
    analytics = student_analytics_summary(user["id"])
    recommendations = analytics_practice(user["id"], limit=5)
    weak = weak_topics(user["id"])
    attempts = student_attempts(user["id"])
    skill_profile = student_skill_profile(user["id"])
    direct = direct_summary(user["id"])

    return render(
        request,
        "student/dashboard.html",
        {
            "user": user,
            "mastery": mastery,
            "weak_topics": weak,
            "recommendations": recommendations,
            "analytics": analytics,
            "attempts": attempts,
            "skill_profile": skill_profile,
            "direct": direct,
            "learning_book": mistake_book(user["id"]),
            "learning_sets": practice_sets(user["id"]),
            "notice": (
                "Your password has been reset."
                if request.query_params.get("recovered")
                else None
            ),
        },
    )


@app.get("/student/settings", response_class=HTMLResponse)
def student_settings_page(request: Request):
    user = require_role(request, "student")
    if not user:
        return redirect_login()
    return render(
        request,
        "student/settings.html",
        {
            "user": user,
            "error": None,
            "success": request.query_params.get("success"),
        },
    )


@app.post("/student/settings/profile", response_class=HTMLResponse)
def student_settings_profile(
    request: Request,
    display_name: str = Form(...),
):
    user = require_role(request, "student")
    if not user:
        return redirect_login()
    cleaned = display_name.strip()
    if not 1 <= len(cleaned) <= 60:
        return render(
            request,
            "student/settings.html",
            {
                "user": user,
                "error": "Display name must be between 1 and 60 characters.",
                "success": None,
            },
            status_code=400,
        )
    execute("UPDATE users SET name = ? WHERE id = ?", (cleaned, user["id"]))
    return RedirectResponse(
        "/student/settings?success=profile",
        status_code=303,
    )


@app.post("/student/settings/exam")
def student_settings_exam(
    request: Request,
    exam_candidate: str = Form("0"),
    exam_date: str = Form(""),
    exam_session: str = Form(""),
):
    user = require_role(request, "student")
    if not user:
        return redirect_login()
    enabled = exam_candidate == "1"
    cleaned_date = exam_date.strip() if enabled else ""
    if cleaned_date:
        try:
            datetime.strptime(cleaned_date, "%Y-%m-%d")
        except ValueError:
            return render(
                request,
                "student/settings.html",
                {
                    "user": user,
                    "error": "Choose a valid exam date.",
                    "success": None,
                },
                status_code=400,
            )
    execute(
        """
        UPDATE users
        SET exam_candidate = ?, exam_date = ?, exam_session = ?
        WHERE id = ?
        """,
        (
            1 if enabled else 0,
            cleaned_date or None,
            exam_session.strip()[:60] if enabled else None,
            user["id"],
        ),
    )
    return RedirectResponse("/student/settings?success=exam", status_code=303)


@app.post("/student/settings/password", response_class=HTMLResponse)
def student_settings_password(
    request: Request,
    current_password: str = Form(...),
    password: str = Form(...),
    password_confirmation: str = Form(...),
):
    user = require_role(request, "student")
    if not user:
        return redirect_login()
    error = None
    if not verify_password(current_password, user["password_hash"]):
        error = "Your current password is not correct."
    elif password != password_confirmation:
        error = "Passwords do not match."
    else:
        error = validate_password(password)
    if error:
        return render(
            request,
            "student/settings.html",
            {"user": user, "error": error, "success": None},
            status_code=400,
        )
    execute(
        "UPDATE users SET password_hash = ? WHERE id = ?",
        (hash_password(password), user["id"]),
    )
    return RedirectResponse(
        "/student/settings?success=password",
        status_code=303,
    )


@app.get("/student/solve", response_class=HTMLResponse)
def student_solve_page(request: Request):
    user = require_role(request, "student")
    if not user:
        return redirect_login()
    questions = query_all(
        """
        SELECT * FROM student_help_questions
        WHERE student_id = ?
        ORDER BY created_at DESC, id DESC LIMIT 20
        """,
        (user["id"],),
    )
    return render(
        request,
        "student/solve.html",
        {
            "user": user,
            "questions": questions,
            "error": request.query_params.get("error"),
        },
    )


@app.post("/student/solve")
def student_solve_question(
    request: Request,
    image: UploadFile = File(...),
):
    user = require_role(request, "student")
    if not user:
        return redirect_login()
    content = image.file.read(config.MAX_UPLOAD_BYTES + 1)
    allowed_types = {"image/jpeg", "image/png", "image/webp"}
    if (
        not content
        or len(content) > config.MAX_UPLOAD_BYTES
        or image.content_type not in allowed_types
    ):
        return RedirectResponse(
            "/student/solve?error=invalid_image",
            status_code=303,
        )
    extension = {
        "image/jpeg": ".jpg",
        "image/png": ".png",
        "image/webp": ".webp",
    }[image.content_type]
    filename = f"solve-{user['id']}-{uuid.uuid4().hex}{extension}"
    path = save_upload(filename, content)
    started = monotonic()
    now = datetime.now().astimezone().isoformat()
    question_id = execute(
        """
        INSERT INTO student_help_questions
        (student_id, image_path, original_filename, status, created_at, updated_at)
        VALUES (?, ?, ?, 'processing', ?, ?)
        """,
        (user["id"], path, image.filename or "", now, now),
    )
    try:
        solution = solve_question_image(path)
        duration_ms = int((monotonic() - started) * 1000)
        execute(
            """
            UPDATE student_help_questions
            SET status = 'completed', transcription = ?, question_latex = ?,
                solution_en = ?, solution_zh = ?, final_answer = ?,
                final_answer_zh = ?, topic = ?, skill = ?,
                classification_confidence = ?, model = ?, duration_ms = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (
                solution["transcription"],
                solution["question_latex"],
                solution["solution_en"],
                solution["solution_zh"],
                solution["final_answer"],
                solution["final_answer_zh"],
                solution["topic"],
                solution["skill"],
                solution["classification_confidence"],
                solution["model"],
                duration_ms,
                datetime.now().astimezone().isoformat(),
                question_id,
            ),
        )
        record_student_activity(
            user["id"],
            "other",
            path=request.url.path,
            entity_type="help_question",
            entity_id=question_id,
            metadata={"duration_ms": duration_ms},
        )
    except Exception as exc:
        execute(
            """
            UPDATE student_help_questions
            SET status = 'failed', failure_message = ?, duration_ms = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (
                str(exc)[:600],
                int((monotonic() - started) * 1000),
                datetime.now().astimezone().isoformat(),
                question_id,
            ),
        )
    return RedirectResponse(f"/student/solve/{question_id}", status_code=303)


@app.get("/student/solve/{question_id}", response_class=HTMLResponse)
def student_solve_result(request: Request, question_id: int):
    user = require_role(request, "student")
    if not user:
        return redirect_login()
    question = query_one(
        """
        SELECT * FROM student_help_questions
        WHERE id = ? AND student_id = ?
        """,
        (question_id, user["id"]),
    )
    if not question:
        return RedirectResponse("/student/solve", status_code=303)
    return render(
        request,
        "student/solve_result.html",
        {"user": user, "question": question},
    )


@app.get("/student/solve/{question_id}/image")
def student_solve_image(request: Request, question_id: int):
    user = require_role(request, "student")
    if not user:
        return redirect_login()
    question = query_one(
        """
        SELECT image_path FROM student_help_questions
        WHERE id = ? AND student_id = ?
        """,
        (question_id, user["id"]),
    )
    if not question or not os.path.isfile(question["image_path"]):
        return JSONResponse({"detail": "Not found."}, status_code=404)
    return FileResponse(question["image_path"])


@app.get("/student/report")
def student_profile_report(request: Request):
    user = require_role(request, "student")
    if not user:
        return redirect_login()
    content = profile_report(user["id"], lang=get_lang(request), variant="student")
    record_student_activity(
        user["id"],
        "download",
        path=request.url.path,
        entity_type="progress_report",
    )
    return pdf_response(
        content,
        f"sumkora-{safe_filename(user['name'])}-progress-report.pdf",
    )


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
async def student_upload(
    request: Request,
    assignment_id: int,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
):
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
    if len(content) > config.MAX_UPLOAD_BYTES or not is_valid_pdf(content):
        return RedirectResponse(f"/student/assignments/{assignment_id}", status_code=303)
    digest = hashlib.sha256(content).hexdigest()
    duplicate = query_one(
        """
        SELECT id, assignment_id FROM submissions
        WHERE student_id = ? AND file_hash = ?
        ORDER BY uploaded_at DESC LIMIT 1
        """,
        (user["id"], digest),
    )
    if duplicate and duplicate["assignment_id"] != assignment_id:
        return RedirectResponse(
            f"/student/results/{duplicate['id']}", status_code=303
        )
    safe_original = os.path.basename(file.filename or "submission.pdf")
    path = save_upload(f"sub_{uuid.uuid4().hex}_{safe_original}", content)

    submission = query_one(
        "SELECT id FROM submissions WHERE assignment_id = ? AND student_id = ?",
        (assignment_id, user["id"]),
    )
    student_id = user["id"]

    if submission:
        execute(
            """
            UPDATE submissions
            SET file_path = ?, file_hash = ?, status = 'pending', uploaded_at = ?,
                confirmed_min_score = NULL, provisional_score = NULL,
                possible_max_score = NULL
            WHERE id = ?
            """,
            (path, digest, datetime.now().isoformat(), submission["id"]),
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
        execute(
            "UPDATE submissions SET file_hash = ? WHERE id = ?",
            (digest, sid),
        )
    ensure_grade_rows(sid, assignment_id)
    job_id = create_processing_job(sid)
    background_tasks.add_task(run_analysis_pipeline, sid, job_id)
    return RedirectResponse(f"/student/processing/{sid}", status_code=303)


@app.get("/student/processing/{submission_id}", response_class=HTMLResponse)
def student_processing(request: Request, submission_id: int):
    user = require_role(request, "student")
    if not user:
        return redirect_login()
    submission = query_one(
        """
        SELECT s.*, a.title AS assignment_title
        FROM submissions s
        JOIN assignments a ON a.id = s.assignment_id
        WHERE s.id = ? AND s.student_id = ?
        """,
        (submission_id, user["id"]),
    )
    if not submission:
        return RedirectResponse("/student", status_code=303)
    job = query_one(
        """
        SELECT * FROM processing_jobs
        WHERE submission_id = ?
        ORDER BY id DESC LIMIT 1
        """,
        (submission_id,),
    )
    return render(
        request,
        "student/processing.html",
        {
            "user": user,
            "submission": submission,
            "job": job,
            "pipeline_stages": PIPELINE_STAGES,
        },
    )


@app.get("/student/processing/{submission_id}/status")
def student_processing_status(request: Request, submission_id: int):
    user = require_role(request, "student")
    if not user:
        return JSONResponse({"detail": "Authentication required."}, status_code=401)
    submission = query_one(
        "SELECT id FROM submissions WHERE id = ? AND student_id = ?",
        (submission_id, user["id"]),
    )
    if not submission:
        return JSONResponse({"detail": "Not found."}, status_code=404)
    job = query_one(
        "SELECT * FROM processing_jobs WHERE submission_id = ? ORDER BY id DESC LIMIT 1",
        (submission_id,),
    )
    return dict(job) if job else {"status": "queued", "current_stage": "validation"}


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
    summary = paper_summary(user["id"], submission_id)
    lost = marks_lost_breakdown(submission_id)

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
            "summary": summary,
            "marks_lost": lost,
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
    record_student_activity(
        user["id"],
        "download",
        path=request.url.path,
        entity_type="legacy_paper_report",
        entity_id=submission_id,
    )
    return pdf_response(
        content,
        (
            f"sumkora-{safe_filename(user['name'])}-"
            f"{safe_filename(submission['assignment_title'])}-paper-report.pdf"
        ),
    )


@app.get("/student/history", response_class=HTMLResponse)
def student_history(request: Request):
    user = require_role(request, "student")
    if not user:
        return redirect_login()
    return RedirectResponse("/student/papers", status_code=303)


@app.get("/student/compare", response_class=HTMLResponse)
def retired_student_compare(request: Request):
    user = require_role(request, "student")
    if not user:
        return redirect_login()
    return RedirectResponse("/student/papers", status_code=303)


@app.get("/student/skills", response_class=HTMLResponse)
def student_skills(request: Request):
    user = require_role(request, "student")
    if not user:
        return redirect_login()
    profile = student_skill_profile(user["id"])
    return render(
        request,
        "student/skills.html",
        {"user": user, "profile": profile},
    )


@app.get("/student/skills/detail", response_class=HTMLResponse)
def student_skill_detail(request: Request, skill: str = "", topic: str = ""):
    user = require_role(request, "student")
    if not user:
        return redirect_login()
    detail = skill_detail(user["id"], skill, topic)
    if not detail:
        return RedirectResponse("/student/skills", status_code=303)
    return render(
        request,
        "student/skill_detail.html",
        {"user": user, "detail": detail},
    )


@app.get("/student/mistakes", response_class=HTMLResponse)
def student_mistakes(
    request: Request,
    topic: str = "",
    status: str = "",
):
    user = require_role(request, "student")
    if not user:
        return redirect_login()
    return render(
        request,
        "student/mistakes.html",
        {
            "user": user,
            "book": mistake_book(user["id"], topic=topic, status=status),
        },
    )


@app.post("/student/mistakes/{entry_id}/status")
def student_mistake_status(
    request: Request,
    entry_id: int,
    status: str = Form(...),
):
    user = require_role(request, "student")
    if not user:
        return redirect_login()
    update_mistake_status(user["id"], entry_id, status)
    return RedirectResponse("/student/mistakes", status_code=303)


@app.get("/student/mistakes/{kind}.pdf")
def student_mistake_book_pdf(request: Request, kind: str):
    user = require_role(request, "student")
    if not user:
        return redirect_login()
    if kind not in {"questions", "answers"}:
        return JSONResponse({"detail": "Not found."}, status_code=404)
    content = mistake_book_pdf(user["id"], kind, get_lang(request))
    suffix = "questions" if kind == "questions" else "answers"
    record_student_activity(
        user["id"],
        "download",
        path=request.url.path,
        entity_type=f"mistake_book_{kind}",
    )
    return pdf_response(content, f"sumkora-mistake-book-{suffix}.pdf")


@app.get("/student/practice", response_class=HTMLResponse)
def student_practice(request: Request):
    user = require_role(request, "student")
    if not user:
        return redirect_login()
    return render(
        request,
        "student/practice.html",
        {
            "user": user,
            "sets": practice_sets(user["id"]),
            "bank": question_bank_inventory(),
        },
    )


@app.post("/student/practice")
def student_create_practice(
    request: Request,
    count: int = Form(...),
    selection_mode: str = Form("weaknesses"),
    topic: str = Form(""),
    difficulty: str = Form("mixed"),
    calculator_policy: str = Form("any"),
):
    user = require_role(request, "student")
    if not user:
        return redirect_login()
    set_id = create_practice_set(
        user["id"],
        count=count,
        selection_mode=selection_mode,
        topic=topic,
        difficulty=difficulty,
        calculator_policy=calculator_policy,
        lang=get_lang(request),
    )
    return RedirectResponse(f"/student/practice/{set_id}", status_code=303)


@app.get("/student/practice/{set_id}", response_class=HTMLResponse)
def student_practice_detail(request: Request, set_id: int):
    user = require_role(request, "student")
    if not user:
        return redirect_login()
    detail = practice_set_detail(user["id"], set_id)
    if not detail:
        return RedirectResponse("/student/practice", status_code=303)
    return render(
        request,
        "student/practice_detail.html",
        {"user": user, "practice": detail},
    )


@app.get("/student/practice/{set_id}/{kind}.pdf")
def student_practice_pdf(request: Request, set_id: int, kind: str):
    user = require_role(request, "student")
    if not user:
        return redirect_login()
    if kind not in {"questions", "answers"}:
        return JSONResponse({"detail": "Not found."}, status_code=404)
    content = practice_pdf(user["id"], set_id, kind, get_lang(request))
    if not content:
        return JSONResponse({"detail": "Not found."}, status_code=404)
    record_student_activity(
        user["id"],
        "download",
        path=request.url.path,
        entity_type=f"practice_{kind}",
        entity_id=set_id,
    )
    return pdf_response(
        content,
        f"sumkora-practice-{set_id}-{kind}.pdf",
    )


@app.post("/student/practice/{set_id}/submit")
async def student_practice_submit(
    request: Request,
    set_id: int,
    background_tasks: BackgroundTasks,
    completed_work: UploadFile = File(...),
):
    user = require_role(request, "student")
    if not user:
        return redirect_login()
    detail = practice_set_detail(user["id"], set_id)
    if not detail:
        return RedirectResponse("/student/practice", status_code=303)
    payload = await completed_work.read()
    if (
        not payload
        or len(payload) > config.MAX_UPLOAD_BYTES
        or not is_valid_pdf(payload)
    ):
        return RedirectResponse(
            f"/student/practice/{set_id}?upload_error=1",
            status_code=303,
        )
    answer_key = practice_pdf(user["id"], set_id, "answers", get_lang(request))
    if not answer_key:
        return RedirectResponse(f"/student/practice/{set_id}", status_code=303)
    try:
        paper_id, version_id = create_student_paper_draft(
            user["id"],
            completed_work.filename or f"practice-{set_id}.pdf",
            payload,
            f"sumkora-practice-{set_id}-answers.pdf",
            answer_key,
        )
    except ValueError:
        return RedirectResponse(
            f"/student/practice/{set_id}?upload_error=1",
            status_code=303,
        )
    execute(
        """
        UPDATE student_papers
        SET title = ?, source_type = 'practice', updated_at = ?
        WHERE id = ?
        """,
        (
            f"Practice: {detail['set']['title']}",
            datetime.now().isoformat(),
            paper_id,
        ),
    )
    execute(
        """
        UPDATE practice_sets
        SET status = 'completed', analysis_paper_id = ?, submitted_at = ?,
            updated_at = ?
        WHERE id = ? AND student_id = ?
        """,
        (
            paper_id,
            datetime.now().isoformat(),
            datetime.now().isoformat(),
            set_id,
            user["id"],
        ),
    )
    version = _owned_analysis_version(user["id"], version_id)
    confirm_version(
        user["id"],
        version_id,
        parse_json(version["detected_metadata"], {}),
        parse_json(version["question_plan"], []),
    )
    background_tasks.add_task(run_self_service_analysis, version_id)
    return RedirectResponse(
        f"/student/analysis/{version_id}/processing",
        status_code=303,
    )


@app.get(
    "/student/results/{submission_id}/questions/{question_id}",
    response_class=HTMLResponse,
)
def student_question_detail(request: Request, submission_id: int, question_id: int):
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
    question = query_one(
        """
        SELECT q.*, gd.final_mark, gd.ai_mark, gd.ai_confidence, gd.ai_notes,
               gd.teacher_comment, gd.risk_flags, gd.needs_exception_review
        FROM questions q
        JOIN grade_drafts gd ON gd.question_id = q.id
        WHERE q.id = ? AND gd.submission_id = ?
        """,
        (question_id, submission_id),
    )
    if not question:
        return RedirectResponse(f"/student/results/{submission_id}", status_code=303)
    decisions = query_all(
        """
        SELECT cd.*, mc.criterion_code, mc.mark_type, mc.description,
               mc.dependencies, mc.follow_through_rules
        FROM criterion_decisions cd
        JOIN marking_criteria mc ON mc.id = cd.criterion_id
        WHERE cd.submission_id = ? AND cd.question_id = ? AND cd.is_current = 1
        ORDER BY mc.order_index
        """,
        (submission_id, question_id),
    )
    related = query_all(
        """
        SELECT so.*, a.title
        FROM skill_observations so
        JOIN submissions s ON s.id = so.submission_id
        JOIN assignments a ON a.id = s.assignment_id
        WHERE so.student_id = ?
          AND so.skill = COALESCE(?, ?, ?)
          AND so.submission_id != ?
        ORDER BY so.observed_at DESC LIMIT 8
        """,
        (
            user["id"],
            question["subtopic"],
            question["assessment_objective"],
            question["topic"],
            submission_id,
        ),
    )
    return render(
        request,
        "student/question_detail.html",
        {
            "user": user,
            "submission": submission,
            "question": question,
            "decisions": decisions,
            "related": related,
            "page_image": get_page_image_base64(
                submission["file_path"], question["page_number"], dpi=140
            ),
        },
    )


@app.get("/student/submissions/{submission_id}/file")
def student_submission_file(request: Request, submission_id: int):
    user = require_role(request, "student")
    if not user:
        return redirect_login()
    submission = query_one(
        "SELECT * FROM submissions WHERE id = ? AND student_id = ?",
        (submission_id, user["id"]),
    )
    if not submission or not os.path.isfile(submission["file_path"]):
        return JSONResponse({"detail": "Not found."}, status_code=404)
    record_student_activity(
        user["id"],
        "download",
        path=request.url.path,
        entity_type="legacy_submission",
        entity_id=submission_id,
    )
    return FileResponse(
        submission["file_path"],
        media_type="application/pdf",
        filename=f"sumkora-submission-{submission_id}.pdf",
    )


def _research_overview():
    return {
        "students": query_one(
            "SELECT COUNT(*) AS count FROM users WHERE role = 'student'"
        )["count"],
        "attempts": query_one(
            """
            SELECT
              (SELECT COUNT(*) FROM submissions) +
              (SELECT COUNT(*) FROM student_papers) AS count
            """
        )["count"],
        "question_responses": query_one(
            """
            SELECT
              (SELECT COUNT(*) FROM grade_drafts) +
              (SELECT COUNT(*) FROM analysis_question_results) AS count
            """
        )["count"],
        "criterion_decisions": query_one(
            """
            SELECT
              (SELECT COUNT(*) FROM criterion_decisions) +
              (SELECT COUNT(*) FROM analysis_question_results) AS count
            """
        )["count"],
        "human_corrections": query_one(
            """
            SELECT
              (SELECT COUNT(*) FROM human_corrections) +
              (SELECT COUNT(*) FROM analysis_human_corrections) AS count
            """
        )["count"],
        "uncertain_decisions": query_one(
            """
            SELECT
              (SELECT COUNT(*) FROM criterion_decisions WHERE decision = 'uncertain') +
              (SELECT COUNT(*) FROM analysis_question_results
               WHERE ai_confidence < 0.70) AS count
            """
        )["count"],
        "failed_jobs": query_one(
            """
            SELECT
              (SELECT COUNT(*) FROM processing_jobs WHERE status = 'failed') +
              (SELECT COUNT(*) FROM paper_analysis_versions WHERE status = 'failed') AS count
            """
        )["count"],
        "ocr_runs": query_one(
            """
            SELECT
              (SELECT COUNT(*) FROM model_runs WHERE run_type = 'ocr') +
              (SELECT COUNT(*) FROM analysis_ocr_pages) AS count
            """
        )["count"],
        "grading_runs": query_one(
            """
            SELECT
              (SELECT COUNT(*) FROM model_runs WHERE run_type != 'ocr') +
              (SELECT COUNT(*) FROM analysis_question_results) AS count
            """
        )["count"],
        "active_experiments": query_one(
            """
            SELECT COUNT(*) AS count FROM research_experiments
            WHERE status IN ('draft', 'ready', 'running')
            """
        )["count"],
        "completed_experiments": query_one(
            "SELECT COUNT(*) AS count FROM research_experiments WHERE status = 'completed'"
        )["count"],
    }


def _student_usage_rows(today_started_at: str) -> list[dict]:
    return [
        {
            **dict(row),
            "open_minutes": round(float(row["open_seconds"] or 0) / 60, 1),
            "open_minutes_today": round(
                float(row["open_seconds_today"] or 0) / 60,
                1,
            ),
        }
        for row in query_all(
            """
            SELECT u.id, u.name, COALESCE(u.username, u.email) AS username,
                   COALESCE(SUM(sae.active_seconds), 0) AS open_seconds,
                   COALESCE(SUM(
                       CASE WHEN sae.created_at >= ?
                            THEN sae.active_seconds ELSE 0 END
                   ), 0) AS open_seconds_today,
                   COALESCE(SUM(
                       CASE WHEN sae.event_type = 'download' THEN 1 ELSE 0 END
                   ), 0) AS download_count,
                   MAX(sae.created_at) AS last_active_at,
                   (
                       SELECT sae2.path
                       FROM student_activity_events sae2
                       WHERE sae2.student_id = u.id
                         AND sae2.active_seconds > 0
                       ORDER BY sae2.id DESC LIMIT 1
                   ) AS last_page,
                   (
                       SELECT COUNT(*)
                       FROM paper_analysis_versions pav
                       JOIN student_papers sp ON sp.id = pav.paper_id
                       WHERE sp.student_id = u.id AND pav.status = 'completed'
                   ) AS paper_analysis_count,
                   (
                       SELECT COUNT(*)
                       FROM analysis_question_results aqr
                       JOIN paper_analysis_versions pav
                         ON pav.id = aqr.analysis_version_id
                       JOIN student_papers sp ON sp.id = pav.paper_id
                       WHERE sp.student_id = u.id AND pav.status = 'completed'
                   ) AS analysed_question_count,
                   (
                       SELECT COUNT(*)
                       FROM student_help_questions shq
                       WHERE shq.student_id = u.id AND shq.status = 'completed'
                   ) AS solved_question_count,
                   (
                       SELECT COUNT(*)
                       FROM practice_sets ps
                       WHERE ps.student_id = u.id AND ps.status != 'archived'
                   ) AS worksheet_count
            FROM users u
            LEFT JOIN student_activity_events sae ON sae.student_id = u.id
            WHERE u.role = 'student'
              AND NOT EXISTS (
                  SELECT 1 FROM user_roles ur
                  WHERE ur.user_id = u.id
                    AND ur.role IN ('researcher', 'owner')
              )
            GROUP BY u.id, u.name, u.username, u.email
            ORDER BY last_active_at DESC, u.name
            """,
            (today_started_at,),
        )
    ]


def _recent_student_downloads() -> list:
    return query_all(
        """
        SELECT sae.*, u.name AS student_name,
               COALESCE(u.username, u.email) AS username
        FROM student_activity_events sae
        JOIN users u ON u.id = sae.student_id
        WHERE sae.event_type = 'download'
        ORDER BY sae.created_at DESC
        LIMIT 20
        """
    )


def _admin_usage_overview() -> dict:
    return dict(
        query_one(
            """
            SELECT
              (SELECT COUNT(*) FROM users u
               WHERE u.role = 'student'
                 AND NOT EXISTS (
                   SELECT 1 FROM user_roles ur
                   WHERE ur.user_id = u.id
                     AND ur.role IN ('researcher', 'owner')
                 )) AS students,
              COALESCE((SELECT SUM(active_seconds)
                        FROM student_activity_events), 0) AS open_seconds,
              (SELECT COUNT(*) FROM student_activity_events
               WHERE event_type = 'download') AS downloads,
              (SELECT COUNT(*) FROM paper_analysis_versions
               WHERE status = 'completed') AS paper_analyses,
              (SELECT COUNT(*) FROM analysis_question_results) AS analysed_questions,
              (SELECT COUNT(*) FROM student_help_questions
               WHERE status = 'completed') AS solved_questions
            """
        )
    )


@app.get("/research", response_class=HTMLResponse)
def research_dashboard(request: Request):
    user = require_researcher(request)
    if not user:
        return redirect_login()
    today_started_at = (
        datetime.now()
        .astimezone()
        .replace(hour=0, minute=0, second=0, microsecond=0)
        .isoformat()
    )
    student_activity = _student_usage_rows(today_started_at)
    recent_downloads = _recent_student_downloads()
    if user_has_role(user["id"], "owner"):
        return render(
            request,
            "research/dashboard.html",
            {
                "user": user,
                "admin_overview": _admin_usage_overview(),
                "student_activity": student_activity,
                "recent_downloads": recent_downloads,
            },
        )
    recent_runs = query_all(
        "SELECT * FROM model_runs ORDER BY started_at DESC LIMIT 20"
    )
    uncertain = query_all(
        """
        SELECT cd.*, q.label, q.topic, s.student_id, a.title
        FROM criterion_decisions cd
        LEFT JOIN questions q ON q.id = cd.question_id
        JOIN submissions s ON s.id = cd.submission_id
        JOIN assignments a ON a.id = s.assignment_id
        WHERE cd.decision = 'uncertain'
        ORDER BY cd.created_at DESC LIMIT 20
        """
    )
    experiments = query_all(
        "SELECT * FROM research_experiments ORDER BY created_at DESC LIMIT 20"
    )
    activity = query_all(
        "SELECT * FROM audit_logs ORDER BY created_at DESC LIMIT 12"
    )
    dataset = query_one(
        """
        SELECT
          (SELECT COUNT(*) FROM student_papers) AS self_service_papers,
          (SELECT COUNT(*) FROM submissions) AS legacy_submissions,
          (SELECT COUNT(*) FROM analysis_ocr_pages) AS self_service_ocr_pages,
          (SELECT COUNT(*) FROM human_corrections) +
          (SELECT COUNT(*) FROM analysis_human_corrections) AS labelled_decisions
        """
    )
    analysis_runs = []
    for row in query_all(
        """
        SELECT pav.*, sp.title AS paper_title, sp.maximum_marks,
               u.name AS student_name,
               (SELECT COUNT(*) FROM analysis_question_results aqr
                WHERE aqr.analysis_version_id = pav.id) AS question_count
        FROM paper_analysis_versions pav
        JOIN student_papers sp ON sp.id = pav.paper_id
        JOIN users u ON u.id = sp.student_id
        WHERE pav.assessment_mode IN ('estimate', 'detailed')
        ORDER BY pav.created_at DESC
        LIMIT 20
        """
    ):
        item = dict(row)
        provider = parse_json(item.get("provider_metadata"), {})
        failure = parse_json(item.get("failure_details"), {})
        item.update(
            {
                "provider_model": provider.get("model")
                or item.get("grading_model")
                or config.WHOLE_DOCUMENT_MODEL,
                "duration_seconds": (
                    round(float(provider.get("duration_ms") or 0) / 1000, 1)
                    if provider.get("duration_ms") is not None
                    else None
                ),
                "provider_attempts": provider.get("attempts"),
                "context_seconds": round(
                    float(
                        (provider.get("document_context") or {}).get(
                            "duration_ms",
                            0,
                        )
                    )
                    / 1000,
                    1,
                ),
                "feedback_seconds": round(
                    float(
                        (provider.get("feedback") or {}).get(
                            "duration_ms",
                            0,
                        )
                    )
                    / 1000,
                    1,
                ),
                "failure_type": failure.get("error_type"),
            }
        )
        analysis_runs.append(item)
    return render(
        request,
        "research/dashboard.html",
        {
            "user": user,
            "overview": _research_overview(),
            "paper_packs": paper_pack_inventory(),
            "provider_health": cxsee_health_check(),
            "recent_runs": recent_runs,
            "uncertain": uncertain,
            "experiments": experiments,
            "activity": activity,
            "dataset": dataset,
            "student_activity": student_activity,
            "recent_downloads": recent_downloads,
            "analysis_runs": analysis_runs,
            "whole_document_model": config.WHOLE_DOCUMENT_MODEL,
            "whole_document_target_seconds": config.WHOLE_DOCUMENT_TARGET_SECONDS,
        },
    )


@app.post("/research/paper-packs/ingest")
def research_ingest_paper_packs(request: Request):
    user = require_researcher(request)
    if not user:
        return redirect_login()
    imported = ingest_0606_directory("private_test_data/official_0606")
    execute(
        """
        INSERT INTO audit_logs (actor_id, action, entity_type, metadata, created_at)
        VALUES (?, 'paper_pack_ingest', 'paper_pack', ?, ?)
        """,
        (user["id"], json.dumps(imported), datetime.now().isoformat()),
    )
    return RedirectResponse("/research", status_code=303)


@app.get("/research/question-bank", response_class=HTMLResponse)
def research_question_bank(request: Request):
    user = require_researcher(request)
    if not user:
        return redirect_login()
    return render(
        request,
        "research/question_bank.html",
        {
            "user": user,
            "inventory": question_bank_inventory(),
            "papers": paper_bank_rows(),
            "questions": review_questions(),
            "imported": request.query_params.get("imported"),
            "warnings": request.query_params.get("warnings"),
            "error": request.query_params.get("error"),
        },
    )


@app.post("/research/question-bank/import")
async def research_question_bank_import(
    request: Request,
    archive: UploadFile = File(...),
):
    user = require_researcher(request)
    if not user:
        return redirect_login()
    payload = await archive.read()
    try:
        result = ingest_question_bank_zip(
            payload,
            archive.filename or "question-bank.zip",
        )
    except (ValueError, zipfile.BadZipFile) as exc:
        return RedirectResponse(
            f"/research/question-bank?error={quote(str(exc), safe='')}",
            status_code=303,
        )
    execute(
        """
        INSERT INTO audit_logs (actor_id, action, entity_type, metadata, created_at)
        VALUES (?, 'question_bank_import', 'paper_pack', ?, ?)
        """,
        (user["id"], json.dumps(result), datetime.now().isoformat()),
    )
    ready = sum(item["ready"] for item in result["papers"])
    return RedirectResponse(
        f"/research/question-bank?imported={ready}&warnings={len(result['warnings'])}",
        status_code=303,
    )


@app.post("/research/question-bank/questions/{question_id}")
def research_question_bank_review(
    request: Request,
    question_id: int,
    topic: str = Form(...),
    skills: str = Form(""),
    difficulty: str = Form("standard"),
    review_status: str = Form("needs_review"),
):
    user = require_researcher(request)
    if not user:
        return redirect_login()
    update_question_review(
        question_id,
        topic=topic,
        skills=skills,
        difficulty=difficulty,
        review_status=review_status,
    )
    return RedirectResponse("/research/question-bank", status_code=303)


@app.post("/research/decisions/{decision_id}/correct")
def research_correct_decision(
    request: Request,
    decision_id: int,
    corrected_marks: float = Form(...),
    reason: str = Form(...),
    notes: str = Form(""),
):
    user = require_researcher(request)
    if not user:
        return redirect_login()
    decision = query_one(
        """
        SELECT cd.*, mc.marks AS criterion_marks
        FROM criterion_decisions cd
        JOIN marking_criteria mc ON mc.id = cd.criterion_id
        WHERE cd.id = ?
        """,
        (decision_id,),
    )
    if not decision:
        return RedirectResponse("/research", status_code=303)
    corrected = max(0.0, min(float(corrected_marks), float(decision["available_marks"])))
    execute(
        """
        INSERT INTO human_corrections
        (criterion_decision_id, corrected_by, original_marks, corrected_marks,
         reason, notes, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            decision_id,
            user["id"],
            decision["awarded_marks"],
            corrected,
            reason,
            notes,
            datetime.now().isoformat(),
        ),
    )
    execute(
        """
        INSERT INTO audit_logs (actor_id, action, entity_type, entity_id, metadata, created_at)
        VALUES (?, 'human_correction', 'criterion_decision', ?, ?, ?)
        """,
        (
            user["id"],
            str(decision_id),
            json.dumps({"reason": reason}),
            datetime.now().isoformat(),
        ),
    )
    return RedirectResponse("/research", status_code=303)


@app.post("/research/experiments")
def research_create_experiment(
    request: Request,
    title: str = Form(...),
    research_question: str = Form(""),
    hypothesis: str = Form(""),
    description: str = Form(""),
    dataset_selection: str = Form("{}"),
    ocr_model: str = Form(""),
    grading_model: str = Form(""),
    diagnosis_model: str = Form(""),
    ocr_prompt_version: str = Form(""),
    grading_prompt_version: str = Form("grading-0606-v1"),
    confidence_threshold: float = Form(0.70),
    deterministic_checks: str = Form("1"),
    image_resolution: int = Form(200),
    evaluation_metrics: str = Form("[]"),
    notes: str = Form(""),
):
    user = require_researcher(request)
    if not user:
        return redirect_login()
    now = datetime.now().isoformat()
    try:
        dataset_json = json.loads(dataset_selection or "{}")
        metrics_json = json.loads(evaluation_metrics or "[]")
    except json.JSONDecodeError:
        dataset_json, metrics_json = {}, []
    experiment_id = execute(
        """
        INSERT INTO research_experiments
        (title, research_question, hypothesis, description, dataset_selection,
         ocr_model, grading_model, diagnosis_model, ocr_prompt_version,
         grading_prompt_version, confidence_threshold, deterministic_checks,
         image_resolution, evaluation_metrics, notes, status, created_by,
         created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'draft', ?, ?, ?)
        """,
        (
            title,
            research_question,
            hypothesis,
            description,
            json.dumps(dataset_json),
            ocr_model or config.CXSEE_OCR_MODEL,
            grading_model or config.CXSEE_MARKING_MODEL,
            diagnosis_model or config.CXSEE_DIAGNOSIS_MODEL or config.CXSEE_MARKING_MODEL,
            ocr_prompt_version or config.OCR_PROMPT_VERSION,
            grading_prompt_version,
            max(0.0, min(confidence_threshold, 1.0)),
            0 if deterministic_checks in {"0", "false", "off"} else 1,
            max(72, min(image_resolution, 400)),
            json.dumps(metrics_json),
            notes,
            user["id"],
            now,
            now,
        ),
    )
    return RedirectResponse(f"/research/experiments/{experiment_id}", status_code=303)


@app.get("/research/experiments", response_class=HTMLResponse)
def research_experiments_page(request: Request):
    user = require_researcher(request)
    if not user:
        return redirect_login()
    experiments = query_all(
        """
        SELECT re.*,
               (SELECT COUNT(*) FROM research_experiment_runs rer
                WHERE rer.experiment_id = re.id) AS run_count,
               (SELECT MAX(sample_size) FROM research_experiment_runs rer
                WHERE rer.experiment_id = re.id) AS latest_sample_size
        FROM research_experiments re
        ORDER BY CASE re.status WHEN 'running' THEN 0 WHEN 'ready' THEN 1
                 WHEN 'draft' THEN 2 WHEN 'completed' THEN 3 ELSE 4 END,
                 re.updated_at DESC
        """
    )
    return render(
        request,
        "research/experiments.html",
        {"user": user, "experiments": experiments},
    )


@app.get("/research/experiments/new", response_class=HTMLResponse)
def research_experiment_new(request: Request):
    user = require_researcher(request)
    if not user:
        return redirect_login()
    return render(
        request,
        "research/experiment_form.html",
        {"user": user, "experiment": None, "config": config},
    )


@app.get("/research/experiments/{experiment_id}", response_class=HTMLResponse)
def research_experiment_detail(request: Request, experiment_id: int):
    user = require_researcher(request)
    if not user:
        return redirect_login()
    experiment = query_one(
        "SELECT * FROM research_experiments WHERE id = ?",
        (experiment_id,),
    )
    if not experiment:
        return RedirectResponse("/research/experiments", status_code=303)
    runs = query_all(
        """
        SELECT * FROM research_experiment_runs
        WHERE experiment_id = ? ORDER BY run_number DESC
        """,
        (experiment_id,),
    )
    return render(
        request,
        "research/experiment_detail.html",
        {
            "user": user,
            "experiment": experiment,
            "runs": runs,
            "dataset": parse_json(experiment["dataset_selection"], {}),
            "metrics": parse_json(experiment["metrics"], {}),
        },
    )


@app.get("/research/experiments/{experiment_id}/report")
def research_experiment_pdf(request: Request, experiment_id: int):
    user = require_researcher(request)
    if not user:
        return redirect_login()
    content = research_experiment_report(experiment_id)
    if not content:
        return JSONResponse({"detail": "Not found."}, status_code=404)
    return pdf_response(
        content,
        f"sumkora-research-experiment-{experiment_id}-report.pdf",
    )


@app.get("/research/experiments/{experiment_id}/edit", response_class=HTMLResponse)
def research_experiment_edit(request: Request, experiment_id: int):
    user = require_researcher(request)
    if not user:
        return redirect_login()
    experiment = query_one(
        "SELECT * FROM research_experiments WHERE id = ?",
        (experiment_id,),
    )
    if not experiment:
        return RedirectResponse("/research/experiments", status_code=303)
    return render(
        request,
        "research/experiment_form.html",
        {"user": user, "experiment": experiment, "config": config},
    )


@app.post("/research/experiments/{experiment_id}/edit")
def research_experiment_update(
    request: Request,
    experiment_id: int,
    title: str = Form(...),
    research_question: str = Form(""),
    hypothesis: str = Form(""),
    description: str = Form(""),
    status: str = Form("draft"),
    dataset_selection: str = Form("{}"),
    ocr_model: str = Form(""),
    grading_model: str = Form(""),
    diagnosis_model: str = Form(""),
    ocr_prompt_version: str = Form(""),
    grading_prompt_version: str = Form(""),
    confidence_threshold: float = Form(0.70),
    deterministic_checks: str = Form("1"),
    image_resolution: int = Form(200),
    preprocessing_config: str = Form("{}"),
    longitudinal_config: str = Form("{}"),
    evaluation_metrics: str = Form("[]"),
    notes: str = Form(""),
):
    user = require_researcher(request)
    if not user:
        return redirect_login()
    allowed_status = status if status in {
        "draft", "ready", "running", "completed", "failed", "archived"
    } else "draft"
    for raw, fallback in (
        (dataset_selection, "{}"),
        (preprocessing_config, "{}"),
        (longitudinal_config, "{}"),
        (evaluation_metrics, "[]"),
    ):
        try:
            json.loads(raw or fallback)
        except json.JSONDecodeError:
            return RedirectResponse(
                f"/research/experiments/{experiment_id}/edit",
                status_code=303,
            )
    execute(
        """
        UPDATE research_experiments
        SET title = ?, research_question = ?, hypothesis = ?,
            description = ?, status = ?, dataset_selection = ?,
            ocr_model = ?, grading_model = ?, diagnosis_model = ?,
            ocr_prompt_version = ?, grading_prompt_version = ?,
            confidence_threshold = ?, deterministic_checks = ?,
            image_resolution = ?, preprocessing_config = ?,
            longitudinal_config = ?, evaluation_metrics = ?, notes = ?,
            updated_at = ?
        WHERE id = ?
        """,
        (
            title.strip(),
            research_question,
            hypothesis,
            description,
            allowed_status,
            dataset_selection or "{}",
            ocr_model,
            grading_model,
            diagnosis_model,
            ocr_prompt_version,
            grading_prompt_version,
            max(0, min(confidence_threshold, 1)),
            0 if deterministic_checks in {"0", "false", "off"} else 1,
            max(72, min(image_resolution, 400)),
            preprocessing_config or "{}",
            longitudinal_config or "{}",
            evaluation_metrics or "[]",
            notes,
            datetime.now().isoformat(),
            experiment_id,
        ),
    )
    return RedirectResponse(
        f"/research/experiments/{experiment_id}",
        status_code=303,
    )


@app.post("/research/experiments/{experiment_id}/duplicate")
def research_experiment_duplicate(request: Request, experiment_id: int):
    user = require_researcher(request)
    if not user:
        return redirect_login()
    source = query_one(
        "SELECT * FROM research_experiments WHERE id = ?",
        (experiment_id,),
    )
    if not source:
        return RedirectResponse("/research/experiments", status_code=303)
    now = datetime.now().isoformat()
    new_id = execute(
        """
        INSERT INTO research_experiments
        (title, research_question, hypothesis, description, dataset_selection,
         independent_variable, comparison_groups, model_version,
         prompt_version, ocr_model, grading_model, diagnosis_model,
         ocr_prompt_version, grading_prompt_version, confidence_threshold,
         taxonomy_version, calculation_version, deterministic_checks,
         image_resolution, preprocessing_config, longitudinal_config,
         evaluation_metrics, configuration, notes, status, created_by,
         created_at, updated_at)
        SELECT title || ' — copy', research_question, hypothesis, description,
               dataset_selection, independent_variable, comparison_groups,
               model_version, prompt_version, ocr_model, grading_model,
               diagnosis_model, ocr_prompt_version, grading_prompt_version,
               confidence_threshold, taxonomy_version, calculation_version,
               deterministic_checks, image_resolution, preprocessing_config,
               longitudinal_config, evaluation_metrics, configuration, notes,
               'draft', ?, ?, ?
        FROM research_experiments WHERE id = ?
        """,
        (user["id"], now, now, experiment_id),
    )
    return RedirectResponse(f"/research/experiments/{new_id}", status_code=303)


def _experiment_metrics():
    labelled = query_all(
        """
        SELECT aqr.ai_mark, ahc.corrected_mark
        FROM analysis_human_corrections ahc
        JOIN analysis_question_results aqr
          ON aqr.id = ahc.analysis_question_result_id
        UNION ALL
        SELECT cd.awarded_marks, hc.corrected_marks
        FROM human_corrections hc
        JOIN criterion_decisions cd ON cd.id = hc.criterion_decision_id
        """
    )
    sample_size = len(labelled)
    if not sample_size:
        return 0, {
            "sample_size": 0,
            "message": "No human-labelled decisions are available; agreement metrics are not meaningful.",
        }
    errors = [
        float(row["ai_mark"]) - float(row["corrected_mark"])
        for row in labelled
    ]
    metrics = {
        "sample_size": sample_size,
        "exact_mark_agreement": round(
            100 * sum(abs(error) < 1e-9 for error in errors) / sample_size, 1
        ),
        "mean_absolute_error": round(
            sum(abs(error) for error in errors) / sample_size, 3
        ),
        "within_one_mark": round(
            100 * sum(abs(error) <= 1 for error in errors) / sample_size, 1
        ),
        "over_marking_rate": round(
            100 * sum(error > 0 for error in errors) / sample_size, 1
        ),
        "under_marking_rate": round(
            100 * sum(error < 0 for error in errors) / sample_size, 1
        ),
    }
    return sample_size, metrics


@app.post("/research/experiments/{experiment_id}/run")
def research_experiment_run(request: Request, experiment_id: int):
    user = require_researcher(request)
    if not user:
        return redirect_login()
    experiment = query_one(
        "SELECT * FROM research_experiments WHERE id = ?",
        (experiment_id,),
    )
    if not experiment:
        return RedirectResponse("/research/experiments", status_code=303)
    row = query_one(
        """
        SELECT COALESCE(MAX(run_number), 0) + 1 AS number
        FROM research_experiment_runs WHERE experiment_id = ?
        """,
        (experiment_id,),
    )
    sample_size, metrics = _experiment_metrics()
    now = datetime.now().isoformat()
    execute(
        """
        INSERT INTO research_experiment_runs
        (experiment_id, run_number, status, baseline,
         configuration_snapshot, sample_size, metrics, result_summary,
         started_at, finished_at, created_by, created_at)
        VALUES (?, ?, 'completed', ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            experiment_id,
            row["number"],
            1 if row["number"] == 1 else 0,
            json.dumps(dict(experiment), default=str),
            sample_size,
            json.dumps(metrics),
            metrics.get("message", "Evaluation completed against available human labels."),
            now,
            now,
            user["id"],
            now,
        ),
    )
    execute(
        """
        UPDATE research_experiments
        SET status = 'completed', metrics = ?, result = ?,
            last_run_at = ?, updated_at = ?
        WHERE id = ?
        """,
        (
            json.dumps(metrics),
            metrics.get("message", "Run completed."),
            now,
            now,
            experiment_id,
        ),
    )
    return RedirectResponse(
        f"/research/experiments/{experiment_id}",
        status_code=303,
    )


@app.post("/research/experiments/{experiment_id}/archive")
def research_experiment_archive(request: Request, experiment_id: int):
    user = require_researcher(request)
    if not user:
        return redirect_login()
    now = datetime.now().isoformat()
    execute(
        """
        UPDATE research_experiments
        SET status = 'archived', archived_at = ?, updated_at = ?
        WHERE id = ?
        """,
        (now, now, experiment_id),
    )
    return RedirectResponse("/research/experiments", status_code=303)


@app.post("/research/experiments/{experiment_id}/delete")
def research_experiment_delete(request: Request, experiment_id: int):
    user = require_researcher(request)
    if not user:
        return redirect_login()
    execute(
        "DELETE FROM research_experiments WHERE id = ? AND status = 'draft'",
        (experiment_id,),
    )
    return RedirectResponse("/research/experiments", status_code=303)


@app.get("/research/ocr", response_class=HTMLResponse)
def research_ocr_lab(request: Request):
    user = require_researcher(request)
    if not user:
        return redirect_login()
    pages = query_all(
        """
        SELECT aop.*, sp.title AS paper_title, sp.student_id,
               pav.version_number, pav.answer_script_path
        FROM analysis_ocr_pages aop
        JOIN paper_analysis_versions pav ON pav.id = aop.analysis_version_id
        JOIN student_papers sp ON sp.id = pav.paper_id
        ORDER BY aop.created_at DESC LIMIT 100
        """
    )
    return render(
        request,
        "research/ocr.html",
        {"user": user, "pages": pages},
    )


@app.post("/research/ocr/{ocr_page_id}/correct")
def research_correct_ocr(
    request: Request,
    ocr_page_id: int,
    corrected_text: str = Form(...),
    evaluation_label: str = Form(...),
):
    user = require_researcher(request)
    if not user:
        return redirect_login()
    label = evaluation_label if evaluation_label in {
        "correct", "partially_correct", "incorrect"
    } else "partially_correct"
    execute(
        """
        UPDATE analysis_ocr_pages
        SET corrected_text = ?, evaluation_label = ?, corrected_by = ?,
            corrected_at = ?
        WHERE id = ?
        """,
        (
            corrected_text,
            label,
            user["id"],
            datetime.now().isoformat(),
            ocr_page_id,
        ),
    )
    execute(
        """
        INSERT INTO audit_logs
        (actor_id, action, entity_type, entity_id, metadata, created_at)
        VALUES (?, 'ocr_correction', 'analysis_ocr_page', ?, ?, ?)
        """,
        (
            user["id"],
            str(ocr_page_id),
            json.dumps({"evaluation_label": label}),
            datetime.now().isoformat(),
        ),
    )
    return RedirectResponse("/research/ocr", status_code=303)


@app.get("/research/grading", response_class=HTMLResponse)
def research_grading_lab(request: Request):
    user = require_researcher(request)
    if not user:
        return redirect_login()
    results = query_all(
        """
        SELECT aqr.*, sp.title AS paper_title, sp.student_id,
               pav.version_number, pav.answer_script_path,
               (SELECT corrected_mark FROM analysis_human_corrections ahc
                WHERE ahc.analysis_question_result_id = aqr.id
                ORDER BY ahc.id DESC LIMIT 1) AS human_mark,
               (SELECT failure_explanation FROM analysis_human_corrections ahc
                WHERE ahc.analysis_question_result_id = aqr.id
                ORDER BY ahc.id DESC LIMIT 1) AS failure_explanation
        FROM analysis_question_results aqr
        JOIN paper_analysis_versions pav ON pav.id = aqr.analysis_version_id
        JOIN student_papers sp ON sp.id = pav.paper_id
        ORDER BY aqr.created_at DESC LIMIT 150
        """
    )
    return render(
        request,
        "research/grading.html",
        {"user": user, "results": results},
    )


@app.post("/research/grading/{question_result_id}/correct")
def research_correct_direct_grade(
    request: Request,
    question_result_id: int,
    corrected_mark: float = Form(...),
    corrected_decision: str = Form(""),
    error_category: str = Form(""),
    error_mechanism: str = Form(""),
    failure_explanation: str = Form(""),
    alternative_method_should_pass: Optional[str] = Form(None),
    ocr_caused_error: Optional[str] = Form(None),
    parser_caused_error: Optional[str] = Form(None),
):
    user = require_researcher(request)
    if not user:
        return redirect_login()
    result = query_one(
        "SELECT * FROM analysis_question_results WHERE id = ?",
        (question_result_id,),
    )
    if not result:
        return RedirectResponse("/research/grading", status_code=303)
    corrected = max(0.0, min(float(corrected_mark), float(result["maximum_marks"])))
    execute(
        """
        INSERT INTO analysis_human_corrections
        (analysis_question_result_id, corrected_by, original_mark,
         corrected_mark, corrected_decision, error_category, error_mechanism,
         failure_explanation, alternative_method_should_pass,
         ocr_caused_error, parser_caused_error, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            question_result_id,
            user["id"],
            result["ai_mark"],
            corrected,
            corrected_decision,
            error_category or None,
            error_mechanism or None,
            failure_explanation,
            1 if alternative_method_should_pass else 0,
            1 if ocr_caused_error else 0,
            1 if parser_caused_error else 0,
            datetime.now().isoformat(),
        ),
    )
    # The original AI row is immutable; the correction is a separate label.
    return RedirectResponse("/research/grading", status_code=303)


@app.get("/research/failures", response_class=HTMLResponse)
def research_failure_gallery(request: Request, failure_type: str = ""):
    user = require_researcher(request)
    if not user:
        return redirect_login()
    if failure_type:
        cases = query_all(
            """
            SELECT rfc.*, sp.title AS paper_title, aqr.question_label
            FROM research_failure_cases rfc
            LEFT JOIN paper_analysis_versions pav ON pav.id = rfc.analysis_version_id
            LEFT JOIN student_papers sp ON sp.id = pav.paper_id
            LEFT JOIN analysis_question_results aqr ON aqr.id = rfc.question_result_id
            WHERE rfc.failure_type = ?
            ORDER BY rfc.updated_at DESC
            """,
            (failure_type,),
        )
    else:
        cases = query_all(
            """
            SELECT rfc.*, sp.title AS paper_title, aqr.question_label
            FROM research_failure_cases rfc
            LEFT JOIN paper_analysis_versions pav ON pav.id = rfc.analysis_version_id
            LEFT JOIN student_papers sp ON sp.id = pav.paper_id
            LEFT JOIN analysis_question_results aqr ON aqr.id = rfc.question_result_id
            ORDER BY rfc.updated_at DESC
            """
        )
    return render(
        request,
        "research/failures.html",
        {"user": user, "cases": cases, "failure_type": failure_type},
    )


@app.post("/research/failures/{case_id}/update")
def research_failure_update(
    request: Request,
    case_id: int,
    severity: str = Form("medium"),
    status: str = Form("open"),
    tags: str = Form(""),
    notes: str = Form(""),
):
    user = require_researcher(request)
    if not user:
        return redirect_login()
    tag_values = [item.strip() for item in tags.split(",") if item.strip()]
    execute(
        """
        UPDATE research_failure_cases
        SET severity = ?, status = ?, tags = ?, notes = ?, updated_at = ?
        WHERE id = ?
        """,
        (
            severity if severity in {"low", "medium", "high", "critical"} else "medium",
            status if status in {"open", "reviewed", "resolved"} else "open",
            json.dumps(tag_values),
            notes,
            datetime.now().isoformat(),
            case_id,
        ),
    )
    return RedirectResponse("/research/failures", status_code=303)


@app.get("/research/student-models", response_class=HTMLResponse)
def research_student_models(request: Request, student_id: Optional[int] = None):
    user = require_researcher(request)
    if not user:
        return redirect_login()
    students = query_all(
        """
        SELECT id, name, username
        FROM users WHERE role = 'student'
        ORDER BY name
        """
    )
    selected_id = student_id or (students[0]["id"] if students else None)
    observations = query_all(
        """
        SELECT aso.*, sp.title AS paper_title, pav.version_number
        FROM analysis_skill_observations aso
        JOIN student_papers sp ON sp.id = aso.paper_id
        JOIN paper_analysis_versions pav ON pav.id = aso.analysis_version_id
        WHERE aso.student_id = ?
        ORDER BY aso.observed_at DESC
        """,
        (selected_id,),
    ) if selected_id else []
    states = query_all(
        """
        SELECT * FROM student_skill_states
        WHERE student_id = ? ORDER BY current_estimate DESC
        """,
        (selected_id,),
    ) if selected_id else []
    return render(
        request,
        "research/student_models.html",
        {
            "user": user,
            "students": students,
            "selected_id": selected_id,
            "observations": observations,
            "states": states,
        },
    )


@app.post("/research/student-models/{student_id}/rebuild")
def research_rebuild_student_model(request: Request, student_id: int):
    user = require_researcher(request)
    if not user:
        return redirect_login()
    states = rebuild_student_profile(student_id)
    execute(
        """
        INSERT INTO audit_logs
        (actor_id, action, entity_type, entity_id, metadata, created_at)
        VALUES (?, 'profile_rebuild', 'student', ?, ?, ?)
        """,
        (
            user["id"],
            str(student_id),
            json.dumps({"calculation_version": "beta-recency-v1", "states": len(states)}),
            datetime.now().isoformat(),
        ),
    )
    return RedirectResponse(
        f"/research/student-models?student_id={student_id}",
        status_code=303,
    )


@app.get("/research/taxonomy", response_class=HTMLResponse)
def research_taxonomy(request: Request):
    user = require_researcher(request)
    if not user:
        return redirect_login()
    versions = query_all(
        "SELECT * FROM taxonomy_versions ORDER BY created_at DESC"
    )
    return render(
        request,
        "research/taxonomy.html",
        {"user": user, "versions": versions},
    )


@app.post("/research/taxonomy")
def research_create_taxonomy(
    request: Request,
    version: str = Form(...),
    taxonomy: str = Form(...),
    notes: str = Form(""),
):
    user = require_researcher(request)
    if not user:
        return redirect_login()
    try:
        parsed = json.loads(taxonomy)
    except json.JSONDecodeError:
        return RedirectResponse("/research/taxonomy", status_code=303)
    execute(
        """
        INSERT INTO taxonomy_versions
        (version, taxonomy, notes, created_by, created_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            version,
            json.dumps(parsed),
            notes,
            user["id"],
            datetime.now().isoformat(),
        ),
    )
    return RedirectResponse("/research/taxonomy", status_code=303)


@app.get("/research/export")
def research_export(
    request: Request,
    format: str = "jsonl",
    mode: str = "pseudonymized",
    dataset: str = "skill_observations",
):
    user = require_researcher(request)
    if not user:
        return redirect_login()
    queries = {
        "skill_observations": """
            SELECT aso.*, sp.title AS paper_title,
                   pav.version_number AS analysis_version
            FROM analysis_skill_observations aso
            JOIN student_papers sp ON sp.id = aso.paper_id
            JOIN paper_analysis_versions pav ON pav.id = aso.analysis_version_id
            ORDER BY aso.observed_at
        """,
        "ocr_runs": """
            SELECT aop.id, aop.analysis_version_id, aop.document_type,
                   aop.page_number, aop.provider, aop.model,
                   aop.prompt_version, aop.text, aop.normalized_text,
                   aop.confidence, aop.warnings, aop.timing_ms,
                   aop.evaluation_label, aop.corrected_text, aop.created_at,
                   sp.student_id, sp.title AS paper_title
            FROM analysis_ocr_pages aop
            JOIN paper_analysis_versions pav ON pav.id = aop.analysis_version_id
            JOIN student_papers sp ON sp.id = pav.paper_id
            ORDER BY aop.created_at
        """,
        "grading": """
            SELECT aqr.*, sp.student_id, sp.title AS paper_title,
                   pav.version_number
            FROM analysis_question_results aqr
            JOIN paper_analysis_versions pav ON pav.id = aqr.analysis_version_id
            JOIN student_papers sp ON sp.id = pav.paper_id
            ORDER BY aqr.created_at
        """,
        "corrections": """
            SELECT ahc.*, sp.student_id, sp.title AS paper_title
            FROM analysis_human_corrections ahc
            JOIN analysis_question_results aqr
              ON aqr.id = ahc.analysis_question_result_id
            JOIN paper_analysis_versions pav ON pav.id = aqr.analysis_version_id
            JOIN student_papers sp ON sp.id = pav.paper_id
            ORDER BY ahc.created_at
        """,
        "experiments": """
            SELECT id, title, research_question, hypothesis, description,
                   dataset_selection, ocr_model, grading_model,
                   diagnosis_model, ocr_prompt_version,
                   grading_prompt_version, confidence_threshold,
                   deterministic_checks, image_resolution,
                   preprocessing_config, longitudinal_config,
                   evaluation_metrics, metrics, result, notes, status,
                   created_at, updated_at
            FROM research_experiments ORDER BY created_at
        """,
        "experiment_runs": """
            SELECT * FROM research_experiment_runs ORDER BY created_at
        """,
        "failures": """
            SELECT * FROM research_failure_cases ORDER BY created_at
        """,
    }
    dataset = dataset if dataset in queries else "skill_observations"
    rows = query_all(queries[dataset])
    records = []
    for row in rows:
        record = dict(row)
        for key in list(record):
            if key.endswith("_path") or key in {"raw_response", "raw_provider_response"}:
                record.pop(key, None)
        if mode != "identified" and "student_id" in record:
            record["student_id"] = hashlib.sha256(
                f"{config.SECRET_KEY}:{record['student_id']}".encode()
            ).hexdigest()[:16]
        if mode == "anonymized":
            record.pop("student_id", None)
            record.pop("paper_title", None)
            record.pop("corrected_by", None)
            record.pop("created_by", None)
        records.append(record)
    if format == "csv":
        output = io.StringIO()
        fieldnames = list(records[0]) if records else ["student_id"]
        writer = csv.DictWriter(output, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(records)
        content = output.getvalue()
        media_type = "text/csv"
        suffix = "csv"
    elif format == "json":
        content = json.dumps(records, ensure_ascii=False, indent=2)
        media_type = "application/json"
        suffix = "json"
    else:
        content = "\n".join(json.dumps(record, ensure_ascii=False) for record in records)
        media_type = "application/x-ndjson"
        suffix = "jsonl"
    execute(
        """
        INSERT INTO audit_logs (actor_id, action, entity_type, metadata, created_at)
        VALUES (?, 'research_export', 'skill_observation', ?, ?)
        """,
        (
            user["id"],
            json.dumps(
                {
                    "mode": mode,
                    "format": suffix,
                    "rows": len(records),
                    "dataset": dataset,
                }
            ),
            datetime.now().isoformat(),
        ),
    )
    return StreamingResponse(
        iter([content.encode("utf-8")]),
        media_type=media_type,
        headers={
            "Content-Disposition": (
                f'attachment; filename="sumkora-{dataset}-{mode}.{suffix}"'
            )
        },
    )
