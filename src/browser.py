# src/browser.py
# Chrome browser — only used for pages that require a PDF download.
# For HTML document pages and URL collection, see src/fetcher.py.
#
# Use LazyBrowser so Chrome is only started if the current run actually
# encounters a document that needs a PDF:
#
#   browser = LazyBrowser()
#   try:
#       driver, wait = browser.get()   # starts Chrome on first call
#       driver.get("https://...")
#   finally:
#       browser.close()
#
# ChromeDriver resolution order:
#   1. CHROME_DRIVER_PATH in config.py  — set this on firewalled machines
#   2. chromedriver already on system PATH
#   3. webdriver-manager               — downloads & caches the right version
#   4. RuntimeError with setup guide   — if all above fail

import logging
import os
import platform
import shutil
from contextlib import contextmanager

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait

from .config import CHROME_DRIVER_PATH, DOWNLOAD_DIR, PAGE_LOAD_TIMEOUT

logger = logging.getLogger(__name__)

_MANUAL_SETUP_GUIDE = """
ChromeDriver could not be located automatically.
This usually means the machine cannot reach the ChromeDriver download servers
(e.g. due to a firewall or proxy).

To fix this, follow these steps:

  1. Check your Chrome version:
     Open Chrome → go to chrome://version → note the version number (e.g. 136.0.7103.93)

  2. Download the matching ChromeDriver for Windows:
     https://googlechromelabs.github.io/chrome-for-testing/
     Pick the version that matches your Chrome, download 'chromedriver-win64.zip',
     and extract chromedriver.exe somewhere (e.g. C:\\tools\\chromedriver.exe).

  3. Set CHROME_DRIVER_PATH in src/config.py:
     CHROME_DRIVER_PATH = r"C:\\tools\\chromedriver.exe"

Then run the script again.
"""


_CHROME_BINARIES = {
    "Darwin": [
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/Applications/Chromium.app/Contents/MacOS/Chromium",
    ],
    "Linux": [
        "/usr/bin/google-chrome",
        "/usr/bin/chromium-browser",
        "/usr/bin/chromium",
    ],
}


def _build_options(download_dir: str) -> Options:
    opts = Options()
    opts.add_argument("--disable-notifications")
    opts.add_argument("--disable-infobars")

    # Explicitly set the Chrome binary if it can't be found automatically.
    # This matters on macOS where the default PATH lookup often fails.
    system = platform.system()
    for binary in _CHROME_BINARIES.get(system, []):
        if os.path.exists(binary):
            opts.binary_location = binary
            break

    prefs = {
        "download.default_directory": download_dir,
        "plugins.always_open_pdf_externally": True,
        "download.prompt_for_download": False,
        "download.directory_upgrade": True,
    }
    opts.add_experimental_option("prefs", prefs)
    return opts


def _get_service() -> Service:
    """
    Return a configured ChromeDriver Service.
    Tries multiple resolution strategies before raising a clear error.
    """
    if CHROME_DRIVER_PATH:
        return Service(executable_path=CHROME_DRIVER_PATH)

    if shutil.which("chromedriver"):
        return Service()

    try:
        from webdriver_manager.chrome import ChromeDriverManager
        return Service(ChromeDriverManager().install())
    except Exception as e:
        raise RuntimeError(_MANUAL_SETUP_GUIDE) from e


# ---------------------------------------------------------------------------
# LazyBrowser — starts Chrome only when first needed
# ---------------------------------------------------------------------------

class LazyBrowser:
    """
    Wraps a Chrome WebDriver that is only started on the first call to .get().
    This means runs where every document is HTML never open Chrome at all.
    """

    def __init__(self) -> None:
        self._driver: webdriver.Chrome | None = None
        self._wait: WebDriverWait | None = None

    @property
    def started(self) -> bool:
        return self._driver is not None

    def get(self) -> tuple[webdriver.Chrome, WebDriverWait]:
        """Return (driver, wait), starting Chrome if this is the first call."""
        if self._driver is None:
            logger.info("Starting Chrome for PDF downloads…")
            os.makedirs(DOWNLOAD_DIR, exist_ok=True)
            opts = _build_options(DOWNLOAD_DIR)
            service = _get_service()
            self._driver = webdriver.Chrome(service=service, options=opts)
            self._wait = WebDriverWait(self._driver, PAGE_LOAD_TIMEOUT)
        return self._driver, self._wait

    def close(self) -> None:
        """Quit Chrome if it was started."""
        if self._driver is not None:
            self._driver.quit()
            self._driver = None
            self._wait = None
