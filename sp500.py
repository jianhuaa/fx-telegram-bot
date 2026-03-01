import cloudscraper
import pdfplumber
import io
import re
import requests
import os
import csv
import pandas as pd
from datetime import datetime
from pathlib import Path

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

CSV_FILE       = "sp500_master_history.csv"
GITHUB_TOKEN   = os.environ.get("GIST_TOKEN", "")
GIST_ID_FILE   = "sp500_gist_id.txt"

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

# --- HTML PAGE BUILDER ---
def build_html_page(df):
    df_fut = df[df["Type"] == "FUT"]
    df_opt = df[df["Type"] == "OPT"]

    rows_fut_html = ""
    for _, r in df_fut.iterrows():
        chg_val = str(r["Change"])
        try:
            chg_num = float(chg_val.replace("+", ""))
            pct_class = "pos" if chg_num > 0 else ("neg" if chg_num < 0 else "")
        except: pct_class = ""
        rows_fut_html += (f'<tr data-date="{r["Date"]}">'
                          f'<td>{r["Date"]}</td><td>{r["Month"]}</td><td>{r["Sett_PC"]}</td>'
                          f'<td class="{pct_class}">{r["Change"]}</td><td>{format_num(float(str(r["Vol"]).replace(",", "")))}</td>'
                          f'<td>{format_num(float(str(r["OI"]).replace(",", "")))}</td><td>{format_num(float(str(r["Delta"]).replace(",", "")))}</td></tr>\n')

    rows_opt_html = ""
    for _, r in df_opt.iterrows():
        rows_opt_html += (f'<tr data-date="{r["Date"]}">'
                          f'<td>{r["Date"]}</td><td>{r["Month"]}</td><td>{r["Sett_PC"]}</td>'
                          f'<td>{format_num(float(str(r["Vol"]).replace(",", "")))}</td>'
                          f'<td>{format_num(float(str(r["OI"]).replace(",", "")))}</td><td>{format_num(float(str(r["Delta"]).replace(",", "")))}</td></tr>\n')

    dates = sorted(df["Date"].unique().tolist(), reverse=True)
    date_options = "\n".join(f'<option value="{d}">{d}</option>' for d in dates)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1, user-scalable=no">
<title>S&P 500 Master History</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: 'Courier New', monospace; background: #0d0d0d; color: #e0e0e0; padding: 6px; font-size: 0.7rem; }}
  h2 {{ color: #00aaff; margin: 8px 0; font-size: 1rem; letter-spacing: 0.5px; text-align: center; }}
  h3 {{ color: #ffd700; margin: 12px 0 4px 0; font-size: 0.85rem; border-bottom: 1px solid #333; padding-bottom: 2px; }}
  .controls {{ display: flex; justify-content: center; align-items: center; margin-bottom: 12px; gap: 6px; }}
  .controls label {{ color: #888; font-size: 0.75rem; }}
  select {{ padding: 4px 6px; background: #1a1a1a; color: #ccc; border: 1px solid #444; border-radius: 4px; font-size: 0.75rem; font-family: inherit; }}
  .table-wrap {{ width: 100%; margin-bottom: 16px; overflow-x: auto; }}
  table {{ border-collapse: collapse; white-space: nowrap; width: 100%; table-layout: fixed; }}
  th, td {{ border: 1px solid #2a2a2a; padding: 4px 2px; text-align: right; overflow: hidden; position: relative; }}
  th {{ text-align: left; background: #161616; color: #00aaff; cursor: pointer; user-select: none; touch-action: manipulation; }}
  
  /* Futures Table Column Widths */
  #tbl-fut th:nth-child(1), #tbl-fut td:nth-child(1) {{ width: 20%; }}
  #tbl-fut th:nth-child(2), #tbl-fut td:nth-child(2) {{ width: 14%; }}
  #tbl-fut th:nth-child(3), #tbl-fut td:nth-child(3) {{ width: 15%; }}
  #tbl-fut th:nth-child(4), #tbl-fut td:nth-child(4) {{ width: 15%; }}
  #tbl-fut th:nth-child(5), #tbl-fut td:nth-child(5) {{ width: 12%; }}
  #tbl-fut th:nth-child(6), #tbl-fut td:nth-child(6) {{ width: 12%; }}
  #tbl-fut th:nth-child(7), #tbl-fut td:nth-child(7) {{ width: 12%; }}

  /* Options Table Column Widths */
  #tbl-opt th:nth-child(1), #tbl-opt td:nth-child(1) {{ width: 22%; }}
  #tbl-opt th:nth-child(2), #tbl-opt td:nth-child(2) {{ width: 16%; }}
  #tbl-opt th:nth-child(3), #tbl-opt td:nth-child(3) {{ width: 14%; }}
  #tbl-opt th:nth-child(4), #tbl-opt td:nth-child(4) {{ width: 16%; }}
  #tbl-opt th:nth-child(5), #tbl-opt td:nth-child(5) {{ width: 16%; }}
  #tbl-opt th:nth-child(6), #tbl-opt td:nth-child(6) {{ width: 16%; }}

  th .arrow {{ display: none; }} /* Hidden to save space on iPhone */
  th.sorted {{ color: #fff; background: #222; }}
  th .sort-rank {{ position: absolute; top: 1px; right: 1px; font-size: 0.5rem; color: #ff5252; font-weight: bold; }}
  td.pos {{ color: #00e676; }}
  td.neg {{ color: #ff5252; }}
</style>
</head>
<body>
<h2>S&P 500 Master</h2>
<div class="controls">
  <label>Filter Date:</label>
  <select id="dateSelect" onchange="applyFilters()">
    <option value="">All dates</option>
    {date_options}
  </select>
</div>

<h3>Futures</h3>
<div class="table-wrap">
<table id="tbl-fut">
  <thead>
    <tr>
      <th onclick="handleMultiSort('tbl-fut', 0)">Date<span class="arrow"></span></th>
      <th onclick="handleMultiSort('tbl-fut', 1)">Mo<span class="arrow"></span></th>
      <th onclick="handleMultiSort('tbl-fut', 2)">Sett<span class="arrow"></span></th>
      <th onclick="handleMultiSort('tbl-fut', 3)">Chg<span class="arrow"></span></th>
      <th onclick="handleMultiSort('tbl-fut', 4)">Vol<span class="arrow"></span></th>
      <th onclick="handleMultiSort('tbl-fut', 5)">OI<span class="arrow"></span></th>
      <th onclick="handleMultiSort('tbl-fut', 6)">ΔOI<span class="arrow"></span></th>
    </tr>
  </thead>
  <tbody>
{rows_fut_html}  </tbody>
</table>
</div>

<h3>Options</h3>
<div class="table-wrap">
<table id="tbl-opt">
  <thead>
    <tr>
      <th onclick="handleMultiSort('tbl-opt', 0)">Date<span class="arrow"></span></th>
      <th onclick="handleMultiSort('tbl-opt', 1)">Mo<span class="arrow"></span></th>
      <th onclick="handleMultiSort('tbl-opt', 2)">P/C<span class="arrow"></span></th>
      <th onclick="handleMultiSort('tbl-opt', 3)">Vol<span class="arrow"></span></th>
      <th onclick="handleMultiSort('tbl-opt', 4)">OI<span class="arrow"></span></th>
      <th onclick="handleMultiSort('tbl-opt', 5)">ΔOI<span class="arrow"></span></th>
    </tr>
  </thead>
  <tbody>
{rows_opt_html}  </tbody>
</table>
</div>

<script>
let sortState = {{ 'tbl-fut': [], 'tbl-opt': [] }};

function applyFilters() {{
    const dateQ = document.getElementById('dateSelect').value;
    ['tbl-fut', 'tbl-opt'].forEach(tblId => {{
        const rows = document.querySelectorAll(`#${{tblId}} tbody tr`);
        rows.forEach(row => {{
            row.style.display = (!dateQ || row.dataset.date === dateQ) ? '' : 'none';
        }});
    }});
}}

function handleMultiSort(tblId, col) {{
    let stack = sortState[tblId];
    let idx = stack.findIndex(s => s.col === col);
    if (idx !== -1) {{
        if (!stack[idx].asc) stack[idx].asc = true;
        else stack.splice(idx, 1);
    }} else {{
        stack.push({{col: col, asc: false}});
    }}
    renderSortUI(tblId); executeSort(tblId);
}}

function renderSortUI(tblId) {{
    const ths = document.querySelectorAll(`#${{tblId}} th`);
    let stack = sortState[tblId];
    ths.forEach((th, i) => {{
        const rank = stack.findIndex(s => s.col === i);
        const oldRank = th.querySelector('.sort-rank');
        if (oldRank) oldRank.remove();
        if (rank !== -1) {{
            th.classList.add('sorted'); 
            const span = document.createElement('span'); 
            span.className = 'sort-rank'; 
            span.innerHTML = (rank + 1); 
            th.appendChild(span);
        }} else {{ 
            th.classList.remove('sorted'); 
        }}
    }});
}}

function executeSort(tblId) {{
    const tbody = document.querySelector(`#${{tblId}} tbody`);
    const rows = Array.from(tbody.querySelectorAll('tr'));
    let stack = sortState[tblId];
    rows.sort((a, b) => {{
        for (let s of stack) {{
            let av = a.cells[s.col].textContent.trim(), bv = b.cells[s.col].textContent.trim();
            const parse = (str) => {{ 
                if (/^\d{{4}}-\d{{2}}-\d{{2}}$/.test(str)) return Date.parse(str);
                if (/^[A-Z]{{3}}\d{{2}}$/i.test(str)) {{
                    const mos = ["JAN","FEB","MAR","APR","MAY","JUN","JUL","AUG","SEP","OCT","NOV","DEC"];
                    const m = mos.indexOf(str.substring(0, 3).toUpperCase());
                    const y = parseInt(str.substring(3, 5), 10);
                    if (m !== -1 && !isNaN(y)) return (y * 100) + m;
                }}
                let n = parseFloat(str.replace(/[%k,\+]/g, '')); 
                return str.includes('k') ? n * 1000 : n; 
            }};
            const an = parse(av), bn = parse(bv);
            let res = (!isNaN(an) && !isNaN(bn)) ? an - bn : av.localeCompare(bv);
            if (res !== 0) return s.asc ? res : -res;
        }}
        return 0;
    }}).forEach(r => tbody.appendChild(r));
}}

window.onload = applyFilters;
</script>
</body>
</html>"""

# --- GIST & STORAGE HELPERS ---
def load_gist_id():
    return Path(GIST_ID_FILE).read_text().strip() if os.path.isfile(GIST_ID_FILE) else ""

def push_to_gist(html):
    if not GITHUB_TOKEN: return None
    headers = {"Authorization": f"token {GITHUB_TOKEN}", "Accept": "application/vnd.github+json"}
    payload = {"description": "S&P 500 Master", "public": True, "files": {"sp500.html": {"content": html}}}
    gid = load_gist_id()
    try:
        if gid:
            resp = requests.patch(f"https://api.github.com/gists/{gid}", headers=headers, json=payload)
            if resp.status_code == 200: return "https://htmlpreview.github.io/?" + resp.json()["files"]["sp500.html"]["raw_url"]
        resp = requests.post("https://api.github.com/gists", headers=headers, json=payload)
        if resp.status_code == 201:
            Path(GIST_ID_FILE).write_text(resp.json()["id"])
            return "https://htmlpreview.github.io/?" + resp.json()["files"]["sp500.html"]["raw_url"]
    except: pass
    return None

def archive_and_publish(records, trade_date):
    try: clean_date = datetime.strptime(trade_date, "%b %d, %Y").strftime("%Y-%m-%d")
    except: clean_date = trade_date
    file_exists = os.path.isfile(CSV_FILE)
    already_exists = False
    if file_exists:
        with open(CSV_FILE, 'r') as f:
            lines = f.readlines()
            if lines:
                last_row = lines[-1].split(',')
                if last_row[0] == clean_date: already_exists = True
    if not already_exists:
        with open(CSV_FILE, 'a', newline='') as f:
            writer = csv.writer(f)
            if not file_exists: writer.writerow(['Date', 'Type', 'Month', 'Sett_PC', 'Change', 'Vol', 'OI', 'Delta'])
            for r in records: 
                writer.writerow([clean_date, r['Type'], r['Month'], r['Sett_PC'], r['Change'], r['Vol'], r['OI'], r['Delta']])
    
    df = pd.read_csv(CSV_FILE).sort_values(by=['Date', 'Type', 'Month'], ascending=[False, True, True])
    html = build_html_page(df)
    Path("sp500.html").write_text(html, encoding="utf-8")
    return push_to_gist(html)

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

    # --- RECORD PREPARATION FOR HTML & CSV ---
    records = []
    for m in sorted(f_sum.keys(), key=get_month_score):
        s = f_sum[m]
        records.append({
            "Type": "FUT", "Month": m, "Sett_PC": f"{s['Sett']:.2f}",
            "Change": f"{s['Change']:+6.2f}", "Vol": s['Vol'], "OI": s['OI'], "Delta": s['Delta']
        })
    for m in sorted(opt_sum.keys(), key=get_month_score):
        s = opt_sum[m]
        if s["V_Gross"] == 0: continue
        pc = s["V_Puts"] / s["V_Calls"] if s["V_Calls"] > 0 else 0.0
        records.append({
            "Type": "OPT", "Month": m, "Sett_PC": f"{pc:.2f}",
            "Change": "-", "Vol": s['V_Gross'], "OI": s['OI_Net'], "Delta": s['D_Net']
        })

    link = archive_and_publish(records, trade_date)

    # --- TELEGRAM MESSAGE CONSTRUCTION ---
    tg_msg = [f"🇺🇸 <b>S&P 500 - {trade_date}</b>", "", "<b>FUTURES (E-MINI UNITS)</b>", "<code>MO   | SETT | CHG  | VOL |  OI |  ΔOI</code>"]
    for m in sorted(f_sum.keys(), key=get_month_score):
        s = f_sum[m]
        tg_msg.append(f"<code>{m:5}|{s['Sett']:6.1f}|{s['Change']:+6.1f}|{format_num(s['Vol']):>5}|{format_num(s['OI']):>5}|{format_num(s['Delta']):>5}</code>")
        tg_msg.append("-" * 38)

    tg_msg.append("\n<b>OPTIONS SUMMARY (NET E-MINI UNITS)</b>")
    tg_msg.append("<code>MO    | VOL  |   P/C  |  OI   | ΔOI </code>")
    for m in sorted(opt_sum.keys(), key=get_month_score):
        s = opt_sum[m]
        if s["V_Gross"] == 0: continue
        pc = s["V_Puts"] / s["V_Calls"] if s["V_Calls"] > 0 else 0.0
        tg_msg.append(f"<code>{m:5} |{format_num(s['V_Gross']):>5} | {pc:6.2f} |{format_num(s['OI_Net']):>6} |{format_num(s['D_Net']):>5}</code>")

    if link:
        tg_msg.append(f"\n<a href='{link}'>🔍 Interactive History</a>")

    print("\n[INFO] Sending Telegram message...")
    requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", json={"chat_id": CHAT_ID, "text": "\n".join(tg_msg), "parse_mode": "HTML", "disable_web_page_preview": True})
    print("[INFO] Done.")

if __name__ == "__main__":
    run_sp500_master_vacuum()
