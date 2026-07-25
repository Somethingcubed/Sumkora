# Deployment guide

## Current public-site relationship

`https://numera.coze.site` is a separate 0580-era Next.js/Coze prototype. No
deployment manifest or API configuration in this repository connects to it.
Do not overwrite it without owner approval and a data-migration plan.

## Recommended production architecture

Deploy FastAPI behind HTTPS with managed PostgreSQL, a private S3-compatible
bucket, and a Redis-backed worker queue. Store only object keys in the
database. Use ownership-checked downloads or short-lived signed URLs. Keep
Coze as an optional demo/conversational layer calling a narrowly scoped API
after its privacy and authentication behavior is approved.

## Local/container build

```bash
pnpm install --frozen-lockfile
pnpm build
docker build -t numera:local .
docker run --rm -p 8000:8000 --env-file .env numera:local
```

Without Docker:

```bash
.venv/bin/pip install -r requirements.txt
.venv/bin/uvicorn main:app --host 0.0.0.0 --port 8000
```

## Production variables

Required:

- `APP_ENV=production`
- `SECRET_KEY` as a long random secret
- `COOKIE_SECURE=true`
- `TRUSTED_HOSTS=app.example.com`
- `DB_PATH` only for a single-instance pilot; replace with a PostgreSQL URL
- private object-store endpoint/bucket/access credentials after adapter work
- `CXSEE_API_KEY`, `CXSEE_BASE_URL`
- `CXSEE_OCR_MODEL=qwen-vl-ocr-latest`
- `CXSEE_OCR_FALLBACK_MODELS=qwen-vl-ocr,qwen3-vl-plus`
- timeout/retry/upload limits appropriate to the worker tier

Never put secrets in the image, Git, browser bundle or Coze page.

## Required platform work before public use

1. Add versioned PostgreSQL migrations and convert SQLite queries/adapters.
2. Implement the S3/R2 storage adapter, encryption, retention and deletion.
3. Move `run_analysis_pipeline` to a durable queue with idempotency/retries.
4. Configure TLS, secure cookies, proxy headers, rate limits and monitoring.
5. Add backups and a tested database/object recovery procedure.
6. Review provider contracts/data residency and obtain student/guardian basis.
7. Review/approve parsed mark schemes and calibrate against human marking.
8. Run load, authorization, failure-recovery and deletion tests.

## Domain connection

On a conventional platform, deploy the container, attach PostgreSQL/Redis/
object storage, set environment variables, run migrations, then map the chosen
domain's CNAME/A record to the platform and enforce HTTPS. Add the exact host
to `TRUSTED_HOSTS`.

For Coze, first create a separate staging deployment, configure secrets through
its environment-variable workflow, validate private database/storage and
backup/export behavior, then connect a custom domain using Coze's documented
domain settings. Do not upload real scripts during this evaluation.

## Alternative pilot

A single HTTPS container with a persistent volume can demonstrate the system
to a small owner-controlled group, but SQLite/local files prevent safe
horizontal scaling and complicate recovery. It is not the recommended student
launch architecture.

## Unresolved owner/account actions

- Choose hosting region/vendor and public domain.
- Approve Coze's role or keep the existing prototype unchanged.
- Approve provider student-data terms and retention.
- Provision PostgreSQL, Redis, object storage and deployment credentials.
- Decide retention/deletion policy and user onboarding/account recovery.

No public deployment was performed in this session.
