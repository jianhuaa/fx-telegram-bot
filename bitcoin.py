import cloudscraper
import pdfplumber
import io
import re
import requests

# --- CONFIGURATION ---
PDF_URL = "https://www.cmegroup.com/daily_bulletin/current/Section74_Cryptocurrency.pdf"
TELEGRAM_TOKEN = "8577879935:AAEpSjAz4wdcZ9Lb7AJpURRk8haADlPCbHo"
CHAT_ID = "876384974"

def to_int(val):
    if not val: return 0
    s = str(val).replace(",", "").replace("----", "").replace("UNCH", "").strip()
    if not s: return 0
    s = re.sub(r'[BA]$', '', s)
    s = s.replace("+", "")
    try: return int(float(s))
    except: return 0

def to_float(val):
    if not val: return 0.0
    s = str(val).replace(",", "").replace("----", "").replace("UNCH", "").strip()
    if not s: return 0.0
    s = re.sub(r'[BA]$', '', s)
    try: return float(s)
    except: return 0.0

def format_num(val):
    n = round(val)
    abs_n = abs(n)
    sign = "-" if n < 0 else ""
    if abs_n < 1000: return f"{n}"
    elif abs_n < 10000: return f"{sign}{abs_n/1000:.1f}k"
    else: return f"{sign}{round(abs_n/1000)}k"

def get_month_score(month_str):
    months = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]
    try:
        m = month_str[:3].upper()
        y = int(month_str[3:])
        return y * 100 + (months.index(m) + 1)
    except: return 0


def normalize_tokens(tokens):
    """
    Fix garbled change-column tokens produced by pdfplumber.
    
    Known garbling patterns (pdfplumber merges/splits chars around the sign):
      - "1-025.00"  -> should be "-1025.00"   (digit(s) before '-')
      - "0+.07500"  -> should be "+0.07500"    (digit before '+', dot after sign)
      - "0 .+009000"-> two tokens that together form "+0.009000"
      - "0 .+07650" -> two tokens
      - "0 .-000315"-> two tokens that form "-0.000315"
    
    Strategy: rebuild the token list, merging or fixing as needed.
    """
    result = []
    i = 0
    while i < len(tokens):
        t = tokens[i]

        # Pattern 1: digit(s) immediately followed by '-' then more digits/dot
        # e.g. "1-025.00" -> "-1025.00"
        m = re.match(r'^(\d+)-(\d[\d.]*)$', t)
        if m:
            fixed = '-' + m.group(1) + m.group(2)
            result.append(fixed)
            i += 1
            continue

        # Pattern 2: digit immediately followed by '+' then dot/digits
        # e.g. "0+.07500" -> "+0.07500"
        m = re.match(r'^(\d+)\+\.(\d+)$', t)
        if m:
            fixed = '+' + m.group(1) + '.' + m.group(2)
            result.append(fixed)
            i += 1
            continue

        # Pattern 3: lone "0" (or small digit) followed by next token like ".+009000" or ".-000315"
        # pdfplumber splits "0.+009000" into "0" and ".+009000"
        if re.match(r'^\d+$', t) and i + 1 < len(tokens):
            nxt = tokens[i + 1]
            m2 = re.match(r'^\.([+\-])(\d+)$', nxt)
            if m2:
                sign = m2.group(1)
                digits = m2.group(2)
                fixed = sign + t + '.' + digits
                result.append(fixed)
                i += 2
                continue

        result.append(t)
        i += 1

    return result


# --- THE POSITION-BASED PARSER (with fix) ---
def process_futures_block(product_name, clean_line):
    # Ensure line starts with a month code like FEB26
    if not re.match(r'^[A-Z]{3}\d{2}', clean_line): return None

    tokens = clean_line.split()
    if len(tokens) < 5: return None

    # Fix garbled tokens before any logic
    tokens = normalize_tokens(tokens)

    try:
        month = tokens[0]

        # Identify the Change column: explicitly signed (+/-) number, or UNCH
        chg_idx = -1
        for i, t in enumerate(tokens):
            if i == 0: continue
            if t == 'UNCH':
                chg_idx = i
                break
            # Must start with + or - and have something numeric after
            if t.startswith('+') or t.startswith('-'):
                remainder = t[1:].replace(',', '').replace('.', '', 1)
                if remainder.isdigit() and len(remainder) > 0:
                    chg_idx = i
                    break

        if chg_idx == -1: return None

        # Data Extraction based on the Change Column Pivot
        sett = to_float(tokens[chg_idx - 1])
        chg = to_float(tokens[chg_idx]) if tokens[chg_idx] != 'UNCH' else 0.0

        # Volume is often two columns (RTH + Globex)
        vol = to_int(tokens[chg_idx + 1])
        if chg_idx + 2 < len(tokens) and tokens[chg_idx + 2] != "----":
            next_t = tokens[chg_idx + 2]
            if next_t.isdigit() or "," in next_t:
                vol += to_int(next_t)
                oi_idx = chg_idx + 3
            else:
                oi_idx = chg_idx + 2
        else:
            oi_idx = chg_idx + 2

        oi = to_int(tokens[oi_idx]) if oi_idx < len(tokens) else 0

        # Delta is usually next to OI
        delta_idx = oi_idx + 1
        delta = 0
        if delta_idx < len(tokens):
            d_val = tokens[delta_idx]
            if d_val in ["+", "-"] and delta_idx + 1 < len(tokens):
                delta = to_int(tokens[delta_idx + 1])
                if d_val == "-": delta *= -1
            else:
                delta = to_int(d_val)

        print(f"[DEBUG] ✅ {product_name} {month}: Sett={sett} | Chg={chg} | Vol={vol} | OI={oi} | Delta={delta}")

        return { "Product": product_name, "Month": month, "Sett": sett,
                 "Change": chg, "Volume": vol, "OI": oi, "Delta": delta }

    except Exception as e:
        print(f"[DEBUG] ❌ Skip Line: {clean_line[:40]}... ({e})")
        return None


# --- OPTIONS (PRESERVED) ---
def process_options_total(current_name, month, line, side):
    line = line.replace(",", "").replace("----", " 0 ").strip()
    tokens = line.split()
    t_idx = next((i for i, t in enumerate(tokens) if t == "TOTAL"), -1)
    if t_idx == -1 or t_idx + 2 >= len(tokens): return None
    try:
        vol = tokens[t_idx + 1]
        oi = tokens[t_idx + 2]
        delta = "0"
        if t_idx + 3 < len(tokens):
            delta = tokens[t_idx + 3]
            if delta in ["+", "-"] and t_idx + 4 < len(tokens):
                delta += tokens[t_idx + 4]
        return { "Series": current_name, "Month": month, "Volume": to_int(vol),
                 "OI": to_int(oi), "Delta": delta, "Side": side }
    except: return None

def run_comprehensive_vacuum():
    print("--- STARTING POSITION-BASED DEBUG LOG ---")
    scraper = cloudscraper.create_scraper(browser='chrome')
    pdf_bytes = io.BytesIO(scraper.get(PDF_URL).content)

    TARGET_FUTS = ["BTC FUT", "MBT FUT", "BFF FUT"]
    W_FUT = {"BTC FUT": 1.0, "MBT FUT": 0.02, "BFF FUT": 0.004}
    W_OPT = ["BTC OPT", "MBT OPT", "BFF OPT"]

    futures_results, options_results = [], []
    trade_date = "Unknown Date"

    with pdfplumber.open(pdf_bytes) as pdf:
        active_f, in_opt, c_name, c_opt_month, side = None, False, "UNKNOWN", "UNKNOWN", "CALLS"

        for p_idx, page in enumerate(pdf.pages):
            text = page.extract_text() or ""
            if p_idx == 0:
                d_match = re.search(r'[A-Z][a-z]{2}, ([A-Z][a-z]{2} \d{2}, \d{4})', text)
                if d_match: trade_date = d_match.group(1)

            for line in text.split('\n'):
                clean = line.strip().upper()
                if not clean: continue

                # Identify Product Blocks
                if "FUT" in clean and "TOTAL" not in clean:
                    found_target = False
                    for f_key in TARGET_FUTS:
                        if f_key in clean:
                            active_f, in_opt = f_key, False
                            found_target = True
                            break
                    if not found_target: active_f = None

                for o_key in W_OPT:
                    if o_key in clean and "TOTAL" not in clean:
                        active_f, in_opt, c_name = None, True, o_key

                if "CALLS" in clean: side = "CALLS"
                elif "PUTS" in clean: side = "PUTS"

                m_match = re.search(r'\b(?:JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)\d{2}\b', clean)

                # Process Futures
                if active_f and m_match and "TOTAL" not in clean:
                    res = process_futures_block(active_f, clean)
                    if res: futures_results.append(res)

                # Process Options
                if in_opt:
                    if m_match: c_opt_month = m_match.group()
                    if "TOTAL" in clean:
                        res = process_options_total(c_name, c_opt_month, clean, side)
                        if res: options_results.append(res)

    # --- AGGREGATION ---
    f_sum, opt_sum = {}, {}
    for r in futures_results:
        m, w = r["Month"], W_FUT.get(r["Product"], 0)
        if m not in f_sum: f_sum[m] = {"av":0,"ao":0,"ad":0,"rv":0,"ro":0,"rd":0,"s":0,"c":0}

        # Only use BTC FUT for settlement price and change — never fall back to MBT/BFF prices
        if r["Product"] == "BTC FUT" and r["Sett"] > 0:
            f_sum[m]["s"], f_sum[m]["c"] = r["Sett"], r["Change"]

        f_sum[m]["av"] += r["Volume"] * w
        f_sum[m]["ao"] += r["OI"] * w
        f_sum[m]["ad"] += r["Delta"] * w
        if w < 1.0:
            f_sum[m]["rv"] += r["Volume"] * w
            f_sum[m]["ro"] += r["OI"] * w
            f_sum[m]["rd"] += r["Delta"] * w

    # --- OPTIONS SIZING ---
    # Contract sizes: BTC=5 BTC, MBT=0.1 BTC, BFF=0.02 BTC (1/50)
    # Normalise to BTC-contract equivalent (divide by 5):
    #   BTC OPT: 5/5  = 1.0
    #   MBT OPT: 0.1/5 = 0.02
    #   BFF OPT: 0.02/5 = 0.004  (1/50 BTC per contract)
    W_OPT_SIZE = {"BTC OPT": 1.0, "MBT OPT": 0.02, "BFF OPT": 0.004}

    for r in options_results:
        m = r["Month"]
        w = W_OPT_SIZE.get(r["Series"], 1.0)
        if m not in opt_sum: opt_sum[m] = {"total_vol": 0, "net_oi": 0, "net_delta": 0, "vc": 0, "vp": 0}
        v, oi, d = r["Volume"]*w, r["OI"]*w, to_int(r["Delta"])*w
        opt_sum[m]["total_vol"] += v
        if r["Side"] == "CALLS":
            opt_sum[m]["vc"] += v; opt_sum[m]["net_oi"] += oi; opt_sum[m]["net_delta"] += d
        else:
            opt_sum[m]["vp"] += v; opt_sum[m]["net_oi"] -= oi; opt_sum[m]["net_delta"] -= d

    # --- TELEGRAM ---
    tg_msg = [
        f"🟠 <b>BITCOIN - {trade_date}</b>",
        "",
        "<b>FUTURES (STANDARD UNITS)</b>",
        "<code>MO   |TYP|  ST  | CHG | VOL | OI  | ΔOI</code>",
    ]
# Sort the months and slice to keep only the first 6
    sorted_months = sorted(f_sum.keys(), key=get_month_score)[:6] 

    for m in sorted_months:
        s = f_sum[m]
        if s['s'] == 0 and s['av'] == 0 and s['ao'] == 0: continue
        tg_msg.append(f"<code>{m:5}|ALL|{s['s']:6.0f}|{s['c']:+6.0f}|{format_num(s['av']):>4}|{format_num(s['ao']):>5}|{format_num(s['ad']):>4}</code>")
        tg_msg.append(f"<code>{m:5}|RET|{s['s']:6.0f}|{s['c']:+6.0f}|{format_num(s['rv']):>4}|{format_num(s['ro']):>5}|{format_num(s['rd']):>4}</code>")
        tg_msg.append("-------------------------------")

    tg_msg.append("\n<b>OPTIONS SUMMARY</b>\n<code>MO    | VOL | P/C| OI  | ΔOI</code>")
    if not opt_sum:
        tg_msg.append("<code>No options data found</code>")
    else:
        for m in sorted(opt_sum.keys(), key=get_month_score):
            s = opt_sum[m]
            pc = s["vp"] / s["vc"] if s["vc"] > 0 else 0.0
            row = f"{m:5} |{format_num(s['total_vol']):>5}|{pc:4.2f}|{format_num(s['net_oi']):>5}|{format_num(s['net_delta']):>5}"
            tg_msg.append(f"<code>{row}</code>")

    requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", json={"chat_id": CHAT_ID, "text": "\n".join(tg_msg), "parse_mode": "HTML"})
    print("--- DEBUG LOG COMPLETE (MESSAGE SENT) ---")

if __name__ == "__main__":
    run_comprehensive_vacuum()
