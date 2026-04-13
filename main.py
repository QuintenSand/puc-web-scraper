# main.py
# PUC web scraper — httpx edition.
# https://puc.overheid.nl/nza/
#
# Run with:
#   uv run python main.py
#
# Two-phase approach
# ------------------
# Phase 1 — URL collection:  construct paginated list URLs directly from the
#            known path structure and collect document links with httpx + BS4.
#            No browser needed.
#
# Phase 2 — Document processing:  fetch each document page with httpx,
#            extract the article text with BeautifulSoup. Only start Chrome
#            if a page has no article body and needs a PDF download instead.

import logging
import os
import time
from datetime import date

from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from src.browser import LazyBrowser
from src.config import (
    INTER_PAGE_DELAY,
    LOG_FILE,
    MAX_RETRIES,
    MIN_ARTICLE_LENGTH,
    RETRY_BACKOFF,
)
from src.fetcher import (
    build_list_url,
    extract_article_text,
    extract_doc_links,
    extract_metadata,
    fetch_category_options,
    fetch_soup,
    get_client,
)
from src.parser import (
    existing_pdfs,
    pdf_to_text,
    wait_for_new_pdf,
)
from src.prompt import ScraperFilters, ask_filters
from src.storage import (
    count_documents,
    document_exists,
    get_connection,
    save_document,
)

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Retry helper
# ---------------------------------------------------------------------------

def with_retry(fn, *args, retries: int = MAX_RETRIES, backoff: float = RETRY_BACKOFF, **kwargs):
    for attempt in range(1, retries + 1):
        try:
            return fn(*args, **kwargs)
        except Exception as exc:
            if attempt == retries:
                logger.error("All %d attempts failed for %s: %s", retries, fn.__name__, exc)
                return None
            wait = backoff * (2 ** (attempt - 1))
            logger.warning("Attempt %d/%d failed (%s). Retrying in %.1fs…", attempt, retries, exc, wait)
            time.sleep(wait)


# ---------------------------------------------------------------------------
# Phase 1 — URL collection  (httpx, no browser)
# ---------------------------------------------------------------------------

def collect_urls(client, filters: ScraperFilters) -> list[str]:
    """
    Construct paginated list URLs from the known path structure and collect
    all matching document links using plain HTTP requests.
    """
    logger.info("Phase 1: collecting document URLs")

    # Determine categories to scrape
    categories = filters.category_codes if filters.category_codes else ["NZA000"]

    # Determine the date segment for the URL
    valid_date: str | None = None
    if filters.valid_only:
        valid_date = date.today().strftime("%d-%m-%Y")

    all_urls: list[str] = []

    for category in categories:
        logger.info("Collecting URLs for category: %s", category)
        page = 1
        while True:
            url = build_list_url(page, category, valid_date)
            soup = fetch_soup(client, url)
            if not soup:
                break

            links = extract_doc_links(soup)
            if not links:
                logger.info("  No links on page %d — reached end of results.", page)
                break

            all_urls.extend(links)
            logger.info("  Page %d: %d links (total so far: %d)", page, len(links), len(all_urls))
            page += 1
            time.sleep(INTER_PAGE_DELAY)

    unique = list(dict.fromkeys(all_urls))
    logger.info("Phase 1 complete. Collected %d unique URLs.", len(unique))
    return unique


# ---------------------------------------------------------------------------
# Phase 2 — Document processing  (httpx for HTML, browser only for PDF)
# ---------------------------------------------------------------------------

def _puc_id_from_url(url: str) -> str:
    parts = url.rstrip("/").split("/")
    for part in reversed(parts):
        if part.startswith("PUC_"):
            return part
    return parts[-1] or parts[-2]


def _passes_filters(meta: dict, filters: ScraperFilters, puc_id: str) -> bool:
    """Return False (and log a reason) if the document should be skipped."""

    # Keyword filter
    if filters.keyword:
        kw = filters.keyword.lower()
        if kw not in (meta["title"] or "").lower() and kw not in (meta["doc_type"] or "").lower():
            logger.info("Skipping %s — keyword '%s' not in title/type", puc_id, filters.keyword)
            return False

    # Date-range filter
    if meta["doc_date"] and (filters.date_from or filters.date_to):
        try:
            from datetime import datetime as _dt
            doc_date = _dt.fromisoformat(str(meta["doc_date"])).date()
            if filters.date_from and doc_date < filters.date_from:
                logger.info("Skipping %s — date %s before %s", puc_id, doc_date, filters.date_from)
                return False
            if filters.date_to and doc_date > filters.date_to:
                logger.info("Skipping %s — date %s after %s", puc_id, doc_date, filters.date_to)
                return False
        except (ValueError, TypeError):
            pass

    return True


def process_document(client, browser: LazyBrowser, con, url: str, filters: ScraperFilters) -> bool:
    """
    Fetch *url*, extract text (HTML or PDF), apply filters, and save to DuckDB.
    Returns True on success or skip, False on unrecoverable failure.
    """
    puc_id = _puc_id_from_url(url)

    if document_exists(con, puc_id):
        logger.debug("Already in DB, skipping: %s", puc_id)
        return True

    # Fetch with httpx
    soup = fetch_soup(client, url)
    if not soup:
        return False

    meta = extract_metadata(soup)

    if not _passes_filters(meta, filters, puc_id):
        return True   # skipped, not a failure

    # --- Option A: HTML article (no browser needed) ---
    text = extract_article_text(soup)
    source_format = "HTML"

    # --- Option B: PDF download (browser started lazily) ---
    if not text:
        driver, wait = browser.get()
        driver.get(url)
        time.sleep(2)

        try:
            pdf_btn_xpath = (
                "//a[contains(., 'Maak een PDF')]"
                " | //a[contains(., 'PDF Openen')]"
            )
            pdf_btn = wait.until(EC.element_to_be_clickable((By.XPATH, pdf_btn_xpath)))
            before = existing_pdfs()
            pdf_btn.click()

            try:
                finish_btn = WebDriverWait(driver, 5).until(
                    EC.element_to_be_clickable((By.XPATH, "//a[contains(., 'Klaar!')]"))
                )
                finish_btn.click()
            except Exception:
                pass

            pdf_path = wait_for_new_pdf(before)
            if pdf_path:
                text = pdf_to_text(pdf_path)
                source_format = "PDF"
                os.remove(pdf_path)
            else:
                logger.warning("PDF download timed out for %s", puc_id)
                return False

        except Exception:
            logger.exception("Error during PDF extraction for %s", url)
            return False

    if not text or not text.strip():
        logger.warning("No text extracted from %s", puc_id)
        return False

    save_document(
        con, puc_id, url, text,
        title=meta["title"],
        doc_date=meta["doc_date"],
        doc_type=meta["doc_type"],
        source_format=source_format,
    )
    logger.info("Saved %s | format=%s | chars=%d | title=%s",
                puc_id, source_format, len(text), meta["title"])
    return True


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    con = get_connection()
    browser = LazyBrowser()

    with get_client() as client:
        # Pre-flight — fetch filter options and ask the user
        category_options = fetch_category_options(client)
        filters = ask_filters(category_options)

        # Phase 1 — collect URLs (httpx only, no browser)
        urls = collect_urls(client, filters)

        # Phase 2 — process documents
        logger.info("Phase 2: processing %d documents", len(urls))
        success, skipped, failed = 0, 0, 0

        try:
            for i, url in enumerate(urls, 1):
                puc_id = _puc_id_from_url(url)
                if document_exists(con, puc_id):
                    skipped += 1
                    continue

                logger.info("[%d/%d] Processing %s", i, len(urls), puc_id)
                ok = with_retry(process_document, client, browser, con, url, filters)
                if ok:
                    success += 1
                else:
                    failed += 1
        finally:
            browser.close()

    logger.info(
        "Scraping finished. success=%d | skipped=%d | failed=%d",
        success, skipped, failed,
    )
    logger.info("Database totals — documents: %d", count_documents(con))
    con.close()


if __name__ == "__main__":
    main()
