import requests
import pdfplumber
import io
import re
from datetime import datetime

# ===== CONFIGURATION =====
# As provided in the Master Prompt/Setup
TELEGRAM_TOKEN = "7649050168:AAHNIYnrHzLOTcjNuMpeKgyUbfJB9x9an3c"
CHAT_ID = "876384974"

# Strict display order and names for extraction
CURRENCIES = [
    {'code': 'AUD', 'name': 'AUD Options', 'flag': '🇦🇺', 'full': 'AUSTRALIAN DOLLAR'},
    {'code': 'CAD', 'name': 'CAD Options', 'flag': '🇨🇦', 'full': 'CANADIAN DOLLAR'},
    {'code': 'CHF', 'name': 'CHF Options', 'flag': '🇨🇭', 'full': 'SWISS FRANC'},
    {'code': 'EUR', 'name': 'EUR Options', 'flag': '🇪🇺', 'full': 'EUROPEAN MONETARY UNIT'},
    {'code': 'GBP', 'name': 'GBP Options', 'flag': '🇬🇧', 'full': 'BRITISH POUND'},
    {'code': 'JPY', 'name': 'JPY Options', 'flag': '🇯🇵', 'full': 'JAPANESE YEN'}
]

URL_REPORT = "https://www.cmegroup.com/reports/fx-report.pdf"
URL_PUT_CALL = "https://www.cmegroup.com/reports/fx-put-call.pdf"

def clean_numeric(val):
    """Cleans currency strings like '$767,790,000' into floats."""
    if val is None or str(val).strip() in ['', '-', 'None']:
        return 0.0
    cleaned = re.sub(r'[^\d.]', '', str(val))
    return float(cleaned) if cleaned else 0.0

def format_vol(val):
    """Formats volume as $M or $B rounded to 0.1M."""
    val_m = val / 1_000_000
    if val_m >= 1000:
        return f"${val_m/1000:.1f}B"
    return f"${val_m:.1f}M"

def get_pdf(url):
    """Downloads PDF with headers to bypass potential scraping blocks."""
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }
    resp = requests.get(url, headers=headers, timeout=30)
    resp.raise_for_status()
    return io.BytesIO(resp.content)

def parse_fx_report(pdf_stream):
    """Extracts Notional Value (Pg 2) and Open Interest (Pg 3) from fx-report.pdf."""
    results = {c['code']: {'nv_c': 0, 'nv_p': 0, 'oi_c': 0, 'oi_p': 0} for c in CURRENCIES}
    trade_date = ""

    with pdfplumber.open(pdf_stream) as pdf:
        # Trade Date Extraction
        header_text = ""
        for p in pdf.pages[:2]:
            header_text += p.extract_text() or ""
        
        date_match = re.search(r'Trade Date:?\s*(\d{1,2}/\d{1,2}/\d{2,4})', header_text)
        if date_match:
            raw_date = date_match.group(1)
            dt_obj = datetime.strptime(raw_date, '%m/%d/%y' if len(raw_date.split('/')[-1])==2 else '%m/%d/%Y')
            trade_date = dt_obj.strftime('%d %b %Y')

        for page in pdf.pages:
            text = page.extract_text() or ""
            table = page.extract_table()
            if not table: continue

            # Page 2: Notional Value Breakdown
            if "Notional Value: Put-Call Breakdown" in text:
                for row in table:
                    if not row: continue
                    for c in CURRENCIES:
                        if row[0] and c['name'] in row[0]:
                            results[c['code']]['nv_c'] = clean_numeric(row[1])
                            results[c['code']]['nv_p'] = clean_numeric(row[2])

            # Page 3: Notional Open Interest Breakdown
            elif "Notional Open Interest: Put-Call Breakdown" in text:
                for row in table:
                    if not row: continue
                    for c in CURRENCIES:
                        if row[0] and c['name'] in row[0]:
                            results[c['code']]['oi_c'] = clean_numeric(row[1])
                            results[c['code']]['oi_p'] = clean_numeric(row[2])
    
    return trade_date, results

def parse_expiry_breakdown(pdf_stream, results):
    """Extracts Expiry data from fx-put-call.pdf using the Shift Rule."""
    with pdfplumber.open(pdf_stream) as pdf:
        current_currency = None
        for page in pdf.pages:
            text = (page.extract_text() or "").upper()
            
            # Identify which currency section we are currently in
            for c in CURRENCIES:
                if c['full'] in text:
                    current_currency = c['code']
            
            if not current_currency: continue
            
            tables = page.extract_tables()
            for table in tables:
                for row in table:
                    # Filter for rows: [Date, DTE, Call, Put, Total]
                    if len(row) < 4: continue
                    dte_val = str(row[1]).strip()
                    if not dte_val.isdigit(): continue
                    
                    dte = int(dte_val)
                    
                    # MASTER PROMPT SHIFT RULE:
                    # If the Call cell is empty, Call is $0 and index 3 is Put.
                    if row[2] is None or str(row[2]).strip() in ['', '-', 'None']:
                        c_val = 0.0
                        p_val = clean_numeric(row[3])
                    else:
                        c_val = clean_numeric(row[2])
                        p_val = clean_numeric(row[3])

                    group = 'e1' if dte <= 7 else 'e8'
                    results[current_currency][f'{group}_c'] = results[current_currency].get(f'{group}_c', 0) + c_val
                    results[current_currency][f'{group}_p'] = results[current_currency].get(f'{group}_p', 0) + p_val

    return results

def format_telegram_update(trade_date, data):
    """Constructs the high-density grid for iPhone 13 Pro."""
    output = [
        f"📊 <b>FX Options — {trade_date}</b>",
        "<code>🌎 | METRIC     | CALL / PUT   | VOL</code>"
    ]

    for c in CURRENCIES:
        entry = data[c['code']]
        metrics = [
            ('NOTIONAL', 'nv'),
            ('OPEN INT.', 'oi'),
            ('≤1W', 'e1'),
            ('>1W', 'e8')
        ]
        
        for label, key in metrics:
            c_v = entry.get(f'{key}_c', 0)
            p_v = entry.get(f'{key}_p', 0)
            total = c_v + p_v
            
            # Percentage Calculation with rounding
            if total > 0:
                call_pct = int(round((c_v / total) * 100))
                put_pct = 100 - call_pct
            else:
                call_pct = put_pct = 0
            
            vol_str = format_vol(total)
            c_str = f"{call_pct}%"
            p_str = f"{put_pct}%"
            
            # Monospaced Grid Construction
            row = f"<code>{c['flag']} | {label:<10} | 🟢{c_str:>3} 🔴{p_str:>3} | {vol_str:>6}</code>"
            output.append(row)

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
        response = requests.post(url, json=payload, timeout=25)
        response.raise_for_status()
        print("✅ Live Report sent successfully.")
    except Exception as e:
        print(f"❌ Error sending message: {e}")

if __name__ == "__main__":
    print("🚀 Initiating CME FX Options Data Extraction...")
    try:
        # Step 1: Parse Notional and Open Interest
        print("...Processing fx-report.pdf")
        report_pdf = get_pdf(URL_REPORT)
        trade_date, data = parse_fx_report(report_pdf)
        
        # Step 2: Parse Expiry Date Breakdown
        print("...Processing fx-put-call.pdf")
        expiry_pdf = get_pdf(URL_PUT_CALL)
        final_data = parse_expiry_breakdown(expiry_pdf, data)
        
        # Step 3: Format and Dispatch
        if trade_date:
            report_content = format_telegram_update(trade_date, final_data)
            
            # Console Preview
            print("\n--- FINAL OUTPUT PREVIEW ---")
            print(report_content)
            print("----------------------------\n")
            
            send_telegram_message(report_content)
        else:
            print("❌ Failure: Could not extract Trade Date from CME PDFs.")
            
    except Exception as e:
        print(f"💥 Fatal Error: {e}")
