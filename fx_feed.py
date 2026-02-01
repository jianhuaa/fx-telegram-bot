import os
import json
import time
import requests
from datetime import datetime, timedelta, timezone
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from webdriver_manager.chrome import ChromeDriverManager
from selenium_stealth import stealth

# ===== CONFIG =====
TELEGRAM_TOKEN = "7649050168:AAHNIYnrHzLOTcjNuMpeKgyUbfJB9x9an3c"
CHAT_ID = "876384974"
SGT = timezone(timedelta(hours=8))
now = datetime.now(SGT)

# Mapping the Website Names to your preferred G8 Labels
G8_MAP = {
    "Federal Reserve": "Fed",
    "European Central Bank": "ECB",
    "Bank of England": "BoE",
    "Bank of Japan": "BoJ",
    "Bank of Canada": "BoC",
    "Reserve Bank of Australia": "RBA",
    "Reserve Bank of New Zealand": "RBNZ",
    "Swiss National Bank": "SNB"
}

# ===== STEALTH SCRAPER =====
def scrape_g8_rates():
    chrome_options = Options()
    chrome_options.add_argument("--headless")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--window-size=1920,1080")
    chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

    try:
        driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=chrome_options)
        stealth(driver, languages=["en-US", "en"], vendor="Google Inc.", platform="Win32", fix_hairline=True)

        driver.get("https://www.investing.com/central-banks/world-central-banks")
        time.sleep(10) 
        
        g8_rates = {}
        table = driver.find_element(By.ID, "curr_table")
        rows = table.find_elements(By.TAG_NAME, "tr")[1:]
        
        for row in rows:
            cells = row.find_elements(By.TAG_NAME, "td")
            if len(cells) >= 3:
                full_name = cells[1].text.split('(')[0].strip() # Extract "Federal Reserve" from "Federal Reserve (FED)"
                rate = cells[2].text.strip()
                
                # Check if this bank is in our G8 list
                if full_name in G8_MAP:
                    label = G8_MAP[full_name]
                    g8_rates[label] = rate
        
        driver.quit()
        return g8_rates

    except Exception as e:
        print(f"Scrape Error: {e}")
        return None

# ===== BUILD MESSAGE =====
central_bank_rates = scrape_g8_rates()

lines = [f"📊 G8 Macro Update — {now.strftime('%H:%M')} SGT\n"]

lines.append("🏛 Central Bank Policy Rates")
if central_bank_rates:
    # Ensure a consistent order for G8
    order = ["Fed", "ECB", "BoE", "BoJ", "BoC", "RBA", "RBNZ", "SNB"]
    for bank in order:
        if bank in central_bank_rates:
            lines.append(f"{bank:<5}: {central_bank_rates[bank]}")
else:
    lines.append("⚠️ Could not fetch G8 rates.")

message = "\n".join(lines)

# ===== SEND =====
url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
payload = {"chat_id": CHAT_ID, "text": message}
requests.post(url, data=payload)
