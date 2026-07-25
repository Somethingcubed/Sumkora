# External Research Audit Prompt

Copy this entire prompt into another AI model with browsing/research access. Give that model access to this repository and tell it to read the linked docs first.

```text
You are auditing an educational web app called IGCSE 0580 Math Tracker.

You must be harsh, precise, research-grounded, and implementation-oriented. Do not just give generic advice. Read the repository first, then research online, then compare the current implementation against evidence from academic research, education technology practice, assessment design, teacher workflow studies, human-computer interaction, dashboard design, and relevant open-source software.

Repository context:
- Project root: /Users/oscar/Desktop/IGCSE Math AnAn
- Main handoff spec: docs/master_handoff_spec.md
- Analytics test harness doc: docs/analytics_test_harness.md
- README: README.md

Current product summary:
- Python FastAPI + SQLite + Jinja2 web app.
- Built for Cambridge IGCSE 0580 Mathematics.
- Teacher uploads handwritten PDF scans.
- AI uses CXSee Qwen3-VL OCR/grading suggestions.
- Teacher reviews and finalizes marks.
- Student sees analytics, topic mastery, predicted score, review queue, and practice recommendations.
- Teacher sees class analytics and printable PDF reports.
- English/Chinese UI toggle exists.
- The product is local-first and not production hardened.

Your task:
Audit everything and return a concrete improvement plan that can be handed back to the developer.

Before making recommendations, do all of the following:
1. Read README.md.
2. Read docs/master_handoff_spec.md in full.
3. Read docs/analytics_test_harness.md.
4. Inspect the codebase, especially:
   - main.py
   - db.py
   - grading.py
   - ocr.py
   - analytics.py
   - reports.py
   - i18n.py
   - pdf_utils.py
   - templates/
   - scripts/
5. Run or reason through the existing flows:
   - teacher login
   - assignment creation
   - PDF upload
   - AI grading
   - teacher review/finalize
   - student dashboard/results
   - teacher analytics
   - printable report generation
   - analytics demo harness
6. Research current external evidence and examples before final recommendations.

Research requirements:
- Search academic papers, education research, UX/HCI literature, and reputable product/design references.
- Use sources such as Google Scholar, ACM, IEEE, arXiv, education journals, learning analytics literature, assessment-for-learning literature, teacher dashboard research, and public GitHub projects.
- Research teacher dashboard design, learning analytics dashboards, formative assessment, feedback quality, student-facing dashboards, explainable AI in education, AI-assisted grading reliability, OCR of handwritten mathematics, human-in-the-loop assessment systems, and printable student progress reports.
- Include citations or source links for every major research-backed recommendation.
- Do not rely only on blog posts. Blog posts are acceptable only as secondary support.

Key questions to answer:

Product and pedagogy:
- Does the app match how teachers actually mark, review, and reteach?
- Does it support formative assessment rather than just score reporting?
- Are the student analytics actionable or potentially misleading?
- Are predicted scores pedagogically safe, useful, and explained well enough?
- Are review queues and practice recommendations grounded in meaningful learning signals?
- What should be removed, renamed, or reframed to avoid overclaiming?

Grading and OCR:
- Is the current Qwen3-VL OCR plus grading flow safe enough for teacher-reviewed suggestions?
- Where can the exact-answer checker over-credit or under-credit?
- Should OCR be page-level, question-level, or region/crop-based?
- Should the model OCR first, then grade from extracted text, or grade directly from the image?
- How should confidence, uncertainty, and teacher override be represented?
- What failure modes should be explicitly tested?
- What prompts should be changed?

Analytics:
- Are the current difficulty heuristics reasonable?
- Are question-type keyword rules too crude?
- Is the predicted score formula defensible?
- Are teacher support lists and reteach topics correct enough?
- What analytics should be prioritized for V1 versus later?
- What data should be stored now to make later analytics smarter?

Teacher UI:
- Is the teacher workflow ergonomic?
- Can teachers quickly see the original student work, OCR text, AI suggestion, final mark, and reason?
- Is the grading review page too noisy or not structured enough?
- Are PDF reports discoverable enough?
- Are class analytics useful for planning?
- What exact UI changes would reduce teacher workload?

Student UI:
- Does the dashboard help a student know what to do next?
- Are the labels understandable for IGCSE students?
- Are predictions motivating or anxiety-producing?
- Are review questions and practice recommendations specific enough?
- What should be printed for students who do not use the website?

Printable reports:
- Are profile and assessment reports enough?
- What should teacher versions include?
- What should student versions omit?
- Are the reports useful for parent meetings, student revision, and teacher planning?

Security and deployment:
- What are the critical security risks?
- How should API keys be handled?
- Is SQLite acceptable for the next stage?
- What upload/file access risks exist?
- What role checks or data isolation issues should be tested?

Code quality:
- Identify concrete bugs, brittle logic, stale documentation, bad abstractions, duplicated logic, missing tests, and risky assumptions.
- Prioritize behavioral correctness over style.
- Cite exact files/functions/route names when possible.

Expected output format:

1. Executive summary
   Give a blunt 1-page summary of the biggest risks and highest-value improvements.

2. Critical bugs and correctness risks
   List issues ordered by severity. For each issue include:
   - severity
   - affected files/functions/routes
   - what can go wrong
   - why it matters
   - recommended fix
   - how to test it

3. Research-backed product recommendations
   For each recommendation include:
   - recommendation
   - evidence/source links
   - how it applies to this app
   - implementation implications

4. UX/UI audit
   Cover teacher pages, student pages, review page, dashboards, reports, and mobile behavior.
   Include precise suggested changes, not vague design comments.

5. Grading/OCR audit
   Cover prompts, model choices, OCR granularity, confidence display, exact-answer logic, teacher review flow, and failure cases.

6. Analytics audit
   Cover topic mastery, difficulty, question type, review queue, predictions, teacher analytics, and recommended practice logic.

7. Security/deployment audit
   Include API keys, sessions, uploads, file access, database, role checks, production readiness, and privacy risks.

8. Implementation roadmap
   Give a staged roadmap:
   - Step 1: must fix before more real student data
   - Step 2: must fix before regular teacher use
   - Step 3: polish and expansion
   Each step must be concrete enough for a coding agent to implement.

9. Test plan
   Include unit, integration, manual UI, OCR/grading, report rendering, and real-data pilot tests.

10. Questions for the owner
   Ask only questions that materially affect product direction or implementation.

Strict rules:
- Do not propose a full rewrite unless you can justify it with strong evidence.
- Do not assume automatic grading is the final goal. Teacher-finalized marks are the source of truth.
- Do not ignore the bilingual English/Chinese context.
- Do not ignore students who will not use the website and need printable reports.
- Do not give generic SaaS dashboard advice. This is a school mathematics assessment tool.
- Do not skip online research. Cite sources.
- Do not hide uncertainty. If a recommendation is speculative, label it as speculative.
- Be direct. The owner wants a harsh audit that leads to real fixes.
```

Recommended extra instruction if the model can run commands:

```text
After reading the repo, run the app locally if possible:

pip3 install -r requirements.txt
python3 run.py

Then test:
- http://127.0.0.1:8000/login
- teacher@school.edu / teacher123
- student@school.edu / student123

If you cannot run the app, say exactly why and continue with static analysis.
```
