import cloudscraper
import pdfplumber
import io
import re
import requests

# --- CONFIGURATION ---
PDF_URL = "https://www.cmegroup.com/daily_bulletin/current/Section40_Nasdaq_100_And_E_Mini_Nasdaq_100_Options.pdf"
TELEGRAM_TOKEN = "7649050168:AAHNIYnrHzLOTcjNuMpeKgyUbfJB9x9an3c"
CHAT_ID = "876384974"

def to_int(val):
    if not val: return 0
    s = str(val).replace(",", "").replace("+", "").strip()
    try: return int(float(s))
    except: return 0

def to_float(val):
    if not val: return 0.0
    s = str(val).replace(",", "").replace("+", "").strip()
    try: return float(s)
    except: return 0

def format_num(val):
    """Formats numbers >= 100k as 'xxxk', else adds commas."""
    n = to_int(val)
    if abs(n) >= 100000:
        return f"{n // 1000}k"
    return f"{n:,}"

def decode_put_month(date_str):
    months = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]
    try:
        year = date_str[2:4]
        month_idx = int(date_str[4:6]) - 1
        return f"{months[month_idx]}{year}"
    except: return "UNKNOWN"

def get_month_score(month_str):
    months = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]
    try:
        m = month_str[:3]
        y = int(month_str[3:])
        return y * 100 + (months.index(m) + 1)
    except: return 0

def process_futures_block(contract, lines, page_num):
    cleaned_lines = [line.strip() for line in lines if line.strip()]
    full_text = " ".join(cleaned_lines)
    tokens = full_text.split()
    
    settlement, change_val = 0.0, 0.0
    change_idx = -1
    
    for i, t in enumerate(tokens):
        if t in ["+", "-"] and i+1 < len(tokens):
            raw_sett = tokens[i-1]
            raw_chg = tokens[i+1]
            
            if "." in raw_sett and len(raw_sett.split(".")[-1]) == 1:
                spill_digit = raw_chg[0]
                healed_sett = to_float(raw_sett + spill_digit)
                if (healed_sett * 100) % 25 == 0:
                    settlement = healed_sett
                else:
                    settlement = to_float(raw_sett)
            else:
                settlement = to_float(raw_sett)
            
            change_val = to_float(f"{t}{to_float(raw_chg)/100.0}")
            change_idx = i
            break
            
    delta_val, delta_idx = "0", -1
    for i in range(len(tokens)-1, change_idx + 1, -1):
        t = tokens[i]
        if t.startswith("UNCH") or t.startswith("NEW") or (i > 0 and tokens[i-1] in ["+", "-"]):
            if t.startswith("UNCH"): delta_val, delta_idx = "UNCH", i
            elif t.startswith("NEW"): delta_val, delta_idx = "NEW", i
            else:
                delta_val = tokens[i-1] + (t[:-8] if len(t) > 6 else t)
                delta_idx = i - 1
            break
            
    oi_val = "0"
    if delta_idx > 0:
        for j in range(delta_idx - 1, change_idx, -1):
            if re.match(r"^\d+(?:,\d+)*$", tokens[j]):
                oi_val = tokens[j]
                break

    volume = "0"
    for line in reversed(cleaned_lines):
        if line in ["0", "5"]: continue
        tks = line.split()
        for i, tk in enumerate(tks):
            if tk == delta_val or tk == oi_val:
                if i > 0:
                    cand = tks[i-1].replace(",", "")
                    if cand.isdigit() and to_int(cand) > 5:
                        volume = cand
                        break
        if volume != "0": break

    month_match = re.search(r'\b(?:JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)\d{2}\b', contract)
    month = month_match.group() if month_match else "UNKNOWN"
    return { "Contract": contract, "Month": month, "Sett": settlement, "Change": change_val, "Volume": to_int(volume), "OI": to_int(oi_val), "Delta": delta_val }

def process_options_total(name, month, line, page_num, side):
    tokens = line.split()
    total_idx = -1
    for i, t in enumerate(tokens):
        if t == "TOTAL":
            total_idx = i
            break
    if total_idx == -1: return None
    try:
        volume = tokens[total_idx + 1]; oi_val = tokens[total_idx + 2]
        delta_val = tokens[total_idx + 3] if total_idx + 3 < len(tokens) else "0"
        if delta_val in ["+", "-"] and total_idx + 4 < len(tokens):
            delta_val += tokens[total_idx + 4]
    except: return None
    
    clean_name = name.split('(')[0].strip()
    if "QN1" in clean_name: clean_name = "QN1"
    elif "QN2" in clean_name: clean_name = "QN2"
    elif "QN4" in clean_name: clean_name = "QN4"
    elif "WEEKLY-1" in clean_name: clean_name = "NASDAQ 100 WEEKLY-1"
    elif "WEEKLY-2" in clean_name: clean_name = "E-MINI NASDAQ 100 WEEKLY-2"
    elif "WEEKLY-4" in clean_name or "MAR26" in clean_name: clean_name = "E-MINI NASDAQ 100 WEEKLY-4"
    clean_name = clean_name.replace(month, "").strip()
    clean_name = re.sub(r'\d{8}', '', clean_name).strip()
    clean_name = re.sub(r'\b(CALLS|PUTS|CALL|PUT)\b', '', clean_name, flags=re.IGNORECASE).strip()
    clean_name = f"{clean_name} {side}"
    return { "Series": clean_name, "Month": month, "Volume": to_int(volume), "OI": to_int(oi_val), "Delta": delta_val, "Side": side }

def run_comprehensive_vacuum():
    scraper = cloudscraper.create_scraper(browser='chrome')
    pdf_bytes = io.BytesIO(scraper.get(PDF_URL).content)
    TARGET_MONTHS = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]
    WANTED_FUTURES = ["EMINI NASD FUT", "MNQ FUT"]
    WANTED_OPTIONS = ["WEEKLY-1", "WEEKLY-2", "WEEKLY-4", "EMINI NASD CALL", "EMINI NASD PUT", "QN1", "QN2", "QN4", "DMQ", "DRQ", "DTQ", "DWQ", "QMW", "QN OOF", "QRW", "QTW", "QWW", "MINI NSDQ EOM"]
    
    futures_results, options_results, seen_options = [], [], {}
    trade_date = "Unknown Date"

    with pdfplumber.open(pdf_bytes) as pdf:
        current_block_name, current_option_month = "UNKNOWN_SERIES", "UNKNOWN"
        in_futures, in_options = False, False
        current_side = "CALLS"

        for p_idx, page in enumerate(pdf.pages):
            page_num = p_idx + 1
            text_content = page.extract_text() or ""
            if p_idx == 0:
                date_match = re.search(r'[A-Z][a-z]{2}, ([A-Z][a-z]{2} \d{2}, \d{4})', text_content)
                if date_match: trade_date = date_match.group(1)

            lines = text_content.split('\n')
            for line in lines:
                clean = line.strip()
                if not clean: continue
                if "NASDAQ 100 WEEKLY-1 CALLS" in clean.upper(): current_side = "CALLS"
                elif "E-MINI NASDAQ 100 WEEKLY-1 PUTS" in clean.upper(): current_side = "PUTS"
                if "DEC29 EMINI NASD CALL" in clean.upper(): in_options = False; continue

                month_match = re.search(r'\b(?:JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)\d{2}\b', clean)
                put_month_match = re.search(r'\b\d{6}00\b', clean)
                if put_month_match: current_option_month = decode_put_month(put_month_match.group())
                elif month_match: current_option_month = month_match.group()

                found_f = False
                for f in WANTED_FUTURES:
                    if f in clean and "TOTAL" not in clean:
                        in_futures, in_options = True, False
                        current_block_name, found_f = f, True
                        break
                if found_f: continue

                found_o = False
                for o in WANTED_OPTIONS:
                    if o in clean and "TOTAL" not in clean:
                        if clean[0].isdigit() and not re.match(r'^\d{8}', clean): continue
                        in_futures, in_options = False, True
                        current_block_name, found_o = clean, True
                        break
                if not found_o and in_options and clean == "MAR26":
                    current_block_name = "E-MINI NASDAQ 100 WEEKLY-4"
                    current_option_month = "MAR26"

                if in_futures:
                    if "TOTAL" in clean: in_futures = False
                    else:
                        parts = clean.split()
                        if parts and len(parts[0]) == 5 and parts[0][:3] in TARGET_MONTHS:
                            futures_results.append(process_futures_block(f"{current_block_name} {parts[0]}", [clean], page_num))

                if in_options:
                    if clean.startswith("TOTAL"):
                        res = process_options_total(current_block_name, current_option_month, clean, page_num, current_side)
                        if res:
                            current_score = get_month_score(res["Month"])
                            if res["Series"] not in seen_options:
                                options_results.append(res); seen_options[res["Series"]] = current_score
                            elif current_score >= seen_options[res["Series"]]:
                                if not any(x for x in options_results if x["Series"] == res["Series"] and x["Month"] == res["Month"]):
                                    options_results.append(res); seen_options[res["Series"]] = current_score

    tg_msg = [f"📈 <b>NASDAQ 100 - {trade_date}</b>", ""]
    
    # --- FUTURES SECTION ---
    tg_msg.append("<b>FUTURES (AVG)</b>")
    tg_msg.append("<code>MO   | SETT| CHG |  VOL |  OI  | ΔOI </code>")
    f_summary = {}
    for r in futures_results:
        m = r["Month"]
        if m not in f_summary: 
            f_summary[m] = {"s":0, "c":0, "v":0, "oi":0, "d":0, "cnt":0}
        f_summary[m]["s"] += r["Sett"]
        f_summary[m]["c"] += r["Change"]
        f_summary[m]["v"] += r["Volume"]
        f_summary[m]["oi"] += r["OI"]
        delta_val = to_int(r["Delta"]) if r["Delta"] not in ["UNCH", "NEW"] else 0
        f_summary[m]["d"] += delta_val
        f_summary[m]["cnt"] += 1

    for m in sorted(f_summary.keys(), key=get_month_score):
        s = f_summary[m]; count = s["cnt"]
        # Columns: MO(5)|SETT(5)|CHG(5)|VOL(6)|OI(6)|ΔOI(5)
        row = f"{m[:5]}|{s['s']/count:5.0f}|{s['c']/count:+5.0f}|{format_num(s['v']):>6}|{format_num(s['oi']):>6}|{format_num(s['d']):>5}"
        tg_msg.append(f"<code>{row}</code>")

    # --- OPTIONS SECTION ---
    tg_msg.append("\n<b>OPTIONS SUMMARY</b>")
    tg_msg.append("<code>MO   |GROSS VOL| P/C | NET OI | ΔOI </code>")
    opt_sum = {}
    for r in options_results:
        m = r["Month"]
        if m not in opt_sum: 
            opt_sum[m] = {"V_Gross": 0, "V_Calls": 0, "V_Puts": 0, "OI_Net": 0, "D_Net": 0}
        opt_sum[m]["V_Gross"] += r["Volume"]
        delta = to_int(r["Delta"]) if r["Delta"] not in ["UNCH", "NEW"] else 0
        if r["Side"] == "CALLS":
            opt_sum[m]["V_Calls"] += r["Volume"]
            opt_sum[m]["OI_Net"] += r["OI"]
            opt_sum[m]["D_Net"] += delta
        else:
            opt_sum[m]["V_Puts"] += r["Volume"]
            opt_sum[m]["OI_Net"] -= r["OI"]
            opt_sum[m]["D_Net"] -= delta

    for m in sorted(opt_sum.keys(), key=get_month_score):
        s = opt_sum[m]
        pc_ratio = s["V_Puts"] / s["V_Calls"] if s["V_Calls"] > 0 else 0.0
        # Columns: MO(3)|VOL(10)|P/C(5)|OI(8)|ΔOI(5)
        row = f"{m[:5]}|{format_num(s['V_Gross']):>9}|{pc_ratio:5.2f}|{format_num(s['OI_Net']):>8}|{format_num(s['D_Net']):>5}"
        tg_msg.append(f"<code>{row}</code>")

    final_text = "\n".join(tg_msg)
    requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", json={"chat_id": CHAT_ID, "text": final_text, "parse_mode": "HTML"})

if __name__ == "__main__":
    run_comprehensive_vacuum()
