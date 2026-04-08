# src/storage.py
# DuckDB storage layer with an RAG-optimised schema.
#
# Schema rationale for RAG
# -------------------------
# RAG retrievers work best when:
#   1. Each row is a *chunk*, not a full document (better semantic granularity).
#   2. Metadata (title, date, type) is stored alongside the chunk so that it
#      can be injected into the LLM prompt as attribution context.
#   3. A documents table keeps one row per source URL so we can cheaply check
#      whether a document was already scraped without re-fetching it.

import duckdb

from .config import DB_PATH


def get_connection() -> duckdb.DuckDBPyConnection:
    """Open (or create) the database and ensure the schema exists."""
    con = duckdb.connect(DB_PATH)
    _create_schema(con)
    return con


def _create_schema(con: duckdb.DuckDBPyConnection) -> None:
    # One row per source document — used as a cheap "seen" check.
    con.execute("""
        CREATE TABLE IF NOT EXISTS documents (
            puc_id        VARCHAR PRIMARY KEY,
            url           VARCHAR NOT NULL,
            title         VARCHAR,
            doc_date      DATE,
            doc_type      VARCHAR,        -- 'regelgeving', 'beleidsregel', etc.
            source_format VARCHAR,        -- 'HTML' | 'PDF'
            scraped_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # One row per text chunk — what the RAG retriever actually searches.
    con.execute("""
        CREATE TABLE IF NOT EXISTS chunks (
            chunk_id      VARCHAR PRIMARY KEY,   -- '{puc_id}__{chunk_index}'
            puc_id        VARCHAR NOT NULL REFERENCES documents(puc_id),
            chunk_index   INTEGER NOT NULL,
            content       TEXT NOT NULL,
            chunk_size    INTEGER,               -- character count, handy for debugging
            created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)


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
    chunks: list[str],
    *,
    title: str | None = None,
    doc_date: str | None = None,   # ISO-8601 string, e.g. '2024-03-15'
    doc_type: str | None = None,
    source_format: str = "HTML",
) -> None:
    """
    Persist a document and all its text chunks in one transaction.
    Existing entries for the same puc_id are replaced.
    """
    with con.cursor() as cur:
        # Upsert document record
        cur.execute("""
            INSERT OR REPLACE INTO documents
                (puc_id, url, title, doc_date, doc_type, source_format)
            VALUES (?, ?, ?, ?, ?, ?)
        """, [puc_id, url, title, doc_date, doc_type, source_format])

        # Remove stale chunks (needed for OR REPLACE semantics on documents)
        cur.execute("DELETE FROM chunks WHERE puc_id = ?", [puc_id])

        # Insert new chunks
        rows = [
            (f"{puc_id}__{i}", puc_id, i, chunk, len(chunk))
            for i, chunk in enumerate(chunks)
        ]
        cur.executemany("""
            INSERT INTO chunks (chunk_id, puc_id, chunk_index, content, chunk_size)
            VALUES (?, ?, ?, ?, ?)
        """, rows)


# ---------------------------------------------------------------------------
# Read helpers (useful for debugging / inspection)
# ---------------------------------------------------------------------------

def count_documents(con: duckdb.DuckDBPyConnection) -> int:
    return con.execute("SELECT COUNT(*) FROM documents").fetchone()[0]


def count_chunks(con: duckdb.DuckDBPyConnection) -> int:
    return con.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
