# src/parser.py
# Text extraction from HTML and PDF sources.

import logging
import os
import time

import fitz          # PyMuPDF
import html2text

from .config import DOWNLOAD_DIR, PDF_DOWNLOAD_TIMEOUT

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# HTML → plain text / Markdown
# ---------------------------------------------------------------------------

_h2t = html2text.HTML2Text()
_h2t.ignore_links = False
_h2t.ignore_images = True
_h2t.body_width = 0   # no line-wrapping — keeps paragraphs intact


def html_to_text(html: str) -> str:
    """Convert an HTML string to clean Markdown/plain text."""
    return _h2t.handle(html)


# ---------------------------------------------------------------------------
# PDF → plain text
# ---------------------------------------------------------------------------

def pdf_bytes_to_text(data: bytes) -> str:
    """Extract text from raw PDF bytes (e.g. from an httpx download)."""
    try:
        doc = fitz.open(stream=data, filetype="pdf")
        pages: list[str] = []
        for page in doc:
            text = page.get_text("text").strip()
            if not text:
                blocks = page.get_text("blocks")
                text = "\n".join(b[4] for b in blocks if b[4].strip())
            pages.append(text)
        return "\n\n".join(pages)
    except Exception:
        logger.exception("PyMuPDF failed on PDF bytes")
        return ""


def pdf_to_text(pdf_path: str) -> str:
    """
    Extract text from a PDF using PyMuPDF.

    Uses page.get_text("text") for clean output. Falls back to the block-based
    approach if simple extraction returns an empty string (scanned PDF guard).
    """
    try:
        doc = fitz.open(pdf_path)
        pages: list[str] = []
        for page in doc:
            text = page.get_text("text").strip()
            if not text:
                blocks = page.get_text("blocks")
                text = "\n".join(b[4] for b in blocks if b[4].strip())
            pages.append(text)
        return "\n\n".join(pages)
    except Exception:
        logger.exception("PyMuPDF failed on %s", pdf_path)
        return ""


# ---------------------------------------------------------------------------
# PDF download helper
# ---------------------------------------------------------------------------

def wait_for_new_pdf(before: set[str], timeout: int = PDF_DOWNLOAD_TIMEOUT) -> str | None:
    """
    Wait until a *new* completed PDF appears in DOWNLOAD_DIR.

    Pass the set of PDF filenames that existed *before* the download was
    triggered so we can identify the newly arrived file.
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        current = {
            f for f in os.listdir(DOWNLOAD_DIR)
            if f.endswith(".pdf") and not f.endswith(".crdownload")
        }
        new_files = current - before
        if new_files:
            return os.path.join(DOWNLOAD_DIR, new_files.pop())
        time.sleep(1)
    return None


def existing_pdfs() -> set[str]:
    """Return the set of PDF filenames currently in DOWNLOAD_DIR."""
    if not os.path.exists(DOWNLOAD_DIR):
        return set()
    return {f for f in os.listdir(DOWNLOAD_DIR) if f.endswith(".pdf")}
