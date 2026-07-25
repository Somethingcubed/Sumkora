# IGCSE 0580 Math Tracker

Python web app for Cambridge IGCSE 0580 Mathematics teachers and students.

What it does:

- teacher/student login
- classes and assignments
- handwritten PDF upload
- automatic AI/OCR grading with teacher exception correction
- student analytics and review recommendations
- printable teacher/student PDF reports
- English/Chinese UI toggle

The current default AI path is:

```text
CXSee Qwen3-VL OCR + Qwen3-VL grading + automatic finalization
```

## Quick Start

```bash
cd "/Users/oscar/Desktop/IGCSE Math AnAn"
pip3 install -r requirements.txt
python3 run.py
```

Open:

```text
http://127.0.0.1:8000
```

Demo accounts:

- teacher: `teacher@school.edu` / `teacher123`
- student: `student@school.edu` / `student123`

## Read This First

Primary handoff and audit document:

- [docs/master_handoff_spec.md](/Users/oscar/Desktop/IGCSE%20Math%20AnAn/docs/master_handoff_spec.md)

Reusable analytics/demo testing guide:

- [docs/analytics_test_harness.md](/Users/oscar/Desktop/IGCSE%20Math%20AnAn/docs/analytics_test_harness.md)

Detailed dated project changelog:

- [docs/project_changelog.md](/Users/oscar/Desktop/IGCSE%20Math%20AnAn/docs/project_changelog.md)

Prompt to give another AI for a harsh research-backed audit:

- [docs/external_research_audit_prompt.md](/Users/oscar/Desktop/IGCSE%20Math%20AnAn/docs/external_research_audit_prompt.md)

If a new AI or engineer is reviewing this project, the master handoff spec is the source of truth. It contains:

- current architecture
- current route inventory
- database schema and invariants
- page-by-page UI behavior
- OCR and grading logic
- analytics logic
- printable report behavior
- scripts and demo data
- current risks and audit targets

## Current Stack

- FastAPI
- SQLite
- Jinja2
- PyMuPDF
- ReportLab
- Tailwind via CDN

## Important Files

- [main.py](/Users/oscar/Desktop/IGCSE%20Math%20AnAn/main.py)
- [db.py](/Users/oscar/Desktop/IGCSE%20Math%20AnAn/db.py)
- [grading.py](/Users/oscar/Desktop/IGCSE%20Math%20AnAn/grading.py)
- [ocr.py](/Users/oscar/Desktop/IGCSE%20Math%20AnAn/ocr.py)
- [analytics.py](/Users/oscar/Desktop/IGCSE%20Math%20AnAn/analytics.py)
- [reports.py](/Users/oscar/Desktop/IGCSE%20Math%20AnAn/reports.py)
- [config.py](/Users/oscar/Desktop/IGCSE%20Math%20AnAn/config.py)

## Useful Scripts

Analytics demo rebuild:

```bash
python3 scripts/analytics_demo.py
```

Tiny grading smoke test:

```bash
python3 scripts/demo_flow.py
```

Past-paper ingest:

```bash
python3 scripts/ingest.py
```

Future real-data folder validation:

```bash
python3 scripts/real_data_checklist.py
```

## Config Notes

Configuration is read by [config.py](/Users/oscar/Desktop/IGCSE%20Math%20AnAn/config.py) from environment variables or a local `.env` file.
Start from [.env.example](/Users/oscar/Desktop/IGCSE%20Math%20AnAn/.env.example) and keep real keys out of git.

Current default provider settings:

```text
AI_PROVIDER=cxsee_qwen
OCR_PROVIDER=cxsee_vl
CXSEE_OCR_MODEL=qwen3-vl-plus
CXSEE_MARKING_MODEL=qwen3-vl-plus
```

Important:

- real API keys and `SECRET_KEY` belong in `.env` or shell environment variables
- the previously exposed CXSee key should be rotated before real use
- this project is still local-first and not production hardened
