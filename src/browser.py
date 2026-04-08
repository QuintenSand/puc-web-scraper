# src/browser.py
# Selenium browser factory.
# Use as a context manager so the driver is always closed, even on error:
#
#   with get_driver() as driver:
#       driver.get("https://...")

import os
from contextlib import contextmanager

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait

from .config import DOWNLOAD_DIR, PAGE_LOAD_TIMEOUT


def _build_options(download_dir: str) -> Options:
    opts = Options()
    # Suppress Chrome UI noise
    opts.add_argument("--disable-notifications")
    opts.add_argument("--disable-infobars")
    prefs = {
        "download.default_directory": download_dir,
        # Force PDFs to download instead of opening in the browser viewer
        "plugins.always_open_pdf_externally": True,
        "download.prompt_for_download": False,
        "download.directory_upgrade": True,
    }
    opts.add_experimental_option("prefs", prefs)
    return opts


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

    driver = webdriver.Chrome(options=opts)
    wait = WebDriverWait(driver, PAGE_LOAD_TIMEOUT)
    try:
        yield driver, wait
    finally:
        driver.quit()
