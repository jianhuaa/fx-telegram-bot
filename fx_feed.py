import os
import time
import requests
import numpy as np
import yfinance as yf
from datetime import datetime, timedelta, timezone

# Selenium Imports (For Scraping)
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from webdriver_manager.chrome import ChromeDriverManager
from selenium_stealth import stealth

# ===== CONFIGURATION =====
# ⚠️ HARDCODED CREDENTIALS (SECURITY RISK ACCEPTED BY USER)
TELEGRAM_TOKEN = "7649050168:AAHNIYnrHzLOTcjNuMpeKgyUbfJB9x9an3c"
CHAT_ID = "876384974"

# Timezone
SGT = timezone(timedelta(hours=8))
now = datetime.now(SGT)

# ===== USER DEFINED PAIR LIST =====
TARGET_PAIRS = {
    # AUD Group
    "AUDCAD": "AUDCAD=X", "AUDCHF": "AUDCHF=X", "AUDJPY": "AUDJPY=X", 
    "AUDNZD": "AUDNZD=X", "AUDUSD": "AUDUSD=X",
    # CAD Group
    "CADCHF": "CADCHF=X", "CADJPY": "CADJPY=X",
    # CHF Group
    "CHFJPY": "CHFJPY=X",
    # EUR Group
    "EURAUD": "EURAUD=X", "EURCAD": "EURCAD=X", "EURCHF": "EURCHF=X", 
    "EURGBP": "EURGBP=X", "EURJPY": "EURJPY=X", "EURNZD": "EURNZD=X", "EURUSD": "EURUSD=X",
    # GBP Group
    "GBPAUD": "GBPAUD=X", "GBPCAD": "GBPCAD=X", "GBPCHF": "GBPCHF=X", 
    "GBPJPY": "GBPJPY=X", "GBPNZD": "GBPNZD=X", "GBPUSD": "GBPUSD=X",
    # NZD Group
    "NZDCAD": "NZDCAD=X", "NZDCHF": "NZDCHF=X", "NZDJPY": "NZDJPY=X", "NZDUSD": "NZDUSD=X",
    # USD Group
    "USDCAD": "USDCAD=X", "USDCHF": "USDCHF=X", "USDJPY": "USDJPY=X"
}

# ===== MANUAL / STATIC SECTIONS =====
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

# ===== 1. SCRAPER (CENTRAL BANKS) - UNCHANGED =====
def scrape_cb_rates():
    print("🕷️ Attempting to scrape Central Bank rates...")
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
        time.sleep(15) # Wait for Cloudflare
        
        rates = {}
        name_map = {
            "Federal Reserve": "Fed", "European Central Bank": "ECB",
            "Bank of England": "BoE", "Bank of Japan": "BoJ",
            "Bank of Canada": "BoC", "Reserve Bank of Australia": "RBA",
            "Reserve Bank of New Zealand": "RBNZ", "Swiss National Bank": "SNB"
        }

        # Try selectors
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

        if not rates: raise ValueError("No rates found")
        return rates

    except Exception as e:
        print(f"⚠️ Scraping Failed: {e}")
        return None
    finally:
        if driver: driver.quit()

# ===== 2. SCRAPER (FOREX FACTORY CALENDAR) - NEW =====
def scrape_forex_factory():
    print("📅 Scraping ForexFactory (Weekly Red Impact)...")
    url = "https://www.forexfactory.com/calendar"
    
    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)
    # Anti-bot user agent
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
        
        for row in rows:
            try:
                # Handle Date Headers
                if "new-day" in row.get_attribute("class"):
                    date_ele = row.find_element(By.CSS_SELECTOR, "td.calendar__date span")
                    current_date_str = date_ele.text.strip()
                    continue

                # Filter Red Impact Only
                impact_ele = row.find_element(By.CSS_SELECTOR, "td.calendar__impact span")
                if "impact-red" not in impact_ele.get_attribute("class"):
                    continue

                # Extract Data
                currency = row.find_element(By.CSS_SELECTOR, "td.calendar__currency").text.strip()
                event = row.find_element(By.CSS_SELECTOR, "span.calendar__event-title").text.strip()
                time_str = row.find_element(By.CSS_SELECTOR, "td.calendar__time").text.strip()
                
                act = row.find_element(By.CSS_SELECTOR, "td.calendar__actual").text.strip()
                cons = row.find_element(By.CSS_SELECTOR, "td.calendar__forecast").text.strip()
                prev = row.find_element(By.CSS_SELECTOR, "td.calendar__previous").text.strip()

                flag_map = {
                    "USD": "🇺🇸", "EUR": "🇪🇺", "GBP": "🇬🇧", "JPY": "🇯🇵",
                    "CAD": "🇨🇦", "AUD": "🇦🇺", "NZD": "🇳🇿", "CHF": "🇨🇭", "CNY": "🇨🇳"
                }

                releases.append({
                    "date": current_date_str,
                    "flag": flag_map.get(currency, "🌍"),
                    "title": f"{currency} {event}",
                    "time": time_str,
                    "act": act if act else "-",
                    "cons": cons if cons else "-",
                    "prev": prev if prev else "-"
                })

            except Exception:
                continue
                
        return releases

    except Exception as e:
        print(f"⚠️ FF Scraping Failed: {e}")
        return []
    finally:
        if driver: driver.quit()

# ===== 3. FX DATA PROCESSING (yfinance) - UNCHANGED =====
def fetch_fx_data():
    print("⏳ Fetching FX data...")
    tickers = list(TARGET_PAIRS.values())
    
    data = yf.download(tickers, period="1mo", progress=False)
    closes = data['Close']
    
    results = {}
    
    for pair, ticker in TARGET_PAIRS.items():
        if ticker in closes.columns:
            series = closes[ticker].dropna()
            
            if len(series) < 5:
                continue

            curr_price = series.iloc[-1]
            prev_day = series.iloc[-2]
            prev_week = series.iloc[-6] 

            is_jpy = "JPY" in pair
            mult = 100 if is_jpy else 10000
            
            dd_pips = (curr_price - prev_day) * mult
            ww_pips = (curr_price - prev_week) * mult
            
            results[pair] = {
                "price": curr_price,
                "dd": int(dd_pips),
                "ww": int(ww_pips),
                "is_jpy": is_jpy
            }
            
    return results

def calculate_base_movers(fx_data):
    currencies = ["AUD", "CAD", "CHF", "EUR", "GBP", "NZD", "USD", "JPY"]
    movers = {}

    for curr in currencies:
        total_dd = 0
        total_ww = 0
        count = 0
        
        for pair, vals in fx_data.items():
            if curr not in pair: continue
            
            is_base = pair.startswith(curr)
            factor = 1 if is_base else -1
            
            total_dd += (vals["dd"] * factor)
            total_ww += (vals["ww"] * factor)
            count += 1
            
        if count > 0:
            movers[curr] = [int(total_dd / count), int(total_ww / count)]
            
    return movers

# ===== 4. MAIN EXECUTION =====
fx_results = fetch_fx_data()
scraped_rates = scrape_cb_rates()
calendar_events = scrape_forex_factory() # New Call

# Fallback Rates Logic (Unchanged)
final_rates = {
    "Fed": "5.50%", "ECB": "4.50%", "BoE": "5.25%", "BoJ": "-0.10%",
    "BoC": "5.00%", "RBA": "4.35%", "RBNZ": "5.50%", "SNB": "1.75%"
}
if scraped_rates and len(scraped_rates) > 3:
    final_rates = scraped_rates

# Calculate Movers
base_movers = calculate_base_movers(fx_results)

# ===== BUILD MESSAGE =====
lines = [f"📊 *G8 FX Update* — {now.strftime('%H:%M')} SGT\n"]

# 1. Top Movers
lines.append("🔥 *Top Movers (Base Index)*")
sorted_movers = sorted(base_movers.items(), key=lambda x: abs(x[1][0]), reverse=True)
for curr, vals in sorted_movers:
    lines.append(f"{curr}: {vals[0]:+} pips d/d | {vals[1]:+} w/w")

lines.append("\n---")

# 2. FX Pairs List
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
    segment_lines = []
    for pair in pairs:
        if pair in fx_results:
            d = fx_results[pair]
            price_fmt = f"{d['price']:.2f}" if d['is_jpy'] else f"{d['price']:.4f}"
            segment_lines.append(f"{pair} `{price_fmt}`  {d['dd']:+} d/d | {d['ww']:+} w/w")
    
    if segment_lines:
        lines.append(f"*{base}*")
        lines.append("\n".join(segment_lines))
        lines.append("")

lines.append("---")

# 3. Economic Releases (From Scraper)
lines.append("📅 *ForexFactory: High Impact (Weekly)*")

if calendar_events:
    count = 0
    for e in calendar_events:
        # Limit to 10 to avoid spam
        if count >= 10: 
            lines.append("... _(More events truncated)_")
            break
            
        # Format: [Sun Jan 12] 🇺🇸 USD CPI | 20:30
        lines.append(f"[{e['date']}] {e['flag']} {e['title']} | {e['time']}")
        # Add Data line if it exists
        if e['act'] != "-" or e['cons'] != "-":
            lines.append(f"   Act: {e['act']} | C: {e['cons']} | P: {e['prev']}")
        
        count += 1
else:
    lines.append("_No Red Impact events found (or Scraper Blocked)._")

lines.append("\n---")

# 4. Central Banks
lines.append("🏛 *Central Bank Policy Rates*")
cb_order = ["Fed", "ECB", "BoE", "BoJ", "BoC", "RBA", "RBNZ", "SNB"]
for bank in cb_order:
    rate = final_rates.get(bank, "N/A")
    lines.append(f"{bank}: {rate}")

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
