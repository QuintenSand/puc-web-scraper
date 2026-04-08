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
PAGE_LOAD_TIMEOUT = 10        # seconds for WebDriverWait
PDF_DOWNLOAD_TIMEOUT = 30     # seconds to wait for a PDF to appear
INTER_PAGE_DELAY = 3          # seconds between pagination clicks
MIN_ARTICLE_LENGTH = 300      # characters; below this we fall back to PDF

# --- ChromeDriver ---
# Leave as None to let webdriver-manager find/download the driver automatically.
# Set to an absolute path if you are on a network that blocks the download,
# e.g. CHROME_DRIVER_PATH = r"C:\tools\chromedriver.exe"
CHROME_DRIVER_PATH: str | None = None

# --- Retry ---
MAX_RETRIES = 3
RETRY_BACKOFF = 2.0           # seconds; doubles on each retry
