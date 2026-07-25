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

1. Sign in with `student` / `student123`, or choose **Create account** to make
   a student account without an email address.
2. Choose **Analyse paper**.
3. Upload a question-paper PDF, completed answer-script PDF or image, and
   mark-scheme PDF. No title, paper metadata, class or assignment is needed.
4. Analysis starts immediately. Numera reads the documents, detects naturally
   ordered top-level questions and matches answer pages during OCR.
5. Follow the processing stages to the paper result. Inspect the score range,
   marks lost, question evidence and concise recommendations.
6. Choose **Run a new version** to reuse or replace any document. The new
   version starts automatically; version 1 remains available from the result
   page.
7. Open **My papers**, **Compare**, and **Strengths** to see the attempt in its
   paper and longitudinal contexts.
8. Download the student PDF report from the result page.
9. Use the persistent **EN / 中文** control to switch the student interface.

## 3. Researcher journey

1. Log out and sign in with `teacher@school.edu` / `teacher123`.
2. You land directly in the private **Research overview**; there are no
   classes, assignments or teacher queues.
3. Create two experiments, configure model/prompt/preprocessing parameters,
   duplicate one, and record runs. Run cards show configuration snapshots,
   sample sizes and available human-agreement metrics.
4. Open **OCR** to inspect immutable OCR output and save a separate corrected
   transcription and evaluation label.
5. Open **Grading** to compare student evidence, the scheme and AI decision,
   then add a human label. The original AI mark is not overwritten.
6. Inspect and tag **Failures**, rebuild derived profiles in **Student models**,
   and create a versioned taxonomy record.
7. Export CSV, JSON or JSONL in identified, pseudonymized or anonymized mode.
   Raw private PDFs are excluded.
8. Download a technical experiment PDF from an experiment detail page.

## 4. Deterministic evidence

`scripts/seed_0606_demo.py` is additive/idempotent and creates the scenario:

- Paper A: differentiation error → early concern.
- Paper B: repeated error → recurring concern.
- Paper C: success → improving.

The same transitions are asserted in `tests/test_numera_v2.py`.
