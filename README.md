# PUC Web Scraper

A two-phase Selenium scraper for the [PUC Overheid (NZA) portal](https://puc.overheid.nl/nza/). It collects public NZA documents, extracts their full text (from HTML or PDF), and stores everything in a local DuckDB database — ready to be consumed by a downstream RAG pipeline for chunking, embedding, and retrieval.

## Features

- **Interactive filter prompts** — before scraping starts, the script fetches the live filter options from the site and asks what you want to scrape: validity status, document categories, an optional date range, and an optional keyword.
- **Two-phase execution** — collects all matching document URLs first, then processes them. Keeps crawling and extraction separate and resumable.
- **Dual extraction** — prefers the HTML article body; automatically falls back to downloading and parsing the PDF if the article is too short or absent.
- **Enriched metadata** — stores title, publication date, and document type alongside the full text.
- **Resumable** — both phases check DuckDB before doing any work, so re-running skips already-processed documents.
- **Automatic schema migration** — if you have a database from an older version of this project, missing columns are added and old column names are mapped automatically on first run.
- **Retry logic** — exponential backoff on transient network or render failures.
- **Safe browser lifecycle** — Chrome is opened inside a context manager and always quits cleanly, even on crash.
- **Inspection script** — `check_db.py` prints a full database overview with stats and a content preview.

## Project structure

```
puc-web-scraper/
├── main.py           # Entry point — orchestrates prompts + both phases
├── check_db.py       # Inspect the database contents
├── src/
│   ├── config.py     # All tunables (timeouts, URLs, …)
│   ├── browser.py    # Selenium context manager
│   ├── storage.py    # DuckDB schema, migration, and read/write helpers
│   ├── parser.py     # HTML→text and PDF→text extraction
│   └── prompt.py     # Interactive filter prompts + ScraperFilters dataclass
├── downloads/        # Temporary PDF downloads (auto-cleaned after extraction)
├── puc_data.db       # DuckDB database (created on first run)
└── scraper_debug.log # Full run log
```

## How it works

### 1. Filter selection

When you run the script, Chrome opens briefly to fetch the live filter options from the PUC portal. You are then asked in the terminal:

```
==================================================
  PUC SCRAPER — filter selection
==================================================

--------------------------------------------------
  Validity filter
--------------------------------------------------
  [1] Geldig vandaag (currently valid documents only)
  [2] Alle (all documents)

Select [1/2] (default: 1): 1

--------------------------------------------------
  Document category
--------------------------------------------------
  [1] All categories
  [2] Jeugdzorg
  [3] GGZ
  ...

Select one or more [default: 1 = all]: 2 3

--------------------------------------------------
  Date range  (leave blank to skip)
--------------------------------------------------
  Published from (YYYY-MM-DD): 2024-01-01
  Published to   (YYYY-MM-DD):

==================================================
  SCRAPE SUMMARY
==================================================
  Validity  : Geldig vandaag
  Categories: Jeugdzorg, GGZ
  Date from : 2024-01-01
  Date to   : —

--------------------------------------------------
  Keyword filter  (leave blank to scrape everything)
--------------------------------------------------
  Matched against the document title and type.
  Only documents containing the keyword are saved.

  Keyword: tarieven

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

### 2. URL collection (Phase 1)

The chosen filters are applied by clicking the corresponding buttons in the PUC portal. The scraper then paginates through all result pages and collects every matching document URL.

### 3. Document processing (Phase 2)

Each URL is visited and the text is extracted in one of two ways:

- **HTML** — if the page contains an `<article>` element with sufficient text, it is converted to plain text directly.
- **PDF** — if not, the scraper clicks the "Maak een PDF" or "PDF Openen" button, waits for the file to download, extracts the text with PyMuPDF, and deletes the local file afterwards.

Documents that don't contain the keyword in their title or document type are skipped before any content is downloaded. Documents outside the selected date range are also skipped. Documents already in the database are skipped automatically, making every run resumable.

## Database schema

One table is created automatically on first run:

**`documents`** — one row per source document:

| Column | Type | Description |
|---|---|---|
| `puc_id` | VARCHAR (PK) | Identifier extracted from the URL, e.g. `PUC_813946_22` |
| `url` | VARCHAR | Source URL |
| `title` | VARCHAR | Page `<h1>` title |
| `doc_date` | DATE | Publication date from the `<time>` element |
| `doc_type` | VARCHAR | Document type (e.g. `Beleidsregel`, `Regelgeving`) |
| `source_format` | VARCHAR | `HTML` or `PDF` |
| `content` | TEXT | Full extracted text |
| `scraped_at` | TIMESTAMP | When the row was written |

## Installation

**Prerequisites**

- Python 3.9+
- [uv](https://docs.astral.sh/uv/) package manager
- Google Chrome — ChromeDriver is managed automatically by Selenium

**Setup**

```bash
git clone https://github.com/QuintenSand/puc-web-scraper.git
cd puc-web-scraper
uv sync
```

## Usage

Run the scraper:

```bash
uv run python main.py
```

Inspect the database after a run:

```bash
uv run python check_db.py
```

## Configuration

All tunables live in `src/config.py`:

| Variable | Default | Description |
|---|---|---|
| `PAGE_LOAD_TIMEOUT` | `10` | Seconds for Selenium `WebDriverWait` |
| `PDF_DOWNLOAD_TIMEOUT` | `30` | Seconds to wait for a PDF to appear |
| `INTER_PAGE_DELAY` | `3` | Seconds between pagination clicks |
| `MIN_ARTICLE_LENGTH` | `300` | Characters; below this the PDF path is used |
| `MAX_RETRIES` | `3` | Retry attempts per document |
| `RETRY_BACKOFF` | `2.0` | Base seconds for exponential backoff |
