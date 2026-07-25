# Migration notes

## Preserved foundations

The FastAPI/Jinja monolith, login/session implementation, PDF rendering, OCR
adapters, grading compatibility path, reports, analytics module, localization
and visual design were preserved. The imported checkpoint is Git commit
`00b0ed3`.

The existing `teacher@school.edu` account, password verification, session and
legacy `users.role = 'teacher'` value remain for compatibility. Authorization
maps that account to the private researcher experience. The visible product
calls it Researcher.

## Added or substantially extended

- `assessment.py`: criterion compatibility adapter, diagnoses, score ranges
  and longitudinal 0606 evidence model.
- `pipeline.py`: persisted processing stages and failure handling.
- `paper_packs.py`: versioned supplied-pack registration/parser.
- `math_checks.py`: deterministic symbolic checks.
- `storage.py`: traversal-safe local adapter with a production replacement
  boundary.
- Student history/comparison/skills/question pages and research workbench.
- `self_service.py`: student-owned question-paper, answer-script and
  mark-scheme ingestion; metadata review; immutable analysis versions; direct
  analysis and longitudinal profile integration.
- Dedicated OCR, grading, failures, experiments, student-model and taxonomy
  research surfaces.

Core files `db.py`, `main.py`, `auth.py`, `ocr.py`, `pdf_utils.py`,
`analytics.py` and templates were extended rather than rewritten.

## Teacher/classroom retirement

The active teacher product is disabled, not destructively deleted:

- every `/teacher` route is intercepted and redirected to `/research` for a
  researcher, or to login otherwise;
- legacy class, enrollment, assignment, teacher-review and classroom-report
  links are absent from active navigation;
- legacy student assignment-upload URLs redirect to `/student/analyse`;
- new student papers do not reference a class or assignment;
- existing legacy results remain reachable to their owning student for
  historical continuity.

The old route handlers, templates, tables and fields remain in the repository
and SQLite schema as archived compatibility code. In particular `classes`,
`class_students`, `assignments`, `submissions`, `users.role`, and historic
teacher-review fields have not been dropped. A later Alembic/PostgreSQL
migration should first copy any retained historic submissions to explicit
student-owned records, verify report parity, then remove the archived code and
columns in a separately reversible release.

## Database migration

`init_db()` creates new normalized tables and adds columns to legacy SQLite
tables. It also backfills legacy user roles. Migrations are additive and keep
the old records. New core tables include `student_papers`,
`paper_analysis_versions`, immutable `analysis_ocr_pages`,
`analysis_question_results`, separate `analysis_human_corrections`,
`analysis_skill_observations`, `research_experiment_runs`,
`research_dataset_selections`, `research_failure_cases`, and
`taxonomy_versions`. There is no destructive automatic conversion and no
Alembic history yet.

Before any production migration:

1. stop writers;
2. copy `data/app.db` and `data/uploads`;
3. verify SHA-256 hashes;
4. migrate into PostgreSQL with explicit scripts;
5. validate counts, foreign keys and ownership queries;
6. keep the SQLite copy read-only until acceptance.

## Authentication changes

Signed sessions now have a maximum age; production cookies can be Secure and
SameSite; trusted-host/security-header and same-origin POST middleware were
added. Multi-role authorization is stored in `user_roles`. The old `users.role`
column remains for compatibility.

The additive SQLite migration also adds nullable `username`,
`username_normalized` and `recovery_code_hash` columns plus a partial unique
index on normalized usernames. Valid, unique legacy student email local-parts
are backfilled as usernames. New public students receive a UUID-based internal
placeholder in the still-required legacy `email` column; it is never requested
from or shown to the student. A later schema migration can make that column
nullable after all compatibility queries have been removed.

New password values are prefixed `bcrypt-sha256$`: the UTF-8 password is first
reduced with SHA-256 and the digest is then processed by bcrypt. Verification
still accepts the inherited raw bcrypt records, so existing credentials remain
valid. Recovery codes are normalized and stored as HMAC-SHA-256 digests keyed
by the application secret; a successful reset clears the digest.

## Legacy records

Legacy 0580 classes, assignments, practice records and importer code remain
available for audit and historic student access. They are not relabelled,
silently copied or shown as active classes/assignments. New direct uploads may
be official 0606 papers, mocks or custom mathematics papers; detected metadata
is editable before analysis.

## Rollback

The safest rollback is a separate checkout of `00b0ed3` with a copied pre-
upgrade database and upload directory. Do not point the older code at a
database after new migrations without restoring that backup. The working
branch can be discarded only after preserving any new owner-entered data.
