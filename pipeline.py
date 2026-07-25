import json
import os
import time
from datetime import datetime, timezone

import fitz

import config
from assessment import sync_submission_evidence
from db import execute, query_all, query_one
from grading import run_grading_job
from ocr import file_hash, run_submission_ocr


PIPELINE_STAGES = [
    "validation",
    "orientation",
    "rendering",
    "ocr",
    "response_mapping",
    "grading",
    "consistency_checks",
    "diagnosis",
    "profile_update",
    "report_generation",
]


def _now():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def create_processing_job(submission_id: int) -> int:
    now = _now()
    return execute(
        """
        INSERT INTO processing_jobs
        (submission_id, status, current_stage, stage_index, created_at, updated_at)
        VALUES (?, 'queued', 'validation', 0, ?, ?)
        """,
        (submission_id, now, now),
    )


def update_job(job_id: int, stage: str, warnings=None):
    index = PIPELINE_STAGES.index(stage) if stage in PIPELINE_STAGES else 0
    execute(
        """
        UPDATE processing_jobs
        SET status = 'processing', current_stage = ?, stage_index = ?,
            warnings = ?, started_at = COALESCE(started_at, ?), updated_at = ?
        WHERE id = ?
        """,
        (
            stage,
            index,
            json.dumps(warnings or [], ensure_ascii=False),
            _now(),
            _now(),
            job_id,
        ),
    )


def _validate_submission(submission):
    if not submission or not os.path.isfile(submission["file_path"]):
        raise RuntimeError("Uploaded file is missing.")
    size = os.path.getsize(submission["file_path"])
    if size <= 0 or size > config.MAX_UPLOAD_BYTES:
        raise RuntimeError("Uploaded file size is outside the permitted range.")
    with fitz.open(submission["file_path"]) as doc:
        if not len(doc):
            raise RuntimeError("Uploaded PDF contains no pages.")
        if len(doc) > 80:
            raise RuntimeError("Uploaded PDF exceeds the 80-page safety limit.")


def _orientation_warnings(path: str):
    warnings = []
    with fitz.open(path) as doc:
        rotations = sorted({page.rotation for page in doc})
    if any(rotation % 360 for rotation in rotations):
        warnings.append(
            "Page rotation metadata detected; rendering normalizes orientation for OCR."
        )
    return warnings


def _validate_totals(submission_id: int):
    rows = query_all(
        """
        SELECT gd.final_mark, q.max_marks
        FROM grade_drafts gd
        JOIN questions q ON q.id = gd.question_id
        WHERE gd.submission_id = ?
        """,
        (submission_id,),
    )
    for row in rows:
        mark = float(row["final_mark"] or 0)
        maximum = float(row["max_marks"] or 0)
        if mark < 0 or mark > maximum:
            raise RuntimeError("A question mark is outside its valid bounds.")


def run_analysis_pipeline(submission_id: int, job_id: int):
    warnings = []
    started = time.monotonic()
    submission = query_one("SELECT * FROM submissions WHERE id = ?", (submission_id,))
    try:
        update_job(job_id, "validation", warnings)
        _validate_submission(submission)
        digest = file_hash(submission["file_path"])
        execute(
            """
            UPDATE submissions
            SET file_hash = ?, processing_started_at = ?
            WHERE id = ?
            """,
            (digest, _now(), submission_id),
        )

        update_job(job_id, "orientation", warnings)
        warnings.extend(_orientation_warnings(submission["file_path"]))

        update_job(job_id, "rendering", warnings)
        with fitz.open(submission["file_path"]) as doc:
            blank_pages = [
                index + 1
                for index, page in enumerate(doc)
                if len(page.get_text().strip()) == 0 and len(page.get_images()) == 0
            ]
        if blank_pages:
            warnings.append(f"Potential blank pages: {blank_pages}")

        update_job(job_id, "ocr", warnings)
        ocr_pages = run_submission_ocr(submission_id, submission["file_path"])
        failed_pages = [page["page_number"] for page in ocr_pages if page["status"] == "failed"]
        if failed_pages:
            warnings.append(f"OCR provider failed on pages {failed_pages}; native text fallback was used.")

        update_job(job_id, "response_mapping", warnings)
        update_job(job_id, "grading", warnings)
        run_grading_job(submission_id)

        update_job(job_id, "consistency_checks", warnings)
        _validate_totals(submission_id)

        update_job(job_id, "diagnosis", warnings)
        evidence = sync_submission_evidence(submission_id)

        update_job(job_id, "profile_update", warnings)
        update_job(job_id, "report_generation", warnings)

        execute(
            """
            UPDATE submissions
            SET processing_finished_at = ?
            WHERE id = ?
            """,
            (_now(), submission_id),
        )
        execute(
            """
            UPDATE processing_jobs
            SET status = 'completed', current_stage = 'completed',
                stage_index = ?, warnings = ?, updated_at = ?, finished_at = ?
            WHERE id = ?
            """,
            (
                len(PIPELINE_STAGES),
                json.dumps(warnings, ensure_ascii=False),
                _now(),
                _now(),
                job_id,
            ),
        )
        return {
            "status": "completed",
            "duration_ms": int((time.monotonic() - started) * 1000),
            **evidence,
        }
    except Exception as exc:
        execute(
            "UPDATE submissions SET status = 'review', processing_finished_at = ? WHERE id = ?",
            (_now(), submission_id),
        )
        execute(
            """
            UPDATE processing_jobs
            SET status = 'failed', failure_message = ?, warnings = ?,
                updated_at = ?, finished_at = ?
            WHERE id = ?
            """,
            (
                str(exc),
                json.dumps(warnings, ensure_ascii=False),
                _now(),
                _now(),
                job_id,
            ),
        )
        return {
            "status": "failed",
            "error": str(exc),
            "duration_ms": int((time.monotonic() - started) * 1000),
        }
