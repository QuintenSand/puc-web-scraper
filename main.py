# Main script to web scrape PUC
# https://puc.overheid.nl/nza/

import os
import time
import random
import logging
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# --- Configuration ---
# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler("scraper_debug.log"),  # Saves everything to a file
        logging.StreamHandler(),  # Also prints to your console
    ],
)
logger = logging.getLogger(__name__)
LOG_FILE = "download_history.txt"

# Add download map
DOWNLOAD_DIR = os.path.join(os.getcwd(), "downloads")
if not os.path.exists(DOWNLOAD_DIR):
    os.makedirs(DOWNLOAD_DIR)

chrome_options = Options()
prefs = {
    "download.default_directory": DOWNLOAD_DIR,
    "plugins.always_open_pdf_externally": True,
    "download.prompt_for_download": False,
}

# Browser setup
chrome_options.add_experimental_option("prefs", prefs)
driver = webdriver.Chrome(options=chrome_options)
wait = WebDriverWait(driver, 10)


# --- HELPER FUNCTIONS ---
def was_downloaded(url):
    if not os.path.exists(LOG_FILE):
        return False
    with open(LOG_FILE, "r") as f:
        return url in f.read()


def mark_done(url):
    with open(LOG_FILE, "a") as f:
        f.write(url + "\n")


# --- Phase 1: Collecting all urls ---
logger.info("Start Phase 1: collecting urls")
all_doc_urls = []

# 1. Start at the main list
driver.get("https://puc.overheid.nl/nza/")
alle_btn = wait.until(
    EC.element_to_be_clickable((By.XPATH, "//a[contains(., 'Alle')]"))
)
alle_btn.click()

# Click on geldig vandaag button
# Wacht tot de knop klikbaar is
geldig_vandaag_btn = driver.find_element(
    By.XPATH, "//label[contains(., 'Geldig vandaag')]"
)

# Klik op de knop
geldig_vandaag_btn.click()

# Voor de test doen we alleen Jeugdzorg
# Wacht tot de knop klikbaar is
jeugdzorg_btn = WebDriverWait(driver, 10).until(
    EC.element_to_be_clickable(
        (
            By.XPATH,
            "//a[contains(normalize-space(), 'Jeugdzorg')] | //label[contains(normalize-space(), 'Jeugdzorg')]",
        )
    )
)

# Klik op de knop
jeugdzorg_btn.click()

logger.info("All buttons applied now start getting all urls")
while True:
    print(f"Crawling page: {driver.current_url}")
    wait.until(
        EC.presence_of_all_elements_located(
            (By.XPATH, "//a[contains(@href, 'doc/PUC_')]")
        )
    )

    # Extract links from the current page
    links = driver.find_elements(By.XPATH, "//a[contains(@href, 'doc/PUC_')]")
    print(f"Found: {len(links)} urls")
    for link in links:
        all_doc_urls.append(link.get_attribute("href"))

    # Try to go to the next page
    try:
        next_xpath = "//a[contains(@class, 'volgende')] | //a[contains(., 'Volgende')]"
        next_btn = driver.find_element(By.XPATH, next_xpath)

        # Scroll and click
        driver.execute_script("arguments[0].scrollIntoView();", next_btn)
        next_btn.click()
        time.sleep(3)  # Wait for Ajax

    except:
        logging.exception(f"{link} failed")
        break

    logger.info(f"Reached end of list. Total URLs: {len(all_doc_urls)}")
    print("Reached the end of the list.")

print(f"Total URLs collected: {len(all_doc_urls)}")

# --- Phase 2: Downloading pdf files --- #
logger.info("Phase 2: Downloading PDFs")
# Iterate through all urls and download pdfs
unique_doc_urls = list(set(all_doc_urls))
for url in unique_doc_urls:
    if was_downloaded(url):
        logger.info(f"Skipping {url} (Already in history)")
        continue
    driver.get(url)
    print(f"Start with url: {url}")

    try:
        # Click "Maak een PDF"
        pdf_btn = wait.until(
            EC.element_to_be_clickable(
                (
                    By.XPATH,
                    "//a[contains(., 'Maak een PDF')] | //a[contains(., 'PDF Openen')]",
                )
            )
        )
        pdf_btn.click()

        # Wait for the generation to finish and the download link to appear (Klaar! or Openen)
        download_link = wait.until(
            EC.element_to_be_clickable(
                (
                    By.XPATH,
                    "//a[contains(., 'Klaar!')] | //a[contains(., 'Openen')] | //button[contains(., 'Klaar!')]",
                )
            )
        )
        download_link.click()
        print(f"Downloaded: {url.split('/')[-2]}")

        # Small pause for the download to register
        mark_done(url)
        logger.info(f"Successfully downloaded: {url}")
        time.sleep(random.uniform(3.0, 6.0))

    except Exception as e:
        logger.error(f"Failed to process {url}: {str(e)}")
        print(f"Failed to download {url}: {e}")


# Finish proces and logging.
logger.info("Scraping process finished.")
driver.quit()
