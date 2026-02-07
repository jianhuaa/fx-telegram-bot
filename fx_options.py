import requests

# ===== CONFIGURATION =====
TELEGRAM_TOKEN = "7649050168:AAHNIYnrHzLOTcjNuMpeKgyUbfJB9x9an3c"
CHAT_ID = "876384974"

def format_telegram_update(trade_date, data):
    """
    Ultra-dense layout for iPhone 13 Pro.
    Removed extra delineator line to prevent vertical overflow.
    Uses bolding on the last row to signal the break between blocks.
    """
    output = [
        f"📊 <b>FX Options — {trade_date}</b>",
        "<code>🌎 | METRIC     | CALL / PUT   | VOL</code>"
    ]

    for entry in data:
        metrics = [
            ('NOTIONAL', 'nv'),
            ('OPEN INT.', 'oi'),
            ('≤1W', 'e1'),
            ('>1W', 'e8') 
        ]
        
        for i, (label, key) in enumerate(metrics):
            call_pct = entry[f'{key}_c']
            put_pct = 100 - call_pct
            vol = str(entry[f'{key}_v']).strip()
            
            c_str = f"{call_pct}%"
            p_str = f"{put_pct}%"
            
            # Row Construction
            content = f"{entry['flag']} | {label:<10} | 🟢{c_str:>3} 🔴{p_str:>3} | {vol}"
            
            # If it's the last row of the block (>1W), we wrap it in <b> as a delineator
            # This makes the row "heavier" visually without adding vertical pixels.
            if label == '>1W':
                row = f"<b><code>{content}</code></b>"
            else:
                row = f"<code>{content}</code>"
                
            output.append(row)

    return "\n".join(output)

def send_telegram_message(message):
    """Sends the formatted HTML message to the specified Telegram chat."""
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": True
    }
    try:
        response = requests.post(url, json=payload, timeout=10)
        response.raise_for_status()
        print("✅ Options Report sent successfully to Telegram.")
    except Exception as e:
        print(f"❌ Failed to send message: {e}")

# --- DATA (Mocked for 05 Feb 2026) ---
test_data = [
    {'flag': '🇦🇺', 'code': 'AUD', 'nv_c': 18, 'nv_v': '$29M', 'oi_c': 46, 'oi_v': '$465M', 'e1_c': 24, 'e1_v': '$39M', 'e8_c': 66, 'e8_v': '$238M'},
    {'flag': '🇨🇦', 'code': 'CAD', 'nv_c': 2, 'nv_v': '$55M', 'oi_c': 56, 'oi_v': '$651M', 'e1_c': 7, 'e1_v': '$168M', 'e8_c': 26, 'e8_v': '$149M'},
    {'flag': '🇨🇭', 'code': 'CHF', 'nv_c': 63, 'nv_v': '$1.3M', 'oi_c': 55, 'oi_v': '$312M', 'e1_c': 65, 'e1_v': '$23M', 'e8_c': 51, 'e8_v': '$189M'},
    {'flag': '🇪🇺', 'code': 'EUR', 'nv_c': 59, 'nv_v': '$2.1B', 'oi_c': 58, 'oi_v': '$10.0B', 'e1_c': 66, 'e1_v': '$1.2B', 'e8_c': 48, 'e8_v': '$830M'},
    {'flag': '🇬🇧', 'code': 'GBP', 'nv_c': 47, 'nv_v': '$1.3B', 'oi_c': 48, 'oi_v': '$5.0B', 'e1_c': 40, 'e1_v': '$760M', 'e8_c': 55, 'e8_v': '$600M'},
    {'flag': '🇯🇵', 'code': 'JPY', 'nv_c': 59, 'nv_v': '$1.5B', 'oi_c': 56, 'oi_v': '$5.5B', 'e1_c': 69, 'e1_v': '$1.0B', 'e8_c': 36, 'e8_v': '$470M'}
]

if __name__ == "__main__":
    trade_date_str = "05 Feb 2026"
    final_report = format_telegram_update(trade_date_str, test_data)
    print(final_report)
    send_telegram_message(final_report)
