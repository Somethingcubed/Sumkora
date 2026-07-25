# IGCSE 0580 Math Tracker - Project Changelog

This document records the practical project history: what changed, why it changed, what bugs or design problems were found, and how each pass made the system better.

It is intentionally specific. It should help a future developer or AI reviewer understand how the product moved from a simple grading tracker into an automatic-grading and analytics prototype.

## Current Product Direction

As of 2026-06-12, the intended V1 direction is:

- automatic AI/OCR grading is the normal workflow;
- grades are finalized automatically after grading;
- teacher review is an emergency correction path, not the default marking workflow;
- teacher overrides are the highest-authority score;
- analytics and reports trust finalized marks;
- privacy/compliance is not a V1 priority, but score integrity, upload reliability, API key safety, route ownership, and database consistency are still in scope.

## 2026-06-07 - Initial App Build And Core Workflow

### What Was Built

- Created the FastAPI + SQLite + Jinja2 web app structure.
- Added teacher and student login.
- Added basic seeded demo accounts:
  - `teacher@school.edu / teacher123`
  - `student@school.edu / student123`
- Added teacher class management.
- Added assignments with question entry.
- Added PDF upload from teacher side and student side.
- Added a teacher grading/review page.
- Added student result pages.
- Added basic English/Chinese UI switching through `i18n.py`.

### Why It Helped

- Established the first end-to-end classroom loop:
  1. teacher creates assignment;
  2. student uploads PDF;
  3. AI/teacher marks questions;
  4. student sees results.
- Proved the local-first FastAPI + SQLite architecture could support the product quickly without a heavy frontend stack.

### Bugs And Problems Found

- The original workflow still assumed teacher-reviewed grading as the trust boundary.
- AI marks were treated more like suggestions than a fully operational automatic marking pipeline.
- The review page could show the teacher the marks, but not always enough evidence about what the student actually wrote.
- PDF embedding in browser could appear blank on some local/browser combinations.

## 2026-06-07 - Past Paper Ingest And Question Bank Direction

### What Was Built

- Added `scripts/ingest.py`.
- Implemented ingest from the local `Past Papers/` folder.
- Ingested the Oct/Nov 2025 Cambridge 0580 session.
- Created roughly 12 assignments and around 335 questions from those papers.
- Added practice-question data so analytics could recommend revision.

### Why It Helped

- Moved the product away from only hand-entered toy assignments.
- Gave the app a realistic Cambridge IGCSE 0580 content base.
- Made topic analytics and practice recommendation screens feel closer to actual classroom use.

### Bugs And Problems Found

- Some ingested question text was weirdly formatted because PDF extraction is not clean LaTeX.
- The extracted questions were not always teacher-ready.
- Imported questions still needed review before real publication.
- Mark-scheme parsing was good enough for demos, not for unattended grading.

## 2026-06-07 - Student Analytics Roadmap And First Analytics Build

### What Was Built

- Added student dashboard analytics:
  - latest score;
  - average score;
  - score history;
  - topic mastery;
  - strongest topic;
  - weakest/revision topic;
  - recommended practice.
- Added difficulty tracking:
  - easy = 1-2 marks;
  - medium = 3-4 marks;
  - hard = 5+ marks;
  - Paper 3/4 style questions treated slightly harder in heuristic paths.
- Added question-type tracking with keyword rules:
  - solve equation;
  - expand/factorise;
  - graph/sketch;
  - angle geometry;
  - trigonometry;
  - probability;
  - statistics;
  - sequences;
  - mensuration.
- Added a review queue of low-scoring questions.
- Added a predicted-score style calculation.
- Added teacher analytics:
  - class score overview;
  - students needing support;
  - weak topics;
  - difficulty and question-type breakdowns.

### Why It Helped

- Shifted the product from "marking website" toward "analytics tracking website."
- Made finalized marks useful after grading.
- Gave students and teachers a reason to return after a submission is marked.
- Made the system less dependent on students actively using the site by preparing later printable report work.

### Bugs And Problems Found

- The initial demo data did not clearly show one strong, one improving, and one weak student.
- The predicted-score output was too exact and not pedagogically safe.
- Difficulty and question type were heuristic rather than teacher-verified.
- Practice recommendations were too broad: mostly topic-matched, not misconception-matched.

## 2026-06-07 - Reusable Analytics Demo Harness

### What Was Built

- Added `docs/analytics_test_harness.md`.
- Added `scripts/analytics_demo.py`.
- Created reusable synthetic students.
- Generated synthetic PDF submissions.
- Inserted finalized marks directly so analytics could be tested without OCR/API dependencies.
- Added `scripts/real_data_checklist.py` for later real handwritten batches.

### Why It Helped

- Made analytics testing repeatable.
- Removed the need to manually recreate test students and assignments.
- Created a safe path for next-week real PDF intake:
  - roster CSV;
  - assignments CSV;
  - submissions folder;
  - pre-import validation.

### Bugs And Problems Found

- The first harness version only created three assignments.
- It still included geometry and graphs, which made the scenario less focused for text-only analytics testing.
- It reset only demo-tagged data, which was safe but not what was later requested for a full local cleanup.

## 2026-06-07 - Printable PDF Reports

### What Was Built

- Added ReportLab PDF generation in `reports.py`.
- Added student profile reports.
- Added assessment-specific reports.
- Added teacher and student report variants.
- Added teacher class detail page:
  - `/teacher/classes/{class_id}`;
  - student report links;
  - finalized assessment report links.
- Added student-side report buttons:
  - `/student/report`;
  - `/student/results/{submission_id}/report`.
- Added teacher-side report buttons for student and assessment reports.

### Why It Helped

- Addressed the fact that many students may not use the website.
- Let teachers print/share a student progress profile.
- Made the system useful for meetings, parent communication, and offline revision.

### Bugs And Problems Found

- Report navigation was not obvious at first; the teacher needed a clearer route through class detail pages.
- Student reports initially included unvalidated predicted score information.
- Teacher reports needed more diagnostic information than student reports.
- Reports were serviceable but not yet polished as printable action plans.

## 2026-06-07 - OCR And China-Compatible Model Direction

### What Was Built

- Investigated China-compatible model providers and the CXSee endpoint.
- Switched the default planned provider path toward CXSee/Qwen3-VL.
- Added provider configuration for:
  - CXSee Qwen3-VL OCR;
  - CXSee Qwen3-VL marking;
  - DeepSeek-style text grading fallback;
  - Google Vision and Mathpix as possible OCR alternatives.
- Added OCR page cache table `ocr_pages`.
- Added OCR diagnostics on teacher review pages:
  - provider;
  - page number;
  - status;
  - confidence where available;
  - error;
  - extracted text.
- Added PDF page thumbnail previews because embedded PDFs could appear blank.

### Why It Helped

- Made the system closer to the real input format: handwritten scanned PDFs.
- Kept the V1 provider path more China-compatible.
- Reduced confusion when the PDF embed area was blank by showing rendered page previews.
- Gave teachers evidence about whether OCR actually ran.

### Bugs And Problems Found

- Page-level OCR is not precise enough for handwritten math grading.
- OCR confidence is blank for the CXSee path because the provider response does not expose a calibrated confidence score in the current integration.
- Multiple questions on one page can contaminate exact-answer checks and AI grading.
- The review page still needs question-level crops/regions.

## 2026-06-09 - Master Handoff And External Audit Prompt

### What Was Built

- Added `docs/master_handoff_spec.md`.
- Added `docs/external_research_audit_prompt.md`.
- Updated README to point new reviewers to the major documents.
- Documented:
  - architecture;
  - database schema;
  - route inventory;
  - UI behavior;
  - OCR logic;
  - grading logic;
  - analytics formulas;
  - report behavior;
  - test scripts;
  - known risks.

### Why It Helped

- Made the project reviewable by another AI or developer.
- Preserved the product intent and implementation details in one place.
- Made later correction passes more grounded and less likely to reinterpret the app from scratch.

### Bugs And Problems Found

- The master handoff became partly stale once the product direction changed from teacher-reviewed marking to automatic-grading V1.
- Some sections still described teacher finalization as the main trust boundary.
- The later automatic-grading hardening pass required updates to docs and README.

## 2026-06-09 - Research-Backed Audit

### What Was Done

- Added `docs/research_backed_audit_2026_06_09.md`.
- Reviewed the codebase, templates, docs, and scripts.
- Ran compile checks and smoke tests.
- Checked authorization behavior.
- Tested an adversarial exact-answer case.

### Critical Bugs Found

- Cross-teacher assignment creation:
  - a teacher could submit another teacher's `class_id` to `POST /teacher/assignments`;
  - a forged assignment could be inserted into another teacher's class.
- Teacher profile report leakage:
  - teacher-facing profile reports and some analytics could aggregate a student's work across classes/teachers.
- Exact-answer over-crediting:
  - a response like `Q1: x = 7, but I wrote 6 in working` could receive full marks if `6` appeared in the response.
- Student upload to draft assignments:
  - students could upload to unpublished assignments if they guessed IDs.
- Non-final report generation:
  - direct report URLs could create durable PDFs from non-final submissions.
- Hardcoded secrets:
  - the CXSee key and session secret were still in `config.py`.

### Why It Helped

- Converted vague unease into specific reproducible bugs.
- Reframed V1 around automatic grading with exception correction.
- Made score integrity and operational reliability the key engineering priority.

## 2026-06-10 - Automatic-Grading V1 Hardening

### What Was Built

- Extended `grade_drafts` with automatic grading metadata:
  - `risk_flags`;
  - `needs_exception_review`;
  - `auto_finalized_at`;
  - `auto_finalize_reason`;
  - `teacher_override_mark`;
  - `teacher_override_comment`;
  - `teacher_override_at`;
  - `teacher_override_by`.
- Changed AI grading so it writes `final_mark` automatically.
- Changed AI grading so submissions move to `final` after grading.
- Added exception routing:
  - risky rows are still finalized;
  - risky rows appear in `/teacher/exceptions`.
- Made teacher overrides explicit and persistent.
- Protected teacher overrides from being overwritten by later AI reruns.
- Added grading quality signals to teacher dashboard and assignment pages:
  - auto-finalized count;
  - exception count;
  - override count;
  - average confidence.
- Added `scripts/regression_checks.py`.

### Bugs Fixed

- Cross-teacher assignment creation blocked.
- Student upload to draft assignments blocked.
- Non-final assessment PDF reports blocked.
- Teacher-scoped student profile reports fixed.
- Exact-answer checker made conservative:
  - one-mark answer-only checks remain possible;
  - multi-mark exact/numeric matches no longer get full credit from shortcut alone;
  - unsafe multi-mark matches are risk-flagged.
- Teacher override rows are removed from the exception queue after correction.
- Reused old AI suggestions can be backfilled with auto-finalization metadata.

### Why It Helped

- Moved the product closer to the requested automatic-grading V1.
- Created an audit trail for automatic marks.
- Made teacher correction an exception workflow rather than routine finalization.
- Added regression coverage for the most dangerous bugs.

### Regression Checks Added

The regression suite checks:

- cross-teacher assignment creation is blocked;
- draft assignment upload is blocked;
- multi-mark exact check does not over-credit;
- one-mark mismatch auto-zeroes without exception;
- auto grading finalizes and flags risky rows;
- exception queue shows risky rows;
- non-final assessment report is blocked;
- teacher override survives AI rerun;
- reusable AI suggestion backfills auto-finalized fields.

## 2026-06-10 - Remaining Problems Audit

### What Was Documented

- Added `docs/remaining_problems_audit_2026_06_10.md`.
- Listed the remaining gaps after automatic-grading hardening.

### Main Problems Still Identified

- Page-level OCR is too crude for reliable handwritten math grading.
- Question-level crop/region evidence is missing.
- Automatic grading is not calibrated against real teacher marks.
- Review UI is still a review page, not a compact exception operations console.
- Student dashboard is still more descriptive than prescriptive.
- Prediction/current trajectory needs caution.
- Practice recommendations are not specific enough.
- Upload limits, background jobs, backup/migration discipline, and batch upload feedback still need work.

### Why It Helped

- Prevented the project from pretending automatic finalization equals trustworthy automatic grading.
- Gave a clear roadmap:
  1. fix secrets and calibration;
  2. add question-level OCR regions;
  3. add exception-first teacher workflow;
  4. improve student actionability and teacher planning.

## 2026-06-10 - Secrets, Calibration, Metadata, And Safer Trajectory

### What Was Built

- Moved configuration to environment variables and optional local `.env`.
- Added `.env.example`.
- Added `.env` to `.gitignore`.
- Removed hardcoded API key and fixed session secret from `config.py`.
- Added startup warnings when:
  - `SECRET_KEY` is missing;
  - selected provider key is missing.
- Added fail-closed behavior for missing provider keys.
- Added teacher calibration route:
  - `/teacher/calibration`.
- Added `grading_audit_summary(...)`:
  - total auto-finalized rows;
  - override count;
  - override rate;
  - mean absolute difference between original AI mark and teacher override;
  - disagreement by topic;
  - disagreement by mark count;
  - disagreement by question type;
  - disagreement by risk flag.
- Added optional question metadata columns:
  - `syllabus_code`;
  - `subtopic`;
  - `paper_component`;
  - `calculator_allowed`;
  - `source_paper`;
  - `source_year`;
  - `question_number`;
  - `assessment_objective`;
  - `difficulty_teacher`;
  - `question_type_tag`;
  - `mark_structure`;
  - `requires_method_marks`;
  - `answer_only_eligible`.
- Changed prediction display to current trajectory bands.
- Hid trajectory until at least four finalized assessments exist.
- Updated student PDFs to avoid raw predicted percentages.

### Bugs Fixed

- Hardcoded secret risk removed from active code.
- Student-facing prediction no longer appears as a precise unsupported exam-style percentage.
- Question type/difficulty analytics can now use teacher-verified metadata before falling back to heuristics.

### Why It Helped

- Reduced billing/session integrity risk.
- Made AI quality measurable through teacher overrides.
- Improved pedagogical tone and reduced overclaiming.
- Prepared the schema for more defensible analytics.

### Verification

- Regression suite passed.
- Compile checks passed.
- Secret scan found no long provider-key-shaped tokens in active code/docs.

## 2026-06-12 - Creative Text-Only Analytics Demo Reset

### What Was Built

- Rewrote `scripts/analytics_demo.py`.
- The script now resets the local demo database more aggressively:
  - deletes all classes;
  - deletes all student accounts;
  - keeps the teacher account;
  - rebuilds one class and three students.
- Created class:
  - `Creative Analytics Test Class`.
- Created three synthetic students:
  - `Maya Strong` / `creative.strong@demo.local`;
  - `Nina Needs Practice` / `creative.weak@demo.local`;
  - `Leo Improving` / `creative.improving@demo.local`.
- Created five text-only assignments:
  - `[Creative Text Demo] 01 - Number Fluency`;
  - `[Creative Text Demo] 02 - Algebra Equations`;
  - `[Creative Text Demo] 03 - Probability and Statistics`;
  - `[Creative Text Demo] 04 - Trigonometry and Mensuration`;
  - `[Creative Text Demo] 05 - Mixed Word Problems`.
- Excluded geometry and graphs on purpose.
- Generated 15 text PDFs with deliberately varied work:
  - correct working;
  - partial working;
  - wrong working;
  - random copied numbers;
  - omitted final answers;
  - improving organization for Leo.
- Inserted 75 finalized grade rows directly.
- Added teacher-verified metadata where possible:
  - `difficulty_teacher`;
  - `question_type_tag`;
  - `subtopic`;
  - `answer_only_eligible`;
  - `requires_method_marks`.
- Updated `docs/analytics_test_harness.md` to describe the new creative dataset.

### Why It Helped

- Created a cleaner test scenario for analytics without OCR noise.
- Made the three student patterns obvious:
  - Maya is consistently strong;
  - Nina is consistently weak;
  - Leo improves across five assessments.
- Made dashboards, review queues, support lists, and current trajectory easier to inspect manually.
- Gave a reusable local testbed for future analytics and report changes.

### Verification

- `python3 scripts/analytics_demo.py` ran twice with stable counts:
  - 3 students;
  - 1 class;
  - 5 assignments;
  - 15 submissions;
  - 75 grade rows.
- Regression suite passed.
- Compile checks passed.
- Local server was started at `http://127.0.0.1:8000`.

## Current Known Limitations

These are not forgotten. They are deliberately still open:

- Page-level OCR should be replaced or supplemented with question-level crop/region OCR.
- A true exception-first teacher workflow is still needed.
- AI grading must be calibrated on real teacher-marked submissions.
- Background grading jobs are needed before large class batches.
- Upload size/page/pixel limits are still needed.
- Bulk upload feedback should show matched, skipped, invalid, duplicate, and replaced files.
- Student dashboard should become more action-plan-like:
  - redo this question;
  - because this skill failed;
  - then try these similar items.
- Teacher analytics should become a reteach planner:
  - topic/subtopic;
  - affected students;
  - representative failed questions;
  - printable group practice.
- Printable student reports should become shorter action plans rather than dashboard dumps.
- SQLite backup/migration discipline should be improved before real grading data accumulates.

## Most Important Invariants Now

- `final_mark` is the analytics source of truth.
- Teacher override marks outrank AI marks.
- AI reruns must not overwrite teacher overrides.
- Risky automatic marks may still be finalized, but they must remain visible in exception/calibration workflows.
- Teacher routes must scope every class, assignment, submission, and report by teacher ownership.
- Student routes must only expose that student's assignments, submissions, reports, and results.
- Real API keys must live in `.env` or environment variables, not in committed code.
