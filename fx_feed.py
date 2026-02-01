import time
import requests
import pandas as pd
import yfinance as yf
from datetime import datetime, timedelta, timezone

# Selenium Imports
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait, Select
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
    "CADCHF": "CADCHF=X", "CADJPY": "CADJPY=X", "CHFJPY": "CHFJPY=X",
    "EURAUD": "EURAUD=X", "EURCAD": "EURCAD=X", "EURCHF": "EURCHF=X", "EURGBP": "EURGBP=X", "EURJPY": "EURJPY=X", "EURNZD": "EURNZD=X", "EURUSD": "EURUSD=X",
    "GBPAUD": "GBPAUD=X", "GBPCAD": "GBPCAD=X", "GBPCHF": "GBPCHF=X", "GBPJPY": "GBPJPY=X", "GBPNZD": "GBPNZD=X", "GBPUSD": "GBPUSD=X",
    "NZDCAD": "NZDCAD=X", "NZDCHF": "NZDCHF=X", "NZDJPY": "NZDJPY=X", "NZDUSD": "NZDUSD=X",
    "USDCAD": "USDCAD=X", "USDCHF": "USDCHF=X", "USDJPY": "USDJPY=X"
}

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
    options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36")
    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
    stealth(driver, languages=["en-US", "en"], vendor="Google Inc.", platform="Win32", webgl_vendor="Intel Inc.", renderer="Intel Iris OpenGL Engine", fix_hairline=True)
    return driver

# New function to force SGT Timezone on the website
def set_forexfactory_timezone(driver):
    print("🕒 Setting ForexFactory timezone to SGT (GMT+8)...")
    try:
        driver.get("https://www.forexfactory.com/timezone")
        time.sleep(2)
        # Find the timezone dropdown
        tz_dropdown = Select(driver.find_element(By.NAME, "timezone"))
        # We look for GMT+8. Note: FF value strings can be specific, using visible text is safer.
        tz_dropdown.select_by_visible_text("(GMT+8:00) Beijing, Perth, Singapore, Hong Kong")
        
        # Click Save Settings
        save_btn = driver.find_element(By.CSS_SELECTOR, "input.submit")
        save_btn.click()
        time.sleep(2)
        print("✅ Timezone saved.")
    except Exception as e:
        print(f"⚠️ Failed to set timezone: {e}")

# ===== SCRAPERS =====
def scrape_cb_rates():
    print("🕷️ Scraping Central Bank rates...")
    driver = None
    try:
        driver = setup_driver()
        driver.get("https://www.investing.com/central-banks/")
        WebDriverWait(driver, 30).until(EC.presence_of_element_located((By.XPATH, "//a[contains(@href, 'federal-reserve')]")))
        
        rates = {}
        name_map = {"Federal Reserve": "Fed", "European Central Bank": "ECB", "Bank of England": "BoE", "Bank of Japan": "BoJ", "Bank of Canada": "BoC", "Reserve Bank of Australia": "RBA", "Reserve Bank of New Zealand": "RBNZ", "Swiss National Bank": "SNB"}

        rows = driver.find_elements(By.CSS_SELECTOR, "table#curr_table tbody tr")
        for row in rows:
            cols = row.find_elements(By.TAG_NAME, "td")
            if len(cols) < 3: continue
            for full_name, short_name in name_map.items():
                if full_name in row.text:
                    rates[short_name] = cols[2].text.strip()
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
        
        # Step 1: Fix the Timezone
        set_forexfactory_timezone(driver)
        
        # Step 2: Load the calendar
        driver.get("https://www.forexfactory.com/calendar?week=this")
        
        # Step 3: Lazy-load scroll
        for i in range(1, 7):
            driver.execute_script(f"window.scrollTo(0, document.body.scrollHeight * {i/6});")
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
            if not impact or "icon--ff-impact-red" not in impact[0].get_attribute("class"):
                continue

            try:
                currency = row.find_element(By.CSS_SELECTOR, "td.calendar__currency").text.strip()
                event = row.find_element(By.CSS_SELECTOR, "span.calendar__event-title").text.strip()
                time_str = row.find_element(By.CSS_SELECTOR, "td.calendar__time").text.strip()
                
                if not time_str: time_str = last_valid_time
                else: last_valid_time = time_str
                
                # We no longer need the 'convert_time_to_sgt' math if the website is already in GMT+8!
                # We just take the string as it appears.
                actual_time = time_str if time_str else "N/A"
                
                act = row.find_element(By.CSS_SELECTOR, "td.calendar__actual").text.strip()
                cons = row.find_element(By.CSS_SELECTOR, "td.calendar__forecast").text.strip()
                prev = row.find_element(By.CSS_SELECTOR, "td.calendar__previous").text.strip()

                flag_map = {"USD":"🇺🇸", "EUR":"🇪🇺", "GBP":"🇬🇧", "JPY":"🇯🇵", "CAD":"🇨🇦", "AUD":"🇦🇺", "NZD":"🇳🇿", "CHF":"🇨🇭"}
                releases.append({
                    "date": current_date_str, "flag": flag_map.get(currency, "🌍"),
                    "title": f"{currency} {event}", "time_sgt": actual_time,
                    "act": act or "-", "cons": cons or "-", "prev": prev or "-"
                })
            except: continue
        return releases
    except Exception as e:
        print(f"⚠️ FF Scraping Failed: {e}"); return None
    finally:
        if driver: driver.quit()

# ===== REMAINING LOGIC =====
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

# EXECUTION
fx_results = fetch_fx_data()
scraped_rates = scrape_cb_rates()
calendar_events = scrape_forex_factory()
base_movers = calculate_base_movers(fx_results)

# Build Message
lines = [f"📊 *G8 FX Update* — {now_sgt.strftime('%H:%M')} SGT\n", "🔥 *Top Movers (Base Index)*"]
for curr, vals in sorted(base_movers.items()):
    lines.append(f"{curr}: {vals[0]:+} pips d/d | {vals[1]:+} w/w")

lines.append("\n---")
groups = {"AUD": ["AUDCAD", "AUDCHF", "AUDJPY", "AUDNZD", "AUDUSD"], "CAD": ["CADCHF", "CADJPY"], "CHF": ["CHFJPY"], "EUR": ["EURAUD", "EURCAD", "EURCHF", "EURGBP", "EURJPY", "EURNZD", "EURUSD"], "GBP": ["GBPAUD", "GBPCAD", "GBPCHF", "GBPJPY", "GBPNZD", "GBPUSD"], "NZD": ["NZDCAD", "NZDCHF", "NZDJPY", "NZDUSD"], "USD": ["USDCAD", "USDCHF", "USDJPY"]}

for base, pairs in groups.items():
    seg = [f"{pair} `{fx_results[pair]['price']:.2f}` {fx_results[pair]['dd']:+} d/d | {fx_results[pair]['ww']:+} w/w" if fx_results[pair]['is_jpy'] else f"{pair} `{fx_results[pair]['price']:.4f}` {fx_results[pair]['dd']:+} d/d | {fx_results[pair]['ww']:+} w/w" for pair in pairs if pair in fx_results]
    if seg: lines.append(f"*{base}*\n" + "\n".join(seg) + "\n")

lines.append("---")
lines.append("📅 *ForexFactory: High Impact (SGT)*")
if calendar_events:
    for e in calendar_events:
        lines.append(f"[{e['date']}] {e['flag']} {e['title']} | {e['time_sgt']}")
        if e['act'] != "-": lines.append(f"   Act: {e['act']} | C: {e['cons']} | P: {e['prev']}")
else: lines.append("⚠️ _Fetch Error (Lazy Load)_")

lines.append("\n---")
lines.append("🏛 *Central Bank Policy Rates*")
if scraped_rates:
    for bank in ["Fed", "ECB", "BoE", "BoJ", "SNB", "RBA", "BoC", "RBNZ"]:
        lines.append(f"{bank}: {scraped_rates.get(bank, 'N/A')}")
else: lines.append("⚠️ _Table Layout Changed_")

lines.append("\n🔮 *Rates Outlook*")
for bank, outlook in rates_outlook.items():
    lines.append(f"{bank}: {outlook[0]} | {outlook[1]} | {outlook[2]}")

# Send
requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", data={"chat_id": CHAT_ID, "text": "\n".join(lines), "parse_mode": "Markdown"})
