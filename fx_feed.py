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

# Futures Symbols for Implied Probability Logic
FUTURES_MAP = {
    "Fed": "ZQ*0",
    "BoE": "J8*0",
    "ECB": "IM*0",
    "BoC": "CRA*0",
    "RBNZ": "BF*0",
    "BoJ": "T0*0",
    "SNB": "J2*0",
    "RBA": "IR*0"
}

# ===== HELPERS =====
def setup_driver():
    """Detailed Selenium initialization with all original flags and stealth parameters."""
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
    
    # Force New York Timezone at the browser level to stabilize ET source
    driver.execute_cdp_cmd('Emulation.setTimezoneOverride', {'timezoneId': 'America/New_York'})
    
    stealth(driver, 
            languages=["en-US", "en"], 
            vendor="Google Inc.", 
            platform="Win32", 
            webgl_vendor="Intel Inc.", 
            renderer="Intel Iris OpenGL Engine", 
            fix_hairline=True)
    return driver

# ===== SCRAPERS =====

def scrape_cbrates_current():
    """Original robust regex scraper for CBRates policy levels."""
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
    """Original meeting date scraper with explicit monthly parsing."""
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

def scrape_barchart_outlook(driver, current_benchmarks):
    """Detailed Barchart scraper implementing the Implied Yield vs Benchmark math."""
    print("📈 Scraping Barchart Futures Outlook...")
    outlook_results = {}
    
    for bank, symbol in FUTURES_MAP.items():
        try:
            url = f"https://www.barchart.com/futures/quotes/{symbol}/overview"
            driver.get(url)
            
            # Wait for specific price element to render via JS
            wait = WebDriverWait(driver, 10)
            price_element = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "span.last-price")))
            
            price_text = price_element.text
            price = float(price_text.replace(',', ''))
            
            # MATH LOGIC:
            # 1. Implied Yield = 100 - Future Price
            # 2. Difference in Bps = (Implied Yield - Current Rate) * 100
            # 3. Probability % = (Bps Difference / 25) * 100
            
            implied_yield = 100.0 - price
            benchmark = current_benchmarks.get(bank, 0.0)
            
            diff_bps = (implied_yield - benchmark) * 100
            prob_pct = (diff_bps / 25.0) * 100
            
            # Logic: If implied is higher than benchmark = Hike probability (Green)
            if prob_pct > 0.5:
                status = f"🟢 ⬆️ {abs(int(prob_pct))}%"
            elif prob_pct < -0.5:
                status = f"🔴 ⬇️ {abs(int(prob_pct))}%"
            else:
                status = "🟡 ➡️ 0%"
                
            outlook_results[bank] = status
            time.sleep(1) # Small delay to avoid rate limiting
        except Exception as e:
            print(f"⚠️ Barchart Error for {bank} ({symbol}): {e}")
            outlook_results[bank] = "⚪ ➖ N/A"
            
    return outlook_results

def scrape_forex_factory(driver):
    """Original FF scraper with explicit date-breaker logic and red-impact filtering."""
    print("📅 Scraping ForexFactory (Today)...")
    releases = []
    try:
        driver.get("https://www.forexfactory.com/calendar?week=this")
        # Ensure full page load
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
                
            impact_els = row.find_elements(By.CSS_SELECTOR, "td.calendar__impact span.icon")
            if not impact_els: continue
            if "icon--ff-impact-red" not in impact_els[0].get_attribute("class"): continue
            
            try:
                currency = row.find_element(By.CSS_SELECTOR, "td.calendar__currency").text.strip()
                event = row.find_element(By.CSS_SELECTOR, "span.calendar__event-title").text.strip()
                time_str = row.find_element(By.CSS_SELECTOR, "td.calendar__time").text.strip()
                
                # Handling blank time slots (concurrent events)
                if not time_str: 
                    time_str = last_valid_time
                else: 
                    last_valid_time = time_str
                
                actual = row.find_element(By.CSS_SELECTOR, "td.calendar__actual").text.strip()
                forecast = row.find_element(By.CSS_SELECTOR, "td.calendar__forecast").text.strip()
                previous = row.find_element(By.CSS_SELECTOR, "td.calendar__previous").text.strip()
                
                flag_map = {"USD":"🇺🇸", "EUR":"🇪🇺", "GBP":"🇬🇧", "JPY":"🇯🇵", "CAD":"🇨🇦", "AUD":"🇦🇺", "NZD":"🇳🇿", "CHF":"🇨🇭"}
                
                releases.append({
                    "date": current_date_str,
                    "flag": flag_map.get(currency, "🌍"),
                    "title": f"{currency} {event}",
                    "time_et": time_str,
                    "act": actual or "-",
                    "cons": forecast or "-",
                    "prev": previous or "-"
                })
            except: continue
        return releases
    except Exception as e:
        print(f"⚠️ FF Scraping Failed: {e}"); return None

# ===== CALCULATIONS =====

def fetch_fx_data():
    """Detailed YFinance download and institutional NY cut pip calculation."""
    print("📈 Fetching FX Data (Institutional Anchor: 05:00 SGT)...")
    tickers = list(TARGET_PAIRS.values())
    
    # Download enough data to ensure the 05:00 SGT anchor points are captured
    data = yf.download(tickers, period="10d", interval="1h", progress=False)
    
    if isinstance(data.columns, pd.MultiIndex):
        closes = data.xs('Close', level=0, axis=1)
    else: 
        closes = data['Close']
    
    results = {}
    for pair, ticker in TARGET_PAIRS.items():
        if ticker in closes.columns:
            series = closes[ticker].dropna()
            if not series.empty:
                curr_price = float(series.iloc[-1])
                
                # Filtering for the 05:00 SGT candles (New York Close proxy)
                ny_cut_candles = series[series.index.hour == 5]
                
                if not ny_cut_candles.empty:
                    # Daily Anchor: Most recent NY Close
                    p_day = float(ny_cut_candles.iloc[-1])
                    # Weekly Anchor: First NY Close in the window
                    p_week = float(ny_cut_candles.iloc[0])
                else:
                    # Fallback if market just opened or data is sparse
                    p_day = float(series.iloc[0])
                    p_week = float(series.iloc[0])
                
                # Pip Multipliers
                multiplier = 100 if "JPY" in pair else 10000
                
                results[pair] = {
                    "price": curr_price, 
                    "dd": int((curr_price - p_day) * multiplier), 
                    "ww": int((curr_price - p_week) * multiplier), 
                    "is_jpy": "JPY" in pair
                }
    return results

def calculate_base_movers(fx_data):
    """Derives G8 base index movements from individual pair pip changes."""
    currencies = ["AUD", "CAD", "CHF", "EUR", "GBP", "NZD", "USD", "JPY"]
    movers = {}
    for c in currencies:
        dd_total, ww_total, count = 0, 0, 0
        for pair, vals in fx_data.items():
            if c in pair:
                # Factor determines if the currency is Base or Quote
                factor = 1 if pair.startswith(c) else -1
                dd_total += vals["dd"] * factor
                ww_total += vals["ww"] * factor
                count += 1
        if count > 0: 
            movers[c] = [int(dd_total / count), int(ww_total / count)]
    return movers

# ===== EXECUTION FLOW =====

# Start the single driver session
main_driver = setup_driver()

# Perform all scrapes using the same driver to maximize speed/stability
fx_stats = fetch_fx_data()
cb_current = scrape_cbrates_current() 
cb_dates = scrape_cbrates_meetings()
barchart_outlook = scrape_barchart_outlook(main_driver, cb_current)
econ_calendar = scrape_forex_factory(main_driver)
base_indices = calculate_base_movers(fx_stats)

# Close browser immediately after scraping is complete
main_driver.quit()

# ===== MESSAGE CONSTRUCTION =====

# Super Title with compact am/pm
msg_lines = [
    f"📊 <b>G8 FX Update</b> — {now_sgt.strftime('%I:%M%p').lower()} SGT / {now_et.strftime('%I:%M%p').lower()} ET\n", 
    "🔥 <b>Top Movers (Base Index)</b>"
]

for curr, values in sorted(base_indices.items()):
    msg_lines.append(f"{curr}: {values[0]:+} pips d/d | {values[1]:+} w/w")

# Detailed Crosses Vault
msg_lines.append("\n💰 <b>28 FX G8 Crosses</b>")
groups = {
    "AUD": ["AUDCAD", "AUDCHF", "AUDJPY", "AUDNZD", "AUDUSD"],
    "CAD": ["CADCHF", "CADJPY"],
    "CHF": ["CHFJPY"],
    "EUR": ["EURAUD", "EURCAD", "EURCHF", "EURGBP", "EURJPY", "EURNZD", "EURUSD"],
    "GBP": ["GBPAUD", "GBPCAD", "GBPCHF", "GBPJPY", "GBPNZD", "GBPUSD"],
    "NZD": ["NZDCAD", "NZDCHF", "NZDJPY", "NZDUSD"],
    "USD": ["USDCAD", "USDCHF", "USDJPY"]
}

crosses_block = []
for base_currency, pairs_list in groups.items():
    group_seg = [f"<b>{base_currency}</b>"]
    for p_name in pairs_list:
        if p_name in fx_stats:
            d_val = fx_stats[p_name]
            p_format = f"{d_val['price']:.2f}" if d_val['is_jpy'] else f"{d_val['price']:.4f}"
            group_seg.append(f"{p_name} <code>{p_format}</code> {d_val['dd']:+} d/d | {d_val['ww']:+} w/w")
    crosses_block.append("\n".join(group_seg))

msg_lines.append(f"<blockquote expandable>\n" + "\n\n".join(crosses_block) + "\n</blockquote>")

msg_lines.append("") # Blank space

# Economic Calendar (Strictly ET Source)
msg_lines.append("📅 <b>Economic Calendar (ET)</b>") 
if econ_calendar:
    cal_block = []
    for event in econ_calendar:
        e_line = f"[{event['date']}] {event['flag']} {event['title']} | {event['time_et']} ET"
        if event['act'] != "-": 
            e_line += f"\n   Act: {event['act']} | C: {event['cons']} | P: {event['prev']}"
        cal_block.append(e_line)
    msg_lines.append(f"<blockquote expandable>\n" + "\n".join(cal_block) + "\n</blockquote>")
else:
    msg_lines.append("<blockquote expandable>No high-impact events today.</blockquote>")

msg_lines.append("") # Blank space

# Institutional Outlook & Rates
msg_lines.append("🏛 <b>Central Bank Policy & Outlook</b>")
if cb_current:
    policy_block = []
    sort_order = ["RBA", "BoC", "SNB", "ECB", "BoE", "BoJ", "RBNZ", "Fed"]
    for bank_code in sort_order:
        current_rate = f"{cb_current.get(bank_code, 'N/A')}%"
        implied_bias = barchart_outlook.get(bank_code, "N/A")
        next_meeting = cb_dates.get(bank_code, "TBA")
        policy_block.append(f"{bank_code}: {current_rate} | {implied_bias} | {next_meeting}")
    msg_lines.append(f"<blockquote expandable>\n" + "\n".join(policy_block) + "\n</blockquote>")
else:
    msg_lines.append("<blockquote expandable>⚠️ Rates Scraper Offline</blockquote>")

# Final Post to Telegram API
print("Broadcasting to Telegram...")
try:
    final_payload = {
        "chat_id": CHAT_ID, 
        "text": "\n".join(msg_lines), 
        "parse_mode": "HTML", 
        "disable_web_page_preview": True
    }
    api_url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    broadcast_response = requests.post(api_url, json=final_payload)
    print(f"Broadcast Status: {broadcast_response.status_code}")
except Exception as broadcast_error:
    print(f"Transmission Error: {broadcast_error}")
