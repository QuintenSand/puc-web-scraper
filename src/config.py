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

# --- Politeness / rate limiting -------------------------------------------
# These settings keep the scraper under the server's radar so the source
# site does not block our IP for requesting too many documents too quickly.
#
# Every outbound request goes through a shared adaptive throttle (see
# src/fetcher.py). The throttle waits REQUEST_DELAY seconds (plus a random
# jitter) between requests. If the server signals overload (HTTP 429/503),
# the throttle automatically slows down and stays slow for the rest of the
# run, then gently speeds back up after sustained success.

# Base seconds to wait between *every* HTTP request. Raise this if you still
# get blocked; lower it (carefully) if runs are too slow and you trust the site.
REQUEST_DELAY = 2.0
# Extra random seconds (0..REQUEST_JITTER) added to each wait. Randomising the
# cadence avoids the perfectly-regular request pattern that flags bots.
REQUEST_JITTER = 1.5

# HTTP status codes that mean "you are being rate limited / server is busy".
# Seeing one of these triggers a cooldown instead of an immediate retry.
RETRY_STATUS_CODES = frozenset({429, 500, 502, 503, 504})
# Honour the server's `Retry-After` header when present.
RESPECT_RETRY_AFTER = True
# Base cooldown (seconds) applied the first time we are rate limited and no
# Retry-After header is given. Doubles on repeated hits, capped at MAX_COOLDOWN.
RATELIMIT_COOLDOWN = 60.0
MAX_COOLDOWN = 900.0  # never wait longer than 15 minutes
# After a rate-limit hit, the per-request delay is multiplied by this factor
# (persisted for the rest of the run) so we approach the site more gently.
SLOWDOWN_FACTOR = 1.5
# Hard ceiling for the adaptive per-request delay.
MAX_REQUEST_DELAY = 30.0

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
