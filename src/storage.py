# src/storage.py
# DuckDB storage layer.
#
# One table — documents — stores the full extracted text of each PUC document
# alongside its metadata. Chunking for RAG happens downstream in a separate
# pipeline, not here.

import duckdb

from .config import DB_PATH


def get_connection() -> duckdb.DuckDBPyConnection:
    """Open (or create) the database and ensure the schema exists."""
    con = duckdb.connect(DB_PATH)
    _create_schema(con)
    _migrate_schema(con)
    return con


def _create_schema(con: duckdb.DuckDBPyConnection) -> None:
    con.execute("""
        CREATE TABLE IF NOT EXISTS documents (
            puc_id        VARCHAR PRIMARY KEY,
            url           VARCHAR NOT NULL,
            title         VARCHAR,
            doc_date      DATE,
            doc_type      VARCHAR,        -- e.g. 'Beleidsregel', 'Regelgeving'
            source_format VARCHAR,        -- 'HTML' | 'PDF'
            content       TEXT,           -- full extracted text
            scraped_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)


def _migrate_schema(con: duckdb.DuckDBPyConnection) -> None:
    """
    Bring an older database up to the current schema without losing data.

    The original schema used different column names:
      - content_md  → content
      - source_type → source_format

    New columns (title, doc_date, doc_type) are added as nullable so
    existing rows remain valid; they will be populated on re-scrape.
    """
    existing = {
        row[0]
        for row in con.execute("""
            SELECT column_name
            FROM information_schema.columns
            WHERE table_name = 'documents'
        """).fetchall()
    }

    # Add any missing columns introduced in the new schema
    new_columns = [
        ("title",         "VARCHAR"),
        ("doc_date",      "DATE"),
        ("doc_type",      "VARCHAR"),
        ("source_format", "VARCHAR"),
        ("content",       "TEXT"),
    ]
    for col, col_type in new_columns:
        if col not in existing:
            con.execute(f"ALTER TABLE documents ADD COLUMN {col} {col_type}")

    # Migrate data from old column names if they still exist
    if "content_md" in existing:
        con.execute("UPDATE documents SET content = content_md WHERE content IS NULL")

    if "source_type" in existing:
        con.execute("UPDATE documents SET source_format = source_type WHERE source_format IS NULL")


# ---------------------------------------------------------------------------
# Write helpers
# ---------------------------------------------------------------------------

def document_exists(con: duckdb.DuckDBPyConnection, puc_id: str) -> bool:
    row = con.execute(
        "SELECT 1 FROM documents WHERE puc_id = ?", [puc_id]
    ).fetchone()
    return row is not None


def save_document(
    con: duckdb.DuckDBPyConnection,
    puc_id: str,
    url: str,
    content: str,
    *,
    title: str | None = None,
    doc_date: str | None = None,   # ISO-8601 string, e.g. '2024-03-15'
    doc_type: str | None = None,
    source_format: str = "HTML",
) -> None:
    """Persist a document. Existing entries for the same puc_id are replaced."""
    con.execute("""
        INSERT OR REPLACE INTO documents
            (puc_id, url, title, doc_date, doc_type, source_format, content)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, [puc_id, url, title, doc_date, doc_type, source_format, content])


# ---------------------------------------------------------------------------
# Read helpers (useful for debugging / inspection)
# ---------------------------------------------------------------------------

def count_documents(con: duckdb.DuckDBPyConnection) -> int:
    return con.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
