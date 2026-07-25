# Analytics Test Harness

For full product, UI, route, grading, and architecture details, read:

- [docs/master_handoff_spec.md](/Users/oscar/Desktop/IGCSE%20Math%20AnAn/docs/master_handoff_spec.md)

This document is the reusable testing guide for the analytics tracker. It is designed for two stages:

1. Synthetic analytics testing now, independent of OCR quality.
2. Real handwritten PDF intake later, when school data arrives.

The important rule is that analytics trusts finalized marks. OCR and AI grading can help produce suggestions, but the dashboards should be tested against teacher-confirmed `final_mark` values.

## Quick Start

From the project root:

```bash
python3 scripts/analytics_demo.py
python3 run.py
```

Open `http://127.0.0.1:8000`.

Teacher:

```text
teacher@school.edu / teacher123
```

Demo students:

```text
creative.strong@demo.local / student123
creative.weak@demo.local / student123
creative.improving@demo.local / student123
```

The script is idempotent. Running it again resets the local demo database to exactly one teacher class, three creative demo students, five assignments, fifteen finalized submissions, and seventy-five finalized grade rows.

Important: this is intentionally a destructive local demo reset. It deletes all existing classes, assignments, submissions, and student accounts before rebuilding the creative scenario. It keeps the teacher account.

## Demo Scenario

Class:

```text
Creative Analytics Test Class
```

Assignments:

```text
[Creative Text Demo] 01 - Number Fluency
[Creative Text Demo] 02 - Algebra Equations
[Creative Text Demo] 03 - Probability and Statistics
[Creative Text Demo] 04 - Trigonometry and Mensuration
[Creative Text Demo] 05 - Mixed Word Problems
```

The questions intentionally cover:

- Number
- Algebra
- Trigonometry
- Probability
- Statistics
- Sequences
- Mensuration

Geometry and graphs are deliberately excluded from this version. The current goal is to test analytics from word-based, text-readable work without OCR or diagram complications.

They include teacher-verified metadata where possible:

- `difficulty_teacher`: easy / medium / hard
- `question_type_tag`: number, solve equation, expand/factorise, probability, statistics, sequences, trigonometry, mensuration
- `subtopic`
- `answer_only_eligible`
- `requires_method_marks`

The script generates simple text PDFs for each submission. The PDF content includes deliberately messy student-style responses:

- correct working
- partial working
- wrong working
- random copied numbers
- omitted final answers
- increasingly organised work for the improving student

## Expected Outcomes

Maya Strong:

- high latest and average score
- strong current trajectory after enough assessments
- few review questions
- mostly strong topic mastery

Leo Improving:

- lower first assignments and clearly stronger later assignments
- improving trend
- review queue focused on harder algebra/trigonometry/mensuration questions
- current trajectory should sit below Maya but above Nina

Nina Needs Practice:

- low scores across assessments
- many omitted/wrong answers
- appears in teacher `Students needing support`
- class analytics should flag basics and reteach topics clearly

## Analytics Checklist

Check each demo student dashboard for:

- latest score
- average score
- score history
- current trajectory
- trend
- topic mastery
- difficulty performance
- question-type performance
- topic + difficulty breakdown
- review queue
- recommended practice

Check the teacher analytics page for:

- students needing support
- topics to reteach
- difficulty performance
- question-type performance
- topic performance table

Check teacher review pages for demo submissions:

- each submission has a generated PDF
- the PDF opens from the review screen
- marks are finalized
- teacher comments explain the intended test behavior

## Real PDF Workflow

Use this folder convention for real batches:

```text
Real Submissions/
  2026-06-Homework-01/
    roster.csv
    assignments.csv
    submissions/
      Alex Student.pdf
      Jamie Lee.pdf
```

Suggested `roster.csv`:

```csv
student_name,email,class_name
Alex Student,alex@example.com,0580 Extended A
Jamie Lee,jamie@example.com,0580 Extended A
```

Suggested `assignments.csv`:

```csv
assignment_title,type,due_date,total_marks
Homework 01,worksheet,2026-06-14,40
```

Before importing anything, run:

```bash
python3 scripts/real_data_checklist.py
```

The checklist is read-only. It reports:

- missing `roster.csv`
- missing `assignments.csv`
- missing `submissions/`
- invalid PDFs
- duplicate roster names/emails
- PDFs with no matching roster student
- roster students with no PDF

## Known Limits

- Handwriting OCR now has a provider-ready cache layer, but real scans still need validation before trusting the output.
- CXSee Qwen3-VL is the default China-compatible V1 path: set `AI_PROVIDER=cxsee_qwen`, `OCR_PROVIDER=cxsee_vl`, and `CXSEE_API_KEY` in local `.env`.
- Google Vision can still be tested by setting `OCR_PROVIDER=google_vision` and `GOOGLE_VISION_API_KEY` in local `.env`.
- Mathpix can be switched on later with `OCR_PROVIDER=mathpix` plus `MATHPIX_APP_ID` / `MATHPIX_APP_KEY`.
- Until real OCR quality is proven, upload real PDFs, let the teacher review/finalize marks, and use analytics from finalized marks.
- The synthetic demo script inserts finalized marks directly so analytics can be tested without API or network dependency.

## Safe Reuse Rules

- Keep demo data tagged with `Creative Text Demo`.
- Do not mix real student accounts with `creative.*@demo.local`.
- Do not run `scripts/analytics_demo.py` against a database containing real student data unless you intentionally want to wipe demo/local class data and rebuild this scenario.
- Prefer running the checklist before importing real PDFs.
