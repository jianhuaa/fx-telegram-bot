import os
import json
import time
import requests
from datetime import datetime, timedelta, timezone
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from webdriver_manager.chrome import ChromeDriverManager
from selenium_stealth import stealth

# ===== TELEGRAM CONFIG =====
TELEGRAM_TOKEN = "7649050168:AAHNIYnrHzLOTcjNuMpeKgyUbfJB9x9an3c"
CHAT_ID = "876384974"
FORCE_SEND = True 

# ===== SGT TIME =====
SGT = timezone(timedelta(hours=8))
now = datetime.now(SGT)

# ===== MAPPING FOR G8 BANKS =====
# Keys match the website text, Values are your desired abbreviation
G8_MAP = {
    "Federal Reserve": "Fed",
    "European Central Bank": "ECB",
    "Bank of England": "BoE",
    "Bank of Japan": "BoJ",
    "Bank of Canada": "BoC",
    "Reserve Bank of Australia": "RBA",
    "Reserve Bank of New Zealand": "RBNZ",
    "Swiss National Bank": "SNB"
}

# ===== STATIC DATA =====
fx_pairs = {
    "AUD": {"AUDCAD": [0.8920, +9, +21], "AUDCHF": [0.5821, +12, +25], "AUDJPY": [97.85, -5, -13], "AUDNZD": [1.0830, +10, +15], "AUDUSD": [0.6624, +22, +41]},
    "CAD": {"CADCHF": [0.6521, -6, -20], "CADJPY": [109.73, -12, -49], "USDCAD": [1.3486, -17, -66]},
    "CHF": {"CHFJPY": [112.50, -10, -42], "USDCHF": [0.8792, -14, -49]},
    "EUR": {"EURAUD": [1.6365, +20, +51], "EURCAD": [1.4620, +14, +45], "EURCHF": [0.9521, +11, +36], "EURGBP": [0.8512, +12, +34], "EURJPY": [160.23, -8, +18], "EURUSD": [1.0845, +26, +91]},
    "GBP": {"GBPAUD": [1.9210, +22, +44], "GBPCAD": [1.5800, +15, +48], "GBPCHF": [1.0300, +13, +41], "GBPJPY": [187.89, -10, -40], "GBPNZD": [1.9982, +21, +50], "GBPUSD": [1.2718, +19, +58]},
    "NZD": {"NZDCHF": [0.5382, +13, +28], "NZDJPY": [90.50, -7, -21], "NZDUSD": [0.6113, +25, +37]},
    "USD": {"USDJPY": [147.90, -34, -205]}
}

top_movers = {
    "AUD": [+21, +56], "CAD": [-15, -62], "CHF": [-12, -50], "EUR": [+18, +92], "GBP": [+16, +57],
    "JPY": [-32, -198], "NZD": [+24, +39], "USD": [-34, -205]
}

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

# ===== STEALTH SCRAPER =====
def scrape_cb_rates():
    chrome_options = Options()
    chrome_options.add_argument("--headless")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--window-size=1920,1080")
    
    # Use a real browser user agent
    user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    chrome_options.add_argument(f"user-agent={user_agent}")

    try:
        driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=chrome_options)
        
        # Apply Stealth to hide automation flags
        stealth(driver,
            languages=["en-US", "en"],
            vendor="Google Inc.",
            platform="Win32",
            webgl_vendor="Intel Inc.",
            renderer="Intel Iris OpenGL Engine",
            fix_hairline=True,
        )

        # UPDATED LINK
        driver.get("https://www.investing.com/central-banks/")
        
        # Give it a substantial wait to bypass JS challenges
        time.sleep(15) 
        
        rates = {}
        # Based on your HTML, ID is "curr_table"
        try:
            table = driver.find_element(By.ID, "curr_table")
        except:
            # Fallback
            table = driver.find_element(By.CSS_SELECTOR, "table.genTbl")

        rows = table.find_elements(By.TAG_NAME, "tr")[1:]
        for row in rows:
            cells = row.find_elements(By.TAG_NAME, "td")
            if len(cells) >= 3:
                # Name is in index 1. It looks like "Federal Reserve (FED)"
                # We split by '(' to get just "Federal Reserve"
                raw_name = cells[1].text.split('(')[0].strip()
                rate = cells[2].text.strip()
                
                # Check if this name is in our G8 list
                if raw_name in G8_MAP:
                    short_name = G8_MAP[raw_name]
                    rates[short_name] = rate
        
        driver.quit()
        if not rates: raise Exception("No matching G8 data found in table")
        return rates

    except Exception as e:
        print(f"Scrape Error: {e}")
        return {} # Return empty dict instead of error object to handle gracefully

# Get rates
central_bank_rates = scrape_cb_rates()

# ===== BUILD MESSAGE =====
lines = [f"📊 G8 FX & Macro Update — {now.strftime('%H:%M')} SGT\n"]
lines.append("🔥 Top Movers")
for c, vals in top_movers.items():
    lines.append(f"{c}: {vals[0]:+} pips d/d | {vals[1]:+} w/w")

lines.append("\n---\n")
for segment in ["AUD","CAD","CHF","EUR","GBP","NZD","USD"]:
    for pair in sorted(fx_pairs.get(segment, {})):
        spot, dd, ww = fx_pairs[segment][pair]
        rate_str = f"{spot:.2f}" if "JPY" in pair else f"{spot:.4f}"
        lines.append(f"{pair} {rate_str}  {dd:+} d/d | {ww:+} w/w")
    lines.append("")

lines.append("---\nToday — Key Economic Releases")
for e in economic_releases:
    lines.append(f"{e['flag']} {e['title']} | {e['time']} | P: {e['prev']} | C: {e['cons']}")

lines.append("\n---\nCentral Bank Policy Rates")
if central_bank_rates:
    # Print in specific G8 order
    g8_order = ["Fed", "ECB", "BoE", "BoJ", "BoC", "RBA", "RBNZ", "SNB"]
    for bank in g8_order:
        if bank in central_bank_rates:
            lines.append(f"{bank}: {central_bank_rates[bank]}")
else:
    lines.append("⚠️ Could not fetch live rates (check site connection)")

lines.append("\n---\nRates Outlook")
for k, v in rates_outlook.items():
    lines.append(f"{k}: {v[0]} | {v[1]} | {v[2]}")

message = "\n".join(lines)

# ===== SEND =====
url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
payload = {"chat_id": CHAT_ID, "text": message}
response = requests.post(url, data=payload)

print(f"Telegram Response: {response.json()}")
