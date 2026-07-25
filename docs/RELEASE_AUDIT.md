# Release audit

Updated: 25 July 2026

The local release candidate was compared with `https://sumkora.com`. The live
site was intentionally left unchanged during the audit and still displayed
the previous product name; deployment occurs only after the full checks pass.

## Route audit

| Route | Working state | Visual/responsive state | Console/API state | Action |
|---|---|---|---|---|
| `/login` | Working | Desktop and mobile clean | No console errors | Rebranded title, metadata, favicon |
| `/signup` | Working | Auth layout consistent | Deterministic signup checks pass | Rebranded bilingual copy |
| `/recover` | Working | Auth layout consistent | Recovery tests pass | Rebranded title |
| `/student` | Working, zero-paper state inspected | No mobile overflow | No console errors | Sumkora navigation and canonical URL |
| `/student/analyse` | Working | Three clear upload areas; no mobile overflow | Validation tests pass | Duplicate-document validation added |
| `/student/analysis/{id}/processing` | Working | Persisted stages; actionable failure state | Status authorization tested | Safe error and retry link added |
| `/student/papers` | Working | Clean empty/list states | Ownership tests pass | Rebranded |
| `/student/papers/{id}` | Working in automated flow | Report view covered by templates/tests | Cross-student access denied | Rebranded and export renamed |
| `/student/compare` | Working | No mobile overflow | Comparison tests pass | Rebranded |
| `/student/skills` | Working | No mobile overflow | Longitudinal tests pass | Rebranded |
| `/student/settings` | Working | No mobile overflow | Password logic tested | Rebranded |
| `/research` | Working and private | Mobile/tablet clean | Student access denied; no console errors | Rebranded |
| `/research/experiments` | Working | No mobile overflow | Lifecycle tests pass | Rebranded |
| `/research/experiments/new` | Working | Tablet/mobile clean | Save flow tested | Rebranded |
| `/research/ocr` | Working and private | Compact expandable evidence | No console errors | Rebranded |
| `/research/grading` | Working and private | Responsive | Human-label immutability tested | Rebranded |
| `/research/failures` | Working and private | Responsive | No console errors | Rebranded |
| `/research/student-models` | Working and private | Responsive | Rebuild path covered | Rebranded |
| `/research/taxonomy` | Working and private | Responsive table/detail strategy | No console errors | Rebranded |

## Data and privacy checks

- Public signup creates only a student role and requires no email.
- Username uniqueness and login are case-insensitive.
- Passwords use the versioned bcrypt-SHA256 path.
- Student A cannot read Student B's result, source PDF or research route.
- Anonymous users are redirected from authenticated pages.
- Research pages require the private researcher/owner role.
- Private uploads are served only through ownership-checked routes.
- No API key appears in HTML, tracked source, test output or PDF artifacts.
- The ignored private 0580 scripts were not imported into 0606 profiles.

## Outstanding release risks

- The primary CXSee OCR model was unavailable during the benchmark; fallback
  operation is visible and much slower than an interactive request.
- SQLite, local volume storage and in-process background tasks are suitable
  only for a small single-instance pilot.
- A representative human-marked 0606 grading gold set is still missing.
- Provider data terms, retention and PyMuPDF licensing require owner review.
