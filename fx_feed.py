import requests
from datetime import datetime, timedelta, timezone
import json
from bs4 import BeautifulSoup

# ===== TELEGRAM CONFIG =====
TELEGRAM_TOKEN = "7649050168:AAHNIYnrHzLOTcjNuMpeKgyUbfJB9x9an3c"
CHAT_ID = "876384974"
FORCE_SEND = True  # Send even weekends for testing

# ===== SGT TIME =====
SGT = timezone(timedelta(hours=8))
now = datetime.now(SGT)
weekday = now.weekday()  # 0=Mon ... 6=Sun

if not FORCE_SEND and weekday in [5, 6]:
    print("Weekend — skipping FX update")
    exit(0)

# ===== STATIC FX DATA =====
fx_pairs = {
    "AUD": {"AUDCAD": [0.8920, +9, +21],
            "AUDCHF": [0.5821, +12, +25],
            "AUDJPY": [97.85, -5, -13],
            "AUDNZD": [1.0830, +10, +15],
            "AUDUSD": [0.6624, +22, +41]},
    "CAD": {"CADCHF": [0.6521, -6, -20],
            "CADJPY": [109.73, -12, -49],
            "USDCAD": [1.3486, -17, -66]},
    "CHF": {"CHFJPY": [112.50, -10, -42],
            "USDCHF": [0.8792, -14, -49]},
    "EUR": {"EURAUD": [1.6365, +20, +51],
            "EURCAD": [1.4620, +14, +45],
            "EURCHF": [0.9521, +11, +36],
            "EURGBP": [0.8512, +12, +34],
            "EURJPY": [160.23, -8, +18],
            "EURUSD": [1.0845, +26, +91]},
    "GBP": {"GBPAUD": [1.9210, +22, +44],
            "GBPCAD": [1.5800, +15, +48],
            "GBPCHF": [1.0300, +13, +41],
            "GBPJPY": [187.89, -10, -40],
            "GBPNZD": [1.9982, +21, +50],
            "GBPUSD": [1.2718, +19, +58]},
    "NZD": {"NZDCHF": [0.5382, +13, +28],
            "NZDJPY": [90.50, -7, -21],
            "NZDUSD": [0.6113, +25, +37]},
    "USD": {"USDJPY": [147.90, -34, -205]}
}

# ===== Top Movers =====
top_movers = {
    "AUD": [+21, +56],
    "CAD": [-15, -62],
    "CHF": [-12, -50],
    "EUR": [+18, +92],
    "GBP": [+16, +57],
    "JPY": [-32, -198],
    "NZD": [+24, +39],
    "USD": [-34, -205]
}

# ===== Rates Outlook — Colored Arrows =====
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

# ===== Economic Releases =====
economic_releases = [
    {"flag":"🇺🇸","title":"US CPI (High)","time":"20:30 SGT","prev":"3.4%","cons":"3.2%"},
    {"flag":"🇪🇺","title":"EZ Industrial Prod","time":"16:00 SGT","prev":"-0.6%","cons":"-0.3%"},
    {"flag":"🇬🇧","title":"UK GDP MoM","time":"16:30 SGT","prev":"0.0%","cons":"0.1%"}
]

# ===== Fetch Central Bank Rates from Investing.com (once per day) =====
CACHE_FILE = "cb_rates.json"
try:
    with open(CACHE_FILE,"r") as f:
        central_bank_rates = json.load(f)
except FileNotFoundError:
    print("Fetching central bank rates from Investing.com...")
    url = "https://www.investing.com/central-banks/"
    headers = {"User-Agent":"Mozilla/5.0"}
    r = requests.get(url, headers=headers)
    soup = BeautifulSoup(r.content, "html.parser")
    central_bank_rates = {}
    # This depends on Investing.com's table structure
    table = soup.find("table", {"id":"centralBankRates"})
    if table:
        for row in table.find_all("tr")[1:]:
            cells = row.find_all("td")
            if len(cells) >= 2:
                bank = cells[0].text.strip()
                rate = cells[1].text.strip()
                central_bank_rates[bank] = rate
    # Save cache
    with open(CACHE_FILE,"w") as f:
        json.dump(central_bank_rates,f)
    print("Central bank rates cached.")

# ===== Format Telegram Message =====
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
    lines.append(f"{k:<10}: {v}")

lines.append("\n---\nRates Outlook — Next Meeting")
for k,v in rates_outlook.items():
    lines.append(f"{k:<4}: {v[0]:<8} | {v[1]:<8} | {v[2]}")

message = "\n".join(lines)

# ===== Send to Telegram =====
url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
payload = {"chat_id": CHAT_ID, "text": message}
response = requests.post(url, data=payload)
print(response.json())
