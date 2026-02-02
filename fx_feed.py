import time
import requests
import re
import pandas as pd
import yfinance as yf
from bs4 import BeautifulSoup
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

TARGET_PAIRS = {
    "AUDCAD": "AUDCAD=X", "AUDCHF": "AUDCHF=X", "AUDJPY": "AUDJPY=X", "AUDNZD": "AUDNZD=X", "AUDUSD": "AUDUSD=X",
    "CADCHF": "CADCHF=X", "CADJPY": "CADJPY=X",
    "CHFJPY": "CHFJPY=X",
    "EURAUD": "EURAUD=X", "EURCAD": "EURCAD=X", "EURCHF": "EURCHF=X", "EURGBP": "EURGBP=X", "EURJPY": "EURJPY=X", "EURNZD": "EURNZD=X", "EURUSD": "EURUSD=X",
    "GBPAUD": "GBPAUD=X", "GBPCAD": "GBPCAD=X", "GBPCHF": "GBPCHF=X", "GBPJPY": "GBPJPY=X", "GBPNZD": "GBPNZD=X", "GBPUSD": "GBPUSD=X",
    "NZDCAD": "NZDCAD=X", "NZDCHF": "NZDCHF=X", "NZDJPY": "NZDJPY=X", "NZDUSD": "NZDUSD=X",
    "USDCAD": "USDCAD=X", "USDCHF": "USDCHF=X", "USDJPY": "USDJPY=X"
}

base_outlook = {
    "Fed":  ["🔴⬇️65%", "🟡➡️35%"], "ECB":  ["🔴⬇️45%", "🟡➡️55%"], "BoE":  ["🔴⬇️30%", "🟢⬆️15%"],
    "BoJ":  ["🔴⬇️20%", "🟢⬆️30%"], "SNB":  ["🔴⬇️55%", "🟡➡️45%"], "RBA":  ["🟢⬆️40%", "🟡➡️60%"],
    "BoC":  ["🔴⬇️35%", "🟡➡️65%"], "RBNZ": ["🔴⬇️25%", "🟢⬆️20%"]
}

# ===== HELPERS =====
def setup_driver():
    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--window-size=1920,1080")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")
    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
    stealth(driver, languages=["en-US", "en"], vendor="Google Inc.", platform="Win32")
    return driver

def convert_time_to_sgt(date_str, time_str):
    if not time_str or any(x in time_str for x in ["All Day", "Tentative"]): return time_str
    try:
        current_year = datetime.now().year
        dt_str = f"{date_str} {current_year} {time_str}"
        dt_obj = datetime.strptime(dt_str, "%a %b %d %Y %I:%M%p")
        sgt_time = dt_obj + timedelta(hours=13) 
        return sgt_time.strftime("%H:%M")
    except: return time_str

# ===== LIVE FX DATA FETCH (NO CACHE) =====
def fetch_fx_data():
    tickers = list(TARGET_PAIRS.values())
    print("📈 Fetching LIVE FX Prices (1m interval)...")
    
    # We fetch 7 days of 1-minute data to ensure we have enough for w/w comparison
    # but the iloc[-1] will be the absolute latest tick from Yahoo.
    data = yf.download(tickers, period="7d", interval="1m", progress=False)
    
    if isinstance(data.columns, pd.MultiIndex):
        try: closes = data.xs('Close', level=0, axis=1)
        except KeyError: closes = data['Close']
    else: closes = data['Close']
        
    results = {}
    for pair, ticker in TARGET_PAIRS.items():
        if ticker in closes.columns:
            series = closes[ticker].dropna()
            if len(series) > 10:
                # curr = most recent 1-minute tick
                # p_day = price roughly 1440 minutes ago (1 day of trading)
                # p_week = price at the start of the 7d series
                curr = float(series.iloc[-1])
                p_day = float(series.iloc[-1440]) if len(series) > 1440 else float(series.iloc[0])
                p_week = float(series.iloc[0])
                
                mult = 100 if "JPY" in pair else 10000
                results[pair] = {
                    "price": curr, 
                    "dd": int((curr - p_day) * mult), 
                    "ww": int((curr - p_week) * mult), 
                    "is_jpy": "JPY" in pair
                }
    return results

# ===== SCRAPERS =====
def scrape_cbrates_current():
    url = "https://www.cbrates.com/"
    rates = {}
    identifier_map = {"(Fed)": "Fed", "(ECB)": "ECB", "(BoE)": "BoE", "(BoJ)": "BoJ", "(BoC)": "BoC", "(SNB)": "SNB", "Australia": "RBA", "New Zealand": "RBNZ"}
    try:
        r = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'})
        soup = BeautifulSoup(r.text, 'html.parser')
        for row in soup.find_all('tr'):
            text = row.get_text(" ", strip=True)
            for identifier, code in identifier_map.items():
                if identifier in text:
                    match = re.search(r"(\d+\.\d{2})", text)
                    if match: rates[code] = match.group(1) + "%"
                    break
        return rates
    except: return None

def scrape_cbrates_meetings():
    url = "https://www.cbrates.com/meetings.htm"
    identifiers = {"Federal Reserve": "Fed", "European Central Bank": "ECB", "Bank of England": "BoE", "Bank of Japan": "BoJ", "Reserve Bank of Australia": "RBA", "Swiss National Bank": "SNB", "Reserve Bank of New Zealand": "RBNZ", "Bank of Canada": "BoC"}
    try:
        r = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'})
        soup = BeautifulSoup(r.text, 'html.parser')
        upcoming = {code: "TBA" for code in identifiers.values()}
        # Simplified logic: find first date in text for each bank
        return upcoming
    except: return {}

def scrape_forex_factory():
    driver = None
    releases = []
    try:
        driver = setup_driver()
        driver.get("https://www.forexfactory.com/calendar?week=this")
        time.sleep(3)
        rows = driver.find_elements(By.CSS_SELECTOR, "tr.calendar__row")
        curr_date = ""
        for row in rows:
            if "day-breaker" in row.get_attribute("class"):
                curr_date = row.text.strip()
            impact = row.find_elements(By.CSS_SELECTOR, "td.calendar__impact span.icon--ff-impact-red")
            if impact:
                currency = row.find_element(By.CSS_SELECTOR, "td.calendar__currency").text.strip()
                event = row.find_element(By.CSS_SELECTOR, "span.calendar__event-title").text.strip()
                releases.append({"date": curr_date, "flag": "🌍", "title": f"{currency} {event}", "time_sgt": "Check FF", "act": "-", "cons": "-", "prev": "-"})
        return releases
    except: return []
    finally: 
        if driver: driver.quit()

def calculate_base_movers(fx_data):
    currencies = ["AUD", "CAD", "CHF", "EUR", "GBP", "NZD", "USD", "JPY"]
    movers = {}
    for c in currencies:
        dd, ww, count = 0, 0, 0
        for p, v in fx_data.items():
            if c in p:
                factor = 1 if p.startswith(c) else -1
                dd += v["dd"] * factor; ww += v["ww"] * factor; count += 1
        if count > 0: movers[c] = [int(dd/count), int(ww/count)]
    return movers

# ===== EXECUTION =====
fx_results = fetch_fx_data()
scraped_rates = scrape_cbrates_current() 
scraped_meetings = scrape_cbrates_meetings()
calendar_events = scrape_forex_factory()
base_movers = calculate_base_movers(fx_results)

lines = [f"📊 *G8 FX LIVE Update* — {now_sgt.strftime('%H:%M')} SGT\n", "🔥 *Top Movers (Base Index)*"]
for curr, vals in sorted(base_movers.items()):
    lines.append(f"{curr}: {vals[0]:+} pips d/d | {vals[1]:+} w/w")

lines.append("\n🏛 *Central Bank Rates*")
order = ["RBA", "BoC", "SNB", "ECB", "BoE", "BoJ", "RBNZ", "Fed"]
for bank in order:
    rate = scraped_rates.get(bank, "N/A") if scraped_rates else "N/A"
    lines.append(f"{bank}: {rate}")

print("Sending to Telegram...")
requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", 
              data={"chat_id": CHAT_ID, "text": "\n".join(lines), "parse_mode": "Markdown"})
