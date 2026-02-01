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

# ===== 1. SCRAPER (STRICT - NO FALLBACK) =====
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
        time.sleep(15) # Wait for Cloudflare
        
        rates = {}
        name_map = {
            "Federal Reserve": "Fed", "European Central Bank": "ECB",
            "Bank of England": "BoE", "Bank of Japan": "BoJ",
            "Bank of Canada": "BoC", "Reserve Bank of Australia": "RBA",
            "Reserve Bank of New Zealand": "RBNZ", "Swiss National Bank": "SNB"
        }

        # Try multiple selectors
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
        
        if not rates:
            return None # Explicit failure
            
        return rates

    except Exception as e:
        print(f"⚠️ Scraping Failed: {e}")
        return None # Explicit failure
    finally:
        if driver: driver.quit()

# ===== 2. FX & FUTURES DATA (yfinance) =====
def fetch_market_data():
    print("⏳ Fetching Market Data...")
    
    # 1. FX Tickers
    fx_tickers = list(TARGET_PAIRS.values())
    
    # 2. CME Fed Funds Futures (Front Month)
    # ZQ=F is the standard ticker for 30-Day Fed Funds Futures on Yahoo
    futures_tickers = ["ZQ=F"] 
    
    all_tickers = fx_tickers + futures_tickers
    
    # Fetch 1 month to calculate W/W changes accurately
    data = yf.download(all_tickers, period="1mo", progress=False)
    closes = data['Close']
    
    fx_results = {}
    fed_implied = None
    
    # -- Process FX --
    for pair, ticker in TARGET_PAIRS.items():
        if ticker in closes.columns:
            series = closes[ticker].dropna()
            if len(series) >= 6: # Need at least 5-6 days
                curr = series.iloc[-1]
                prev_day = series.iloc[-2]
                prev_week = series.iloc[-6] # ~1 week ago
                
                is_jpy = "JPY" in pair
                mult = 100 if is_jpy else 10000
                
                fx_results[pair] = {
                    "price": curr,
                    "dd": int((curr - prev_day) * mult),
                    "ww": int((curr - prev_week) * mult),
                    "is_jpy": is_jpy
                }

    # -- Process Fed Futures --
    # Logic: 100 - Price = Implied Fed Funds Rate
    if "ZQ=F" in closes.columns:
        zq_series = closes["ZQ=F"].dropna()
        if not zq_series.empty:
            zq_price = zq_series.iloc[-1]
            fed_implied = 100.0 - zq_price
            
    return fx_results, fed_implied

# ===== 3. CALCULATE BASE INDEX =====
def calculate_base_strength(fx_data):
    # Logic: Average pip performance of a currency against its basket
    currencies = ["AUD", "CAD", "CHF", "EUR", "GBP", "NZD", "USD", "JPY"]
    movers = {}

    for curr in currencies:
        total_dd = 0
        total_ww = 0
        count = 0
        
        for pair, vals in fx_data.items():
            if curr not in pair: continue
            
            # If Pair is "AUDUSD", AUD is Base (+). 
            # If Pair is "EURAUD", AUD is Quote (-).
            factor = 1 if pair.startswith(curr) else -1
            
            total_dd += (vals["dd"] * factor)
            total_ww += (vals["ww"] * factor)
            count += 1
            
        if count > 0:
            movers[curr] = [int(total_dd/count), int(total_ww/count)]
            
    return movers

# ===== 4. EXECUTION =====
fx_data, fed_implied_rate = fetch_market_data()
cb_rates = scrape_cb_rates()
base_movers = calculate_base_strength(fx_data)

# Manual Sections (Must be updated by YOU)
economic_releases = [
    {"flag":"🇺🇸","title":"Non-Farm Payrolls","time":"21:30 SGT","prev":"150k","cons":"180k"},
]

# ===== BUILD MESSAGE =====
lines = [f"📊 *G8 FX Update* — {now.strftime('%H:%M')} SGT\n"]

# 1. Top Movers
lines.append("🔥 *Top Movers (Base Index)*")
sorted_movers = sorted(base_movers.items(), key=lambda x: abs(x[1][0]), reverse=True)
for curr, vals in sorted_movers:
    lines.append(f"{curr}: {vals[0]:+} pips d/d | {vals[1]:+} w/w")

lines.append("\n---")

# 2. FX Pairs (Grouped)
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

# 3. Central Bank Rates (Strict Mode)
lines.append("🏛 *Central Bank Policy Rates*")
cb_list = ["Fed", "ECB", "BoE", "BoJ", "BoC", "RBA", "RBNZ", "SNB"]

if cb_rates:
    for bank in cb_list:
        val = cb_rates.get(bank, "N/A")
        lines.append(f"{bank}: {val}")
else:
    lines.append("⚠️ _Fetch Failed - Investing.com Blocked_")
    lines.append("_(Please check manual source)_")

lines.append("\n---")

# 4. Rates Outlook (Hybrid: Auto Fed, Manual Others)
lines.append("🔮 *Rates Outlook (Market Implied)*")

# Automated Fed Outlook
if fed_implied_rate:
    # Compare Implied vs Current (Assuming Current is ~5.50% or scraped value)
    # Note: If scrape failed, we assume a standard; here we just show the raw implied rate.
    lines.append(f"🇺🇸 *Fed (CME Futures):* Implied Rate {fed_implied_rate:.2f}%")
else:
    lines.append(f"🇺🇸 *Fed:* ⚠️ Data Unavailable")

# Manual Placeholders for others
lines.append("🇪🇺 *ECB:* 🔴⬇️45% (Manual)")
lines.append("🇬🇧 *BoE:* 🟡➡️60% (Manual)")
lines.append("🇦🇺 *RBA:* 🟢⬆️20% (Manual)")

# 5. Economic Releases
lines.append("\n---")
lines.append("📅 *Today — Key Economic Releases*")
for e in economic_releases:
    lines.append(f"{e['flag']} {e['title']} | {e['time']} | P: {e['prev']} | C: {e['cons']}")

message = "\n".join(lines)

# Send
try:
    requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", 
                  data={"chat_id": CHAT_ID, "text": message, "parse_mode": "Markdown"})
    print("✅ Telegram Sent")
except Exception as e:
    print(f"❌ Telegram Error: {e}")
