import requests
import yfinance as yf
from datetime import datetime, timedelta, timezone

# ===== TELEGRAM CONFIG =====
TELEGRAM_TOKEN = "7649050168:AAHNIYnrHzLOTcjNuMpeKgyUbfJB9x9an3c"
CHAT_ID = "876384974"
FORCE_SEND = True  # Set True to send even weekends for testing

# ===== SGT TIME =====
SGT = timezone(timedelta(hours=8))
now = datetime.now(SGT)
weekday = now.weekday()  # 0=Mon ... 6=Sun

# Skip weekends if not forcing send
if not FORCE_SEND and weekday in [5, 6]:
    print("Weekend — skipping FX update")
    exit(0)

# ===== FX TICKERS (Yahoo Finance) — All 28 G8 Crosses =====
tickers = [
    # AUD crosses
    "AUDCAD=X", "AUDCHF=X", "AUDJPY=X", "AUDNZD=X", "AUDUSD=X",
    # CAD crosses
    "CADCHF=X", "CADJPY=X", "USDCAD=X",
    # CHF crosses
    "CHFJPY=X", "USDCHF=X",
    # EUR crosses
    "EURAUD=X", "EURCAD=X", "EURCHF=X", "EURGBP=X", "EURJPY=X", "EURUSD=X",
    # GBP crosses
    "GBPAUD=X", "GBPCAD=X", "GBPCHF=X", "GBPJPY=X", "GBPNZD=X", "GBPUSD=X",
    # NZD crosses
    "NZDCHF=X", "NZDJPY=X", "NZDUSD=X",
    # USD crosses
    "USDJPY=X"
]

# ===== Helper Functions =====
def calc_pips(pair, new, old):
    """Calculate pips difference."""
    pip_size = 0.01 if "JPY" in pair else 0.0001
    return round((new - old) / pip_size)

# ===== Fetch FX Spot Rates + History =====
data = {}
for t in tickers:
    yf_ticker = yf.Ticker(t)
    hist = yf_ticker.history(period="8d", interval="1d")
    if hist.shape[0] < 2:
        continue
    latest_close = hist["Close"][-1]
    prev_close = hist["Close"][-2]
    week_close = hist["Close"][0]  # oldest point in 8d
    dd_pips = calc_pips(t, latest_close, prev_close)
    ww_pips = calc_pips(t, latest_close, week_close)
    data[t.replace("=X","")] = [latest_close, dd_pips, ww_pips]

if not data:
    print("No FX data fetched — exiting")
    exit(0)

# ===== Top Movers (Weighted Average Across Crosses) =====
currs = ["AUD","CAD","CHF","EUR","GBP","JPY","NZD","USD"]
top = {}
for c in currs:
    dd_vals = []
    ww_vals = []
    for p, vals in data.items():
        if p.startswith(c) or p.endswith(c):
            dd_vals.append(vals[1])
            ww_vals.append(vals[2])
    if dd_vals:
        top[c] = [round(sum(dd_vals)/len(dd_vals)), round(sum(ww_vals)/len(ww_vals))]
    else:
        top[c] = [0,0]

# ===== Economic Releases (Static Demo) =====
economic_releases = [
    {"flag":"🇺🇸","title":"US CPI (High)","time":"20:30 SGT","prev":"3.4%","cons":"3.2%"},
    {"flag":"🇪🇺","title":"EZ Industrial Prod","time":"16:00 SGT","prev":"-0.6%","cons":"-0.3%"},
    {"flag":"🇬🇧","title":"UK GDP MoM","time":"16:30 SGT","prev":"0.0%","cons":"0.1%"}
]

# ===== Central Bank Rates =====
central_bank_rates = {
    "Fed":"5.25–5.50%", "ECB":"4.00%", "BoE":"5.25%", "BoJ":"0.10%",
    "SNB":"1.75%", "RBA":"4.35%", "BoC":"5.00%", "RBNZ":"5.50%"
}

# ===== Rates Outlook — Colored Arrows =====
rates_outlook = {
    "Fed":["🔴⬇️65%","🟡➡️35%","22 Feb 2026"],
    "ECB":["🔴⬇️45%","🟡➡️55%","08 Mar 2026"],
    "BoE":["🔴⬇️30%","🟢⬆️15%","20 Mar 2026"],
    "BoJ":["🔴⬇️20%","🟢⬆️30%","10 Mar 2026"],
    "SNB":["🔴⬇️55%","🟡➡️45%","16 Mar 2026"],
    "RBA":["🟢⬆️40%","🟡➡️60%","05 Mar 2026"],
    "BoC":["🔴⬇️35%","🟡➡️65%","11 Mar 2026"],
    "RBNZ":["🔴⬇️25%","🟢⬆️20%","03 Mar 2026"]
}

# ===== Format Telegram Message =====
lines = []
lines.append(f"📊 G8 FX & Macro Update — {now.strftime('%H:%M')} SGT\n")
lines.append("🔥 Top Movers (Weighted Avg across crosses)")
for c,v in top.items():
    lines.append(f"{c}: {v[0]:+} pips d/d | {v[1]:+} pips w/w")
lines.append("\n---\n")

for pair in sorted(data):
    rate, dd, ww = data[pair]
    rate_str = f"{rate:.2f}" if "JPY" in pair else f"{rate:.4f}"
    lines.append(f"{pair} {rate_str}  {dd:+} d/d | {ww:+} w/w")

lines.append("\n---\nToday — Key Economic Releases")
for e in economic_releases:
    lines.append(f"{e['flag']} {e['title']:<22} | {e['time']} | Prev {e['prev']} | Cons {e['cons']}")

lines.append("\n---\nCentral Bank Policy Rates")
for k,v in central_bank_rates.items():
    lines.append(f"{k:<4}: {v}")

lines.append("\n---\nRates Outlook — Next Meeting")
for k,v in rates_outlook.items():
    lines.append(f"{k:<4}: {v[0]:<8} | {v[1]:<8} | {v[2]}")

message = "\n".join(lines)

# ===== Send to Telegram =====
url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
payload = {"chat_id":CHAT_ID,"text":message}
response = requests.post(url,data=payload)
print(response.json())
