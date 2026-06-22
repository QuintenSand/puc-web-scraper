#!/usr/bin/env python3
"""
Diagnostic script — dump everything in a PUC document page that might contain
a PDF URL.  Run with:

    uv run python debug_page.py

This helps us figure out whether the PDF can be downloaded directly with httpx
or whether a browser (Playwright) is truly needed.
"""

import sys
import httpx
from bs4 import BeautifulSoup

URL = "https://puc.overheid.nl/nza/doc/PUC_813538_22/1/"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "nl-NL,nl;q=0.9,en;q=0.8",
}

print(f"Fetching: {URL}\n")
with httpx.Client(headers=HEADERS, follow_redirects=True, timeout=30) as client:
    r = client.get(URL)
    print(f"Status: {r.status_code}  Content-Type: {r.headers.get('content-type', '?')}\n")
    soup = BeautifulSoup(r.text, "lxml")

# ── 1. All links ────────────────────────────────────────────────────────────
print("=" * 60)
print("ALL LINKS (<a href>)")
print("=" * 60)
for a in soup.find_all("a", href=True):
    print(f"  href={a['href']!r:60s}  text={a.get_text(strip=True)[:60]!r}")

# ── 2. Elements with data-* attributes ──────────────────────────────────────
print("\n" + "=" * 60)
print("ELEMENTS WITH data-* ATTRIBUTES")
print("=" * 60)
found_data = False
for el in soup.find_all(True):
    data = {k: v for k, v in el.attrs.items()
            if k.startswith("data-") and isinstance(v, str)}
    if data:
        print(f"  <{el.name}> text={el.get_text(strip=True)[:40]!r}")
        for k, v in data.items():
            print(f"    {k} = {v!r}")
        found_data = True
if not found_data:
    print("  (none found)")

# ── 3. Iframes / embeds / objects ───────────────────────────────────────────
print("\n" + "=" * 60)
print("IFRAMES / EMBEDS / OBJECTS")
print("=" * 60)
found_embed = False
for tag in soup.find_all(["iframe", "embed", "object"]):
    attrs = dict(tag.attrs)
    print(f"  <{tag.name}> {attrs}")
    found_embed = True
if not found_embed:
    print("  (none found)")

# ── 4. Meta tags ─────────────────────────────────────────────────────────────
print("\n" + "=" * 60)
print("META TAGS")
print("=" * 60)
for meta in soup.find_all("meta"):
    print(f"  {dict(meta.attrs)}")

# ── 5. Script tag content ───────────────────────────────────────────────────
print("\n" + "=" * 60)
print("INLINE SCRIPT CONTENT (first 400 chars each)")
print("=" * 60)
for i, s in enumerate(soup.find_all("script")):
    src = s.get("src")
    txt = s.get_text().strip()
    if src:
        print(f"  [script {i}] (external) src={src!r}")
    elif txt:
        print(f"  [script {i}] {txt[:400]!r}")

# ── 6. Raw HTML around PDF-related keywords ──────────────────────────────────
print("\n" + "=" * 60)
print("RAW HTML LINES CONTAINING 'pdf' (case-insensitive)")
print("=" * 60)
for line in r.text.splitlines():
    if "pdf" in line.lower():
        print(f"  {line.strip()[:120]}")
