# src/browser.py
# Playwright browser — only used for pages that require a JS-driven PDF download.
# For HTML document pages and URL collection, see src/fetcher.py.
#
# Playwright bundles its own Chromium, so no Chrome installation is required.
# After installing dependencies, run once:
#
#   uv run playwright install chromium
#
# Use LazyBrowser so Chromium is only started if the current run actually
# encounters a document that needs a browser:
#
#   browser = LazyBrowser()
#   try:
#       pdf_path = browser.download_pdf("https://...")
#       if pdf_path:
#           text = pdf_to_text(pdf_path)
#           os.remove(pdf_path)
#   finally:
#       browser.close()

import logging
import os
from pathlib import Path

from playwright.sync_api import Browser, Playwright, sync_playwright

from .config import DOWNLOAD_DIR, PAGE_LOAD_TIMEOUT

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# LazyBrowser — starts Chromium only when first needed
# ---------------------------------------------------------------------------

class LazyBrowser:
    """
    Wraps a Playwright Chromium browser that is only started on the first call
    to download_pdf().  Runs that require only HTML pages never open a browser.

    Playwright ships with bundled browser binaries — no system Chrome needed.
    Remember to run `uv run playwright install chromium` after first install.
    """

    def __init__(self) -> None:
        self._pw: Playwright | None = None
        self._browser: Browser | None = None

    @property
    def started(self) -> bool:
        return self._browser is not None

    def _ensure_started(self) -> None:
        if self._browser is None:
            logger.info("Starting Chromium for PDF downloads…")
            os.makedirs(DOWNLOAD_DIR, exist_ok=True)
            self._pw = sync_playwright().start()
            self._browser = self._pw.chromium.launch(headless=True)

    def download_pdf(self, url: str) -> str | None:
        """
        Navigate to *url* and capture a PDF download triggered by a button.

        Handles two button patterns found on the PUC portal:
          • 'Maak een PDF' — generates a PDF from the page; a 'Klaar!' button
            appears afterwards to trigger the actual download.
          • 'PDF Openen'   — downloads a pre-existing PDF directly.

        Returns the local path of the downloaded PDF on success (caller is
        responsible for deleting it), or None on failure.
        """
        self._ensure_started()

        context = self._browser.new_context(accept_downloads=True)
        page = context.new_page()

        try:
            timeout_ms = PAGE_LOAD_TIMEOUT * 1000
            page.goto(url, timeout=timeout_ms, wait_until="domcontentloaded")

            # Pattern A: generated PDF ("Maak een PDF" → wait → "Klaar!")
            if page.locator("text=Maak een PDF").count():
                page.click("text=Maak een PDF")
                try:
                    page.wait_for_selector("text=Klaar!", timeout=15_000)
                    with page.expect_download(timeout=30_000) as dl:
                        page.click("text=Klaar!")
                    return _save_download(dl.value)
                except Exception:
                    logger.debug("'Klaar!' button not found after 'Maak een PDF'")

            # Pattern B: direct download ("PDF Openen" or similar)
            for label in ("PDF Openen", "Download PDF", "Open PDF"):
                if page.locator(f"text={label}").count():
                    with page.expect_download(timeout=30_000) as dl:
                        page.click(f"text={label}")
                    return _save_download(dl.value)

            logger.warning("No recognised PDF button found at %s", url)
            return None

        except Exception:
            logger.exception("Playwright PDF download failed for %s", url)
            return None

        finally:
            page.close()
            context.close()

    def close(self) -> None:
        """Quit the browser if it was started."""
        if self._browser is not None:
            self._browser.close()
            self._browser = None
        if self._pw is not None:
            self._pw.stop()
            self._pw = None


def _save_download(download) -> str:
    """Persist a Playwright Download object to DOWNLOAD_DIR and return its path."""
    dest = Path(DOWNLOAD_DIR) / download.suggested_filename
    download.save_as(dest)
    return str(dest)
