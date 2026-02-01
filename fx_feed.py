import time
import requests
import pandas as pd
import yfinance as yf
from datetime import datetime, timedelta, timezone

# Selenium Imports
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
from selenium_stealth import stealth

# ===== CONFIGURATION =====
TELEGRAM_TOKEN = "7649050168:AAHNIYnrHzLOTcjNuMpeKgyUbfJB9x9an3c"
CHAT_ID = "876384974"
SGT_TZ = timezone(timedelta(hours=8))
now_sgt = datetime.now(SGT_TZ)

# Pairs & Outlook kept as per your previous setup
TARGET_PAIRS = {"AUDCAD": "AUDCAD=X", "AUDCHF": "AUDCHF=X", "AUDJPY": "AUDJPY=X", "AUDNZD": "AUDNZD=X", "AUDUSD": "AUDUSD=X", "CADCHF": "CADCHF=X", "CADJPY": "CADJPY=X", "CHFJPY": "CHFJPY=X", "EURAUD": "EURAUD=X", "EURCAD": "EURCAD=X", "EURCHF": "EURCHF=X", "EURGBP": "EURGBP=X", "EURJPY": "EURJPY=X", "EURNZD": "EURNZD=X", "EURUSD": "EURUSD=X", "GBPAUD": "GBPAUD=X", "GBPCAD": "GBPCAD=X", "GBPCHF": "GBPCHF=X", "GBPJPY": "GBPJPY=X", "GBPNZD": "GBPNZD=X", "GBPUSD": "GBPUSD=X", "NZDCAD": "NZDCAD=X", "NZDCHF": "NZDCHF=X", "NZDJPY": "NZDJPY=X", "NZDUSD": "NZDUSD=X", "USDCAD": "USDCAD=X", "USDCHF": "USDCHF=X", "USDJPY": "USDJPY=X"}
rates_outlook = {"Fed": ["🔴⬇️65%", "🟡➡️35%", "18 Mar 26"], "ECB": ["🔴⬇️45%", "🟡➡️55%", "05 Feb 26"], "BoE": ["🔴⬇️30%", "🟢⬆️15%", "05 Feb 26"], "BoJ": ["🔴⬇️20%", "🟢⬆️30%", "19 Mar 26"], "SNB": ["🔴⬇️55%", "🟡➡️45%", "19 Mar 26"], "RBA": ["🟢⬆️40%", "🟡➡️60%", "03 Feb 26"], "BoC": ["🔴⬇️35%", "🟡➡️65%", "18 Mar 26"], "RBNZ": ["🔴⬇️25%", "🟢⬆️20%", "18 Feb 26"]}

def setup_driver():
    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--window-size=1920,1080")
    # Using a 2026-era User Agent string
    options.add_argument("user-agent=Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36")
    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
    stealth(driver, languages=["en-US", "en"], vendor="Google Inc.", platform="Win32", webgl_vendor="Intel Inc.", renderer="Intel Iris OpenGL Engine", fix_hairline=True)
    return driver

def scrape_cb_rates():
    print("🕷️ Scraping CB rates (Anti-Detection Mode)...")
    driver = None
    try:
        driver = setup_driver()
        driver.get("https://www.investing.com/central-banks/")
        # Wait for the specific Federal Reserve text to load
        WebDriverWait(driver, 30).until(EC.presence_of_element_located((By.XPATH, "//*[contains(text(), 'Federal Reserve')]")))
        
        rates = {}
        name_map = {"Federal Reserve": "Fed", "European Central Bank": "ECB", "Bank of England": "BoE", "Bank of Japan": "BoJ", "Bank of Canada": "BoC", "Reserve Bank of Australia": "RBA", "Reserve Bank of New Zealand": "RBNZ", "Swiss National Bank": "SNB"}
        
        # Pull by tag to avoid broken IDs
        rows = driver.find_elements(By.TAG_NAME, "tr")
        for row in rows:
            text = row.text
            for full_name, short_name in name_map.items():
                if full_name in text:
                    cols = row.find_elements(By.TAG_NAME, "td")
                    if len(cols) >= 3:
                        rates[short_name] = cols[2].text.strip()
        return rates
    except Exception as e:
        print(f"⚠️ CB Fail: {e}"); return None
    finally:
        if driver: driver.quit()

def scrape_forex_factory():
    print("📅 Scraping FF (Raw Math Mode)...")
    driver = None
    releases = []
    try:
        driver = setup_driver()
        # Navigate directly to the weekly calendar
        driver.get("https://www.forexfactory.com/calendar?week=this")
        
        # Moderate scroll to trigger lazy loading without looking like a bot
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight / 2);")
        time.sleep(3)
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(3)
        
        rows = driver.find_elements(By.CSS_SELECTOR, "tr.calendar__row")
        current_date_str = ""
        last_valid_time = ""
        
        for row in rows:
            try:
                if "calendar__row--day-breaker" in row.get_attribute("class"):
                    current_date_str = row.text.strip()
                    continue
                
                impact = row.find_elements(By.CSS_SELECTOR, "td.calendar__impact span.icon")
                if not impact or "icon--ff-impact-red" not in impact[0].get_attribute("class"):
                    continue

                currency = row.find_element(By.CSS_SELECTOR, "td.calendar__currency").text.strip()
                event = row.find_element(By.CSS_SELECTOR, "span.calendar__event-title").text.strip()
                time_str = row.find_element(By.CSS_SELECTOR, "td.calendar__time").text.strip()
                
                # Time Math: GitHub is usually UTC/GMT. FF defaults to EST (GMT-5) if not logged in.
                # To get SGT (GMT+8), we add 13 hours to the FF "EST" time.
                if not time_str: time_str = last_valid_time
                else: last_valid_time = time_str
                
                if time_str and ":" in time_str:
                    dt_str = f"{current_date_str} 2026 {time_str}"
                    # Convert 'Mon Feb 2 2026 9:00am' to SGT
                    dt_obj = datetime.strptime(dt_str, "%a %b %d %Y %I:%M%p")
                    sgt_time = (dt_obj + timedelta(hours=13)).strftime("%H:%M")
                else:
                    sgt_time = time_str

                releases.append({
                    "date": current_date_str, "flag": currency, "title": event, "time_sgt": sgt_time,
                    "act": row.find_element(By.CSS_SELECTOR, "td.calendar__actual").text.strip() or "-",
                    "cons": row.find_element(By.CSS_SELECTOR, "td.calendar__forecast").text.strip() or "-",
                    "prev": row.find_element(By.CSS_SELECTOR, "td.calendar__previous").text.strip() or "-"
                })
            except: continue
        return releases
    except Exception as e:
        print(f"⚠️ FF Fail: {e}"); return None
    finally:
        if driver: driver.quit()

# [FX Calculation logic remains exactly as per your previous working copy]
# ... (omitted to focus on the fix)

# Build Message with the restored Currencies
lines = [f"📊 *G8 FX Update* — {now_sgt.strftime('%H:%M')} SGT\n"]
# ... (rest of message builder)

# Send
requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", 
              data={"chat_id": CHAT_ID, "text": "\n".join(lines), "parse_mode": "Markdown"})
