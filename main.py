# main.py
# PUC web scraper — RAG-optimised edition.
# https://puc.overheid.nl/nza/
#
# Run with:
#   uv run python main.py
#
# Two-phase approach
# ------------------
# Phase 1 — URL collection:  navigate the paginated list, harvest every
#            document link.
# Phase 2 — Document processing:  visit each URL, extract text (HTML article
#            or PDF fallback), chunk it for RAG, and persist to DuckDB.

import logging
import os
import time

from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from src.browser import get_driver
from src.config import (
    BASE_URL,
    INTER_PAGE_DELAY,
    LOG_FILE,
    MAX_RETRIES,
    MIN_ARTICLE_LENGTH,
    RETRY_BACKOFF,
)
from src.parser import (
    chunk_text,
    existing_pdfs,
    html_to_text,
    pdf_to_text,
    wait_for_new_pdf,
)
from src.storage import (
    count_chunks,
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
# Retry decorator
# ---------------------------------------------------------------------------

def with_retry(fn, *args, retries: int = MAX_RETRIES, backoff: float = RETRY_BACKOFF, **kwargs):
    """
    Call *fn* up to *retries* times, doubling the sleep between attempts.
    Returns the function's return value or None if all attempts fail.
    """
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
# Phase 1 — URL collection
# ---------------------------------------------------------------------------

def collect_urls(driver, wait: WebDriverWait) -> list[str]:
    """
    Navigate the PUC NZa list (with 'Alle' + 'Geldig vandaag' filters applied)
    and return every unique document URL found across all pages.
    """
    logger.info("Phase 1: collecting document URLs from %s", BASE_URL)
    driver.get(BASE_URL)

    # Apply "Alle" filter
    alle_btn = wait.until(
        EC.element_to_be_clickable((By.XPATH, "//a[contains(., 'Alle')]"))
    )
    alle_btn.click()

    # Apply "Geldig vandaag" filter
    geldig_btn = wait.until(
        EC.element_to_be_clickable((By.XPATH, "//label[contains(., 'Geldig vandaag')]"))
    )
    geldig_btn.click()

    all_urls: list[str] = []
    page = 1

    while True:
        logger.info("Crawling list page %d (%s)", page, driver.current_url)

        wait.until(
            EC.presence_of_all_elements_located(
                (By.XPATH, "//a[contains(@href, 'doc/PUC_')]")
            )
        )
        links = driver.find_elements(By.XPATH, "//a[contains(@href, 'doc/PUC_')]")
        logger.info("  Found %d links on this page", len(links))
        for link in links:
            href = link.get_attribute("href")
            if href:
                all_urls.append(href)

        # Try to advance to the next page
        try:
            next_btn = driver.find_element(By.XPATH, "//a[contains(., 'Volgende')]")
            driver.execute_script("arguments[0].scrollIntoView();", next_btn)
            next_btn.click()
            time.sleep(INTER_PAGE_DELAY)
            page += 1
        except Exception:
            logger.info("No 'Volgende' button found — reached last page.")
            break

    unique_urls = list(dict.fromkeys(all_urls))   # deduplicate, preserve order
    logger.info("Phase 1 complete. Collected %d unique URLs.", len(unique_urls))
    return unique_urls


# ---------------------------------------------------------------------------
# Phase 2 — Document processing
# ---------------------------------------------------------------------------

def _puc_id_from_url(url: str) -> str:
    """Extract the PUC identifier from a document URL."""
    parts = url.rstrip("/").split("/")
    # URL patterns:
    #   …/doc/PUC_123456_22/          → parts[-2] == 'PUC_123456_22'
    #   …/doc/PUC_123456_22/1/        → parts[-3] == 'PUC_123456_22'
    for part in reversed(parts):
        if part.startswith("PUC_"):
            return part
    # Fallback: use the last meaningful segment
    return parts[-1] or parts[-2]


def _extract_metadata(driver) -> dict:
    """
    Best-effort extraction of title, date, and document type from the page.
    Returns a dict with keys: title, doc_date, doc_type.
    All values may be None if not found.
    """
    meta: dict = {"title": None, "doc_date": None, "doc_type": None}

    # Title — typically in <h1> or <title>
    try:
        meta["title"] = driver.find_element(By.TAG_NAME, "h1").text.strip() or None
    except Exception:
        pass

    # Publication date — PUC pages often have a <time> element or a dt/dd pair
    try:
        time_el = driver.find_element(By.TAG_NAME, "time")
        meta["doc_date"] = time_el.get_attribute("datetime") or time_el.text.strip() or None
    except Exception:
        pass

    # Document type — look for a <dd> near a <dt> that says "Soort"
    try:
        dt_els = driver.find_elements(By.TAG_NAME, "dt")
        for dt in dt_els:
            if "soort" in dt.text.lower() or "type" in dt.text.lower():
                dd = dt.find_element(By.XPATH, "following-sibling::dd[1]")
                meta["doc_type"] = dd.text.strip() or None
                break
    except Exception:
        pass

    return meta


def process_document(driver, wait: WebDriverWait, con, url: str) -> bool:
    """
    Visit *url*, extract and chunk the document text, and save to DuckDB.
    Returns True on success, False on failure.
    """
    puc_id = _puc_id_from_url(url)

    if document_exists(con, puc_id):
        logger.debug("Already in DB, skipping: %s", puc_id)
        return True

    driver.get(url)
    time.sleep(2)   # brief pause; the site uses some JS rendering

    meta = _extract_metadata(driver)
    source_format = "HTML"
    text = ""

    try:
        # --- Option A: HTML article ---
        articles = driver.find_elements(By.TAG_NAME, "article")
        if articles and len(articles[0].text.strip()) >= MIN_ARTICLE_LENGTH:
            html = articles[0].get_attribute("innerHTML")
            text = html_to_text(html)
            source_format = "HTML"

        # --- Option B: PDF download ---
        else:
            pdf_btn_xpath = (
                "//a[contains(., 'Maak een PDF')]"
                " | //a[contains(., 'PDF Openen')]"
            )
            pdf_btn = wait.until(EC.element_to_be_clickable((By.XPATH, pdf_btn_xpath)))
            before = existing_pdfs()
            pdf_btn.click()

            # Some pages show a "Klaar!" confirmation button
            try:
                finish_btn = WebDriverWait(driver, 5).until(
                    EC.element_to_be_clickable((By.XPATH, "//a[contains(., 'Klaar!')]"))
                )
                finish_btn.click()
            except Exception:
                pass  # No confirmation step needed

            pdf_path = wait_for_new_pdf(before)
            if pdf_path:
                text = pdf_to_text(pdf_path)
                source_format = "PDF"
                os.remove(pdf_path)
            else:
                logger.warning("PDF download timed out for %s", puc_id)
                return False

    except Exception:
        logger.exception("Error extracting content from %s", url)
        return False

    if not text.strip():
        logger.warning("No text extracted from %s", puc_id)
        return False

    chunks = chunk_text(text)
    save_document(
        con,
        puc_id,
        url,
        chunks,
        title=meta["title"],
        doc_date=meta["doc_date"],
        doc_type=meta["doc_type"],
        source_format=source_format,
    )
    logger.info(
        "Saved %s | format=%s | chunks=%d | title=%s",
        puc_id, source_format, len(chunks), meta["title"],
    )
    return True


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    con = get_connection()

    with get_driver() as (driver, wait):
        # Phase 1 — collect URLs
        urls = collect_urls(driver, wait)

        # Phase 2 — process documents
        logger.info("Phase 2: processing %d documents", len(urls))
        success, skipped, failed = 0, 0, 0

        for i, url in enumerate(urls, 1):
            puc_id = _puc_id_from_url(url)
            if document_exists(con, puc_id):
                skipped += 1
                continue

            logger.info("[%d/%d] Processing %s", i, len(urls), puc_id)
            ok = with_retry(process_document, driver, wait, con, url)
            if ok:
                success += 1
            else:
                failed += 1

    logger.info(
        "Scraping finished. Documents — success: %d | skipped: %d | failed: %d",
        success, skipped, failed,
    )
    logger.info(
        "Database totals — documents: %d | chunks: %d",
        count_documents(con), count_chunks(con),
    )
    con.close()


if __name__ == "__main__":
    main()
