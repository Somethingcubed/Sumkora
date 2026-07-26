import os
import sys
import tempfile
from pathlib import Path

import pytest


TEST_ROOT = tempfile.mkdtemp(prefix="sumkora-tests-")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ["DB_PATH"] = os.path.join(TEST_ROOT, "test.db")
os.environ["UPLOAD_DIR"] = os.path.join(TEST_ROOT, "uploads")
os.environ["SECRET_KEY"] = "test-secret-key-that-is-long-enough-for-sessions"
os.environ["OCR_ENABLED"] = "false"
os.environ["CXSEE_API_KEY"] = ""
os.environ["OPENAI_API_KEY"] = ""
os.environ["DEEPSEEK_API_KEY"] = ""
os.environ["COOKIE_SECURE"] = "false"


@pytest.fixture(autouse=True)
def stub_whole_document_assessment(monkeypatch):
    """Keep the application suite deterministic and free of paid API calls."""
    import self_service

    def fake_assessment(answer_path, scheme_path=None, **_kwargs):
        mode = "detailed" if scheme_path else "estimate"
        status = "graded" if scheme_path else "estimated"
        result = {
            "assessment_mode": mode,
            "paper_title": "Independent mathematics paper",
            "syllabus_code": "0606",
            "paper_reference": "test",
            "total_max_marks": 2.0,
            "estimated_score_min": 2.0 if scheme_path else 1.0,
            "estimated_score": 2.0,
            "estimated_score_max": 2.0,
            "questions": [
                {
                    "label": "Q1",
                    "question_text": "Differentiate x squared.",
                    "maximum_marks": 2.0,
                    "awarded_mark": 2.0,
                    "status": status,
                    "confidence": 0.94,
                    "evidence_pages": [1],
                    "evidence_quote": "2x",
                    "rationale": "The visible derivative is correct.",
                    "topic": "Calculus",
                    "skill": "differentiation",
                    "improvement": "Continue showing each differentiation step.",
                }
            ],
            "strengths": ["Differentiation"],
            "weaknesses": [],
            "recommendations": ["Keep showing complete working."],
            "warnings": [],
        }
        metadata = {
            "provider": "test",
            "model": "whole-document-test-model",
            "prompt_version": "whole-document-assessment-v1",
            "duration_ms": 10,
            "attempts": 1,
            "usage": {},
        }
        return result, metadata

    monkeypatch.setattr(self_service, "assess_documents", fake_assessment)
