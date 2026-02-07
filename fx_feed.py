import time
import requests
import re
import pandas as pd
import yfinance as yf
import cloudscraper
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

# IANA Timezone Objects
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

# Dynamic Futures Mapping for the NEXT TWO contracts
FUTURES_MAP = {
    "Fed": ["ZQ*0", "ZQ*1"],  # 30-Day Fed Funds
    "BoE": ["J8*0", "J8*1"],  # 3-Month SONIA
    "ECB": ["IM*0", "IM*1"],  # 3-Month Euribor
    "BoC": ["RG*0", "RG*1"],  # 3-Month CORRA
    "RBNZ": ["BF*0", "BF*1"], # 90-Day Bank Bill
    "BoJ": ["T0*0", "T0*1"],  # 3-Month TONA
    "SNB": ["J2*0", "J2*1"],  # 3-Month SARON
    "RBA": ["IR*0", "IR*1"]   # 30-Day Interbank Cash Rate
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
    driver.execute_cdp_cmd('Emulation.setTimezoneOverride', {'timezoneId': 'America/New_York'})
    
    stealth(driver, languages=["en-US", "en"], vendor="Google Inc.", platform="Win32", webgl_vendor="Intel Inc.", renderer="Intel Iris OpenGL Engine", fix_hairline=True)
    return driver

# ===== SCRAPERS =====

def scrape_cbrates_current():
    print("🏛️ Scraping Current Rates (cbrates.com)...")
    scraper = cloudscraper.create_scraper()
    rates = {}
    identifier_map = {
        "(Fed)": "Fed", "(ECB)": "ECB", "(BoE)": "BoE", "(BoJ)": "BoJ",
        "(BoC)": "BoC", "(SNB)": "SNB", "Australia": "RBA", "New Zealand": "RBNZ"
    }
    try:
        r = scraper.get("https://www.cbrates.com/")
        soup = BeautifulSoup(r.text, 'html.parser')
        rows = soup.find_all('tr')
        for row in rows:
            text = row.get_text(" ", strip=True)
            for identifier, code in identifier_map.items():
                if identifier in text:
                    if code == "Fed":
                        range_match = re.search(r"(\d+\.\d{2})\s*-\s*(\d+\.\d{2})", text)
                        if range_match: 
                            rates[code] = float(range_match.group(2))
                        else:
                            match = re.search(r"(\d+\.\d{2})", text)
                            if match: rates[code] = float(match.group(1))
                    else:
                        match = re.search(r"(\d+\.\d{2})\s*%", text)
                        if match: rates[code] = float(match.group(1))
                        else:
                            match = re.search(r"(\d+\.\d{2})", text)
                            if match: rates[code] = float(match.group(1))
                    break
        return rates
    except Exception as e:
        print(f"⚠️ CBRates Rates Failed: {e}"); return None

def scrape_cbrates_meetings():
    print("🗓️ Scraping Next TWO Meeting Dates...")
    scraper = cloudscraper.create_scraper()
    upcoming_meetings = {}
    identifiers = {
        "Federal Reserve": "Fed", "European Central Bank": "ECB", 
        "Bank of England": "BoE", "Bank of Japan": "BoJ", 
        "Reserve Bank of Australia": "RBA", "Swiss National Bank": "SNB", 
        "Reserve Bank of New Zealand": "RBNZ", "Bank of Canada": "BoC"
    }
    try:
        r = scraper.get("https://www.cbrates.com/meetings.htm")
        soup = BeautifulSoup(r.text, 'html.parser')
        rows = soup.find_all('tr')
        today = datetime.now()
        current_year = today.year
        found_meetings = {code: [] for code in identifiers.values()}
        
        for row in rows:
            text = row.get_text(" ", strip=True)
            date_match = re.search(r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+(\d{1,2})", text, re.IGNORECASE)
            if date_match:
                try:
                    meeting_date = datetime.strptime(f"{date_match.group(1)} {date_match.group(2)} {current_year}", "%b %d %Y")
                    for identifier, code in identifiers.items():
                        if identifier in text: found_meetings[code].append(meeting_date)
                except: continue
        
        for code, dates in found_meetings.items():
            dates.sort()
            future_dates = [d.strftime("%d %b") for d in dates if d.date() >= today.date()]
            # Ensure we always have at least 2 slots, even if marked TBA
            while len(future_dates) < 2:
                future_dates.append("TBA")
            upcoming_meetings[code] = future_dates[:2]
            
        return upcoming_meetings
    except Exception as e:
        print(f"⚠️ CBRates Meetings Failed: {e}"); return {code: ["TBA", "TBA"] for code in identifiers.values()}

def get_barchart_probability(symbol, current_rate, scraper):
    """Internal helper to scrape a single contract probability."""
    try:
        url = f"https://www.barchart.com/futures/quotes/{symbol}/overview"
        r = scraper.get(url)
        match = re.search(r'"lastPrice"\s*:\s*"([\d\.]+)"', r.text) or re.search(r'"lastPrice"\s*:\s*([\d\.]+)', r.text)
        if match:
            price = float(match.group(1))
            implied_rate = 100.0 - price
            diff = implied_rate - current_rate
            probability = abs(int((diff / 0.25) * 100))
            
            if probability < 20: emoji = f"🟡➡️{probability}%"
            elif diff < 0: emoji = f"🔴⬇️{probability}%"
            else: emoji = f"🟢⬆️{probability}%"
            return emoji
    except: pass
    return "⚪N/A"

def scrape_barchart_outlook(current_rates):
    print("📈 Scraping Next 2 Contracts for Dynamic Outlook...")
    scraper = cloudscraper.create_scraper()
    results = {}
    
    for bank, symbols in FUTURES_MAP.items():
        try:
            current_bench = current_rates.get(bank, 0.0)
            # Fetch for BOTH current and next contract
            prob_0 = get_barchart_probability(symbols[0], current_bench, scraper)
            time.sleep(1.2) # Avoid rate limits
            prob_1 = get_barchart_probability(symbols[1], current_bench, scraper)
            
            results[bank] = [prob_0, prob_1]
            time.sleep(1.2)
        except:
            results[bank] = ["⚪N/A", "⚪N/A"]
    return results

def scrape_forex_factory():
    print("📅 Scraping ForexFactory (Red Folders)...")
    driver = None
    releases = []
    try:
        driver = setup_driver()
        driver.get("https://www.forexfactory.com/calendar?week=this")
        # Scroll logic for lazy loading
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
                
                act = row.find_element(By.CSS_SELECTOR, "td.calendar__actual").text.strip()
                cons = row.find_element(By.CSS_SELECTOR, "td.calendar__forecast").text.strip()
                prev = row.find_element(By.CSS_SELECTOR, "td.calendar__previous").text.strip()
                
                flag_map = {"USD":"🇺🇸", "EUR":"🇪🇺", "GBP":"🇬🇧", "JPY":"🇯🇵", "CAD":"🇨🇦", "AUD":"🇦🇺", "NZD":"🇳🇿", "CHF":"🇨🇭"}
                releases.append({
                    "date": current_date_str, "flag": flag_map.get(currency, "🌍"),
                    "title": f"{currency} {event}", "time_et": time_str,
                    "act": act or "-", "cons": cons or "-", "prev": prev or "-"
                })
            except: continue
        return releases
    except Exception as e:
        print(f"⚠️ FF Scraping Failed: {e}"); return None
    finally:
        if driver: driver.quit()

# ===== CALCULATIONS =====

def fetch_fx_data():
    print("📈 Fetching FX Data (Strict m/m + Anchor Logic)...")
    tickers = list(TARGET_PAIRS.values())
    # Period 2mo allows us to get the price exactly 30 days ago
    data = yf.download(tickers, period="2mo", interval="1d", progress=False)
    
    if isinstance(data.columns, pd.MultiIndex):
        closes = data.xs('Close', level=0, axis=1)
    else:
        closes = data['Close']
        
    results = {}
    for pair, ticker in TARGET_PAIRS.items():
        if ticker in closes.columns:
            series = closes[ticker].dropna()
            if len(series) > 22:
                curr = float(series.iloc[-1])
                p_day = float(series.iloc[-2])
                p_week = float(series.iloc[-6])
                
                # Strict m/m: Locate price exactly 1 month ago
                target_date = series.index[-1] - timedelta(days=30)
                p_month = float(series.asof(target_date))
                
                mult = 100 if "JPY" in pair else 10000
                results[pair] = {
                    "price": curr, 
                    "dd": int((curr - p_day) * mult), 
                    "ww": int((curr - p_week) * mult),
                    "mm": int((curr - p_month) * mult),
                    "is_jpy": "JPY" in pair
                }
    return results

def calculate_base_movers(fx_data):
    currencies = ["AUD", "CAD", "CHF", "EUR", "GBP", "NZD", "USD", "JPY"]
    movers = {}
    for c in currencies:
        dd, ww, mm, count = 0, 0, 0, 0
        for p, v in fx_data.items():
            if c in p:
                factor = 1 if p.startswith(c) else -1
                dd += v["dd"] * factor
                ww += v["ww"] * factor
                mm += v["mm"] * factor
                count += 1
        if count > 0: 
            movers[c] = [int(dd/count), int(ww/count), int(mm/count)]
    return movers

# ===== EXECUTION =====
fx_results = fetch_fx_data()
scraped_rates = scrape_cbrates_current() 
scraped_meetings = scrape_cbrates_meetings()
dynamic_outlook = scrape_barchart_outlook(scraped_rates)
calendar_events = scrape_forex_factory()
base_movers = calculate_base_movers(fx_results)

# Build Header
lines = [f"📊 <b>G8 FX Update</b> — {now_sgt.strftime('%I:%M%p').lower()} SGT\n", "🔥 <b>Top Movers</b>"]
for curr, vals in sorted(base_movers.items()):
    lines.append(f"{curr}: {vals[0]:+} d/d | {vals[1]:+} w/w | {vals[2]:+} m/m")

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
            seg.append(f"{pair} <code>{p_fmt}</code> {d['dd']:+} d/d | {d['ww']:+} w/w | {d['mm']:+} m/m")
    all_crosses_content.append("\n".join(seg))

lines.append(f"<blockquote expandable>\n" + "\n\n".join(all_crosses_content) + "\n</blockquote>\n")

lines.append("📅 <b>Economic Calendar (ET)</b>") 
if calendar_events:
    cal_content = [f"[{e['date']}] {e['flag']} {e['title']} | {e['time_et']} ET" + (f"\n    Act: {e['act']} | C: {e['cons']} | P: {e['prev']}" if e['act'] != "-" else "") for e in calendar_events]
    lines.append(f"<blockquote expandable>\n" + "\n".join(cal_content) + "\n</blockquote>\n")
else: lines.append("<blockquote expandable>No high impact events today.</blockquote>\n")

lines.append("🏛 <b>Central Bank Rates</b>")
if scraped_rates:
    order = ["RBA", "BoC", "SNB", "ECB", "BoE", "BoJ", "RBNZ", "Fed"]
    lines.append("<blockquote expandable>\n" + "\n".join([f"{b}: {scraped_rates.get(b, 0):.2f}%" for b in order]) + "\n</blockquote>\n")
else: lines.append("<blockquote expandable>⚠️ Rates Scraping Failed</blockquote>\n")

lines.append("🔮 <b>Rates Outlook (Next 2 Meetings)</b>")
order = ["RBA", "BoC", "SNB", "ECB", "BoE", "BoJ", "RBNZ", "Fed"]
outlook_lines = []
for b in order:
    meet = scraped_meetings.get(b, ["TBA", "TBA"])
    outl = dynamic_outlook.get(b, ["⚪N/A", "⚪N/A"])
    outlook_lines.append(f"{b}: {meet[0]}: {outl[0]} | {meet[1]}: {outl[1]}")

lines.append("<blockquote expandable>\n" + "\n".join(outlook_lines) + "\n</blockquote>")

print("Sending to Telegram...")
try:
    requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", 
                  json={"chat_id": CHAT_ID, "text": "\n".join(lines), "parse_mode": "HTML", "disable_web_page_preview": True})
except Exception as e: print(f"Telegram Error: {e}")
