# Numera V2 refinement status

Updated: 25 July 2026

## Outcome

The inherited FastAPI prototype has been preserved and upgraded in place.
Numera now has exactly two active experiences: a student-owned assessment
product and a separate private researcher/owner workbench. The class,
assignment and teacher-review product is archived from active routing.

This is a tested development build, not a production deployment.

## What worked before this refinement

- FastAPI, Jinja, SQLite and a compact Tailwind-style interface.
- Separate teacher/student logins, classes, assignments and uploads.
- Page rendering, OCR adapters, AI-assisted whole-question marking.
- Teacher review, final marks, reports and basic student analytics.
- An inherited 0580 ingest path and regression harness.

## What changed and now works

- Students upload a question paper, completed work and mark scheme directly;
  no class, assignment, teacher registration or approval is required.
- Students review detected metadata/question mappings before running analysis.
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
- Local Tailwind CSS replaces the fragile development CDN without a redesign.

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

- `.venv/bin/pytest -q`: 11 passed.
- `.venv/bin/python scripts/regression_checks.py`: 10 checks passed,
  including archived teacher-route mutation checks.
- Python compile check: passed.
- Tailwind production build: passed.
- Tests cover direct upload without classes, ownership, researcher isolation,
  rerun preservation, experiments, separate human labels and PDF generation.
- No PDF or API key is tracked by Git.

## Database and deployment

SQLite runtime migrations preserve the local prototype database. Legacy 0580
records remain available for migration/audit but are filtered out of new 0606
student analytics. Production still needs PostgreSQL migrations, a durable job
queue and private object storage. The Dockerfile and environment contract make
the app deployable once those adapters and hosting accounts are configured.
No public deployment was attempted because owner permission was not given.

## Known limitations and security concerns

- Paper-to-question parsing is heuristic and must be human-reviewed.
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
- No password reset, MFA, invite workflow, rate limiter or malware scanner.
- Provider data residency/retention must be approved before real student use.
- PyMuPDF's AGPL/commercial licensing must be reviewed for the deployment.
- The mark scheme is intentionally required; no weaker mark-scheme-free mode is
  exposed.

## Next five priorities

1. Build durable, cancellable experiment/OCR/grading workers with true model
   A/B reruns and question-level diffs.
2. Add enhanced/cropped image assets and side-by-side OCR comparison.
3. Complete the reusable visual dataset builder and granular taxonomy editor.
4. Move to PostgreSQL, private object storage and a durable worker queue.
5. Complete privacy/security review, malware scanning, rate limiting, account
   recovery and production deployment under HTTPS.
