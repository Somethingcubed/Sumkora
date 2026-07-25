# Migration notes

## Preserved

The FastAPI/Jinja monolith, login/session pattern, classes, assignments,
uploads, PDF rendering, OCR adapters, grading compatibility path, teacher
review, reports, analytics module, localization and visual design were
preserved. The imported checkpoint is Git commit `00b0ed3`.

## Added or substantially extended

- `assessment.py`: criterion compatibility adapter, diagnoses, score ranges
  and longitudinal 0606 evidence model.
- `pipeline.py`: persisted processing stages and failure handling.
- `paper_packs.py`: versioned supplied-pack registration/parser.
- `math_checks.py`: deterministic symbolic checks.
- `storage.py`: traversal-safe local adapter with a production replacement
  boundary.
- Student history/comparison/skills/question pages and research workbench.

Core files `db.py`, `main.py`, `auth.py`, `ocr.py`, `pdf_utils.py`,
`analytics.py` and templates were extended rather than rewritten.

## Database migration

`init_db()` creates new normalized tables and adds columns to legacy SQLite
tables. It also backfills legacy user roles. Migrations are additive and keep
the old records. There is no destructive automatic conversion and no Alembic
history yet.

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

## Legacy 0580 handling

Legacy 0580 classes, assignments, practice records and importer code remain
untouched. New assignment defaults and seeds are 0606. Student dashboards,
attempt history and learner-model rebuilds explicitly select
`a.syllabus_code = '0606'`; legacy attempts are not relabeled as 0606.
Teacher/research audit views may still expose legacy rows for migration.

## Rollback

The safest rollback is a separate checkout of `00b0ed3` with a copied pre-
upgrade database and upload directory. Do not point the older code at a
database after new migrations without restoring that backup. The working
branch can be discarded only after preserving any new owner-entered data.
