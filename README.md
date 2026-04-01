# PUC-Web-scraper

A robust, two-phase Selenium-based scraper designed to navigate the PUC Overheid (NZA) portal, apply filters, and automatically generate and download PDF documents.

## 🚀 Features
- Two-Phase Execution: Crawls all search results first to ensure session stability, then downloads files sequentially.
- State Management: Uses a download_history.txt log to skip previously downloaded files, allowing for easy resumes after interruptions.
- Intelligent Selectors: Handles multiple button states ("Maak een PDF", "PDF Openen", "Klaar!") using robust XPath logic.
- Detailed Logging: Professional logging to both console and puc_scraper.log with timestamps and error tracking.
- Auto-Configuration: Automatically sets up Chrome preferences to bypass PDF viewers and "Save As" prompts.

## 🛠️ Installation

**Prerequisites**

- Python 3.11+
- Google Chrome installed.
- Chrome Driver: Handled automatically by modern Selenium, or ensure your chromedriver matches your Chrome version.

**Setup**

1. Clone the repository:

```
git clone https://github.com/QuintenSand/puc-web-scraper.git
```

2. Install dependencies:

```
python -m uv sync
```

## 📖 Usage
Simply run the main script. The scraper will default to the NZA portal, select the "Alle" and "Geldig vandaag" filters, and begin processing.

```
python -m uv run main.py
```

**Configuration**

You can modify the following variables in main.py:

- DOWNLOAD_DIR: Change where the files are saved.
- wait = WebDriverWait(driver, 15): Increase if the website/internet is slow.
- time.sleep(2): Adjust the delay between downloads to be more or less aggressive.
