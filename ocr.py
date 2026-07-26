import base64
import hashlib
import json
import os
import ssl
import time
import urllib.error
import urllib.request
from datetime import datetime
from typing import Optional, Protocol, Tuple

import fitz

import config
from db import execute, query_all, query_one
from pdf_utils import page_render_matrix

OCR_PROMPT = (
    "Transcribe this IGCSE mathematics student-work page. Preserve visible "
    "question labels, line breaks, equations, fractions, superscripts, units, "
    "crossed-out work, and uncertain symbols. Distinguish printed question text, "
    "student handwriting, and teacher annotations when possible. Do not solve, "
    "correct, or award marks. Return transcription only."
)


class OCRProvider(Protocol):
    def transcribe(self, image_b64: str) -> Tuple[str, Optional[float]]:
        ...


def active_provider() -> str:
    return getattr(config, "OCR_PROVIDER", "cxsee_vl") or "cxsee_vl"


def file_hash(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def pdf_page_count(path: str) -> int:
    try:
        doc = fitz.open(path)
        count = len(doc)
        doc.close()
        return count
    except Exception:
        return 0


def render_page_base64(path: str, page_number: int) -> str:
    try:
        doc = fitz.open(path)
    except Exception:
        return ""
    if len(doc) == 0:
        doc.close()
        return ""
    index = max(0, min(page_number - 1, len(doc) - 1))
    page = doc.load_page(index)
    dpi = getattr(config, "OCR_RENDER_DPI", 200)
    pix = page.get_pixmap(matrix=page_render_matrix(page, dpi))
    data = base64.b64encode(pix.tobytes("png")).decode("ascii")
    doc.close()
    return data


def api_post_json(
    url: str,
    payload: dict,
    headers: Optional[dict] = None,
    timeout: Optional[int] = None,
    retries: Optional[int] = None,
) -> dict:
    data = json.dumps(payload).encode("utf-8")
    attempts = (config.CXSEE_MAX_RETRIES if retries is None else retries) + 1
    timeout = timeout or config.CXSEE_TIMEOUT_SECONDS
    last_error = None
    ssl_context = ssl.create_default_context()
    try:
        import certifi

        ssl_context = ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        pass
    for attempt in range(attempts):
        request = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json", **(headers or {})},
            method="POST",
        )
        try:
            with urllib.request.urlopen(
                request,
                timeout=timeout,
                context=ssl_context,
            ) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            last_error = exc
            if exc.code not in {408, 429, 500, 502, 503, 504} or attempt + 1 >= attempts:
                raise
        except (urllib.error.URLError, TimeoutError) as exc:
            last_error = exc
            if attempt + 1 >= attempts:
                raise
        time.sleep(min(0.5 * (2**attempt), 2.0))
    raise RuntimeError(f"Provider request failed: {type(last_error).__name__}")


def cxsee_api_base() -> str:
    base_url = getattr(config, "CXSEE_BASE_URL", "https://api.cxsee.com").rstrip("/")
    return base_url if base_url.endswith("/v1") else f"{base_url}/v1"


def cxsee_chat_completion(model: str, content: list, temperature: float = 0.0) -> dict:
    key = getattr(config, "CXSEE_API_KEY", "")
    if not key:
        raise RuntimeError("CXSee API key is not configured.")
    return api_post_json(
        f"{cxsee_api_base()}/chat/completions",
        {
            "model": model,
            "messages": [{"role": "user", "content": content}],
            "temperature": temperature,
        },
        headers={"Authorization": f"Bearer {key}"},
    )


def cxsee_response_text(result: dict) -> str:
    choices = result.get("choices") or []
    if not choices:
        raise RuntimeError("CXSee returned no choices.")
    message = choices[0].get("message") or {}
    content = message.get("content", "")
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict):
                parts.append(str(item.get("text", "")))
            else:
                parts.append(str(item))
        content = "\n".join(part for part in parts if part)
    return str(content).strip()


def average_google_confidence(full_text_annotation: dict) -> Optional[float]:
    values = []
    for page in full_text_annotation.get("pages", []):
        for block in page.get("blocks", []):
            if "confidence" in block:
                values.append(float(block["confidence"]))
            for paragraph in block.get("paragraphs", []):
                if "confidence" in paragraph:
                    values.append(float(paragraph["confidence"]))
                for word in paragraph.get("words", []):
                    if "confidence" in word:
                        values.append(float(word["confidence"]))
    if not values:
        return None
    return round(sum(values) / len(values), 3)


def google_vision_ocr(image_b64: str) -> Tuple[str, Optional[float]]:
    key = getattr(config, "GOOGLE_VISION_API_KEY", "")
    if not key:
        raise RuntimeError("Google Vision API key is not configured.")

    payload = {
        "requests": [
            {
                "image": {"content": image_b64},
                "features": [{"type": "DOCUMENT_TEXT_DETECTION"}],
                "imageContext": {"languageHints": ["en"]},
            }
        ]
    }
    result = api_post_json(
        f"https://vision.googleapis.com/v1/images:annotate?key={key}",
        payload,
    )
    response = (result.get("responses") or [{}])[0]
    if response.get("error"):
        raise RuntimeError(response["error"].get("message", "Google Vision OCR failed."))
    full = response.get("fullTextAnnotation") or {}
    text = full.get("text", "")
    return text, average_google_confidence(full)


def mathpix_ocr(image_b64: str) -> Tuple[str, Optional[float]]:
    app_id = getattr(config, "MATHPIX_APP_ID", "")
    app_key = getattr(config, "MATHPIX_APP_KEY", "")
    if not app_id or not app_key:
        raise RuntimeError("Mathpix app_id/app_key are not configured.")

    payload = {
        "src": f"data:image/png;base64,{image_b64}",
        "formats": ["text"],
        "data_options": {
            "include_asciimath": True,
            "include_latex": True,
        },
    }
    result = api_post_json(
        "https://api.mathpix.com/v3/text",
        payload,
        headers={
            "app_id": app_id,
            "app_key": app_key,
        },
    )
    if result.get("error"):
        raise RuntimeError(str(result["error"]))
    confidence = result.get("confidence_rate", result.get("confidence"))
    return result.get("text", ""), float(confidence) if confidence is not None else None


def cxsee_vl_ocr(image_b64: str) -> Tuple[str, Optional[float]]:
    text, confidence, _ = cxsee_vl_ocr_detailed(image_b64)
    return text, confidence


def cxsee_vl_ocr_detailed(image_b64: str) -> tuple[str, Optional[float], dict]:
    model = getattr(config, "CXSEE_OCR_MODEL", "qwen-vl-ocr-latest")
    content = [
        {"type": "text", "text": OCR_PROMPT},
        {
            "type": "image_url",
            "image_url": {"url": f"data:image/png;base64,{image_b64}"},
        },
    ]
    candidates = [model] + [
        candidate
        for candidate in getattr(config, "CXSEE_OCR_FALLBACK_MODELS", [])
        if candidate != model
    ]
    last_error = None
    result = None
    for candidate in candidates:
        try:
            result = cxsee_chat_completion(candidate, content)
            result["_sumkora"] = {
                "requested_model": model,
                "used_model": candidate,
                **(
                    {"warning": "configured_model_unavailable_fallback_used"}
                    if candidate != model
                    else {}
                ),
            }
            break
        except urllib.error.HTTPError as exc:
            last_error = exc
            if exc.code not in {400, 404, 503}:
                raise
    if result is None:
        raise last_error or RuntimeError("No CXSee OCR model completed the request.")
    return cxsee_response_text(result), None, result


def run_page_ocr(provider: str, image_b64: str) -> Tuple[str, Optional[float]]:
    if provider == "cxsee_vl":
        return cxsee_vl_ocr(image_b64)
    if provider == "mathpix":
        return mathpix_ocr(image_b64)
    if provider == "google_vision":
        return google_vision_ocr(image_b64)
    raise RuntimeError(f"Unknown OCR provider: {provider}")


def upsert_ocr_page(
    submission_id: int,
    page_number: int,
    provider: str,
    current_hash: str,
    text: str,
    confidence: Optional[float],
    status: str,
    error: str = "",
    model: str = "",
    prompt_version: str = "",
    raw_response: Optional[str] = None,
    normalized_latex: str = "",
    warnings: str = "[]",
    timing_ms: Optional[int] = None,
    model_run_id: Optional[int] = None,
):
    now = datetime.now().isoformat()
    existing = query_one(
        """
        SELECT id FROM ocr_pages
        WHERE submission_id = ? AND page_number = ? AND provider = ?
        """,
        (submission_id, page_number, provider),
    )
    if existing:
        execute(
            """
            UPDATE ocr_pages
            SET file_hash = ?, text = ?, confidence = ?, status = ?,
                error = ?, updated_at = ?, model = ?, prompt_version = ?,
                raw_response = ?, normalized_latex = ?, warnings = ?,
                timing_ms = ?, model_run_id = ?
            WHERE id = ?
            """,
            (
                current_hash,
                text,
                confidence,
                status,
                error,
                now,
                model,
                prompt_version,
                raw_response,
                normalized_latex,
                warnings,
                timing_ms,
                model_run_id,
                existing["id"],
            ),
        )
    else:
        execute(
            """
            INSERT INTO ocr_pages
            (submission_id, page_number, provider, file_hash, text, confidence,
             status, error, created_at, updated_at, model, prompt_version,
             raw_response, normalized_latex, warnings, timing_ms, model_run_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                submission_id,
                page_number,
                provider,
                current_hash,
                text,
                confidence,
                status,
                error,
                now,
                now,
                model,
                prompt_version,
                raw_response,
                normalized_latex,
                warnings,
                timing_ms,
                model_run_id,
            ),
        )


def start_model_run(submission_id: int, run_type: str, model: str) -> int:
    return execute(
        """
        INSERT INTO model_runs
        (submission_id, run_type, provider, model, prompt_version, status, started_at)
        VALUES (?, ?, 'cxsee', ?, ?, 'processing', ?)
        """,
        (
            submission_id,
            run_type,
            model,
            getattr(config, "OCR_PROMPT_VERSION", "ocr-math-v2"),
            datetime.now().isoformat(),
        ),
    )


def finish_model_run(
    run_id: int,
    status: str,
    started: float,
    raw_response: Optional[dict] = None,
    error: Optional[str] = None,
    used_model: Optional[str] = None,
    warnings: Optional[list[str]] = None,
):
    duration_ms = int((time.monotonic() - started) * 1000)
    execute(
        """
        UPDATE model_runs
        SET status = ?, raw_response = ?, error = ?, duration_ms = ?,
            model = COALESCE(?, model), warning_flags = ?, finished_at = ?
        WHERE id = ?
        """,
        (
            status,
            json.dumps(raw_response, ensure_ascii=False) if raw_response is not None else None,
            error,
            duration_ms,
            used_model,
            json.dumps(warnings or [], ensure_ascii=False),
            datetime.now().isoformat(),
            run_id,
        ),
    )
    return duration_ms


def cached_pages(submission_id: int, provider: str, current_hash: str):
    return query_all(
        """
        SELECT * FROM ocr_pages
        WHERE submission_id = ? AND provider = ? AND file_hash = ?
        ORDER BY page_number
        """,
        (submission_id, provider, current_hash),
    )


def run_submission_ocr(submission_id: int, pdf_path: str, force: bool = False):
    provider = active_provider()
    if not os.path.exists(pdf_path):
        return []

    count = pdf_page_count(pdf_path)
    if count == 0:
        return []

    current_hash = file_hash(pdf_path)
    pages = cached_pages(submission_id, provider, current_hash)
    if (
        not force
        and len(pages) == count
        and all(page["status"] == "done" for page in pages)
    ):
        return pages

    if not getattr(config, "OCR_ENABLED", False):
        for page_number in range(1, count + 1):
            upsert_ocr_page(
                submission_id,
                page_number,
                provider,
                current_hash,
                "",
                None,
                "skipped",
                "OCR is disabled in config.py.",
            )
        return cached_pages(submission_id, provider, current_hash)

    for page_number in range(1, count + 1):
        started = time.monotonic()
        run_id = None
        model = (
            getattr(config, "CXSEE_OCR_MODEL", "qwen-vl-ocr-latest")
            if provider == "cxsee_vl"
            else provider
        )
        try:
            image_b64 = render_page_base64(pdf_path, page_number)
            if not image_b64:
                raise RuntimeError("Could not render PDF page for OCR.")
            raw_result = None
            if provider == "cxsee_vl":
                run_id = start_model_run(submission_id, "ocr", model)
                text, confidence, raw_result = cxsee_vl_ocr_detailed(image_b64)
                provider_meta = raw_result.get(
                    "_sumkora",
                    raw_result.get("_numera", {}),
                )
                model = provider_meta.get("used_model", model)
            else:
                text, confidence = run_page_ocr(provider, image_b64)
            duration_ms = (
                finish_model_run(
                    run_id,
                    "completed",
                    started,
                    raw_result,
                    used_model=model,
                    warnings=[provider_meta["warning"]]
                    if provider_meta.get("warning")
                    else [],
                )
                if run_id
                else int((time.monotonic() - started) * 1000)
            )
            upsert_ocr_page(
                submission_id,
                page_number,
                provider,
                current_hash,
                text,
                confidence,
                "done",
                "",
                model=model,
                prompt_version=getattr(config, "OCR_PROMPT_VERSION", "ocr-math-v2"),
                raw_response=json.dumps(raw_result, ensure_ascii=False) if raw_result else None,
                warnings=json.dumps(
                    [provider_meta["warning"]]
                    if provider == "cxsee_vl" and provider_meta.get("warning")
                    else [],
                    ensure_ascii=False,
                ),
                timing_ms=duration_ms,
                model_run_id=run_id,
            )
        except (RuntimeError, urllib.error.URLError, urllib.error.HTTPError) as exc:
            duration_ms = (
                finish_model_run(run_id, "failed", started, error=str(exc))
                if run_id
                else int((time.monotonic() - started) * 1000)
            )
            upsert_ocr_page(
                submission_id,
                page_number,
                provider,
                current_hash,
                "",
                None,
                "failed",
                str(exc),
                model=model,
                prompt_version=getattr(config, "OCR_PROMPT_VERSION", "ocr-math-v2"),
                warnings=json.dumps(["provider_error"], ensure_ascii=False),
                timing_ms=duration_ms,
                model_run_id=run_id,
            )

    return cached_pages(submission_id, provider, current_hash)


def ocr_pages_for_submission(submission_id: int, pdf_path: Optional[str] = None):
    provider = active_provider()
    if pdf_path and os.path.exists(pdf_path):
        current_hash = file_hash(pdf_path)
        return cached_pages(submission_id, provider, current_hash)
    return query_all(
        """
        SELECT * FROM ocr_pages
        WHERE submission_id = ? AND provider = ?
        ORDER BY page_number
        """,
        (submission_id, provider),
    )


def ocr_text_for_page(submission_id: int, pdf_path: str, page_number: int) -> str:
    pages = ocr_pages_for_submission(submission_id, pdf_path)
    for page in pages:
        if page["page_number"] == page_number and page["status"] == "done":
            return page["text"] or ""
    return ""


def reset_ocr_cache(submission_id: int):
    execute("DELETE FROM ocr_pages WHERE submission_id = ?", (submission_id,))


def cxsee_health_check() -> dict:
    if not getattr(config, "CXSEE_API_KEY", ""):
        return {"ok": False, "error": "missing_key", "configured_model_available": False}
    request = urllib.request.Request(
        f"{cxsee_api_base()}/models",
        headers={
            "Authorization": f"Bearer {config.CXSEE_API_KEY}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(
            request, timeout=min(config.CXSEE_TIMEOUT_SECONDS, 20)
        ) as response:
            payload = json.loads(response.read().decode("utf-8"))
        models = [
            item.get("id", "")
            for item in payload.get("data", [])
            if isinstance(item, dict)
        ]
        return {
            "ok": True,
            "model_count": len(models),
            "configured_model": config.CXSEE_OCR_MODEL,
            "configured_model_available": config.CXSEE_OCR_MODEL in models,
            "ocr_models": [model for model in models if "ocr" in model.lower()],
        }
    except Exception as exc:
        return {
            "ok": False,
            "error": type(exc).__name__,
            "configured_model_available": False,
        }
