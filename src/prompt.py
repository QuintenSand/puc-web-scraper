# src/prompt.py
# Interactive terminal prompts that run before the scraper starts.
# Category options are fetched via httpx (see src/fetcher.py), then the user
# picks filters here. Returns a ScraperFilters dataclass consumed by main.py.

import logging
from dataclasses import dataclass, field
from datetime import date, datetime

logger = logging.getLogger(__name__)

_DIVIDER = "-" * 50


# ---------------------------------------------------------------------------
# Filter dataclass — passed around the rest of the program
# ---------------------------------------------------------------------------

@dataclass
class ScraperFilters:
    valid_only: bool = True           # True  → include gdlv/gd date in URL
    category_codes: list[str] = field(default_factory=list)
    #   empty list → use NZA000 (all categories)
    #   non-empty  → one URL-collection pass per code
    date_from: date | None = None     # inclusive lower bound on doc_date
    date_to:   date | None = None     # inclusive upper bound on doc_date
    keyword:   str  | None = None     # matched against title and doc_type


# ---------------------------------------------------------------------------
# Terminal UI helpers
# ---------------------------------------------------------------------------

def _print_header(text: str) -> None:
    print(f"\n{_DIVIDER}")
    print(f"  {text}")
    print(_DIVIDER)


def _ask_choice(prompt: str, options: list[str], allow_multiple: bool = False) -> list[int]:
    """Print a numbered menu and return selected 0-based indices."""
    for i, opt in enumerate(options, 1):
        print(f"  [{i}] {opt}")

    while True:
        raw = input(f"\n{prompt} ").strip()
        if not raw:
            return [0]
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


# ---------------------------------------------------------------------------
# Main prompt
# ---------------------------------------------------------------------------

def ask_filters(category_options: list[tuple[str, str]]) -> ScraperFilters:
    """
    Interactively ask the user what to scrape.

    category_options — list of (name, code) pairs from fetcher.fetch_category_options()
    Returns a filled-in ScraperFilters instance.
    """
    print("\n" + "=" * 50)
    print("  PUC SCRAPER — filter selection")
    print("=" * 50)

    # --- Validity ---
    _print_header("Validity filter")
    validity_options = [
        "Geldig vandaag (currently valid documents only)",
        "Alle (all documents)",
    ]
    choice = _ask_choice("Select [1/2] (default: 1):", validity_options)
    valid_only = choice[0] == 0

    # --- Category ---
    selected_codes: list[str] = []
    if category_options:
        _print_header("Document category")
        names = [name for name, _ in category_options]
        menu  = ["All categories"] + names
        print("  To pick one:      type a single number,   e.g.  26")
        print("  To pick multiple: type numbers separated by spaces or commas,")
        print("                    e.g.  26 32   or   26,32")
        indices = _ask_choice(
            "Select [default: 1 = all]:",
            menu,
            allow_multiple=True,
        )
        if 0 not in indices:
            selected_codes = [category_options[i - 1][1] for i in indices]
    else:
        print("\n  (No category filters detected — scraping all categories.)")

    # --- Date range ---
    _print_header("Date range  (leave blank to skip)")
    date_from = _ask_date("  Published from (YYYY-MM-DD):")
    date_to   = _ask_date("  Published to   (YYYY-MM-DD):")

    # --- Keyword ---
    _print_header("Keyword filter  (leave blank to scrape everything)")
    print("  Matched against the document title and type.")
    print("  Only documents containing the keyword are saved.")
    keyword_raw = input("\n  Keyword: ").strip()
    keyword = keyword_raw or None

    # --- Summary ---
    filters = ScraperFilters(
        valid_only=valid_only,
        category_codes=selected_codes,
        date_from=date_from,
        date_to=date_to,
        keyword=keyword,
    )
    _print_summary(filters, category_options)
    input("\nPress Enter to start scraping, or Ctrl-C to abort …")
    return filters


def _print_summary(f: ScraperFilters, category_options: list[tuple[str, str]]) -> None:
    # Map codes back to names for display
    code_to_name = {code: name for name, code in category_options}
    cat_display = (
        ", ".join(code_to_name.get(c, c) for c in f.category_codes)
        if f.category_codes else "All"
    )
    print("\n" + "=" * 50)
    print("  SCRAPE SUMMARY")
    print("=" * 50)
    print(f"  Validity  : {'Geldig vandaag' if f.valid_only else 'Alle'}")
    print(f"  Categories: {cat_display}")
    print(f"  Date from : {f.date_from or '—'}")
    print(f"  Date to   : {f.date_to   or '—'}")
    print(f"  Keyword   : {f.keyword   or '—'}")
