import cloudscraper
import pdfplumber
import io
import re
import requests

# --- CONFIGURATION ---
FUT_URL = "https://www.cmegroup.com/daily_bulletin/current/Section61_Energy_Futures_Products.pdf"
OPT_URL = "https://www.cmegroup.com/daily_bulletin/current/Section63_Energy_Options_Products.pdf"

TELEGRAM_TOKEN = "8577879935:AAEpSjAz4wdcZ9Lb7AJpURRk8haADlPCbHo"
CHAT_ID = "876384974"

# --- SCALING WEIGHTS ---
W_FUT = {
    "CL": 1.0, "26": 1.0, "QM": 0.5, "MCL": 0.1,
    "BZ": 1.0, "MBC": 0.5, "MDB": 0.1,
    "NG": 1.0, "HH": 1.0, "NN": 1.0, "HP": 1.0, "NPG": 1.0, "QG": 0.25, "MNG": 0.1,
    "RB": 1.0, "RT": 1.0, "QU": 0.5, "MRB": 0.1,
    "HO": 1.0, "BH": 1.0, "QH": 0.5, "MHO": 0.1
}

W_OPT = {
    "LO CALL": 1.0, "LO PUT": 1.0,
    "LC CALL": 1.0, "LC PUT": 1.0,
    "LO1 CALL": 1.0, "LO1 PUT": 1.0, "LO2 CALL": 1.0, "LO2 PUT": 1.0,
    "LO3 CALL": 1.0, "LO3 PUT": 1.0, "LO4 CALL": 1.0, "LO4 PUT": 1.0,
    "MLW OPT": 1.0, "NLC OPT": 1.0, "WLW OPT": 1.0, "XLC OPT": 1.0,
    "MCO OPT": 0.1, "MWW OPT": 0.1,
    "BZO CALL": 1.0, "BZO PUT": 1.0,
    "ON CALL": 1.0, "ON PUT": 1.0,
    "LN CALL": 1.0, "LN PUT": 1.0,
    "E7 CALL": 1.0, "E7 PUT": 1.0,
    "HNW OPT": 1.0, "INW OPT": 1.0, "JNW OPT": 1.0, "KNW OPT": 1.0,
    "KD CALL": 1.0, "KD PUT": 1.0,
    "OB CALL": 1.0, "OB PUT": 1.0,
    "RF CALL": 1.0, "RF PUT": 1.0,
    "OH CALL": 1.0, "OH PUT": 1.0,
    "LB CALL": 1.0, "LB PUT": 1.0
}

# --- PDF HEADER TARGET MAPS ---
FUT_MAP = {
    "CL FUT NYMEX CRUDE OIL (PHYSICAL)": "CL",
    "26 FUT CRUDE OIL LAST DAY FINANCIAL FUT": "26",
    "QM FUT E-MINI CRUDE OIL FUTURES": "QM",
    "MCL FUT MICRO CRUDE OIL FUTURES": "MCL",
    "BZ FUT NYMEX BRENT OIL LAST DAY FUTURES": "BZ",
    "MBC FUT MINI BRENT FINANCIAL FUTURES": "MBC",
    "MDB FUT MINI DATED BRENT (PLATTS) FINANCIAL": "MDB",
    "NG FUT NATURAL GAS HENRY HUB (PHYSICAL)": "NG",
    "NN FUT HENRY HUB": "NN",
    "HH FUT HENRY HUB NG LAST DAY FINANCIAL": "HH",
    "HP FUT NYMEX NATURAL GAS FUTURES": "HP",
    "NPG FUT HENRY HUB PENULTIMATE FUT": "NPG",
    "QG FUT E-MINI NATURAL GAS": "QG",
    "MNG FUT MICRO HENRY HUB NATURAL GAS FUTURES": "MNG",
    "RB FUT NYMEX NY HARBOR GAS (RBOB) (PHY)": "RB",
    "RT FUT NYMEX RBOB GASOLINE FUTURES": "RT",
    "QU FUT E-MINI GASOLINE FUTURES": "QU",
    "MRB FUT MICRO RBOB GASOLINE FUTURE": "MRB",
    "HO FUT NYMEX HEATING OIL (PHYSICAL)": "HO",
    "BH FUT NYMEX HEATING OIL FUTURES": "BH",
    "QH FUT E-MINI HEATING OIL FUTURES": "QH",
    "MHO FUT MICRO NY HARBOR ULSD FUT": "MHO"
}

# OPTIONS MAPPING - product code -> asset group
OPT_MAPPING = {
    # WTI Crude
    "LO CALL": "WTI CRUDE",    "LO PUT": "WTI CRUDE",
    "LC CALL": "WTI CRUDE",    "LC PUT": "WTI CRUDE",
    "LO1 CALL": "WTI CRUDE",   "LO1 PUT": "WTI CRUDE",
    "LO2 CALL": "WTI CRUDE",   "LO2 PUT": "WTI CRUDE",
    "LO3 CALL": "WTI CRUDE",   "LO3 PUT": "WTI CRUDE",
    "LO4 CALL": "WTI CRUDE",   "LO4 PUT": "WTI CRUDE",
    "MLW OPT": "WTI CRUDE",    "NLC OPT": "WTI CRUDE",
    "WLW OPT": "WTI CRUDE",    "XLC OPT": "WTI CRUDE",
    "MCO OPT": "WTI CRUDE",    "MWW OPT": "WTI CRUDE",

    # Brent Crude
    "BZO CALL": "BRENT CRUDE", "BZO PUT": "BRENT CRUDE",

    # Natural Gas
    "ON CALL": "NATURAL GAS",  "ON PUT": "NATURAL GAS",
    "LN CALL": "NATURAL GAS",  "LN PUT": "NATURAL GAS",
    "E7 CALL": "NATURAL GAS",  "E7 PUT": "NATURAL GAS",
    "KD CALL": "NATURAL GAS",  "KD PUT": "NATURAL GAS",
    "HNW OPT": "NATURAL GAS",  "INW OPT": "NATURAL GAS",
    "JNW OPT": "NATURAL GAS",  "KNW OPT": "NATURAL GAS",

    # Gasoline
    "OB CALL": "GASOLINE",     "OB PUT": "GASOLINE",
    "RF CALL": "GASOLINE",     "RF PUT": "GASOLINE",

    # Heating Oil
    "OH CALL": "HEATING OIL",  "OH PUT": "HEATING OIL",
    "LB CALL": "HEATING OIL",  "LB PUT": "HEATING OIL"
}

# Pre-compile regex patterns for each target (word-boundary, ordered match)
OPT_PATTERNS = {}
for target in OPT_MAPPING:
    words = target.split()
    pattern = r'\b' + r'\s+'.join(re.escape(w) for w in words) + r'\b'
    OPT_PATTERNS[target] = re.compile(pattern)

# Product header signature (verified against all 222 headers in the bulletin):
#   <CODE> <CALL|PUT|OPT|OOF> <DESCRIPTION...>
#   CODE  = first token, one or more uppercase letters/digits  (e.g. BZO, E7, 9C, 4J)
#   TYPE  = second token, exactly one of CALL / PUT / OPT / OOF
#   DESC  = at least one more token after TYPE
# This pattern matches every real product header and nothing else in the PDF.
PRODUCT_HEADER_RE = re.compile(r'^[A-Z0-9]+\s+(CALL|PUT|OPT|OOF)\s+\S+')

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
    if sym in ["NG", "QG", "MNG", "HH", "NN", "HP", "NPG"]: return ".3f"
    if sym in ["RB", "QU", "MRB", "RT", "HO", "QH", "BH", "MHO"]: return ".3f"
    return ".2f"

def get_month_score(month_str):
    months = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN",
              "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]
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
        return {"Symbol": product_code, "Month": month, "Sett": sett,
                "Chg": chg, "Vol": vol, "OI": oi_val, "Delta": delta_val}
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
        vol = int(to_float(nums[0])) + int(to_float(nums[1]))
        oi = int(to_float(nums[2]))
        delta = int(to_float(nums[3]))
    else:
        vol = sum(int(to_float(x)) for x in nums[:-2])
        oi = int(to_float(nums[-2]))
        delta = int(to_float(nums[-1]))
    return vol, oi, delta


def run_combined_vacuum():
    scraper = cloudscraper.create_scraper(browser='chrome')

    # =========================================================================
    # PART 1: SCRAPE OPTIONS
    # =========================================================================
    print("=" * 80)
    print("SCRAPING OPTIONS: G8 ENERGY MASTER")
    print("=" * 80)

    resp_o = scraper.get(OPT_URL)
    results_o = []

    with pdfplumber.open(io.BytesIO(resp_o.content)) as pdf:
        active_asset  = None
        cur_product   = None
        cur_side      = "CALLS"
        cur_mo        = "UNKNOWN"
        last_printed_product = None
        stop_parsing  = False

        for p_idx, page in enumerate(pdf.pages, start=1):
            if stop_parsing: break
            text = page.extract_text() or ""

            for line in text.split('\n'):
                clean = line.strip().upper()

                # ── Kill-switch ──────────────────────────────────────────────
                if "OPTIONS EOO'S AND BLOCKS" in clean:
                    print(f"\n>>> STOP: EOO/Blocks detected P{p_idx}\n")
                    stop_parsing = True
                    break

                # ── Header detection ─────────────────────────────────────────
                if PRODUCT_HEADER_RE.match(clean):
                    matched = False
                    for target, pattern in OPT_PATTERNS.items():
                        if pattern.search(clean):
                            active_asset = OPT_MAPPING[target]
                            cur_product  = target
                            cur_side     = ("CALLS" if "CALL" in target
                                            else "PUTS" if "PUT" in target
                                            else "OPT")
                            if cur_product != last_printed_product:
                                print(f"\n>>> Locked onto Product: "
                                      f"{cur_product} ({cur_side}) -> {active_asset}")
                                last_printed_product = cur_product
                            matched = True
                            break

                    if not matched:
                        if cur_product is not None:
                            print(f">>> [SKIP] P{p_idx} unrecognised header, "
                                  f"releasing '{cur_product}': {clean[:60]}")
                        active_asset = None
                        cur_product  = None

                if not cur_product:
                    continue

                # ── Track CALLS / PUTS sub-headers inside a block ────────────
                if "TOTAL" not in clean:
                    if re.search(r'\bCALLS?\b', clean):
                        cur_side = "CALLS"
                    elif re.search(r'\bPUTS?\b', clean):
                        cur_side = "PUTS"

                # ── Track current expiry month ───────────────────────────────
                m_match = re.search(
                    r'\b(?:JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)\d{2}\b',
                    clean)
                if m_match:
                    cur_mo = m_match.group()

                # ── Capture TOTAL rows ───────────────────────────────────────
                if clean.startswith("TOTAL"):
                    parsed = parse_options_total(clean)
                    if parsed:
                        vol, oi, delta = parsed
                        results_o.append({
                            "Asset":   active_asset,
                            "Product": cur_product,
                            "Month":   cur_mo,
                            "Side":    cur_side,
                            "Vol":     vol,
                            "OI":      oi,
                            "Delta":   delta
                        })
                        asset_sh = active_asset[:3].upper() if active_asset else "UNK"
                        print(f"[OPT] P {p_idx:3} | {asset_sh} | "
                              f"{cur_product:<9} {cur_mo} | {cur_side:<5} | "
                              f"VOL: {vol:>6.0f} | OI: {oi:>8.0f} | "
                              f"ΔOI: {delta:>+7.0f}")

    # =========================================================================
    # PART 2: AGGREGATE OPTIONS (WITH SCALING)
    # =========================================================================
    print("\n" + "=" * 80)
    print("AGGREGATING OPTIONS REPORTS (WITH SCALING)")
    print("=" * 80)

    ASSETS_ORDER = ["WTI CRUDE", "BRENT CRUDE", "NATURAL GAS", "GASOLINE", "HEATING OIL"]
    o_mos_master = {a: {} for a in ASSETS_ORDER}

    for o in results_o:
        a_name = o["Asset"]
        mo     = o["Month"]
        if mo not in o_mos_master[a_name]:
            o_mos_master[a_name][mo] = {"VC": 0, "VP": 0, "ON": 0, "DN": 0}

        w = W_OPT.get(o["Product"], 1.0)

        if o["Side"] == "CALLS":
            o_mos_master[a_name][mo]["VC"] += o["Vol"] * w
            o_mos_master[a_name][mo]["ON"] += o["OI"]  * w
            o_mos_master[a_name][mo]["DN"] += o["Delta"] * w
        else:
            o_mos_master[a_name][mo]["VP"] += o["Vol"] * w
            o_mos_master[a_name][mo]["ON"] -= o["OI"]  * w
            o_mos_master[a_name][mo]["DN"] -= o["Delta"] * w

    # FILTER BRENT OPTIONS BY WTI FRONT MONTH
    wti_opt_front_score = 0
    if o_mos_master.get("WTI CRUDE"):
        sorted_wti = sorted(o_mos_master["WTI CRUDE"].keys(), key=get_month_score)
        if sorted_wti:
            wti_opt_front_score = get_month_score(sorted_wti[0])

    if wti_opt_front_score > 0 and o_mos_master.get("BRENT CRUDE"):
        keys_to_remove = []
        for m in o_mos_master["BRENT CRUDE"].keys():
            if get_month_score(m) <= wti_opt_front_score:
                keys_to_remove.append(m)
        for m in keys_to_remove:
            del o_mos_master["BRENT CRUDE"][m]

    for asset in ASSETS_ORDER:
        if o_mos_master[asset]:
            print(f"\n--- {asset} SUMMARY ---")
            for mo in sorted(o_mos_master[asset].keys(), key=get_month_score)[:5]:
                o_s    = o_mos_master[asset][mo]
                tot_vol = o_s["VC"] + o_s["VP"]
                
                # Enforce a strict 5-character width for console alignment
                if o_s["VC"] == 0 and o_s["VP"] == 0:
                    pc_str = "  N/A"
                elif o_s["VC"] == 0 and o_s["VP"] > 0:
                    pc_str = "  INF"
                else:
                    pc_str = f"{(o_s['VP'] / o_s['VC']):>5.2f}"
                
                print(f"{mo} | VOL: {tot_vol:>7.1f} | P/C: {pc_str} | "
                      f"NET OI: {o_s['ON']:>8.1f} | NET ΔOI: {o_s['DN']:>7.1f}")

    print("\n^^options")
    print("\nvv futures")
    print("=" * 80)
    print("CLEAN ENERGY VACUUM: NO GHOST BLOCKS")
    print("=" * 80)

    # =========================================================================
    # PART 3: SCRAPE FUTURES
    # =========================================================================
    resp_f = scraper.get(FUT_URL)
    results_f, trade_date = [], "Unknown"

    with pdfplumber.open(io.BytesIO(resp_f.content)) as pdf:
        active_code       = None
        last_printed_code = None

        for p_idx, page in enumerate(pdf.pages, start=1):
            text = page.extract_text() or ""
            if p_idx == 1:
                d_m = re.search(r'[A-Z][a-z]{2}, ([A-Z][a-z]{2} \d{2}, \d{4})', text)
                if d_m: trade_date = d_m.group(1)

            if "ENERGY CONTRACTS LAST TRADE DATES" in text.upper(): break

            for line in text.split('\n'):
                clean = line.strip().upper()
                for head, code in FUT_MAP.items():
                    if head in clean and "TOTAL" not in clean:
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
                        p_fmt    = get_precision_format(res["Symbol"])
                        sett_str = f"{res['Sett']:{p_fmt}}"
                        chg_str  = f"{res['Chg']:+{p_fmt}}"
                        print(f"[FUT] P{p_idx} | {active_code:<4} {res['Month']} | "
                              f"SETT: {sett_str:>8} | CHG: {chg_str:>6} | "
                              f"VOL: {res['Vol']:>6.0f} | OI: {res['OI']:>7.0f} | "
                              f"ΔOI: {res['Delta']:>+6.0f}")

    # =========================================================================
    # PART 4: TELEGRAM PAYLOAD + FUTURES SUMMARY
    # =========================================================================
    print("\n" + "=" * 80)
    print("AGGREGATING FUTURES REPORTS (WITH SCALING)")
    print("=" * 80)

    final_msg = [f"⚡ <b>ENERGY REPORT - {trade_date}</b>", ""]

    GROUPS = [
        ("WTI CRUDE",   ["CL", "26", "QM", "MCL"]),
        ("BRENT CRUDE", ["BZ", "MBC", "MDB"]),
        ("NATURAL GAS", ["NG", "HH", "NN", "HP", "NPG", "QG", "MNG"]),
        ("GASOLINE",    ["RB", "RT", "QU", "MRB"]),
        ("HEATING OIL", ["HO", "BH", "QH", "MHO"])
    ]

    sett_map = {"CL": {}, "BZ": {}, "RB": {}, "HO": {}}
    wti_fut_front_score = 0  # To track the global front month

    for asset_name, syms in GROUPS:
        f_sum = {}
        p = get_precision_format(syms[0])

        for r in results_f:
            if r["Symbol"] in syms:
                m, w = r["Month"], W_FUT.get(r["Symbol"], 1.0)

                if r["Symbol"] in sett_map:
                    sett_map[r["Symbol"]][m] = r["Sett"]

                if m not in f_sum:
                    f_sum[m] = {"av": 0, "ao": 0, "ad": 0,
                                "rv": 0, "ro": 0, "rd": 0, "s": 0, "c": 0}
                if w == 1.0 and (r["Vol"] > 0 or f_sum[m]["s"] == 0):
                    f_sum[m]["s"], f_sum[m]["c"] = r["Sett"], r["Chg"]
                f_sum[m]["av"] += r["Vol"] * w
                f_sum[m]["ao"] += r["OI"]  * w
                f_sum[m]["ad"] += r["Delta"] * w
                if w < 1.0:
                    f_sum[m]["rv"] += r["Vol"] * w
                    f_sum[m]["ro"] += r["OI"]  * w
                    f_sum[m]["rd"] += r["Delta"] * w

        # FILTER BRENT FUTURES BY WTI FRONT MONTH
        if asset_name == "WTI CRUDE" and f_sum:
            sorted_wti = sorted(f_sum.keys(), key=get_month_score)
            if sorted_wti:
                wti_fut_front_score = get_month_score(sorted_wti[0])

        if asset_name == "BRENT CRUDE" and wti_fut_front_score > 0:
            keys_to_remove = []
            for m in f_sum.keys():
                if get_month_score(m) <= wti_fut_front_score:
                    keys_to_remove.append(m)
            
            for m in keys_to_remove:
                del f_sum[m]

        if f_sum:
            print(f"\n--- {asset_name} FUTURES SUMMARY ---")
            for m in sorted(f_sum.keys(), key=get_month_score)[:5]:
                s        = f_sum[m]
                sett_str = f"{s['s']:{p}}"
                chg_str  = f"{s['c']:+{p}}"
                print(f"{m:5} | SETT: {sett_str:>8} | CHG: {chg_str:>8} | "
                      f"VOL: {s['av']:>9.1f} | OI: {s['ao']:>10.1f} | "
                      f"ΔOI: {s['ad']:>8.1f}")

            final_msg.append(f"<b>{asset_name} FUTURES</b>")
            final_msg.append("<code>MO   |TYP|  SETT |  CHG | VOL| OI | ΔOI</code>")
            
            for m in sorted(f_sum.keys(), key=get_month_score)[:3]:
                s = f_sum[m]
                final_msg.append(
                    f"<code>{m:5}|ALL|{s['s']:7{p}}|{s['c']:+6{p}}"
                    f"|{format_num(s['av']):>4}|{format_num(s['ao']):>4}"
                    f"|{format_num(s['ad']):>4}</code>")
                
                final_msg.append(
                    f"<code>{m:5}|RET|{s['s']:7{p}}|{s['c']:+6{p}}"
                    f"|{format_num(s['rv']):>4}|{format_num(s['ro']):>4}"
                    f"|{format_num(s['rd']):>4}</code>")

        if o_mos_master.get(asset_name):
            final_msg.append("<code>  -- OPTIONS -- </code>")
            # --- NEW EXPLICIT LOGIC: Tightened header spacing for strict alignment ---
            final_msg.append("<code>MO   |   VOL|  P/C|    OI|  ΔOI</code>")
            
            for mo in sorted(o_mos_master[asset_name].keys(), key=get_month_score)[:4]:
                o_s = o_mos_master[asset_name][mo]
                
                # Enforce a strict 5-character width for Telegram alignment
                if o_s["VC"] == 0 and o_s["VP"] == 0:
                    pc_str = "  N/A"
                elif o_s["VC"] == 0 and o_s["VP"] > 0:
                    pc_str = "  INF"
                else:
                    pc_str = f"{(o_s['VP'] / o_s['VC']):>5.2f}"

                # Extract and explicitly format the remaining variables
                vol_str = format_num(o_s['VC'] + o_s['VP'])
                oi_str  = format_num(o_s['ON'])
                doi_str = format_num(o_s['DN'])

                # Align variables mathematically to match the exact character count of the header
                final_msg.append(
                    f"<code>{mo:5}|{vol_str:>6}|{pc_str}|{oi_str:>6}|{doi_str:>5}</code>")
            # -------------------------------------------------------------------------

        if f_sum or o_mos_master.get(asset_name):
            final_msg.append("-" * 42)

    # =========================================================================
    # PART 5: REFINERY MARGINS (CRACK SPREADS)
    # =========================================================================
    all_mos_set = set(sett_map["RB"].keys()).intersection(set(sett_map["HO"].keys()))
    all_mos     = sorted(list(all_mos_set), key=get_month_score)[:3]

    if all_mos:
        print("\n--- REFINERY MARGINS (CRACK SPREADS) ---")

        final_msg.append("<b>3-2-1 MACRO SPREADS ($/BBL)</b>")
        final_msg.append("<code>MO   | WTI(US) | BRT(GLB)</code>")
        for m in all_mos:
            rb_s = sett_map["RB"][m]
            ho_s = sett_map["HO"][m]
            wti_c_str = " N/A  "
            brt_c_str = " N/A  "
            if m in sett_map["CL"]:
                cl_s      = sett_map["CL"][m]
                wti_c     = ((2 * rb_s * 42) + (1 * ho_s * 42) - (3 * cl_s)) / 3
                wti_c_str = f"${wti_c:5.2f}"
            if m in sett_map["BZ"]:
                bz_s      = sett_map["BZ"][m]
                brt_c     = ((2 * rb_s * 42) + (1 * ho_s * 42) - (3 * bz_s)) / 3
                brt_c_str = f"${brt_c:5.2f}"
            print(f"{m:5} | 3-2-1 WTI: {wti_c_str} | 3-2-1 BRENT: {brt_c_str}")
            final_msg.append(f"<code>{m:5}| {wti_c_str}  |  {brt_c_str} </code>")

        final_msg.append("-" * 42)

        final_msg.append("<b>1:1 PRODUCT CRACKS ($/BBL)</b>")
        final_msg.append("<code>MO   | GAS/WTI| HO/WTI | GAS/BRT| HO/BRT</code>")
        for m in all_mos:
            rb_s  = sett_map["RB"][m]
            ho_s  = sett_map["HO"][m]
            cl_s  = sett_map["CL"].get(m)
            bz_s  = sett_map["BZ"].get(m)
            g_wti = f"${(rb_s*42 - cl_s):5.2f}" if cl_s else " N/A  "
            h_wti = f"${(ho_s*42 - cl_s):5.2f}" if cl_s else " N/A  "
            g_brt = f"${(rb_s*42 - bz_s):5.2f}" if bz_s else " N/A  "
            h_brt = f"${(ho_s*42 - bz_s):5.2f}" if bz_s else " N/A  "
            print(f"{m:5} | GAS/WTI: {g_wti} | HO/WTI: {h_wti} | "
                  f"GAS/BRENT: {g_brt} | HO/BRENT: {h_brt}")
            final_msg.append(
                f"<code>{m:5}| {g_wti} | {h_wti} | {g_brt} | {h_brt}</code>")

        final_msg.append("-" * 42)

    full_text = "\n".join(final_msg)
    print(f"\nPayload length: {len(full_text)} characters")

    # Telegram hard limit is 4096 chars per message — split if needed
    LIMIT = 4096
    chunks = []
    lines  = full_text.split("\n")
    cur    = []
    cur_len = 0
    for line in lines:
        # +1 for the newline we'll re-join with
        if cur_len + len(line) + 1 > LIMIT and cur:
            chunks.append("\n".join(cur))
            cur     = [line]
            cur_len = len(line) + 1
        else:
            cur.append(line)
            cur_len += len(line) + 1
    if cur:
        chunks.append("\n".join(cur))

    print(f"Sending in {len(chunks)} chunk(s)...")
    for i, chunk in enumerate(chunks, 1):
        resp = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={"chat_id": CHAT_ID, "text": chunk, "parse_mode": "HTML"}
        )
        if resp.status_code == 200:
            print(f"  Chunk {i}/{len(chunks)} sent OK")
        else:
            print(f"  Chunk {i}/{len(chunks)} FAILED: {resp.status_code} — {resp.text}")


if __name__ == "__main__":
    run_combined_vacuum()
