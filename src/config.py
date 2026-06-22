# src/config.py
# Central configuration for the PUC scraper.

import os

# --- Paths ---
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOWNLOAD_DIR = os.path.join(BASE_DIR, "downloads")
DB_PATH = os.path.join(BASE_DIR, "puc_data.db")
LOG_FILE = os.path.join(BASE_DIR, "scraper_debug.log")

# --- Scraping ---
BASE_URL = "https://puc.overheid.nl/nza/"
PAGE_LOAD_TIMEOUT = 10  # seconds for WebDriverWait
PDF_DOWNLOAD_TIMEOUT = 30  # seconds to wait for a PDF to appear
INTER_PAGE_DELAY = 3  # seconds between pagination clicks
MIN_ARTICLE_LENGTH = 300  # characters; below this we fall back to PDF

# Number of documents processed in parallel in Phase 2. Workers share the
# adaptive throttle below. Because the throttle only holds its lock while
# *spacing* requests (not while a request is in flight), extra workers let
# network/parse time of different documents overlap — so raising this DOES
# improve throughput up to the throttle's req/sec ceiling. 8 is a good balance.
MAX_WORKERS = 8

# --- Politeness / rate limiting (AIMD self-healing) -----------------------
# Every outbound request goes through a single shared adaptive throttle (see
# src/fetcher.py). It uses an AIMD ("additive-increase / multiplicative-
# decrease") strategy, the same idea TCP uses for congestion control:
#
#   * Steady state: it spaces requests REQUEST_DELAY (+ jitter) seconds apart.
#   * Server pushes back (HTTP 429/503/…): it MULTIPLIES the delay by
#     SLOWDOWN_FACTOR (up to MAX_REQUEST_DELAY) and cools down briefly,
#     honouring the server's Retry-After header when present.
#   * Sustained success: after SPEEDUP_AFTER consecutive good responses it
#     ADDITIVELY shaves SPEEDUP_STEP off the delay (down to MIN_REQUEST_DELAY),
#     so the scraper continuously feels out the fastest pace the server
#     tolerates and RECOVERS automatically instead of staying crippled.
#
# This is the key fix over the old throttle, which could only ever get slower:
# a few rate-limit hits used to pin it at 30s/request with 15-minute cooldowns
# for the rest of the run.

# Starting / steady-state seconds between request *starts* (global cap on rate
# ≈ 1 / REQUEST_DELAY req/sec). AIMD adjusts it within
# [MIN_REQUEST_DELAY, MAX_REQUEST_DELAY] at runtime.
REQUEST_DELAY = 0.4
# Fastest the throttle is ever allowed to go (the speed floor).
MIN_REQUEST_DELAY = 0.25
# Extra random seconds (0..REQUEST_JITTER) added to each wait to avoid a
# perfectly-regular, bot-like cadence.
REQUEST_JITTER = 0.2

# Speed recovery: after this many consecutive successful requests, shave
# SPEEDUP_STEP seconds off the per-request delay (down to MIN_REQUEST_DELAY).
SPEEDUP_AFTER = 12
SPEEDUP_STEP = 0.1

# HTTP status codes that mean "you are being rate limited / server is busy".
RETRY_STATUS_CODES = frozenset({429, 500, 502, 503, 504})
# Honour the server's `Retry-After` header when present.
RESPECT_RETRY_AFTER = True
# Base cooldown (seconds) the first time we are rate limited with no
# Retry-After header. Doubles on repeated *consecutive* hits, capped at
# MAX_COOLDOWN, and resets once the scraper recovers.
RATELIMIT_COOLDOWN = 20.0
MAX_COOLDOWN = 120.0  # never self-impose more than 2 minutes (was 15 min)
# On a rate-limit hit the per-request delay is multiplied by this factor.
SLOWDOWN_FACTOR = 1.5
# Hard ceiling for the adaptive per-request delay (was 30s — caused the
# death-spiral). Kept low because the throttle now recovers on its own.
MAX_REQUEST_DELAY = 8.0

# User-Agent strings rotated per client to avoid a single static fingerprint.
USER_AGENTS = [
    (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0.0.0 Safari/537.36"
    ),
    (
        "Mozilla/5.0 (X11; Linux x86_64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    ("Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0"),
]

# --- ChromeDriver ---
# Leave as None to let webdriver-manager find/download the driver automatically.
# Set to an absolute path if you are on a network that blocks the download,
# e.g. CHROME_DRIVER_PATH = r"C:\tools\chromedriver.exe"
CHROME_DRIVER_PATH: str | None = None

# --- Retry ---
MAX_RETRIES = 3
RETRY_BACKOFF = 2.0  # seconds; doubles on each retry
