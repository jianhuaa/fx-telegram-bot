import os
import time
import requests
import yfinance as yf
from datetime import datetime, timedelta, timezone

# Selenium Imports
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from webdriver_manager.chrome import ChromeDriverManager
from selenium_stealth import stealth

# ===== CONFIGURATION (HARDCODED) =====
TELEGRAM_TOKEN = "7649050168:AAHNIYnrHzLOTcjNuMpeKgyUbfJB9x9an3c"
CHAT_ID = "876384974"

# Singapore Time
SGT = timezone(timedelta(hours=8))
now = datetime.now(SGT)

# ===== 1. ROBUST SCRAPER (The "Live" Part) =====
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
        
        # Apply Stealth
        stealth(driver,
            languages=["en-US", "en"],
            vendor="Google Inc.",
            platform="Win32",
            webgl_vendor="Intel Inc.",
            renderer="Intel Iris OpenGL Engine",
            fix_hairline=True,
        )

        # 1. Go to target
        driver.get("https://www.investing.com/central-banks/")
        
        # 2. Wait for Cloudflare challenge to pass (Crucial)
        time.sleep(15)
        
        # 3. Scrape Table
        rates = {}
        # Mapping Investing.com names to your Short names
        name_map = {
            "Federal Reserve": "Fed", "European Central Bank": "ECB",
            "Bank of England": "BoE", "Bank of Japan": "BoJ",
            "Bank of Canada": "BoC", "Reserve Bank of Australia": "RBA",
            "Reserve Bank of New Zealand": "RBNZ", "Swiss National Bank": "SNB"
        }

        # Try multiple selectors in case they change the site layout
        rows = driver.find_elements(By.CSS_SELECTOR, "table#curr_table tbody tr")
        if not rows:
            rows = driver.find_elements(By.CSS_SELECTOR, "table.genTbl tbody tr")

        for row in rows:
            cols = row.find_elements(By.TAG_NAME, "td")
            if len(cols) >= 2:
                # Text is usually "Federal Reserve (Fed)"
                raw_name = cols[0].text.split('(')[0].strip()
                rate_val = cols[1].text.strip()
                
                if raw_name in name_map:
                    short_name = name_map[raw_name]
                    rates[short_name] = rate_val

        if not rates:
            raise ValueError("Table found but no rates extracted.")

        print("✅ Scraping Success!")
        return rates

    except Exception as e:
        print(f"⚠️ Scraping Failed (likely blocked): {e}")
        return None
    finally:
        if driver:
            driver.quit()

# ===== 2. RELIABLE FX DATA (yfinance) =====
def fetch_live_fx():
    print("⏳ Fetching live FX from Yahoo...")
    pair_map = {
        "AUDCAD": "AUDCAD=X", "AUDCHF": "AUDCHF=X", "AUDJPY": "AUDJPY=X", "AUDNZD": "AUDNZD=X", "AUDUSD": "AUDUSD=X",
        "CADCHF": "CADCHF=X", "CADJPY": "CADJPY=X", "USDCAD": "USDCAD=X",
        "CHFJPY": "CHFJPY=X", "USDCHF": "USDCHF=X",
        "EURAUD": "EURAUD=X", "EURCAD": "EURCAD=X", "EURCHF": "EURCHF=X", "EURGBP": "EURGBP=X", "EURJPY": "EURJPY=X", "EURUSD": "EURUSD=X",
        "GBPAUD": "GBPAUD=X", "GBPCAD": "GBPCAD=X", "GBPCHF": "GBPCHF=X", "GBPJPY": "GBPJPY=X", "GBPNZD": "GBPNZD=X", "GBPUSD": "GBPUSD=X",
        "NZDCHF": "NZDCHF=X", "NZDJPY": "NZDJPY=X", "NZDUSD": "NZDUSD=X",
        "USDJPY": "USDJPY=X"
    }
    tickers = list(pair_map.values())
    try:
        data = yf.download(tickers, period="5d", progress=False)
        closes = data['Close']
        results = {}
        for pair, ticker in pair_map.items():
            if ticker in closes.columns:
                series = closes[ticker].dropna()
                if len(series) >= 2:
                    curr = series.iloc[-1]
                    prev = series.iloc[-2]
                    is_jpy = "JPY" in pair
                    mult = 100 if is_jpy else 10000
                    chg = (curr - prev) * mult
                    results[pair] = [curr, int(chg)]
        return results
    except Exception as e:
        print(f"❌ Yahoo Error: {e}")
        return {}

# ===== 3. EXECUTION =====
fx_data = fetch_live_fx()
scraped_rates = scrape_cb_rates()

# FALLBACK RATES (Used if scraping fails)
fallback_rates = {
    "Fed": "5.50%", "ECB": "4.50%", "BoE": "5.25%", "BoJ": "-0.10%",
    "BoC": "5.00%", "RBA": "4.35%", "RBNZ": "5.50%", "SNB": "1.75%"
}

# Decide which rates to use
if scraped_rates and len(scraped_rates) > 3:
    final_rates = scraped_rates
    rate_source_icon = "🟢" # Live
else:
    final_rates = fallback_rates
    rate_source_icon = "⚠️" # Cached

# Build Message
lines = [f"📊 *G8 FX Update* — {now.strftime('%H:%M')} SGT\n"]

# Top Movers
if fx_data:
    sorted_pairs = sorted(fx_data.items(), key=lambda x: abs(x[1][1]), reverse=True)[:3]
    lines.append("🔥 *Top Movers*")
    for pair, vals in sorted_pairs:
        lines.append(f"{pair}: {vals[1]:+} pips")
else:
    lines.append("⚠️ FX Data Unavailable")

lines.append("")

# Segments
groups = {
    "AUD": ["AUDCAD", "AUDCHF", "AUDJPY", "AUDNZD", "AUDUSD"],
    "CAD": ["CADCHF", "CADJPY", "USDCAD"],
    "CHF": ["CHFJPY", "USDCHF"],
    "EUR": ["EURAUD", "EURCAD", "EURCHF", "EURGBP", "EURJPY", "EURUSD"],
    "GBP": ["GBPAUD", "GBPCAD", "GBPCHF", "GBPJPY", "GBPNZD", "GBPUSD"],
    "NZD": ["NZDCHF", "NZDJPY", "NZDUSD"],
    "USD": ["USDJPY"]
}

for grp, pairs in groups.items():
    seg_lines = []
    for p in pairs:
        if p in fx_data:
            pr, ch = fx_data[p]
            fmt = f"{pr:.2f}" if "JPY" in p else f"{pr:.4f}"
            seg_lines.append(f"{p} `{fmt}` ({ch:+} pips)")
    if seg_lines:
        lines.append(f"*{grp}*")
        lines.append("\n".join(seg_lines))
        lines.append("")

# Central Banks
lines.append(f"🏛 *Central Bank Rates* {rate_source_icon}")
cb_order = ["Fed", "ECB", "BoE", "BoJ", "BoC", "RBA", "RBNZ", "SNB"]
cb_lines = []
for b in cb_order:
    cb_lines.append(f"{b}: {final_rates.get(b, 'N/A')}")
lines.append(" | ".join(cb_lines))

message = "\n".join(lines)

# Send
try:
    requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", 
                  data={"chat_id": CHAT_ID, "text": message, "parse_mode": "Markdown"})
    print("✅ Telegram Sent")
except Exception as e:
    print(f"❌ Telegram Error: {e}")
