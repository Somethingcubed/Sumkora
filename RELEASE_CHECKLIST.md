# Sumkora release checklist

Updated: 25 July 2026

- [x] Production CSS build succeeds.
- [x] Additive database initialization succeeds; this release adds no
  destructive schema migration.
- [x] Rollback path exists through the previous Railway deployment and Git
  checkpoint `1a3e9e4`.
- [x] Student sign-up works without email.
- [x] Student login works case-insensitively.
- [x] Researcher login works and cannot be created publicly.
- [x] Student data and PDF access are isolated by owner.
- [x] Three-file upload works for custom papers.
- [x] Invalid, duplicate and Unicode-named upload cases are checked.
- [x] Live CXSee OCR completes through the recorded fallback path.
- [x] Analysis completes and persists.
- [x] Failed analysis presents a safe retry path.
- [x] Paper results and immutable reruns save.
- [x] Longitudinal progress updates.
- [x] Paper comparison works.
- [x] Student and research PDF exports work and use Sumkora filenames.
- [x] Principal mobile/tablet/desktop routes have no horizontal overflow.
- [x] Browser console is clean on inspected routes.
- [x] Local backend has no unexplained request errors.
- [x] No secrets, private PDFs or production database are tracked.
- [x] Production environment variables are documented.
- [x] Principal pages and both report types were visually inspected.
- [x] Known limitations are documented.
- [ ] Verified release candidate is deployed to `https://sumkora.com`.
- [ ] Post-deployment sign-up/login, existing data and export smoke tests pass.
