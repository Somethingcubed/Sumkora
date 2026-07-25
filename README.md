# Numera

Numera is an evidence-based Cambridge IGCSE Additional Mathematics 0606
assessment application. Students upload completed papers, inspect
question/criterion evidence, compare attempts and build a longitudinal
strengths-and-weaknesses profile. Teachers review exceptions; private
researcher tools preserve model runs, corrections and pseudonymized exports.

## Local start

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env
pnpm install --frozen-lockfile
pnpm build
.venv/bin/uvicorn main:app --host 127.0.0.1 --port 8000
```

Open `http://127.0.0.1:8000`.

Development accounts:

- Teacher/researcher: `teacher@school.edu` / `teacher123`
- Student: `student@school.edu` / `student123`

Add the deterministic longitudinal demo with:

```bash
.venv/bin/python scripts/seed_0606_demo.py
```

Run verification:

```bash
.venv/bin/pytest -q
.venv/bin/python scripts/regression_checks.py
.venv/bin/python scripts/demo_flow.py
```

Read `STATUS.md` before treating the project as production-ready. Private
papers, uploads, `.env` and the local database are intentionally ignored.
