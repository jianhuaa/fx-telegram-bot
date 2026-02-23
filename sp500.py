import cloudscraper
import pdfplumber
import io
import re
import requests

# --- CONFIGURATION ---
PDF_URLS = {
    "SEC_47_ES_CALLS": "https://www.cmegroup.com/daily_bulletin/current/Section47_E_Mini_S_And_P_500_Call_Options.pdf",
    "SEC_48_ES_PUTS": "https://www.cmegroup.com/daily_bulletin/current/Section48_E_Mini_S_And_P_500_Put_Options.pdf",
    "SEC_49_BIG_CALLS": "https://www.cmegroup.com/daily_bulletin/current/Section49_S_And_P_500_Call_Options.pdf",
    "SEC_50_BIG_PUTS": "https://www.cmegroup.com/daily_bulletin/current/Section50_S_And_P_500_Put_Options.pdf"
}

TELEGRAM_TOKEN = "8577879935:AAEpSjAz4wdcZ9Lb7AJpURRk8haADlPCbHo"
CHAT_ID = "876384974"

WANTED_OPTIONS = [
    "EMINI S&P CALL", "EMINI S&P PUT", "S&P 500 CALL", "S&P 500 PUT",
    "MINI S&P C", "MINI S&P P", "S&P 500 C", "S&P 500 P",
    "XMS MON", "XTS TUE", "XWS WED", "XRS THUR",
    "MDW MID", "MMW MID", "MRW MID", "MTW MID", "EOM EMINI S&P P"
]

def to_int(val):
    if not val: return 0
    s = str(val).replace(",", "").replace(" ", "").strip()
    match = re.search(r'^([+-]?\d+)', s)
    if match: s = match.group(1)
    try: return int(float(s))
    except: return 0

def format_num(val):
    n = to_int(val)
    abs_n = abs(n)
    sign = "-" if n < 0 else ""
    if abs_n < 1000: return f"{n}"
    elif abs_n < 10000: return f"{sign}{abs_n/1000:.1f}k"
    else: return f"{sign}{round(abs_n/1000)}k"

def clean_month(m_str):
    if not m_str.isdigit(): return m_str.upper()
    if len(m_str) == 8:
        months = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]
        try:
            m_idx = int(m_str[4:6]) - 1
            return f"{months[m_idx]}{m_str[2:4]}"
        except: pass
    return "UNKNOWN"

def get_month_score(m_str):
    months = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]
    try:
        m, y = m_str[:3], int(m_str[3:])
        return y * 100 + (months.index(m) + 1)
    except: return 0

def parse_es_futures_line(line, page_num):
    tokens = line.split()
    if len(tokens) < 11: return None
    try:
        month = tokens[0]
        sett = float(tokens[5].replace(",", "").replace("A", "").replace("B", ""))
        sign = tokens[6]
        chg_val = tokens[7].replace(",", "").replace("A", "").replace("B", "")
        
        change = float(f"{sign}{float(chg_val)/100}") if sign in ["+", "-"] else 0.0
        
        total_vol = to_int(tokens[8]) + to_int(tokens[9])
        oi = to_int(tokens[10])
        
        raw_token = tokens[11] if len(tokens) > 11 else "0"
        dirty_delta = raw_token
        if raw_token in ["+", "-"] and len(tokens) > 12:
            dirty_delta = raw_token + tokens[12]
            
        delta_oi = "0"
        if "UNCH" in dirty_delta or "NEW" in dirty_delta:
            delta_oi = "0"
        elif "." in dirty_delta:
            price_len = len(str(int(sett)))
            left_side = dirty_delta.split(".")[0]
            if len(left_side) > price_len: delta_oi = left_side[:-price_len]
            else: delta_oi = left_side
        else:
            delta_oi = dirty_delta
            
        res = {
            "Contract": f"ES {month}", "Month": month,
            "Sett": sett, "Change": change, "Volume": total_vol,
            "OI": oi, "Delta": delta_oi, "Page": page_num
        }
        print(f"[FUT] P{page_num:<3} | {res['Contract']:10} | SETT: {res['Sett']:7.2f} | CHG: {res['Change']:+6.2f} | VOL: {res['Volume']:7} | OI: {res['OI']:7} | ΔOI: {res['Delta']:6}")
        return res
    except: return None

def run_sp500_master_vacuum():
    scraper = cloudscraper.create_scraper(browser='chrome')
    all_futures, all_options = [], []
    trade_date = "Unknown"

    print("\n" + "="*95)
    print("SCRAPING S&P 500: INSTITUTIONAL MASTER (NO DIVIDENDS)")
    print("="*95)

    for label, url in PDF_URLS.items():
        try:
            resp = scraper.get(url)
            pdf_bytes = io.BytesIO(resp.content)
        except: continue
        
        multiplier = 5.0 if "BIG" in label else 1.0
        is_put_side = "PUTS" in label 
        
        with pdfplumber.open(pdf_bytes) as pdf:
            current_side = "PUTS" if is_put_side else "CALLS"
            active_block, current_month = None, "UNKNOWN"
            
            for p_idx, page in enumerate(pdf.pages):
                text = page.extract_text()
                if not text: continue
                
                if trade_date == "Unknown":
                    date_match = re.search(r'[A-Z][a-z]{2}, ([A-Z][a-z]{2} \d{2}, \d{4})', text)
                    if date_match: trade_date = date_match.group(1)

                lines = text.split('\n')
                for line in lines:
                    clean = line.strip()

                    # --- 1. THE KILL SWITCHES ---
                    if is_put_side and "OPTIONS EOO'S, BLOCKS and EXERCISES" in clean:
                        active_block = None; break 
                        
                    if "SDA OPT" in clean or "FIXING PRICE" in clean:
                        active_block = None
                        continue

                    # --- 2. ANCHORS ---
                    if "E-MINI S&P FUTURES" in clean:
                        active_block = "FUTURES"
                        print(f"\n>>> Locked onto Product: FUTURES")
                        continue
                        
                    if "WK EW-W" in clean or "E-MINI S&P CALLS" in clean or "E-MINI S&P PUTS" in clean:
                        if active_block == "FUTURES":
                            active_block = None
                            print(f"\n>>> Exiting Futures, entering Options Stream")

                    # --- CONTEXT UPDATES ---
                    if "CALLS" in clean.upper(): current_side = "CALLS"
                    elif "PUTS" in clean.upper(): current_side = "PUTS"

                    month_match = re.search(r'\b(?:JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)\d{2}\b', clean)
                    put_month_match = re.search(r'\b\d{6}00\b', clean)
                    temp_month = None
                    if put_month_match:
                        temp_month = decode_put_month(put_month_match.group())
                    elif month_match:
                        temp_month = month_match.group()
                    if temp_month:
                        current_month = temp_month

                    # --- OPTION HEADER DETECTION ---
                    if active_block != "FUTURES":
                        found_o = next((o for o in WANTED_OPTIONS if o in clean), None)
                        if found_o and "TOTAL" not in clean:
                            if "CALL OPTIONS" in clean or "PUT OPTIONS" in clean: continue
                            active_block = found_o
                            print(f"\n>>> Locked onto Product: {active_block} ({current_side})")
                            continue

                    # --- DATA EXTRACTION ---
                    if active_block == "FUTURES" and re.match(r'^[A-Z]{3}\d{2}', clean):
                        res = parse_es_futures_line(clean, p_idx + 1)
                        if res: all_futures.append(res)
                        continue

                    if "TOTAL" in clean and active_block and active_block != "FUTURES":
                        tokens = clean.split()
                        try:
                            t_idx = tokens.index("TOTAL")
                            vol_idx = -1
                            for i in range(t_idx + 1, len(tokens)):
                                if tokens[i].replace(",", "").isdigit():
                                    vol_idx = i
                                    break

                            if vol_idx != -1:
                                vol = to_int(tokens[vol_idx])
                                oi = to_int(tokens[vol_idx+1]) if vol_idx+1 < len(tokens) else 0
                                raw_delta = tokens[vol_idx+2] if vol_idx+2 < len(tokens) else "0"
                                if raw_delta in ["+", "-"] and vol_idx + 3 < len(tokens):
                                    delta_val = raw_delta + tokens[vol_idx+3]
                                else:
                                    delta_val = raw_delta

                                opt_res = {
                                    "Series": active_block,
                                    "Month": current_month,
                                    "Volume": vol * multiplier, 
                                    "OI": oi * multiplier, 
                                    "Delta": to_int(delta_val) * multiplier, 
                                    "Side": current_side
                                }
                                all_options.append(opt_res)
                                print(f"[OPT] P{p_idx+1:<3} | SPX | {opt_res['Series'][:12]:<12} {opt_res['Month']} | {opt_res['Side']:5} | VOL: {int(opt_res['Volume']):>6} | OI: {int(opt_res['OI']):>8} | ΔOI: {delta_val:>7}")
                        except: pass

    # --- AGGREGATION ---
    f_sum, opt_sum = {}, {}
    for f in all_futures:
        m = f["Month"]
        if m not in f_sum: f_sum[m] = {"Sett": f["Sett"], "Change": f["Change"], "Vol": 0, "OI": 0, "Delta": 0}
        f_sum[m]["Vol"] += f["Volume"]; f_sum[m]["OI"] += f["OI"]; f_sum[m]["Delta"] += to_int(f["Delta"])
    
    for o in all_options:
        m = o["Month"]
        if m not in opt_sum: opt_sum[m] = {"V_Gross":0,"V_Calls":0,"V_Puts":0,"OI_Net":0,"D_Net":0}
        opt_sum[m]["V_Gross"] += o["Volume"]
        if o["Side"] == "CALLS":
            opt_sum[m]["V_Calls"] += o["Volume"]; opt_sum[m]["OI_Net"] += o["OI"]; opt_sum[m]["D_Net"] += o["Delta"]
        else:
            opt_sum[m]["V_Puts"] += o["Volume"]; opt_sum[m]["OI_Net"] -= o["OI"]; opt_sum[m]["D_Net"] -= o["Delta"]

    # --- CONSOLE SUMMARY ---
    print("\n" + "="*95)
    print("AGGREGATING S&P 500 REPORTS (CONSOLE SUMMARY)")
    print("="*95)
    print("--- OPTIONS SUMMARY ---")
    for m in sorted(opt_sum.keys(), key=get_month_score):
        s = opt_sum[m]
        pc = s["V_Puts"] / s["V_Calls"] if s["V_Calls"] > 0 else 0.0
        print(f"{m:5} | VOL: {s['V_Gross']:10.1f} | P/C: {pc:5.2f} | NET OI: {s['OI_Net']:11.1f} | ΔOI: {s['D_Net']:10.1f}")

    print("\n^^options\n\nvv futures")
    print("="*95)
    print("--- FUTURES SUMMARY ---")
    for m in sorted(f_sum.keys(), key=get_month_score):
        s = f_sum[m]
        print(f"{m:5} | SETT: {s['Sett']:8.2f} | CHG: {s['Change']:+7.2f} | VOL: {s['Vol']:10.1f} | OI: {s['OI']:11.1f} | ΔOI: {s['Delta']:10.1f}")

    # --- TELEGRAM MESSAGE CONSTRUCTION ---
    tg_msg = [f"🇺🇸 <b>S&P 500 - {trade_date}</b>", "", "<b>FUTURES (E-MINI UNITS)</b>", "<code>MO   | SETT | CHG  | VOL |  OI |  ΔOI</code>"]
    for m in sorted(f_sum.keys(), key=get_month_score):
        s = f_sum[m]
        tg_msg.append(f"<code>{m:5}|{s['Sett']:6.1f}|{s['Change']:+6.1f}|{format_num(s['Vol']):>5}|{format_num(s['OI']):>5}|{format_num(s['Delta']):>5}</code>")
        tg_msg.append("-" * 38)

    tg_msg.append("\n<b>OPTIONS SUMMARY (NET E-MINI UNITS)</b>")
    tg_msg.append("<code>MO    | VOL  |  P/C  |  OI   | ΔOI </code>")
    for m in sorted(opt_sum.keys(), key=get_month_score):
        s = opt_sum[m]
        if s["V_Gross"] == 0: continue
        pc = s["V_Puts"] / s["V_Calls"] if s["V_Calls"] > 0 else 0.0
        tg_msg.append(f"<code>{m:5} |{format_num(s['V_Gross']):>5} | {pc:5.2f} |{format_num(s['OI_Net']):>6} |{format_num(s['D_Net']):>5}</code>")

    print("\n[INFO] Sending Telegram message...")
    requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", json={"chat_id": CHAT_ID, "text": "\n".join(tg_msg), "parse_mode": "HTML"})
    print("[INFO] Done.")

if __name__ == "__main__":
    run_sp500_master_vacuum()
