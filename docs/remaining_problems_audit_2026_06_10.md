# IGCSE 0580 Math Tracker - Remaining Problems Audit

Date: 2026-06-10

This document is the blunt "what is still wrong" handoff. It assumes the owner's revised V1 goal:

- automatic grading should be the normal workflow;
- teachers should not check every problem;
- teacher correction is an emergency feature;
- privacy/compliance is out of V1 scope;
- score correctness, reliability, and operational integrity are still in scope.

The current system is closer to automatic-grading V1 than before, but it is not yet "perfect." The main gap is not ambition. The main gap is evidence: the system still lacks enough machine-side safeguards, calibration data, question-level evidence, and workflow compression to justify trusting it across real handwritten Cambridge IGCSE 0580 work.

## 1. Executive Summary

The app now auto-finalizes marks, records risk flags, exposes an exception queue, preserves teacher overrides, and regression-tests several high-risk bugs. That is a meaningful foundation. But the product is still not ready to be treated as a complete automatic marking system.

The biggest remaining issue is that the grading pipeline is still built around page-level text and page images, while IGCSE math marking is question-specific, method-sensitive, and often dependent on layout. Page-level OCR is too blunt for handwritten math. A correct number on a page, or an OCR transcript that loses fractions, signs, indices, roots, diagrams, or working order, can lead to wrong scoring. CROHME-style handwritten math recognition research exists precisely because mathematical notation recognition is structurally harder than plain text OCR: two-dimensional layout and symbol relationships matter. Source: [CROHME](https://www.isical.ac.in/~crohme/).

The second issue is calibration. Qwen3-VL plus heuristics may be useful, but this app has no local validation set, no AI-vs-teacher disagreement rate, no per-topic accuracy estimate, and no threshold tuning. A confidence number shown by a model is not the same as a calibrated probability that the mark is correct. Explainable AI in education literature stresses that explanations and confidence must support appropriate human trust, not decorate opaque decisions. Source: [Khosravi et al., 2022](https://doi.org/10.1016/j.caeai.2022.100074).

The third issue is product framing. The dashboard still contains "predicted score" style outputs based on a handcrafted formula. It is now teacher-scoped in the relevant places, but it is not validated against Cambridge outcomes. Learning analytics literature repeatedly warns that dashboards should be actionable, transparent, and tied to intervention, not just present impressive numbers. Sources: [Verbert et al., 2013](https://doi.org/10.1007/s11423-013-9282-2), [Matcha et al., 2019](https://doi.org/10.1109/TLT.2019.2916802), [Jivet et al., 2018](https://doi.org/10.1145/3170358.3170395).

The fourth issue is teacher workflow. The current teacher review page is still a full-submission review page with exception indicators. For the revised V1 goal, that is not enough. A teacher should see a short, prioritized exception workbench: "these 7 marks are likely wrong; fix them in 3 minutes." The current page still makes the teacher scroll through pages, OCR diagnostics, repeated extracted text, and every question. That is too slow.

The fifth issue is student actionability. Students still receive analytics that are more descriptive than prescriptive. Formative assessment research is clear: feedback is valuable when it helps learners understand the goal, current state, and next step. Sources: [Black and Wiliam, 1998](https://doi.org/10.1080/0969595980050102), [Hattie and Timperley, 2007](https://doi.org/10.3102/003465430298487), [Shute, 2008](https://doi.org/10.3102/0034654307313795). The current dashboard is closer to "you scored badly on Algebra" than "redo Q4 using simultaneous equation elimination, then attempt these two similar items."

The sixth issue is operational reliability. AI/OCR jobs are still synchronous. Upload limits are still weak. API keys and the session secret are still hardcoded in `config.py`. Privacy may be out of V1 scope, but hardcoded API keys affect billing and system integrity. Upload controls affect whether the teacher can actually run a class batch without timeouts or crashes. Sources: [OWASP File Upload Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/File_Upload_Cheat_Sheet.html), [OWASP Authorization Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Authorization_Cheat_Sheet.html), [OWASP API Broken Object Level Authorization](https://owasp.org/API-Security/editions/2023/en/0xa1-broken-object-level-authorization/).

Do not rewrite the app. The FastAPI/Jinja/SQLite architecture is still acceptable for local-first V1. But the next development pass must focus on correctness evidence, question-level grading evidence, exception-first workflow, and validation metrics. Fancy UI polish is secondary.

## 2. Critical Remaining Problems

### P0 - Hardcoded CXSee API key and fixed session secret remain in `config.py`

Affected files/functions:

- `config.py`
- `auth.py`
- app session handling in `main.py`

What is wrong:

- `CXSEE_API_KEY` is committed directly in `config.py`.
- `SECRET_KEY` is a fixed development value.

Why it matters even when privacy is out of V1:

- A leaked CXSee key can create billing damage and service disruption.
- A known session secret can allow forged sessions.
- This affects operational integrity, not just privacy.

Recommended fix:

1. Move all secrets to environment variables.
2. Add `.env.example` with placeholder names only.
3. Fail closed if the configured AI provider needs a key but no key exists.
4. Rotate the exposed CXSee key.
5. Add a startup warning in local dev if `SECRET_KEY` is still the default.

How to test:

- Run with no CXSee key and confirm AI grading fails safely with a visible "not configured" risk flag.
- Run with a test key from environment and confirm provider initialization works.
  - Search the repository for key-shaped provider tokens, inline API key assignments, and the default secret.

Evidence:

- [OWASP Session Management Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Session_Management_Cheat_Sheet.html)

### P0 - Automatic grading is not calibrated against real teacher marks

Affected files/functions:

- `grading.py`
- `main.py:manual_grade`
- `templates/teacher/exceptions.html`
- `scripts/regression_checks.py`

What is wrong:

- The app records teacher overrides, but it does not yet compute AI-vs-teacher disagreement metrics.
- There is no validation set.
- There is no per-topic, per-question-type, per-mark-band reliability estimate.
- There is no threshold tuning for exception routing.

Why it matters:

- The owner wants teachers not to check every problem.
- That is only defensible if the system measures how often automatic marks are wrong and where.

Recommended fix:

1. Add `grading_audit_summary` queries:
   - total auto-finalized rows
   - total overrides
   - override rate
   - mean absolute difference between original AI mark and teacher override
   - disagreement by topic
   - disagreement by max marks
   - disagreement by risk flag
   - disagreement by provider/model
2. Store the original AI mark separately from final mark forever.
3. Add an "AI calibration" page for teachers/admin:
   - "AI was corrected on 8/240 rows this week"
   - "Most corrected: geometry, 3+ mark questions"
4. Use override data to tune exception rules.

How to test:

- Seed 20 grade rows with AI marks and 5 overrides.
- Confirm override rate and absolute mark error are calculated correctly.
- Confirm teacher-scoped calibration excludes other teachers.

Evidence:

- Explainable AI in education requires supporting appropriate trust, not blind acceptance: [Khosravi et al., 2022](https://doi.org/10.1016/j.caeai.2022.100074)
- Broad AIED reviews emphasize context-specific validation: [Zawacki-Richter et al., 2019](https://doi.org/10.1186/s41239-019-0171-0)

### P0 - Page-level OCR is too crude for reliable handwritten math grading

Affected files/functions:

- `ocr.py`
- `grading.py:run_grading_job`
- `grading.py:extract_labelled_response`
- `templates/teacher/review.html`
- database: no `ocr_regions` or question-crop table

What is wrong:

- OCR is stored per page.
- Question grading reuses page text and page image.
- Multiple questions on one page can contaminate each other.
- The current labelled-response extraction is regex-based and fragile.
- There is no crop box tying a grade to the exact student work region.

Why it matters:

- Handwritten math contains fractions, powers, roots, inequalities, diagrams, annotations, crossed-out work, and method steps.
- Plain page OCR often loses the structure that marking needs.
- A "complete automatic system" must know which pixels and text were used for each question.

Recommended fix:

1. Add an `ocr_regions` table:
   - `submission_id`
   - `question_id`
   - `page_number`
   - `x0`
   - `y0`
   - `x1`
   - `y1`
   - `image_path` or cached rendered image hash
   - `ocr_text`
   - `ocr_confidence`
   - `provider`
   - `status`
   - `error`
2. Start with manual or semi-automatic region assignment:
   - question has `page_number`
   - optional crop boxes can be set once per assignment
   - apply same crop to each student's submission
3. Grade from the region image plus region OCR, not whole page text.
4. On the review page, highlight the exact crop used by AI.

How to test:

- One page with Q1 and Q2 where Q1 answer appears in Q2 working.
- Confirm Q1 grading only sees Q1 region.
- Confirm region OCR failure flags only the affected question.

Evidence:

- Mathematical handwriting recognition is a specialized problem because notation is two-dimensional and structural: [CROHME](https://www.isical.ac.in/~crohme/)
- Image-to-LaTeX systems show the need for specialized math recognition rather than generic OCR: [pix2tex/LaTeX-OCR](https://github.com/lukas-blecher/LaTeX-OCR)

### P1 - The review UI is still not an exception-first operations console

Affected files/templates:

- `templates/teacher/review.html`
- `templates/teacher/exceptions.html`
- `main.py:review_submission`
- `main.py:teacher_exceptions`

What is wrong:

- The exception queue exists, but clicking an exception opens the full review page.
- The full review page shows the whole PDF, page images, OCR diagnostics, OCR text, AI notes, and all questions.
- The teacher cannot rapidly process only the risky questions.

Why it matters:

- In the revised V1 workflow, teachers should not check every problem.
- The exception path must be extremely fast.

Recommended fix:

1. Add an exception-only review route:
   - `/teacher/submissions/{submission_id}/exceptions`
   - or `/teacher/exceptions/{grade_draft_id}`
2. Show one risky question at a time:
   - student name
   - assignment
   - exact crop/page region
   - mark scheme
   - AI mark
   - AI reason
   - risk flags
   - final mark input
   - accept button
   - override button
   - next exception button
3. Add keyboard-friendly actions:
   - accept AI
   - set 0
   - set full marks
   - next exception
4. Add bulk "accept low-risk similar exceptions" only after calibration exists.

How to test:

- Seed 10 exception rows.
- Teacher should be able to resolve them without scrolling through non-exception questions.
- After each override/accept, row leaves exception queue.

Evidence:

- Teacher dashboards need to connect data to intervention and fit classroom workflow: [Verbert et al., 2013](https://doi.org/10.1007/s11423-013-9282-2), [Holstein et al., 2019](https://doi.org/10.1145/3290605.3300607)
- Similar-answer grouping and exception workflows are common in grading tools such as Gradescope: [Gradescope AI-assisted grading](https://help.gradescope.com/article/5d3ifaeqi4-ai-assisted-grading)

### P1 - The predicted score remains pedagogically unsafe

Affected files/templates:

- `analytics.py:predict_student_score`
- `templates/student/dashboard.html`
- `reports.py:profile_report`
- `i18n.py` labels around `predicted_score`

What is wrong:

- The prediction is a handcrafted weighted average with a weak-topic penalty.
- It is not calibrated to Cambridge IGCSE grade thresholds.
- It is not based on comparable paper components.
- It is displayed as a precise percent.
- It appears in student-facing UI and profile PDFs.

Why it matters:

- A precise but unvalidated forecast can mislead students and parents.
- It can create anxiety or false confidence.
- It is not necessary for formative V1.

Recommended fix:

1. Rename `predicted_score` to `current_trajectory`.
2. Display bands instead of exact percentages:
   - needs support
   - developing
   - secure
   - strong
3. Hide it until at least 4 finalized comparable assessments exist.
4. Remove it from student PDFs until validated.
5. Add "based on finalized class work only" explanation.

How to test:

- Student with 0, 1, 3, and 4 submissions.
- Confirm exact forecast is hidden below threshold.
- Confirm student PDF omits prediction or uses safe band language.

Evidence:

- Student-facing learning analytics should support self-regulated learning with transparent, actionable information: [Jivet et al., 2018](https://doi.org/10.1145/3170358.3170395)
- Feedback should answer "where to next" rather than simply judge performance: [Hattie and Timperley, 2007](https://doi.org/10.3102/003465430298487)

### P1 - Topic, difficulty, and question-type analytics are still heuristic

Affected files/functions:

- `analytics.py:difficulty_label`
- `analytics.py:question_type`
- `topics.py`
- `reports.py`
- student and teacher dashboard templates

What is wrong:

- Difficulty is inferred from max marks and assignment title.
- Question type is inferred from keyword rules.
- Topics are broad and manually selected.
- No Cambridge component/paper/source metadata is stored.
- No assessment objective metadata is stored.

Why it matters:

- Analytics are only as good as the metadata.
- A 2-mark algebra question can be hard; a 5-mark routine mensuration question can be easy.
- Keyword rules will misclassify many IGCSE questions.

Recommended fix:

Add explicit metadata fields to `questions`:

- `syllabus_code`
- `subtopic`
- `paper_component`
- `calculator_allowed`
- `source_paper`
- `source_year`
- `question_number`
- `assessment_objective`
- `difficulty_teacher`
- `mark_structure`
- `requires_method_marks`
- `answer_only_eligible`

How to test:

- Create questions with known metadata.
- Confirm analytics use stored metadata before falling back to heuristics.
- Confirm reports expose the teacher-verified metadata.

Evidence:

- Cambridge 0580 has a defined syllabus and assessment structure that should anchor the product metadata: [Cambridge IGCSE Mathematics 0580](https://www.cambridgeinternational.org/programmes-and-qualifications/cambridge-igcse-mathematics-0580/)

### P1 - Practice recommendations are not specific enough

Affected files/functions:

- `analytics.py`
- `reports.py:profile_report`
- `templates/student/dashboard.html`
- `content/practice_questions.json` if used by recommendations

What is wrong:

- Practice is mostly matched by topic.
- It does not reliably match failed skill, question type, difficulty, method error, or mark-scheme requirement.
- The student is not told exactly why the practice item was selected.

Why it matters:

- A student who missed a trigonometry bearing question does not just need "Trigonometry." They need a similar bearing/sine/cosine/rule item at the right difficulty.

Recommended fix:

1. Attach skill tags to questions and practice items.
2. Recommend practice based on:
   - topic
   - subtopic
   - question type
   - difficulty
   - failed mark-scheme step
3. Show the reason:
   - "Chosen because you lost marks on Q5: expanding double brackets."
4. Add "redo original question" before new practice.

How to test:

- Seed weak performance in one subtopic.
- Confirm recommendations are subtopic/type matched, not only broad-topic matched.

Evidence:

- Formative feedback is more effective when it is task-specific and actionable: [Shute, 2008](https://doi.org/10.3102/0034654307313795)

### P1 - AI prompts still need stricter mark-scheme discipline

Affected file:

- `grading.py`

What is wrong:

- The model is asked to grade, but the system still lacks a strict per-mark evidence schema.
- It does not force separate method marks, accuracy marks, special-case marks, units, rounding, and follow-through.
- It does not always require "not visible" versus "incorrect" distinction.

Why it matters:

- IGCSE math grading is not just final-answer matching.
- A model can sound confident while skipping mark-scheme logic.

Recommended fix:

Change model output schema to include:

```json
{
  "question_label": "Q3",
  "max_marks": 4,
  "awarded_mark": 3,
  "confidence": 0.72,
  "mark_breakdown": [
    {
      "mark_id": "M1",
      "awarded": true,
      "evidence": "student rearranged equation correctly",
      "source": "image",
      "uncertain": false
    }
  ],
  "final_answer_seen": "...",
  "uncertainties": ["unit not visible"],
  "risk_flags": ["unit_unclear"]
}
```

How to test:

- Method correct, final answer wrong.
- Final answer correct, no working visible.
- Units missing.
- Rounded answer outside tolerance.
- Crossed-out correct answer followed by wrong answer.
- Ambiguous handwriting.

Evidence:

- Explainability must support human decision-making and appropriate trust: [Khosravi et al., 2022](https://doi.org/10.1016/j.caeai.2022.100074)

### P1 - Synchronous OCR/grading will not survive real class batches

Affected files/functions:

- `main.py:ai_grade_submission`
- `grading.py:run_grading_job`
- `ocr.py:run_submission_ocr`

What is wrong:

- OCR and AI grading run during the request path.
- Long model calls can cause timeouts.
- Users may retry and create confusing state.
- There is no job status page or retry queue.

Why it matters:

- A teacher may upload 20 to 40 handwritten PDFs.
- Batch grading should not depend on one browser request staying alive.

Recommended fix:

1. Add a `grading_jobs` table:
   - `id`
   - `submission_id`
   - `status`
   - `started_at`
   - `finished_at`
   - `error`
   - `attempts`
2. Add a local background worker thread or process for V1.
3. Make the UI show:
   - queued
   - OCR running
   - grading running
   - final
   - failed
4. Add retry for failed jobs.

How to test:

- Fake provider delay.
- Fake provider exception.
- Browser request returns immediately.
- Job status updates correctly.

Evidence:

- This is implementation practice rather than education research. The relevant point is teacher workflow reliability, not theoretical novelty.

### P2 - Upload controls are still too weak

Affected files/functions:

- `pdf_utils.py:is_valid_pdf`
- `pdf_utils.py:save_upload`
- `main.py` upload routes

What is wrong:

- Server-side PDF validation exists, but there are no clear file size, page count, render pixel, or batch count limits.
- Very large PDFs can make rendering/OCR expensive or crash the local app.
- Original filename is still part of saved filename after a UUID prefix.

Why it matters:

- Scanned homework PDFs can be large.
- Broken uploads should fail cleanly, not damage the teacher workflow.

Recommended fix:

1. Add max upload size.
2. Add max page count.
3. Add max rendered pixel count.
4. Store randomized internal filename and original filename separately.
5. Return upload result feedback for every file in batch upload.

How to test:

- Oversized PDF.
- 100-page PDF.
- Corrupt PDF.
- Valid but huge scanned image PDF.
- Duplicate student upload.
- Filename with unusual characters.

Evidence:

- [OWASP File Upload Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/File_Upload_Cheat_Sheet.html)

### P2 - Teacher bulk upload feedback is insufficient

Affected route/template:

- `main.py:teacher_bulk_upload`
- `templates/teacher/assignment_detail.html`

What is wrong:

- Batch upload depends on matching student names from filenames.
- Invalid, unmatched, duplicate, or replaced files are not summarized well enough for the teacher.

Why it matters:

- In real teacher workflow, upload feedback is part of grading reliability.
- A missing student submission can otherwise go unnoticed.

Recommended fix:

1. After bulk upload, show a result table:
   - file name
   - matched student
   - action taken
   - reason if skipped
2. Store batch upload events in a lightweight table or flash-like session message.
3. Add manual "assign this PDF to student" fallback.

How to test:

- Upload valid matched file.
- Upload valid unmatched file.
- Upload invalid PDF.
- Upload duplicate for same student.

Evidence:

- Teacher-facing dashboards should reduce orchestration burden and support fast intervention: [Holstein et al., 2019](https://doi.org/10.1145/3290605.3300607)

### P2 - Student reports still include too much unvalidated analytics

Affected file:

- `reports.py:profile_report`

What is wrong:

- Student profile PDF includes predicted score.
- Suggested practice is broad.
- Review questions are listed, but the report does not clearly tell a non-web student what to do next.

Why it matters:

- The owner explicitly cares about students who will not use the website.
- Printable reports must be action plans, not dashboards on paper.

Recommended fix:

Student version should include:

- latest assessment score
- 2 strengths
- 2 revision priorities
- exact questions to redo
- 3 matched practice items
- teacher comment if available

Student version should omit:

- AI risk diagnostics
- unvalidated predicted percentage
- model confidence
- internal exception flags

Teacher version should include:

- exception flags
- override trail
- OCR/model diagnostics
- reteach grouping
- intervention notes

How to test:

- Generate teacher and student versions for same submission.
- Confirm student PDF is action-oriented and free of internal diagnostics.
- Confirm teacher PDF includes grading trail.

Evidence:

- Feedback should be specific, manageable, and forward-looking: [Hattie and Timperley, 2007](https://doi.org/10.3102/003465430298487), [Shute, 2008](https://doi.org/10.3102/0034654307313795)

### P2 - Bilingual wording needs product-level review

Affected files:

- `i18n.py`
- all templates showing analytics labels

What is wrong:

- English and Chinese strings exist, but the new automatic-grading concepts need tone review.
- Labels like predicted score, exception, weak topic, and confidence can be interpreted harshly or misleadingly.

Why it matters:

- Students may read these labels directly.
- Chinese labels should avoid fatalistic phrasing and should distinguish "revise next" from "bad at."

Recommended fix:

1. Replace student-facing "weak" style language with "revise next" language.
2. Translate "exception" differently for teachers and students:
   - teacher: grading exception
   - student: omit or use "teacher checked"
3. Avoid showing model confidence to students.
4. Keep teacher-only technical terms out of student reports.

How to test:

- Review every student-visible English and Chinese string.
- Print one student report in English and Chinese.
- Ask one teacher and one student to explain what each label means.

Evidence:

- Student-facing dashboards should support self-regulation and interpretation, not just expose analytics: [Jivet et al., 2018](https://doi.org/10.1145/3170358.3170395)

### P3 - SQLite is acceptable for V1, but backup/migration discipline is missing

Affected files:

- `db.py`
- `data/app.db`
- scripts

What is wrong:

- Additive migrations exist, but there is no migration version table.
- There is no backup command.
- There is no WAL setting.

Why it matters:

- SQLite is fine for local-first, but teachers cannot lose grading data.

Recommended fix:

1. Add `schema_migrations` table.
2. Add `scripts/backup_db.py`.
3. Enable WAL mode.
4. Add startup DB integrity check.

How to test:

- Run migration twice.
- Restore from backup.
- Simulate interrupted process.

Evidence:

- This is local-first operational engineering, not a research claim.

## 3. Product And Pedagogy Problems

### 3.1 The system still reports more than it teaches

The student dashboard tells students what happened. It does not yet reliably tell them what to do next.

Required change:

- Replace first-priority student dashboard content with:
  - redo this question
  - because this skill failed
  - then try these two similar questions

Research basis:

- Formative assessment is useful when evidence changes teaching and learning actions: [Black and Wiliam, 1998](https://doi.org/10.1080/0969595980050102)
- Effective feedback answers where the learner is going, how they are going, and where to go next: [Hattie and Timperley, 2007](https://doi.org/10.3102/003465430298487)

### 3.2 Teacher analytics do not yet produce a lesson plan

The teacher analytics page needs to answer:

- What should I reteach tomorrow?
- Which students need the same intervention?
- Which exact questions show the misconception?
- What worksheet/report should I print?

Required change:

- Add a "Reteach planner" section:
  - topic/subtopic
  - affected students
  - representative failed questions
  - suggested practice set
  - print group worksheet button

Research basis:

- Learning analytics dashboards need to be actionable and situated in teacher workflow: [Verbert et al., 2013](https://doi.org/10.1007/s11423-013-9282-2), [Matcha et al., 2019](https://doi.org/10.1109/TLT.2019.2916802)

### 3.3 "Perfect automatic grading" needs a quality bar

The product goal can be "teacher does not check every problem." But the implementation needs a measurable threshold.

Recommended owner-level definition:

- The system is acceptable for V1 if:
  - at least 95 percent of one-mark answer-only questions need no correction;
  - at least 90 percent of multi-mark questions are within 1 mark of teacher mark;
  - exception queue catches at least 80 percent of errors larger than 1 mark;
  - teacher override rate is visible by assignment and topic;
  - no teacher override is overwritten by AI.

These thresholds are product targets, not research facts. They must be validated with local pilot data.

## 4. Grading/OCR Problems

### 4.1 OCR-first versus direct image grading

Current state:

- The system uses both page image and text depending on provider/model path.
- The exact checker uses extracted text.
- Fallback grading uses page text.

Recommendation:

- For V1, grade from image plus OCR transcript together.
- Store both.
- Ask the model to quote/describe visual evidence for every mark.
- Use exact-answer checker only for explicitly answer-only questions.

Reason:

- OCR-only misses math layout.
- Image-only grading is harder to debug.
- Combining both gives better auditability.

### 4.2 Confidence should be treated as routing metadata, not truth

Current state:

- AI confidence is shown and averaged.

Problem:

- Model confidence is not calibrated.

Recommendation:

- Show confidence only to teachers.
- Pair it with concrete risk flags.
- Do not show it to students.
- Use teacher override data to calibrate whether low confidence actually predicts errors.

### 4.3 Required failure cases

Add tests and sample PDFs for:

- blank page
- wrong page number
- multiple questions on one page
- answer crossed out then changed
- correct final answer with no working for method-mark question
- correct method with arithmetic slip
- missing units
- rounding/accuracy tolerance
- equivalent fractions
- negative sign ambiguity
- graph/diagram question
- geometry proof
- Chinese/English mixed annotation
- low-quality scan
- rotated page
- two students uploaded under wrong filenames

## 5. Analytics Problems

### 5.1 Difficulty labels are not reliable

Current logic:

- max marks plus paper title.

Problem:

- Difficulty is a property of the task and student population, not only mark count.

Fix:

- Add teacher-verified difficulty.
- Later estimate empirical difficulty from class performance.

### 5.2 Question-type keyword rules are brittle

Current logic:

- Keyword search in question text/mark scheme/topic.

Problem:

- Keywords miss context and create false positives.

Fix:

- Add explicit type tags.
- Use keyword fallback only when no tag exists.

### 5.3 Review queue is score-based, not misconception-based

Current logic:

- Low percentage questions become review items.

Problem:

- A low score does not explain what to study.

Fix:

- Add failed skill or failed mark-scheme-step tags.
- Use teacher comments and model mark breakdown to infer next action.

## 6. UI/UX Problems

### 6.1 Teacher review page

Current problem:

- Too much repeated OCR text.
- Not enough focus on risky rows.
- No exact crop evidence.
- Per-question forms are slower than a focused exception workflow.

Concrete change:

- Build a compact exception reviewer:
  - left: cropped student work
  - right: AI mark, mark scheme, risk flags, override controls
  - bottom: next/previous exception

### 6.2 Teacher dashboard

Current problem:

- It shows quality metrics but does not yet say whether grading is trustworthy.

Concrete change:

- Add:
  - correction rate
  - unresolved exception count
  - failed grading jobs
  - assignments with high exception rate

### 6.3 Student dashboard

Current problem:

- Too dashboard-like, not revision-plan-like.

Concrete change:

- First screen should show:
  - "Redo Q..."
  - "Practice..."
  - "Ask teacher about..."
  - latest score as secondary context

### 6.4 Mobile behavior

Current problem:

- The app uses responsive Tailwind classes, but the review page is inherently heavy.

Concrete change:

- Teacher exception review can be mobile-friendly only if it shows one crop and one decision at a time.
- Full PDF review should be desktop-first.

## 7. Security And Deployment Problems

Privacy is out of V1 scope by owner decision. The following remain necessary because they affect operations and score integrity.

Must fix:

- hardcoded API key
- default session secret
- upload size/page limits
- object ownership tests for every route with an ID
- background job failure handling
- database backup

Can wait:

- formal privacy policy
- parent/student consent flows
- school SSO
- production hosting compliance
- detailed data retention policy

## 8. Implementation Roadmap

### Step 1 - Must fix before more real student data

1. Move API keys and session secret to environment variables.
2. Rotate exposed CXSee key.
3. Add upload size/page limits.
4. Add object ownership regression tests for all teacher/student ID routes.
5. Add `grading_audit_summary` calculations.
6. Add teacher calibration metrics from overrides.
7. Hide or rename predicted score in student UI and PDFs.

### Step 2 - Must fix before regular teacher use

1. Add background grading jobs.
2. Add job status UI.
3. Add exception-only review screen.
4. Add question-level crop/region metadata.
5. Grade from region image plus region OCR.
6. Add batch upload result feedback.
7. Add explicit question metadata fields.
8. Add student printable action plan format.

### Step 3 - Polish and expansion

1. Add Cambridge 0580 metadata import helpers.
2. Add empirical difficulty from class performance.
3. Add similar-answer grouping across class.
4. Add reteach planner and printable group worksheets.
5. Add bilingual copy review.
6. Add dashboard trend explanations.
7. Add backup/restore UI.

## 9. Test Plan

### Unit tests

- `answer_candidates`
- `extract_labelled_response`
- `exact_answer_grade`
- `difficulty_label`
- `question_type`
- `predict_student_score`
- report text cleaning and safe filename
- risk flag JSON parsing

### Integration tests

- login by role
- teacher creates assignment only in own class
- student uploads only to published enrolled assignment
- AI grading auto-finalizes
- risky rows enter exception queue
- teacher override clears exception
- AI rerun preserves override
- non-final report blocked
- teacher report scoped to teacher
- student cannot access other student's report/submission

### OCR/grading tests

- clean one-mark answer
- wrong one-mark answer
- multi-mark correct final answer but missing method
- multi-mark wrong final answer with correct number in working
- ambiguous handwriting
- no OCR text
- rotated scan
- low-resolution scan
- multi-question page contamination

### UI manual tests

- teacher dashboard quality cards
- exception queue empty state
- exception queue with many rows
- review page with risk flags
- override flow
- assignment detail confidence/exception display
- English/Chinese toggle on new labels
- mobile view of dashboard and exception queue

### PDF tests

- teacher assessment report includes diagnostics
- student assessment report omits teacher-only diagnostics
- profile report scoped to teacher
- Chinese report renders without broken glyphs
- long names/titles wrap correctly

### Pilot tests

- Use 20 to 30 real student submissions.
- Teacher marks manually once as ground truth.
- AI marks independently.
- Compute exact agreement, within-1-mark agreement, large-error rate, and exception-capture rate.
- Tune risk flags before allowing teacher-light workflow.

## 10. Questions For The Owner

1. What error tolerance is acceptable for V1 automatic grading: exact agreement, within 1 mark, or "no dramatic mistakes" only?
2. Should student-facing predicted score be removed entirely for V1, or renamed to a broad trajectory band?
3. Can the teacher spend time setting question crop regions once per assignment if that greatly improves automatic grading reliability?
4. Are Cambridge past-paper questions the primary source, or will teachers mostly create custom worksheets?
5. Should the first real pilot optimize for one-mark answer-only reliability or for multi-mark method-mark grading?

## 11. Bottom Line

The system is now directionally aligned with the revised automatic-grading V1 goal. But "automatic" is not the same as "trustworthy." The next pass should stop adding broad dashboard features and instead build the evidence loop:

- question-level evidence,
- calibrated AI error metrics,
- exception-first teacher workflow,
- safer student-facing claims,
- stronger operational reliability.

That is the path from "AI-powered marking demo" to "teacher can actually stop checking every problem."
