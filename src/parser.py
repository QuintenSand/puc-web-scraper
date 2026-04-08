# src/parser.py
# Text extraction and RAG-oriented chunking.
#
# Why chunk?
# ----------
# Embedding models (e.g. text-embedding-3-small) have a fixed token limit
# (~8 k tokens). More importantly, *retrieval quality* degrades sharply when
# chunks are too large: the embedding of a 10-page document becomes a blurry
# average that matches nothing well. Chunks of ~400-800 characters (roughly
# 100-200 tokens) give a much tighter semantic signal.
#
# The splitter below is sentence-aware: it never cuts mid-sentence, and it
# adds an overlap window so that sentences near a boundary appear in both
# adjacent chunks (preventing missed context at retrieval time).

import re
import logging
import os
import time

import fitz          # PyMuPDF
import html2text

from .config import (
    CHUNK_SIZE,
    CHUNK_OVERLAP,
    DOWNLOAD_DIR,
    PDF_DOWNLOAD_TIMEOUT,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# HTML → Markdown
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

def pdf_to_text(pdf_path: str) -> str:
    """
    Extract text from a PDF using PyMuPDF.

    Uses page.get_text("text") which is faster and produces cleaner output
    than the block-based approach for most PUC documents.  Falls back to the
    block approach if the simple extraction returns an empty string (scanned
    PDF guard).
    """
    try:
        doc = fitz.open(pdf_path)
        pages: list[str] = []
        for page in doc:
            text = page.get_text("text").strip()
            if not text:
                # Fallback: reconstruct from text blocks
                blocks = page.get_text("blocks")
                text = "\n".join(b[4] for b in blocks if b[4].strip())
            pages.append(text)
        return "\n\n".join(pages)
    except Exception:
        logger.exception("PyMuPDF failed on %s", pdf_path)
        return ""


# ---------------------------------------------------------------------------
# Sentence-aware text chunker
# ---------------------------------------------------------------------------

# Matches sentence-ending punctuation followed by whitespace or end-of-string.
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")


def _split_sentences(text: str) -> list[str]:
    """Split text into sentences on '.', '!', '?' boundaries."""
    parts = _SENTENCE_END.split(text.strip())
    return [p.strip() for p in parts if p.strip()]


def chunk_text(text: str, chunk_size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
    """
    Split *text* into overlapping chunks of at most *chunk_size* characters.

    Algorithm
    ---------
    1. Split the text into sentences.
    2. Greedily accumulate sentences until the chunk would exceed *chunk_size*.
    3. When a chunk is full, emit it and roll back *overlap* characters worth
       of sentences to form the start of the next chunk.

    Returns an empty list for blank input.
    """
    text = text.strip()
    if not text:
        return []

    sentences = _split_sentences(text)
    if not sentences:
        return [text[:chunk_size]] if text else []

    chunks: list[str] = []
    current: list[str] = []
    current_len = 0

    for sentence in sentences:
        sentence_len = len(sentence)

        # A single sentence longer than chunk_size: split it hard.
        if sentence_len > chunk_size:
            # Flush whatever we have first
            if current:
                chunks.append(" ".join(current))
                current, current_len = [], 0
            # Hard-split the long sentence
            for start in range(0, sentence_len, chunk_size - overlap):
                chunks.append(sentence[start : start + chunk_size])
            continue

        # Would adding this sentence overflow the chunk?
        if current_len + sentence_len + 1 > chunk_size and current:
            chunks.append(" ".join(current))

            # Roll back: keep sentences that fit within the overlap window
            overlap_sentences: list[str] = []
            overlap_len = 0
            for s in reversed(current):
                if overlap_len + len(s) + 1 <= overlap:
                    overlap_sentences.insert(0, s)
                    overlap_len += len(s) + 1
                else:
                    break
            current = overlap_sentences
            current_len = overlap_len

        current.append(sentence)
        current_len += sentence_len + 1  # +1 for the space separator

    if current:
        chunks.append(" ".join(current))

    return chunks


# ---------------------------------------------------------------------------
# PDF download helper
# ---------------------------------------------------------------------------

def wait_for_new_pdf(before: set[str], timeout: int = PDF_DOWNLOAD_TIMEOUT) -> str | None:
    """
    Wait until a *new* completed PDF appears in DOWNLOAD_DIR.

    Pass the set of PDF filenames that existed *before* the download was
    triggered so we can identify the newly arrived file.  This avoids the
    bug in the original code where `files[0]` might return a pre-existing PDF.
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
