import os
import time
import requests
import yfinance as yf
from datetime import datetime, timedelta, timezone
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

# ===== G8 FX MAPPING (Yahoo Tickers) =====
# Yahoo formatted tickers for all 28 crosses
G8_TICKERS = [
    "AUDUSD=X", "AUDCAD=X", "AUDCHF=X", "AUDJPY=X", "AUDNZD=X",
    "CADCHF=X", "CADJPY=X",
    "CHFJPY=X",
    "EURUSD=X", "EURAUD=X", "EURCAD=X", "EURCHF=X", "EURGBP=X", "EURJPY=X", "EURNZD=X",
    "GBPUSD=X", "GBPAUD=X", "GBPCAD=X", "GBPCHF=X", "GBPJPY=X", "GBPNZD=X",
    "NZDUSD=X", "NZDCHF=X", "NZDJPY=X",
    "USDCAD=X", "USDCHF=X", "USDJPY=X"
]

# ===== CENTRAL BANK MAPPING =====
G8_CB_MAP = {
    "Federal Reserve": "Fed",
    "European Central Bank": "ECB",
    "Bank of England": "BoE",
    "Bank of Japan": "BoJ",
    "Bank of Canada": "BoC",
    "Reserve Bank of Australia": "RBA",
    "Reserve Bank of New Zealand": "RBNZ",
    "Swiss National Bank": "SNB"
}

# ===== ENGINE 1: YFINANCE (FX RATES) =====
def get_fx_data():
    print("Fetching FX data from Yahoo Finance...")
    data_store = {} # Structure: {"AUD": [("AUD/USD", 0.65, +0.1%, +1.2%)], ...}
    movers = []     # For top movers sorting

    # Download 1 week of data for all tickers at once (efficient)
    tickers_str = " ".join(G8_TICKERS)
    try:
        # Get 5 days history to calculate weekly change
        df = yf.download(tickers_str, period="5d", interval="1d", group_by='ticker', progress=False)
        
        # Get live/latest prices separately to ensure real-time accuracy
        # Note: 'period="1d"' usually gets the latest quote
        
        for ticker in G8_TICKERS:
            try:
                # Extract clean pair name (e.g., "AUDUSD=X" -> "AUD/USD")
                base = ticker[:3]
                quote = ticker[3:6]
                pair_name = f"{base}/{quote}"
                
                # Access ticker data
                ticker_df = df[ticker]
                if ticker_df.empty: continue

                # Latest Close (Live Price)
                current_price = ticker_df['Close'].iloc[-1]
                
                # Daily Change (vs Yesterday Close)
                prev_close = ticker_df['Close'].iloc[-2] if len(ticker_df) > 1 else current_price
                daily_chg_pct = ((current_price - prev_close) / prev_close) * 100
                
                # Weekly Change (vs 5 days ago)
                week_close = ticker_df['Close'].iloc[0]
                weekly_chg_pct = ((current_price - week_close) / week_close) * 100

                # Format strings
                p_str = f"{current_price:.4f}" if "JPY" not in ticker else f"{current_price:.2f}"
                d_str = f"{daily_chg_pct:+.2f}%"
                w_str = f"{weekly_chg_pct:+.2f}%"

                # Store in dictionary grouped by Base currency
                if base not in data_store: data_store[base] = []
                data_store[base].append({
                    "pair": pair_name,
                    "price": p_str,
                    "d_chg": d_str,
                    "w_chg": w_str
                })

                # Add to movers list (using daily change for ranking)
                movers.append((pair_name, daily_chg_pct))

            except Exception as e:
                print(f"Error processing {ticker}: {e}")
                continue
                
        return data_store, movers

    except Exception as e:
        print(f"YFinance Error: {e}")
        return None, None

# ===== ENGINE 2: STEALTH SCRAPER (CENTRAL BANKS) =====
def scrape_cb_rates():
    chrome_options = Options()
    chrome_options.add_argument("--headless=new")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--window-size=1920,1080")
    chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36")

    try:
        driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=chrome_options)
        stealth(driver, languages=["en-US", "en"], vendor="Google Inc.", platform="Win32", fix_hairline=True)

        driver.get("https://www.investing.com/central-banks/")
        time.sleep(20) 
        
        rates = {}
        try:
            table = driver.find_element(By.ID, "curr_table")
        except:
            table = driver.find_element(By.CSS_SELECTOR, "table.genTbl")

        rows = table.find_elements(By.TAG_NAME, "tr")[1:]
        for row in rows:
            cells = row.find_elements(By.TAG_NAME, "td")
            if len(cells) >= 3:
                raw_name = cells[1].get_attribute("textContent").split('(')[0].strip()
                rate_val = cells[2].get_attribute("textContent").strip()
                if raw_name in G8_CB_MAP:
                    rates[G8_CB_MAP[raw_name]] = rate_val
        
        driver.quit()
        return rates
    except Exception as e:
        print(f"Scrape Error: {e}")
        return None

# ===== EXECUTION =====
fx_data, fx_movers = get_fx_data()
cb_rates = scrape_cb_rates()

# ===== BUILD MESSAGE =====
lines = [f"📊 G8 FX & Macro Update — {now.strftime('%H:%M')} SGT\n"]

# 1. Dynamic Top Movers
if fx_movers:
    lines.append("🔥 Top Movers (Daily %)")
    fx_movers.sort(key=lambda x: x[1], reverse=True) # Sort Descending
    
    top_3 = fx_movers[:3]
    for m in top_3:
        lines.append(f"🟢 {m[0]}: +{m[1]:.2f}%")
        
    fx_movers.sort(key=lambda x: x[1]) # Sort Ascending
    bot_3 = fx_movers[:3]
    if bot_3[0][1] < 0:
        for m in bot_3:
            lines.append(f"🔴 {m[0]}: {m[1]:.2f}%")
else:
    lines.append("⚠️ Market data unavailable")

lines.append("\n---\n")

# 2. FX Matrix (with Weekly Change!)
if fx_data:
    g8_order = ["AUD", "CAD", "CHF", "EUR", "GBP", "NZD", "USD"]
    for base in g8_order:
        if base in fx_data:
            # Sort by Pair Name
            pairs = sorted(fx_data[base], key=lambda x: x['pair'])
            for p in pairs:
                # Format: AUD/USD  0.6500  (D: +0.10% | W: -1.20%)
                lines.append(f"{p['pair']}  {p['price']}")
                lines.append(f"   D: {p['d_chg']} | W: {p['w_chg']}")
            lines.append("")
else:
    lines.append("⚠️ FX Data Fetch Failed")

lines.append("---\nCentral Bank Policy Rates")
if cb_rates:
    g8_cb = ["Fed", "ECB", "BoE", "BoJ", "BoC", "RBA", "RBNZ", "SNB"]
    for bank in g8_cb:
        if bank in cb_rates:
            lines.append(f"{bank}: {cb_rates[bank]}")
else:
    lines.append("⚠️ Could not fetch live CB rates")

message = "\n".join(lines)

# ===== SEND =====
url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
payload = {"chat_id": CHAT_ID, "text": message}
requests.post(url, data=payload)
