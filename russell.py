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
PDF_URL = "https://www.cmegroup.com/daily_bulletin/current/Section40_Nasdaq_100_And_E_Mini_Nasdaq_100_Options.pdf"
TELEGRAM_TOKEN = "8577879935:AAEpSjAz4wdcZ9Lb7AJpURRk8haADlPCbHo"
CHAT_ID = "876384974"

CSV_FILE       = "russell_history.csv"
GITHUB_TOKEN   = os.environ.get("GIST_TOKEN", "")
GIST_ID_FILE   = "gist_russell_id.txt"

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
        m, y = month_str[:3], int(month_str[3:5]) # Safely parses '26' from 'MAR26-ALL'
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

# --- HTML PAGE BUILDER ---
def build_html_page(df):
    df_fut = df[df["Type"].isin(["FUT", "ALL", "RET"])]
    df_opt = df[df["Type"] == "OPT"]

    rows_fut_html = ""
    for _, r in df_fut.iterrows():
        chg_val = str(r["Change"])
        try:
            chg_num = float(chg_val.replace("+", ""))
            pct_class = "pos" if chg_num > 0 else ("neg" if chg_num < 0 else "")
        except: pct_class = ""
        
        # Smart formatting for backward compatibility with old records
        typ = str(r["Type"])
        mo = str(r["Month"])
        if typ == "FUT":
            if "-ALL" in mo:
                typ = "ALL"
                mo = mo.replace("-ALL", "")
            elif "-RET" in mo:
                typ = "RET"
                mo = mo.replace("-RET", "")
                
        rows_fut_html += (f'<tr data-date="{r["Date"]}" data-typ="{typ}">'
                          f'<td>{r["Date"]}</td><td>{mo}</td><td>{typ}</td><td>{r["Sett_PC"]}</td>'
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
<title>Russell 2000 Master History</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: 'Courier New', monospace; background: #0d0d0d; color: #e0e0e0; padding: 6px; font-size: 0.7rem; }}
  h2 {{ color: #00aaff; margin: 8px 0; font-size: 1rem; letter-spacing: 0.5px; text-align: center; }}
  h3 {{ color: #ffd700; margin: 12px 0 4px 0; font-size: 0.85rem; border-bottom: 1px solid #333; padding-bottom: 2px; }}
  .controls {{ display: flex; justify-content: center; align-items: center; margin-bottom: 12px; gap: 6px; flex-wrap: wrap; }}
  .controls label {{ color: #888; font-size: 0.75rem; }}
  select {{ padding: 4px 6px; background: #1a1a1a; color: #ccc; border: 1px solid #444; border-radius: 4px; font-size: 0.75rem; font-family: inherit; }}
  button {{ padding: 4px 8px; cursor: pointer; background: #1a1a1a; color: #ccc; border: 1px solid #444; border-radius: 4px; font-size: 0.75rem; font-family: inherit; }}
  button.active {{ background: #00aaff; color: #000; border-color: #00aaff; font-weight: bold; }}
  .table-wrap {{ width: 100%; margin-bottom: 16px; overflow-x: auto; }}
  table {{ border-collapse: collapse; white-space: nowrap; width: 100%; table-layout: fixed; }}
  th, td {{ border: 1px solid #2a2a2a; padding: 4px 2px; text-align: right; overflow: hidden; position: relative; }}
  th {{ text-align: left; background: #161616; color: #00aaff; cursor: pointer; user-select: none; touch-action: manipulation; }}
  
  /* Adjusted sensibly for iPhone 13 Pro viewport */
  #tbl-fut th:nth-child(1), #tbl-fut td:nth-child(1) {{ width: 22%; }}
  #tbl-fut th:nth-child(2), #tbl-fut td:nth-child(2) {{ width: 10%; }}
  #tbl-fut th:nth-child(3), #tbl-fut td:nth-child(3) {{ width: 9%; }}
  #tbl-fut th:nth-child(4), #tbl-fut td:nth-child(4) {{ width: 12%; }}
  #tbl-fut th:nth-child(5), #tbl-fut td:nth-child(5) {{ width: 12%; }}
  #tbl-fut th:nth-child(6), #tbl-fut td:nth-child(6) {{ width: 12%; }}
  #tbl-fut th:nth-child(7), #tbl-fut td:nth-child(7) {{ width: 12%; }}
  #tbl-fut th:nth-child(8), #tbl-fut td:nth-child(8) {{ width: 11%; }}

  #tbl-opt th:nth-child(1), #tbl-opt td:nth-child(1) {{ width: 24%; }}
  #tbl-opt th:nth-child(2), #tbl-opt td:nth-child(2) {{ width: 12%; }}
  #tbl-opt th:nth-child(3), #tbl-opt td:nth-child(3) {{ width: 12%; }}
  #tbl-opt th:nth-child(4), #tbl-opt td:nth-child(4) {{ width: 19%; }}
  #tbl-opt th:nth-child(5), #tbl-opt td:nth-child(5) {{ width: 19%; }}
  #tbl-opt th:nth-child(6), #tbl-opt td:nth-child(6) {{ width: 14%; }}

  th .arrow {{ display: none; }} 
  th.sorted {{ color: #fff; background: #222; }}
  th .sort-rank {{ position: absolute; top: 1px; right: 1px; font-size: 0.5rem; color: #ff5252; font-weight: bold; }}
  td.pos {{ color: #00e676; }}
  td.neg {{ color: #ff5252; }}
</style>
</head>
<body>
<h2>Russell 2000 Master</h2>
<div class="controls">
  <label>Date:</label>
  <select id="dateSelect" onchange="applyFilters()">
    <option value="">All dates</option>
    {date_options}
  </select>
  <label style="margin-left:8px;">Type:</label>
  <button onclick="filterTyp('BOTH')" data-typ="BOTH" class="active">BOTH</button>
  <button onclick="filterTyp('ALL')" data-typ="ALL">ALL</button>
  <button onclick="filterTyp('RET')" data-typ="RET">RET</button>
</div>

<h3>Futures</h3>
<div class="table-wrap">
<table id="tbl-fut">
  <thead>
    <tr>
      <th onclick="handleMultiSort('tbl-fut', 0)">Date<span class="arrow"></span></th>
      <th onclick="handleMultiSort('tbl-fut', 1)">Mo<span class="arrow"></span></th>
      <th onclick="handleMultiSort('tbl-fut', 2)">Typ<span class="arrow"></span></th>
      <th onclick="handleMultiSort('tbl-fut', 3)">Sett<span class="arrow"></span></th>
      <th onclick="handleMultiSort('tbl-fut', 4)">Chg<span class="arrow"></span></th>
      <th onclick="handleMultiSort('tbl-fut', 5)">Vol<span class="arrow"></span></th>
      <th onclick="handleMultiSort('tbl-fut', 6)">OI<span class="arrow"></span></th>
      <th onclick="handleMultiSort('tbl-fut', 7)">ΔOI<span class="arrow"></span></th>
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
let activeTyp = 'BOTH';

function filterTyp(typ) {{
    activeTyp = typ;
    document.querySelectorAll('button[data-typ]').forEach(b => b.classList.toggle('active', b.dataset.typ === typ));
    applyFilters();
}}

function applyFilters() {{
    const dateQ = document.getElementById('dateSelect').value;
    
    // Futures table requires Date + Typ filter
    const futRows = document.querySelectorAll('#tbl-fut tbody tr');
    futRows.forEach(row => {{
        let showDate = !dateQ || row.dataset.date === dateQ;
        let showTyp = activeTyp === 'BOTH' || row.dataset.typ === activeTyp;
        row.style.display = (showDate && showTyp) ? '' : 'none';
    }});

    // Options table requires Date filter only
    const optRows = document.querySelectorAll('#tbl-opt tbody tr');
    optRows.forEach(row => {{
        let showDate = !dateQ || row.dataset.date === dateQ;
        row.style.display = showDate ? '' : 'none';
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
                if (/^[A-Z]{{3}}\d{{2}}/i.test(str)) {{ 
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
    payload = {"description": "Russell 2000 Master", "public": True, "files": {"rty.html": {"content": html}}}
    gid = load_gist_id()
    try:
        if gid:
            resp = requests.patch(f"https://api.github.com/gists/{gid}", headers=headers, json=payload)
            if resp.status_code == 200: return "https://htmlpreview.github.io/?" + resp.json()["files"]["rty.html"]["raw_url"]
        resp = requests.post("https://api.github.com/gists", headers=headers, json=payload)
        if resp.status_code == 201:
            Path(GIST_ID_FILE).write_text(resp.json()["id"])
            return "https://htmlpreview.github.io/?" + resp.json()["files"]["rty.html"]["raw_url"]
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
    Path("rty.html").write_text(html, encoding="utf-8")
    return push_to_gist(html)

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

    sorted_opts = sorted(
        options_results,
        key=lambda x: (
            get_month_score(x['Month']),
            0 if x['Side'] == "CALLS" else 1,
            x['Series']
        )
    )

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
            delta_int = to_int(r['Delta'])
            
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

    # --- RECORD PREPARATION FOR HTML & CSV ---
    records = []
    for m in sorted(f_sum.keys(), key=get_month_score):
        s = f_sum[m]
        records.append({
            "Type": "ALL", "Month": m, "Sett_PC": f"{s['s']:.2f}",
            "Change": f"{s['c']:+6.2f}", "Vol": s['av'], "OI": s['ao'], "Delta": s['ad']
        })
        records.append({
            "Type": "RET", "Month": m, "Sett_PC": f"{s['s']:.2f}",
            "Change": f"{s['c']:+6.2f}", "Vol": s['rv'], "OI": s['ro'], "Delta": s['rd']
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

    tg_msg = [f"🐿️ <b>RUSSELL 2000 - {trade_date}</b>", "", "<b>FUTURES (STANDARD UNITS)</b>", "<code>MO   |TYP| SETT | CHG | VOL| OI | ΔOI</code>"]
    for m in sorted(f_sum.keys(), key=get_month_score):
        s = f_sum[m]
        tg_msg.append(f"<code>{m:5}|ALL|{s['s']:6.1f}|{s['c']:+5.1f}|{format_num(s['av']):>4}|{format_num(s['ao']):>4}|{format_num(s['ad']):>4}</code>")
        tg_msg.append(f"<code>{m:5}|RET|{s['s']:6.1f}|{s['c']:+5.1f}|{format_num(s['rv']):>4}|{format_num(s['ro']):>4}|{format_num(s['rd']):>4}</code>")
        tg_msg.append("-" * 38)

    tg_msg.append("\n<b>OPTIONS SUMMARY</b>")
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
    run_comprehensive_vacuum()
