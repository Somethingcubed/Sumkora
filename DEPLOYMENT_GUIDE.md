# Deployment guide

## Current public deployment

The active public website is `https://sumkora.com`, deployed from this
repository to a single Railway service in Singapore. A separate 0580-era
prototype remains historical and is not part of the deployment.

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
docker build -t sumkora:local .
docker run --rm -p 8000:8000 --env-file .env sumkora:local
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
- `TRUSTED_HOSTS=sumkora.com`
- `DB_PATH` only for a single-instance pilot; replace with a PostgreSQL URL
- private object-store endpoint/bucket/access credentials after adapter work
- `CXSEE_API_KEY`, `CXSEE_BASE_URL`
- `CXSEE_OCR_MODEL=qwen-vl-ocr-latest`
- `CXSEE_OCR_FALLBACK_MODELS=qwen-vl-ocr,qwen3-vl-plus`
- timeout/retry/upload limits appropriate to the worker tier

Never put secrets in the image, Git, browser bundle or Coze page.

## Required platform work before broader public use

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

## Alternative pilot

A single HTTPS container with a persistent volume can demonstrate the system
to a small owner-controlled group, but SQLite/local files prevent safe
horizontal scaling and complicate recovery. It is not the recommended student
launch architecture.

## Unresolved owner/account actions

- Approve provider student-data terms and retention.
- Provision PostgreSQL, Redis, object storage and deployment credentials.
- Decide retention/deletion policy and user onboarding/account recovery.

The current pilot is deployed at `https://sumkora.com`. Production changes are
uploaded manually with the Railway CLI; no automatic Git deployment source is
connected.
