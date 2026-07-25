# Numera demo guide

## 1. Start the application

```bash
cd "/Users/oscar/Desktop/Math /IGCSE Math AnAn"
pnpm build
.venv/bin/python scripts/seed_0606_demo.py
.venv/bin/uvicorn main:app --host 127.0.0.1 --port 8000
```

Open `http://127.0.0.1:8000`.

## 2. Student journey

1. Sign in with `student@school.edu` / `student123`.
2. On **My dashboard**, inspect the three 0606 demo papers, latest/average
   scores, trajectory, evidence-backed strengths and explicit untested count.
3. Open **Papers** to inspect every registered 0606 attempt.
4. To exercise upload/processing, open a published assignment, select a PDF,
   submit it and watch validation through report-generation on the processing
   page. External OCR needs a valid `.env`; deterministic tests disable it.
5. Open `[Numera 0606 Demo] Paper C`. Inspect the score, score-range cards,
   question marks and marks-lost groups.
6. Open one question card to inspect criterion decisions, evidence,
   confidence, warnings and related attempts.
7. Open **Compare**, select Paper A and Paper C, and compare normalized scores,
   marks lost and comparability warnings.
8. Open **Skills**. Confirm differentiation is `improving`; integration is
   evidence-backed but not called strong; untouched taxonomy skills remain
   `untested`.

## 3. Researcher journey

1. Log out and sign in with `teacher@school.edu` / `teacher123`.
2. Open **Research** from the navigation.
3. Inspect the provider-health card and recent OCR/model-run metadata.
4. Inspect the 0606 pack table. Use **Ingest supplied packs** only when the
   ignored local official-paper directory is present.
5. If an uncertain decision exists, enter a human mark, reason and evidence
   note. The correction is appended; the original model decision remains.
6. Use the recent-runs table to compare model/prompt/status/duration records.
   A full side-by-side regrade/A-B screen is not implemented yet.
7. Register an experiment with a question and hypothesis. This creates the
   experiment record; automated experiment execution is future work.
8. Review failure/uncertainty counts. A dedicated failure gallery is not yet
   implemented.
9. Download pseudonymized CSV or JSONL exports. Student identifiers are
   deterministic hashes and raw private PDF content is excluded.

## 4. Deterministic evidence

`scripts/seed_0606_demo.py` is additive/idempotent and creates the scenario:

- Paper A: differentiation error → early concern.
- Paper B: repeated error → recurring concern.
- Paper C: success → improving.

The same transitions are asserted in `tests/test_numera_v2.py`.
