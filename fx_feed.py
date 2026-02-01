import os
import json
from datetime import datetime, timedelta, timezone
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
import requests

# ===== TELEGRAM CONFIG (HARD-CODED) =====
TELEGRAM_TOKEN = "7649050168:AAHNIYnrHzLOTcjNuMpeKgyUbfJB9x9an3c"
CHAT_ID = "876384974"
FORCE_SEND = True  # send even weekends for testing

# ===== SGT TIME =====
SGT = timezone(timedelta(hours=8))
now = datetime.now(SGT)
weekday = now.weekday()  # 0=Mon ... 6=Sun

if not FORCE_SEND and weekday >= 5:
    print("Weekend — skipping FX update")
    exit(0)

# ===== STATIC FX DATA =====
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

# ===== Central Bank Rates w/ Selenium + daily cache =====
CACHE_FILE = "cb_rates.json"

def get_cached_cb_rates():
    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE,"r") as f:
            data = json.load(f)
            last_update = datetime.fromisoformat(data["date"])
            if last_update.date() == datetime.now(SGT).date():
                return data["rates"]
    return None

def scrape_cb_rates():
    chrome_options = Options()
    chrome_options.add_argument("--headless")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    driver = webdriver.Chrome(service=Service("/usr/bin/chromedriver"), options=chrome_options)
    
    driver.get("https://www.investing.com/central-banks/world-central-banks")
    driver.implicitly_wait(5)
    
    rates = {}
    table = driver.find_element(By.ID,"curr_table")
    rows = table.find_elements(By.TAG_NAME,"tr")[1:]
    for row in rows:
        cells = row.find_elements(By.TAG_NAME,"td")
        if len(cells)>=3:
            name = cells[1].text.strip()
            rate = cells[2].text.strip()
            rates[name] = rate
    driver.quit()
    
    with open(CACHE_FILE,"w") as f:
        json.dump({"date":datetime.now(SGT).isoformat(),"rates":rates},f)
    return rates

central_bank_rates = get_cached_cb_rates()
if not central_bank_rates:
    central_bank_rates = scrape_cb_rates()

# ===== Build Telegram Message =====
lines = []
lines.append(f"📊 G8 FX & Macro Update — {datetime.now(SGT).strftime('%H:%M')} SGT\n")
lines.append("🔥 Top Movers (Weighted Avg across crosses)")
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
    lines.append(f"{e['flag']} {e['title']}")
    lines.append(f"Time {e['time']} | Prev {e['prev']} | Cons {e['cons']}")

lines.append("\n---\nCentral Bank Policy Rates")
for k,v in central_bank_rates.items():
    lines.append(f"{k:<35}: {v}")

lines.append("\n---\nRates Outlook — Next Meeting")
for k,v in rates_outlook.items():
    lines.append(f"{k:<4}: {v[0]:<8} | {v[1]:<8} | {v[2]}")

message = "\n".join(lines)

# ===== Send to Telegram =====
url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
payload = {"chat_id":CHAT_ID,"text":message}
response = requests.post(url,data=payload)
print(response.json())
