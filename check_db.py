# check_db.py
# Quick inspection script for the PUC DuckDB database.
# Run with:  uv run python check_db.py

import duckdb
from src.config import DB_PATH

con = duckdb.connect(DB_PATH, read_only=True)

# ---------------------------------------------------------------------------
# 1. Overview
# ---------------------------------------------------------------------------
n_docs = con.execute("SELECT COUNT(*) FROM documents").fetchone()[0]

print("=" * 60)
print("  PUC DATABASE OVERVIEW")
print("=" * 60)
print(f"  Documents : {n_docs}")

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
# 4. Content size distribution
# ---------------------------------------------------------------------------
print("\n--- Content size distribution ---")
row = con.execute("""
    SELECT
        MIN(LENGTH(content))    AS min_chars,
        MAX(LENGTH(content))    AS max_chars,
        AVG(LENGTH(content))    AS avg_chars,
        MEDIAN(LENGTH(content)) AS median_chars
    FROM documents
    WHERE content IS NOT NULL
""").fetchone()
if row and row[0] is not None:
    print(f"  Min    : {row[0]:,} chars")
    print(f"  Max    : {row[1]:,} chars")
    print(f"  Avg    : {row[2]:,.0f} chars")
    print(f"  Median : {row[3]:,.0f} chars")
else:
    print("  (no content yet)")

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
# 6. Content preview for the most recent document
# ---------------------------------------------------------------------------
if rows:
    sample_id = rows[0][0]
    print(f"\n--- Content preview for '{sample_id}' ---")
    row = con.execute("""
        SELECT LENGTH(content), content
        FROM documents
        WHERE puc_id = ?
    """, [sample_id]).fetchone()
    if row:
        total_chars, content = row
        print(f"  Total : {total_chars:,} chars")
        print(f"\n  First 500 chars:")
        print(f"  {content[:500].replace(chr(10), ' ')}")

print("\n" + "=" * 60)
con.close()
