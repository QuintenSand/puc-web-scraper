# PUC Web Scraper

A two-phase Selenium scraper for the [PUC Overheid (NZA) portal](https://puc.overheid.nl/nza/). It collects all public NZA documents, extracts their full text, and stores everything in a local DuckDB database — ready to be consumed by a downstream RAG pipeline for chunking, embedding, and retrieval.

## Features

- **Two-phase execution** — collects all document URLs first, then processes them. This keeps the list crawl and content extraction separate and resumable.
- **Dual extraction** — prefers the HTML article body; falls back to downloading and parsing the PDF if the article is too short or absent.
- **Enriched metadata** — stores title, publication date, and document type alongside the full text.
- **Resumable** — both phases check DuckDB before doing any work, so re-running skips already-processed documents.
- **Retry logic** — exponential backoff on transient network or render failures.
- **Safe browser lifecycle** — Chrome is opened inside a context manager and always quits cleanly, even on crash.
- **Inspection script** — `check_db.py` prints a full database overview with stats and a content preview.

## Project structure

```
puc-web-scraper/
├── main.py           # Entry point — orchestrates both phases
├── check_db.py       # Inspect the database contents
├── src/
│   ├── config.py     # All tunables (timeouts, URLs, …)
│   ├── browser.py    # Selenium context manager
│   ├── storage.py    # DuckDB schema + read/write helpers
│   └── parser.py     # HTML→text and PDF→text extraction
├── downloads/        # Temporary PDF downloads (auto-cleaned after extraction)
├── puc_data.db       # DuckDB database (created on first run)
└── scraper_debug.log # Full run log
```

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
