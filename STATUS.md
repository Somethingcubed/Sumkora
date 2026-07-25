# Numera student signup and interface refinement status

Updated: 25 July 2026

## Outcome

The inherited FastAPI prototype has been preserved and upgraded in place.
Numera now has exactly two active experiences: a public student assessment
product and a separate private researcher/owner workbench. Students can create
their own username-based accounts without providing email, class or teacher
details. The class, assignment and teacher-review product is archived from
active routing.

This is a tested development build, not a production deployment.

## What worked before this refinement

- FastAPI, Jinja, SQLite and a compact Tailwind-style interface.
- Separate teacher/student logins, classes, assignments and uploads.
- Page rendering, OCR adapters, AI-assisted whole-question marking.
- Teacher review, final marks, reports and basic student analytics.
- An inherited 0580 ingest path and regression harness.

## What changed and now works

- Public student registration asks only for a username, optional display name,
  password and confirmation. It can never create a researcher account.
- Usernames are trimmed, validated, unique and matched case-insensitively.
  Existing students can sign in with their migrated username; the inherited
  researcher continues to use the private email credential.
- New password hashes use a versioned SHA-256-plus-bcrypt construction that
  handles Unicode and long passwords safely. Existing bcrypt hashes continue
  to verify and are not invalidated.
- Each new student receives a high-entropy recovery code that is shown once,
  stored only as a keyed digest and consumed after a successful reset.
- Login, signup and recovery endpoints have practical per-IP throttling for
  this single-process development build.
- Students upload a question paper, completed work and mark scheme directly;
  no title, syllabus, component, year, session, class, assignment, teacher
  registration or approval is required.
- Analysis starts immediately after upload. Paper metadata and top-level
  questions are inferred automatically from OCR/native text, reconciled across
  the question paper and mark scheme, naturally sorted and matched to answer
  pages without exposing editable mapping JSON to students.
- Official 0606, mocks and custom mathematics papers share the same path.
- Reruns create immutable analysis versions and can replace any source file.
- Each version retains OCR, AI decisions, evidence, models, prompts and score
  range; the latest version drives the current longitudinal profile.
- Backend ownership checks protect student results and PDF downloads.
- Research access is a separate `researcher`/`owner` role. The inherited
  internal `teacher` role remains a temporary compatibility alias only.
- `/teacher` is disabled at middleware level; the researcher lands on
  `/research` and sees no classroom functionality.
- Same-origin POST checks, trusted hosts, security headers, timed cookies and
  production-secure-cookie configuration were added.
- Uploads have size/page validation, hashes, rotation warnings, processing
  stages, failure states and status polling.
- CXSee calls record model, prompt version, raw response, warnings and timing.
- Marking evidence is persisted at criterion level; uncertain marks produce
  confirmed/provisional/possible score ranges.
- Marks lost are grouped by topic, subtopic, skill, category and mechanism.
- A recency-weighted Beta evidence model distinguishes early signal,
  recurring concern, improving, secure/strong and untested.
- Students have paper history, comparison, skill and question-evidence pages.
- Researchers can create, edit, duplicate, archive and run multiple configured
  experiments; inspect OCR and grading evidence; preserve separate human
  labels; tag failures; rebuild profiles; version taxonomies; and export
  identified, pseudonymized or anonymized CSV/JSON/JSONL datasets.
- Student and technical experiment PDFs are distinct report types.
- The auth, student and research surfaces now share a restrained design system,
  consistent navigation, sentence-case copy, labelled fields, visible focus
  states, progressive disclosure and responsive layouts.
- A persistent `EN / 中文` control restores bilingual authentication,
  navigation and principal student workflows for students in China.
- The inherited demo researcher is displayed as Oscar.
- Local Tailwind CSS replaces the fragile development CDN.

## Live versus deterministic behavior

- Live CXSee authentication and model listing succeeded with the local key.
- `qwen-vl-ocr-latest` is configured as primary, but was not in the provider's
  returned model list and returned HTTP 503 during the check.
- `qwen-vl-ocr` also returned 503. The auditable fallback
  `qwen3-vl-plus` successfully transcribed both a synthetic image and one
  owner-authorized private scan page.
- Automated grading tests disable external providers and are deterministic.
- The supplied official pack parser is real but conservative: all extracted
  records remain `parsed_requires_review`.

## Commands

```bash
cd "/Users/oscar/Desktop/Math /IGCSE Math AnAn"
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
pnpm install --frozen-lockfile
pnpm build
.venv/bin/uvicorn main:app --host 127.0.0.1 --port 8000
```

Combined repeat start after dependencies are installed:

```bash
pnpm build && .venv/bin/uvicorn main:app --host 127.0.0.1 --port 8000
```

## Verification

- `.venv/bin/pytest -q`: 22 passed.
- `.venv/bin/python scripts/regression_checks.py`: 10 checks passed,
  including archived teacher-route mutation checks.
- Python compile check: passed.
- Tailwind production build: passed.
- Browser checks cover the principal auth, student and research pages at
  390 px mobile and 1440 px desktop widths with no horizontal overflow or
  console errors.
- Both report types were rendered and visually inspected; automated checks
  also verify that report text stays inside page bounds.
- Tests cover signup validation, case-insensitive uniqueness/login, Unicode
  password hashing, single-use recovery, direct upload without classes,
  ownership, researcher isolation, rerun preservation, experiments, human
  labels, content conventions and PDF generation.
- No PDF or API key is tracked by Git.

## Database and deployment

SQLite runtime migrations preserve the local prototype database. Legacy 0580
records remain available for migration/audit but are filtered out of new 0606
student analytics. Production still needs PostgreSQL migrations, a durable job
queue and private object storage. The Dockerfile and environment contract make
the app deployable once those adapters and hosting accounts are configured.
No public deployment was attempted because owner permission was not given.

## Known limitations and security concerns

- Paper-to-question detection is heuristic. It now combines OCR/native text
  from both source documents and answer-page labels, but unusual layouts still
  need inspection in the private research workbench.
- Direct processing is sequential and runs in the web process; a durable queue
  with progress cancellation is still required for production.
- The experiment runner currently evaluates saved configuration snapshots
  against available human labels. It does not yet batch-rerun external models,
  pause/cancel running jobs or provide a full image-level A/B execution engine.
- The OCR lab records corrections and evaluation labels, but enhanced/cropped
  image previews and one-click OCR reruns are not yet implemented.
- Run comparison is presently configuration/metric/version comparison rather
  than a complete changed/improved/worsened question diff interface.
- Dataset selection is stored as editable structured configuration; reusable
  named dataset-builder UI is incomplete.
- Taxonomies are versioned, but granular topic/skill mapping editing remains
  incomplete.
- Processing runs in a web-process background task; restarts can interrupt it.
- SQLite and local private storage are development-only for multiple servers.
- Recovery depends on the one-time code. A lost or already-consumed code
  currently requires a manual account reset; there is deliberately no
  email-based recovery.
- Rate limits are held in process memory. A multi-server deployment needs a
  shared durable limiter. MFA, invite workflows and malware scanning are not
  implemented.
- Username moderation uses a conservative fixed reserved-name list, not a
  comprehensive language or abuse-screening service.
- Provider data residency/retention must be approved before real student use.
- PyMuPDF's AGPL/commercial licensing must be reviewed for the deployment.
- The mark scheme is intentionally required; no weaker mark-scheme-free mode is
  exposed.

## Next five priorities

1. Build durable, cancellable experiment/OCR/grading workers with true model
   A/B reruns and question-level diffs.
2. Add enhanced/cropped image assets and side-by-side OCR comparison.
3. Complete the reusable visual dataset builder and granular taxonomy editor.
4. Move to PostgreSQL, private object storage, a durable worker queue and a
   shared rate limiter.
5. Complete privacy/security review, malware scanning, recovery-code
   regeneration/MFA and production deployment under HTTPS.
