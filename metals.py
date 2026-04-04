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
FUT_URL = "https://www.cmegroup.com/daily_bulletin/current/Section62_Metals_Futures_Products.pdf"
OPT_URL = "https://www.cmegroup.com/daily_bulletin/current/Section64_Metals_Option_Products.pdf"

TELEGRAM_TOKEN = "8577879935:AAEpSjAz4wdcZ9Lb7AJpURRk8haADlPCbHo"
CHAT_ID = "876384974"

GITHUB_TOKEN   = os.environ.get("GIST_TOKEN", "")
CSV_FILE       = "metals_history.csv"
GIST_ID_FILE   = "metals_gist.txt"

# --- SCALING WEIGHTS ---
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
    if "PL" in sym: return ".0f"
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
                if tokens[i-1][0] in "0123456789.":
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

# ─────────────────────────────────────────────
# HTML PAGE BUILDER
# ─────────────────────────────────────────────

def build_html_page(df):
    df_fut = df[df["Type"].isin(["ALL", "RET"])]
    df_opt = df[df["Type"] == "OPT"]

    assets = sorted(df["Asset"].unique().tolist())
    filter_buttons = "\n  ".join(f'<button onclick="filterAsset(\'{a}\')" data-asset="{a}">{a}</button>' for a in assets)

    rows_fut_html = ""
    for _, r in df_fut.iterrows():
        try:
            chg_num = float(str(r["Change"]).replace("+", ""))
            pct_class = "pos" if chg_num > 0 else ("neg" if chg_num < 0 else "")
        except:
            pct_class = ""
            chg_num = 0.0

        display_sett = str(r["Sett_PC"])
        display_chg = str(r["Change"])

        try:
            val_sett = float(display_sett.replace(',', ''))
            if r["Asset"] in ["GOLD", "PLATINUM"]:
                display_sett = f"{val_sett:.0f}"
                display_chg = f"{chg_num:+.0f}"
            elif r["Asset"] in ["COPPER", "SILVER"]:
                display_sett = f"{val_sett:.2f}"
                display_chg = f"{chg_num:+.2f}"
        except: pass

        rows_fut_html += (
            f'<tr data-date="{r["Date"]}" data-typ="{r["Type"]}" data-asset="{r["Asset"]}">'
            f'<td>{r["Date"]}</td><td class="id-cell">{r["Asset"][:3]}</td><td>{r["Month"]}</td><td>{r["Type"]}</td>'
            f'<td>{display_sett}</td>'
            f'<td class="{pct_class}">{display_chg}</td>'
            f'<td>{format_num(r["Vol"])}</td>'
            f'<td>{format_num(r["OI"])}</td>'
            f'<td>{format_num(r["Delta"])}</td></tr>\n'
        )

    rows_opt_html = ""
    for _, r in df_opt.iterrows():
        rows_opt_html += (
            f'<tr data-date="{r["Date"]}" data-asset="{r["Asset"]}">'
            f'<td>{r["Date"]}</td><td class="id-cell">{r["Asset"][:3]}</td><td>{r["Month"]}</td><td>{r["Sett_PC"]}</td>'
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
<title>Metals CME Master History</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: 'Courier New', monospace; background: #0d0d0d; color: #e0e0e0; padding: 12px; }}
  h2 {{ color: #00aaff; margin-bottom: 12px; font-size: 1.1rem; letter-spacing: 1px; }}
  .controls {{ display: flex; flex-wrap: wrap; gap: 8px; align-items: center; margin-bottom: 10px; }}
  .controls label {{ color: #888; font-size: 0.85rem; margin-right: -4px; }}
  button {{ padding: 6px 13px; cursor: pointer; background: #1a1a1a; color: #ccc; border: 1px solid #444; border-radius: 4px; font-size: 0.85rem; font-family: inherit; }}
  button.active {{ background: #00aaff; color: #000; border-color: #00aaff; font-weight: bold; }}
  select {{ padding: 6px 8px; background: #1a1a1a; color: #ccc; border: 1px solid #444; border-radius: 4px; font-size: 0.85rem; font-family: inherit; }}
  .count {{ font-size: 0.8rem; color: #555; margin-bottom: 8px; }}
  .table-wrap {{ width: 100%; margin-bottom: 16px; overflow-x: auto; }}
  table {{ border-collapse: collapse; font-size: 0.72rem; white-space: nowrap; width: 100%; table-layout: fixed; }}
  th, td {{ border: 1px solid #2a2a2a; padding: 5px 3px; text-align: right; overflow: hidden; position: relative; }}
  th {{ text-align: left; background: #161616; color: #00aaff; cursor: pointer; user-select: none; touch-action: manipulation; }}

  #tbl-fut th:nth-child(1), #tbl-fut td:nth-child(1) {{ width: 18%; font-size: 0.62rem;}}
  #tbl-fut th:nth-child(2), #tbl-fut td:nth-child(2) {{ width: 9%; }}
  #tbl-fut th:nth-child(3), #tbl-fut td:nth-child(3) {{ width: 11%; }}
  #tbl-fut th:nth-child(4), #tbl-fut td:nth-child(4) {{ width: 8%; }}
  #tbl-fut th:nth-child(5), #tbl-fut td:nth-child(5) {{ width: 13%; }}
  #tbl-fut th:nth-child(6), #tbl-fut td:nth-child(6) {{ width: 13%; }}
  #tbl-fut th:nth-child(7), #tbl-fut td:nth-child(7) {{ width: 10%; font-size: 0.68rem;}}
  #tbl-fut th:nth-child(8), #tbl-fut td:nth-child(8) {{ width: 9%; }}
  #tbl-fut th:nth-child(9), #tbl-fut td:nth-child(9) {{ width: 9%; }}

  #tbl-opt th:nth-child(1), #tbl-opt td:nth-child(1) {{ width: 22%; font-size: 0.62rem;}}
  #tbl-opt th:nth-child(2), #tbl-opt td:nth-child(2) {{ width: 10%; }}
  #tbl-opt th:nth-child(3), #tbl-opt td:nth-child(3) {{ width: 11%; }}
  #tbl-opt th:nth-child(4), #tbl-opt td:nth-child(4) {{ width: 11%; }}
  #tbl-opt th:nth-child(5), #tbl-opt td:nth-child(5) {{ width: 16%; }}
  #tbl-opt th:nth-child(6), #tbl-opt td:nth-child(6) {{ width: 16%; }}
  #tbl-opt th:nth-child(7), #tbl-opt td:nth-child(7) {{ width: 14%; }}

  th .arrow {{ font-size: 0.6rem; color: #444; }}
  th.sorted .arrow {{ color: #00aaff; }}
  th .sort-rank {{ position: absolute; top: 1px; right: 1px; font-size: 0.55rem; color: #ff5252; font-weight: bold; }}
  td.id-cell {{ color: #ffd700; font-weight: bold; text-align: center; }}
  td.pos {{ color: #00e676; }}
  td.neg {{ color: #ff5252; }}
</style>
</head>
<body>
<h2>⚒️ Metals CME Master</h2>
<div class="controls">
  <label>Asset:</label>
  <button onclick="filterAsset('ALL')" data-asset="ALL" class="active">ALL</button>
  {filter_buttons}
  <label style="margin-left:4px">Type:</label>
  <button onclick="filterTyp('BOTH')" data-typ="BOTH" class="active">BOTH</button>
  <button onclick="filterTyp('ALL')"  data-typ="ALL">ALL</button>
  <button onclick="filterTyp('RET')"  data-typ="RET">RET</button>
  <label style="margin-left:4px">Date:</label>
  <select id="dateSelect" onchange="applyFilters()">
    <option value="">All dates</option>
    {date_options}
  </select>
</div>
<div class="count" id="rowCount">Loading...</div>

<h3>Futures</h3>
<div class="table-wrap">
<table id="tbl-fut">
  <thead><tr>
    <th onclick="handleMultiSort('tbl-fut',0)">Date <span class="arrow">▼</span></th>
    <th onclick="handleMultiSort('tbl-fut',1)">Ast <span class="arrow">▼</span></th>
    <th onclick="handleMultiSort('tbl-fut',2)">Mo <span class="arrow">▼</span></th>
    <th onclick="handleMultiSort('tbl-fut',3)">Typ <span class="arrow">▼</span></th>
    <th onclick="handleMultiSort('tbl-fut',4)">Sett <span class="arrow">▼</span></th>
    <th onclick="handleMultiSort('tbl-fut',5)">Chg <span class="arrow">▼</span></th>
    <th onclick="handleMultiSort('tbl-fut',6)">Vol <span class="arrow">▼</span></th>
    <th onclick="handleMultiSort('tbl-fut',7)">OI <span class="arrow">▼</span></th>
    <th onclick="handleMultiSort('tbl-fut',8)">ΔOI <span class="arrow">▼</span></th>
  </tr></thead>
  <tbody>
{rows_fut_html}  </tbody>
</table>
</div>

<h3>Options</h3>
<div class="table-wrap">
<table id="tbl-opt">
  <thead><tr>
    <th onclick="handleMultiSort('tbl-opt',0)">Date <span class="arrow">▼</span></th>
    <th onclick="handleMultiSort('tbl-opt',1)">Ast <span class="arrow">▼</span></th>
    <th onclick="handleMultiSort('tbl-opt',2)">Mo <span class="arrow">▼</span></th>
    <th onclick="handleMultiSort('tbl-opt',3)">P/C <span class="arrow">▼</span></th>
    <th onclick="handleMultiSort('tbl-opt',4)">Vol <span class="arrow">▼</span></th>
    <th onclick="handleMultiSort('tbl-opt',5)">OI <span class="arrow">▼</span></th>
    <th onclick="handleMultiSort('tbl-opt',6)">ΔOI <span class="arrow">▼</span></th>
  </tr></thead>
  <tbody>
{rows_opt_html}  </tbody>
</table>
</div>
<script>
let sortState = {{'tbl-fut':[], 'tbl-opt':[]}};
let activeTyp = 'BOTH';
let activeAsset = 'ALL';

function filterAsset(asset) {{
  activeAsset = asset;
  document.querySelectorAll('button[data-asset]').forEach(b => b.classList.toggle('active', b.dataset.asset === asset));
  applyFilters();
}}

function filterTyp(typ) {{
  activeTyp = typ;
  document.querySelectorAll('button[data-typ]').forEach(b => b.classList.toggle('active', b.dataset.typ === typ));
  applyFilters();
}}

function applyFilters() {{
  const dateQ = document.getElementById('dateSelect').value;
  let visible = 0;

  document.querySelectorAll('#tbl-fut tbody tr').forEach(row => {{
    const showDate = !dateQ || row.dataset.date === dateQ;
    const showTyp  = activeTyp === 'BOTH' || row.dataset.typ === activeTyp;
    const showAst  = activeAsset === 'ALL' || row.dataset.asset === activeAsset;
    let show = showDate && showTyp && showAst;
    row.style.display = show ? '' : 'none';
    if (show) visible++;
  }});

  document.querySelectorAll('#tbl-opt tbody tr').forEach(row => {{
    const showDate = !dateQ || row.dataset.date === dateQ;
    const showAst  = activeAsset === 'ALL' || row.dataset.asset === activeAsset;
    let show = showDate && showAst;
    row.style.display = show ? '' : 'none';
    if (show) visible++;
  }});

  document.getElementById('rowCount').textContent = 'Showing ' + visible + ' rows';
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
    const oldRank = th.querySelector('.sort-rank');
    if (oldRank) oldRank.remove();
    if (rank !== -1) {{
      th.classList.add('sorted');
      th.querySelector('.arrow').innerHTML = sortState[tblId][rank].asc ? '▲' : '▼';
      const span = document.createElement('span');
      span.className = 'sort-rank';
      span.innerHTML = (rank + 1);
      th.appendChild(span);
    }} else {{
      th.classList.remove('sorted');
      th.querySelector('.arrow').innerHTML = '▼';
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
        print("\n[⚠️ WARNING] No GIST_TOKEN found! Skipping GitHub Gist upload.")
        print("[!] The interactive HTML link will NOT be generated locally.")
        return None

    headers = {"Authorization": f"token {GITHUB_TOKEN}", "Accept": "application/vnd.github+json"}
    payload = {"description": "Metals CME Master", "public": True,
                "files": {"metals.html": {"content": html}}}
    gid = load_gist_id()
    try:
        if gid:
            resp = requests.patch(f"https://api.github.com/gists/{gid}", headers=headers, json=payload)
            if resp.status_code == 200:
                link = "https://htmlpreview.github.io/?" + resp.json()["files"]["metals.html"]["raw_url"]
                print(f"\n[✓] SUCCESSFULLY UPDATED GIST: {link}")
                return link

        resp = requests.post("https://api.github.com/gists", headers=headers, json=payload)
        if resp.status_code == 201:
            Path(GIST_ID_FILE).write_text(resp.json()["id"])
            link = "https://htmlpreview.github.io/?" + resp.json()["files"]["metals.html"]["raw_url"]
            print(f"\n[✓] SUCCESSFULLY CREATED NEW GIST: {link}")
            return link
    except Exception as e:
        print(f"\n[ERROR] Failed to push to Gist: {e}")

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
                if last_row[0] == clean_date:
                    already_exists = True

    if not already_exists:
        with open(CSV_FILE, 'a', newline='') as f:
            writer = csv.writer(f)
            if not file_exists:
                writer.writerow(['Date','Asset','Type','Month','Sett_PC','Change','Vol','OI','Delta'])
            for r in records:
                writer.writerow([clean_date, r['Asset'], r['Type'], r['Month'], r['Sett_PC'],
                                  r['Change'], r['Vol'], r['OI'], r['Delta']])

    df = pd.read_csv(CSV_FILE).sort_values(by=['Date','Asset','Type','Month'], ascending=[False,True,True,True])

    html = build_html_page(df)
    Path("metals.html").write_text(html, encoding="utf-8")
    return push_to_gist(html)

def run_combined_vacuum():
    headers = {
        'Referer': 'https://www.cmegroup.com/market-data/volume-open-interest/exchange-volume.html',
    }

    # --- PART 1: SCRAPE OPTIONS ---
    print("=" * 80)
    print("SCRAPING OPTIONS: G8 METALS MASTER")
    print("=" * 80)

    time.sleep(2)
    resp_o = cureq.get(OPT_URL, impersonate="chrome120", headers=headers, timeout=45)
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

                # Heal CME dashed blanks and squished numbers to prevent block skipping
                clean = re.sub(r'-{2,}(?=[A-Z0-9])', ' ', clean)
                clean = re.sub(r'(\d)([-+])(\d)', r'\1 \2\3', clean)

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
    time.sleep(2)
    resp_f = cureq.get(FUT_URL, impersonate="chrome120", headers=headers, timeout=45)
    results_f, trade_date = [], "Unknown"

    # ── FIX: multiple platinum header variants to cover whatever the PDF uses ──
    FUT_MAP = {
        "1 OUNCE GOLD": "1OZ", "COMEX GOLD": "GC", "MICRO GOLD": "MGC", "E-MINI GOLD": "QO",
        "COMEX SILVER": "SI", "E-MINI SILVER": "QI", "MICRO SILVER": "SIL", "100-OUNCE SILVER": "SIC",
        "COMEX COPPER": "HG", "E-MINI COPPER": "QC", "MICRO COPPER": "MHG",
        "NYMEX PLATINUM FUTURES": "PL", "NYMEX PLATINUM": "PL", "PLATINUM FUTURES": "PL",
    }

    with pdfplumber.open(io.BytesIO(resp_f.content)) as pdf:
        active_code = None
        last_printed_code = None
        stop_parsing = False  # ── FIX: line-level sentinel flag

        for p_idx, page in enumerate(pdf.pages, start=1):
            if stop_parsing: break  # ── FIX: outer loop respects the flag

            text = page.extract_text() or ""
            if p_idx == 1:
                d_m = re.search(r'[A-Z][a-z]{2}, ([A-Z][a-z]{2} \d{2}, \d{4})', text)
                if d_m: trade_date = d_m.group(1)

            for line in text.split('\n'):
                clean = line.strip().upper()

                # Heal CME dashed blanks and squished numbers to prevent block skipping
                clean = re.sub(r'-{2,}(?=[A-Z0-9])', ' ', clean)
                clean = re.sub(r'(\d)([-+])(\d)', r'\1 \2\3', clean)

                # ── FIX: check sentinel at line level, not page blob level ──
                if "METALS CONTRACTS LAST TRADE DATES" in clean:
                    print(f"[!] Early exit triggered on P{p_idx}: '{clean}'")
                    stop_parsing = True
                    break

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

    # Store extracted data for CSV
    records = []

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
            # Build CSV Records for Futures
            for m in sorted(f_sum.keys(), key=get_month_score):
                s = f_sum[m]
                records.append({
                    "Asset": metal_name, "Type": "ALL", "Month": m,
                    "Sett_PC": f"{s['s']:{p}}", "Change": f"{s['c']:+{p}}",
                    "Vol": s['av'], "OI": s['ao'], "Delta": s['ad']
                })
                records.append({
                    "Asset": metal_name, "Type": "RET", "Month": m,
                    "Sett_PC": f"{s['s']:{p}}", "Change": f"{s['c']:+{p}}",
                    "Vol": s['rv'], "OI": s['ro'], "Delta": s['rd']
                })

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

        if f_sum or o_mos_master.get(metal_name): final_msg.append("-" * 42)

    # Build CSV Records for Options
    for metal_name in METALS_ORDER:
        if o_mos_master.get(metal_name):
            for m in sorted(o_mos_master[metal_name].keys(), key=get_month_score):
                o_s = o_mos_master[metal_name][m]
                if o_s["VC"] == 0 and o_s["VP"] == 0: continue
                pc = o_s["VP"] / o_s["VC"] if o_s["VC"] > 0 else 0.0
                records.append({
                    "Asset": metal_name, "Type": "OPT", "Month": m,
                    "Sett_PC": f"{pc:.2f}", "Change": "-",
                    "Vol": o_s["VC"] + o_s["VP"], "OI": o_s["ON"], "Delta": o_s["DN"]
                })

    # Trigger CSV/HTML generator logic
    link = archive_and_publish(records, trade_date)

    # Append interactive link before executing API push
    if link:
        final_msg.append(f"\n<a href='{link}'>🔍 Interactive History</a>")

    requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                  json={"chat_id": CHAT_ID, "text": "\n".join(final_msg), "parse_mode": "HTML", "disable_web_page_preview": True})

    print("\nDone. Message Sent.")

if __name__ == "__main__":
    run_combined_vacuum()
