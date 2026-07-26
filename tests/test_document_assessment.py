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
                "question_latex": r"Differentiate \(x^2\).",
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


def test_assessment_contract_requires_complete_math_question_context():
    schema = document_assessment.assessment_schema()
    question_schema = schema["properties"]["questions"]["items"]
    assert "question_text" not in question_schema["properties"]
    context_schema = document_assessment.document_context_schema()
    context_question = context_schema["properties"]["questions"]["items"]
    assert "question_text" in context_question["required"]
    assert "question_latex" not in context_question["properties"]
    prompt = document_assessment._document_context_prompt(
        validate_assessment(
            valid_assessment("detailed"),
            mode="detailed",
            completed_work_pages=2,
        )
    )
    assert "complete readable printed question" in prompt
    assert "repeat its parent stem" in prompt
    assert r"\frac" in prompt


def test_provider_json_parser_repairs_unescaped_tex_without_changing_json_escapes():
    payload = (
        '{"question_latex":"Solve \\(x^2\\) using \\frac{1}{2}.",'
        '"rationale":"Line one.\\nLine two."}'
    )
    parsed = document_assessment._parse_provider_json(payload)
    assert parsed["question_latex"] == r"Solve \(x^2\) using \frac{1}{2}."
    assert parsed["rationale"] == "Line one.\nLine two."


def test_provider_json_parser_accepts_literal_newline_inside_string():
    parsed = document_assessment._parse_provider_json(
        '{"rationale":"Line one.\nLine two."}'
    )
    assert parsed["rationale"] == "Line one.\nLine two."


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


def test_estimate_uses_visible_question_marks_not_inferred_full_paper_total():
    result = valid_assessment("estimate")
    result.update(
        {
            "total_max_marks": 127,
            "estimated_score_min": 90,
            "estimated_score": 100,
            "estimated_score_max": 110,
        }
    )
    validated = validate_assessment(
        result,
        mode="estimate",
        completed_work_pages=2,
    )
    assert validated["total_max_marks"] == 3
    assert validated["estimated_score"] == 2
    assert validated["estimated_score_min"] == 0
    assert validated["estimated_score_max"] == 3


def test_student_maximum_marks_detects_incomplete_question_coverage():
    result = valid_assessment("estimate")
    result["total_max_marks"] = 80
    with pytest.raises(AssessmentValidationError) as exc:
        validate_assessment(
            result,
            mode="estimate",
            completed_work_pages=2,
            expected_maximum_marks=80,
        )
    message = str(exc.value)
    assert "question maximums total 3" in message
    assert "student supplied 80" in message
    prompt = document_assessment._prompt(
        "estimate",
        expected_maximum_marks=80,
    )
    assert "coverage checksum" in prompt
    assert "80 marks" in prompt


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
            "model": "gpt-5.6-terra",
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
    result, metadata = document_assessment.assess_documents(
        str(answer),
        model="gpt-5.6-terra",
    )
    assert len(calls) == 2
    assert result["estimated_score"] == 2
    assert metadata["attempts"] == 2
    assert metadata["provider"] == "cxsee_responses"
    assert metadata["response_id"] == "response-2"
    repair_text = calls[1]["input"][0]["content"][0]["text"]
    assert "invalid completed-work page" in repair_text
    file_part = calls[1]["input"][0]["content"][1]
    assert file_part["type"] == "input_file"
    assert file_part["file_data"].startswith("data:application/pdf;base64,")
    assert calls[1]["max_output_tokens"] == 16384


def test_ocr_transcript_is_sent_to_gpt_as_one_complete_text_input(
    tmp_path, monkeypatch
):
    answer = tmp_path / "answer.pdf"
    make_pdf(answer, "Scanned answer placeholder")
    calls = []

    def fake_post(_url, payload, **kwargs):
        calls.append((payload, kwargs))
        body = valid_assessment("estimate")
        body["questions"][0]["evidence_pages"] = [1]
        return {
            "id": "response-transcript",
            "model": "gpt-5.6-terra",
            "output": [
                {
                    "content": [
                        {
                            "type": "output_text",
                            "text": json.dumps(body),
                        }
                    ]
                }
            ],
            "usage": {"total_tokens": 10},
        }

    monkeypatch.setattr(document_assessment.config, "CXSEE_API_KEY", "test-key")
    monkeypatch.setattr(document_assessment, "api_post_json", fake_post)
    result, _ = document_assessment.assess_documents(
        str(answer),
        model="gpt-5.6-terra",
        completed_work_text=(
            "--- COMPLETED STUDENT WORK, PAGE 1 ---\n"
            "Q1 Student Work: 2x"
        ),
    )

    content = calls[0][0]["input"][0]["content"]
    assert len(content) == 1
    assert content[0]["type"] == "input_text"
    assert "PAGE 1" in content[0]["text"]
    assert "Student Work: 2x" in content[0]["text"]
    assert "input_file" not in content[0]["text"]
    assert calls[0][1]["retries"] == 1
    assert result["questions"][0]["question_latex"] == r"Differentiate \(x^2\)."


def test_qwen_receives_complete_ocr_transcript_without_rendered_images(
    tmp_path, monkeypatch
):
    answer = tmp_path / "answer.pdf"
    make_pdf(answer, "Scanned answer placeholder")
    calls = []

    def fake_post(_url, payload, **_kwargs):
        calls.append(payload)
        body = valid_assessment("estimate")
        body["questions"][0]["evidence_pages"] = [1]
        return {
            "id": "qwen-transcript",
            "model": "qwen3-vl-plus",
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {"content": json.dumps(body)},
                }
            ],
            "usage": {"total_tokens": 10},
        }

    monkeypatch.setattr(document_assessment.config, "CXSEE_API_KEY", "test-key")
    monkeypatch.setattr(document_assessment, "api_post_json", fake_post)
    result, metadata = document_assessment.assess_documents(
        str(answer),
        model="qwen3-vl-plus",
        completed_work_text=(
            "--- COMPLETED STUDENT WORK, PAGE 1 ---\n"
            "Q1 Student Work: 2x"
        ),
    )

    content = calls[0]["messages"][0]["content"]
    assert all(part["type"] == "text" for part in content)
    assert "Student Work: 2x" in content[1]["text"]
    assert calls[0]["max_tokens"] == 16384
    assert metadata["provider"] == "cxsee_qwen_vision"
    assert metadata["render_dpi"] is None
    assert result["estimated_score"] == 2


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


def test_bilingual_feedback_enriches_without_changing_validated_marks():
    result = validate_assessment(
        valid_assessment("estimate"),
        mode="estimate",
        completed_work_pages=2,
    )
    enriched = document_assessment._apply_feedback(
        result,
        {
            "questions": [
                {
                    "label": "Q1",
                    "rationale_zh": "方法正确，但最后一步没有化简。",
                    "improvement": "Complete the final simplification.",
                    "improvement_zh": "完成最后的化简。",
                }
            ],
            "strengths": ["Correct differentiation method."],
            "weaknesses": ["Final simplification."],
            "recommendations": ["Check the final line."],
            "warnings_zh": [],
            "strengths_zh": ["求导方法正确。"],
            "weaknesses_zh": ["最后的化简。"],
            "recommendations_zh": ["检查最后一行。"],
        },
    )
    assert enriched["estimated_score"] == result["estimated_score"]
    assert enriched["questions"][0]["awarded_mark"] == 2
    assert enriched["questions"][0]["rationale_zh"].startswith("方法正确")
    assert enriched["recommendations_zh"] == ["检查最后一行。"]
