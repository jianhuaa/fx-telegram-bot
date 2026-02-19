import cloudscraper
import pdfplumber
import io
import re
import requests

def run_comprehensive_vacuum():
    print("--- STARTING SECTOR VACUUM ---")
    scraper = cloudscraper.create_scraper(browser='chrome')
    pdf_bytes = io.BytesIO(scraper.get(PDF_URL).content)

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

    futures_results = []
    trade_date = "Unknown Date"

    with pdfplumber.open(pdf_bytes) as pdf:
        active_f = None

        for p_idx, page in enumerate(pdf.pages):
            text = page.extract_text() or ""
            if p_idx == 0:
                d_match = re.search(r'[A-Z][a-z]{2}, ([A-Z][a-z]{2} \d{2}, \d{4})', text)
                if d_match: trade_date = d_match.group(1)

            for line in text.split('\n'):
                clean = line.strip().upper()
                if not clean: continue

                # Identify Product Blocks
                found_target = False
                for f_key in TARGET_SECTORS.keys():
                    if f_key in clean and "TOTAL" not in clean:
                        active_f = f_key
                        found_target = True
                        break
                
                if not found_target and "TOTAL" in clean: 
                    active_f = None

                m_match = re.search(r'\b(?:JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)\d{2}\b', clean)

                # Process Futures
                if active_f and m_match and "TOTAL" not in clean:
                    res = process_futures_block(active_f, clean)
                    if res: futures_results.append(res)

    # --- AGGREGATION & PERCENTAGE CALCULATION ---
    front_months = {}
    print("\n--- CALCULATING PERCENTAGES ---")
    for r in futures_results:
        prod = r["Product"]
        if prod not in front_months:
            sett = r["Sett"]
            raw_chg = r["Change"]
            
            # --- IMPLICIT DECIMAL FIX ---
            actual_chg = raw_chg / 100.0
            
            prev_sett = sett - actual_chg
            pct = (actual_chg / prev_sett * 100) if prev_sett != 0 else 0.0
            
            # ---> EXPLICIT MATH DEBUG <---
            print(f"[DEBUG MATH] {TARGET_SECTORS[prod]} | Raw Sett: {sett} | Raw Chg: {raw_chg} -> Act Chg: {actual_chg} | Prev Sett: {prev_sett:.2f} | Pct: {pct:.2f}%")
            
            front_months[prod] = {
                "ID": TARGET_SECTORS[prod],
                "Sett": sett,
                "Pct": pct,
                "Vol": r["Volume"],
                "OI": r["OI"],
                "Delta": r["Delta"]
            }
    print("-------------------------------\n")

    sorted_sectors = sorted(front_months.values(), key=lambda x: x["ID"])

    # --- TELEGRAM ---
    tg_msg = [
        f"📊 <b>S&P 500 SECTORS - {trade_date}</b>",
        "",
        "<code>ID   | SETT |  %CHG | VOL |  OI |  ΔOI</code>",
        "<code>--------------------------------------</code>"
    ]

    for s in sorted_sectors:
        row = f"<code>{s['ID']:4} |{s['Sett']:6.0f}|{s['Pct']:+6.2f}%|{format_num(s['Vol']):>5}|{format_num(s['OI']):>5}|{format_num(s['Delta']):>5}</code>"
        tg_msg.append(row)

    requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", json={"chat_id": CHAT_ID, "text": "\n".join(tg_msg), "parse_mode": "HTML"})
    print("--- DEBUG LOG COMPLETE (MESSAGE SENT) ---")

if __name__ == "__main__":
    run_comprehensive_vacuum()
