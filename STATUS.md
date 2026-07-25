# Sumkora release-candidate status

Updated: 25 July 2026

## Starting state and safety checkpoint

- Starting commit: `1a3e9e4100c9705d53a4223412df8096129be70d`
- Previous branch: `feat/numera-0606-upgrade`
- Release branch: `chore/sumkora-release-candidate`
- Public site: `https://sumkora.com`
- Deployment: manual Railway upload; no automatic Git source is connected.
- Runtime: one Singapore service, one persistent volume, SQLite and private
  local uploads.
- `.env`, databases, uploads, private papers, API documents and PDFs are
  ignored by both Git and the deployment image.
- A local database backup was created under `/tmp`. Railway could not download
  the production database because the account has no SSH key, so the
  production volume was not touched.

## Changes made

### Product rename

- All active page titles, navigation, authentication, student/research copy,
  bilingual strings, API metadata, PDF footers, filenames and active
  documentation now use Sumkora.
- Added canonical `https://sumkora.com` URLs, Open Graph metadata, a Sumkora
  manifest and an accessible S favicon.
- New internal placeholder emails use `accounts.sumkora.invalid`.
- Student reports use `sumkora-...-paper-report.pdf`; progress and research
  reports use equivalent Sumkora names.
- `MIGRATION_NOTES.md` records the previous public name.

### OCR and pipeline

- Fixed sideways OCR/evidence rendering for scanner PDFs with 90/270-degree
  rotation metadata while preserving genuine landscape pages.
- The original PDFs remain unchanged.
- Live benchmark calls recorded the requested/actual model, fallback and
  latency without logging secrets or raw private transcriptions.
- Failed analysis status now hides provider/internal details and provides a
  clear retry route.

### Upload and privacy

- Added duplicate-document detection across question paper, completed work and
  mark scheme.
- Verified invalid PDFs, empty/size limits and Unicode filenames.
- Preserved ownership checks for result pages, original documents, PDFs and
  research routes.

### Interface and reports

- Preserved the existing restrained design rather than redesigning it.
- Verified zero-paper dashboard, upload, paper, comparison, skills, settings
  and research pages at desktop, tablet and mobile sizes.
- Removed internal corrected-mapping wording from the student report.
- Rendered and inspected student and research PDFs with Sumkora footers.

## Test results

- `.venv/bin/pytest -q`: 26 passed.
- `.venv/bin/python scripts/regression_checks.py`: 10 checks passed.
- `.venv/bin/python scripts/demo_flow.py`: completed and finalized a demo
  submission.
- `pnpm build`: passed.
- Python compile check: passed.
- Live OCR subset: 2 unique pages, 13 selected checks; primary unavailable,
  fallback completed. See `docs/OCR_BENCHMARK.md`.
- Browser audit: principal local student and research routes had no old-brand
  text, horizontal overflow or console warnings/errors.
- PDF render: both sample files passed text-bound checks and PNG inspection.

## Intentionally retained legacy identifiers

These are not shown to students or researchers:

1. `auth.py` keeps the `numera-session-v2` signing salt so existing sessions
   remain valid.
2. OCR readers accept the old `_numera` metadata key so stored runs remain
   readable; new runs write `_sumkora`.
3. The PDF QA test accepts the old `NUMERA_PDF_QA_DIR` variable as a fallback;
   the active variable is `SUMKORA_PDF_QA_DIR`.
4. `numera` remains a reserved username to prevent impersonation of old links
   or support identities.
5. Existing older student rows may retain hidden
   `@accounts.numera.invalid` placeholders; new rows use the Sumkora domain.
6. Railway's internal project/service names and generated
   `RAILWAY_SERVICE_NUMERA_URL` remain unchanged to avoid unnecessary
   deployment-resource churn. The public host and canonical URL are Sumkora.
7. The previous Railway subdomain remains a compatibility address but is not
   linked from the public product.
8. The single previous-name sentence in `MIGRATION_NOTES.md` is intentional
   project history.

## Known limitations

- The configured primary OCR model was unavailable in the measured live calls;
  fallback processing took 31-88 seconds per sampled page.
- The two-page OCR benchmark is evidence, not a general accuracy claim.
- The grading gold set is synthetic and too small for examiner-level claims.
- Processing is an in-process background task; a restart can interrupt it.
- SQLite and local volume storage support only a small single-instance pilot.
- Recovery codes have no email fallback; loss requires manual owner help.
- Shared rate limiting, malware scanning, MFA and durable worker cancellation
  are not implemented.
- Provider student-data terms/retention and PyMuPDF licensing require review.

## Exact verification commands

```bash
cd "/Users/oscar/Desktop/Math /IGCSE Math AnAn"
.venv/bin/pytest -q
.venv/bin/python scripts/regression_checks.py
.venv/bin/python scripts/demo_flow.py
.venv/bin/python -m compileall -q . -x '(.venv|node_modules|tmp|data)'
pnpm build
SUMKORA_PDF_QA_DIR=output/pdf .venv/bin/pytest -q \
  tests/test_v2_refinement.py::test_student_and_research_pdfs_render
pdftoppm -png -r 120 output/pdf/student-report.pdf tmp/pdfs/student-report
pdftoppm -png -r 120 output/pdf/research-report.pdf tmp/pdfs/research-report
```

## Deployment status

The release candidate has not yet been uploaded. The final deployment and
post-deployment smoke-test result will be recorded before handoff.
