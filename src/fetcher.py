# src/fetcher.py
# Lightweight HTTP client for PUC pages using httpx + BeautifulSoup.
#
# Now that we know the PUC site uses path-based routing (server-side rendering),
# we can skip Selenium entirely for both list pages and HTML document pages.
# Chrome is only started if a document requires a PDF download (see browser.py).
#
# Politeness / anti-blocking (AIMD self-healing)
# ----------------------------------------------
# Every outbound request goes through a single shared, adaptive throttle so we
# never hammer the source site (which previously got our IP blocked) — but,
# unlike the old throttle, it RECOVERS on its own:
#
#   * requests are spaced by a minimum delay + random jitter;
#   * a rate-limit / overload status (429/503/…) MULTIPLIES the delay and
#     triggers a short cooldown (honouring Retry-After when present);
#   * sustained success ADDITIVELY speeds the pace back up toward the floor.
#
# The spacing uses a slot-reservation scheme: each worker reserves its next
# send slot under a short lock and then sleeps OUTSIDE the lock, so different
# documents' network/parse time genuinely overlaps across worker threads
# (real concurrency, capped at ~1 / current-delay requests per second).
#
# Use `polite_get` / `polite_head` for raw requests so they share the throttle.

import email.utils
import logging
import random
import re
import threading
import time

import httpx
from bs4 import BeautifulSoup

from .config import (
    BASE_URL,
    MAX_COOLDOWN,
    MAX_REQUEST_DELAY,
    MAX_RETRIES,
    MIN_ARTICLE_LENGTH,
    MIN_REQUEST_DELAY,
    RATELIMIT_COOLDOWN,
    REQUEST_DELAY,
    REQUEST_JITTER,
    RESPECT_RETRY_AFTER,
    RETRY_STATUS_CODES,
    SLOWDOWN_FACTOR,
    SPEEDUP_AFTER,
    SPEEDUP_STEP,
    USER_AGENTS,
)
from .parser import html_to_text

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Adaptive throttle (shared across every request in the process)
# ---------------------------------------------------------------------------


class _Throttle:
    """
    Paces outbound requests with an AIMD (additive-increase / multiplicative-
    decrease) strategy and adapts to server push-back *in both directions*.

    * `wait()` reserves the next send slot and blocks (outside the lock) until
      it arrives, so the global request-start rate stays ~1/base_delay while
      different requests still overlap across worker threads.
    * `register_success()` records a good response; after enough consecutive
      successes it shaves the per-request delay back down toward the floor.
    * `register_rate_limit()` records server push-back; it multiplies the delay
      (up to a cap) and returns how long to cool down before retrying.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._next_slot = 0.0
        self.base_delay = REQUEST_DELAY
        self._cooldown = RATELIMIT_COOLDOWN
        self._successes = 0
        self._hits = 0

    def wait(self) -> None:
        """Reserve the next send slot, then sleep (outside the lock) until it."""
        with self._lock:
            now = time.monotonic()
            interval = self.base_delay + random.uniform(0, REQUEST_JITTER)
            # Chain slots so concurrent callers each get a distinct future slot.
            self._next_slot = max(now, self._next_slot) + interval
            target = self._next_slot
        delay = target - time.monotonic()
        if delay > 0:
            time.sleep(delay)

    def register_success(self) -> None:
        """Record a successful response; speed up after sustained success."""
        with self._lock:
            self._successes += 1
            # Recovery: a clean streak relaxes the cooldown escalation and,
            # every SPEEDUP_AFTER successes, additively speeds the pace back up.
            if self._successes >= SPEEDUP_AFTER:
                self._successes = 0
                self._cooldown = RATELIMIT_COOLDOWN
                if self.base_delay > MIN_REQUEST_DELAY:
                    self.base_delay = max(
                        MIN_REQUEST_DELAY, self.base_delay - SPEEDUP_STEP
                    )
                    logger.debug(
                        "Sustained success — per-request delay eased to %.2fs.",
                        self.base_delay,
                    )

    def register_rate_limit(self, retry_after: float | None) -> float:
        """Record a rate-limit hit and return how long to sleep before retrying."""
        with self._lock:
            self._hits += 1
            self._successes = 0
            # Multiplicative decrease: back off the pace (bounded by the cap).
            self.base_delay = min(self.base_delay * SLOWDOWN_FACTOR, MAX_REQUEST_DELAY)

            if retry_after is not None and RESPECT_RETRY_AFTER:
                cooldown = min(max(retry_after, 1.0), MAX_COOLDOWN)
            else:
                cooldown = min(self._cooldown, MAX_COOLDOWN)
                self._cooldown = min(self._cooldown * 2, MAX_COOLDOWN)
            logger.warning(
                "Rate limited (hit #%d). Cooling down %.0fs; per-request delay now %.2fs.",
                self._hits,
                cooldown,
                self.base_delay,
            )
            return cooldown


_throttle = _Throttle()


def _parse_retry_after(value: str | None) -> float | None:
    """Parse a Retry-After header (delta-seconds or HTTP-date) into seconds."""
    if not value:
        return None
    value = value.strip()
    # Delta-seconds form, e.g. "120"
    try:
        return float(value)
    except (ValueError, AttributeError):
        pass
    # HTTP-date form, e.g. "Wed, 21 Oct 2025 07:28:00 GMT"
    try:
        dt = email.utils.parsedate_to_datetime(value)
        if dt is not None:
            delta = dt.timestamp() - time.time()
            return delta if delta > 0 else None
    except (TypeError, ValueError):
        pass
    return None


# ---------------------------------------------------------------------------
# HTTP client
# ---------------------------------------------------------------------------


def _headers() -> dict[str, str]:
    return {
        "User-Agent": random.choice(USER_AGENTS),
        "Accept": (
            "text/html,application/xhtml+xml,application/xml;q=0.9,application/pdf;q=0.9,*/*;q=0.8"
        ),
        "Accept-Language": "nl-NL,nl;q=0.9,en;q=0.8",
    }


def get_client() -> httpx.Client:
    """Return a configured httpx session with sensible, polite defaults.

    Connection pooling is sized for the worker pool so concurrent requests
    reuse keep-alive connections instead of opening a fresh socket each time.
    """
    limits = httpx.Limits(max_connections=20, max_keepalive_connections=20)
    return httpx.Client(
        headers=_headers(), follow_redirects=True, timeout=30, limits=limits
    )


def polite_get(client: httpx.Client, url: str, **kwargs) -> httpx.Response | None:
    """
    Throttled GET that transparently handles rate-limit / overload responses.

    Returns the response on success, or None if it keeps being rate limited
    or fails. Cooldowns (Retry-After or adaptive backoff) are handled here so
    every caller benefits, and success feeds the throttle's speed recovery.
    """
    for attempt in range(MAX_RETRIES + 1):
        _throttle.wait()
        try:
            response = client.get(url, **kwargs)
        except Exception:
            logger.exception("Request error for %s", url)
            return None

        if response.status_code in RETRY_STATUS_CODES:
            retry_after = _parse_retry_after(response.headers.get("Retry-After"))
            if attempt == MAX_RETRIES:
                logger.error("Still rate limited after %d retries: %s", MAX_RETRIES, url)
                return None
            time.sleep(_throttle.register_rate_limit(retry_after))
            continue

        _throttle.register_success()
        return response

    return None


def polite_head(client: httpx.Client, url: str, **kwargs) -> httpx.Response | None:
    """Throttled HEAD request that also respects rate-limit push-back."""
    _throttle.wait()
    try:
        response = client.head(url, **kwargs)
    except Exception:
        return None

    if response.status_code in RETRY_STATUS_CODES:
        # Don't retry HEADs (they're best-effort probes), but do let the
        # throttle back off so following GETs slow down too.
        retry_after = _parse_retry_after(response.headers.get("Retry-After"))
        _throttle.register_rate_limit(retry_after)
        return None

    _throttle.register_success()
    return response


def fetch_soup(client: httpx.Client, url: str) -> BeautifulSoup | None:
    """Fetch *url* (throttled, rate-limit aware) and return a parsed soup."""
    response = polite_get(client, url)
    if response is None:
        return None
    try:
        response.raise_for_status()
        return BeautifulSoup(response.text, "lxml")
    except Exception:
        logger.exception("Failed to fetch %s", url)
        return None


# ---------------------------------------------------------------------------
# URL construction
# ---------------------------------------------------------------------------


def build_list_url(
    page: int,
    category: str = "NZA000",
    valid_date: str | None = None,  # DD-MM-YYYY as returned by the site
) -> str:
    """
    Construct a paginated document-list URL.

    URL structure discovered from the live site:
      /nza/zorgsectoren/pagina/{category}/-/gdlv/0/gd/{date}/p/{page}/
      /nza/zorgsectoren/pagina/{category}/-/p/{page}/   (no date filter)

    NZA000 is the code for 'all categories'.
    """
    base = f"{BASE_URL}zorgsectoren/pagina/{category}/-/"
    if valid_date:
        base += f"gdlv/0/gd/{valid_date}/"
    base += f"p/{page}/"
    return base


# ---------------------------------------------------------------------------
# List-page parsing
# ---------------------------------------------------------------------------


def extract_doc_links(soup: BeautifulSoup) -> list[str]:
    """Return all document URLs found on a list page."""
    links = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "doc/PUC_" not in href:
            continue
        if not href.startswith("http"):
            href = "https://puc.overheid.nl" + href
        links.append(href)
    return links


def fetch_category_options(client: httpx.Client) -> list[tuple[str, str]]:
    """
    Return (name, code) pairs for all selectable document categories.
    Category codes are extracted from the filter links on the main NZa page.

    Example: [("Jeugdzorg", "NZA012"), ("GGZ", "NZA005"), …]
    """
    soup = fetch_soup(client, BASE_URL)
    if not soup:
        return []

    seen: set[str] = set()
    categories: list[tuple[str, str]] = []

    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "/zorgsectoren/pagina/" not in href:
            continue
        parts = [p for p in href.strip("/").split("/") if p]
        try:
            idx = parts.index("pagina")
            code = parts[idx + 1]
        except (ValueError, IndexError):
            continue

        # Strip trailing document-count digits that the site appends inside
        # the link text (e.g. "Acute zorg50" → "Acute zorg")
        raw_name = a.get_text(strip=True)
        name = re.sub(r"\d+$", "", raw_name).strip()

        if not name or not code or code in seen or code == "NZA000":
            continue
        seen.add(code)
        categories.append((name, code))

    logger.info("Found %d category options.", len(categories))
    return categories


# ---------------------------------------------------------------------------
# Document-page parsing
# ---------------------------------------------------------------------------


def extract_metadata(soup: BeautifulSoup) -> dict:
    """Extract title, doc_date, and doc_type from a document page."""
    meta: dict = {"title": None, "doc_date": None, "doc_type": None}

    h1 = soup.find("h1")
    if h1:
        meta["title"] = h1.get_text(strip=True) or None

    time_el = soup.find("time")
    if time_el:
        meta["doc_date"] = time_el.get("datetime") or time_el.get_text(strip=True) or None

    for dt in soup.find_all("dt"):
        label = dt.get_text(strip=True).lower()
        if "soort" in label or "type" in label:
            dd = dt.find_next_sibling("dd")
            if dd:
                meta["doc_type"] = dd.get_text(strip=True) or None
            break

    return meta


def extract_pdf_url(soup: BeautifulSoup) -> str | None:
    """
    Return the direct URL of a PDF embedded in or linked from a document page.

    Some PUC documents (e.g. all Jeugdzorg pages) are inherently PDFs — the
    page offers only a download link rather than an HTML article body.  We try
    three passes to find the URL so we can download via httpx, avoiding Selenium.

    Pass 1 — <a href="…"> links:
      • href ends in .pdf
      • link text contains "PDF Openen" or similar

    Pass 2 — data-* attributes:
      • JS buttons sometimes store the real URL in a data-href / data-url / …
        attribute even though the visible href is '#'

    Pass 3 — inline <script> tags:
      • PDF URL referenced as a JS string literal
    """
    _BASE = "https://puc.overheid.nl"

    def _make_absolute(href: str) -> str | None:
        if href.startswith("/"):
            return _BASE + href
        if href.startswith("http"):
            return href
        return None

    # Pass 1 — navigable <a> elements
    for a in soup.find_all("a", href=True):
        href: str = a["href"]
        if not href or href.startswith("#") or href.lower().startswith("javascript"):
            continue
        text = a.get_text(strip=True).lower()
        if (
            href.lower().endswith(".pdf")
            or "pdf openen" in text
            or ("pdf" in text and "download" in text)
        ):
            result = _make_absolute(href)
            if result:
                return result

    # Pass 2a — <object data="…"> and <embed src="…"> (inline PDF viewers)
    for tag in soup.find_all(["object", "embed"]):
        val = tag.get("data") or tag.get("src") or ""
        if "pdf" in val.lower():
            result = _make_absolute(val)
            if result:
                return result

    # Pass 2b — data-* attributes on any element
    for el in soup.find_all(True):
        for attr, val in el.attrs.items():
            if not isinstance(val, str) or not attr.startswith("data-"):
                continue
            if val.lower().endswith(".pdf") or "/pdf/" in val.lower():
                result = _make_absolute(val)
                if result:
                    return result

    # Pass 3 — PDF URL strings inside <script> tags
    _pdf_re = re.compile(r'["\']([^"\']*\.pdf[^"\']*)["\']')
    for script in soup.find_all("script"):
        src = script.get_text()
        if not src:
            continue
        for match in _pdf_re.findall(src):
            result = _make_absolute(match)
            if result:
                return result

    return None


def extract_article_text(soup: BeautifulSoup) -> str | None:
    """
    Return the article body as plain text.
    Returns None if no article is found or its text is below MIN_ARTICLE_LENGTH
    — the caller should then fall back to a PDF download.
    """
    article = soup.find("article")
    if not article:
        return None
    text = html_to_text(str(article))
    if len(text.strip()) < MIN_ARTICLE_LENGTH:
        return None
    return text
