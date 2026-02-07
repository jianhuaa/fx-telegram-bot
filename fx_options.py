import requests

# ===== CONFIGURATION =====
TELEGRAM_TOKEN = "7649050168:AAHNIYnrHzLOTcjNuMpeKgyUbfJB9x9an3c"
CHAT_ID = "876384974"

def format_telegram_update(trade_date, data):
    """
    Formats the FX Options data into a stacked, mobile-friendly layout
    optimized for Telegram's monospaced blocks on iPhone 13 Pro.
    Layout: METRIC | CALL/PUT | VOL
    """
    # Updated Title format
    output = [
        f"<b>FX Options — {trade_date}</b>\n"
    ]

    for entry in data:
        # Currency Header
        header = f"{entry['flag']} <b>{entry['code']}</b>"
        output.append(header)
        
        # New 3-column table structure: METRIC | CALL/PUT | VOL
        table = ["<code>METRIC  | CALL/PUT | VOL</code>"]
        
        metrics = [
            ('NOTIONAL', 'nv'),
            ('OPEN INT', 'oi'),
            ('EXP ≤1W ', 'e1'),
            ('EXP >1W ', 'e8')
        ]
        
        for label, key in metrics:
            call_pct = entry[f'{key}_c']
            put_pct = 100 - call_pct
            vol = str(entry[f'{key}_v']).strip()
            
            # Remove leading zeros for <10% while keeping columns aligned
            c_str = f"{call_pct}%"
            p_str = f"{put_pct}%"
            
            # Row Construction:
            # Metric(8) | GreenBall + Call%(3) + RedBall + Put%(3) | Volume
            # Padding :>3 ensures the layout doesn't break when % digits change
            row = f"<code>{label}| 🟢{c_str:>3} 🔴{p_str:>3} | {vol}</code>"
            table.append(row)
        
        output.append("\n".join(table) + "\n")

    return "\n".join(output)

def send_telegram_message(message):
    """Sends the formatted HTML message to Telegram."""
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
        print(f"❌ Failed to send Options message: {e}")

# --- MOCK DATA (As specified in Master Prompt v2.0) ---
test_data = [
    {'flag': '🇦🇺', 'code': 'AUD', 'nv_c': 18, 'nv_v': '$29M', 'oi_c': 46, 'oi_v': '$465M', 'e1_c': 24, 'e1_v': '$39M', 'e8_c': 66, 'e8_v': '$238M'},
    {'flag': '🇨🇦', 'code': 'CAD', 'nv_c': 2, 'nv_v': '$55M', 'oi_c': 56, 'oi_v': '$651M', 'e1_c': 7, 'e1_v': '$168M', 'e8_c': 26, 'e8_v': '$149M'},
    {'flag': '🇨🇭', 'code': 'CHF', 'nv_c': 63, 'nv_v': '$1.3M', 'oi_c': 55, 'oi_v': '$312M', 'e1_c': 65, 'e1_v': '$23M', 'e8_c': 51, 'e8_v': '$189M'},
    {'flag': '🇪🇺', 'code': 'EUR', 'nv_c': 59, 'nv_v': '$2.1B', 'oi_c': 58, 'oi_v': '$10.0B', 'e1_c': 66, 'e1_v': '$1.2B', 'e8_c': 48, 'e8_v': '$830M'},
    {'flag': '🇬🇧', 'code': 'GBP', 'nv_c': 47, 'nv_v': '$1.3B', 'oi_c': 48, 'oi_v': '$5.0B', 'e1_c': 40, 'e1_v': '$760M', 'e8_c': 55, 'e8_v': '$600M'},
    {'flag': '🇯🇵', 'code': 'JPY', 'nv_c': 59, 'nv_v': '$1.5B', 'oi_c': 56, 'oi_v': '$5.5B', 'e1_c': 69, 'e1_v': '$1.0B', 'e8_c': 36, 'e8_v': '$470M'}
]

if __name__ == "__main__":
    # Current Trade Date from CME
    trade_date = "05 Feb 2026"
    
    # Generate the report
    report_content = format_telegram_update(trade_date, test_data)
    
    # Log to console for debugging
    print("--- GENERATED OUTPUT ---")
    print(report_content)
    
    # Fire the message
    send_telegram_message(report_content)
