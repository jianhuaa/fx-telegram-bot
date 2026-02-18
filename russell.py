import cloudscraper
import pdfplumber
import io
import re
import requests

# --- CONFIGURATION ---
PDF_URL = "https://www.cmegroup.com/daily_bulletin/current/Section40_Nasdaq_100_And_E_Mini_Nasdaq_100_Options.pdf"
TELEGRAM_TOKEN = "8577879935:AAEpSjAz4wdcZ9Lb7AJpURRk8haADlPCbHo"
CHAT_ID = "876384974"

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

def decode_put_month(date_str):
    months = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]
    try:
        month_idx = int(date_str[4:6]) - 1
        return f"{months[month_idx]}{date_str[2:4]}"
    except: return "UNKNOWN"

def get_month_score(month_str):
    months = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]
    try:
        m, y = month_str[:3], int(month_str[3:])
        return y * 100 + (months.index(m) + 1)
    except: return 0

def parse_rty_line(line, contract_name, page_num):
    tokens = line.split()
    if len(tokens) < 11: return None
    try:
        month = tokens[0]
        sett = float(tokens[4].replace(",", ""))
        sign = tokens[5]
        chg_val = tokens[6].replace(",", "")
        change = float(f"{sign}{float(chg_val)/100}")
        total_vol = to_int(tokens[7]) + to_int(tokens[8])
        oi = to_int(tokens[9])
        raw_token = tokens[10]
        dirty_delta = raw_token
        if raw_token in ["+", "-"] and len(tokens) > 11:
            dirty_delta = raw_token + tokens[11]
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
            "Contract": f"{contract_name} {month}", "Month": month,
            "Sett": sett, "Change": change, "Volume": total_vol,
            "OI": oi, "Delta": delta_oi, "Page": page_num
        }
        print(f"[FUT] P{page_num} | {res['Contract']:18} | SETT: {res['Sett']:7.2f} | CHG: {res['Change']:+6.2f} | VOL: {res['Volume']:7} | OI: {res['OI']:7} | ΔOI: {res['Delta']:6}")
        return res
    except: return None

def run_comprehensive_vacuum():
    scraper = cloudscraper.create_scraper(browser='chrome')
    pdf_bytes = io.BytesIO(scraper.get(PDF_URL).content)

    WANTED_FUTURES = ["RTY FUT", "M2K FUT"]
    WANTED_OPTIONS = ["RTM EOM", "RTO OPT", "RMW MON", "RRW THU", "RTW TUE", "RWW WED", "QN4", "R1E", "R2E", "R4E"]

    futures_results, options_results = [], []
    trade_date = "Unknown"

    # Futures State Tracking
    fut_last_score = 0
    fut_done = False

    # QN4 State Tracking
    qn4_in_block = False
    qn4_russell_mode = False
    qn4_last_total_score = 0  
    qn4_buffer = []           

    print("\n" + "="*95)
    print("STARTING VACUUM: RUSSELL 2000 (WITH ROBUST QN4 DETECTION)")
    print("="*95)

    with pdfplumber.open(pdf_bytes) as pdf:
        active_block, current_side, current_month = None, "CALLS", "UNKNOWN"

        for p_idx, page in enumerate(pdf.pages):
            text = page.extract_text()
            if not text: continue
            if p_idx == 0:
                date_match = re.search(r'[A-Z][a-z]{2}, ([A-Z][a-z]{2} \d{2}, \d{4})', text)
                if date_match: trade_date = date_match.group(1)

            lines = text.split('\n')
            for line in lines:
                clean = line.strip()

                # --- HARD STOP: end of Russell QN4 section ---
                if "ADDITIONAL NASDAQ PUTS" in clean:
                    if qn4_in_block:
                        print(f"    🛑 [HARD STOP] 'ADDITIONAL NASDAQ PUTS' detected — exiting QN4 Russell block.")
                    qn4_in_block = False
                    qn4_russell_mode = False
                    qn4_last_total_score = 0
                    qn4_buffer = []
                    active_block = None
                    continue

                # --- FUTURES BLOCK DETECTION ---
                if any(f == clean for f in WANTED_FUTURES):
                    active_block = clean
                    fut_last_score = 0
                    fut_done = False
                    qn4_in_block = False
                    qn4_russell_mode = False
                    qn4_last_total_score = 0
                    qn4_buffer = []
                    print(f"\n>>> Entering Futures Block: {active_block}")
                    continue

                # --- OPTION HEADER DETECTION ---
                if any(o in clean for o in WANTED_OPTIONS) and "TOTAL" not in clean:
                    if "QN4" in clean:
                        is_standalone = (clean == "QN4 CALL" or clean == "QN4 PUT" or clean == "QN4")
                        if is_standalone:
                            active_block = "QN4"
                            qn4_in_block = True
                            qn4_russell_mode = False
                            qn4_last_total_score = 0
                            qn4_buffer = []
                            print(f"\n>>> Entering QN4 Block [Russell Mode: False]: {clean}")
                        else:
                            print(f"    >>> QN4 Month Header: {clean}")
                    else:
                        active_block = clean
                        qn4_in_block = False
                        qn4_russell_mode = False
                        qn4_last_total_score = 0
                        qn4_buffer = []
                        print(f"\n>>> Entering Options Block: {clean}")

                    # Extract month from header line
                    header_month = re.search(r'\b(?:JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)\d{2}\b', clean)
                    put_header_match = re.search(r'\b\d{6}00\b', clean)
                    if put_header_match:
                        current_month = decode_put_month(put_header_match.group())
                    elif header_month:
                        current_month = header_month.group()
                    continue

                # --- TOTAL LINE PARSING ---
                if "TOTAL" in clean and active_block and active_block not in WANTED_FUTURES:
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
                                "Series": "QN4" if active_block == "QN4" else active_block,
                                "Month": current_month,
                                "Volume": vol, "OI": oi, "Delta": delta_val, "Side": current_side
                            }

                            if opt_res["Volume"] > 0 or opt_res["OI"] > 0:
                                if active_block == "QN4":
                                    curr_score = get_month_score(opt_res["Month"])

                                    # Line-by-line loopback
                                    if (not qn4_russell_mode
                                            and qn4_last_total_score > 0
                                            and curr_score < qn4_last_total_score):
                                        qn4_russell_mode = True
                                        qn4_buffer = []  # Discard Nasdaq captures
                                        print(f"    ⚠️  [LOOPBACK DETECTED] {opt_res['Month']} (score {curr_score}) < previous TOTAL (score {qn4_last_total_score}). Russell Mode ACTIVATED. Buffer cleared.")

                                    qn4_last_total_score = curr_score

                                    if qn4_russell_mode:
                                        options_results.append(opt_res)
                                        print(f"[OPT] P{p_idx+1} | {opt_res['Series'][:15]:<15} {opt_res['Side']:5} | {opt_res['Month']} | Vol: {opt_res['Volume']:6} | OI: {opt_res['OI']:7} | ΔOI: {opt_res['Delta']:5} [RUSSELL]")
                                    else:
                                        qn4_buffer.append((opt_res, p_idx+1))
                                        print(f"[BUF] P{p_idx+1} | {opt_res['Series'][:15]:<15} {opt_res['Side']:5} | {opt_res['Month']} | Vol: {opt_res['Volume']:6} | OI: {opt_res['OI']:7} | ΔOI: {opt_res['Delta']:5} [NASDAQ-BUFFERED]")
                                else:
                                    options_results.append(opt_res)
                                    print(f"[OPT] P{p_idx+1} | {opt_res['Series'][:15]:<15} {opt_res['Side']:5} | {opt_res['Month']} | Vol: {opt_res['Volume']:6} | OI: {opt_res['OI']:7} | ΔOI: {opt_res['Delta']:5}")
                    except:
                        pass

                    if not qn4_in_block:
                        active_block = None
                    continue

                # --- CONTEXT UPDATES ---
                if "CALLS" in clean.upper(): current_side = "CALLS"
                elif "PUTS" in clean.upper(): current_side = "PUTS"

                # --- Month Detection ---
                month_match = re.search(r'\b(?:JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)\d{2}\b', clean)
                put_month_match = re.search(r'\b\d{6}00\b', clean)
                temp_month = None
                if put_month_match:
                    temp_month = decode_put_month(put_month_match.group())
                elif month_match:
                    temp_month = month_match.group()
                if temp_month:
                    current_month = temp_month

                # --- FUTURES LINE PARSING ---
                if active_block in WANTED_FUTURES and not fut_done and re.match(r'^[A-Z]{3}\d{2}', clean):
                    line_month_match = re.match(r'^([A-Z]{3}\d{2})', clean)
                    if line_month_match:
                        line_month = line_month_match.group(1)
                        curr_score = get_month_score(line_month)
                        if fut_last_score > 0 and curr_score < fut_last_score:
                            print(f"    [FUT STOP] Backward jump {line_month} (score {curr_score}) < previous (score {fut_last_score}). Stopping futures capture for this block.")
                            fut_done = True
                        else:
                            res = parse_rty_line(clean, active_block, p_idx + 1)
                            if res:
                                fut_last_score = curr_score
                                futures_results.append(res)

    # =================================================================================
    # NEW DEBUG SECTION: OPTIONS AGGREGATION & MATH VERIFICATION
    # =================================================================================
    print("\n" + "="*95)
    print("DEBUG: OPTIONS AGGREGATION BREAKDOWN (SORTED BY MONTH -> SIDE)")
    print("="*95)

    # 1. Sort options for readability: Month -> Side (Calls first) -> Series
    # We use a tuple (MonthScore, Side_Priority, Series)
    # Side Priority: Calls=0, Puts=1 to make Calls appear first
    sorted_opts = sorted(
        options_results,
        key=lambda x: (
            get_month_score(x['Month']),
            0 if x['Side'] == "CALLS" else 1,
            x['Series']
        )
    )

    # 2. Group by Month and print step-by-step math
    # Use a temporary dict to group purely for printing
    debug_groups = {}
    for r in sorted_opts:
        if r['Month'] not in debug_groups: debug_groups[r['Month']] = []
        debug_groups[r['Month']].append(r)

    for m in debug_groups:
        print(f"\n>> PROCESSING MONTH: {m}")
        print(f"   {'SERIES':<10} | {'SIDE':<5} | {'VOL':>6} | {'OI (Raw)':>8} | {'ΔOI (Raw)':>9} | {'MATH APPLIED'}")
        print(f"   {'-'*90}")

        d_run_vol = 0
        d_run_oi = 0
        d_run_delta = 0
        d_call_vol = 0
        d_put_vol = 0

        for r in debug_groups[m]:
            vol = r['Volume']
            oi = r['OI']
            # Parse delta to int for calculation
            delta_int = to_int(r['Delta'])
            
            # MATH LOGIC:
            # Calls: Add OI, Add Delta
            # Puts:  Subtract OI, Subtract Delta
            if r['Side'] == "CALLS":
                eff_oi = oi
                eff_delta = delta_int
                math_str = f"+{oi} OI, +{delta_int} Δ"
                d_call_vol += vol
            else:
                eff_oi = -oi
                eff_delta = -delta_int
                math_str = f"-{oi} OI, -({delta_int}) Δ"
                d_put_vol += vol

            d_run_vol += vol
            d_run_oi += eff_oi
            d_run_delta += eff_delta

            print(f"   {r['Series'][:10]:<10} | {r['Side']:<5} | {vol:6} | {oi:8} | {delta_int:9} | {math_str}")

        # Summary for this month
        pc_ratio = d_put_vol / d_call_vol if d_call_vol > 0 else 0.0
        print(f"   {'-'*90}")
        print(f"   ==> RESULT: VOL={d_run_vol} (Calls:{d_call_vol}/Puts:{d_put_vol} P/C:{pc_ratio:.2f}) | NET OI={d_run_oi} | NET ΔOI={d_run_delta}")

    print("\n" + "="*95)
    # =================================================================================

    # --- ORIGINAL AGGREGATION & OUTPUT ---
    f_sum, opt_sum = {}, {}
    for r in futures_results:
        m, w = r["Month"], (0.1 if "M2K" in r["Contract"] else 1.0)
        if m not in f_sum: f_sum[m] = {"av":0,"ao":0,"ad":0,"rv":0,"ro":0,"rd":0,"s":r["Sett"],"c":r["Change"]}
        d = to_int(r["Delta"]) * w
        f_sum[m]["av"] += r["Volume"]*w; f_sum[m]["ao"] += r["OI"]*w; f_sum[m]["ad"] += d
        if w == 0.1: f_sum[m]["rv"] += r["Volume"]*w; f_sum[m]["ro"] += r["OI"]*w; f_sum[m]["rd"] += d

    for r in options_results:
        m = r["Month"]
        if m not in opt_sum: opt_sum[m] = {"V_Gross":0,"V_Calls":0,"V_Puts":0,"OI_Net":0,"D_Net":0}
        v, d = r["Volume"], to_int(r["Delta"])
        opt_sum[m]["V_Gross"] += v
        if r["Side"] == "CALLS":
            opt_sum[m]["V_Calls"] += v; opt_sum[m]["OI_Net"] += r["OI"]; opt_sum[m]["D_Net"] += d
        else:
            opt_sum[m]["V_Puts"] += v; opt_sum[m]["OI_Net"] -= r["OI"]; opt_sum[m]["D_Net"] -= d

    tg_msg = [f"🐿️ <b>RUSSELL 2000 - {trade_date}</b>", "", "<b>FUTURES (STANDARD UNITS)</b>", "<code>MO   |TYP| SETT | CHG | VOL| OI | ΔOI</code>"]
    for m in sorted(f_sum.keys(), key=get_month_score):
        s = f_sum[m]
        tg_msg.append(f"<code>{m:5}|ALL|{s['s']:6.1f}|{s['c']:+5.1f}|{format_num(s['av']):>4}|{format_num(s['ao']):>4}|{format_num(s['ad']):>4}</code>")
        tg_msg.append(f"<code>{m:5}|RET|{s['s']:6.1f}|{s['c']:+5.1f}|{format_num(s['rv']):>4}|{format_num(s['ro']):>4}|{format_num(s['rd']):>4}</code>")
        tg_msg.append("-" * 38)

    tg_msg.append("\n<b>OPTIONS SUMMARY</b>")
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
    run_comprehensive_vacuum()
