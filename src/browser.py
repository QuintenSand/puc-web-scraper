# src/browser.py
# Selenium browser factory.
# Use as a context manager so the driver is always closed, even on error:
#
#   with get_driver() as (driver, wait):
#       driver.get("https://...")
#
# ChromeDriver resolution order:
#   1. CHROME_DRIVER_PATH in config.py  — use this on offline / firewalled machines
#   2. webdriver-manager                — downloads & caches the correct driver version
#   3. Clear error with instructions    — if both above fail

import os
from contextlib import contextmanager

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait

from .config import CHROME_DRIVER_PATH, DOWNLOAD_DIR, PAGE_LOAD_TIMEOUT

_MANUAL_SETUP_GUIDE = """
ChromeDriver could not be located automatically.
This usually means the machine cannot reach the ChromeDriver download servers
(e.g. due to a firewall or proxy).

To fix this, do the following steps:

  1. Check your Chrome version:
     Open Chrome → go to chrome://version → note the version number (e.g. 136.0.7103.93)

  2. Download the matching ChromeDriver for Windows:
     https://googlechromelabs.github.io/chrome-for-testing/
     Pick the version that matches your Chrome, download 'chromedriver-win64.zip',
     and extract chromedriver.exe to a folder (e.g. C:\\tools\\chromedriver.exe).

  3. Set CHROME_DRIVER_PATH in src/config.py:
     CHROME_DRIVER_PATH = r"C:\\tools\\chromedriver.exe"

Then run the script again.
"""


def _build_options(download_dir: str) -> Options:
    opts = Options()
    opts.add_argument("--disable-notifications")
    opts.add_argument("--disable-infobars")
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

    Tries webdriver-manager first (handles version matching and local caching).
    If that fails, raises a clear error with manual setup instructions.
    """
    # Manual path — highest priority, always works offline
    if CHROME_DRIVER_PATH:
        return Service(executable_path=CHROME_DRIVER_PATH)

    # webdriver-manager — downloads and caches the right ChromeDriver version
    try:
        from webdriver_manager.chrome import ChromeDriverManager
        return Service(ChromeDriverManager().install())
    except Exception as e:
        raise RuntimeError(_MANUAL_SETUP_GUIDE) from e


@contextmanager
def get_driver(headless: bool = False):
    """
    Yield a configured (driver, wait) tuple and guarantee driver.quit() on exit.

    Example
    -------
    with get_driver() as (driver, wait):
        driver.get("https://example.com")
    """
    os.makedirs(DOWNLOAD_DIR, exist_ok=True)
    opts = _build_options(DOWNLOAD_DIR)
    if headless:
        opts.add_argument("--headless=new")

    service = _get_service()
    driver = webdriver.Chrome(service=service, options=opts)
    wait = WebDriverWait(driver, PAGE_LOAD_TIMEOUT)
    try:
        yield driver, wait
    finally:
        driver.quit()
