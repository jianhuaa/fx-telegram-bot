import time
import requests
import pandas as pd
import yfinance as yf
import random
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

# Added back the Rates Outlook
rates_outlook = {
    "Fed":  ["🔴⬇️65%", "🟡➡️35%", "18 Mar 26"],
    "ECB":  ["🔴⬇️45%", "🟡➡️55%", "05 Feb 26"],
    "BoE":  ["🔴⬇️30%", "🟢⬆️15%", "05 Feb 26"],
    "BoJ":  ["🔴⬇️20%", "🟢⬆️30%", "19 Mar 26"],
    "SNB":  ["🔴⬇️55%", "🟡➡️45%", "19 Mar 26"],
    "RBA":  ["🟢⬆️40%", "🟡➡️60%", "03 Feb 26"],
    "BoC":  ["🔴⬇️35%", "🟡➡️65%", "18 Mar 26"],
    "RBNZ": ["🔴⬇️25%", "🟢⬆️20%", "18 Feb 26"]
}

# ===== HELPERS =====
def setup_driver():
    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--window-size=1920,1080")
    # Masking automation
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
def scrape_cb_rates():
    print("🕷️ Scraping Central Bank rates...")
    driver = None
    try:
        driver = setup_driver()
        driver.get("https://www.investing.com/central-banks/")
        
        # Based on your HTML: Targeted wait for the table ID
        WebDriverWait(driver, 20).until(EC.presence_of_element_located((By.ID, "curr_table")))
        
        rates = {}
        name_map = {
            "Federal Reserve": "Fed", "European Central Bank": "ECB", "Bank of England": "BoE", 
            "Bank of Japan": "BoJ", "Bank of Canada": "BoC", "Reserve Bank of Australia": "RBA", 
            "Reserve Bank of New Zealand": "RBNZ", "Swiss National Bank": "SNB"
        }

        # Iterate directly through the tbody rows provided in your HTML snippet
        rows = driver.find_elements(By.CSS_SELECTOR, "table#curr_table tbody tr")
        for row in rows:
            cols = row.find_elements(By.TAG_NAME, "td")
            if len(cols) < 4: continue
            
            row_text = row.text
            for full_name, short_name in name_map.items():
                if full_name in row_text:
                    # Col 2: Rate, Col 3: Next Meeting (cleaning whitespace)
                    rate_val = cols[2].text.strip()
                    next_meet = cols[3].text.strip().replace("\n", " ").strip()
                    # Final cleanup of excessive spaces from the HTML source
                    next_meet = " ".join(next_meet.split())
                    rates[short_name] = {"rate": rate_val, "meeting": next_meet}
        return rates
    except Exception as e:
        print(f"⚠️ CB Scraping Failed: {e}"); return None
    finally:
        if driver: driver.quit()

def scrape_forex_factory():
    print("📅 Scraping ForexFactory...")
    driver = None
    releases = []
    try:
        driver = setup_driver()
        driver.get("https://www.forexfactory.com/calendar?week=this")
        
        # FIX: MULTI-STEP SCROLLING
        # This forces the browser to trigger lazy-loading for Wed, Thu, Fri
        for i in range(1, 6):
            driver.execute_script(f"window.scrollTo(0, document.body.scrollHeight * {i/5});")
            time.sleep(2) # Sufficient time for data center IPs
        
        rows = driver.find_elements(By.CSS_SELECTOR, "tr.calendar__row")
        current_date_str, last_valid_time = "", ""
        
        for row in rows:
            row_class = row.get_attribute("class")
            if "calendar__row--day-breaker" in row_class:
                val = row.text.strip()
                if val: current_date_str = val
                continue
            
            # Impact Check
            impact = row.find_elements(By.CSS_SELECTOR, "td.calendar__impact span.icon")
            if not impact or "icon--ff-impact-red" not in impact[0].get_attribute("class"):
                continue

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
                releases.append({
                    "date": current_date_str, "flag": flag_map.get(currency, "🌍"),
                    "title": f"{currency} {event}", "time_sgt": sgt_time,
                    "act": act or "-", "cons": cons or "-", "prev": prev or "-"
                })
            except: continue
        return sorted(releases, key=lambda x: x['date']) # Ensure order
    except Exception as e:
        print(f"⚠️ FF Scraping Failed: {e}"); return None
    finally:
        if driver: driver.quit()

# ===== CALCS =====
def fetch_fx_data():
    tickers = list(TARGET_PAIRS.values())
    data = yf.download(tickers, period="1mo", progress=False)
    closes = data.xs('Close', level=0, axis=1) if isinstance(data.columns, pd.MultiIndex) else data['Close']
    results = {}
    for pair, ticker in TARGET_PAIRS.items():
        if ticker in closes.columns:
            series = closes[ticker].dropna()
            if len(series) >= 6:
                curr, p_day, p_week = float(series.iloc[-1]), float(series.iloc[-2]), float(series.iloc[-6])
                mult = 100 if "JPY" in pair else 10000
                results[pair] = {"price": curr, "dd": int((curr - p_day) * mult), "ww": int((curr - p_week) * mult), "is_jpy": "JPY" in pair}
    return results

def calculate_base_movers(fx_data):
    movers = {}
    for c in ["AUD", "CAD", "CHF", "EUR", "GBP", "NZD", "USD", "JPY"]:
        dd, ww, count = 0, 0, 0
        for p, v in fx_data.items():
            if c in p:
                factor = 1 if p.startswith(c) else -1
                dd += v["dd"] * factor; ww += v["ww"] * factor; count += 1
        if count > 0: movers[c] = [int(dd/count), int(ww/count)]
    return movers

# ===== EXECUTION =====
fx_results = fetch_fx_data()
scraped_rates = scrape_cb_rates()
calendar_events = scrape_forex_factory()
base_movers = calculate_base_movers(fx_results)

# Build Message
lines = [f"📊 *G8 FX Update* — {now_sgt.strftime('%H:%M')} SGT\n", "🔥 *Top Movers (Base Index)*"]
for curr, vals in sorted(base_movers.items()):
    lines.append(f"{curr}: {vals[0]:+} pips d/d | {vals[1]:+} w/w")

lines.append("\n---")
groups = {"AUD": ["AUDCAD", "AUDCHF", "AUDJPY", "AUDNZD", "AUDUSD"], "EUR": ["EURUSD", "EURJPY", "EURGBP"], "USD": ["USDJPY", "USDCAD", "USDCHF"]}
for base, pairs in groups.items():
    seg = [f"{p} `{fx_results[p]['price']:.4f}` {fx_results[p]['dd']:+} d/d" for p in pairs if p in fx_results]
    if seg: lines.append(f"*{base}*\n" + "\n".join(seg) + "\n")

lines.append("---\n📅 *ForexFactory: High Impact*")
if calendar_events:
    for e in calendar_events:
        lines.append(f"[{e['date']}] {e['flag']} {e['title']} | {e['time_sgt']}")
        if e['act'] != "-": lines.append(f"   Act: {e['act']} | C: {e['cons']} | P: {e['prev']}")
else: lines.append("⚠️ _Fetch Error (Lazy Load)_")

lines.append("---\n🏛 *Central Banks*")
if scraped_rates:
    for bank in ["Fed", "ECB", "BoE", "BoJ", "RBA", "RBNZ", "SNB", "BoC"]:
        d = scraped_rates.get(bank)
        if d: lines.append(f"{bank}: {d['rate']} (Next: {d['meeting']})")
else: lines.append("⚠️ _Table Layout Changed_")

lines.append("\n🔮 *Rates Outlook*")
for bank, outlook in rates_outlook.items():
    lines.append(f"{bank}: {outlook[0]} | {outlook[1]} | {outlook[2]}")

# Final Send
requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", data={"chat_id": CHAT_ID, "text": "\n".join(lines), "parse_mode": "Markdown"})
