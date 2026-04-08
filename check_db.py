# check_db.py
# Quick inspection script for the PUC DuckDB database.
# Run with:  uv run python check_db.py

import duckdb
from src.config import DB_PATH

con = duckdb.connect(DB_PATH, read_only=True)

# ---------------------------------------------------------------------------
# 1. Overview
# ---------------------------------------------------------------------------
n_docs   = con.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
n_chunks = con.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
avg_chunks = n_chunks / n_docs if n_docs else 0

print("=" * 60)
print("  PUC DATABASE OVERVIEW")
print("=" * 60)
print(f"  Documents : {n_docs}")
print(f"  Chunks    : {n_chunks}  (avg {avg_chunks:.1f} per document)")

# ---------------------------------------------------------------------------
# 2. Breakdown by source format (HTML vs PDF)
# ---------------------------------------------------------------------------
print("\n--- By source format ---")
rows = con.execute("""
    SELECT source_format, COUNT(*) AS n
    FROM documents
    GROUP BY source_format
    ORDER BY n DESC
""").fetchall()
for fmt, n in rows:
    print(f"  {fmt or 'unknown':10s}  {n}")

# ---------------------------------------------------------------------------
# 3. Breakdown by document type
# ---------------------------------------------------------------------------
print("\n--- By document type (top 10) ---")
rows = con.execute("""
    SELECT COALESCE(doc_type, '(unknown)') AS doc_type, COUNT(*) AS n
    FROM documents
    GROUP BY doc_type
    ORDER BY n DESC
    LIMIT 10
""").fetchall()
for doc_type, n in rows:
    print(f"  {doc_type:40s}  {n}")

# ---------------------------------------------------------------------------
# 4. Chunk size distribution
# ---------------------------------------------------------------------------
print("\n--- Chunk size distribution ---")
row = con.execute("""
    SELECT
        MIN(chunk_size)  AS min_chars,
        MAX(chunk_size)  AS max_chars,
        AVG(chunk_size)  AS avg_chars,
        MEDIAN(chunk_size) AS median_chars
    FROM chunks
""").fetchone()
if row and row[0] is not None:
    print(f"  Min    : {row[0]} chars")
    print(f"  Max    : {row[1]} chars")
    print(f"  Avg    : {row[2]:.0f} chars")
    print(f"  Median : {row[3]:.0f} chars")
else:
    print("  (no chunks yet)")

# ---------------------------------------------------------------------------
# 5. Sample documents
# ---------------------------------------------------------------------------
print("\n--- 5 most recently scraped documents ---")
rows = con.execute("""
    SELECT puc_id, source_format, doc_type, title, scraped_at
    FROM documents
    ORDER BY scraped_at DESC
    LIMIT 5
""").fetchall()
for puc_id, fmt, doc_type, title, scraped_at in rows:
    print(f"\n  ID      : {puc_id}")
    print(f"  Format  : {fmt}")
    print(f"  Type    : {doc_type or '—'}")
    print(f"  Title   : {(title or '—')[:70]}")
    print(f"  Scraped : {scraped_at}")

# ---------------------------------------------------------------------------
# 6. Sample chunks for the most recent document
# ---------------------------------------------------------------------------
if rows:
    sample_id = rows[0][0]
    print(f"\n--- First 2 chunks of '{sample_id}' ---")
    chunks = con.execute("""
        SELECT chunk_index, chunk_size, content
        FROM chunks
        WHERE puc_id = ?
        ORDER BY chunk_index
        LIMIT 2
    """, [sample_id]).fetchall()
    for idx, size, content in chunks:
        print(f"\n  [chunk {idx}]  {size} chars")
        print(f"  {content[:300].replace(chr(10), ' ')}{'…' if size > 300 else ''}")

print("\n" + "=" * 60)
con.close()
