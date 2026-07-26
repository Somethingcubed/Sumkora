import json

import fitz
import pytest

import document_assessment
from document_assessment import AssessmentValidationError, validate_assessment


def valid_assessment(mode="detailed"):
    status = "graded" if mode == "detailed" else "estimated"
    return {
        "assessment_mode": mode,
        "paper_title": "Mathematics paper",
        "syllabus_code": "0606",
        "paper_reference": "13",
        "total_max_marks": 3,
        "estimated_score_min": 2,
        "estimated_score": 2,
        "estimated_score_max": 2 if mode == "detailed" else 3,
        "questions": [
            {
                "label": "Q1",
                "question_text": "Differentiate.",
                "maximum_marks": 3,
                "awarded_mark": 2,
                "status": status,
                "confidence": 0.9,
                "evidence_pages": [2],
                "evidence_quote": "2x",
                "rationale": "Correct method with one missing simplification.",
                "topic": "Calculus",
                "skill": "differentiation",
                "improvement": "Finish the simplification.",
            }
        ],
        "strengths": ["Uses the correct method."],
        "weaknesses": ["Final simplification."],
        "recommendations": ["Check the final line."],
        "warnings": [],
    }


def make_pdf(path, text):
    document = fitz.open()
    document.new_page().insert_text((72, 72), text)
    document.save(path)
    document.close()


def test_validator_rejects_wrong_page_and_positive_mark_for_blank_evidence():
    result = valid_assessment()
    result["questions"][0]["evidence_pages"] = [99]
    result["questions"][0]["rationale"] = "The page is blank."
    with pytest.raises(AssessmentValidationError) as exc:
        validate_assessment(result, mode="detailed", completed_work_pages=2)
    message = str(exc.value)
    assert "invalid completed-work page" in message
    assert "awards marks while describing missing or wrong evidence" in message


def test_validator_preserves_ungraded_as_null_instead_of_zero():
    result = valid_assessment("estimate")
    item = result["questions"][0]
    item.update(
        {
            "maximum_marks": None,
            "awarded_mark": None,
            "status": "ungraded",
            "evidence_pages": [],
            "evidence_quote": "",
        }
    )
    result.update(
        {
            "total_max_marks": None,
            "estimated_score_min": None,
            "estimated_score": None,
            "estimated_score_max": None,
        }
    )
    with pytest.raises(AssessmentValidationError) as exc:
        validate_assessment(result, mode="estimate", completed_work_pages=2)
    assert "overall score range is incomplete" in str(exc.value)
    assert "ungraded but has an awarded mark" not in str(exc.value)


def test_validator_derives_detailed_range_from_uncertain_questions():
    result = valid_assessment()
    result["questions"][0]["status"] = "uncertain"
    validated = validate_assessment(
        result,
        mode="detailed",
        completed_work_pages=2,
    )
    assert validated["estimated_score_min"] == 0
    assert validated["estimated_score"] == 2
    assert validated["estimated_score_max"] == 3


def test_provider_repairs_invalid_structured_result_once(tmp_path, monkeypatch):
    answer = tmp_path / "answer.pdf"
    make_pdf(answer, "Q1 answer")
    invalid = valid_assessment("estimate")
    invalid["questions"][0]["evidence_pages"] = [8]
    corrected = valid_assessment("estimate")
    corrected["questions"][0]["evidence_pages"] = [1]
    calls = []

    def fake_post(_url, payload, **_kwargs):
        calls.append(payload)
        body = invalid if len(calls) == 1 else corrected
        return {
            "id": f"response-{len(calls)}",
            "output": [
                {
                    "content": [
                        {"type": "output_text", "text": json.dumps(body)}
                    ]
                }
            ],
            "usage": {"total_tokens": 10},
        }

    monkeypatch.setattr(document_assessment.config, "CXSEE_API_KEY", "test-key")
    monkeypatch.setattr(document_assessment, "api_post_json", fake_post)
    result, metadata = document_assessment.assess_documents(str(answer))
    assert len(calls) == 2
    assert result["estimated_score"] == 2
    assert metadata["attempts"] == 2
    repair_text = calls[1]["input"][0]["content"][0]["text"]
    assert "invalid completed-work page" in repair_text


def test_independent_audit_corrects_semantic_mark_and_recalculates_total():
    result = validate_assessment(
        valid_assessment("detailed"),
        mode="detailed",
        completed_work_pages=2,
    )
    audited = document_assessment._apply_audit(
        result,
        {
            "checks": [
                {
                    "label": "Q1",
                    "verdict": "corrected",
                    "corrected_mark": 1,
                    "confidence": 0.98,
                    "student_answer": "r = 39",
                    "expected_answer": "r = 19",
                    "reason": "The visible final value is wrong; only method credit remains.",
                }
            ],
            "warnings": [],
        },
        completed_work_pages=2,
    )
    assert audited["questions"][0]["awarded_mark"] == 1
    assert audited["questions"][0]["audit"]["student_answer"] == "r = 39"
    assert audited["estimated_score"] == 1


def test_independent_audit_must_cover_every_question():
    result = valid_assessment("detailed")
    with pytest.raises(AssessmentValidationError) as exc:
        document_assessment._apply_audit(
            result,
            {"checks": [], "warnings": []},
            completed_work_pages=2,
        )
    assert "audit omitted labels" in str(exc.value)
