import io
import json
import urllib.error
import base64

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


def make_pdf(path, text, pages=1):
    document = fitz.open()
    for index in range(pages):
        document.new_page().insert_text((72, 72), f"{text} page {index + 1}")
    document.save(path)
    document.close()


def make_image_only_pdf(path, pages=2):
    image = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 1280, 1707), False)
    image.clear_with(245)
    jpeg = image.tobytes("jpeg", jpg_quality=82)
    document = fitz.open()
    for _index in range(pages):
        image_document = fitz.open(stream=jpeg, filetype="jpeg")
        page_pdf = fitz.open("pdf", image_document.convert_to_pdf())
        document.insert_pdf(page_pdf)
        page_pdf.close()
        image_document.close()
    document.save(path)
    document.close()
    return jpeg


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


def test_student_maximum_marks_checks_detailed_mode_too():
    result = valid_assessment("detailed")
    with pytest.raises(AssessmentValidationError) as exc:
        validate_assessment(
            result,
            mode="detailed",
            completed_work_pages=2,
            expected_maximum_marks=4,
        )
    assert "question maximums total 3" in str(exc.value)
    assert "student supplied 4" in str(exc.value)


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
    repair_content = calls[1]["input"][0]["content"]
    assert len(repair_content) == 1
    assert repair_content[0]["type"] == "input_text"
    assert "PREVIOUS WHOLE-PAPER ASSESSMENT JSON" in repair_content[0]["text"]
    assert "invalid completed-work page" in repair_content[0]["text"]
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
    assert calls[0][1]["retries"] == 0
    assert result["questions"][0]["question_latex"] == r"Differentiate \(x^2\)."


def test_retryable_provider_failure_reconnects_complete_pdf_once(
    tmp_path, monkeypatch
):
    answer = tmp_path / "answer.pdf"
    make_pdf(answer, "Q1 answer")
    calls = []
    progress = []

    def fake_post(_url, payload, **kwargs):
        calls.append((payload, kwargs))
        if len(calls) == 1:
            raise urllib.error.HTTPError(
                "https://provider.invalid/v1/responses",
                500,
                "Internal Server Error",
                {},
                None,
            )
        body = valid_assessment("estimate")
        body["questions"][0]["evidence_pages"] = [1]
        return {
            "id": "response-after-reconnect",
            "model": payload["model"],
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
    monkeypatch.setattr(document_assessment.time, "sleep", lambda _seconds: None)

    result, metadata = document_assessment.assess_documents(
        str(answer),
        reasoning_effort="medium",
        progress_callback=lambda stage, detail: progress.append((stage, detail)),
    )

    assert len(calls) == 2
    assert all(call[1]["retries"] == 0 for call in calls)
    first_content = calls[0][0]["input"][0]["content"]
    assert first_content[1]["type"] == "input_text"
    assert first_content[2]["type"] == "input_image"
    retry_content = calls[1][0]["input"][0]["content"]
    assert retry_content[1]["type"] == "input_text"
    assert retry_content[2]["type"] == "input_image"
    assert metadata["transport_attempts"] == 2
    assert len(metadata["transport_timeouts"]) == 2
    assert metadata["transport_timeouts"] == [70, 45]
    assert metadata["transport_reasoning_efforts"] == ["medium", "low"]
    assert metadata["transport_models"] == ["gpt-5.4-mini", "gpt-5.4-mini"]
    assert metadata["fallback_used"] is True
    assert calls[0][0]["reasoning"]["effort"] == "medium"
    assert calls[1][0]["reasoning"]["effort"] == "low"
    assert metadata["provider"] == "cxsee_responses_images"
    assert metadata["render_dpi"] == 110
    assert any(stage == "provider_retry" for stage, _detail in progress)
    assert result["estimated_score"] == 2


def test_fast_image_transport_retries_without_falling_back_to_native_pdf(
    tmp_path, monkeypatch
):
    answer = tmp_path / "scanned-answer.pdf"
    make_pdf(answer, "Q1 handwritten answer")
    calls = []

    def fake_post(_url, payload, **kwargs):
        calls.append((payload, kwargs))
        if len(calls) == 1:
            raise urllib.error.HTTPError(
                "https://provider.invalid/v1/responses",
                500,
                "Internal Server Error",
                {},
                None,
            )
        body = valid_assessment("estimate")
        body["questions"][0]["evidence_pages"] = [1]
        return {
            "id": "response-after-image-fallback",
            "model": "gpt-5.5",
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
    monkeypatch.setattr(document_assessment.time, "sleep", lambda _seconds: None)

    result, metadata = document_assessment.assess_documents(
        str(answer),
        model="gpt-5.4-mini",
    )

    assert len(calls) == 2
    assert calls[0][0]["input"][0]["content"][1]["type"] == "input_text"
    assert calls[0][0]["input"][0]["content"][2]["type"] == "input_image"
    retry_content = calls[1][0]["input"][0]["content"]
    assert retry_content[1]["type"] == "input_text"
    assert retry_content[2]["type"] == "input_image"
    assert metadata["provider"] == "cxsee_responses_images"
    assert metadata["transport_attempts"] == 2
    assert result["estimated_score"] == 2


def test_fast_timeout_switches_models_within_two_minute_budget(
    tmp_path, monkeypatch
):
    answer = tmp_path / "timeout-answer.pdf"
    make_pdf(answer, "Q answer", pages=7)
    clock = [0.0]
    calls = []

    def fake_post(_url, payload, **kwargs):
        calls.append((payload, kwargs))
        if len(calls) == 1:
            clock[0] += 71
            raise TimeoutError("The read operation timed out")
        clock[0] += 40
        body = valid_assessment("estimate")
        body["questions"][0]["evidence_pages"] = [1]
        return {
            "id": "fallback-response",
            "model": payload["model"],
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
    monkeypatch.setattr(document_assessment.config, "WHOLE_DOCUMENT_CONTEXT_ENABLED", False)
    monkeypatch.setattr(document_assessment.config, "WHOLE_DOCUMENT_FEEDBACK_ENABLED", False)
    monkeypatch.setattr(document_assessment, "api_post_json", fake_post)
    monkeypatch.setattr(document_assessment.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(
        document_assessment.time,
        "sleep",
        lambda seconds: clock.__setitem__(0, clock[0] + seconds),
    )

    result, metadata = document_assessment.assess_documents(
        str(answer),
    )

    assert [call[0]["model"] for call in calls] == [
        "gpt-5.4-mini",
        "gpt-5.4-mini",
    ]
    assert metadata["transport_timeouts"] == [70, 45]
    assert metadata["fallback_used"] is True
    assert metadata["duration_ms"] == 112000
    assert result["estimated_score"] == 2


def test_short_detailed_paper_uses_fast_path(tmp_path, monkeypatch):
    answer = tmp_path / "short-detailed-answer.pdf"
    scheme = tmp_path / "short-mark-scheme.pdf"
    make_pdf(answer, "Q answer", pages=3)
    make_pdf(scheme, "Q scheme", pages=4)
    calls = []

    def fake_post(_url, payload, **kwargs):
        calls.append((payload, kwargs))
        body = valid_assessment("detailed")
        body["questions"][0]["evidence_pages"] = [1]
        return {
            "id": "fast-detailed-response",
            "model": payload["model"],
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
    monkeypatch.setattr(document_assessment.config, "WHOLE_DOCUMENT_CONTEXT_ENABLED", False)
    monkeypatch.setattr(document_assessment.config, "WHOLE_DOCUMENT_FEEDBACK_ENABLED", False)
    monkeypatch.setattr(document_assessment, "api_post_json", fake_post)

    result, metadata = document_assessment.assess_documents(
        str(answer),
        str(scheme),
    )

    assert len(calls) == 1
    assert calls[0][0]["reasoning"]["effort"] == "low"
    assert calls[0][0]["model"] == "gpt-5.5"
    assert calls[0][1]["timeout"] == 70
    assert metadata["fast_detailed_path"] is True
    assert metadata["render_dpi"] == 110
    assert metadata["target_seconds"] == 120
    assert result["estimated_score"] == 2


def test_compact_paper_uses_low_reasoning_fast_path(tmp_path, monkeypatch):
    answer = tmp_path / "compact-answer.pdf"
    make_pdf(answer, "Q1 answer")
    calls = []

    def fake_post(_url, payload, **_kwargs):
        calls.append(payload)
        body = valid_assessment("estimate")
        body["questions"][0]["evidence_pages"] = [1]
        return {
            "id": "compact-response",
            "model": "gpt-5.5",
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
    monkeypatch.setattr(document_assessment.config, "WHOLE_DOCUMENT_CONTEXT_ENABLED", False)
    monkeypatch.setattr(document_assessment.config, "WHOLE_DOCUMENT_FEEDBACK_ENABLED", False)
    monkeypatch.setattr(document_assessment, "api_post_json", fake_post)

    result, metadata = document_assessment.assess_documents(
        str(answer),
    )

    assert calls[0]["reasoning"]["effort"] == "low"
    assert metadata["compact_fast_path"] is True
    assert metadata["target_seconds"] == 120
    assert metadata["primary_timeout_seconds"] == 70
    assert metadata["reasoning_effort"] == "low"
    assert result["estimated_score"] == 2


def test_seven_page_estimate_uses_fast_nonblocking_path(tmp_path, monkeypatch):
    answer = tmp_path / "seven-page-answer.pdf"
    make_pdf(answer, "Q answer", pages=7)
    calls = []

    def fake_post(_url, payload, **kwargs):
        calls.append((payload, kwargs))
        body = valid_assessment("estimate")
        body["questions"][0]["evidence_pages"] = [1]
        return {
            "id": "seven-page-fast-response",
            "model": "gpt-5.5",
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
    monkeypatch.setattr(document_assessment.config, "WHOLE_DOCUMENT_CONTEXT_ENABLED", True)
    monkeypatch.setattr(document_assessment.config, "WHOLE_DOCUMENT_FEEDBACK_ENABLED", False)
    monkeypatch.setattr(document_assessment, "api_post_json", fake_post)

    result, metadata = document_assessment.assess_documents(
        str(answer),
    )

    assert len(calls) == 1
    assert calls[0][0]["reasoning"]["effort"] == "low"
    assert calls[0][0]["model"] == "gpt-5.4-mini"
    assert calls[0][1]["timeout"] == 70
    assert metadata["fast_estimate_path"] is True
    assert metadata["render_dpi"] == 110
    assert metadata["target_seconds"] == 120
    assert metadata["document_context"]["status"] == "skipped_fast_assessment"
    assert result["estimated_score"] == 2


def test_fifteen_page_estimate_uses_stable_ordered_image_fast_path(
    tmp_path, monkeypatch
):
    answer = tmp_path / "fifteen-page-answer.pdf"
    make_pdf(answer, "Q answer", pages=15)
    calls = []

    def fake_post(_url, payload, **kwargs):
        calls.append((payload, kwargs))
        body = valid_assessment("estimate")
        body["questions"][0]["evidence_pages"] = [1]
        return {
            "id": "full-paper-fast-response",
            "model": payload["model"],
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
    monkeypatch.setattr(document_assessment.config, "WHOLE_DOCUMENT_CONTEXT_ENABLED", False)
    monkeypatch.setattr(document_assessment.config, "WHOLE_DOCUMENT_FEEDBACK_ENABLED", False)
    monkeypatch.setattr(document_assessment, "api_post_json", fake_post)

    result, metadata = document_assessment.assess_documents(str(answer))

    content = calls[0][0]["input"][0]["content"]
    assert calls[0][0]["model"] == "gpt-5.4-mini"
    assert calls[0][1]["timeout"] in {104, 105}
    assert content[1]["type"] == "input_text"
    assert content[2]["type"] == "input_image"
    assert len(content) == 31
    assert "page 1 of 15" in content[1]["text"]
    assert "page 15 of 15" in content[-2]["text"]
    assert metadata["fast_estimate_path"] is True
    assert metadata["fast_image_transport"] is True
    assert metadata["render_dpi"] == 110
    assert metadata["target_seconds"] == 120
    assert result["estimated_score"] == 2


def test_small_gallery_images_are_sent_as_clear_bounded_page_images(tmp_path):
    answer = tmp_path / "completed-work-pages.pdf"
    original_jpeg = make_image_only_pdf(answer)

    parts = document_assessment._render_responses_document_image_parts(
        str(answer),
        label="Completed student work",
        dpi=110,
    )

    assert len(parts) == 4
    assert parts[0]["text"].endswith("page 1 of 2:")
    assert parts[2]["text"].endswith("page 2 of 2:")
    for image_part in (parts[1], parts[3]):
        assert image_part["type"] == "input_image"
        assert image_part["image_url"].startswith("data:image/jpeg;base64,")
        encoded = image_part["image_url"].split("base64,", 1)[1]
        prepared = base64.b64decode(encoded)
        assert prepared != original_jpeg
        assert len(prepared) < 300_000
        prepared_pixmap = fitz.Pixmap(prepared)
        assert prepared_pixmap.width >= 1400


def test_validator_removes_provider_warning_with_contradictory_estimate_total():
    body = valid_assessment("estimate")
    body["warnings"] = [
        "Estimated total awarded mark is 1 out of 3.",
        "One handwritten symbol is faint.",
    ]

    result = validate_assessment(
        body,
        mode="estimate",
        completed_work_pages=2,
    )

    assert result["estimated_score"] == 2
    assert "Estimated total awarded mark is 1 out of 3." not in result["warnings"]
    assert "One handwritten symbol is faint." in result["warnings"]


def test_unrelated_bad_request_does_not_retry_document_transport():
    error = urllib.error.HTTPError(
        "https://provider.invalid/v1/responses",
        400,
        "Bad Request",
        {},
        io.BytesIO(b'{"error":{"message":"Invalid JSON schema"}}'),
    )

    assert document_assessment._retryable_provider_error(error) is False


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
