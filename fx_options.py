import cloudscraper
import pdfplumber
import io
import re
import sys
from datetime import datetime

# ===== CONFIGURATION =====
TELEGRAM_TOKEN = "7649050168:AAHNIYnrHzLOTcjNuMpeKgyUbfJB9x9an3c"
CHAT_ID = "876384974"

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
    try:
        return float(cleaned)
    except ValueError:
        return 0.0

def format_vol(val):
    """Formats volume as $M or $B rounded to 0.1M."""
    val_m = val / 1_000_000
    if val_m >= 1000:
        return f"${val_m/1000:.1f}B"
    return f"${val_m:.1f}M"

def get_pdf(url):
    """Downloads PDF using cloudscraper to bypass bot protection."""
    scraper = cloudscraper.create_scraper(
        browser={
            'browser': 'chrome',
            'platform': 'windows',
            'desktop': True
        }
    )
    try:
        resp = scraper.get(url, timeout=45)
        resp.raise_for_status()
        
        # Verify PDF signature
        if not resp.content.startswith(b'%PDF'):
            print(f"❌ Error: Content from {url} is not a PDF. Headers: {resp.headers}")
            raise ValueError("CME returned a non-PDF response (likely a bot-block page).")
            
        return io.BytesIO(resp.content)
    except Exception as e:
        print(f"❌ Network/Scraping Error for {url}: {e}")
        raise

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
            try:
                dt_obj = datetime.strptime(raw_date, '%m/%d/%y' if len(raw_date.split('/')[-1])==2 else '%m/%d/%Y')
                trade_date = dt_obj.strftime('%d %b %Y')
            except Exception as e:
                print(f"⚠️ Date parsing error: {e}")

        for page_idx, page in enumerate(pdf.pages):
            text = page.extract_text() or ""
            table = page.extract_table()
            if not table: continue

            if "Notional Value: Put-Call Breakdown" in text:
                print(f"✅ Found Notional table on page {page_idx + 1}")
                for row in table:
                    if not row or len(row) < 3: continue
                    for c in CURRENCIES:
                        if row[0] and c['name'] in row[0]:
                            results[c['code']]['nv_c'] = clean_numeric(row[1])
                            results[c['code']]['nv_p'] = clean_numeric(row[2])

            elif "Notional Open Interest: Put-Call Breakdown" in text:
                print(f"✅ Found Open Interest table on page {page_idx + 1}")
                for row in table:
                    if not row or len(row) < 3: continue
                    for c in CURRENCIES:
                        if row[0] and c['name'] in row[0]:
                            results[c['code']]['oi_c'] = clean_numeric(row[1])
                            results[c['code']]['oi_p'] = clean_numeric(row[2])
    
    return trade_date, results

def parse_expiry_breakdown(pdf_stream, results):
    """Extracts Expiry data from fx-put-call.pdf using the Shift Rule."""
    with pdfplumber.open(pdf_stream) as pdf:
        for page_idx, page in enumerate(pdf.pages):
            text = (page.extract_text() or "").upper()
            
            current_currency = None
            for c in CURRENCIES:
                if c['full'] in text:
                    current_currency = c['code']
                    break 
            
            if not current_currency: continue
            
            tables = page.extract_tables()
            for table in tables:
                for row in table:
                    if len(row) < 4: continue
                    dte_val = str(row[1]).strip()
                    if not dte_val.isdigit(): continue
                    
                    dte = int(dte_val)
                    
                    # Shift Rule logic: Empty index 2 means index 3 is Put
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
        metrics = [('NOTIONAL', 'nv'), ('OPEN INT.', 'oi'), ('≤1W', 'e1'), ('>1W', 'e8')]
        
        for label, key in metrics:
            c_v = entry.get(f'{key}_c', 0)
            p_v = entry.get(f'{key}_p', 0)
            total = c_v + p_v
            
            if total > 0:
                call_pct = int(round((c_v / total) * 100))
                put_pct = 100 - call_pct
            else:
                call_pct = put_pct = 0
            
            vol_str = format_vol(total)
            row = f"<code>{c['flag']} | {label:<10} | 🟢{call_pct:>3}% 🔴{put_pct:>3}% | {vol_str:>6}</code>"
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
    import requests as req_basic
    response = req_basic.post(url, json=payload, timeout=25)
    response.raise_for_status()
    print("✅ Live Report sent successfully.")

if __name__ == "__main__":
    print("🚀 Initiating CME FX Options Data Extraction...")
    try:
        print("...Downloading fx-report.pdf")
        report_pdf = get_pdf(URL_REPORT)
        trade_date, data = parse_fx_report(report_pdf)
        
        print("...Downloading fx-put-call.pdf")
        expiry_pdf = get_pdf(URL_PUT_CALL)
        final_data = parse_expiry_breakdown(expiry_pdf, data)
        
        if trade_date:
            report_content = format_telegram_update(trade_date, final_data)
            print("\n--- FINAL OUTPUT PREVIEW ---")
            print(report_content)
            send_telegram_message(report_content)
        else:
            print("❌ Failure: Could not extract Trade Date from CME PDFs.")
            sys.exit(1)
            
    except Exception as e:
        print(f"💥 Fatal Error: {e}")
        sys.exit(1)
