import os
import time
import requests
import numpy as np
import yfinance as yf
from datetime import datetime, timedelta, timezone

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

SGT = timezone(timedelta(hours=8))
now = datetime.now(SGT)

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

# ===== MANUAL SECTIONS =====
# You can update this manually if you want specific narrative control
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

# ===== 1. SCRAPER: FOREX FACTORY (WEEKLY VIEW) =====
def scrape_weekly_calendar():
    print("📅 Scraping ForexFactory (Weekly View)...")
    url = "https://www.forexfactory.com/calendar"
    
    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)

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
        
        # In weekly view, we need to track the current date header as we loop rows
        rows = driver.find_elements(By.CSS_SELECTOR, "tr.calendar__row")
        current_date_str = "Unknown Date"
        
        for row in rows:
            try:
                # Check if this row is a new Day Header
                # Class usually contains 'calendar__row--new-day'
                classes = row.get_attribute("class")
                if "new-day" in classes:
                    # Extract date text (e.g. "Sun Jan 12")
                    # Usually in the first column span
                    date_ele = row.find_element(By.CSS_SELECTOR, "td.calendar__date span")
                    current_date_str = date_ele.text.strip()
                    continue # It's just a header, move to next row

                # --- EXTENSIBILITY CHECK ---
                # This is where you filter.
                # To add Orange later, change to: if "red" in impact or "orange" in impact:
                impact_ele = row.find_element(By.CSS_SELECTOR, "td.calendar__impact span")
                impact_class = impact_ele.get_attribute("class")
                
                if "impact-red" not in impact_class:
                    continue # Skip low/med impact
                # ---------------------------

                # Extract Details
                currency = row.find_element(By.CSS_SELECTOR, "td.calendar__currency").text.strip()
                event = row.find_element(By.CSS_SELECTOR, "span.calendar__event-title").text.strip()
                time_str = row.find_element(By.CSS_SELECTOR, "td.calendar__time").text.strip()
                
                actual = row.find_element(By.CSS_SELECTOR, "td.calendar__actual").text.strip()
                forecast = row.find_element(By.CSS_SELECTOR, "td.calendar__forecast").text.strip()
                prev = row.find_element(By.CSS_SELECTOR, "td.calendar__previous").text.strip()

                # Flag Icon Logic
                flag_map = {
                    "USD": "🇺🇸", "EUR": "🇪🇺", "GBP": "🇬🇧", "JPY": "🇯🇵",
                    "CAD": "🇨🇦", "AUD": "🇦🇺", "NZD": "🇳🇿", "CHF": "🇨🇭", "CNY": "🇨🇳"
                }
                flag = flag_map.get(currency, "🌍")

                releases.append({
                    "date": current_date_str, # e.g. "Sun Jan 12"
                    "time": time_str,
                    "flag": flag,
                    "title": f"{currency} {event}",
                    "act": actual if actual else "-",
                    "cons": forecast if forecast else "-",
                    "prev": prev if prev else "-"
                })

            except Exception:
                continue
                
        return releases

    except Exception as e:
        print(f"⚠️ Calendar Scrape Failed: {e}")
        return []
    finally:
        if driver: driver.quit()

# ===== 2. SCRAPER: CENTRAL BANKS (STRICT) =====
def scrape_cb_rates():
    print("🕷️ Scraping Central Bank Rates...")
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

        rows = driver.find_elements(By.CSS_SELECTOR, "table#curr_table tbody tr")
        if not rows:
            rows = driver.find_elements(By.CSS_SELECTOR, "table.genTbl tbody tr")

        for row in rows:
            cols = row.find_elements(By.TAG_NAME, "td")
            if len(cols) >= 2:
                raw_name = cols[0].text.split('(')[0].strip()
                rate_val = cols[1].text.strip()
                if raw_name in name_map:
                    rates[name_map[raw_name]] = rate_val
        
        if not rates: return None
        return rates

    except Exception as e:
        print(f"⚠️ CB Scraping Failed: {e}")
        return None 
    finally:
        if driver: driver.quit()

# ===== 3. FX DATA (yfinance) =====
def fetch_fx_data():
    print("⏳ Fetching FX Data...")
    tickers = list(TARGET_PAIRS.values())
    
    data = yf.download(tickers, period="1mo", progress=False)
    closes = data['Close']
    
    results = {}
    for pair, ticker in TARGET_PAIRS.items():
        if ticker in closes.columns:
            series = closes[ticker].dropna()
            if len(series) >= 6:
                curr = series.iloc[-1]
                prev_day = series.iloc[-2]
                prev_week = series.iloc[-6] 
                
                is_jpy = "JPY" in pair
                mult = 100 if is_jpy else 10000
                
                results[pair] = {
                    "price": curr,
                    "dd": int((curr - prev_day) * mult),
                    "ww": int((curr - prev_week) * mult),
                    "is_jpy": is_jpy
                }
    return results

# ===== 4. CALCULATE BASE INDEX =====
def calculate_base_strength(fx_data):
    currencies = ["AUD", "CAD", "CHF", "EUR", "GBP", "NZD", "USD", "JPY"]
    movers = {}

    for curr in currencies:
        total_dd = 0
        total_ww = 0
        count = 0
        
        for pair, vals in fx_data.items():
            if curr not in pair: continue
            
            factor = 1 if pair.startswith(curr) else -1
            
            total_dd += (vals["dd"] * factor)
            total_ww += (vals["ww"] * factor)
            count += 1
            
        if count > 0:
            movers[curr] = [int(total_dd/count), int(total_ww/count)]
    return movers

# ===== 5. EXECUTION =====
fx_data = fetch_fx_data()
cb_rates = scrape_cb_rates()
base_movers = calculate_base_strength(fx_data)
calendar_events = scrape_weekly_calendar()

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
    seg_lines = []
    for pair in pairs:
        if pair in fx_data:
            d = fx_data[pair]
            p_fmt = f"{d['price']:.2f}" if d['is_jpy'] else f"{d['price']:.4f}"
            seg_lines.append(f"{pair} `{p_fmt}`  {d['dd']:+} d/d | {d['ww']:+} w/w")
    
    if seg_lines:
        lines.append(f"*{base}*")
        lines.append("\n".join(seg_lines))
        lines.append("")

lines.append("---")

# 3. Central Bank Rates
lines.append("🏛 *Central Bank Policy Rates*")
cb_list = ["Fed", "ECB", "BoE", "BoJ", "BoC", "RBA", "RBNZ", "SNB"]

if cb_rates:
    for bank in cb_list:
        val = cb_rates.get(bank, "N/A")
        lines.append(f"{bank}: {val}")
else:
    lines.append("⚠️ _Fetch Failed - Investing.com Blocked_")

lines.append("\n---")

# 4. Rates Outlook (Manual)
lines.append("🔮 *Rates Outlook*")
for bank, outlook in rates_outlook.items():
    lines.append(f"{bank}: {outlook[0]} | {outlook[1]} | {outlook[2]}")

lines.append("\n---")

# 5. Economic Calendar (Weekly Scraper Results)
lines.append("📅 *ForexFactory: High Impact (Weekly)*")

if calendar_events:
    # Limit to first 10 events to avoid spamming telegram if the list is huge
    count = 0
    for e in calendar_events:
        if count >= 10: 
            lines.append("... _(More events truncated)_")
            break
            
        # Format: [Sun Jan 12] 🇺🇸 USD CPI | 20:30
        lines.append(f"[{e['date']}] {e['flag']} {e['title']} | {e['time']}")
        # Add Data line if data exists
        if e['act'] != "-" or e['cons'] != "-":
            lines.append(f"   Act: {e['act']} | C: {e['cons']} | P: {e['prev']}")
        
        count += 1
else:
    lines.append("_No High Impact events found (or Scraper Blocked)._")

message = "\n".join(lines)

# Send
try:
    requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", 
                  data={"chat_id": CHAT_ID, "text": message, "parse_mode": "Markdown"})
    print("✅ Telegram Sent")
except Exception as e:
    print(f"❌ Telegram Error: {e}")
