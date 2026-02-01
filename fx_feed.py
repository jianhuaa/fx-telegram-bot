import time
import requests
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

SGT = timezone(timedelta(hours=8))
now = datetime.now(SGT)

# ===== PAIR MAPPING =====
TARGET_PAIRS = {
    "AUDCAD": "AUDCAD=X", "AUDCHF": "AUDCHF=X", "AUDJPY": "AUDJPY=X", "AUDNZD": "AUDNZD=X", "AUDUSD": "AUDUSD=X",
    "CADCHF": "CADCHF=X", "CADJPY": "CADJPY=X",
    "CHFJPY": "CHFJPY=X",
    "EURAUD": "EURAUD=X", "EURCAD": "EURCAD=X", "EURCHF": "EURCHF=X", "EURGBP": "EURGBP=X", "EURJPY": "EURJPY=X", "EURNZD": "EURNZD=X", "EURUSD": "EURUSD=X",
    "GBPAUD": "GBPAUD=X", "GBPCAD": "GBPCAD=X", "GBPCHF": "GBPCHF=X", "GBPJPY": "GBPJPY=X", "GBPNZD": "GBPNZD=X", "GBPUSD": "GBPUSD=X",
    "NZDCAD": "NZDCAD=X", "NZDCHF": "NZDCHF=X", "NZDJPY": "NZDJPY=X", "NZDUSD": "NZDUSD=X",
    "USDCAD": "USDCAD=X", "USDCHF": "USDCHF=X", "USDJPY": "USDJPY=X"
}

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

# ===== HELPER: SETUP DRIVER =====
def setup_driver():
    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)
    
    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
    
    stealth(driver,
        languages=["en-US", "en"],
        vendor="Google Inc.",
        platform="Win32",
        webgl_vendor="Intel Inc.",
        renderer="Intel Iris OpenGL Engine",
        fix_hairline=True,
    )
    return driver

# ===== 1. SCRAPER: CENTRAL BANKS (FIXED) =====
def scrape_cb_rates():
    print("🕷️ Scraping Central Bank rates...")
    driver = None
    try:
        driver = setup_driver()
        driver.get("https://www.investing.com/central-banks/")
        
        # Wait for table to be visible
        WebDriverWait(driver, 20).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "table#curr_table"))
        )
        
        rates = {}
        # Mapping Investing.com names to your output keys
        name_map = {
            "Federal Reserve": "Fed", "European Central Bank": "ECB",
            "Bank of England": "BoE", "Bank of Japan": "BoJ",
            "Bank of Canada": "BoC", "Reserve Bank of Australia": "RBA",
            "Reserve Bank of New Zealand": "RBNZ", "Swiss National Bank": "SNB"
        }

        # Select all rows in the specific table
        rows = driver.find_elements(By.CSS_SELECTOR, "table#curr_table tbody tr")
        
        for row in rows:
            try:
                cols = row.find_elements(By.TAG_NAME, "td")
                if len(cols) < 3: continue

                # Name is in Col 1 (index 1) -> "Federal Reserve (FED)"
                raw_name = cols[1].text.strip()
                # Rate is in Col 2 (index 2) -> "3.75%"
                rate_val = cols[2].text.strip()
                
                # Clean name: "Federal Reserve (FED)" -> "Federal Reserve"
                clean_name = raw_name.split('(')[0].strip()

                if clean_name in name_map:
                    rates[name_map[clean_name]] = rate_val
            except Exception as e:
                continue

        return rates

    except Exception as e:
        print(f"⚠️ CB Scraping Failed: {e}")
        return None
    finally:
        if driver: driver.quit()

# ===== 2. SCRAPER: FOREX FACTORY (FIXED DATE & IMPACT) =====
def scrape_forex_factory():
    print("📅 Scraping ForexFactory...")
    url = "https://www.forexfactory.com/calendar"
    driver = None
    releases = []
    
    try:
        driver = setup_driver()
        driver.get(url)
        time.sleep(5) # Let Cloudflare/JS settle

        # Explicitly wait for the calendar table
        WebDriverWait(driver, 20).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "table.calendar__table"))
        )
        
        rows = driver.find_elements(By.CSS_SELECTOR, "tr.calendar__row")
        current_date_str = "Unknown Date"
        
        for row in rows:
            try:
                row_class = row.get_attribute("class")

                # 1. Detect Date Breaker Row (e.g., "Sun Feb 1")
                if "calendar__row--day-breaker" in row_class:
                    # The text inside is usually just the date
                    current_date_str = row.text.strip()
                    continue

                # 2. Skip spacer/empty rows
                if "calendar__row--no-event" in row_class:
                    continue

                # 3. Check Impact
                # We look for the span inside td.calendar__impact
                impact_spans = row.find_elements(By.CSS_SELECTOR, "td.calendar__impact span.icon")
                if not impact_spans:
                    continue
                
                impact_class = impact_spans[0].get_attribute("class")
                
                # Filter: Only Red Impact
                if "impact-red" in impact_class:
                    
                    currency = row.find_element(By.CSS_SELECTOR, "td.calendar__currency").text.strip()
                    event = row.find_element(By.CSS_SELECTOR, "span.calendar__event-title").text.strip()
                    time_str = row.find_element(By.CSS_SELECTOR, "td.calendar__time").text.strip()
                    
                    act = row.find_element(By.CSS_SELECTOR, "td.calendar__actual").text.strip()
                    cons = row.find_element(By.CSS_SELECTOR, "td.calendar__forecast").text.strip()
                    prev = row.find_element(By.CSS_SELECTOR, "td.calendar__previous").text.strip()

                    flag_map = {"USD":"🇺🇸", "EUR":"🇪🇺", "GBP":"🇬🇧", "JPY":"🇯🇵", "CAD":"🇨🇦", "AUD":"🇦🇺", "NZD":"🇳🇿", "CHF":"🇨🇭", "CNY":"🇨🇳"}

                    releases.append({
                        "date": current_date_str,
                        "flag": flag_map.get(currency, "🌍"),
                        "title": f"{currency} {event}",
                        "time": time_str,
                        "act": act if act else "-",
                        "cons": cons if cons else "-",
                        "prev": prev if prev else "-"
                    })
            
            except Exception as row_e:
                # Silently skip malformed rows
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
    
    # Using threads to speed up yf download if needed, but standard is fine
    data = yf.download(tickers, period="1mo", progress=False)
    
    # Handle MultiIndex columns if yfinance returns them
    if isinstance(data.columns, pd.MultiIndex):
        closes = data.xs('Close', level=0, axis=1)
    else:
        closes = data['Close']
    
    results = {}
    for pair, ticker in TARGET_PAIRS.items():
        if ticker in closes.columns:
            series = closes[ticker].dropna()
            if len(series) >= 6:
                curr = float(series.iloc[-1])
                p_day = float(series.iloc[-2])
                p_week = float(series.iloc[-6]) 
                
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
# Need to import pandas for the yfinance fix above
import pandas as pd

fx_results = fetch_fx_data()
scraped_rates = scrape_cb_rates()
calendar_events = scrape_forex_factory()
base_movers = calculate_base_movers(fx_results)

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
lines.append("📅 *ForexFactory: High Impact (Weekly)*")

if calendar_events is None:
    lines.append("⚠️ _Scraper Error / Blocked_")
elif not calendar_events:
    lines.append("_No Red Impact events found (Market Closed?)_")
else:
    count = 0
    for e in calendar_events:
        if count >= 15: # Increased limit slightly 
            lines.append("... _(More events truncated)_")
            break
        lines.append(f"[{e['date']}] {e['flag']} {e['title']} | {e['time']}")
        if e['act'] != "-" or e['cons'] != "-":
            lines.append(f"   Act: {e['act']} | C: {e['cons']} | P: {e['prev']}")
        count += 1

lines.append("\n---")

# 4. Central Banks (Strict)
lines.append("🏛 *Central Bank Policy Rates*")
cb_order = ["Fed", "ECB", "BoE", "BoJ", "BoC", "RBA", "RBNZ", "SNB"]

if scraped_rates:
    for bank in cb_order:
        rate = scraped_rates.get(bank, "N/A")
        lines.append(f"{bank}: {rate}")
else:
    lines.append("⚠️ _Fetch Failed - Check Table Layout_")

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
