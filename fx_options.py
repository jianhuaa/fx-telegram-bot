import datetime
import requests

# ===== CONFIGURATION =====
# Derived from your provided configuration
TELEGRAM_TOKEN = "7649050168:AAHNIYnrHzLOTcjNuMpeKgyUbfJB9x9an3c"
CHAT_ID = "876384974"

def format_telegram_update(trade_date, data):
    """
    Formats the FX Options data into a stacked, mobile-friendly layout
    optimized for Telegram's monospaced (pre/code) blocks.
    """
    
    output = [
        f"📊 <b>CME OPTIONS SKEW</b> — {trade_date}",
        "Sentiment: Call 🟢 | Put 🔴\n"
    ]

    for entry in data:
        header = f"{entry['flag']} <b>{entry['code']}</b>"
        output.append(header)
        
        # Start the monospaced block for this currency
        table = [
            "<code>METRIC  | CALL/PUT (VOL)  | %SKEW</code>"
        ]
        
        metrics = [
            ('NOTIONAL', 'nv'),
            ('OPEN INT', 'oi'),
            ('EXP ≤1W ', 'e1'),
            ('EXP >1W ', 'e8')
        ]
        
        for label, key in metrics:
            call_pct = entry[f'{key}_c']
            put_pct = 100 - call_pct
            vol = entry[f'{key}_v']
            
            # Generate the 4-segment sparkline logic
            # 🟢 = 25% increments
            green_count = round(call_pct / 25)
            red_count = 4 - green_count
            sparkline = "🟢" * green_count + "🔴" * red_count
            
            # Format the percentage to remove leading zeros for <10%
            c_str = f"{call_pct}%"
            p_str = f"{put_pct}%"
            
            # Construct the row with strict padding for alignment
            row = f"<code>{label}| 🟢{c_str:>3} 🔴{p_str:>3} ({vol:>6}) | {sparkline}</code>"
            table.append(row)
        
        output.append("\n".join(table) + "\n")

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
        response = requests.post(url, json=payload)
        response.raise_for_status()
        print("✅ Report sent successfully to Telegram.")
    except Exception as e:
        print(f"❌ Failed to send message: {e}")

# --- MOCK DATA FOR TESTING ---
# Based on our research/image data
test_data = [
    {
        'flag': '🇦🇺', 'code': 'AUD',
        'nv_c': 18, 'nv_v': '$29M',
        'oi_c': 46, 'oi_v': '$465M',
        'e1_c': 24, 'e1_v': '$39M',
        'e8_c': 66, 'e8_v': '$238M'
    },
    {
        'flag': '🇨🇦', 'code': 'CAD',
        'nv_c': 2, 'nv_v': '$55M',
        'oi_c': 56, 'oi_v': '$651M',
        'e1_c': 7, 'e1_v': '$168M',
        'e8_c': 26, 'e8_v': '$149M'
    },
    {
        'flag': '🇨🇭', 'code': 'CHF',
        'nv_c': 63, 'nv_v': '$1.3M',
        'oi_c': 55, 'oi_v': '$312M',
        'e1_c': 65, 'e1_v': '$23M',
        'e8_c': 51, 'e8_v': '$189M'
    }
]

# --- EXECUTION ---
if __name__ == "__main__":
    trade_date_str = "05 FEB 2026"
    final_html = format_telegram_update(trade_date_str, test_data)
    
    print("--- PREVIEWING OUTPUT ---")
    print(final_html)
    
    # Uncomment the line below to test the actual live send
    # send_telegram_message(final_html)
