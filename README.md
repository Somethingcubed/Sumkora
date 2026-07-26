# Sumkora

Sumkora is an evidence-based Cambridge IGCSE Additional Mathematics 0606
assessment application. Students upload completed papers, inspect
question/criterion evidence, compare attempts and build a longitudinal
strengths-and-weaknesses profile. A separate private researcher workbench
preserves model runs, corrections, experiments and privacy-aware exports.

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

- Researcher: `teacher@school.edu` / `teacher123`
- Student: `student` / `student123`

The research credential keeps its inherited email and internal `teacher`
compatibility role, but the active product has no teacher or classroom
experience. New students choose **Create account** and register with only a
username, an optional display name and a password; Sumkora does not ask them
for an email address. The active authentication and student experience can be
switched between English and Simplified Chinese from the persistent `EN / 中文`
control.

The student upload flow has two modes:

- Completed work only: a calibrated estimated score range and learning profile.
- Completed work plus an optional mark scheme: detailed, independently audited
  question-by-question marking.

A separate question paper is not required in either mode.

After analysis, the student learning loop includes:

- clickable skill pages with a paper-by-paper trend graph and question evidence;
- an automatically maintained Mistake Book with separate printable question
  and answer booklets;
- targeted worksheets of 10, 20, 30, 40 or 50 real past-paper questions,
  selected by weakness, topic, mixed practice or saved mistakes;
- worksheet re-upload, marking and automatic progress updates.

Researchers prepare the practice bank at **Research → Question bank** by
uploading one ZIP containing Cambridge-style question-paper/mark-scheme pairs,
for example `0606_s24_qp_11.pdf` and `0606_s24_ms_11.pdf`. Sumkora pairs the
files, separates top-level questions while keeping dependent subparts
together, extracts the original PDF question/answer assets, classifies them
and exposes uncertain items for human review. A separate manual sorting step
is not required.

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
