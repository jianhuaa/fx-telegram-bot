import time
import requests
import pandas as pd
import yfinance as yf
from bs4 import BeautifulSoup
from datetime import datetime, timedelta, timezone

# Selenium Imports (Kept for ForexFactory dynamic scrolling)
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

# Probabilities are static/manual for now, but Dates will be dynamic
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

# ===== NEW SCRAPERS (CBRates.com) =====

def scrape_cbrates_current():
    print("🏛️ Scraping Current Rates (cbrates.com)...")
    url = "https://www.cbrates.com/"
    rates = {}
    
    # Mapping cbrates.com country names to our codes
    # Note: Keys must match the text found on cbrates.com exactly
    country_map = {
        "United States": "Fed",
        "Euro Area": "ECB",
        "Eurozone": "ECB", # Fallback
        "Britain": "BoE",
        "United Kingdom": "BoE", # Fallback
        "Japan": "BoJ",
        "Canada": "BoC",
        "Australia": "RBA",
        "New Zealand": "RBNZ",
        "Switzerland": "SNB"
    }

    try:
        r = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'})
        soup = BeautifulSoup(r.text, 'html.parser')
        
        # Finding the main table (usually standard table class or just the first big one)
        # cbrates usually has a table with flag images
        rows = soup.find_all('tr')
        
        for row in rows:
            text = row.get_text(" ", strip=True)
            
            for country, code in country_map.items():
                if country in text:
                    # Found a row. Now find the rate percentage.
                    # Logic: Look for the last '%' in the row, or handle US range.
                    cells = row.find_all('td')
                    if len(cells) < 2: continue
                    
                    # Extract text from the cell that likely holds the rate (usually last or 2nd)
                    # We grab all text in row and look for % patterns
                    row_text = row.get_text()
                    
                    # Special Logic for US Fed "3.50 - 3.75"
                    if code == "Fed" and "-" in row_text:
                        # Extract the range, take the second number
                        # Example: "United States USD 3.50 - 3.75"
                        try:
                            # Split by hyphen, take the part after it
                            parts = row_text.split('-')
                            # The higher number is in the last part (e.g. " 3.75")
                            # We need to clean it of extra text
                            high_part = parts[-1].replace('%', '').strip()
                            # Sometimes it might have extra chars, extract float
                            import re
                            match = re.search(r"(\d+\.\d+)", high_part)
                            if match:
                                rates[code] = f"{match.group(1)}%"
                            else:
                                rates[code] = high_part + "%"
                        except:
                            pass
                    else:
                        # Standard Logic: Find the % value
                        import re
                        # Find all numbers like 4.25 or 0.10
                        matches = re.findall(r"(\d+\.\d{2})", row_text)
                        if matches:
                            # Usually the rate is the first distinct number associated with the country
                            # But cbrates lists Previous | Current sometimes. 
                            # We assume the table shows current.
                            rates[code] = f"{matches[0]}%"
                    
                    # Break loop for this row if found to avoid double matching
                    if code in rates: break
                    
        return rates

    except Exception as e:
        print(f"⚠️ CBRates Rates Failed: {e}")
        return None

def scrape_cbrates_meetings():
    print("🗓️ Scraping Meeting Dates (cbrates.com/meetings)...")
    url = "https://www.cbrates.com/meetings.htm"
    meetings = {}
    
    country_map = {
        "United States": "Fed",
        "Euro Area": "ECB",
        "Eurozone": "ECB",
        "Britain": "BoE",
        "United Kingdom": "BoE",
        "Japan": "BoJ",
        "Canada": "BoC",
        "Australia": "RBA",
        "New Zealand": "RBNZ",
        "Switzerland": "SNB"
    }

    try:
        r = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'})
        soup = BeautifulSoup(r.text, 'html.parser')
        
        # The meetings page is usually a list of rows with Country | Date
        rows = soup.find_all('tr')
        
        for row in rows:
            row_text = row.get_text(" ", strip=True)
            
            for country, code in country_map.items():
                if country in row_text:
                    # We found the country. Now extract the date.
                    # cbrates meetings format is typically: "United States : Dec 18, 2025"
                    # We look for the date pattern.
                    import re
                    # Regex for "Mmm DD, YYYY" or "DD Mmm YYYY"
                    # cbrates often uses "Dec 18" or "Dec 18, 2025"
                    
                    # Clean out the country name to leave the date
                    date_text = row_text.replace(country, "").replace(":", "").strip()
                    
                    # Basic cleanup
                    if date_text:
                         # Store specifically if it looks like a date (contains a month)
                         months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
                         if any(m in date_text for m in months):
                             meetings[code] = date_text
                             break # Found

        return meetings

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
        
        # Scroll to load dynamic content
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
            # Only get high impact (Red) events
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
        return releases
    except Exception as e:
        print(f"⚠️ FF Scraping Failed: {e}"); return None
    finally:
        if driver: driver.quit()

# ===== CALCULATIONS =====
def fetch_fx_data():
    tickers = list(TARGET_PAIRS.values())
    # Downloading data
    data = yf.download(tickers, period="1mo", progress=False)
    
    # Handle MultiIndex columns (yfinance structure changes frequently)
    if isinstance(data.columns, pd.MultiIndex):
        try:
            # Try to get Close prices. If 'Close' is level 0
            closes = data.xs('Close', level=0, axis=1)
        except KeyError:
             # Fallback if structure is different (e.g. Ticker as level 0)
             closes = data['Close']
    else:
        closes = data['Close']
        
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
        if e['act'] != "-": lines.append(f"    Act: {e['act']} | C: {e['cons']} | P: {e['prev']}")
else: lines.append("No high impact events today.")

lines.append("\n---")
lines.append("🏛 *Central Bank Policy Rates*")
if scraped_rates:
    # Preferred order of display
    order = ["Fed", "ECB", "BoE", "BoJ", "SNB", "RBA", "BoC", "RBNZ"]
    for bank in order:
        rate = scraped_rates.get(bank, "N/A")
        lines.append(f"{bank}: {rate}")
else: 
    lines.append("⚠️ _Scraping Failed_")

lines.append("\n🔮 *Rates Outlook*")
# Merge static probabilities with dynamic dates
order = ["Fed", "ECB", "BoE", "BoJ", "SNB", "RBA", "BoC", "RBNZ"]
for bank in order:
    probs = base_outlook.get(bank, ["-", "-"])
    # Get dynamic date if available, else placeholder
    date_str = scraped_meetings.get(bank, "TBA")
    lines.append(f"{bank}: {probs[0]} | {probs[1]} | {date_str}")

# Send
print("Sending to Telegram...")
try:
    response = requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", 
                             data={"chat_id": CHAT_ID, "text": "\n".join(lines), "parse_mode": "Markdown"})
    print(f"Status Code: {response.status_code}")
except Exception as e:
    print(f"Error sending message: {e}")
