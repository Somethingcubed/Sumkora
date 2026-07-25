# Architecture decision v2

## Decision

Keep the current FastAPI application as the upgrade base for this iteration.
For production, deploy it as a conventional web/API service backed by
PostgreSQL, private S3-compatible object storage and a durable worker queue.
Use Coze only as an optional public demo or future conversational/workflow
surface, not as the source of truth for private assessment data.

## Why

The repository already has working auth, classroom, upload, grading, report
and analytics behavior. Rebuilding would increase regression risk and discard
tested teacher workflows. FastAPI routes also provide direct backend ownership
enforcement, which is essential for student scripts.

SQLite/local files and in-process jobs are intentionally retained for local
development. They do not meet multi-instance durability requirements.

## Target components

```text
Browser
  -> HTTPS reverse proxy / application platform
  -> FastAPI web/API instances
       -> PostgreSQL (users, papers, decisions, profiles, audit)
       -> private S3/R2 bucket (scripts and rendered pages)
       -> Redis/queue -> OCR/marking workers
       -> CXSee-compatible model API
```

The browser never receives provider credentials. File downloads are served by
an ownership-checked route or short-lived signed URLs. Workers write immutable
model runs and append corrections rather than overwriting source evidence.

## Data model boundary

- `paper_packs`, `paper_questions`, `marking_criteria`: versioned assessment
  truth and parser provenance.
- `submissions`, `ocr_pages`, `model_runs`, `criterion_decisions`: evidence and
  model execution history.
- `skill_observations`, `student_skill_states`: derived, rebuildable learner
  model.
- `human_corrections`, `research_experiments`, `audit_logs`: private research
  lineage.

## Rejected options

- Full rewrite: unnecessary and risky while most core workflows already work.
- Browser-only marking: exposes credentials and cannot protect evidence.
- Coze as the immediate system of record: the live prototype is disconnected
  from this repository, and its suitability for the project's full private
  data, job and audit requirements has not been established.

## Consequences

The current Docker image is deployable for a single-instance pilot, but public
student use is blocked until PostgreSQL/object storage/worker adapters,
migrations, privacy approval and operational monitoring are complete.
