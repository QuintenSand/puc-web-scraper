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
#   3. Selenium's built-in manager      — last resort (requires access to googlechromelabs.github.io)

import os
from contextlib import contextmanager

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait

from .config import CHROME_DRIVER_PATH, DOWNLOAD_DIR, PAGE_LOAD_TIMEOUT


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


def _get_service() -> Service | None:
    """
    Return a configured Service, or None to let Selenium use its default.

    Tries webdriver-manager first (handles version matching and local caching).
    Falls back gracefully if it is not installed or fails.
    """
    # Manual override — highest priority
    if CHROME_DRIVER_PATH:
        return Service(executable_path=CHROME_DRIVER_PATH)

    # webdriver-manager — downloads and caches the right ChromeDriver version
    try:
        from webdriver_manager.chrome import ChromeDriverManager
        return Service(ChromeDriverManager().install())
    except Exception:
        # Not installed or download failed — fall through to Selenium's own manager
        return None


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
    driver = webdriver.Chrome(service=service, options=opts) if service else webdriver.Chrome(options=opts)
    wait = WebDriverWait(driver, PAGE_LOAD_TIMEOUT)
    try:
        yield driver, wait
    finally:
        driver.quit()
