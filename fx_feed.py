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
    # CHANGE 1: Linux/GitHub Runner compatibility flags
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
    
    stealth(driver, languages=["en-US", "en"], vendor="Google Inc.", platform="Win32", webgl_vendor="Intel Inc.", renderer="Intel Iris OpenGL Engine", fix_hairline=True)
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
                        if range_match: rates[code] = range_match.group(2) + "%"
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
                if not time_str: time_str = last_valid_time
                else: last_valid_time = time_str
                sgt_time = convert_time_to_sgt(current_date_str, time_str)
                act = row.find_element(By.CSS_SELECTOR, "td.calendar__actual").text.strip()
                cons = row.find_element(By.CSS_SELECTOR, "td.calendar__forecast").text.strip()
                prev = row.find_element(By.CSS_SELECTOR, "td.calendar__previous").text.strip()
                flag_map = {"USD":"🇺🇸", "EUR":"🇪🇺", "GBP":"🇬🇧", "JPY":"🇯🇵", "CAD":"🇨🇦", "AUD":"🇦🇺", "NZD":"🇳🇿", "CHF":"🇨🇭"}
                releases.append({"date": current_date_str, "flag": flag_map.get(currency, "🌍"), "title": f"{currency} {event}", "time_sgt": sgt_time, "act": act or "-", "cons": cons or "-", "prev": prev or "-"})
            except: continue
        return releases
    except Exception as e:
        print(f"⚠️ FF Scraping Failed: {e}"); return None
    finally:
        if driver: driver.quit()

# ===== CALCULATIONS (INSTITUTIONAL RESAMPLE LOGIC) =====
def fetch_fx_data():
    print("📈 Fetching FX Data (Institutional Resample: Daily Close Alignment)...")
    tickers = list(TARGET_PAIRS.values())
    
    # We download 10 days of 1-hour data
    data = yf.download(tickers, period="10d", interval="1h", progress=False)
    
    if isinstance(data.columns, pd.MultiIndex):
        closes = data.xs('Close', level=0, axis=1)
    else: closes = data['Close']
    
    results = {}
    for pair, ticker in TARGET_PAIRS.items():
        if ticker in closes.columns:
            series = closes[ticker].dropna()
            if not series.empty:
                # Live Price (Most recent 1h bar)
                curr = float(series.iloc[-1])
                
                # Logic: Resample by Day ('D') and take the '.last()' available price of that day.
                # This automatically finds the 'Institutional Close' for each date.
                daily_closes = series.resample('D').last().dropna()
                
                if len(daily_closes) >= 2:
                    # p_day = The last price of the PREVIOUS full trading day
                    p_day = float(daily_closes.iloc[-2])
                    # p_week = The last price of the oldest trading day in the 10d window
                    p_week = float(daily_closes.iloc[0])
                else:
                    p_day = curr
                    p_week = curr
                
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

lines = [f"📊 *G8 FX Update* — {now_sgt.strftime('%H:%M')} SGT\n", "🔥 *Top Movers (Base Index)*"]
for curr, vals in sorted(base_movers.items()):
    lines.append(f"{curr}: {vals[0]:+} pips d/d | {vals[1]:+} w/w")

lines.append("\n---")

groups = {
    "AUD": ["AUDCAD", "AUDCHF", "AUDJPY", "AUDNZD", "AUDUSD"],
    "CAD": ["CADCHF", "CADJPY"],
    "CHF": ["CHFJPY"],
    "EUR": ["EURAUD", "EURCAD", "EURCHF", "EURGBP", "EURJPY", "EURNZD", "EURUSD"],
    "GBP": ["GBPAUD", "GBPCAD", "GBPCHF", "GBPJPY", "GBPNZD", "GBPUSD"],
    "NZD": ["NZDCAD", "NZDCHF", "NZDJPY", "NZDUSD"],
    "USD": ["USDCAD", "USDCHF", "USDJPY"]
}

for base, pairs in groups.items():
    seg = []
    for pair in pairs:
        if pair in fx_results:
            d = fx_results[pair]
            p_fmt = f"{d['price']:.2f}" if d['is_jpy'] else f"{d['price']:.4f}"
            seg.append(f"{pair} `{p_fmt}`  {d['dd']:+} d/d | {d['ww']:+} w/w")
    if seg:
        lines.append(f"*{base}*")
        lines.append("\n".join(seg) + "\n")

lines.append("---")
lines.append("📅 *Weekly Economic Calendar (Central Time)*") 
if calendar_events:
    for e in calendar_events:
        lines.append(f"[{e['date']}] {e['flag']} {e['title']} | {e['time_sgt']}")
        if e['act'] != "-": lines.append(f"    Act: {e['act']} | C: {e['cons']} | P: {e['prev']}")
else: lines.append("No high impact events today.")

lines.append("\n---")
lines.append("🏛 *Central Bank Policy Rates*")
if scraped_rates:
    order = ["RBA", "BoC", "SNB", "ECB", "BoE", "BoJ", "RBNZ", "Fed"]
    for bank in order:
        rate = scraped_rates.get(bank, "N/A")
        lines.append(f"{bank}: {rate}")
else: lines.append("⚠️ _Scraping Failed_")

lines.append("\n🔮 *Rates Outlook*")
order = ["RBA", "BoC", "SNB", "ECB", "BoE", "BoJ", "RBNZ", "Fed"]
for bank in order:
    probs = base_outlook.get(bank, ["-", "-"])
    date_str = scraped_meetings.get(bank, "TBA") if scraped_meetings else "TBA"
    lines.append(f"{bank}: {probs[0]} | {probs[1]} | {date_str}")

print("Sending to Telegram...")
try:
    response = requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", 
                             data={"chat_id": CHAT_ID, "text": "\n".join(lines), "parse_mode": "Markdown"})
    print(f"Status Code: {response.status_code}")
except Exception as e:
    print(f"Error sending message: {e}")

def send_telegram_message(message):
    """Sends the final report to Telegram using your config."""
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID, 
        "text": message, 
        "parse_mode": "HTML",
        "disable_web_page_preview": True
    }
    try:
        response = requests.post(url, json=payload)
        return response.json()
    except Exception as e:
        print(f"Telegram Error: {e}")
        return None
