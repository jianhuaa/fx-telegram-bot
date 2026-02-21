import cloudscraper
import pdfplumber
import io
import re
import requests
import os
import csv
import pandas as pd
from telegraph import Telegraph
from datetime import datetime

# --- CONFIGURATION ---
PDF_URL = "https://www.cmegroup.com/daily_bulletin/current/Section12_Equity_And_Index_Futures_Continued.pdf"
TELEGRAM_TOKEN = "8577879935:AAEpSjAz4wdcZ9Lb7AJpURRk8haADlPCbHo"
CHAT_ID = "876384974"
CSV_FILE = "spdr_sectors_history.csv" 

TARGET_SECTORS = {
    "E-MINI COM SERVICES SELECT SECTOR": "COMM",
    "SP 500 CONS DISCRETIONARY SECTOR IX": "DISC",
    "SP 500 ENERGY SECTOR INDEX": "ENER",
    "SP 500 FINANCIAL SECTOR INDEX": "FINA",
    "SP 500 HEALTH CARE SECTOR INDEX": "HLTH",
    "SP 500 INDUSTRIAL SECTOR INDEX": "INDU",
    "SP 500 MATERIALS SECTOR INDEX": "MATL",
    "REAL ESTATE SELECT SECTOR FUTURES": "REIT",
    "SP 500 CONSUMER STAPLES SECTOR IX": "STAP",
    "SP 500 TECHNOLOGY SECTOR INDEX": "TECH",
    "SP 500 UTILITIES SECTOR INDEX": "UTIL"
}

# --- HELPERS ---
def to_float(val):
    if not val: return 0.0
    s = str(val).replace(",", "").replace("UNCH", "0").replace("----", "0").strip()
    s = re.sub(r'[NBA]$', '', s)
    try: return float(s)
    except: return 0.0

def format_num(val):
    n = round(val)
    abs_n = abs(n)
    sign = "-" if n < 0 else ""
    if abs_n < 1000: return f"{n}"
    elif abs_n < 10000: return f"{sign}{abs_n/1000:.1f}k"
    else: return f"{sign}{round(abs_n/1000)}k"

def normalize_tokens(tokens):
    split = []
    for t in tokens:
        m = re.match(r'^([+\-]?\d[\d,]*)([+\-])$', t)
        if m:
            split.append(m.group(1)); split.append(m.group(2))
        else:
            split.append(t)
    result = []
    i = 0
    while i < len(split):
        t = split[i]
        if (t == "+" or t == "-") and i + 1 < len(split):
            if split[i+1].replace('.', '').replace(',', '').isdigit():
                result.append(t + split[i+1]); i += 2; continue
        result.append(t); i += 1
    return result

def process_futures_block(product_name, line):
    raw_tokens = line.split()
    tokens = normalize_tokens(raw_tokens)
    if len(tokens) < 6: return None
    try:
        month = tokens[0]
        chg_idx = -1
        for i in range(1, len(tokens)):
            t = tokens[i]
            if t == "UNCH" or (len(t) > 1 and t[0] in "+-" and t[1].isdigit()):
                chg_idx = i; break
        if chg_idx == -1: return None
        sett = to_float(tokens[chg_idx - 1])
        chg = to_float(tokens[chg_idx])
        trailing_data = tokens[chg_idx+1:]
        nums = [t for t in trailing_data if '.' not in t]
        if len(nums) >= 3:
            vol = sum(int(to_float(n)) for n in nums[:-2])
            oi = int(to_float(nums[-2]))
            delta = int(to_float(nums[-1]))
        elif len(nums) == 2:
            vol = 0
            oi = int(to_float(nums[-2]))
            delta = int(to_float(nums[-1]))
        else:
            vol = oi = delta = 0
        return {"Product": product_name, "Month": month, "Sett": sett, "Change": chg, "Volume": vol, "OI": oi, "Delta": delta}
    except Exception:
        return None

# --- STORAGE & INSTANT VIEW LOGIC ---
def archive_and_publish(sorted_sectors, trade_date):
    try:
        clean_date = datetime.strptime(trade_date, "%b %d, %Y").strftime("%Y-%m-%d")
    except:
        clean_date = trade_date 

    file_exists = os.path.isfile(CSV_FILE)
    already_exists = False
    
    if file_exists:
        try:
            with open(CSV_FILE, 'r') as f:
                lines = f.readlines()
                if len(lines) > 1:
                    last_line = lines[-1].strip().split(',')
                    if last_line[0] == clean_date:
                        already_exists = True
                        print(f">>> Data for {clean_date} already exists. Skipping append.")
        except Exception as e:
            print(f"Check Error: {e}")

    if not already_exists:
        with open(CSV_FILE, mode='a', newline='') as f:
            writer = csv.writer(f)
            if not file_exists:
                writer.writerow(['Date', 'ID', 'Sett', 'Pct', 'Vol', 'OI', 'Delta'])
            for s in sorted_sectors:
                writer.writerow([clean_date, s['ID'], s['Sett'], f"{s['Pct']:.2f}%", s['Vol'], s['OI'], s['Delta']])
        print(f">>> Successfully archived data for {clean_date}.")
    
    # TELEGRAPH: Using Text-Grid (Pre) format to avoid 'table' tag errors
    try:
        df = pd.read_csv(CSV_FILE)
        # Show last 60 entries (approx 5 days)
        df = df.sort_values(by=['Date', 'ID'], ascending=[False, True]).head(60)
        
        header = "DATE       | ID   | SETT   | %CHG   | VOL   | OI    | ΔOI\n"
        sep    = "-----------|------|--------|--------|-------|-------|------\n"
        rows_text = ""
        for _, r in df.iterrows():
            rows_text += f"{r['Date']} | {r['ID']:4} | {str(r['Sett']):>6} | {r['Pct']:>6} | {format_num(r['Vol']):>5} | {format_num(r['OI']):>5} | {format_num(r['Delta']):>4}\n"
        
        html_content = f"<h4>S&P 500 Sector History (Newest First)</h4><pre>{header}{sep}{rows_text}</pre>"
        
        telegraph = Telegraph()
        telegraph.create_account(short_name='SectorBot')
        response = telegraph.create_page(
            title="S&P 500 Sectors Historical",
            author_name="CME Vacuum",
            html_content=html_content
        )
        return f"https://telegra.ph/{response['path']}"
    except Exception as e:
        print(f"History/Telegraph Error: {e}")
        return None

# --- MAIN VACUUM ---
def run_comprehensive_vacuum():
    print("=" * 80 + "\nSTARTING SECTOR VACUUM\n" + "=" * 80)
    
    scraper = cloudscraper.create_scraper(browser='chrome')
    resp = scraper.get(PDF_URL)
    pdf_bytes = io.BytesIO(resp.content)
    futures_results = []
    trade_date = "Unknown Date"

    with pdfplumber.open(pdf_bytes) as pdf:
        active_f = None
        last_printed_target = None
        for p_idx, page in enumerate(pdf.pages, start=1):
            text = page.extract_text() or ""
            if p_idx == 1:
                d_match = re.search(r'[A-Z][a-z]{2}, ([A-Z][a-z]{2} \d{2}, \d{4})', text)
                if d_match: trade_date = d_match.group(1)
            for line in text.split('\n'):
                clean = line.strip().upper()
                if not clean: continue
                found_target = False
                for f_key in TARGET_SECTORS.keys():
                    if f_key in clean and "TOTAL" not in clean:
                        active_f = f_key
                        found_target = True
                        if active_f != last_printed_target:
                            print(f"\n>>> Locked: {TARGET_SECTORS[f_key]}")
                            last_printed_target = active_f
                        break
                if not found_target and "TOTAL" in clean: active_f = None
                m_match = re.search(r'\b(?:JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)\d{2}\b', clean)
                if active_f and m_match and "TOTAL" not in clean:
                    res = process_futures_block(active_f, clean)
                    if res: 
                        futures_results.append(res)
                        print(f"[SECTOR] {TARGET_SECTORS[active_f]} | SETT: {res['Sett']} | CHG: {res['Change']}")

    front_months = {}
    for r in futures_results:
        prod = r["Product"]
        if prod not in front_months:
            sett = r["Sett"]
            actual_chg = r["Change"] / 100.0
            prev_sett = sett - actual_chg
            pct = (actual_chg / prev_sett * 100) if prev_sett != 0 else 0.0
            front_months[prod] = {
                "ID": TARGET_SECTORS[prod], "Sett": sett, "Pct": pct,
                "Vol": r["Volume"], "OI": r["OI"], "Delta": r["Delta"]
            }

    sorted_sectors = sorted(front_months.values(), key=lambda x: x["ID"])
    iv_link = archive_and_publish(sorted_sectors, trade_date)

    tg_msg = [
        f"📊 <b>S&P 500 SECTORS - {trade_date}</b>",
        "",
        "<code>ID   | SETT |  %CHG | VOL |  OI |  ΔOI</code>",
        "<code>--------------------------------------</code>"
    ]
    for s in sorted_sectors:
        row = f"<code>{s['ID']:4} |{s['Sett']:6.0f}|{s['Pct']:+6.2f}%|{format_num(s['Vol']):>5}|{format_num(s['OI']):>5}|{format_num(s['Delta']):>5}</code>"
        tg_msg.append(row)
        
    if iv_link:
        tg_msg.append(f"\n⚡️ <a href='{iv_link}'>INSTANT VIEW: Historical Trends</a>")

    requests.post(
        f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", 
        json={"chat_id": CHAT_ID, "text": "\n".join(tg_msg), "parse_mode": "HTML"}
    )
    print("\nDone.")

if __name__ == "__main__":
    run_comprehensive_vacuum()
