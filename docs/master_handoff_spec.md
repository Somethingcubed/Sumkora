# IGCSE 0580 Math Tracker Master Handoff Spec

This is the canonical handoff and audit document for the current project state.

Use this document when:

- onboarding a new human engineer
- handing the repo to another AI for review or suggestions
- checking whether the current app behavior still matches the intended product
- planning the next round of fixes without rereading the entire codebase first

This document is intentionally detailed. It tries to capture both what the website looks like and how the logic currently works in code.

## 1. Project Identity

Project name:

```text
IGCSE 0580 Math Tracker
```

Purpose:

- teacher-facing assignment, grading, analytics, and printable reporting system for Cambridge IGCSE 0580 Mathematics
- student-facing dashboard for results, strengths, weaknesses, and revision recommendations
- semi-automatic grading, not autonomous final grading

Core value proposition:

- upload handwritten PDF scans
- AI reads the work and suggests marks per question
- teacher reviews and finalizes marks
- analytics and printable reports use finalized marks only

Current strategic stance:

- this is closer to an analytics and tracking platform than a fully automatic marking platform
- teacher confirmation remains the trust boundary
- handwriting OCR is now integrated, but it is still an assistive layer, not a source of truth

## 2. Current Snapshot

Snapshot date:

```text
2026-06-09
```

Current database counts at time of writing:

- users: `6`
- classes: `2`
- assignments: `17`
- questions: `557`
- submissions: `11`
- finalized submissions: `8`
- grade drafts: `108`
- OCR page rows: `2`
- practice questions: `540`

Current seeded and demo users:

- teacher: `teacher@school.edu` / `teacher123`
- student: `student@school.edu` / `student123`
- student: `student2@school.edu` / `student123`
- demo analytics student: `analytics.strong@demo.local` / `student123`
- demo analytics student: `analytics.improving@demo.local` / `student123`
- demo analytics student: `analytics.support@demo.local` / `student123`

Current classes:

- seeded teacher class: `0580 Extended - Set A`
- analytics demo class: `Analytics Demo Class`

Current content coverage:

- past papers ingested from Oct/Nov 2025 only
- ingest source folder: `Past Papers/`
- one known bad file remains: `0580_w25_gt.pdf` at `0 KB`

Current AI path:

- default provider path is now `CXSee + Qwen3-VL`
- OCR provider default is `cxsee_vl`
- grading provider default is `cxsee_qwen`
- exact-answer matching is still used before or alongside model grading

## 3. Tech Stack

Backend:

- Python
- FastAPI
- SQLite
- Jinja2 templates

PDF and document processing:

- PyMuPDF (`fitz`) for PDF validation, text extraction, page rendering
- ReportLab for printable PDF reports

Auth:

- session-cookie based
- `itsdangerous`
- `bcrypt` password hashing

Frontend:

- server-rendered HTML templates
- Tailwind via CDN
- small local stylesheet in `static/style.css`
- MathJax enabled globally in `templates/base.html`

No frontend build system:

- no npm
- no React
- no bundler
- no client-side state framework

## 4. Design Language And UI Conventions

Overall visual style:

- light theme only
- `bg-slate-50` page background
- indigo primary color
- white cards with soft shadow
- restrained school/admin-tool aesthetic, not a marketing site

Navigation:

- top nav bar is `bg-indigo-700`
- app title at left
- language toggle and role-specific nav links at right
- teacher sees dashboard, classes, analytics
- student sees my dashboard

Cards:

- shared `.card` style in `static/style.css`
- white background
- `0.75rem` border radius
- light box shadow
- default padding `1.25rem`

Badges:

- status displayed through `.badge` classes
- pending: amber
- grading: blue
- review: pink
- final/published: green
- draft: slate

Confidence text colors:

- low: amber
- mid: blue
- high: green

Typography:

- Tailwind defaults plus system/browser defaults
- no custom font family
- math content uses `.math-copy` with increased line-height

Login page:

- centered single card
- white card on slate background
- indigo title and button
- language toggle in upper-right of card
- demo credentials shown below form

Known design limitations:

- visual system is consistent but still basic
- no icon library
- no advanced empty states
- no responsive custom behavior beyond Tailwind layout classes
- some review and analytics pages are dense and still somewhat utilitarian

## 5. File And Module Map

Primary app modules:

- [main.py](/Users/oscar/Desktop/IGCSE%20Math%20AnAn/main.py)
- [db.py](/Users/oscar/Desktop/IGCSE%20Math%20AnAn/db.py)
- [grading.py](/Users/oscar/Desktop/IGCSE%20Math%20AnAn/grading.py)
- [ocr.py](/Users/oscar/Desktop/IGCSE%20Math%20AnAn/ocr.py)
- [analytics.py](/Users/oscar/Desktop/IGCSE%20Math%20AnAn/analytics.py)
- [reports.py](/Users/oscar/Desktop/IGCSE%20Math%20AnAn/reports.py)
- [pdf_utils.py](/Users/oscar/Desktop/IGCSE%20Math%20AnAn/pdf_utils.py)
- [i18n.py](/Users/oscar/Desktop/IGCSE%20Math%20AnAn/i18n.py)
- [auth.py](/Users/oscar/Desktop/IGCSE%20Math%20AnAn/auth.py)
- [config.py](/Users/oscar/Desktop/IGCSE%20Math%20AnAn/config.py)

Templates:

- `templates/base.html`
- `templates/login.html`
- `templates/teacher/*.html`
- `templates/student/*.html`

Scripts:

- `scripts/ingest.py`
- `scripts/demo_flow.py`
- `scripts/analytics_demo.py`
- `scripts/real_data_checklist.py`

Reference docs:

- this file
- `docs/analytics_test_harness.md`

## 6. Configuration And Secrets

Current convention:

- configuration is read by `config.py`
- environment variables and a local `.env` file are supported
- `.env` is ignored by git
- `.env.example` contains reusable placeholders

Important config fields:

```text
AI_PROVIDER=cxsee_qwen
OCR_PROVIDER=cxsee_vl
OCR_ENABLED=true
OCR_RENDER_DPI=200

CXSEE_API_KEY=replace-with-your-cxsee-key
CXSEE_BASE_URL=https://api.cxsee.com/v1
CXSEE_OCR_MODEL=qwen3-vl-plus
CXSEE_MARKING_MODEL=qwen3-vl-plus

DEEPSEEK_API_KEY=
OPENAI_API_KEY=

DB_PATH=data/app.db
UPLOAD_DIR=data/uploads
SECRET_KEY=replace-with-a-long-random-secret
```

Important security note:

- real secrets must not be committed
- the previously exposed CXSee key should be rotated before real student data is used
- if `SECRET_KEY` is missing, the app generates a temporary local secret and prints a warning
- if a selected provider key is missing, grading fails closed and flags the row instead of silently trusting a score

Current provider strategy:

- default: Qwen via CXSee for both OCR and grading
- optional fallback providers remain in code:
  - Google Vision OCR
  - Mathpix OCR
  - OpenAI vision grading
  - DeepSeek text grading

## 7. Database Model And Invariants

Tables:

### `users`

- `id`
- `email` unique
- `password_hash`
- `name`
- `role` in `teacher | student`

### `classes`

- `id`
- `name`
- `teacher_id`

### `class_enrollments`

- `(class_id, student_id)` primary key

### `assignments`

- `id`
- `class_id`
- `title`
- `type` in `past_paper | worksheet | practice`
- `due_date`
- `total_marks`
- `status` in `draft | published`
- `question_paper_path`
- `mark_scheme_path`
- `created_at`

### `questions`

- `id`
- `assignment_id`
- `label`
- `topic`
- `question_text`
- `max_marks`
- `mark_scheme_text`
- `page_number`
- `order_index`

### `submissions`

- `id`
- `assignment_id`
- `student_id`
- `file_path`
- `status` in `pending | grading | review | final`
- `uploaded_at`
- unique `(assignment_id, student_id)`

### `grade_drafts`

- `id`
- `submission_id`
- `question_id`
- `ai_mark`
- `ai_confidence`
- `ai_notes`
- `final_mark`
- `teacher_comment`
- unique `(submission_id, question_id)`

### `ocr_pages`

- `id`
- `submission_id`
- `page_number`
- `provider`
- `file_hash`
- `text`
- `confidence`
- `status` in `pending | done | failed | skipped`
- `error`
- `created_at`
- `updated_at`
- unique `(submission_id, page_number, provider)`

### `practice_questions`

- `id`
- `topic`
- `label`
- `text`
- `source`

Key invariants:

- one submission per assignment per student
- one grade draft per question per submission
- analytics trust `final_mark`, not OCR, not `ai_mark`
- OCR cache is keyed by submission + page + provider + current PDF hash
- replacing a PDF resets grade drafts and OCR cache for that submission

## 8. Auth And Permissions

Auth model:

- session cookie
- login redirects teachers to `/teacher`
- login redirects students to `/student`

Permission shape:

- teacher routes validate teacher role and ownership via class/assignment joins
- student routes validate student role and only their own assignments/results
- teacher PDF/report routes are ownership checked
- student PDF/report routes are self-only

Important trust model:

- teacher is trusted to review and finalize marks
- student cannot mutate finalized teacher analytics directly
- uploaded files are restricted to PDF content by server-side validation

## 9. Route Inventory

Language:

- `GET /lang/{lang_code}`

Auth:

- `GET /`
- `GET /login`
- `POST /login`
- `GET /logout`

Teacher pages:

- `GET /teacher`
- `GET /teacher/classes`
- `GET /teacher/classes/{class_id}`
- `POST /teacher/classes`
- `POST /teacher/classes/{class_id}/enroll`
- `GET /teacher/assignments/new`
- `POST /teacher/assignments`
- `GET /teacher/assignments/{assignment_id}`
- `POST /teacher/assignments/{assignment_id}/questions`
- `POST /teacher/assignments/{assignment_id}/publish`
- `POST /teacher/assignments/{assignment_id}/upload`
- `POST /teacher/submissions/{submission_id}/grade-manual`
- `POST /teacher/submissions/{submission_id}/ai-grade`
- `GET /teacher/submissions/{submission_id}/file`
- `GET /teacher/submissions/{submission_id}/review`
- `POST /teacher/submissions/{submission_id}/finalize`
- `GET /teacher/analytics`

Teacher PDF routes:

- `GET /teacher/students/{student_id}/report`
- `GET /teacher/submissions/{submission_id}/report`

Student pages:

- `GET /student`
- `GET /student/report`
- `GET /student/assignments/{assignment_id}`
- `POST /student/assignments/{assignment_id}/upload`
- `GET /student/results/{submission_id}`
- `GET /student/results/{submission_id}/report`

## 10. End-To-End Product Workflows

### 10.1 Teacher creates and publishes an assignment

Flow:

1. teacher opens `/teacher/assignments/new`
2. enters title, class, type, due date
3. optional question paper PDF and mark scheme PDF can be uploaded
4. assignment is created in `draft`
5. teacher opens assignment detail page
6. teacher manually adds questions
7. teacher clicks publish

Assignment detail behavior:

- left column: question list and add-question form
- right column: submission upload area and submission list

### 10.2 Student uploads work

Flow:

1. student opens `/student/assignments/{id}`
2. sees questions and upload form
3. uploads a PDF
4. existing submission is replaced if it already exists
5. status becomes `pending`
6. grade rows are ensured
7. OCR cache is cleared if replacing an existing PDF

Validation:

- file must start with `%PDF`
- file must open via PyMuPDF

### 10.3 Teacher bulk uploads work

Flow:

1. teacher opens assignment detail
2. uploads one or more PDFs
3. may explicitly select one student, or leave blank to auto-match by filename
4. server tries to match lowercase filename stem against student name or email
5. only enrolled students are accepted
6. replacing a submission resets AI/final marks and OCR cache

### 10.4 Teacher AI grading

Flow:

1. teacher clicks `AI grade`
2. submission status changes to `grading`
3. OCR runs page by page through the configured provider
4. OCR output is cached in `ocr_pages`
5. each question is graded
6. grade drafts are updated with `ai_mark`, `ai_confidence`, `ai_notes`
7. status becomes `review`

Teacher review is always expected after this.

### 10.5 Teacher manual review and finalize

Flow:

1. teacher opens submission review page
2. sees score summary, uploaded work preview, OCR diagnostics, OCR text, AI notes, and manual mark inputs
3. teacher edits final marks and optional comments
4. teacher clicks finalize
5. any `final_mark is NULL` rows inherit `ai_mark`
6. submission status becomes `final`
7. analytics and printable reports begin using these marks

## 11. Current Teacher UI, Page By Page

### 11.1 `/teacher`

Purpose:

- teacher landing dashboard

Visible sections:

- page title
- AI mode summary line
- three metric cards:
  - classes
  - assignments
  - awaiting review
- two primary buttons:
  - new assignment
  - manage classes
- optional pending review list
- assignments table

Behavior notes:

- `ai_mode` text is derived from config
- current intended label is `CXSee Qwen3-VL handwriting OCR + grading`

### 11.2 `/teacher/classes`

Purpose:

- class creation and student enrollment

Visible sections:

- create class form
- card per class
- each class card shows student count
- each class card includes `Printable reports` link
- each class card contains a student enrollment form

Behavior notes:

- enrollment uses a dropdown of all student users not filtered by class
- duplicate enrollment is prevented by table primary key

### 11.3 `/teacher/classes/{class_id}`

Purpose:

- printable report hub for one class

Visible sections:

- student profile reports table
- assessment reports list
- back to classes link

Download variants:

- teacher profile PDF
- student profile PDF
- teacher assessment PDF
- student assessment PDF

### 11.4 `/teacher/assignments/new`

Purpose:

- create assignment metadata shell

Visible fields:

- title
- class
- type
- due date
- question paper PDF
- mark scheme PDF

Notes:

- uploaded question paper/mark scheme files are metadata attachments, not automatic grading logic by themselves

### 11.5 `/teacher/assignments/{assignment_id}`

Purpose:

- assignment authoring and submission management

Layout:

- two-column layout on large screens
- left: question list and add-question form
- right: bulk upload and submissions list

Question creation fields:

- label
- topic
- max marks
- page number
- question text
- mark scheme text

Submission list actions:

- AI grade
- review
- teacher PDF if final
- student PDF if final

### 11.6 `/teacher/submissions/{submission_id}/review`

Purpose:

- main teacher grading review surface

Top area:

- student name
- assignment title
- current total score
- submission status
- finalize button if not final
- report download buttons if final

Submitted work section:

- `Open full PDF` link
- embedded PDF object
- fallback message if browser cannot embed PDF
- rendered page preview images below embed/fallback

OCR diagnostics section:

- OCR provider label
- page number
- OCR status
- OCR confidence
- OCR error
- OCR extracted text shown directly in diagnostics

Per-question card:

- question label
- localized topic
- max marks
- question text
- mark scheme text
- AI confidence if present
- AI suggestion box with notes
- OCR extracted text reference for that question page
- final mark input
- teacher comment input
- save button

Known UX improvements already made:

- OCR text is visible in the diagnostics block, not only deep inside question cards
- page thumbnails are shown because browsers sometimes leave the PDF embed blank

Known remaining UX limitations:

- OCR text repeats in every question that shares the same page
- no question-specific OCR crop
- no inline edit-and-rerun OCR box
- no side-by-side synchronized page/question highlighting

### 11.7 `/teacher/analytics`

Purpose:

- teacher class and student analytics overview

Sections:

- classes overview cards
- students needing support table
- topics to reteach card
- all student performance table
- difficulty performance
- question-type performance
- topic performance table

Behavior notes:

- analytics are aggregated across all classes owned by the logged-in teacher
- support list is intentionally a subset, not all students

## 12. Current Student UI, Page By Page

### 12.1 `/student`

Purpose:

- student dashboard

Summary cards:

- latest score
- average score
- predicted score
- revise next

Other sections:

- prediction note
- score history
- topic mastery
- review questions
- difficulty performance
- question-type performance
- topic + difficulty
- recommended practice
- assignments list
- profile PDF download button

Behavior notes:

- color coding is red/amber/green based on accuracy thresholds
- score history displays progress bars per assessment

### 12.2 `/student/assignments/{assignment_id}`

Purpose:

- question viewing and submission upload

Sections:

- question list
- upload form
- existing submission status if present

Behavior notes:

- student can replace their submission
- only one submission record exists per assignment

### 12.3 `/student/results/{submission_id}`

Purpose:

- finalized result view

Visible sections:

- total earned / total possible
- assessment PDF download button
- question breakdown
- practice next

Behavior notes:

- only finalized marks show here
- teacher comments display if present

## 13. OCR Logic

Primary implementation files:

- [ocr.py](/Users/oscar/Desktop/IGCSE%20Math%20AnAn/ocr.py)
- [pdf_utils.py](/Users/oscar/Desktop/IGCSE%20Math%20AnAn/pdf_utils.py)

Current default OCR provider:

```text
cxsee_vl
```

Current OCR model:

```text
qwen3-vl-plus
```

OCR process:

1. hash submission file contents with SHA-256
2. count PDF pages
3. render each page to PNG base64 using PyMuPDF
4. call provider OCR
5. save result in `ocr_pages`

Current provider implementations:

- `cxsee_vl_ocr`
- `google_vision_ocr`
- `mathpix_ocr`

Current CXSee OCR prompt behavior:

- asks model to OCR the image only
- preserve question labels
- preserve line breaks
- preserve equations and units
- do not solve or mark

Cache reuse rule:

- reuse OCR only if every page for the current file hash is `done`
- failed/skipped rows do not block later retries

Current OCR limitations:

- OCR is page-level, not question-crop-level
- OCR confidence is not currently available from CXSee path, so it stores `None`
- OCR output is plain text, not structured JSON
- no bounding boxes or token-level layout information

## 14. Grading Logic

Primary implementation file:

- [grading.py](/Users/oscar/Desktop/IGCSE%20Math%20AnAn/grading.py)

Current grading priority:

1. exact-answer / numeric matching from extracted text
2. Qwen3-VL direct vision grading if exact match is insufficient
3. teacher review

Legacy/optional paths still present:

- DeepSeek text grading
- OpenAI vision grading
- generic review fallback when no model is usable

### 14.1 Exact answer grading

Core idea:

- mine likely answer tokens from `mark_scheme_text`
- normalize unicode math characters
- search extracted student text for answer match

Important normalizations:

- unicode minus/dash variants to `-`
- `×` to `x`
- `÷` to `/`
- `π` to `pi`
- superscript 2/3 to plain `2`/`3`

Current extracted-answer heuristics:

- parse candidate answers from mark-scheme text
- attempt compact-text match
- attempt numeric subset match
- if a clearly labeled response exists but does not match, assign `0` with review note

Important limitation:

- exact checker is helpful for low-mark answer-only items but can still over-credit some multi-part or numerically ambiguous answers

### 14.2 Qwen vision grading

Function:

```text
cxsee_qwen_vision_grade()
```

Inputs:

- question label
- question text
- max marks
- mark scheme text
- OCR text if available
- page image as base64

Prompt constraints:

- return JSON only
- mark within `[0, max_marks]`
- award method marks only if visible work supports them
- return `0` for blank, unrelated, unreadable, or unmatched work
- do not reward answers merely present in prompt/mark scheme

Expected output keys:

- `ai_mark`
- `ai_confidence`
- `ai_notes`

### 14.3 Reuse rule for AI suggestions

The grading job skips recalculating a question if:

- `ai_mark` already exists
- `ai_notes` exists
- `ai_notes` does not contain failure markers

Current failure markers:

- `failed`
- `not configured`
- `no readable text`
- `could not find`
- `did not run`

Meaning:

- a previous useful AI suggestion is reused to save cost
- bad or incomplete AI attempts are allowed to retry

### 14.4 Finalize logic

When teacher finalizes:

- if `final_mark` is `NULL` and `ai_mark` exists, copy `ai_mark` into `final_mark`
- submission status becomes `final`

Analytics and reports depend on this finalized state.

## 15. Analytics Logic

Primary implementation file:

- [analytics.py](/Users/oscar/Desktop/IGCSE%20Math%20AnAn/analytics.py)

Analytics trust boundary:

- only finalized submissions
- only non-null `final_mark`

### 15.1 Difficulty heuristic

Current rule:

- `1-2` marks = `easy`
- `3-4` marks = `medium`
- `5+` marks = `hard`
- if assignment title matches `Paper 3` or `Paper 4`, difficulty is bumped up by one level, capped at `hard`

### 15.2 Question type heuristic

Question types are inferred by keyword rules over:

- question text
- mark scheme text
- topic

Current type labels:

- `number`
- `solve_equation`
- `expand_factorise`
- `graph_sketch`
- `trigonometry`
- `angle_geometry`
- `probability`
- `statistics`
- `sequences`
- `mensuration`
- fallback: `mixed_skill`

### 15.3 Student summary outputs

`student_analytics_summary(student_id)` returns:

- latest score
- average score
- strongest topic
- weakest topic
- prediction block
- score history
- difficulty breakdown
- type breakdown
- topic+difficulty breakdown
- review questions

### 15.4 Prediction formula

Current logic:

- use last up to 4 finalized assessments
- apply weights `1..n` to favor recent assessments
- weak topic+difficulty area can penalize prediction:
  - accuracy < 50: penalty `4`
  - accuracy < 65: penalty `2`
- trend adjustment:
  - if last score improved by `>= 5`: `+2`
  - if declined by `<= -5`: `-2`
- confidence:
  - 4+ assessments: `high`
  - 2-3 assessments: `medium`
  - 1 assessment: `low`

### 15.5 Review queue rule

`student_review_questions()` includes finalized question rows with:

- question accuracy below `60%`

Sorted by:

- lower accuracy first
- earlier date first

### 15.6 Teacher analytics

`teacher_analytics_summary(teacher_id)` returns:

- all students sorted by descending accuracy
- support students sorted from weakest upward
- topic aggregates
- difficulty aggregates
- question-type aggregates

Support-student filter:

- accuracy < `60`
- or trend declining and accuracy < `75`

## 16. Printable Report Logic

Primary implementation file:

- [reports.py](/Users/oscar/Desktop/IGCSE%20Math%20AnAn/reports.py)

Current report types:

- student profile report
- assessment report

Current report variants:

- teacher variant
- student variant

Rendering:

- ReportLab
- in-memory `BytesIO`
- A4
- footer with page number
- Chinese support via `STSong-Light`

Profile report includes:

- latest score
- average score
- predicted score
- trend
- score history
- topic mastery table
- review questions
- suggested practice
- teacher diagnostics section for teacher variant

Assessment report includes:

- student/class/assignment summary
- total score
- what went well
- what needs work
- question breakdown
- suggested practice
- teacher diagnostics comments if teacher variant

Current content-cleaning behavior:

- strips many LaTeX wrappers into plain text
- removes `MS:` answer content from suggested-practice export

## 17. Ingest Logic

Primary implementation file:

- `scripts/ingest.py`

Purpose:

- parse Cambridge paper and mark scheme PDFs from `Past Papers/`
- create assignments
- create questions
- create practice bank entries

Known behavior:

- filename parsing is heuristic
- question extraction is heuristic
- mark-scheme extraction is heuristic
- invalid/zero-byte PDFs are skipped
- already-ingested assignments are not duplicated by title

Current caveat:

- ingest quality is good enough for demoing, not yet trustworthy enough for unattended publishing without review

## 18. Scripts And Intended Use

### `scripts/demo_flow.py`

Purpose:

- tiny end-to-end grading smoke test using a generated sample PDF

Behavior:

- inserts or replaces one demo submission
- ensures grade rows
- runs grading job
- finalizes submission

### `scripts/analytics_demo.py`

Purpose:

- rebuild isolated demo analytics dataset

Behavior:

- deletes and recreates `Analytics Demo Class`
- creates three synthetic students
- creates three assignments
- inserts finalized marks directly
- generates upload PDFs

Expected demo student patterns:

- Maya Strong: strong
- Leo Improving: improving
- Nina Support: struggling

### `scripts/real_data_checklist.py`

Purpose:

- validate a future real-submission folder before import

Checks:

- missing roster
- missing assignments CSV
- missing submissions folder
- invalid PDFs
- duplicate students/emails
- PDF/student mismatch
- missing student PDFs

## 19. Operational Reality And Known Risks

Important truths for a reviewer or next AI:

- this project has evolved quickly and some docs previously lagged behind code
- provider strategy changed from mock/OpenAI/DeepSeek thinking toward CXSee Qwen-first
- current README before this rewrite was partially stale

Important current risks:

- secrets in `config.py`
- SQLite is fine for single-user/local, weak for concurrent production use
- OCR is page-level, not question-level
- some AI grading notes may sound more confident than the actual evidence deserves
- exact-answer heuristics can overfit to numeric overlap
- the current review UI shows the same OCR page text in multiple question cards when many questions share a page
- the app still trusts teacher finalization rather than robust model confidence gating
- printable reports are serviceable but not deeply polished
- no automated test suite exists beyond ad hoc compile checks and smoke tests

Current known UX oddities:

- browser PDF embeds can be blank, which is why page thumbnails were added
- OCR confidence is blank for CXSee because the current path does not expose a confidence score
- student recommendations are rule-based, not personalized by semantic similarity

## 20. What Another AI Should Review

If handing this repo to another AI for critique, ask it to review these specific areas:

1. Grading correctness:
   Can the exact-answer and Qwen3-VL grading path incorrectly award marks for unrelated or partially matching answers?

2. OCR granularity:
   Should OCR be segmented by question crop rather than reused whole-page text for every question on that page?

3. Analytics soundness:
   Are prediction, support-student ranking, and review queue heuristics pedagogically reasonable and internally consistent?

4. Report quality:
   Are teacher and student PDFs sufficiently differentiated and readable for actual school use?

5. Security and deployment:
   What must change before any production or school deployment?

6. Data integrity:
   Are there route or state transitions that can leave submissions, OCR cache, or grade rows inconsistent?

7. UX:
   Which teacher and student pages still create confusion, especially during grading review?

## 21. Suggested External AI Review Prompt

Use something close to this:

```text
Read the entire project and the master handoff spec first.

Your job is to audit the app harshly but constructively.
Focus on:
- grading correctness
- OCR logic
- analytics correctness
- UI/UX confusion points
- report usefulness
- security and deployment risks
- stale documentation or mismatches between docs and code

Do not redesign from scratch.
Review the current implementation as it exists.
List:
1. critical bugs or logic flaws
2. medium-priority quality issues
3. documentation mismatches
4. recommended next changes in implementation order

When possible, cite exact files and functions.
```

## 22. Non-Goals For The Next Reviewer

The next reviewer should not assume:

- full production hardening already exists
- handwriting grading is meant to be fully autonomous
- OCR output is the source of truth
- the UI is intended to be a final polished school-facing product
- the current provider mix is permanent

The next reviewer should assume:

- teacher-reviewed final marks are the authoritative data layer
- the product is local-first and still evolving
- speed of iteration has mattered more than architecture purity
- preserving current working flows is more important than proposing a total rewrite

## 23. Document Ownership

If the implementation changes materially, update this document first or alongside the code, especially when any of these change:

- provider strategy
- OCR workflow
- grading trust boundary
- analytics formulas
- route inventory
- database schema
- printable report behavior
- demo/test harness assumptions
