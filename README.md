# PUC Web Scraper

A scraper for the [PUC Overheid (NZA) portal](https://puc.overheid.nl/nza/). It collects public NZA documents, extracts their full text, and stores everything in a local DuckDB database — ready to be consumed by a downstream RAG pipeline for chunking, embedding, and retrieval.

## How it works

The PUC portal uses path-based routing (server-side rendering), so a browser is **not needed** for the vast majority of documents. The scraper uses lightweight HTTP requests for everything it can, and only falls back to a browser as a last resort for the rare page where a PDF is only accessible via a JavaScript button.

| Task | Tool |
|---|---|
| Filter selection & URL collection | `httpx` + `BeautifulSoup` |
| HTML document extraction | `httpx` + `BeautifulSoup` |
| Direct PDF download (e.g. Jeugdzorg) | `httpx` + PyMuPDF |
| JS-driven PDF button (last resort) | Selenium + Chrome |

## Features

- **No browser required for most runs** — if all matching documents have HTML content or direct PDF links, Chrome is never opened.
- **Clean-slate option** — if the database already contains documents, you are asked whether to clear it before starting (requires typing `yes` to confirm).
- **Interactive filter prompts** — before scraping starts, fetches live category options and asks you to choose validity, categories, date range, and keyword.
- **Two-phase execution** — collects all matching URLs first, then processes them.
- **Three-tier text extraction** — prefers HTML article body; falls back to direct PDF download via httpx; finally uses Chrome for JS-driven PDF buttons.
- **Keyword filter** — only saves documents whose title or type contains the keyword. Checked before any content is downloaded.
- **Enriched metadata** — stores title, publication date, and document type alongside the full text.
- **Resumable** — documents already in the database are skipped automatically.
- **Automatic schema migration** — existing databases from older versions are upgraded automatically.
- **Self-healing rate limiting (AIMD)** — a shared adaptive throttle paces every request (randomised delay + jitter). If the server returns 429/503 it honours `Retry-After`, briefly cools down (capped at `MAX_COOLDOWN`), and slows the pace by `SLOWDOWN_FACTOR` (bounded by `MAX_REQUEST_DELAY`). After `SPEEDUP_AFTER` consecutive successes it speeds back up toward `MIN_REQUEST_DELAY`, so the scraper continuously finds the fastest pace the server tolerates and recovers automatically instead of staying crippled for the rest of the run. Tunables live in `src/config.py` (`REQUEST_DELAY`, `MIN_REQUEST_DELAY`, `REQUEST_JITTER`, `SPEEDUP_AFTER`, `RATELIMIT_COOLDOWN`, `MAX_COOLDOWN`, `MAX_REQUEST_DELAY`, …).
- **Rotating User-Agent** — a different browser User-Agent per run to avoid a static fingerprint.
- **Retry logic** — exponential backoff on transient failures.
- **Inspection script** — `check_db.py` prints a full overview with stats and content preview.

## Project structure

```
puc-web-scraper/
├── main.py           # Entry point — orchestrates prompts + both phases
├── check_db.py       # Inspect the database contents
├── debug_page.py     # Diagnostic tool — dump a page's links/embeds/scripts
├── src/
│   ├── config.py     # All tunables (timeouts, URLs, ChromeDriver path, …)
│   ├── fetcher.py    # httpx client, URL builder, BeautifulSoup parsers
│   ├── browser.py    # LazyBrowser — Selenium/Chrome, only for JS-driven PDFs
│   ├── storage.py    # DuckDB schema, migration, read/write helpers
│   ├── parser.py     # PDF→text (file and bytes) extraction helpers
│   └── prompt.py     # Interactive filter prompts + ScraperFilters dataclass
├── downloads/        # Temporary PDF downloads (auto-cleaned after extraction)
├── puc_data.db       # DuckDB database (created on first run)
└── scraper_debug.log # Full run log
```

## Filter selection

When you run the script, it first asks whether to clear the database (if it already contains documents), then asks four filter questions before touching the network:

```
==================================================
  PUC SCRAPER — filter selection
==================================================

  Validity   : [1] Geldig vandaag   [2] Alle
  Categories : [1] All  [2] Jeugdzorg  [3] GGZ  …  (fetched live)
  Date range : Published from / to (YYYY-MM-DD, optional)
  Keyword    : matched against title and doc_type (optional)

==================================================
  SCRAPE SUMMARY
==================================================
  Validity  : Geldig vandaag
  Categories: Jeugdzorg, GGZ
  Date from : 2024-01-01
  Date to   : —
  Keyword   : tarieven

Press Enter to start scraping, or Ctrl-C to abort …
```

## Document processing (Phase 2)

Each URL is visited and text is extracted using a three-tier fallback:

1. **HTML** — if the page has an `<article>` element with sufficient text, it is extracted with BeautifulSoup. No browser needed.
2. **Direct PDF** — if the page embeds a PDF via `<object>`, `<embed>`, a direct link, or a `data-*` attribute, it is downloaded with httpx and extracted with PyMuPDF. No browser needed.
3. **JS-driven PDF** — if the PDF is only accessible via a JavaScript button ("Maak een PDF" or "PDF Openen"), Chrome is started lazily and the download is captured via Selenium.

Documents not matching the keyword, outside the date range, or already in the database are skipped before any content is downloaded.

## Database schema

**`documents`** — one row per source document:

| Column | Type | Description |
|---|---|---|
| `puc_id` | VARCHAR (PK) | e.g. `PUC_813946_22` |
| `url` | VARCHAR | Source URL |
| `title` | VARCHAR | Page `<h1>` title |
| `doc_date` | DATE | Publication date |
| `doc_type` | VARCHAR | e.g. `Beleidsregel`, `Regelgeving` |
| `source_format` | VARCHAR | `HTML` or `PDF` |
| `content` | TEXT | Full extracted text |
| `scraped_at` | TIMESTAMP | When the row was written |

## Installation

**Prerequisites**

- Python 3.10+
- [uv](https://docs.astral.sh/uv/) package manager
- Google Chrome + ChromeDriver — only needed as a last resort for JS-driven PDF pages; most categories work without it

**Setup**

```bash
git clone https://github.com/QuintenSand/puc-web-scraper.git
cd puc-web-scraper
uv sync
```

## Usage

```bash
uv run python main.py      # run the scraper
uv run python check_db.py  # inspect the database
```

## Configuration

All tunables live in `src/config.py`:

| Variable | Default | Description |
|---|---|---|
| `PAGE_LOAD_TIMEOUT` | `10` | Seconds for Selenium page load (JS-driven PDF pages only) |
| `PDF_DOWNLOAD_TIMEOUT` | `30` | Seconds to wait for a PDF file to appear |
| `INTER_PAGE_DELAY` | `3` | Seconds between paginated list requests |
| `MIN_ARTICLE_LENGTH` | `300` | Characters; below this the PDF path is used |
| `MAX_RETRIES` | `3` | Retry attempts per document |
| `RETRY_BACKOFF` | `2.0` | Base seconds for exponential backoff |
| `CHROME_DRIVER_PATH` | `None` | Set to `chromedriver.exe` path on firewalled machines |
