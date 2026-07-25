# IGCSE 0580 Math Tracker - Implementation Changelog

Date: 2026-06-10

Purpose: this document records exactly what was changed during the automatic-grading V1 hardening pass. It is written as a developer handoff, not as marketing copy.

V1 product direction assumed in this pass:

- The product should move toward complete automatic grading.
- Teacher checking is not the normal workflow.
- Teacher intervention is an emergency/exception workflow for dramatically wrong scores.
- Privacy/compliance is deliberately out of scope for V1.
- Score integrity, operational safety, and teacher override correctness are still in scope because they affect whether the system works.

## 1. High-Level Change Summary

The app was shifted from "AI suggests marks and teacher finalizes" toward "AI/OCR auto-finalizes marks and teacher corrects exceptions."

The main behavioral changes are:

1. AI grading now writes `final_mark` directly.
2. AI grading now sets submissions to `final` after grading.
3. Risky automatic marks are not held back from finalization, but they are marked with `risk_flags` and `needs_exception_review`.
4. Teacher manual corrections are stored as explicit overrides and are protected from later AI reruns.
5. Teachers have a new exception queue for high-risk auto-graded rows.
6. Teacher dashboards and assignment pages now expose auto-grading quality signals.
7. Teacher profile reports and analytics are now scoped by teacher where needed.
8. Several route correctness bugs were fixed and regression-tested.
9. API keys and the session secret were moved out of `config.py` into environment variables or local `.env`.
10. A teacher AI calibration page was added so overrides can be measured instead of hidden.
11. Student-facing prediction language was softened to a current-trajectory band.

## 2. Database Changes

File: `db.py`

The `grade_drafts` table was extended with automatic-grading audit and exception fields:

- `risk_flags TEXT NOT NULL DEFAULT ''`
- `needs_exception_review INTEGER NOT NULL DEFAULT 0`
- `auto_finalized_at TEXT`
- `auto_finalize_reason TEXT`
- `teacher_override_mark REAL`
- `teacher_override_comment TEXT`
- `teacher_override_at TEXT`
- `teacher_override_by INTEGER REFERENCES users(id)`

Existing databases are migrated by `init_db()` through `ALTER TABLE` checks. The migration is additive and does not delete existing data.

The `questions` table was also extended with optional metadata fields for later teacher-verified analytics:

- `syllabus_code`
- `subtopic`
- `paper_component`
- `calculator_allowed`
- `source_paper`
- `source_year`
- `question_number`
- `assessment_objective`
- `difficulty_teacher`
- `question_type_tag`
- `mark_structure`
- `requires_method_marks`
- `answer_only_eligible`

Why this matters:

- The app can distinguish ordinary auto-finalized marks from high-risk auto-finalized marks.
- Teacher corrections become explicit, auditable overrides rather than silent edits.
- Later analytics can measure how often AI needed human correction.

## 3. Grading Pipeline Changes

File: `grading.py`

### 3.1 Unified grading result structure

Added `grading_result(...)`.

It standardizes grading output with:

- `ai_mark`
- `ai_confidence`
- `ai_notes`
- `risk_flags`
- `needs_exception_review`
- `auto_finalize_reason`

This prevents exact-answer grading, model grading, fallback grading, and error handling from returning incompatible structures.

### 3.2 Exact-answer checker made more conservative

Changed `exact_answer_grade(...)`.

The previous behavior could over-credit multi-mark mathematics questions when the expected number appeared somewhere in student text. That is unsafe for IGCSE-style marking because a correct number in working does not prove the final answer or method marks are correct.

New behavior:

- One-mark answer-only match can still receive full credit.
- One-mark labelled mismatch receives 0 automatically and does not enter exception review.
- Multi-mark exact text match no longer receives full credit from the shortcut.
- Multi-mark numeric subset match no longer receives full credit from the shortcut.
- Risk flags are emitted for unsafe multi-mark shortcut cases:
  - `unsafe_exact_match_multi_mark`
  - `unsafe_numeric_subset_multi_mark`
- Multi-mark mismatch is routed to exception review because method marks may exist.

Also fixed answer parsing for mark schemes such as `Answer: 5`. The candidate is now cleanly parsed as `5`, not polluted by the label text.

### 3.3 Model and fallback grading now carries risk flags

Qwen/OpenAI/DeepSeek/fallback paths now produce structured risk metadata. Examples include:

- low model confidence
- no OCR text
- model not configured
- model error
- unsafe exact-match shortcut

The system now has a way to separate ordinary automatic scores from scores that should appear in the exception queue.

### 3.4 AI grading auto-finalizes

Changed `run_grading_job(...)`.

New behavior:

- Each graded row writes `ai_mark`.
- Each graded row writes `final_mark = ai_mark`.
- Each graded row writes `risk_flags`.
- Each graded row writes `needs_exception_review`.
- Each graded row writes `auto_finalized_at`.
- Each graded row writes `auto_finalize_reason`.
- The submission status becomes `final` when the grading job completes.

This is the central V1 behavior change.

### 3.5 Teacher overrides survive AI reruns

Changed `run_grading_job(...)`.

If a `grade_drafts` row already has `teacher_override_mark`, the AI rerun skips overwriting it. The code also clears stale exception state from that overridden row:

- `needs_exception_review = 0`
- `risk_flags = ''`

Why this matters:

- A teacher correction is the highest-authority score.
- Re-running AI must not undo an emergency correction.

### 3.6 Existing AI suggestions can be backfilled

Added `backfill_reusable_suggestion(existing)`.

If a row already has a reusable `ai_mark` but lacks automatic-finalization metadata, the system can backfill:

- `final_mark`
- `auto_finalized_at`
- `auto_finalize_reason = 'reused_ai_suggestion'`
- default risk/exception fields

This avoids unnecessary regrading when old rows already contain usable AI output.

## 4. Teacher Route Fixes And Workflow Changes

File: `main.py`

### 4.1 Cross-teacher assignment creation blocked

Changed route:

- `POST /teacher/assignments`
- function: `create_assignment(...)`

The route now checks:

```sql
SELECT id FROM classes WHERE id = ? AND teacher_id = ?
```

before accepting uploaded files or inserting the assignment.

Previous risk:

- Teacher A could submit Teacher B's `class_id` and create an assignment in Teacher B's class.

New behavior:

- If the class does not belong to the logged-in teacher, the request redirects safely and no assignment is created.

### 4.2 Student upload to draft assignment blocked

Changed route:

- `POST /student/assignments/{assignment_id}/upload`
- function: `student_upload(...)`

The enrollment query now requires:

```sql
a.status = 'published'
```

Previous risk:

- A student could upload to a draft assignment if they guessed the assignment ID.

New behavior:

- Uploads are accepted only for published assignments in enrolled classes.

### 4.3 Non-final assessment reports blocked

Changed route:

- `GET /teacher/submissions/{submission_id}/report`
- function: `teacher_submission_report(...)`

New behavior:

- If `submission.status != 'final'`, the route redirects to the review page instead of generating a PDF.

Why this matters:

- Draft or pending marks should not be printed as final reports.

### 4.4 Teacher manual grading now records overrides

Changed route:

- `POST /teacher/submissions/{submission_id}/grade-manual`
- function: `manual_grade(...)`

New behavior:

- The submitted mark is still written to `final_mark`.
- The same mark is also written to `teacher_override_mark`.
- The comment is written to both `teacher_comment` and `teacher_override_comment`.
- Override timestamp and teacher ID are stored.
- `needs_exception_review` is cleared.

Why this matters:

- Teacher intervention becomes auditable.
- The exception queue is cleared when the teacher resolves an item.
- Later AI reruns do not erase the teacher correction.

### 4.5 Teacher dashboard now includes automatic-grading quality metrics

Changed teacher dashboard route and template:

- `GET /teacher`
- `templates/teacher/dashboard.html`

Added counts for:

- auto-finalized rows
- exception rows
- teacher override rows
- average AI confidence for auto-finalized rows

Pending review listings now include exception counts so the teacher sees where attention is needed.

### 4.6 Assignment detail now exposes submission quality signals

Changed assignment detail route and template:

- `GET /teacher/assignments/{assignment_id}`
- `templates/teacher/assignment_detail.html`

Per submission, the page now includes:

- `exception_count`
- `override_count`
- `average_confidence`

This makes assignment-level grading quality visible without opening every submission.

### 4.7 Review page now shows exception metadata

Changed route and template:

- `GET /teacher/submissions/{submission_id}/review`
- `templates/teacher/review.html`

New behavior:

- Parses JSON `risk_flags`.
- Computes `exception_count`.
- Shows automatic-finalization reason.
- Shows risk flags on question cards.
- Shows exception count beside the total score.

Important limitation:

- This page is still structured as a manual review page. It now displays exception metadata, but it is not yet a full exception-first operations console.

### 4.8 Added teacher exception queue

Added route:

- `GET /teacher/exceptions`
- function: `teacher_exceptions(...)`

Added template:

- `templates/teacher/exceptions.html`

Added navigation:

- `templates/base.html`

The page lists all `grade_drafts` rows for the logged-in teacher where:

```sql
gd.needs_exception_review = 1
```

It shows:

- student
- class
- assignment
- question label
- topic
- mark
- risk flags
- AI notes
- question text
- link to review the submission

It also shows quality counters:

- auto-finalized
- exceptions
- overridden
- average confidence

## 5. Analytics Changes

File: `analytics.py`

Teacher scoping was added to student analytics paths.

Updated functions include:

- `finalized_question_rows(student_id=None, teacher_id=None)`
- `student_score_history(student_id, teacher_id=None)`
- `student_difficulty_breakdown(student_id, teacher_id=None)`
- `student_type_breakdown(student_id, teacher_id=None)`
- `student_topic_difficulty_breakdown(student_id, limit=8, teacher_id=None)`
- `student_review_questions(student_id, limit=8, teacher_id=None)`
- `predict_student_score(student_id, teacher_id=None)`
- `student_analytics_summary(student_id, teacher_id=None)`

Why this matters:

- A teacher profile report should not accidentally include a student's work from another teacher's class.
- Teacher analytics should be based on that teacher's classes.

Important limitation:

- The prediction formula is still heuristic and unvalidated. It is scoped more correctly now, but it is not pedagogically strong yet.

## 6. Report Generation Changes

File: `reports.py`

### 6.1 Teacher-scoped profile reports

Updated:

- `student_context(student_id, teacher_id=None)`
- `profile_report(student_id, lang='en', variant='teacher', teacher_id=None)`

Teacher routes now pass `teacher_id` into `profile_report(...)`.

Why this matters:

- A teacher's student profile report is now limited to that teacher's class context and analytics.

### 6.2 Assessment reports include teacher-only grading diagnostics

Updated:

- `assessment_rows(submission_id)`
- `assessment_report(submission_id, lang='en', variant='teacher')`

Teacher-version reports can now include:

- exception review flags
- automatic-finalization reason
- teacher override information
- teacher comments

Why this matters:

- Teacher reports now expose the grading trail.
- Student reports can stay cleaner while teacher reports retain diagnostic evidence.

## 7. Bilingual UI Changes

File: `i18n.py`

Added English and Chinese labels for the new automatic-grading and exception workflow:

- `nav_exceptions`
- `exceptions`
- `exception_queue`
- `automatic_grading_quality`
- `auto_finalized`
- `overridden`
- `average_confidence`
- `exception_count`
- `no_exceptions`
- `exception_review`
- `risk_flags`
- `auto_finalize_reason`

Why this matters:

- The exception workflow is visible in both English and Chinese.
- Teachers using the Chinese interface can still understand the new status fields.

## 8. Templates Changed

Changed:

- `templates/base.html`
- `templates/teacher/dashboard.html`
- `templates/teacher/assignment_detail.html`
- `templates/teacher/review.html`

Added:

- `templates/teacher/exceptions.html`

Summary:

- Teacher navigation includes Exceptions.
- Teacher dashboard includes exception and grading-quality cards.
- Assignment detail includes per-submission exception/override/confidence status.
- Review page shows exception count, auto-finalization reason, and risk flags.
- New exception page groups high-risk automatic marks into one queue.

## 9. Regression Harness Added

File added:

- `scripts/regression_checks.py`

The harness uses:

- a temporary SQLite database
- temporary upload directory
- FastAPI `TestClient`
- generated in-memory PDFs
- AI/OCR disabled unless explicitly needed

It currently tests:

1. Cross-teacher assignment creation is blocked.
2. Student upload to draft assignment is blocked.
3. Multi-mark exact checker does not over-credit.
4. One-mark answer mismatch auto-zeroes without exception review.
5. AI grading auto-finalizes and flags risky rows.
6. Exception queue route shows risky rows.
7. Non-final assessment report is blocked.
8. Teacher override survives normal AI rerun.
9. Teacher override survives forced/stale AI rerun.
10. Reusable old AI suggestions are backfilled with auto-finalization metadata.

Command run:

```bash
python3 scripts/regression_checks.py
```

Latest result:

```text
PASS cross-teacher assignment blocked
PASS draft assignment upload blocked
PASS multi-mark exact check does not over-credit
PASS one-mark mismatch auto-zeroes without exception
PASS auto grading finalizes and flags risky row
PASS exception queue route shows risky rows
PASS non-final assessment report blocked
PASS teacher override survives AI rerun
PASS reusable AI suggestion backfills auto-finalized fields
All regression checks passed.
```

## 10. Additional Verification Performed

Compile check:

```bash
python3 -m compileall main.py db.py grading.py ocr.py analytics.py reports.py i18n.py pdf_utils.py auth.py scripts
```

Result:

- Passed.

Manual/TestClient smoke checks previously performed against core pages:

- `/teacher`
- `/teacher/exceptions`
- `/teacher/analytics`
- `/teacher/classes`
- `/student`
- `/teacher/submissions/12/review`
- `/teacher/submissions/12/report`
- `/teacher/students/7/report`

Database consistency checks previously performed:

- final submissions with null final marks: 0
- override rows still in exception queue: 0
- auto-finalized rows without reason: 0
- exception rows without flags: 0

Browser visual check previously performed:

- Teacher dashboard loaded.
- Exception queue loaded.
- New exception/quality cards rendered without obvious overlap.

## 11. What This Pass Did Not Complete

The following are intentionally not claimed as finished:

1. It did not make AI grading reliable enough to trust without real calibration data.
2. It did not add question-level crop/region OCR.
3. It did not replace the heuristic predicted-score formula.
4. It did not add asynchronous job processing.
5. It did not add upload size/page/pixel limits.
6. It did not remove hardcoded secrets from `config.py`.
7. It did not redesign the review page into a true exception-first grading console.
8. It did not add automatic mark-scheme parsing from Cambridge PDFs.
9. It did not add a teacher-facing calibration dashboard comparing AI marks to teacher overrides.
10. It did not solve production deployment hardening.

Those remaining issues are covered in `docs/remaining_problems_audit_2026_06_10.md`.
