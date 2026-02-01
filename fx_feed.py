import os
import time
import requests
import numpy as np
import yfinance as yf
from datetime import datetime, timedelta, timezone
import pytz 

# Selenium Imports
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from webdriver_manager.chrome import ChromeDriverManager
from selenium_stealth import stealth

# ===== CONFIGURATION =====
TELEGRAM_TOKEN = "7649050168:AAHNIYnrHzLOTcjNuMpeKgyUbfJB9x9an3c"
CHAT_ID = "876384974"

# Singapore Timezone
SGT_TZ = timezone(timedelta(hours=8))
now = datetime.now(SGT_TZ)

# ===== PAIR MAPPING =====
TARGET_PAIRS = {
    "AUDCAD": "AUDCAD=X", "AUDCHF": "AUDCHF=X", "AUDJPY": "AUDJPY=X", 
    "AUDNZD": "AUDNZD=X", "AUDUSD": "AUDUSD=X",
    "CADCHF": "CADCHF=X", "CADJPY": "CADJPY=X",
    "CHFJPY": "CHFJPY=X",
    "EURAUD": "EURAUD=X", "EURCAD": "EURCAD=X", "EURCHF": "EURCHF=X", 
    "EURGBP": "EURGBP=X", "EURJPY": "EURJPY=X", "EURNZD": "EURNZD=X", "EURUSD": "EURUSD=X",
    "GBPAUD": "GBPAUD=X", "GBPCAD": "GBPCAD=X", "GBPCHF": "GBPCHF=X", 
    "GBPJPY": "GBPJPY=X", "GBPNZD": "GBPNZD=X", "GBPUSD": "GBPUSD=X",
    "NZDCAD": "NZDCAD=X", "NZDCHF": "NZDCHF=X", "NZDJPY": "NZDJPY=X", "NZDUSD": "NZDUSD=X",
    "USDCAD": "USDCAD=X", "USDCHF": "USDCHF=X", "USDJPY": "USDJPY=X"
}

# ===== HELPER: TIME CONVERTER (FIXED) =====
def convert_to_sgt(time_str, date_str):
    """
    Converts ForexFactory time (US Est) to SGT.
    Handles 'Sun\nJan 12' format issues.
    """
    try:
        # 1. Clean Inputs
        if not time_str or "Day" in time_str or "Tentative" in time_str:
            return time_str 
        
        # Remove newlines from date (Crucial Fix)
        clean_date = date_str.replace('\n', ' ').strip()
        
        # Capitalize PM/AM for parser
        clean_time = time_str.upper() 
        
        # 2. Construct Full String
        current_year = datetime.now().year
        full_str = f"{clean_date} {current_year} {clean_time}"
        
        # 3. Define Timezones
        ny_tz = pytz.timezone('US/Eastern')
        sg_tz = pytz.timezone('Asia/Singapore')
        
        # 4. Parse & Convert
        # Format: "Sun Jan 12 2026 7:30PM"
        dt_obj = datetime.strptime(full_str, "%a %b %d %Y %I:%M%p")
        
        dt_ny = ny_tz.localize(dt_obj)
        dt_sg = dt_ny.astimezone(sg_tz)
        
        # Format output: "08:30 (13 Jan)"
        # We add date if it crosses midnight, but for brevity let's just show time
        return dt_sg.strftime("%H:%M")
        
    except Exception as e:
        # print(f"Time Parse Error: {e}") # Debug only
        return time_str # Fallback

# ===== 1. SCRAPER: CB RATES =====
def scrape_cb_rates():
    print("🕷️ Scraping Central Bank rates...")
    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)
    
    driver = None
    try:
        driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
        stealth(driver,
            languages=["en-US", "en"],
            vendor="Google Inc.",
            platform="Win32",
            webgl_vendor="Intel Inc.",
            renderer="Intel Iris OpenGL Engine",
            fix_hairline=True,
        )

        driver.get("https://www.investing.com/central-banks/")
        time.sleep(15) 
        
        rates = {}
        name_map = {
            "Federal Reserve": "Fed", "European Central Bank": "ECB",
            "Bank of England": "BoE", "Bank of Japan": "BoJ",
            "Bank of Canada": "BoC", "Reserve Bank of Australia": "RBA",
            "Reserve Bank of New Zealand": "RBNZ", "Swiss National Bank": "SNB"
        }

        # Investing.com Column Fix: Flag[0], Name[1], Rate[2]
        rows = driver.find_elements(By.CSS_SELECTOR, "table#curr_table tbody tr")
        if not rows:
            rows = driver.find_elements(By.CSS_SELECTOR, "table.genTbl tbody tr")

        for row in rows:
            cols = row.find_elements(By.TAG_NAME, "td")
            if len(cols) >= 3:
                raw_text = cols[1].text.strip()
                if not raw_text: raw_text = cols[0].text.strip()
                clean_name = raw_text.split('(')[0].strip()
                rate_val = cols[2].text.strip()

                if clean_name in name_map:
                    rates[name_map[clean_name]] = rate_val

        if not rates: return None
        return rates

    except Exception as e:
        print(f"⚠️ CB Scraping Failed: {e}")
        return None
    finally:
        if driver: driver.quit()

# ===== 2. SCRAPER: FOREX FACTORY (SGT) =====
def scrape_forex_factory():
    print("📅 Scraping ForexFactory (SGT)...")
    url = "https://www.forexfactory.com/calendar"
    
    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)
    options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

    driver = None
    releases = []
    
    try:
        driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
        stealth(driver,
            languages=["en-US", "en"],
            vendor="Google Inc.",
            platform="Win32",
            webgl_vendor="Intel Inc.",
            renderer="Intel Iris OpenGL Engine",
            fix_hairline=True,
        )

        driver.get(url)
        time.sleep(8) 
        
        rows = driver.find_elements(By.CSS_SELECTOR, "tr.calendar__row")
        current_date_str = ""
        last_valid_time = "" 
        
        for row in rows:
            try:
                # 1. Date Header
                if "new-day" in row.get_attribute("class"):
                    date_ele = row.find_element(By.CSS_SELECTOR, "td.calendar__date span")
                    current_date_str = date_ele.text.strip()
                    last_valid_time = "" # Reset
                    continue

                # 2. Red Impact Filter
                is_red = row.find_elements(By.CSS_SELECTOR, ".icon--ff-impact-red")
                if not is_red:
                    continue 

                # 3. Time Logic (Fill Down)
                time_ele = row.find_element(By.CSS_SELECTOR, "td.calendar__time")
                raw_time = time_ele.text.strip()
                
                if raw_time and raw_time != "":
                    last_valid_time = raw_time
                
                # 4. Convert to SGT
                final_time_sgt = convert_to_sgt(last_valid_time, current_date_str)

                # 5. Extract Details
                currency = row.find_element(By.CSS_SELECTOR, "td.calendar__currency").text.strip()
                event = row.find_element(By.CSS_SELECTOR, "span.calendar__event-title").text.strip()
                act = row.find_element(By.CSS_SELECTOR, "td.calendar__actual").text.strip()
                cons = row.find_element(By.CSS_SELECTOR, "td.calendar__forecast").text.strip()
                prev = row.find_element(By.CSS_SELECTOR, "td.calendar__previous").text.strip()

                flag_map = {"USD":"🇺🇸", "EUR":"🇪🇺", "GBP":"🇬🇧", "JPY":"🇯🇵", "CAD":"🇨🇦", "AUD":"🇦🇺", "NZD":"🇳🇿", "CHF":"🇨🇭", "CNY":"🇨🇳"}

                releases.append({
                    "date": current_date_str.replace('\n', ' '), # Clean date for display
                    "flag": flag_map.get(currency, "🌍"),
                    "title": f"{currency} {event}",
                    "time": final_time_sgt, # SGT Time
                    "act": act if act else "-",
                    "cons": cons if cons else "-",
                    "prev": prev if prev else "-"
                })
            except:
                continue
        return releases

    except Exception as e:
        print(f"⚠️ FF Scraping Failed: {e}")
        return None
    finally:
        if driver: driver.quit()

# ===== 3. FX DATA (yfinance) =====
def fetch_fx_data():
    print("⏳ Fetching FX data...")
    tickers = list(TARGET_PAIRS.values())
    data = yf.download(tickers, period="1mo", progress=False)
    closes = data['Close']
    results = {}
    for pair, ticker in TARGET_PAIRS.items():
        if ticker in closes.columns:
            series = closes[ticker].dropna()
            if len(series) >= 6:
                curr = series.iloc[-1]
                p_day = series.iloc[-2]
                p_week = series.iloc[-6] 
                is_jpy = "JPY" in pair
                mult = 100 if is_jpy else 10000
                results[pair] = {
                    "price": curr,
                    "dd": int((curr - p_day) * mult),
                    "ww": int((curr - p_week) * mult),
                    "is_jpy": is_jpy
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

# ===== 4. EXECUTION =====
fx_results = fetch_fx_data()
scraped_rates = scrape_cb_rates()
calendar_events = scrape_forex_factory()
base_movers = calculate_base_movers(fx_results)

rates_outlook = {
    "Fed":  ["🔴⬇️65%", "🟡➡️35%", "22 Feb 26"],
    "ECB":  ["🔴⬇️45%", "🟡➡️55%", "08 Mar 26"],
    "BoE":  ["🔴⬇️30%", "🟢⬆️15%", "20 Mar 26"],
    "BoJ":  ["🔴⬇️20%", "🟢⬆️30%", "10 Mar 26"],
    "SNB":  ["🔴⬇️55%", "🟡➡️45%", "16 Mar 26"],
    "RBA":  ["🟢⬆️40%", "🟡➡️60%", "05 Mar 26"],
    "BoC":  ["🔴⬇️35%", "🟡➡️65%", "11 Mar 26"],
    "RBNZ": ["🔴⬇️25%", "🟢⬆️20%", "03 Mar 26"]
}

# ===== BUILD MESSAGE =====
lines = [f"📊 *G8 FX Update* — {now.strftime('%H:%M')} SGT\n"]

# 1. Top Movers
lines.append("🔥 *Top Movers (Base Index)*")
sorted_movers = sorted(base_movers.items(), key=lambda x: abs(x[1][0]), reverse=True)
for curr, vals in sorted_movers:
    lines.append(f"{curr}: {vals[0]:+} pips d/d | {vals[1]:+} w/w")

lines.append("\n---")

# 2. FX Pairs
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
        lines.append("\n".join(seg))
        lines.append("")

lines.append("---")

# 3. Economic Releases
lines.append("📅 *ForexFactory: High Impact (Weekly SGT)*")

if calendar_events is None:
    lines.append("⚠️ _Scraper Error / Blocked_")
elif not calendar_events:
    lines.append("_No Red Impact events found this week._")
else:
    for e in calendar_events:
        # Format: [Sun Jan 12] 🇺🇸 USD CPI | 20:30
        lines.append(f"[{e['date']}] {e['flag']} {e['title']} | {e['time']}")
        if e['act'] != "-" or e['cons'] != "-":
            lines.append(f"   Act: {e['act']} | C: {e['cons']} | P: {e['prev']}")

lines.append("\n---")

# 4. Central Banks
lines.append("🏛 *Central Bank Policy Rates*")
cb_order = ["Fed", "ECB", "BoE", "BoJ", "BoC", "RBA", "RBNZ", "SNB"]

if scraped_rates:
    for bank in cb_order:
        rate = scraped_rates.get(bank, "N/A")
        lines.append(f"{bank}: {rate}")
else:
    lines.append("⚠️ _Fetch Failed - Investing.com Blocked_")

lines.append("\n---")

# 5. Rates Outlook
lines.append("🔮 *Rates Outlook*")
for bank, outlook in rates_outlook.items():
    lines.append(f"{bank}: {outlook[0]} | {outlook[1]} | {outlook[2]}")

message = "\n".join(lines)

# Send
try:
    requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", 
                  data={"chat_id": CHAT_ID, "text": message, "parse_mode": "Markdown"})
    print("✅ Sent to Telegram")
except Exception as e:
    print(f"❌ Error: {e}")
