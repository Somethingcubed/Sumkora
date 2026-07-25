import base64
import hashlib
import json
import os
import urllib.error
import urllib.request
from datetime import datetime
from typing import Optional, Tuple

import fitz

import config
from db import execute, query_all, query_one


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
    pix = page.get_pixmap(dpi=getattr(config, "OCR_RENDER_DPI", 200))
    data = base64.b64encode(pix.tobytes("png")).decode("ascii")
    doc.close()
    return data


def api_post_json(url: str, payload: dict, headers: Optional[dict] = None) -> dict:
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json", **(headers or {})},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.loads(response.read().decode("utf-8"))


def cxsee_chat_completion(model: str, content: list, temperature: float = 0.0) -> dict:
    key = getattr(config, "CXSEE_API_KEY", "")
    if not key:
        raise RuntimeError("CXSee API key is not configured.")
    base_url = getattr(config, "CXSEE_BASE_URL", "https://api.cxsee.com/v1").rstrip("/")
    return api_post_json(
        f"{base_url}/chat/completions",
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
    model = getattr(config, "CXSEE_OCR_MODEL", "qwen3-vl-plus")
    result = cxsee_chat_completion(
        model,
        [
            {
                "type": "text",
                "text": (
                    "OCR this IGCSE mathematics student work image. "
                    "Return only the visible student writing/text. Preserve question labels, "
                    "line breaks, equations, and units. Do not solve or mark anything."
                ),
            },
            {
                "type": "image_url",
                "image_url": {"url": f"data:image/png;base64,{image_b64}"},
            },
        ],
    )
    return cxsee_response_text(result), None


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
                error = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                current_hash,
                text,
                confidence,
                status,
                error,
                now,
                existing["id"],
            ),
        )
    else:
        execute(
            """
            INSERT INTO ocr_pages
            (submission_id, page_number, provider, file_hash, text, confidence,
             status, error, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
            ),
        )


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
        try:
            image_b64 = render_page_base64(pdf_path, page_number)
            if not image_b64:
                raise RuntimeError("Could not render PDF page for OCR.")
            text, confidence = run_page_ocr(provider, image_b64)
            upsert_ocr_page(
                submission_id,
                page_number,
                provider,
                current_hash,
                text,
                confidence,
                "done",
                "",
            )
        except (RuntimeError, urllib.error.URLError, urllib.error.HTTPError) as exc:
            upsert_ocr_page(
                submission_id,
                page_number,
                provider,
                current_hash,
                "",
                None,
                "failed",
                str(exc),
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
