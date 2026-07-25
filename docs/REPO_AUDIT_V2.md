# Repository audit v2

Audit date: 25 July 2026

## Preservation

The original archive remains at `/Users/oscar/Desktop/IGCSE Math AnAn.zip`.
It was extracted into a new working directory. Git was initialized, the
unmodified imported state was committed as `00b0ed3`, and work continued on
the previous feature checkpoint.

## Existing architecture

- Frontend: server-rendered Jinja templates, Tailwind utility classes and a
  small `static/style.css`. The visual language was already coherent but the
  Tailwind browser CDN failed locally.
- Backend: synchronous FastAPI monolith with form routes and generated PDF
  reports.
- Persistence: SQLite in `data/app.db`, with schema creation and additive
  runtime migrations in `db.py`.
- Authentication: bcrypt passwords and signed Starlette sessions.
- Files: local PDF paths under `data/uploads`.
- Processing: PyMuPDF rendering, provider-specific OCR, question-level grader,
  teacher exception/finalization flows.
- Deployment: no reliable production configuration in the imported state.

## Existing behavior and evidence

The imported application already supported teacher/student login, separate
classes, published assignments, student/bulk uploads, OCR caching, AI grading,
teacher review and overrides, reports, dashboards and an 11-check regression
harness. The historical public prototype exposes a similar 0580-era
student experience but is a separate Next.js/Coze deployment; no repository
configuration links this FastAPI source to it.

Backend student separation existed on many routes but was not consistently
tested. The upgrade added explicit ownership queries for results, question
evidence and file downloads, plus negative authorization tests.

## Provider and grading audit

The provider layer was OpenAI-compatible but not sufficiently auditable.
Requests now preserve model/prompt/parser versions, raw response, duration,
warnings and failure state. The older grader primarily made a single
whole-question decision. That logic is preserved as a compatibility adapter,
but new criterion decision tables and diagnosis records expose its current
granularity honestly.

The original analytics aggregated final marks by topic/difficulty and created
score history and reports. It did not maintain a versioned student evidence
model, distinguish weak from untested, expose score uncertainty, or compare
marks-lost mechanisms across papers.

## 0580 assumptions found

- README, title, class placeholders and seed records named syllabus 0580.
- New assignments inherited a database default of 0580.
- Ingest filename parsing and a large local practice bank were 0580-specific.
- Existing analytics did not enforce a syllabus boundary.

Fresh seeds/defaults now use 0606. New student analytics filter to 0606.
Legacy records and ingest code are preserved for migration and audit; they are
not silently relabeled.

## Reusable modules retained

`main.py`, `db.py`, `auth.py`, `grading.py`, `ocr.py`, `pdf_utils.py`,
`analytics.py`, reports, localization, teacher templates, the regression
harness and the overall frontend design were extended rather than replaced.

New focused modules are `assessment.py`, `pipeline.py`, `paper_packs.py`,
`math_checks.py` and `storage.py`.

## Technical debt and risk

- Runtime SQLite migrations are not a production migration system.
- In-process background jobs have no retry/durability guarantee.
- Local file storage cannot support horizontally scaled instances.
- Heuristic paper parsing has low confidence and no visual owner review UI.
- Most live grading is still legacy whole-question logic.
- External model retention, residency and subprocessors are not yet approved.
- No rate limiting, account recovery, MFA, malware scanning or deletion UI.
- Some teacher/research aggregates intentionally still include legacy data.

## Secret and private-data audit

The API credential was read from the owner's Word document without printing
it and written only to an ignored, mode-600 `.env`. Private PDFs were copied
to ignored `private_test_data/` for authorized local evaluation. `.gitignore`,
Git path inspection and secret-pattern scans confirm neither keys nor PDFs are
tracked.
