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

# ===== G8 DEFINITIONS =====
# 1. Map for Central Bank Website Names -> Shorthand
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

# 2. List of FX Tickers for Yahoo Finance (All 28 Pairs)
G8_FX_TICKERS = [
    "AUDUSD=X", "AUDCAD=X", "AUDCHF=X", "AUDJPY=X", "AUDNZD=X",
    "CADCHF=X", "CADJPY=X", "CHFJPY=X",
    "EURUSD=X", "EURAUD=X", "EURCAD=X", "EURCHF=X", "EURGBP=X", "EURJPY=X", "EURNZD=X",
    "GBPUSD=X", "GBPAUD=X", "GBPCAD=X", "GBPCHF=X", "GBPJPY=X", "GBPNZD=X",
    "NZDUSD=X", "NZDCHF=X", "NZDJPY=X",
    "USDCAD=X", "USDCHF=X", "USDJPY=X"
]

# 3. Static Outlook & Releases (To be automated later if needed)
rates_outlook = {
    "Fed":["🔴⬇️65%","🟡➡️35%","22 Feb 26"],
    "ECB":["🔴⬇️45%","🟡➡️55%","08 Mar 26"],
    "BoE":["🔴⬇️30%","🟢⬆️15%","20 Mar 26"],
    "BoJ":["🔴⬇️20%","🟢⬆️30%","10 Mar 26"],
    "SNB":["🔴⬇️55%","🟡➡️45%","16 Mar 26"],
    "RBA":["🟢⬆️40%","🟡➡️60%","05 Mar 26"],
    "BoC":["🔴⬇️35%","🟡➡️65%","11 Mar 26"],
    "RBNZ":["🔴⬇️25%","🟢⬆️20%","03 Mar 26"]
}

economic_releases = [
    {"flag":"🇺🇸","title":"US CPI (High)","time":"20:30 SGT","prev":"3.4%","cons":"3.2%"},
    {"flag":"🇪🇺","title":"EZ Industrial Prod","time":"16:00 SGT","prev":"-0.6%","cons":"-0.3%"},
    {"flag":"🇬🇧","title":"UK GDP MoM","time":"16:30 SGT","prev":"0.0%","cons":"0.1%"}
]

# ===== ENGINE 1: YFINANCE (FX RATES) =====
def get_fx_data():
    print("Fetching FX data from Yahoo Finance...")
    data_store = {} 
    movers = []     

    # Download 5 days of data to calculate Weekly Change
    tickers_str = " ".join(G8_FX_TICKERS)
    try:
        df = yf.download(tickers_str, period="5d", interval="1d", group_by='ticker', progress=False)
        
        for ticker in G8_FX_TICKERS:
            try:
                # Parse Ticker (e.g., "AUDUSD=X" -> "AUD/USD")
                base = ticker[:3]
                pair_name = f"{base}/{ticker[3:6]}"
                
                # Get Data Series
                ticker_df = df[ticker]
                if ticker_df.empty: continue

                # Prices
                current_price = ticker_df['Close'].iloc[-1]
                prev_close = ticker_df['Close'].iloc[-2] if len(ticker_df) > 1 else current_price
                week_close = ticker_df['Close'].iloc[0]

                # Calculations
                daily_chg = ((current_price - prev_close) / prev_close) * 100
                weekly_chg = ((current_price - week_close) / week_close) * 100

                # Formatting
                p_fmt = f"{current_price:.2f}" if "JPY" in ticker else f"{current_price:.4f}"
                
                entry = {
                    "pair": pair_name,
                    "price": p_fmt,
                    "d_str": f"{daily_chg:+.2f}%",
                    "w_str": f"{weekly_chg:+.2f}%"
                }

                if base not in data_store: data_store[base] = []
                data_store[base].append(entry)
                movers.append((pair_name, daily_chg))

            except Exception as e:
                continue
                
        return data_store, movers

    except Exception as e:
        print(f"YFinance Error: {e}")
        return None, None

# ===== ENGINE 2: STEALTH SCRAPER (CENTRAL BANKS) =====
def scrape_cb_rates():
    print("Scraping Central Bank Rates...")
    chrome_options = Options()
    chrome_options.add_argument("--headless=new")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--window-size=1920,1080")
    chrome_options.add_argument("--disable-blink-features=AutomationControlled")
    chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36")

    try:
        driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=chrome_options)
        stealth(driver, languages=["en-US", "en"], vendor="Google Inc.", platform="Win32", fix_hairline=True)

        driver.get("https://www.investing.com/central-banks/")
        
        # Heavy wait to bypass Cloudflare
        time.sleep(20) 
        
        rates = {}
        
        # Strategy A: Find by ID (curr_table)
        try:
            table = driver.find_element(By.ID, "curr_table")
        except:
            # Strategy B: Find any table with "Central Bank" in header
            all_tables = driver.find_elements(By.TAG_NAME, "table")
            table = None
            for t in all_tables:
                if "Central Bank" in t.get_attribute("textContent"):
                    table = t
                    break
        
        if table:
            rows = table.find_elements(By.TAG_NAME, "tr")[1:]
            for row in rows:
                cells = row.find_elements(By.TAG_NAME, "td")
                if len(cells) >= 3:
                    # Clean Name: "Federal Reserve (FED)" -> "Federal Reserve"
                    raw_name = cells[1].get_attribute("textContent").split('(')[0].strip()
                    rate_val = cells[2].get_attribute("textContent").strip()
                    
                    if raw_name in G8_CB_MAP:
                        rates[G8_CB_MAP[raw_name]] = rate_val
        
        driver.quit()
        return rates

    except Exception as e:
        print(f"Scrape Error: {e}")
        return None

# ===== MAIN EXECUTION =====
fx_data, fx_movers = get_fx_data()
cb_rates = scrape_cb_rates()

# ===== BUILD MESSAGE =====
lines = [f"📊 G8 FX & Macro Update — {now.strftime('%H:%M')} SGT\n"]

# 1. Top Movers
if fx_movers:
    lines.append("🔥 Top Movers (Daily %)")
    fx_movers.sort(key=lambda x: x[1], reverse=True)
    for m in fx_movers[:3]: lines.append(f"🟢 {m[0]}: +{m[1]:.2f}%")
    
    fx_movers.sort(key=lambda x: x[1])
    bot_3 = [m for m in fx_movers[:3] if m[1] < 0]
    for m in bot_3: lines.append(f"🔴 {m[0]}: {m[1]:.2f}%")
else:
    lines.append("⚠️ FX Data Unavailable")

lines.append("\n---\n")

# 2. FX Matrix (With Weekly Performance)
if fx_data:
    g8_order = ["AUD", "CAD", "CHF", "EUR", "GBP", "NZD", "USD"]
    for base in g8_order:
        if base in fx_data:
            sorted_pairs = sorted(fx_data[base], key=lambda x: x['pair'])
            for p in sorted_pairs:
                # Format: AUD/USD 0.6500 (D:+0.1% W:-1.2%)
                lines.append(f"{p['pair']} {p['price']} (D:{p['d_str']} W:{p['w_str']})")
            lines.append("")

lines.append("---\nToday — Key Economic Releases")
for e in economic_releases:
    lines.append(f"{e['flag']} {e['title']} | {e['time']} | P: {e['prev']} | C: {e['cons']}")

lines.append("\n---\nCentral Bank Policy Rates")
if cb_rates:
    g8_cb = ["Fed", "ECB", "BoE", "BoJ", "BoC", "RBA", "RBNZ", "SNB"]
    for bank in g8_cb:
        if bank in cb_rates:
            lines.append(f"{bank}: {cb_rates[bank]}")
else:
    lines.append("⚠️ Rates unavailable (Site Blocked)")

lines.append("\n---\nRates Outlook")
for k, v in rates_outlook.items():
    lines.append(f"{k}: {v[0]} | {v[1]} | {v[2]}")

message = "\n".join(lines)

# ===== SEND =====
url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
payload = {"chat_id": CHAT_ID, "text": message}
requests.post(url, data=payload)
