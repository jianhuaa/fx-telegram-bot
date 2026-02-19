import cloudscraper
import pdfplumber
import io
import re
import requests

# --- CONFIGURATION ---
FUT_URL = "https://www.cmegroup.com/daily_bulletin/current/Section62_Metals_Futures_Products.pdf"
OPT_URL = "https://www.cmegroup.com/daily_bulletin/current/Section64_Metals_Option_Products.pdf"
TELEGRAM_TOKEN = "8577879935:AAEpSjAz4wdcZ9Lb7AJpURRk8haADlPCbHo"
CHAT_ID = "876384974"

W_FUT = {
    "GC": 1.0, "QO": 0.5, "MGC": 0.1, "1OZ": 0.01,
    "SI": 1.0, "QI": 0.5, "SIL": 0.2, "SIC": 0.02,
    "HG": 1.0, "QC": 0.5, "MHG": 0.1,
    "PL": 1.0
}

W_OPT = {
    "OMG OPT": 0.1, 
    "WMG WED": 0.1, 
    "FMG OPT": 0.1
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

def get_precision_format(sym):
    if any(x in sym for x in ["GC", "QO", "MGC", "1OZ"]): return ".0f"
    if "PL" in sym: return ".1f"
    if any(x in sym for x in ["HG", "QC", "MHG"]): return ".3f"
    return ".2f"

def get_month_score(month_str):
    months = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]
    try:
        m, y = month_str[:3].upper(), int(month_str[3:])
        return y * 100 + (months.index(m) + 1)
    except: return 0

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

def is_signed(token):
    return token[0] in ('+', '-')

def parse_metals_line(product_code, line):
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
        delta_val = to_float(tokens[-1])
        oi_val = to_float(tokens[-2])
        vol_tokens = tokens[chg_idx+1 : -2]
        vol = sum(int(to_float(v)) for v in vol_tokens if v != "----")
        return {"Symbol": product_code, "Month": month, "Sett": sett, "Chg": chg, "Vol": vol, "OI": oi_val, "Delta": delta_val}
    except: return None

def parse_options_total(clean):
    tokens = normalize_tokens(clean.split())
    nums = [t for t in tokens if re.match(r'^[+\-]?\d[\d,]*$', t) and '.' not in t]
    n = len(nums)
    if n == 0: return None
    elif n == 1:
        vol, oi, delta = 0, int(to_float(nums[0])), 0
    elif n == 2:
        v0 = int(to_float(nums[0]))
        v1 = int(to_float(nums[1]))
        if is_signed(nums[1]): vol, oi, delta = v0, 0, v1
        elif nums[1] == '0': vol, oi, delta = 0, v0, 0
        else: vol, oi, delta = v0, v1, 0
    elif n == 3:
        vol, oi, delta = int(to_float(nums[0])), int(to_float(nums[1])), int(to_float(nums[2]))
    elif n == 4:
        vol, oi, delta = int(to_float(nums[0])) + int(to_float(nums[1])), int(to_float(nums[2])), int(to_float(nums[3]))
    else:
        vol, oi, delta = sum(int(to_float(x)) for x in nums[:-2]), int(to_float(nums[-2])), int(to_float(nums[-1]))
    return vol, oi, delta

def run_combined_vacuum():
    scraper = cloudscraper.create_scraper(browser='chrome')
    
    # --- PART 1: SCRAPE OPTIONS ---
    print("=" * 80)
    print("SCRAPING OPTIONS: G8 METALS MASTER")
    print("=" * 80)
    
    resp_o = scraper.get(OPT_URL)
    results_o = []
    ALL_ANCHORS = {"GOLD OPTIONS ON FUTURES": "GOLD", "SILVER OPTIONS ON FUTURES": "SILVER", "COPPER OPTIONS ON FUTURES": "COPPER", "PLATINUM OPTIONS ON FUTURES": "PLATINUM"}
    TARGETS = {
        "GOLD": ["WMG WED", "OMG OPT", "OG4 PUT", "OG4 CALL", "OG3 PUT", "OG3 CALL", "OG2 PUT", "OG2 CALL", "OG1 PUT", "OG1 CALL", "OG PUT", "OG CALL", "GWW WED", "GWT TUE", "GWR THU", "GMW MON", "FMG OPT"],
        "SILVER": ["RWS THU", "SMW MON", "SO CALL", "SO PUT", "SO1 CALL", "SO1 PUT", "SO2 CALL", "SO2 PUT", "SO3 CALL", "SO3 PUT", "SO4 CALL", "SO4 PUT", "SWW WED", "TWS TUE"],
        "COPPER": ["HMW MON", "HWR THU", "HWT TUE", "HWW WED", "HX CALL", "HX PUT", "HXE CALL", "HXE PUT"],
        "PLATINUM": ["PO CALL", "PO PUT", "PLW OOF"]
    }
    with pdfplumber.open(io.BytesIO(resp_o.content)) as pdf:
        active_metal, cur_product, cur_side, cur_mo = None, None, "CALLS", "UNKNOWN"
        last_printed_metal, last_printed_product = None, None
        
        for p_idx, page in enumerate(pdf.pages, start=1):
            text = page.extract_text() or ""
            for line in text.split('\n'):
                clean = line.strip().upper()
                if "OPTIONS EOO'S AND BLOCKS" in clean: 
                    print(f"\n>>> STOP: EOO/EFP/Blocks detected P{p_idx}: 'OPTIONS EOO'S AND BLOCKS'\n")
                    break
                
                for anchor, m_name in ALL_ANCHORS.items():
                    if anchor in clean: 
                        active_metal = m_name
                        if active_metal != last_printed_metal:
                            print(f"\n>>> [ANCHOR FOUND] Entering {active_metal} Section on Page {p_idx}")
                            last_printed_metal = active_metal

                if not active_metal: continue
                
                for target in TARGETS.get(active_metal, []):
                    if target in clean:
                        cur_product = target
                        cur_side = "CALLS" if "CALL" in target else "PUTS"
                        print(f"\n>>> Locked onto Product: {cur_product} ({cur_side})")
                        last_printed_product = cur_product

                if not cur_product: continue
                
                if "TOTAL" not in clean:
                    if re.search(r'\bCALLS?\b', clean): cur_side = "CALLS"
                    elif re.search(r'\bPUTS?\b', clean): cur_side = "PUTS"
                
                m_match = re.search(r'\b(?:JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)\d{2}\b', clean)
                if m_match: cur_mo = m_match.group()
                
                if clean.startswith("TOTAL"):
                    parsed = parse_options_total(clean)
                    if parsed:
                        vol, oi, delta = parsed
                        results_o.append({"Metal": active_metal, "Product": cur_product, "Month": cur_mo, "Side": cur_side, "Vol": vol, "OI": oi, "Delta": delta})
                        met_sh = active_metal[:3].upper()
                        print(f"[OPT] P {p_idx:2} | {met_sh} | {cur_product:<9} {cur_mo} | {cur_side:<5} | VOL: {vol:>6.0f} | OI: {oi:>8.0f} | ΔOI: {delta:>+7.0f}")

    # --- PART 2: AGGREGATING OPTIONS SCALING ---
    print("\n" + "=" * 80)
    print("AGGREGATING OPTIONS REPORTS (WITH SCALING)")
    print("=" * 80)
    
    METALS_ORDER = ["GOLD", "SILVER", "COPPER", "PLATINUM"]
    o_mos_master = {m: {} for m in METALS_ORDER}
    
    for o in results_o:
        m_name = o["Metal"]
        mo = o["Month"]
        if mo not in o_mos_master[m_name]: 
            o_mos_master[m_name][mo] = {"VC": 0, "VP": 0, "ON": 0, "DN": 0}
        
        w = W_OPT.get(o["Product"], 1.0)
        
        if o["Side"] == "CALLS":
            o_mos_master[m_name][mo]["VC"] += o["Vol"] * w
            o_mos_master[m_name][mo]["ON"] += o["OI"] * w
            o_mos_master[m_name][mo]["DN"] += o["Delta"] * w
        else:
            o_mos_master[m_name][mo]["VP"] += o["Vol"] * w
            o_mos_master[m_name][mo]["ON"] -= o["OI"] * w
            o_mos_master[m_name][mo]["DN"] -= o["Delta"] * w

    for metal in METALS_ORDER:
        if o_mos_master[metal]:
            print(f"\n--- {metal} SUMMARY ---")
            for mo in sorted(o_mos_master[metal].keys(), key=get_month_score)[:5]:
                o_s = o_mos_master[metal][mo]
                tot_vol = o_s["VC"] + o_s["VP"]
                pc = o_s["VP"] / o_s["VC"] if o_s["VC"] > 0 else 0.0
                print(f"{mo} | VOL: {tot_vol:>7.1f} | P/C: {pc:4.2f} | NET OI: {o_s['ON']:>8.1f} | NET ΔOI: {o_s['DN']:>7.1f}")
                
    print("^^options")
    print("\nvv futures")
    print("=" * 80)
    print("CLEAN METALS VACUUM: NO GHOST BLOCKS")
    print("=" * 80)

    # --- PART 3: SCRAPE FUTURES ---
    resp_f = scraper.get(FUT_URL)
    results_f, trade_date = [], "Unknown"
    FUT_MAP = {
        "1 OUNCE GOLD": "1OZ", "COMEX GOLD": "GC", "MICRO GOLD": "MGC", "E-MINI GOLD": "QO",
        "COMEX SILVER": "SI", "E-MINI SILVER": "QI", "MICRO SILVER": "SIL", "100-OUNCE SILVER": "SIC",
        "COMEX COPPER": "HG", "E-MINI COPPER": "QC", "MICRO COPPER": "MHG", "NYMEX PLATINUM": "PL"
    }
    
    with pdfplumber.open(io.BytesIO(resp_f.content)) as pdf:
        active_code = None
        last_printed_code = None
        
        for p_idx, page in enumerate(pdf.pages, start=1):
            text = page.extract_text() or ""
            if p_idx == 1:
                d_m = re.search(r'[A-Z][a-z]{2}, ([A-Z][a-z]{2} \d{2}, \d{4})', text)
                if d_m: trade_date = d_m.group(1)
            
            if "METALS CONTRACTS LAST TRADE DATES" in text.upper(): break
            
            for line in text.split('\n'):
                clean = line.strip().upper()
                for head, code in FUT_MAP.items():
                    if head in clean and "TOTAL" not in clean:
                        if code == "HG" and "HGS" in clean: continue
                        active_code = code
                        
                if active_code and "TOTAL" in clean and active_code in clean: 
                    active_code = None
                    continue
                
                if active_code and re.match(r'^[A-Z]{3}\d{2}', clean):
                    if active_code != last_printed_code:
                        print(f"\n>>> Entering Block: {active_code}")
                        last_printed_code = active_code
                        
                    res = parse_metals_line(active_code, clean)
                    if res: 
                        results_f.append(res)
                        p_fmt = get_precision_format(res["Symbol"])
                        
                        # Fix for ValueError: Format string handles float to string properly now
                        sett_str = f"{res['Sett']:{p_fmt}}"
                        chg_str = f"{res['Chg']:+{p_fmt}}"
                        print(f"[FUT] P{p_idx} | {active_code:<4} {res['Month']} | SETT: {sett_str:>8} | CHG: {chg_str:>6} | VOL: {res['Vol']:>6.0f} | OI: {res['OI']:>7.0f} | ΔOI: {res['Delta']:>+6.0f}")

    # --- PART 4: TELEGRAM PAYLOAD COMPILATION AND FUTURES SUMMARY ---
    print("\n" + "=" * 80)
    print("AGGREGATING FUTURES REPORTS (WITH SCALING)")
    print("=" * 80)
    
    final_msg = [f"⚒️ <b>METALS REPORT - {trade_date}</b>", ""]
    GROUPS = [
        ("GOLD", ["GC", "QO", "MGC", "1OZ"]),
        ("SILVER", ["SI", "QI", "SIL", "SIC"]),
        ("PLATINUM", ["PL"]),
        ("COPPER", ["HG", "QC", "MHG"])
    ]

    for metal_name, syms in GROUPS:
        f_sum = {}
        p = get_precision_format(syms[0])
        for r in results_f:
            if r["Symbol"] in syms:
                m, w = r["Month"], W_FUT.get(r["Symbol"], 1.0)
                if m not in f_sum: f_sum[m] = {"av":0,"ao":0,"ad":0,"rv":0,"ro":0,"rd":0,"s":0,"c":0}
                if w == 1.0 and (r["Vol"] > 0 or f_sum[m]["s"] == 0): f_sum[m]["s"], f_sum[m]["c"] = r["Sett"], r["Chg"]
                f_sum[m]["av"] += r["Vol"] * w; f_sum[m]["ao"] += r["OI"] * w; f_sum[m]["ad"] += r["Delta"] * w
                if w < 1.0: f_sum[m]["rv"] += r["Vol"] * w; f_sum[m]["ro"] += r["OI"] * w; f_sum[m]["rd"] += r["Delta"] * w
        
        if f_sum:
            # Print the aggregated Futures Summary to the debug console
            print(f"\n--- {metal_name} FUTURES SUMMARY ---")
            for m in sorted(f_sum.keys(), key=get_month_score)[:5]:
                s = f_sum[m]
                sett_str = f"{s['s']:{p}}"
                chg_str = f"{s['c']:+{p}}"
                print(f"{m:5} | SETT: {sett_str:>8} | CHG: {chg_str:>8} | VOL: {s['av']:>9.1f} | OI: {s['ao']:>10.1f} | ΔOI: {s['ad']:>8.1f}")
            
            # Prepare Telegram payload for Futures
            final_msg.append(f"<b>{metal_name} FUTURES (STD UNITS)</b>")
            final_msg.append("<code>MO   |TYP|  SETT |  CHG | VOL| OI | ΔOI</code>")
            for m in sorted(f_sum.keys(), key=get_month_score)[:3]:
                s = f_sum[m]
                final_msg.append(f"<code>{m:5}|ALL|{s['s']:7{p}}|{s['c']:+6{p}}|{format_num(s['av']):>4}|{format_num(s['ao']):>4}|{format_num(s['ad']):>4}</code>")
                final_msg.append(f"<code>{m:5}|RET|{s['s']:7{p}}|{s['c']:+6{p}}|{format_num(s['rv']):>4}|{format_num(s['ro']):>4}|{format_num(s['rd']):>4}</code>")
        
        if o_mos_master.get(metal_name):
            # Prepare Telegram payload for Options
            final_msg.append(f"<b>{metal_name} OPTIONS</b>")
            final_msg.append("<code>MO    |  VOL | P/C |  OI  | ΔOI </code>")
            for mo in sorted(o_mos_master[metal_name].keys(), key=get_month_score)[:3]:
                o_s = o_mos_master[metal_name][mo]
                pc = o_s["VP"] / o_s["VC"] if o_s["VC"] > 0 else 0.0
                final_msg.append(f"<code>{mo:5} |{format_num(o_s['VC']+o_s['VP']):>5} |{pc:4.2f} |{format_num(o_s['ON']):>6}|{format_num(o_s['DN']):>5}</code>")
        
        final_msg.append("-" * 42)

    requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", 
                  json={"chat_id": CHAT_ID, "text": "\n".join(final_msg), "parse_mode": "HTML"})
    
    print("\nDone. Message Sent.")

if __name__ == "__main__":
    run_combined_vacuum()
