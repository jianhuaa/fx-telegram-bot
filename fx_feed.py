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
    "AUDCAD": "AUDCAD=X", 
    "AUDCHF": "AUDCHF=X", 
    "AUDJPY": "AUDJPY=X", 
    "AUDNZD": "AUDNZD=X", 
    "AUDUSD": "AUDUSD=X",
    "CADCHF": "CADCHF=X", 
    "CADJPY": "CADJPY=X",
    "CHFJPY": "CHFJPY=X",
    "EURAUD": "EURAUD=X", 
    "EURCAD": "EURCAD=X", 
    "EURCHF": "EURCHF=X", 
    "EURGBP": "EURGBP=X", 
    "EURJPY": "EURJPY=X", 
    "EURNZD": "EURNZD=X", 
    "EURUSD": "EURUSD=X",
    "GBPAUD": "GBPAUD=X", 
    "GBPCAD": "GBPCAD=X", 
    "GBPCHF": "GBPCHF=X", 
    "GBPJPY": "GBPJPY=X", 
    "GBPNZD": "GBPNZD=X", 
    "GBPUSD": "GBPUSD=X",
    "NZDCAD": "NZDCAD=X", 
    "NZDCHF": "NZDCHF=X", 
    "NZDJPY": "NZDJPY=X", 
    "NZDUSD": "NZDUSD=X",
    "USDCAD": "USDCAD=X", 
    "USDCHF": "USDCHF=X", 
    "USDJPY": "USDJPY=X"
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
    options.add_argument("--no-sandbox")            # FIXED FOR GITHUB
    options.add_argument("--disable-dev-shm-usage") # FIXED FOR GITHUB
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
        "(Fed)": "Fed",
        "(ECB)": "ECB",
        "(BoE)": "BoE",
        "(BoJ)": "BoJ",
        "(BoC)": "BoC",
        "(SNB)": "SNB",
        "Australia": "RBA",
        "New Zealand": "RBNZ"
    }

    try:
        r = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=15)
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
                        if match:
                            rates[code] = match.group(1) + "%"
                        else:
                            match = re.search(r"(\d+\.\d{2})", text)
                            if match: rates[code] = match.group(1) + "%"
                    break
        return rates
    except Exception as e:
        print(f"⚠️ CBRates Rates Failed: {e}")
        return None

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
        r = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=15)
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
                        if identifier in text: 
                            found_meetings[code].append(meeting_date)
                except: continue

        for code, dates in found_meetings.items():
            dates.sort()
            upcoming_meetings[code] = next((d.strftime("%b %d") for d in dates if d.date() >= today.date()), "TBA")
        return upcoming_meetings
    except Exception as e:
        print(f"⚠️ CBRates Meetings Failed: {e}")
        return None

def scrape_forex_factory():
    print("📅 Scraping ForexFactory (Today)...")
    driver = None
    releases = []
    try:
        driver = setup_driver()
        driver.get("https://www.forexfactory.com/calendar?day=today")
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
                
                flag_map = {"USD":"🇺🇸", "EUR":"🇪🇺", "GBP":"🇬🇧", "JPY":"🇯🇵", "CAD":"🇨🇦", "AUD":"🇦🇺", "NZD":"🇳🇿", "CHF":"🇨🇭"}
                releases.append({
                    "date": current_date_str, 
                    "flag": flag_map.get(currency, "🌍"),
                    "title": f"{currency} {event}", 
                    "time_sgt": sgt_time,
                    "act": row.find_element(By.CSS_SELECTOR, "td.calendar__actual").text.strip() or "-",
                    "cons": row.find_element(By.CSS_SELECTOR, "td.calendar__forecast").text.strip() or "-",
                    "prev": row.find_element(By.CSS_SELECTOR, "td.calendar__previous").text.strip() or "-"
                })
            except: continue
        return releases
    except Exception as e:
        print(f"⚠️ FF Scraping Failed: {e}")
        return None
    finally:
        if driver: driver.quit()

# ===== IMPROVED LIVE CALCULATIONS =====
def fetch_fx_data():
    print("📈 Fetching Live 1m and Historical Daily Data...")
    tickers = list(TARGET_PAIRS.values())
    
    # 1. Get Daily Closes (Friday's Close and Last Week's Close)
    hist_data = yf.download(tickers, period="10d", interval="1d", progress=False)
    hist_closes = hist_data['Close'] if not isinstance(hist_data.columns, pd.MultiIndex) else hist_data.xs('Close', level=0, axis=1)
    
    # 2. Get Live 1-minute Close (Most current price)
    live_data = yf.download(tickers, period="1d", interval="1m", progress=False)
    live_closes = live_data['Close'] if not isinstance(live_data.columns, pd.MultiIndex) else live_data.xs('Close', level=0, axis=1)
        
    results = {}
    for pair, ticker in TARGET_PAIRS.items():
        if ticker in live_closes.columns and ticker in hist_closes.columns:
            l_series = live_closes[ticker].dropna()
            h_series = hist_closes[ticker].dropna()
            
            if not l_series.empty and len(h_series) >= 6:
                curr = float(l_series.iloc[-1])    # Latest 1-min Close
                p_day = float(h_series.iloc[-1])   # Friday Close
                p_week = float(h_series.iloc[-6])  # Last Week Close
                
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
                dd += v["dd"] * factor
                ww += v["ww"] * factor
                count += 1
        if count > 0: 
            movers[c] = [int(dd/count), int(ww/count)]
    return movers

# ===== EXECUTION =====
fx_results = fetch_fx_data()
scraped_rates = scrape_cbrates_current() 
scraped_meetings = scrape_cbrates_meetings()
calendar_events = scrape_forex_factory()
base_movers = calculate_base_movers(fx_results)

# Build Message
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
lines.append("📅 *Economic Calendar (Today)*") 
if calendar_events:
    for e in calendar_events:
        lines.append(f"[{e['date']}] {e['flag']} {e['title']} | {e['time_sgt']}")
        if e['act'] != "-": 
            lines.append(f"    Act: {e['act']} | C: {e['cons']} | P: {e['prev']}")
else: 
    lines.append("No high impact events today.")

lines.append("\n---")
lines.append("🏛 *Central Bank Policy Rates*")
order = ["RBA", "BoC", "SNB", "ECB", "BoE", "BoJ", "RBNZ", "Fed"]
if scraped_rates:
    for bank in order: 
        rate = scraped_rates.get(bank, 'N/A')
        lines.append(f"{bank}: {rate}")
else: 
    lines.append("⚠️ _Scraping Failed_")

lines.append("\n🔮 *Rates Outlook*")
for bank in order:
    probs = base_outlook.get(bank, ["-", "-"])
    date_str = scraped_meetings.get(bank, "TBA")
    lines.append(f"{bank}: {probs[0]} | {probs[1]} | {date_str}")

# SEND INITIAL (Markdown)
print("Sending Main Report...")
try:
    requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", 
                  data={"chat_id": CHAT_ID, "text": "\n".join(lines), "parse_mode": "Markdown"})
except Exception as e: 
    print(f"Error: {e}")

# ==========================================
# FINAL SECTION (HTML Trigger)
# ==========================================
def send_telegram_message(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage" # FIX: Added /bot
    payload = {
        "chat_id": CHAT_ID, 
        "text": message, 
        "parse_mode": "HTML", 
        "disable_web_page_preview": True
    }
    try:
        response = requests.post(url, json=payload, timeout=15)
        return response.json()
    except Exception as e: 
        print(f"Error: {e}")
        return None

if __name__ == "__main__":
    print(f"🚀 Started G8 Feed at {now_sgt.strftime('%H:%M:%S')} SGT")
    
    current_rates = scrape_cbrates_current()
    
    report = f"📊 <b>G8 FX FEED UPDATE</b>\n"
    report += f"📅 {now_sgt.strftime('%d %b %Y | %H:%M')} SGT\n\n"
    
    if current_rates:
        report += "<b>Current Rates:</b>\n"
        for bank, rate in current_rates.items(): 
            report += f"• {bank}: <code>{rate}</code>\n"
    else: 
        report += "⚠️ <i>Rates data currently unavailable.</i>\n"
        
    send_telegram_message(report)
