import requests
from datetime import datetime, timezone, timedelta

# ====== TELEGRAM CONFIG ======
TELEGRAM_TOKEN = "7649050168:AAHNIYnrHzLOTcjNuMpeKgyUbfJB9x9an3c"
CHAT_ID = "876384974"

# ====== FORCE SEND FLAG ======
FORCE_SEND = True  # Set True to send even on weekends

# ====== SGT TIMEZONE ======
SGT = timezone(timedelta(hours=8))
now = datetime.now(SGT)
weekday = now.weekday()  # 0=Mon, 6=Sun

# Skip weekends unless FORCE_SEND is True
if not FORCE_SEND and weekday in [5, 6]:
    print("Weekend — skipping FX update")
    exit()

# ====== FX DATA (Placeholder for demo) ======
fx_pairs = {
    "AUD": {"AUDCAD": [0.8920, +9, +21],
            "AUDCHF": [0.5821, +12, +25],
            "AUDJPY": [97.85, -5, -13],
            "AUDNZD": [1.0830, +10, +15],
            "AUDUSD": [0.6624, +22, +41]},
    "CAD": {"CADCHF": [0.6521, -6, -20],
            "CADJPY": [109.73, -12, -49]},
    "CHF": {"CHFJPY": [112.50, -10, -42]},
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
    "USD": {"USDJPY": [147.90, -34, -205],
            "USDCAD": [1.3486, -17, -66],
            "USDCHF": [0.8792, -14, -49]}
}

top_movers = {
    "AUD": [+21, +56],
    "CAD": [-15, -62],
    "CHF": [-12, -50],
    "EUR": [+18, +92],
    "GBP": [+16, +57],
    "JPY": [-32, -198],
    "NZD": [+24, +39]
}

central_bank_rates = {
    "Fed": "5.25–5.50%",
    "ECB": "4.00%",
    "BoE": "5.25%",
    "BoJ": "0.10%",
    "SNB": "1.75%",
    "RBA": "4.35%",
    "BoC": "5.00%",
    "RBNZ": "5.50%"
}

rates_outlook = {
    "Fed": ["⬇️65%", "➡️35%", "22 Feb 2026"],
    "ECB": ["⬇️45%", "➡️55%", "08 Mar 2026"],
    "BoE": ["⬇️30%", "⬆️15%", "20 Mar 2026"],
    "BoJ": ["⬇️20%", "⬆️30%", "10 Mar 2026"],
    "SNB": ["⬇️55%", "➡️45%", "16 Mar 2026"],
    "RBA": ["⬆️40%", "➡️60%", "05 Mar 2026"],
    "BoC": ["⬇️35%", "➡️65%", "11 Mar 2026"],
    "RBNZ": ["⬇️25%", "⬆️20%", "03 Mar 2026"]
}

economic_releases = [
    {"flag": "🇺🇸", "title": "US CPI (High)", "time": "20:30 SGT", "prev": "3.4%", "cons": "3.2%"},
    {"flag": "🇪🇺", "title": "EZ Industrial Production (Med)", "time": "16:00 SGT", "prev": "-0.6%", "cons": "-0.3%"},
    {"flag": "🇬🇧", "title": "UK GDP MoM (Med)", "time": "16:30 SGT", "prev": "0.0%", "cons": "0.1%"}
]

# ====== FORMAT MESSAGE ======
msg_lines = []
msg_lines.append(f"📊 G8 FX & Macro Update — {now.strftime('%H:%M')} SGT\n")

# Top Movers
msg_lines.append("🔥 Top Movers (Weighted Avg across crosses)")
for ccy, vals in top_movers.items():
    msg_lines.append(f"{ccy}: {vals[0]:+}  pips d/d | {vals[1]:+}  pips w/w")
msg_lines.append("\n---\n")

# FX segments (no subheaders)
for segment in ["AUD","CAD","CHF","EUR","GBP","NZD","USD"]:
    for pair in sorted(fx_pairs[segment]):
        spot, dd, ww = fx_pairs[segment][pair]
        if "JPY" in pair:
            spot_str = f"{spot:.2f}"
        else:
            spot_str = f"{spot:.4f}"
        msg_lines.append(f"{pair} {spot_str}  {dd:+}  d/d | {ww:+}  w/w")
    msg_lines.append("")

# Economic Releases — single line
msg_lines.append("---\nToday — Key Economic Releases")
for econ in economic_releases:
    msg_lines.append(f"{econ['flag']} {econ['title']:<30} | {econ['time']} | Prev: {econ['prev']} | Cons: {econ['cons']}")
msg_lines.append("")

# Central Bank Rates
msg_lines.append("---\nCentral Bank Policy Rates")
for k,v in central_bank_rates.items():
    msg_lines.append(f"{k:<4}: {v}")
msg_lines.append("")

# Rates Outlook with arrows
msg_lines.append("---\nRates Outlook — Next Meeting (% Probability)")
for k, v in rates_outlook.items():
    msg_lines.append(f"{k:<4}: {v[0]:<6} | {v[1]:<6} | {v[2]}")
msg_lines.append("")

# Join and send
message = "\n".join(msg_lines)

# ====== SEND TO TELEGRAM ======
url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
payload = {"chat_id": CHAT_ID, "text": message}
response = requests.post(url, data=payload)
print(response.json())
