import base64
import os

import fitz

import config
from storage import private_storage


def is_valid_pdf(content: bytes) -> bool:
    if not content.startswith(b"%PDF"):
        return False
    try:
        doc = fitz.open(stream=content, filetype="pdf")
        ok = len(doc) > 0
        doc.close()
        return ok
    except Exception:
        return False


def save_upload(filename: str, content: bytes) -> str:
    return private_storage.save(filename, content)


def pdf_to_page_images(pdf_path: str, dpi: int = 150) -> list[str]:
    try:
        doc = fitz.open(pdf_path)
    except Exception:
        return []
    images = []
    for page_index in range(len(doc)):
        page = doc.load_page(page_index)
        pix = page.get_pixmap(dpi=dpi)
        b64 = base64.b64encode(pix.tobytes("png")).decode("ascii")
        images.append(b64)
    doc.close()
    return images


def get_page_image_base64(pdf_path: str, page_number: int, dpi: int = 150) -> str:
    try:
        doc = fitz.open(pdf_path)
    except Exception:
        return ""
    if len(doc) == 0:
        doc.close()
        return ""
    index = max(0, min(page_number - 1, len(doc) - 1))
    page = doc.load_page(index)
    pix = page.get_pixmap(dpi=dpi)
    b64 = base64.b64encode(pix.tobytes("png")).decode("ascii")
    doc.close()
    return b64


def get_page_text(pdf_path: str, page_number: int) -> str:
    try:
        doc = fitz.open(pdf_path)
    except Exception:
        return ""
    if len(doc) == 0:
        doc.close()
        return ""
    index = max(0, min(page_number - 1, len(doc) - 1))
    text = doc.load_page(index).get_text()
    doc.close()
    return text
