# src/prompt.py
# Interactive terminal prompts that run before the scraper starts.
# Fetches available category filters from the live PUC site, then asks
# the user what they want to scrape. Returns a ScraperFilters dataclass
# that collect_urls() and process_document() both consume.

import logging
from dataclasses import dataclass, field
from datetime import date, datetime

from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from .config import BASE_URL

logger = logging.getLogger(__name__)

_DIVIDER = "-" * 50


# ---------------------------------------------------------------------------
# Filter dataclass — passed around the rest of the program
# ---------------------------------------------------------------------------

@dataclass
class ScraperFilters:
    valid_only: bool = True          # True  → click "Geldig vandaag"
    #                                  False → leave on default ("Alle")
    categories: list[str] = field(default_factory=list)
    #   empty list → scrape all categories
    #   non-empty  → click each named category filter on the site
    date_from: date | None = None    # inclusive lower bound on doc_date
    date_to:   date | None = None    # inclusive upper bound on doc_date


# ---------------------------------------------------------------------------
# Step 1 — fetch available categories from the live site
# ---------------------------------------------------------------------------

def fetch_available_categories(driver, wait: WebDriverWait) -> list[str]:
    """
    Navigate to the PUC portal, expand the full filter view, and return
    the list of category labels found in the filter sidebar.

    Returns an empty list if no categories could be detected — the caller
    should then skip the category prompt and scrape everything.
    """
    logger.info("Fetching available filter categories from %s …", BASE_URL)
    driver.get(BASE_URL)

    # Expand the "Alle" view so all category filters become visible
    try:
        alle_btn = wait.until(
            EC.element_to_be_clickable((By.XPATH, "//a[contains(., 'Alle')]"))
        )
        alle_btn.click()
    except Exception:
        logger.warning("Could not click 'Alle' — category list may be incomplete.")

    # Collect filter labels: look for links or labels inside common filter
    # containers (aside, nav, or elements with 'filter' in their class/id).
    candidates = driver.find_elements(
        By.XPATH,
        "//aside//a | //aside//label"
        " | //*[contains(@class,'filter')]//a"
        " | //*[contains(@id,'filter')]//a"
        " | //*[contains(@class,'facet')]//a"
    )

    seen: dict[str, bool] = {}
    categories: list[str] = []
    skip_words = {"alle", "volgende", "vorige", "meer", "minder", "geldig"}

    for el in candidates:
        label = el.text.strip()
        if not label:
            continue
        key = label.lower()
        if key in skip_words or key in seen:
            continue
        seen[key] = True
        categories.append(label)

    logger.info("Found %d category options.", len(categories))
    return categories


# ---------------------------------------------------------------------------
# Step 2 — ask the user in the terminal
# ---------------------------------------------------------------------------

def _print_header(text: str) -> None:
    print(f"\n{_DIVIDER}")
    print(f"  {text}")
    print(_DIVIDER)


def _ask_choice(prompt: str, options: list[str], allow_multiple: bool = False) -> list[int]:
    """
    Print a numbered menu and return the selected 0-based index/indices.
    Keeps asking until valid input is given.
    """
    for i, opt in enumerate(options, 1):
        print(f"  [{i}] {opt}")

    while True:
        raw = input(f"\n{prompt} ").strip()
        if not raw:
            return [0]   # default: first option

        try:
            if allow_multiple:
                indices = [int(x) - 1 for x in raw.replace(",", " ").split()]
                if all(0 <= idx < len(options) for idx in indices):
                    return indices
            else:
                idx = int(raw) - 1
                if 0 <= idx < len(options):
                    return [idx]
        except ValueError:
            pass

        print("  Invalid input, please try again.")


def _ask_date(prompt: str) -> date | None:
    """Ask for an optional date in YYYY-MM-DD format. Blank = no filter."""
    while True:
        raw = input(f"{prompt} ").strip()
        if not raw:
            return None
        try:
            return datetime.strptime(raw, "%Y-%m-%d").date()
        except ValueError:
            print("  Invalid format. Use YYYY-MM-DD or leave blank.")


def ask_filters(available_categories: list[str]) -> ScraperFilters:
    """
    Interactively ask the user what to scrape.
    Returns a filled-in ScraperFilters instance.
    """
    print("\n" + "=" * 50)
    print("  PUC SCRAPER — filter selection")
    print("=" * 50)

    # --- Validity ---
    _print_header("Validity filter")
    validity_options = ["Geldig vandaag (currently valid documents only)", "Alle (all documents)"]
    choice = _ask_choice("Select [1/2] (default: 1):", validity_options)
    valid_only = choice[0] == 0

    # --- Category ---
    selected_categories: list[str] = []
    if available_categories:
        _print_header("Document category")
        category_options = ["All categories"] + available_categories
        print("  You can select multiple categories separated by spaces or commas.")
        indices = _ask_choice(
            "Select one or more [default: 1 = all]:",
            category_options,
            allow_multiple=True,
        )
        # index 0 = "All categories" → empty list
        if 0 not in indices:
            selected_categories = [available_categories[i - 1] for i in indices]
    else:
        print("\n  (No category filters detected on the site — scraping all categories.)")

    # --- Date range ---
    _print_header("Date range  (leave blank to skip)")
    date_from = _ask_date("  Published from (YYYY-MM-DD):")
    date_to   = _ask_date("  Published to   (YYYY-MM-DD):")

    # --- Confirmation ---
    filters = ScraperFilters(
        valid_only=valid_only,
        categories=selected_categories,
        date_from=date_from,
        date_to=date_to,
    )
    _print_summary(filters)

    input("\nPress Enter to start scraping, or Ctrl-C to abort …")
    return filters


def _print_summary(f: ScraperFilters) -> None:
    print("\n" + "=" * 50)
    print("  SCRAPE SUMMARY")
    print("=" * 50)
    print(f"  Validity  : {'Geldig vandaag' if f.valid_only else 'Alle'}")
    cats = ", ".join(f.categories) if f.categories else "All"
    print(f"  Categories: {cats}")
    print(f"  Date from : {f.date_from or '—'}")
    print(f"  Date to   : {f.date_to   or '—'}")
