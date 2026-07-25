# Numera 0606 upgrade status

Updated: 25 July 2026

## Outcome

The inherited FastAPI prototype has been preserved and upgraded in place. It
now has a functioning 0606-oriented student journey, persisted processing
jobs, criterion evidence, marks-lost diagnoses, score ranges, longitudinal
skill states, paper comparison, owner/researcher controls, paper-pack
registration, private exports, and deployment scaffolding.

This is a tested development build, not a production deployment.

## What worked before

- FastAPI, Jinja, SQLite and a compact Tailwind-style interface.
- Separate teacher/student logins, classes, assignments and uploads.
- Page rendering, OCR adapters, AI-assisted whole-question marking.
- Teacher review, final marks, reports and basic student analytics.
- An inherited 0580 ingest path and regression harness.

## What changed and now works

- Product scope, fresh seed data and new assignment defaults target Cambridge
  IGCSE Additional Mathematics 0606.
- Backend ownership checks protect student results and PDF downloads.
- Research access is a separate `researcher`/`owner` role.
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
- Researchers can inspect packs/runs/uncertainty, record corrections, register
  experiments and export pseudonymized JSON/JSONL/CSV.
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

- `pytest -q`: 6 passed.
- `scripts/regression_checks.py`: 11 passed.
- `scripts/demo_flow.py`: passed.
- `scripts/seed_0606_demo.py`: passed and is idempotent.
- Python compile check: passed.
- Browser: student login, dashboard layout and 0606 longitudinal data verified.
- Official packs: 3 components, 77 question/subpart rows, 260 criteria.
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
- The legacy grader adapts a whole-question decision into one synthetic
  criterion unless a reviewed paper pack is linked.
- Processing runs in a web-process background task; restarts can interrupt it.
- SQLite and local private storage are development-only for multiple servers.
- No password reset, MFA, invite workflow, rate limiter or malware scanner.
- Provider data residency/retention must be approved before real student use.
- PyMuPDF's AGPL/commercial licensing must be reviewed for the deployment.
- Research UI lists runs but does not yet provide a complete regrade/A-B
  comparison workflow or failure-gallery UI.

## Next five priorities

1. Review and approve the 0606 pack parser output and map assignments to packs.
2. Replace legacy whole-question grading with native criterion dependency,
   follow-through and alternative-method evaluation.
3. Move to PostgreSQL, private S3/R2 storage and a durable worker queue.
4. Add owner-run regrading/A-B comparisons, calibration metrics and failure
   gallery pages.
5. Complete a privacy/security review, rate limiting, account recovery and
   production deployment under HTTPS.
