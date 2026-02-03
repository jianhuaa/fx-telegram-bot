import time
import requests
import re
import pandas as pd
import yfinance as yf
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo 

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

# IANA Timezone Objects for precision
SGT = ZoneInfo("Asia/Singapore")
ET = ZoneInfo("America/New_York")

now_sgt = datetime.now(SGT)
now_et = datetime.now(ET)

TARGET_PAIRS = {
    "AUDCAD": "AUDCAD=X", "AUDCHF": "AUDCHF=X", "AUDJPY": "AUDJPY=X", "AUDNZD": "AUDNZD=X", "AUDUSD": "AUDUSD=X",
    "CADCHF": "CADCHF=X", "CADJPY": "CADJPY=X",
    "CHFJPY": "CHFJPY=X",
    "EURAUD": "EURAUD=X", "EURCAD": "EURCAD=X", "EURCHF": "EURCHF=X", "EURGBP": "EURGBP=X", "EURJPY": "EURJPY=X", "EURNZD": "EURNZD=X", "EURUSD": "EURUSD=X",
    "GBPAUD": "GBPAUD=X", "GBPCAD": "GBPCAD=X", "GBPCHF": "GBPCHF=X", "GBPJPY": "GBPJPY=X", "GBPNZD": "GBPNZD=X", "GBPUSD": "GBPUSD=X",
    "NZDCAD": "NZDCAD=X", "NZDCHF": "NZDCHF=X", "NZDJPY": "NZDJPY=X", "NZDUSD": "NZDUSD=X",
    "USDCAD": "USDCAD=X", "USDCHF": "USDCHF=X", "USDJPY": "USDJPY=X"
}

# Probabilities (Static)
base_outlook = {
    "Fed":  ["🔴⬇️65%", "🟡➡️35%"],
    "ECB":  ["🔴⬇️45%", "🟡➡️55%"],
    "BoE":  ["🔴⬇️30%", "🟢⬆️15%"],
    "BoJ":  ["🔴⬇️20%", "🟢⬆️30%"],
    "SNB":  ["🔴⬇️55%", "🟡➡️45%"],
    "RBA":  ["🟢⬆️40%", "🟡➡️60%"],
    "BoC":  ["🔴⬇️35%", "🟡➡️65%"],
    "RBNZ": ["🔴⬇️25%", "🟢⬆️20%"]
}

# ===== HELPERS =====
def setup_driver():
    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--window-size=1920,1080")
    
    prefs = {
        "credentials_enable_service": False,
        "profile.password_manager_enabled": False,
        "profile.default_content_setting_values.notifications": 2,
        "profile.managed_default_content_settings.popups": 2
    }
    options.add_experimental_option("prefs", prefs)
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    
    options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36")
    
    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
    
    # Force the browser to New York Time to ensure ForexFactory serves ET
    driver.execute_cdp_cmd('Emulation.setTimezoneOverride', {'timezoneId': 'America/New_York'})
    
    stealth(driver, languages=["en-US", "en"], vendor="Google Inc.", platform="Win32", webgl_vendor="Intel Inc.", renderer="Intel Iris OpenGL Engine", fix_hairline=True)
    return driver

# ===== SCRAPERS =====

def scrape_cbrates_current():
    print("🏛️ Scraping Current Rates (cbrates.com) [v3 Robust]...")
    url = "https://www.cbrates.com/"
    rates = {}
    identifier_map = {
        "(Fed)": "Fed", "(ECB)": "ECB", "(BoE)": "BoE", "(BoJ)": "BoJ",
        "(BoC)": "BoC", "(SNB)": "SNB", "Australia": "RBA", "New Zealand": "RBNZ"
    }
    try:
        r = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'})
        soup = BeautifulSoup(r.text, 'html.parser')
        rows = soup.find_all('tr')
        for row in rows:
            text = row.get_text(" ", strip=True)
            for identifier, code in identifier_map.items():
                if identifier in text:
                    if code == "Fed":
                        range_match = re.search(r"(\d+\.\d{2})\s*-\s*(\d+\.\d{2})", text)
                        if range_match: 
                            rates[code] = range_match.group(2) + "%"
                        else:
                            match = re.search(r"(\d+\.\d{2})", text)
                            if match: rates[code] = match.group(1) + "%"
                    else:
                        match = re.search(r"(\d+\.\d{2})\s*%", text)
                        if match: rates[code] = match.group(1) + "%"
                        else:
                            match = re.search(r"(\d+\.\d{2})", text)
                            if match: rates[code] = match.group(1) + "%"
                    break
        return rates
    except Exception as e:
        print(f"⚠️ CBRates Rates Failed: {e}"); return None

def scrape_cbrates_meetings():
    print("🗓️ Scraping Meeting Dates (cbrates.com/meetings)...")
    url = "https://www.cbrates.com/meetings.htm"
    upcoming_meetings = {}
    identifiers = {
        "Federal Reserve": "Fed", "European Central Bank": "ECB", 
        "Bank of England": "BoE", "Bank of Japan": "BoJ", 
        "Reserve Bank of Australia": "RBA", "Swiss National Bank": "SNB", 
        "Reserve Bank of New Zealand": "RBNZ", "Bank of Canada": "BoC"
    }
    try:
        r = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'})
        soup = BeautifulSoup(r.text, 'html.parser')
        rows = soup.find_all('tr')
        today = datetime.now()
        current_year = today.year
        found_meetings = {code: [] for code in identifiers.values()}
        for row in rows:
            text = row.get_text(" ", strip=True)
            date_match = re.search(r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+(\d{1,2})", text, re.IGNORECASE)
            if date_match:
                month_str, day_str = date_match.group(1), date_match.group(2)
                try:
                    meeting_date = datetime.strptime(f"{month_str} {day_str} {current_year}", "%b %d %Y")
                    for identifier, code in identifiers.items():
                        if identifier in text: found_meetings[code].append(meeting_date)
                except: continue
        for code, dates in found_meetings.items():
            dates.sort()
            future_date_found = False
            for d in dates:
                if d.date() >= today.date():
                    upcoming_meetings[code] = d.strftime("%b %d")
                    future_date_found = True
                    break
            if not future_date_found: upcoming_meetings[code] = "TBA"
        return upcoming_meetings
    except Exception as e:
        print(f"⚠️ CBRates Meetings Failed: {e}"); return None

def scrape_forex_factory():
    print("📅 Scraping ForexFactory (Today)...")
    driver = None
    releases = []
    try:
        driver = setup_driver()
        driver.get("https://www.forexfactory.com/calendar?week=this")
        for i in range(1, 4):
            driver.execute_script(f"window.scrollTo(0, document.body.scrollHeight * {i/3});")
            time.sleep(1.5)
        rows = driver.find_elements(By.CSS_SELECTOR, "tr.calendar__row")
        current_date_str, last_valid_time = "", ""
        for row in rows:
            row_class = row.get_attribute("class")
            if "calendar__row--day-breaker" in row_class:
                val = row.text.strip()
                if val: current_date_str = val
                continue
            impact = row.find_elements(By.CSS_SELECTOR, "td.calendar__impact span.icon")
            if not impact or "icon--ff-impact-red" not in impact[0].get_attribute("class"): continue
            try:
                currency = row.find_element(By.CSS_SELECTOR, "td.calendar__currency").text.strip()
                event = row.find_element(By.CSS_SELECTOR, "span.calendar__event-title").text.strip()
                time_str = row.find_element(By.CSS_SELECTOR, "td.calendar__time").text.strip()
                
                # RAW TIME FROM SOURCE (ET)
                if not time_str: time_str = last_valid_time
                else: last_valid_time = time_str
                
                act = row.find_element(By.CSS_SELECTOR, "td.calendar__actual").text.strip()
                cons = row.find_element(By.CSS_SELECTOR, "td.calendar__forecast").text.strip()
                prev = row.find_element(By.CSS_SELECTOR, "td.calendar__previous").text.strip()
                flag_map = {"USD":"🇺🇸", "EUR":"🇪🇺", "GBP":"🇬🇧", "JPY":"🇯🇵", "CAD":"🇨🇦", "AUD":"🇦🇺", "NZD":"🇳🇿", "CHF":"🇨🇭"}
                releases.append({"date": current_date_str, "flag": flag_map.get(currency, "🌍"), "title": f"{currency} {event}", "time_et": time_str, "act": act or "-", "cons": cons or "-", "prev": prev or "-"})
            except: continue
        return releases
    except Exception as e:
        print(f"⚠️ FF Scraping Failed: {e}"); return None
    finally:
        if driver: driver.quit()

# ===== CALCULATIONS =====
def fetch_fx_data():
    print("📈 Fetching FX Data (Institutional Anchor: 05:00 SGT)...")
    tickers = list(TARGET_PAIRS.values())
    data = yf.download(tickers, period="10d", interval="1h", progress=False)
    if isinstance(data.columns, pd.MultiIndex):
        closes = data.xs('Close', level=0, axis=1)
    else: closes = data['Close']
    results = {}
    for pair, ticker in TARGET_PAIRS.items():
        if ticker in closes.columns:
            series = closes[ticker].dropna()
            if not series.empty:
                curr = float(series.iloc[-1])
                ny_cut_candles = series[series.index.hour == 5]
                if not ny_cut_candles.empty:
                    p_day = float(ny_cut_candles.iloc[-1])
                    p_week = float(ny_cut_candles.iloc[0])
                else:
                    p_day = float(series.iloc[0])
                    p_week = float(series.iloc[0])
                mult = 100 if "JPY" in pair else 10000
                results[pair] = {
                    "price": curr, 
                    "dd": int((curr - p_day) * mult), 
                    "ww": int((curr - p_week) * mult), 
                    "is_jpy": "JPY" in pair
                }
    return results

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

# Build Header: Compact Lowercase
lines = [f"📊 <b>G8 FX Update</b> — {now_sgt.strftime('%I:%M%p').lower()} SGT / {now_et.strftime('%I:%M%p').lower()} ET\n", "🔥 <b>Top Movers</b>"]
for curr, vals in sorted(base_movers.items()):
    lines.append(f"{curr}: {vals[0]:+} pips d/d | {vals[1]:+} w/w")

# FX Crosses Vault
lines.append("\n💰 <b>28 FX G8 Crosses</b>")
groups = {
    "AUD": ["AUDCAD", "AUDCHF", "AUDJPY", "AUDNZD", "AUDUSD"],
    "CAD": ["CADCHF", "CADJPY"],
    "CHF": ["CHFJPY"],
    "EUR": ["EURAUD", "EURCAD", "EURCHF", "EURGBP", "EURJPY", "EURNZD", "EURUSD"],
    "GBP": ["GBPAUD", "GBPCAD", "GBPCHF", "GBPJPY", "GBPNZD", "GBPUSD"],
    "NZD": ["NZDCAD", "NZDCHF", "NZDJPY", "NZDUSD"],
    "USD": ["USDCAD", "USDCHF", "USDJPY"]
}

all_crosses_content = []
for base, pairs in groups.items():
    seg = [f"<b>{base}</b>"]
    for pair in pairs:
        if pair in fx_results:
            d = fx_results[pair]
            p_fmt = f"{d['price']:.2f}" if d['is_jpy'] else f"{d['price']:.4f}"
            seg.append(f"{pair} <code>{p_fmt}</code> {d['dd']:+} d/d | {d['ww']:+} w/w")
    all_crosses_content.append("\n".join(seg))

lines.append(f"<blockquote expandable>\n" + "\n\n".join(all_crosses_content) + "\n</blockquote>")

# Blank Line Space
lines.append("")

# Calendar Section (ET Strictly)
lines.append("📅 <b>Economic Calendar (ET)</b>") 
if calendar_events:
    cal_content = []
    for e in calendar_events:
        txt = f"[{e['date']}] {e['flag']} {e['title']} | {e['time_et']} ET"
        if e['act'] != "-": 
            txt += f"\n   Act: {e['act']} | C: {e['cons']} | P: {e['prev']}"
        cal_content.append(txt)
    lines.append(f"<blockquote expandable>\n" + "\n".join(cal_content) + "\n</blockquote>")
else:
    lines.append("<blockquote expandable>No high impact events today.</blockquote>")

# Blank Line Space
lines.append("")

# Central Bank Rates
lines.append("🏛 <b>Central Bank Rates</b>")
if scraped_rates:
    rate_content = []
    order = ["RBA", "BoC", "SNB", "ECB", "BoE", "BoJ", "RBNZ", "Fed"]
    for bank in order:
        val = scraped_rates.get(bank, "N/A")
        rate_content.append(f"{bank}: {val}")
    lines.append(f"<blockquote expandable>\n" + "\n".join(rate_content) + "\n</blockquote>")
else:
    lines.append("<blockquote expandable>⚠️ Scraping Failed</blockquote>")

# Outlook
lines.append("\n🔮 <b>Rates Outlook</b>")
outlook_content = []
order = ["RBA", "BoC", "SNB", "ECB", "BoE", "BoJ", "RBNZ", "Fed"]
for bank in order:
    probs = base_outlook.get(bank, ["-", "-"])
    meet_date = scraped_meetings.get(bank, "TBA") if scraped_meetings else "TBA"
    outlook_content.append(f"{bank}: {probs[0]} | {probs[1]} | {meet_date}")
lines.append(f"<blockquote expandable>\n" + "\n".join(outlook_content) + "\n</blockquote>")

# Telegram Bot Dispatch
print("Sending to Telegram...")
try:
    response = requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", 
                             json={
                                 "chat_id": CHAT_ID, 
                                 "text": "\n".join(lines), 
                                 "parse_mode": "HTML", 
                                 "disable_web_page_preview": True
                             })
    print(f"Status: {response.status_code}")
except Exception as e:
    print(f"Telegram Error: {e}")
