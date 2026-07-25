# IGCSE 0580 Math Tracker Research-Backed Audit

Date: 2026-06-09

Scope read: `README.md`, `docs/master_handoff_spec.md`, `docs/analytics_test_harness.md`, `main.py`, `db.py`, `grading.py`, `ocr.py`, `analytics.py`, `reports.py`, `i18n.py`, `pdf_utils.py`, `templates/`, and `scripts/`.

Verification performed:

- `python3 -m compileall main.py db.py grading.py ocr.py analytics.py reports.py i18n.py pdf_utils.py auth.py scripts`
- DB count check matched the handoff counts before my disposable authorization fixture.
- FastAPI smoke tests after installing declared requirements: teacher/student login, dashboards, teacher report routes, student cross-access redirect.
- Adversarial exact-answer check: `Q1: x = 7, but I wrote 6 in working` was awarded full marks by `exact_answer_grade`.
- Authorization proof: `teacher@school.edu` could POST `/teacher/assignments` with another teacher's `class_id`; a forged assignment was inserted. I deleted the disposable fixture immediately after proving the bug.

Owner direction update:

- Revised V1 goal: the system should be as close to fully automatic as possible. The normal workflow is AI/OCR grading -> automatic final score -> analytics/reporting. Teacher review is an exception path for dramatically wrong scores, not a required per-question workflow.
- Revised V1 privacy stance: privacy/compliance is deliberately out of scope for V1. This audit therefore treats privacy notices, consent, and external-provider data sharing as later-stage concerns. Operational security that affects system integrity, billing, or score tampering still matters.

## 1. Executive Summary

With the revised V1 goal, this is not merely a teacher-reviewed tracker. It is an automatic IGCSE 0580 marking and analytics system with teacher override as an emergency correction feature. That changes the bar sharply: the app no longer needs to make every score manually confirmable, but it does need automatic-grading reliability gates, calibration data, confidence routing, and fast correction workflows. The highest risk is that weak OCR/model evidence becomes a confident final score without enough machine-side safeguards.

The first critical bug is an authorization hole in `main.py:create_assignment` (`POST /teacher/assignments`). The route accepts any submitted `class_id` and inserts an assignment before checking that the class belongs to the logged-in teacher. I proved this with a disposable second teacher/class. This is a must-fix before any real student data enters the app.

The second critical bug is data isolation in teacher profile reports and teacher analytics trend calculations. `teacher_student_report` checks that the teacher has access to the student, but `reports.profile_report(student_id)` and `analytics.student_score_history(student_id)` aggregate the student's work across all classes and teachers. In a multi-teacher school, one teacher could see a student's performance from another teacher's class. This violates least privilege and will poison teacher analytics.

The third critical correctness risk is grading. `grading.exact_answer_grade` can award full marks if the expected number appears anywhere in the labelled response. In my test, a wrong final answer with the correct number in surrounding text received full credit. In IGCSE mathematics, marks often depend on method, answer form, units, accuracy, follow-through, and part-specific work. Exact matching should be limited to low-risk answer-only items or converted into a non-final evidence flag.

The fourth risk is no longer that AI suggestions become final automatically; that is now the intended V1 behavior. The risk is that they become final without an automatic quality-control layer. `run_grading_job` updates `final_mark` from `ai_mark` and `finalize_submission` copies remaining `ai_mark` values into `final_mark`, but the system does not yet distinguish "safe to auto-finalize" from "must be flagged for teacher exception review." V1 needs auto-finalization, but only with score-confidence routing and an audit trail.

The fifth risk is analytics overclaiming. The "predicted score" formula is a hand-built weighted average plus penalties. It is not calibrated, not validated, not tied to Cambridge grade thresholds, and can output psychologically unhelpful exact percentages such as 2.4%. Research on learning analytics warns that dashboards need transparency, uncertainty, and actionability, not just numeric display. Rename it to "current trajectory" or hide it until enough comparable finalized assessments exist.

The sixth risk is weak construct validity. Difficulty is inferred from mark count and assignment title. Question type is inferred from keywords. Practice is matched by topic only. These are useful demo heuristics, but they are not defensible learning signals for a real V1. The app should store explicit metadata now: syllabus topic/subtopic, assessment objective, skill tag, calculator/non-calculator, paper/component, source paper, max marks, method/answer mark structure, and teacher-verified difficulty.

The teacher workflow should not be optimized for routine marking every question. It should be optimized for exception handling: find the few likely-wrong scores quickly, inspect the original work, override the score, and move on. The current review page repeats page-level OCR text inside every question card, lacks question crops or page-region links, and does not prioritize high-risk items. A real V1 teacher needs an exceptions workbench, not a manual grading workbench.

The student dashboard has too many diagnostic widgets and too little next action. A student should leave the page knowing the next two tasks: "Redo Q3 using sine ratio, then try these two similar problems." The current review queue points to low-scoring questions, but practice recommendations are broad topic matches. That supports score reporting more than formative assessment.

Printable reports matter because not all students will use the website. The current reports are a good start, but student versions should avoid uncalibrated prediction, and teacher versions should include intervention planning fields, AI/OCR review diagnostics, and teacher-only notes. Parent/student reports should focus on evidence, next steps, and examples of questions to redo.

SQLite is acceptable for the next local-first stage if the app stays single-school/single-machine and gains backups, migrations, and WAL. Privacy/compliance can wait for later if the owner accepts that scope. Do not postpone integrity controls that affect scores or operations: route authorization, upload limits, API key handling, and asynchronous OCR/grading jobs are still important because they affect whether the automatic system works reliably.

No full rewrite is justified. The architecture can support automatic-grading V1 if the developer tightens access control, stores better metadata, turns AI output into a calibrated auto-finalization pipeline, and reframes analytics as formative guidance rather than unsupported exam-score prophecy.

## 2. Critical Bugs And Correctness Risks

### P0 - Cross-teacher assignment creation

- Affected: `main.py:create_assignment`, `POST /teacher/assignments`, lines 370-411.
- What can go wrong: a teacher can forge `class_id` in the form and create an assignment in another teacher's class.
- Why it matters: this is broken object-level authorization and can contaminate another class's assignment/submission space.
- Recommended fix: before reading/saving uploads, query `SELECT id FROM classes WHERE id = ? AND teacher_id = ?`; if missing, redirect or return 403. Add the same ownership pattern to any future route accepting foreign keys.
- How to test: create two teachers/classes; log in as teacher A; POST teacher B's `class_id`; assert no assignment row is created and response is 403 or safe redirect.

### P0 - Teacher profile report leaks cross-class/cross-teacher analytics

- Affected: `main.py:teacher_student_report`; `reports.profile_report`, `student_context`; `analytics.student_score_history`; `teacher_analytics_summary`.
- What can go wrong: if a student is enrolled in multiple teachers' classes, a teacher can see profile analytics from classes they do not own. Teacher trend in `teacher_analytics_summary` also uses global student history.
- Why it matters: even with privacy out of scope, this makes teacher analytics wrong and allows accidental score/report contamination.
- Recommended fix: add `teacher_id` and optional `class_id` scope to profile report and analytics queries. For teacher views, filter `finalized_question_rows` and `student_score_history` by `c.teacher_id`.
- How to test: same student in two classes with different teachers; finalize one assessment per class; assert teacher A's profile report and trend excludes teacher B's assessment.

### P0 - Plaintext API key and fixed session secret in repo

- Affected: `config.py`, lines 14 and 26.
- What can go wrong: the CXSee key can be copied or billed against; fixed `SECRET_KEY` allows session-token forgery if known.
- Why it matters: this is a real credential and identity risk.
- Recommended fix: rotate the CXSee key immediately. Replace secrets with environment variables. Fail closed if required production secrets are missing. Add `.env.example`; never commit `.env`.
- How to test: run with no key and verify AI route gives safe "not configured" suggestions; run with env key and verify provider initializes; scan repo for `sk-` style secrets.

### P1 - Exact-answer checker over-credits

- Affected: `grading.answer_candidates`, `extract_labelled_response`, `exact_answer_grade`, `grade_question`; lines 46-150 and 363-366.
- What can go wrong: full marks are awarded when the expected number appears anywhere in a response, even if the final answer is wrong or contradictory.
- Why it matters: IGCSE marking often awards method/accuracy marks, not "number appears somewhere" marks.
- Recommended fix: for `max_marks > 1`, exact checker should never return full marks by itself. Return an `evidence_match` suggestion or route to vision/text grading. Add an "answer-only eligible" flag per question before exact auto-marking is allowed.
- How to test: wrong final answer with correct number in working; multiple numbers; units missing; rounded answer; equivalent fractions; negative signs; multi-part answers. Assert no full-credit suggestion unless item is explicitly answer-only and final answer is isolated.

### P1 - Automatic final marks have no safety gates

- Affected: `grading.run_grading_job`, lines 421-470; `grading.finalize_submission`; `templates/teacher/review.html`, lines 150-156.
- What can go wrong: AI marks become final even when OCR failed, the question label was not found, the exact-answer shortcut was unsafe, the page crop is ambiguous, or model confidence is not meaningful.
- Why it matters: automatic grading is now the product goal, so the app needs machine-side triage rather than routine teacher confirmation.
- Recommended fix: keep auto-finalization, but add `auto_finalized_at`, `auto_finalize_reason`, `risk_flags`, `needs_exception_review`, and `teacher_override_*` fields. Only auto-finalize rows that pass configured gates; flag the rest in an exception queue. If the owner wants everything auto-finalized no matter what, still label high-risk rows prominently.
- How to test: run AI grade on blank, low-OCR, ambiguous-label, exact-match, and multi-question-page cases. Assert safe rows auto-finalize and risky rows appear in the exception queue.

### P1 - Auto-finalized submissions can have incomplete analytics

- Affected: `finalize_submission`; analytics queries filter `gd.final_mark IS NOT NULL`.
- What can go wrong: a submission can be status `final` while some grade rows have `final_mark NULL`; analytics then exclude those rows instead of counting them as zero or incomplete.
- Why it matters: topic mastery and predictions can be inflated or inconsistent with reports.
- Recommended fix: automatic finalization must assign every question a final mark or explicit `needs_exception_review` state. If the system cannot grade a row, choose a policy: conservative `0` with flag, or incomplete submission blocked from analytics. Do not silently omit rows.
- How to test: create grade rows with null final marks; auto-finalize; assert each row is either marked or flagged, and analytics coverage displays the gap.

### P1 - Student can upload to draft assignments if they guess the ID

- Affected: `main.py:student_upload`, `POST /student/assignments/{assignment_id}/upload`.
- What can go wrong: upload route checks enrollment but not `a.status = 'published'`.
- Why it matters: draft assignments may not be ready or visible.
- Recommended fix: add `AND a.status = 'published'` to the upload authorization query.
- How to test: create draft assignment; enrolled student POST upload; assert redirect/no submission.

### P1 - Teacher can generate assessment reports for non-final submissions

- Affected: `main.py:teacher_submission_report`; `reports.assessment_report`.
- What can go wrong: direct URL can create a report where unfinalized/null marks are rendered as 0 or partial data.
- Why it matters: reports become durable artifacts; draft data should not masquerade as final.
- Recommended fix: require `submission.status = 'final'` for student variant and probably for all report variants. If teacher draft report is needed, watermark "Draft - not finalized".
- How to test: pending/review submission report route; assert blocked or watermarked draft.

### P1 - Synchronous AI/OCR blocks request handling

- Affected: `main.py:ai_grade_submission`; `grading.run_grading_job`; `ocr.run_submission_ocr`.
- What can go wrong: long OCR calls block the web request, fail on timeout, and make users double-click/retry.
- Why it matters: teacher uploads are batch workflows.
- Recommended fix: add a simple job table and background worker/thread for local-first V1. Poll status from the assignment/review page.
- How to test: fake provider with slow pages; ensure UI returns immediately and job status updates.

### P2 - Upload handling lacks resource controls

- Affected: `pdf_utils.is_valid_pdf`, `save_upload`, upload routes.
- What can go wrong: very large or many PDFs can exhaust disk/CPU/RAM during PyMuPDF rendering.
- Why it matters: scanned homework files are large, and malformed PDFs are common.
- Recommended fix: enforce file size/page count/pixel limits, randomize storage names independent of user filenames, and record original filename separately.
- How to test: oversized PDF, 500-page PDF, corrupt header, zip-bomb-like PDF, strange Unicode filenames.

### P3 - CSRF protection is deferred if V1 is strictly local-only

- Affected: all form POST routes.
- What can go wrong: a logged-in teacher/student can be tricked into submitting forms from another site.
- Why it matters: local-first reduces but does not eliminate browser CSRF risk. This is not a V1 blocker if the deployment is genuinely local and privacy/security are out of scope.
- Recommended fix: add per-session CSRF tokens to forms later; set cookie `samesite=lax` or `strict`.
- How to test: POST without CSRF token should fail.

## 3. Research-Backed Product Recommendations

### Recommendation 1 - Reframe as formative assessment, not score prediction

- Evidence/source links: Black and Wiliam's formative assessment work emphasizes using evidence to adapt teaching and learning, not just report scores: https://doi.org/10.1080/0969595980050102. Hattie and Timperley frame useful feedback around "Where am I going?", "How am I going?", and "Where to next?": https://doi.org/10.3102/003465430298487. Shute's review stresses specific, task-focused, actionable feedback: https://doi.org/10.3102/0034654307313795.
- How it applies: the app currently reports latest/average/predicted scores more prominently than next learning actions.
- Implementation implications: make the student dashboard top card "Next revision action", not "Predicted score". For each weak question, show target skill, why it was missed, one redo prompt, and two similar practice items.

### Recommendation 2 - Make teacher actionability the dashboard success metric

- Evidence/source links: learning analytics dashboard reviews repeatedly find that dashboards need to connect data to action, context, and intervention, not only visualization: Verbert et al. https://doi.org/10.1007/s11423-013-9282-2; Matcha et al. https://doi.org/10.1109/TLT.2019.2916802. Teacher-centered AI/analytics work such as Holstein et al. shows the need to fit classroom orchestration and teacher workflows: https://doi.org/10.1145/3290605.3300607.
- How it applies: teacher analytics lists weak students/topics but does not convert them into a reteach plan.
- Implementation implications: add "Reteach plan" output: topic, affected students, common failed question labels, example wrong responses if available, suggested mini-lesson/practice set, and "print group worksheet" action.

### Recommendation 3 - Treat predictions as uncertain, local, and provisional

- Evidence/source links: learning analytics ethics literature warns about transparency, privacy, and student consequences of prediction: Slade and Prinsloo https://doi.org/10.1177/0002764213479366; Pardo and Siemens https://doi.org/10.1111/bjet.12152. Student-facing dashboard research stresses explanation and self-regulation support rather than opaque forecast numbers: Jivet et al. https://doi.org/10.1145/3170358.3170395.
- How it applies: `predict_student_score` is unvalidated but rendered as a precise percentage.
- Implementation implications: rename to "Current trajectory"; show bands (`needs support`, `developing`, `secure`) rather than exact percent; hide until 4 comparable finalized assessments; explain inputs; never show on student PDF until validated.

### Recommendation 4 - Build around Cambridge 0580 constructs, not generic topics

- Evidence/source links: Cambridge 0580 syllabus and assessment structure should be the product's metadata spine: https://www.cambridgeinternational.org/programmes-and-qualifications/cambridge-igcse-mathematics-0580/. Assessment validity depends on interpreting scores against intended constructs, not arbitrary labels.
- How it applies: current `TOPICS`, keyword question type rules, and mark-count difficulty are too crude.
- Implementation implications: add tables/fields for syllabus area, subtopic, assessment objective, paper component, calculator status, source paper, explicit difficulty, method marks, answer marks, and teacher verification status.

### Recommendation 5 - Make automatic AI grading auditable and explainable

- Evidence/source links: XAI-in-education reviews argue explanations must support human decision-making and appropriate trust, not only technical transparency: Khosravi et al. https://doi.org/10.1016/j.caeai.2022.100074. AI-in-education reviews emphasize limits, bias, and context-specific validation: Zawacki-Richter et al. https://doi.org/10.1186/s41239-019-0171-0.
- How it applies: model self-confidence is shown as if it is meaningful, and final marks can be copied from AI without a calibrated reason.
- Implementation implications: display "AI evidence used" and "AI caution flags": no label found, low OCR quality, page mismatch, answer-only shortcut, model JSON repair, teacher override. Store prompt/model/version/output for audit and use those flags to decide whether the row is safe to auto-finalize.

### Recommendation 6 - Use question-level or region-level evidence for handwritten math

- Evidence/source links: handwritten mathematical expression recognition remains hard because recognition depends on symbol segmentation, two-dimensional layout, and structure, as shown by CROHME work: https://www.isical.ac.in/~crohme/. Open-source LaTeX-OCR projects such as pix2tex show image-to-LaTeX is possible but still specialized: https://github.com/lukas-blecher/LaTeX-OCR.
- How it applies: current OCR is page-level plain text. Multiple questions on one page will confuse exact matching and AI grading.
- Implementation implications: V1 can keep page-level rendering but should add question crop metadata or teacher-selectable regions. Store OCR per question/region when possible.

### Recommendation 7 - Borrow workflow patterns from grading tools, not generic dashboards

- Evidence/source links: Gradescope's AI-assisted grading workflow groups similar answers and keeps instructor review central: https://help.gradescope.com/article/5d3ifaeqi4-ai-assisted-grading.
- How it applies: this app reviews one submission at a time and repeats page OCR per question.
- Implementation implications: for later V1+, add "grade question across class" view, grouping similar OCR/answers, showing automatic marks and outliers so the teacher can correct exceptions quickly.

### Recommendation 8 - Apply web security baselines before real data

- Evidence/source links: OWASP File Upload Cheat Sheet https://cheatsheetseries.owasp.org/cheatsheets/File_Upload_Cheat_Sheet.html; Session Management Cheat Sheet https://cheatsheetseries.owasp.org/cheatsheets/Session_Management_Cheat_Sheet.html; Access Control Cheat Sheet https://cheatsheetseries.owasp.org/cheatsheets/Authorization_Cheat_Sheet.html; OWASP API Broken Object Level Authorization https://owasp.org/API-Security/editions/2023/en/0xa1-broken-object-level-authorization/.
- How it applies: current local-first mode has direct object authorization bugs, hardcoded secrets, weak cookie settings, and unbounded uploads.
- Implementation implications: add systematic route tests for every object ID parameter, env secrets, CSRF, cookie flags, upload limits, and scoped report queries.

## 4. UX/UI Audit

### Teacher dashboard and assignment management

- Keep the current simple server-rendered UI. It is appropriate for a local school tool.
- Add a clear "Needs my review" queue grouped by assignment and sorted by highest risk: OCR failed, AI low confidence, large AI/teacher discrepancy, unconfirmed rows.
- On assignment detail, show upload outcomes: matched student, skipped file, invalid PDF, duplicate/replaced submission. Silent skips in `teacher_bulk_upload` are not acceptable for real batches.
- Add "assignment setup completeness": number of questions, total marks, missing mark schemes, missing page numbers, unverified imported questions.
- Add edit/delete for questions. Current add-only flow forces DB/script fixes for mistakes.

### Teacher review page

- Replace the vertical page preview plus repeated OCR cards with a two-pane workbench.
- Left pane: PDF/image page, page selector, zoom, rotate, crop/region highlight.
- Right pane: current question card with question text, mark scheme, automatic mark, risk flags, OCR transcript, override mark, comment, and next/previous buttons.
- Add a compact question list with statuses: unconfirmed, accepted AI, edited, low confidence, OCR failed.
- Add keyboard shortcuts only if discoverable in tooltips/settings, not as in-app instructional clutter.
- Add batch save. Per-question POSTs are slow and risky.
- Do not show AI confidence as a single green/amber/red truth. Show caution flags and evidence quality.
- The finalize button should be disabled until every question is confirmed.

### Student dashboard

- Rename "Predicted score" to "Current trajectory" or remove it from the first viewport.
- First card should be "Next revision action"; second should be latest score; third should be topic to revisit; fourth can be progress.
- Review questions should show "Redo this because..." based on teacher comment or mark-scheme skill tag.
- Practice recommendations should include why each item was chosen and whether it matches topic, type, or difficulty.
- Avoid labels such as "weakest" in student-facing copy. Use "revise next" / "needs practice" in both English and Chinese.
- For bilingual context, validate Chinese strings for tone: avoid fatalistic labels around prediction and support.

### Teacher analytics

- Add class filter. Current page aggregates all classes owned by the teacher, which is not how teachers plan a lesson.
- For "topics to reteach", include student count, representative questions, and a print action.
- Add "recent assessment heatmap" by question: columns are questions, rows are students, cells are marks/percent. This is the most directly useful reteach planning view.
- Show "data coverage": number of finalized submissions, missing students, incomplete finalizations.

### Reports

- Student profile report: remove exact prediction or convert to band with strong caveat.
- Teacher profile report: include teacher-only diagnostics, intervention notes, confidence/coverage, and recent override patterns.
- Assessment report: student version should include question result, teacher feedback, redo instructions, and practice. Teacher version should also include AI/OCR diagnostics and original AI mark vs final mark.
- Add "print class pack" for students who do not use the website.

### Mobile behavior

- The current Tailwind layout is responsive at a basic level, but review grading is not mobile-friendly. That is acceptable if teachers grade on desktop/tablet.
- Student dashboard should be mobile-first: one-column cards, no wide tables, text wrapping tested in English and Chinese.

## 5. Grading/OCR Audit

### Current Qwen3-VL path

The current Qwen3-VL path is not yet safe enough for the revised automatic-grading V1, but it is a plausible base if the app adds calibration and exception routing. The prompt is directionally good because it asks for JSON, max-mark bounds, method evidence, and no credit for prompt leakage. It still lacks structured uncertainty, question-location checks, explicit refusal/flagging when the target question is not visible, and a validated threshold for when a mark can be auto-finalized.

### OCR granularity

Page-level OCR is the wrong long-term unit for math marking. It is acceptable for V0 diagnostics, but grading should move toward question-level region evidence. If the app cannot crop automatically, add teacher/manual region metadata: page number plus crop box. Store the rendered crop and OCR text per `question_id`.

### OCR-first versus direct image grading

Use both, but keep them separate:

- OCR first for auditability, searchable text, and exact-answer hints.
- Direct vision grading for handwritten layout/method evidence.
- Never grade only from OCR when method marks are possible.
- Never let a rerun overwrite a teacher override unless the teacher explicitly clears the override.

### Prompt changes

Change the Qwen grading prompt to require:

- `question_seen`: boolean.
- `evidence_quote_or_description`: short evidence from visible student work.
- `uncertainty_flags`: list from a fixed set.
- `mark_breakdown`: list of method/answer marks if scheme supports it.
- `needs_teacher_attention`: boolean.
- `ai_mark`: number used for auto-finalization when risk gates pass.

Add prompt rule: if multiple questions appear on the page and the target answer cannot be localized, set `needs_exception_review=true` and use low confidence.

### Confidence display

Model self-reported confidence is not enough. Compute an app-level caution score from:

- OCR provider status.
- OCR confidence if available.
- Whether target label was found.
- Whether question page number is valid.
- Whether image crop exists.
- Whether exact checker was used.
- Whether model output needed JSON repair.
- Whether AI and previous teacher mark disagree.

### Failure modes to test explicitly

- Correct answer appears in crossed-out work; wrong final answer.
- Correct number appears in question text or mark scheme, not student work.
- Missing units.
- Equivalent forms: fraction/decimal, exact/surd, `pi` form.
- Rounding tolerance and significant figures.
- Multi-part questions on same page.
- Student labels question incorrectly.
- Blank page, rotated scan, low contrast, two pages per image.
- Chinese annotations mixed with English math.
- Calculator versus non-calculator method expectations.
- Follow-through marks from earlier wrong answers.

## 6. Analytics Audit

### Topic mastery

Current topic mastery is a weighted-by-marks aggregate over finalized rows. That is a reasonable first baseline, but only if all rows are final and topic labels are teacher-verified. Add sample size and coverage warnings everywhere.

### Difficulty

`difficulty_label(max_marks, assignment_title)` is not defensible. A 2-mark trigonometry transformation can be harder than a 5-mark routine statistics table. Replace with explicit teacher/imported difficulty and keep mark-count fallback labelled as "estimated".

### Question type

Keyword rules are too crude. For example, mark schemes containing `x =` push items into equation-solving even if the question is graph interpretation. Store explicit `skill_tags` and `question_type` on questions.

### Review queue

Current rule "accuracy < 60" is simple and useful, but incomplete. Add recency, repeat failures, prerequisite skill, teacher comment, and whether the student later improved. Do not keep showing an old failed question after the student has demonstrated mastery unless it remains a spaced-review item.

### Predictions

The current prediction formula is not calibrated and should not be called a predicted score. For V1, show:

- "Current evidence band" instead of exact percentage.
- Confidence based on number of comparable assessments and coverage.
- A transparent note: based only on finalized work in this app.

Later, if enough data exists, consider IRT/Bayesian knowledge tracing or calibrated regression, but only after collecting item metadata and outcomes. This is speculative and not needed for V1.

### Teacher support lists

Support list is useful but should be scoped by class and recent work. Add "why flagged": low overall accuracy, decline, repeated topic failure, missing submissions.

### Data to store now

Add columns/tables for:

- `questions.syllabus_ref`, `subtopic`, `assessment_objective`, `skill_tags`, `difficulty_verified`, `calculator_allowed`.
- `grade_drafts.auto_finalized_at`, `auto_finalize_reason`, `risk_flags`, `needs_exception_review`, `teacher_override_mark`, `teacher_override_comment`, `teacher_override_at`, `teacher_override_by`.
- `ai_runs` table: provider, model, prompt version, question_id, submission_id, input hash, output JSON, created_at, error.
- `ocr_regions` table: submission_id, question_id, page_number, crop box, provider, text, confidence, status.
- `practice_questions.skill_tags`, `difficulty`, `source_paper`, `worked_solution`.

## 7. Security/Deployment Audit

- Privacy/compliance is explicitly out of scope for V1 under the revised owner direction. Do not block V1 on consent language, external-provider data sharing policy, or production privacy posture.
- Keep operational integrity items that affect automatic scores: route authorization, upload limits, score override audit trails, and job reliability.
- Rotate the CXSee API key in `config.py` if the repository will be shared or if billing abuse is a concern. This is operational hygiene, not a privacy blocker.
- Move secrets to environment variables later if the app moves beyond a trusted local prototype.
- Set cookies with `httponly=True`, `secure` in non-local deployments, and `samesite='lax'` or `'strict'` later.
- Defer CSRF tokens if the app remains strictly local-only for V1.
- Add file size, page count, and render pixel limits.
- Store uploads under randomized filenames; keep original filename in DB.
- Add route-level authorization tests for every `{assignment_id}`, `{submission_id}`, `{class_id}`, and `{student_id}` route.
- SQLite is fine for a single local school pilot. Add WAL, backup/export, migrations, and DB lock handling. Move to Postgres only when concurrent multi-user production use is required.
- Add a privacy notice later when the product leaves V1/local prototype mode.
- Do not use CDN Tailwind/MathJax in offline/local school mode without a fallback. Vendor static assets or document internet dependency.

## 8. Implementation Roadmap

### Step 1 - Must fix before automatic-grading V1 pilot

1. Fix `create_assignment` ownership check.
2. Scope teacher profile reports and teacher trend/history analytics by teacher/class.
3. Add published-status check to student upload.
4. Block non-final report downloads or watermark teacher drafts.
5. Disable full-credit exact matching for multi-mark/non-answer-only items unless the question is explicitly answer-only and validated.
6. Add automatic risk gates: OCR failed, label not found, low confidence, ambiguous page, unsafe exact match, invalid JSON repair, page render failure.
7. Add an exception queue for high-risk auto-finalized rows and ungradable rows.
8. Ensure every finalized submission has either a final mark for every question or a clear exception state excluded from analytics with coverage warnings.
9. Add route authorization tests for all object-ID routes.
10. Add upload size/page limits.
11. Build a small calibration set of real handwritten submissions with teacher ground truth before calling the system "complete."

### Step 2 - Must fix before regular teacher use

1. Add auto-finalization fields, risk flags, and teacher override audit trail.
2. Rework review UI into a two-pane exceptions workbench with high-risk filters.
3. Add upload result feedback for batch uploads.
4. Add class filter and data coverage to teacher analytics.
5. Rename/reframe predicted score.
6. Add explicit question metadata fields and edit UI.
7. Add job table/background worker for OCR/grading.
8. Add report variants: student safe version, teacher diagnostic version, class print pack.
9. Show automatic grading quality metrics: override rate, exception rate, OCR failure rate, and average absolute error on calibration data.

### Step 3 - Polish and expansion

1. Add question-level crop/OCR region support.
2. Add question-across-class grading view.
3. Add practice matching by skill tag and difficulty.
4. Add Cambridge 0580 syllabus mapping import/verification workflow.
5. Add calibration study before reintroducing numeric predictions.
6. Add bilingual content review for student-facing labels and report language.

## 9. Test Plan

### Unit tests

- `grading.exact_answer_grade`: adversarial answers, equivalent answers, units, rounding, crossed-out text, multi-part labels.
- `analytics.difficulty_label` and `question_type`: assert current limitations while migrating to explicit metadata.
- `reports.safe_filename`, `clean_text`, bilingual text rendering.
- `pdf_utils.is_valid_pdf`: invalid header, empty PDF, huge page count.

### Integration tests

- Teacher cannot create assignments in another teacher's class.
- Teacher profile report is scoped to owned class/teacher.
- Student cannot upload to draft assignment.
- Teacher cannot get final-style report for non-final submission.
- Auto-finalization creates a mark or exception state for every question.
- High-risk rows are visible in the teacher exception queue.
- Teacher override persists and is not overwritten by rerunning AI.

### Manual UI tests

- Teacher login, class creation, assignment creation, question edit, publish.
- Student upload and replacement.
- Teacher bulk upload with matched/unmatched/invalid PDFs.
- AI grade with configured and unconfigured provider.
- Review low-confidence item, edit mark, finalize, download reports.
- English/Chinese language switch across review, dashboard, and PDFs.
- Student mobile dashboard.

### OCR/grading pilot tests

- Build a 20-submission handwritten pilot set with teacher ground truth.
- Measure per-question OCR usability, automatic-mark absolute error, exact-check false positives, severe-error rate, and teacher correction time for exception cases.
- Track override rate by topic/question type.
- Define V1 acceptance thresholds before deployment, for example: maximum average absolute mark error, maximum severe-error rate, maximum unreviewed high-risk rate, and acceptable teacher override time.
- Do not report AI accuracy as product quality unless ground truth exists.

### Report rendering tests

- Render English and Chinese profile/assessment reports to PDF.
- Check long names, long comments, long question text, math notation, and page overflow.
- Verify student version omits teacher diagnostics and unsafe prediction.

### Real-data pilot tests

- Run `scripts/real_data_checklist.py` before import.
- Pilot with one class and one assignment.
- Collect teacher time per submission, automatic override rate, exception queue size, student usefulness feedback, and report usefulness in revision/parent meeting contexts.

## 10. Questions For The Owner

1. Should numeric "predicted score" remain in the product at all, or should V1 use only trajectory bands and next actions?
2. Will teachers mark mostly full papers, worksheets, or topic quizzes? This affects whether review should be submission-first or question-across-class-first.
3. Should student profile reports be scoped to one class/teacher, or should there be an explicit whole-student school-level role later?
4. What severe-error threshold is acceptable for automatic grading before a teacher must intervene? Example: any error of 2+ marks, or any total-score error above 5%.
5. Should high-risk questions still receive an automatic score, or should they be marked as "needs teacher exception review" and excluded from analytics until resolved?
6. Which Cambridge 0580 syllabus version should be the canonical metadata spine for the next build?
