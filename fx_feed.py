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

# ===== CONFIGURATION =====
TELEGRAM_TOKEN = "7649050168:AAHNIYnrHzLOTcjNuMpeKgyUbfJB9x9an3c"
CHAT_ID = "876384974"
FORCE_SEND = True 

SGT = timezone(timedelta(hours=8))
now = datetime.now(SGT)

# ===== G8 MAPPING =====
# Matches the exact HTML text content to your shorthand
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

# ===== ROBUST SCRAPER =====
def scrape_cb_rates():
    chrome_options = Options()
    # "New" headless mode is harder to detect
    chrome_options.add_argument("--headless=new")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--window-size=1920,1080")
    
    # Anti-detection flags
    chrome_options.add_argument("--disable-blink-features=AutomationControlled")
    chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
    chrome_options.add_experimental_option("useAutomationExtension", False)
    
    # Generic User Agent
    chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36")

    try:
        driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=chrome_options)
        
        # Apply Stealth
        stealth(driver,
            languages=["en-US", "en"],
            vendor="Google Inc.",
            platform="Win32",
            webgl_vendor="Intel Inc.",
            renderer="Intel Iris OpenGL Engine",
            fix_hairline=True,
        )

        # LINK: Direct to the Central Banks page
        driver.get("https://www.investing.com/central-banks/")
        
        # Wait for Cloudflare/JS checks
        time.sleep(20) 
        
        rates = {}
        
        # Attempt to find the table by ID
        try:
            table = driver.find_element(By.ID, "curr_table")
        except:
            # Fallback for if ID changes
            table = driver.find_element(By.CSS_SELECTOR, "table.genTbl")

        rows = table.find_elements(By.TAG_NAME, "tr")[1:]
        
        for row in rows:
            cells = row.find_elements(By.TAG_NAME, "td")
            if len(cells) >= 3:
                # IMPORTANT: Use get_attribute('textContent') for hidden/headless elements
                # "Federal Reserve (FED)" -> split -> "Federal Reserve"
                raw_text = cells[1].get_attribute("textContent").strip()
                name_clean = raw_text.split('(')[0].strip()
                
                rate_val = cells[2].get_attribute("textContent").strip()
                
                if name_clean in G8_MAP:
                    short_name = G8_MAP[name_clean]
                    rates[short_name] = rate_val
        
        driver.quit()
        return rates

    except Exception as e:
        print(f"Scrape Error details: {e}")
        return None

# Fetch Data
central_bank_rates = scrape_cb_rates()

# ===== BUILD TELEGRAM MESSAGE =====
lines = [f"📊 G8 FX & Macro Update — {now.strftime('%H:%M')} SGT\n"]
lines.append("🔥 Top Movers")
for c, vals in top_movers.items():
    lines.append(f"{c}: {vals[0]:+} pips d/d | {vals[1]:+} w/w")

lines.append("\n---\n")
for segment in ["AUD","CAD","CHF","EUR","GBP","NZD","USD"]:
    # Sort pairs alphabetically
    segment_pairs = sorted(fx_pairs.get(segment, {}))
    for pair in segment_pairs:
        spot, dd, ww = fx_pairs[segment][pair]
        rate_str = f"{spot:.2f}" if "JPY" in pair else f"{spot:.4f}"
        lines.append(f"{pair} {rate_str}  {dd:+} d/d | {ww:+} w/w")
    if segment_pairs:
        lines.append("")

lines.append("---\nToday — Key Economic Releases")
for e in economic_releases:
    lines.append(f"{e['flag']} {e['title']} | {e['time']} | P: {e['prev']} | C: {e['cons']}")

lines.append("\n---\nCentral Bank Policy Rates")
if central_bank_rates:
    # Print in standard G8 order
    g8_order = ["Fed", "ECB", "BoE", "BoJ", "BoC", "RBA", "RBNZ", "SNB"]
    for bank in g8_order:
        if bank in central_bank_rates:
            lines.append(f"{bank}: {central_bank_rates[bank]}")
else:
    # Fallback message if scraper is blocked
    lines.append("⚠️ Could not fetch live rates (Site blocked)")

lines.append("\n---\nRates Outlook")
for k, v in rates_outlook.items():
    lines.append(f"{k}: {v[0]} | {v[1]} | {v[2]}")

message = "\n".join(lines)

# ===== SEND TO TELEGRAM =====
url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
payload = {"chat_id": CHAT_ID, "text": message}
response = requests.post(url, data=payload)

print(f"Sent to Telegram. Status: {response.status_code}")
print(response.json())
