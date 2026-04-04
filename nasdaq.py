from curl_cffi import requests as cureq
import pdfplumber
import io
import re
import requests
import os
import csv
import time
import pandas as pd
from datetime import datetime
from pathlib import Path

# --- CONFIGURATION ---
PDF_URL        = "https://www.cmegroup.com/daily_bulletin/current/Section40_Nasdaq_100_And_E_Mini_Nasdaq_100_Options.pdf"
TELEGRAM_TOKEN = "8577879935:AAEpSjAz4wdcZ9Lb7AJpURRk8haADlPCbHo"
CHAT_ID        = "876384974"

GITHUB_TOKEN   = os.environ.get("GIST_TOKEN", "")
CSV_FILE       = "nasdaq_history.csv"
GIST_ID_FILE   = "nasdaq_gist.txt"

TARGET_MONTHS  = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]
WANTED_FUTURES = ["EMINI NASD FUT", "MNQ FUT"]
WANTED_OPTIONS = ["WEEKLY-1", "WEEKLY-2", "WEEKLY-4", "EMINI NASD CALL", "EMINI NASD PUT", 
                  "QN1", "QN2", "QN4", "DMQ", "DRQ", "DTQ", "DWQ", "QMW", "QN OOF", "QRW", "QTW", "QWW", "MINI NSDQ EOM"]
RETAIL_TICKERS = ["MNQ", "DMQ", "DRQ", "DTQ", "DWQ", "QMW", "QRW", "QTW", "QWW"]

# ─────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────

def to_int(val):
    if not val: return 0
    s = str(val).replace(",", "").replace("+", "").strip()
    try: return int(float(s))
    except: return 0

def to_float(val):
    if not val: return 0.0
    s = str(val).replace(",", "").replace("+", "").strip()
    try: return float(s)
    except: return 0.0

def format_num(val):
    n = to_int(val)
    abs_n = abs(n)
    sign = "-" if n < 0 else ""
    if abs_n < 1000: return f"{n}"
    elif abs_n < 10000: return f"{sign}{abs_n/1000:.1f}k"
    else: return f"{sign}{round(abs_n/1000)}k"

def decode_put_month(date_str):
    try:
        year = date_str[2:4]
        month_idx = int(date_str[4:6]) - 1
        return f"{TARGET_MONTHS[month_idx]}{year}"
    except: return "UNKNOWN"

def get_month_score(month_str):
    try:
        m = month_str[:3]
        y = int(month_str[3:])
        return y * 100 + (TARGET_MONTHS.index(m) + 1)
    except: return 0

# ─────────────────────────────────────────────
# HTML PAGE BUILDER 
# ─────────────────────────────────────────────

def build_html_page(df):
    df_fut = df[df["Type"].isin(["ALL", "RET"])]
    df_opt = df[df["Type"] == "OPT"]

    rows_fut_html = ""
    for _, r in df_fut.iterrows():
        # Clean decimals for HTML display (Futures only)
        display_sett = str(r["Sett_PC"]).split('.')[0]
        display_chg  = str(r["Change"]).split('.')[0]
        
        try:
            chg_num = float(str(r["Change"]).replace("+", ""))
            pct_class = "pos" if chg_num > 0 else ("neg" if chg_num < 0 else "")
        except: 
            pct_class = ""
            
        rows_fut_html += (
            f'<tr data-date="{r["Date"]}" data-typ="{r["Type"]}">'
            f'<td>{r["Date"]}</td><td>{r["Month"]}</td><td>{r["Type"]}</td>'
            f'<td>{display_sett}</td>'
            f'<td class="{pct_class}">{display_chg}</td>'
            f'<td>{format_num(r["Vol"])}</td>'
            f'<td>{format_num(r["OI"])}</td>'
            f'<td>{format_num(r["Delta"])}</td></tr>\n'
        )

    rows_opt_html = ""
    for _, r in df_opt.iterrows():
        rows_opt_html += (
            f'<tr data-date="{r["Date"]}">'
            f'<td>{r["Date"]}</td><td>{r["Month"]}</td><td>{r["Sett_PC"]}</td>'
            f'<td>{format_num(r["Vol"])}</td>'
            f'<td>{format_num(r["OI"])}</td>'
            f'<td>{format_num(r["Delta"])}</td></tr>\n'
        )

    dates = sorted(df["Date"].unique().tolist(), reverse=True)
    date_options = "\n".join(f'<option value="{d}">{d}</option>' for d in dates)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1, user-scalable=no">
<title>Nasdaq CME Master History</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: 'Courier New', monospace; background: #0d0d0d; color: #e0e0e0; padding: 6px; font-size: 0.7rem; }}
  h2 {{ color: #00bfff; margin: 8px 0; font-size: 1rem; letter-spacing: 0.5px; text-align: center; }}
  h3 {{ color: #7ec8e3; margin: 12px 0 4px 0; font-size: 0.85rem; border-bottom: 1px solid #333; padding-bottom: 2px; }}
  .controls {{ display: flex; justify-content: center; align-items: center; margin-bottom: 12px; gap: 6px; flex-wrap: wrap; }}
  .controls label {{ color: #888; font-size: 0.75rem; }}
  select {{ padding: 4px 6px; background: #1a1a1a; color: #ccc; border: 1px solid #444; border-radius: 4px; font-size: 0.75rem; font-family: inherit; }}
  button {{ padding: 4px 8px; cursor: pointer; background: #1a1a1a; color: #ccc; border: 1px solid #444; border-radius: 4px; font-size: 0.75rem; font-family: inherit; }}
  button.active {{ background: #00bfff; color: #000; border-color: #00bfff; font-weight: bold; }}
  .table-wrap {{ width: 100%; margin-bottom: 16px; overflow-x: auto; }}
  table {{ border-collapse: collapse; white-space: nowrap; width: 100%; table-layout: fixed; }}
  th, td {{ border: 1px solid #2a2a2a; padding: 4px 2px; text-align: right; overflow: hidden; position: relative; }}
  th {{ text-align: left; background: #161616; color: #00bfff; cursor: pointer; user-select: none; touch-action: manipulation; }}
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
  th.sorted {{ color: #fff; background: #222; }}
  th .sort-rank {{ position: absolute; top: 1px; right: 1px; font-size: 0.5rem; color: #ff5252; font-weight: bold; }}
  td.pos {{ color: #00e676; }}
  td.neg {{ color: #ff5252; }}
</style>
</head>
<body>
<h2>📈 Nasdaq CME Master</h2>
<div class="controls">
  <label>Date:</label>
  <select id="dateSelect" onchange="applyFilters()">
    <option value="">All dates</option>
    {date_options}
  </select>
  <label style="margin-left:8px;">Type:</label>
  <button onclick="filterTyp('BOTH')" data-typ="BOTH" class="active">BOTH</button>
  <button onclick="filterTyp('ALL')"  data-typ="ALL">ALL</button>
  <button onclick="filterTyp('RET')"  data-typ="RET">RET</button>
</div>
<h3>Futures</h3>
<div class="table-wrap">
<table id="tbl-fut">
  <thead><tr>
    <th onclick="handleMultiSort('tbl-fut',0)">Date</th>
    <th onclick="handleMultiSort('tbl-fut',1)">Mo</th>
    <th onclick="handleMultiSort('tbl-fut',2)">Typ</th>
    <th onclick="handleMultiSort('tbl-fut',3)">Sett</th>
    <th onclick="handleMultiSort('tbl-fut',4)">Chg</th>
    <th onclick="handleMultiSort('tbl-fut',5)">Vol</th>
    <th onclick="handleMultiSort('tbl-fut',6)">OI</th>
    <th onclick="handleMultiSort('tbl-fut',7)">ΔOI</th>
  </tr></thead>
  <tbody>
{rows_fut_html}  </tbody>
</table>
</div>
<h3>Options</h3>
<div class="table-wrap">
<table id="tbl-opt">
  <thead><tr>
    <th onclick="handleMultiSort('tbl-opt',0)">Date</th>
    <th onclick="handleMultiSort('tbl-opt',1)">Mo</th>
    <th onclick="handleMultiSort('tbl-opt',2)">P/C</th>
    <th onclick="handleMultiSort('tbl-opt',3)">Vol</th>
    <th onclick="handleMultiSort('tbl-opt',4)">OI</th>
    <th onclick="handleMultiSort('tbl-opt',5)">ΔOI</th>
  </tr></thead>
  <tbody>
{rows_opt_html}  </tbody>
</table>
</div>
<script>
let sortState = {{'tbl-fut':[], 'tbl-opt':[]}};
let activeTyp = 'BOTH';
function filterTyp(typ) {{
  activeTyp = typ;
  document.querySelectorAll('button[data-typ]').forEach(b => b.classList.toggle('active', b.dataset.typ === typ));
  applyFilters();
}}
function applyFilters() {{
  const dateQ = document.getElementById('dateSelect').value;
  document.querySelectorAll('#tbl-fut tbody tr').forEach(row => {{
    const showDate = !dateQ || row.dataset.date === dateQ;
    const showTyp  = activeTyp === 'BOTH' || row.dataset.typ === activeTyp;
    row.style.display = (showDate && showTyp) ? '' : 'none';
  }});
  document.querySelectorAll('#tbl-opt tbody tr').forEach(row => {{
    row.style.display = (!dateQ || row.dataset.date === dateQ) ? '' : 'none';
  }});
}}
function handleMultiSort(tblId, col) {{
  let stack = sortState[tblId];
  let idx = stack.findIndex(s => s.col === col);
  if (idx !== -1) {{
    if (!stack[idx].asc) stack[idx].asc = true;
    else stack.splice(idx, 1);
  }} else {{
    stack.push({{col, asc: false}});
  }}
  renderSortUI(tblId); executeSort(tblId);
}}
function renderSortUI(tblId) {{
  document.querySelectorAll(`#${{tblId}} th`).forEach((th, i) => {{
    const rank = sortState[tblId].findIndex(s => s.col === i);
    const old = th.querySelector('.sort-rank');
    if (old) old.remove();
    if (rank !== -1) {{
      th.classList.add('sorted');
      const sp = document.createElement('span');
      sp.className = 'sort-rank'; sp.textContent = rank + 1;
      th.appendChild(sp);
    }} else {{
      th.classList.remove('sorted');
    }}
  }});
}}
function executeSort(tblId) {{
  const tbody = document.querySelector(`#${{tblId}} tbody`);
  const rows  = Array.from(tbody.querySelectorAll('tr'));
  const stack = sortState[tblId];
  const parse = str => {{
    if (/^\d{{4}}-\d{{2}}-\d{{2}}$/.test(str)) return Date.parse(str);
    if (/^[A-Z]{{3}}\d{{2}}/i.test(str)) {{
      const mos = ["JAN","FEB","MAR","APR","MAY","JUN","JUL","AUG","SEP","OCT","NOV","DEC"];
      const m = mos.indexOf(str.substring(0,3).toUpperCase());
      const y = parseInt(str.substring(3,5), 10);
      if (m !== -1 && !isNaN(y)) return y * 100 + m;
    }}
    const n = parseFloat(str.replace(/[%k,+]/g,''));
    return str.includes('k') ? n * 1000 : n;
  }};
  rows.sort((a, b) => {{
    for (const s of stack) {{
      const av = a.cells[s.col].textContent.trim();
      const bv = b.cells[s.col].textContent.trim();
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

# ─────────────────────────────────────────────
# GIST & STORAGE HELPERS 
# ─────────────────────────────────────────────

def load_gist_id():
    return Path(GIST_ID_FILE).read_text().strip() if os.path.isfile(GIST_ID_FILE) else ""

def push_to_gist(html):
    if not GITHUB_TOKEN: 
        print("[DEBUG - GIST] No GITHUB_TOKEN found. Skipping gist upload.")
        return None
    headers = {"Authorization": f"token {GITHUB_TOKEN}", "Accept": "application/vnd.github+json"}
    payload = {"description": "Nasdaq CME Master", "public": True,
                "files": {"nasdaq.html": {"content": html}}}
    gid = load_gist_id()
    try:
        if gid:
            print(f"[DEBUG - GIST] Updating existing gist ID: {gid}")
            resp = requests.patch(f"https://api.github.com/gists/{gid}", headers=headers, json=payload)
            if resp.status_code == 200:
                return "https://htmlpreview.github.io/?" + resp.json()["files"]["nasdaq.html"]["raw_url"]
        print("[DEBUG - GIST] Creating new gist...")
        resp = requests.post("https://api.github.com/gists", headers=headers, json=payload)
        if resp.status_code == 201:
            Path(GIST_ID_FILE).write_text(resp.json()["id"])
            return "https://htmlpreview.github.io/?" + resp.json()["files"]["nasdaq.html"]["raw_url"]
    except Exception as e: 
        print(f"[DEBUG - GIST] Error during gist push: {e}")
    return None

def archive_and_publish(records, trade_date):
    print(f"\n[DEBUG - CSV] Archiving and publishing for trade date: {trade_date}")
    try: clean_date = datetime.strptime(trade_date, "%b %d, %Y").strftime("%Y-%m-%d")
    except: clean_date = trade_date

    file_exists = os.path.isfile(CSV_FILE)
    already_exists = False
    if file_exists:
        with open(CSV_FILE, 'r') as f:
            lines = f.readlines()
            if lines:
                last_row = lines[-1].split(',')
                if last_row[0] == clean_date:
                    already_exists = True
                    print(f"[DEBUG - CSV] Data for {clean_date} already exists. Skipping append.")

    if not already_exists:
        print(f"[DEBUG - CSV] Appending {len(records)} records for {clean_date} to {CSV_FILE}")
        with open(CSV_FILE, 'a', newline='') as f:
            writer = csv.writer(f)
            if not file_exists:
                writer.writerow(['Date','Type','Month','Sett_PC','Change','Vol','OI','Delta'])
            for r in records:
                writer.writerow([clean_date, r['Type'], r['Month'], r['Sett_PC'],
                                  r['Change'], r['Vol'], r['OI'], r['Delta']])

    print("[DEBUG - HTML] Building HTML page from CSV...")
    df = pd.read_csv(CSV_FILE).sort_values(by=['Date','Type','Month'], ascending=[False,True,True])
    html = build_html_page(df)
    Path("nasdaq.html").write_text(html, encoding="utf-8")
    return push_to_gist(html)

# ─────────────────────────────────────────────
# PARSERS 
# ─────────────────────────────────────────────

def process_futures_block(contract, lines, page_num):
    cleaned_lines = [line.strip() for line in lines if line.strip()]
    full_text = " ".join(cleaned_lines)
    tokens = full_text.split()
    settlement, change_val = 0.0, 0.0
    change_idx = -1
    
    for i, t in enumerate(tokens):
        if t in ["+", "-"] and i+1 < len(tokens):
            raw_sett = tokens[i-1]; raw_chg = tokens[i+1]
            
            # --- UPGRADED HEALING LOGIC ---
            if "." in raw_sett and len(raw_sett.split(".")[-1]) == 1:
                last_digit = raw_sett.split(".")[-1]
                # Force Nasdaq ticks if a character got swallowed by the PDF reader
                if last_digit == "2": settlement = to_float(raw_sett + "5")
                elif last_digit == "7": settlement = to_float(raw_sett + "5")
                elif last_digit == "5": settlement = to_float(raw_sett + "0")
                elif last_digit == "0": settlement = to_float(raw_sett + "0")
                else:
                    # Fallback to original spill logic just in case
                    spill_digit = raw_chg[0]
                    healed_sett = to_float(raw_sett + spill_digit)
                    if (healed_sett * 100) % 25 == 0: settlement = healed_sett
                    else: settlement = to_float(raw_sett)
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
                        volume = cand; break
        if volume != "0": break
        
    month_match = re.search(r'\b(?:JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)\d{2}\b', contract)
    return { "Contract": contract, "Month": month_match.group() if month_match else "UNKNOWN", "Sett": settlement, "Change": change_val, "Volume": to_int(volume), "OI": to_int(oi_val), "Delta": delta_val, "Page": page_num }

def process_options_total(name, month, line, page_num, side):
    tokens = line.split()
    total_idx = -1
    for i, t in enumerate(tokens):
        if t == "TOTAL": total_idx = i; break
    if total_idx == -1: return None
    try:
        volume = tokens[total_idx + 1]; oi_val = tokens[total_idx + 2]
        delta_val = tokens[total_idx + 3] if total_idx + 3 < len(tokens) else "0"
        if delta_val in ["+", "-"] and total_idx + 4 < len(tokens): delta_val += tokens[total_idx + 4]
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
    return { "Series": f"{clean_name} {side}", "Month": month, "Volume": to_int(volume), "OI": to_int(oi_val), "Delta": delta_val, "Side": side, "Page": page_num, "RawName": name }

# ─────────────────────────────────────────────
# MAIN EXECUTION
# ─────────────────────────────────────────────

def run_comprehensive_vacuum():
    print("[DEBUG - SYSTEM] --- STARTING NASDAQ CME PARSER ---")
    headers = {
        'Referer': 'https://www.cmegroup.com/market-data/volume-open-interest/exchange-volume.html',
    }
    print(f"[DEBUG - HTTP] Fetching PDF from: {PDF_URL}")
    time.sleep(2)
    resp = cureq.get(PDF_URL, impersonate="chrome120", headers=headers, timeout=45)
    pdf_bytes = io.BytesIO(resp.content)
    print("[DEBUG - HTTP] PDF fetched successfully.")

    futures_results, options_results, seen_options = [], [], {}
    trade_date = "Unknown Date"

    with pdfplumber.open(pdf_bytes) as pdf:
        total_pages = len(pdf.pages)
        print(f"[DEBUG - PDF] Total pages found: {total_pages}")
        
        current_block_name, current_option_month = "UNKNOWN", "UNKNOWN"
        in_futures, in_options = False, False
        current_side = "CALLS"
        
        for p_idx, page in enumerate(pdf.pages):
            page_num = p_idx + 1
            print(f"\n[DEBUG - SCAN] === Scanning Page {page_num}/{total_pages} ===")
            
            text_content = page.extract_text() or ""
            if p_idx == 0:
                date_match = re.search(r'[A-Z][a-z]{2}, ([A-Z][a-z]{2} \d{2}, \d{4})', text_content)
                if date_match: 
                    trade_date = date_match.group(1)
                    print(f"[DEBUG - PARSE] Extracted Trade Date from Page 1: {trade_date}")

            lines = text_content.split('\n')
            for line in lines:
                clean = line.strip()
                if not clean: continue
                
                # Side detection
                if "NASDAQ 100 WEEKLY-1 CALLS" in clean.upper(): 
                    current_side = "CALLS"
                    print(f"[DEBUG - STATE] Switched to {current_side} side.")
                elif "E-MINI NASDAQ 100 WEEKLY-1 PUTS" in clean.upper(): 
                    current_side = "PUTS"
                    print(f"[DEBUG - STATE] Switched to {current_side} side.")
                
                if "DEC29 EMINI NASD CALL" in clean.upper(): 
                    in_options = False
                    print("[DEBUG - STATE] Hit end of relevant options (DEC29 CALL). Exiting options block.")
                    continue
                
                # Month detection
                month_match = re.search(r'\b(?:JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)\d{2}\b', clean)
                put_month_match = re.search(r'\b\d{6}00\b', clean)
                
                if put_month_match: 
                    current_option_month = decode_put_month(put_month_match.group())
                    print(f"[DEBUG - STATE] Detected Option Month (PUT format): {current_option_month}")
                elif month_match: 
                    current_option_month = month_match.group()
                    print(f"[DEBUG - STATE] Detected Option Month (Standard format): {current_option_month}")
                
                # Futures block entry
                found_f = False
                for f in WANTED_FUTURES:
                    if f in clean and "TOTAL" not in clean: 
                        in_futures, in_options, current_block_name, found_f = True, False, f, True
                        print(f"[DEBUG - BLOCK] Entered FUTURES block: {current_block_name}")
                        break
                if found_f: continue
                
                # Options block entry
                found_o = False
                for o in WANTED_OPTIONS:
                    if o in clean and "TOTAL" not in clean:
                        if clean[0].isdigit() and not re.match(r'^\d{8}', clean): continue
                        in_futures, in_options, current_block_name, found_o = False, True, clean, True
                        print(f"[DEBUG - BLOCK] Entered OPTIONS block: {current_block_name}")
                        break
                if not found_o and in_options and clean == "MAR26": 
                    current_block_name, current_option_month = "E-MINI NASDAQ 100 WEEKLY-4", "MAR26"
                    print(f"[DEBUG - BLOCK] Fallback Options block applied: {current_block_name}")
                
                # Process Futures data
                if in_futures:
                    if "TOTAL" in clean: 
                        in_futures = False
                        print(f"[DEBUG - BLOCK] Exited FUTURES block: {current_block_name} (Hit TOTAL)")
                    else:
                        parts = clean.split()
                        if parts and len(parts[0]) == 5 and parts[0][:3] in TARGET_MONTHS: 
                            res = process_futures_block(f"{current_block_name} {parts[0]}", [clean], page_num)
                            futures_results.append(res)
                            print(f"[DEBUG - HIT] Future parsed -> Contract: {res['Contract']} | Sett: {res['Sett']:.2f} | Chg: {res['Change']:+.2f} | Vol: {res['Volume']} | OI: {res['OI']}")
                
                # Process Options data
                if in_options:
                    if clean.startswith("TOTAL"):
                        res = process_options_total(current_block_name, current_option_month, clean, page_num, current_side)
                        if res:
                            current_score = get_month_score(res["Month"])
                            if res["Series"] not in seen_options: 
                                options_results.append(res)
                                seen_options[res["Series"]] = current_score
                                print(f"[DEBUG - HIT] Option parsed (New) -> {res['Series']} {res['Month']} | Vol: {res['Volume']} | OI: {res['OI']}")
                            elif current_score >= seen_options[res["Series"]]:
                                if not any(x for x in options_results if x["Series"] == res["Series"] and x["Month"] == res["Month"]): 
                                    options_results.append(res)
                                    seen_options[res["Series"]] = current_score
                                    print(f"[DEBUG - HIT] Option parsed (Updated Date) -> {res['Series']} {res['Month']} | Vol: {res['Volume']} | OI: {res['OI']}")

    # --- ITEMISED DEBUG LOGS ---
    print("\n" + "="*105 + f"\n{'PAGE':<8} {'FUTURES':<25} {'SETT':<12} {'CHG':<10} {'VOL':<12} {'OI':<12} {'ΔOI':<10}\n" + "="*105)
    for r in futures_results: print(f"{r['Page']:<8} {r['Contract']:<25} {r['Sett']:<12.2f} {r['Change']:<+10.2f} {r['Volume']:<12,} {r['OI']:<12,} {r['Delta']:<10}")
    print("\n" + "="*120 + f"\n{'PAGE':<8} {'OPTIONS SERIES':<50} {'MONTH':<10} {'VOL':<12} {'OI':<12} {'ΔOI':<10}\n" + "="*120)
    for r in options_results: print(f"{r['Page']:<8} {r['RawName'][:50]:<50} {r['Month']:<10} {r['Volume']:<12,} {r['OI']:<12,} {r['Delta']:<10}")

    # --- CALCULATIONS: FUTURES ---
    print("\n[DEBUG - MATH] --- AGGREGATING FUTURES ---")
    f_sum = {}
    for r in futures_results:
        m, w = r["Month"], (0.1 if "MNQ" in r["Contract"] else 1.0)
        if m not in f_sum: 
            f_sum[m] = {"av":0,"ao":0,"ad":0,"rv":0,"ro":0,"rd":0,"s":0.0,"c":0.0}
            print(f"[DEBUG - MATH] Initialized accumulator for Future Month: {m}")
        
        if "EMINI NASD FUT" in r["Contract"]:
            f_sum[m]["s"] = r["Sett"]
            f_sum[m]["c"] = r["Change"]
            print(f"[DEBUG - MATH] {m} Base Settlement updated to {r['Sett']} (from {r['Contract']})")
            
        d = (to_int(r["Delta"]) if r["Delta"] not in ["UNCH", "NEW"] else 0)*w
        f_sum[m]["av"] += r["Volume"]*w
        f_sum[m]["ao"] += r["OI"]*w
        f_sum[m]["ad"] += d
        print(f"[DEBUG - MATH] {r['Contract']} ({m}): Weight {w}x -> Adding Vol {r['Volume']*w}, OI {r['OI']*w}")
        
        if w == 0.1: 
            f_sum[m]["rv"] += r["Volume"]*w
            f_sum[m]["ro"] += r["OI"]*w
            f_sum[m]["rd"] += d

    # --- CALCULATIONS: OPTIONS ---
    print("\n[DEBUG - MATH] --- AGGREGATING OPTIONS ---")
    opt_sum = {}
    for r in options_results:
        m, w = r["Month"], (0.1 if any(t in r["Series"] for t in RETAIL_TICKERS) else 1.0)
        if m not in opt_sum: 
            opt_sum[m] = {"V_Gross":0,"V_Calls":0,"V_Puts":0,"OI_Net":0,"D_Net":0}
            print(f"[DEBUG - MATH] Initialized accumulator for Option Month: {m}")
        
        v, oi, d = r["Volume"]*w, r["OI"]*w, (to_int(r["Delta"]) if r["Delta"] not in ["UNCH", "NEW"] else 0)*w
        opt_sum[m]["V_Gross"] += v
        print(f"[DEBUG - MATH] {r['Series']} ({m}) {r['Side']}: Weight {w}x -> Adding Gross Vol {v}")
        
        if r["Side"] == "CALLS":
            opt_sum[m]["V_Calls"] += v
            opt_sum[m]["OI_Net"] += oi
            opt_sum[m]["D_Net"] += d
        else:
            opt_sum[m]["V_Puts"] += v
            opt_sum[m]["OI_Net"] -= oi
            opt_sum[m]["D_Net"] -= d

    # --- PREPARE RECORDS FOR CSV / HTML ---
    print("\n[DEBUG - SYSTEM] Building Final Output Records...")
    records = []
    for m in sorted(f_sum.keys(), key=get_month_score):
        s = f_sum[m]
        records.append({"Type":"ALL","Month":m,"Sett_PC":f"{s['s']:.2f}", "Change":f"{s['c']:+.2f}","Vol":s['av'],"OI":s['ao'],"Delta":s['ad']})
        records.append({"Type":"RET","Month":m,"Sett_PC":f"{s['s']:.2f}", "Change":f"{s['c']:+.2f}","Vol":s['rv'],"OI":s['ro'],"Delta":s['rd']})
                         
    for m in sorted(opt_sum.keys(), key=get_month_score):
        s = opt_sum[m]
        if s["V_Gross"] == 0 and s["OI_Net"] == 0: continue
        pc = s["V_Puts"] / s["V_Calls"] if s["V_Calls"] > 0 else 0.0
        records.append({"Type":"OPT","Month":m,"Sett_PC":f"{pc:.2f}", "Change":"-","Vol":s['V_Gross'],"OI":s['OI_Net'],"Delta":s['D_Net']})

    link = archive_and_publish(records, trade_date)

    # --- TELEGRAM OUTPUT ---
    print("\n[DEBUG - SYSTEM] Formatting Telegram Layout...")
    tg_msg = [f"📈 <b>NASDAQ 100 - {trade_date}</b>", "", "<b>FUTURES (STANDARD UNITS)</b>", "<code>MO   |TYP|  ST | CHG | VOL |  OI | ΔOI</code>"]
    for m in sorted(f_sum.keys(), key=get_month_score):
        s = f_sum[m]
        tg_msg.append(f"<code>{m:5}|ALL|{s['s']:5.0f}|{s['c']:+5.0f}|{format_num(s['av']):>5}|{format_num(s['ao']):>5}|{format_num(s['ad']):>5}</code>")
        tg_msg.append(f"<code>{m:5}|RET|{s['s']:5.0f}|{s['c']:+5.0f}|{format_num(s['rv']):>5}|{format_num(s['ro']):>5}|{format_num(s['rd']):>5}</code>")
        tg_msg.append("---------------------------------------")
        
    tg_msg.append("\n<b>OPTIONS SUMMARY</b>")
    tg_msg.append("<code>MO    | VOL  |  P/C  |  OI   |  ΔOI </code>")

    for m in sorted(opt_sum.keys(), key=get_month_score):
        s = opt_sum[m]
        if s["V_Gross"] == 0 and s["OI_Net"] == 0: continue 
        pc_ratio = s["V_Puts"] / s["V_Calls"] if s["V_Calls"] > 0 else 0.0
        row = f"{m:5} | {format_num(s['V_Gross']):>4} | {pc_ratio:5.2f} | {format_num(s['OI_Net']):>5} | {format_num(s['D_Net']):>5}"
        tg_msg.append(f"<code>{row}</code>")

    if link:
        tg_msg.append(f"\n<a href='{link}'>🔍 Interactive History Dashboard</a>")

    msg = "\n".join(tg_msg)
    print("\n[DEBUG - SYSTEM] Final Message Output:\n")
    print(msg) 
    
    print("\n[DEBUG - HTTP] Pushing to Telegram API...")
    requests.post(
        f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
        json={"chat_id": CHAT_ID, "text": msg, "parse_mode": "HTML", "disable_web_page_preview": True}
    )
    print("[DEBUG - SYSTEM] --- JOB COMPLETE ---")

if __name__ == "__main__":
    run_comprehensive_vacuum()
