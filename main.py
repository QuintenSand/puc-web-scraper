# Main script to web scrape PUC
# https://puc.overheid.nl/nza/

import os
import time
import random
import logging
import html2text
import duckdb
import fitz
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

# Browser setup
chrome_options = Options()
prefs = {
    "download.default_directory": DOWNLOAD_DIR,
    "plugins.always_open_pdf_externally": True,
    "download.prompt_for_download": False,
}

chrome_options.add_experimental_option("prefs", prefs)
driver = webdriver.Chrome(options=chrome_options)
wait = WebDriverWait(driver, 10)

# --- 1. DUCKDB SETUP ---
con = duckdb.connect("puc_data.db")
con.execute("""
    CREATE TABLE IF NOT EXISTS documents (
        puc_id VARCHAR PRIMARY KEY,
        url VARCHAR,
        content_md TEXT,
        source_type VARCHAR,
        scraped_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
""")

# --- 2. HTML TO MARKDOWN SETUP ---
h = html2text.HTML2Text()
h.ignore_links = False
h.ignore_images = True
h.body_width = 0  # No line wrapping

# --- HELPER FUNCTIONS ---
def was_downloaded(url):
    if not os.path.exists(LOG_FILE):
        return False
    with open(LOG_FILE, "r") as f:
        return url in f.read()

def mark_done(url):
    with open(LOG_FILE, "a") as f:
        f.write(url + "\n")

def scrape_to_markdown(url):
    # Check if we already have this in DuckDB
    exists = con.execute("SELECT 1 FROM documents WHERE url = ?", [url]).fetchone()
    if exists:
        return False

    driver.get(url)
    try:
        # Find the main text body. PUC usually puts text in a specific div.
        # If 'article' doesn't work, we use a broader div.
        wait.until(EC.presence_of_element_located((By.TAG_NAME, "article")))
        content_element = driver.find_element(By.TAG_NAME, "article")
        
        html_content = content_element.get_attribute('innerHTML')
        markdown_text = h.handle(html_content)
        
        # Extract PUC ID from URL (e.g., PUC_813946_22)
        puc_id = url.split('/')[-3] if 'doc/' in url else url.split('/')[-2]

        # Save to DuckDB
        con.execute("""
        INSERT OR REPLACE INTO documents (puc_id, url, content_md, source_type)
        VALUES (?, ?, ?, ?)
        """, [puc_id, url, markdown_text, "html"])
        
        return True
    except Exception as e:
        logger.error(f"Failed to extract text from {url}: {e}")
        return False

def extract_pdf_to_md(pdf_path):
    """
    Fast extraction using PyMuPDF. 
    It extracts text blocks and attempts to maintain basic formatting.
    """
    try:
        doc = fitz.open(pdf_path)
        full_text = ""
        for page in doc:
            # "blocks" helps maintain some layout integrity
            blocks = page.get_text("blocks")
            for b in blocks:
                # b[4] is the text content of the block
                full_text += b[4] + "\n"
        return full_text
    except Exception as e:
        logging.error(f"PyMuPDF failed on {pdf_path}: {e}")
        return ""

def save_to_db(puc_id, url, text, source):
    con.execute("""
        INSERT OR REPLACE INTO documents (puc_id, url, content_md, source_type)
        VALUES (?, ?, ?, ?)
    """, [puc_id, url, text, source])

def wait_for_pdf(timeout=30):
    start_time = time.time()
    while time.time() - start_time < timeout:
        files = [f for f in os.listdir(DOWNLOAD_DIR) if f.endswith('.pdf') and not f.endswith('.crdownload')]
        if files:
            full_path = os.path.join(DOWNLOAD_DIR, files[0])
            return full_path
        time.sleep(1)
    return None

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
#jeugdzorg_btn = WebDriverWait(driver, 10).until(
#    EC.element_to_be_clickable(
#        (
#            By.XPATH,
#            "//a[contains(normalize-space(), 'Jeugdzorg')] | //label[contains(normalize-space(), 'Jeugdzorg')]",
#        )
#    )
#)

# Klik op de knop
#jeugdzorg_btn.click()

# Go through all pages
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
        next_xpath = "//a[contains(., 'Volgende')]"
        next_btn = driver.find_element(By.XPATH, next_xpath)

        # Scroll and click
        driver.execute_script("arguments[0].scrollIntoView();", next_btn)
        next_btn.click()
        time.sleep(3)  # Wait for Ajax

    except:
        logging.exception(f"{link} failed because there is no Volgende button")
        break

    logger.info(f"Reached end of list. Total URLs: {len(all_doc_urls)}")
    print("Reached the end of the list.")

print(f"Total URLs collected: {len(all_doc_urls)}")

# --- Phase 2: Processing documents --- #
logger.info("Phase 2: Processing Documents")
# Iterate through all urls and download pdfs
unique_doc_urls = list(set(all_doc_urls))
for url in unique_doc_urls:
    puc_id = url.split('/')[-3] if 'doc/' in url else url.split('/')[-2]
        
    # Check DuckDB if already exists
    if con.execute("SELECT 1 FROM documents WHERE puc_id = ?", [puc_id]).fetchone():
        continue

    driver.get(url)
    time.sleep(3)
        
    try:
        # Option A: Try HTML Article
        article = driver.find_elements(By.TAG_NAME, "article")
        if article and len(article[0].text.strip()) > 300:
            md = h.handle(article[0].get_attribute('innerHTML'))
            save_to_db(puc_id, url, md, "HTML")
            logger.info(f"Saved HTML: {puc_id}")
            
        # Option B: Download PDF and rip text
        else:
            btn_xpath = "//a[contains(., 'Maak een PDF')] | //a[contains(., 'PDF Openen')]"
            wait.until(EC.element_to_be_clickable((By.XPATH, btn_xpath))).click()
                
            # Check for secondary button if site requires it
            try:
                finish_btn = WebDriverWait(driver, 5).until(EC.element_to_be_clickable((By.XPATH, "//a[contains(., 'Klaar!')]")))
                finish_btn.click()
            except: 
                pass

            pdf_path = wait_for_pdf()
            if pdf_path:
                pdf_text = extract_pdf_to_md(pdf_path)
                save_to_db(puc_id, url, pdf_text, "PDF")
                os.remove(pdf_path) # Clean up
                logger.info(f"Saved PDF-to-Text: {puc_id}")

    except Exception as e:
        logger.error(f"Error on {url}: {e}")

# Finish proces and logging.
logger.info("Scraping process finished.")
driver.quit()

results = con.execute("""
    SELECT *
    FROM documents 
""").fetchall()

print(results)