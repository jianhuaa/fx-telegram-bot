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
PDF_URL        = "https://www.cmegroup.com/daily_bulletin/current/Section74_Cryptocurrency.pdf"
TELEGRAM_TOKEN = "8577879935:AAEpSjAz4wdcZ9Lb7AJpURRk8haADlPCbHo"
CHAT_ID        = "876384974"

GITHUB_TOKEN   = os.environ.get("GIST_TOKEN", "")
CSV_FILE       = "bitcoin_history.csv"
GIST_ID_FILE   = "bitcoin_gist.txt"

# BTC-equivalent weights
W_FUT      = {"BTC FUT": 1.0, "MBT FUT": 0.1,  "BFF FUT": 0.02}
W_OPT_SIZE = {"BTC OPT": 1.0, "MBT OPT": 0.02, "BFF OPT": 0.004}
TARGET_FUTS = list(W_FUT.keys())
TARGET_OPTS = list(W_OPT_SIZE.keys())
MONTHS      = ["JAN","FEB","MAR","APR","MAY","JUN","JUL","AUG","SEP","OCT","NOV","DEC"]
MONTH_RE    = re.compile(r'\b(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)\d{2}\b')

# ─────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────

def get_month_score(m):
    try: return int(m[3:]) * 100 + MONTHS.index(m[:3].upper()) + 1
    except: return 0

def to_float(s):
    s = re.sub(r'[#*,BAba]', '', str(s)).strip()
    if s in ('', '----', 'UNCH', 'NEW'): return 0.0
    try: return float(s)
    except: return 0.0

def to_int(s): return int(to_float(s))

def format_num(val):
    n = round(float(str(val).replace(",",""))) if str(val).replace(",","").replace(".","").replace("-","").isdigit() else 0
    try: n = round(float(val))
    except: pass
    a = abs(n); sign = "-" if n < 0 else ""
    if a < 1000:   return str(n)
    if a < 10000:  return f"{sign}{a/1000:.1f}k"
    return f"{sign}{round(a/1000)}k"

def fix_chg_token(t):
    # "3+605.00" -> "+3605.00"
    m = re.match(r'^(\d+)([+\-])(\d*\.?\d+)$', t)
    if m: return m.group(2) + m.group(1) + m.group(3)
    return t

# ─────────────────────────────────────────────
# HTML PAGE BUILDER
# ─────────────────────────────────────────────

def build_html_page(df):
    df_fut = df[df["Type"].isin(["ALL","RET"])]
    df_opt = df[df["Type"] == "OPT"]

    rows_fut_html = ""
    for _, r in df_fut.iterrows():
        chg_val = str(r["Change"])
        try:
            chg_num = float(chg_val.replace("+",""))
            pct_class = "pos" if chg_num > 0 else ("neg" if chg_num < 0 else "")
        except: pct_class = ""
        rows_fut_html += (
            f'<tr data-date="{r["Date"]}" data-typ="{r["Type"]}">'
            f'<td>{r["Date"]}</td><td>{r["Month"]}</td><td>{r["Type"]}</td>'
            f'<td>{r["Sett_PC"]}</td>'
            f'<td class="{pct_class}">{r["Change"]}</td>'
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
<title>Bitcoin CME Master History</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: 'Courier New', monospace; background: #0d0d0d; color: #e0e0e0; padding: 6px; font-size: 0.7rem; }}
  h2 {{ color: #ff9900; margin: 8px 0; font-size: 1rem; letter-spacing: 0.5px; text-align: center; }}
  h3 {{ color: #ffd700; margin: 12px 0 4px 0; font-size: 0.85rem; border-bottom: 1px solid #333; padding-bottom: 2px; }}
  .controls {{ display: flex; justify-content: center; align-items: center; margin-bottom: 12px; gap: 6px; flex-wrap: wrap; }}
  .controls label {{ color: #888; font-size: 0.75rem; }}
  select {{ padding: 4px 6px; background: #1a1a1a; color: #ccc; border: 1px solid #444; border-radius: 4px; font-size: 0.75rem; font-family: inherit; }}
  button {{ padding: 4px 8px; cursor: pointer; background: #1a1a1a; color: #ccc; border: 1px solid #444; border-radius: 4px; font-size: 0.75rem; font-family: inherit; }}
  button.active {{ background: #ff9900; color: #000; border-color: #ff9900; font-weight: bold; }}
  .table-wrap {{ width: 100%; margin-bottom: 16px; overflow-x: auto; }}
  table {{ border-collapse: collapse; white-space: nowrap; width: 100%; table-layout: fixed; }}
  th, td {{ border: 1px solid #2a2a2a; padding: 4px 2px; text-align: right; overflow: hidden; position: relative; }}
  th {{ text-align: left; background: #161616; color: #ff9900; cursor: pointer; user-select: none; touch-action: manipulation; }}

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
<h2>🟠 Bitcoin CME Master</h2>
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
    <th onclick="handleMultiSort('tbl-fut',0)">Date<span class="sort-rank-wrap"></span></th>
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
    if not GITHUB_TOKEN: return None
    headers = {"Authorization": f"token {GITHUB_TOKEN}", "Accept": "application/vnd.github+json"}
    payload = {"description": "Bitcoin CME Master", "public": True,
                "files": {"bitcoin.html": {"content": html}}}
    gid = load_gist_id()
    try:
        if gid:
            resp = requests.patch(f"https://api.github.com/gists/{gid}", headers=headers, json=payload)
            if resp.status_code == 200:
                return "https://htmlpreview.github.io/?" + resp.json()["files"]["bitcoin.html"]["raw_url"]
        resp = requests.post("https://api.github.com/gists", headers=headers, json=payload)
        if resp.status_code == 201:
            Path(GIST_ID_FILE).write_text(resp.json()["id"])
            return "https://htmlpreview.github.io/?" + resp.json()["files"]["bitcoin.html"]["raw_url"]
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
                if last_row[0] == clean_date:
                    already_exists = True

    if not already_exists:
        with open(CSV_FILE, 'a', newline='') as f:
            writer = csv.writer(f)
            if not file_exists:
                writer.writerow(['Date','Type','Month','Sett_PC','Change','Vol','OI','Delta'])
            for r in records:
                writer.writerow([clean_date, r['Type'], r['Month'], r['Sett_PC'],
                                  r['Change'], r['Vol'], r['OI'], r['Delta']])

    df = pd.read_csv(CSV_FILE).sort_values(by=['Date','Type','Month'], ascending=[False,True,True])
    html = build_html_page(df)
    Path("bitcoin.html").write_text(html, encoding="utf-8")
    return push_to_gist(html)

# ─────────────────────────────────────────────
# FUTURES LINE PARSER
# ─────────────────────────────────────────────

def process_futures_block(product_name, clean_line):
    if not re.match(r'^[A-Z]{3}\d{2}', clean_line): return None
    tokens = [fix_chg_token(t) for t in clean_line.split()]
    if len(tokens) < 5: return None

    month = tokens[0]
    if not re.match(r'^[A-Z]{3}\d{2}$', month): return None

    chg_idx = -1
    for i in range(1, len(tokens)):
        t = tokens[i]
        if t in ('UNCH', 'NEW'): chg_idx = i; break
        if re.match(r'^[+\-]\d[\d.]*$', t): chg_idx = i; break
    if chg_idx == -1: return None

    sett = to_float(tokens[chg_idx - 1])
    chg  = 0.0 if tokens[chg_idx] in ('UNCH','NEW') else to_float(tokens[chg_idx])

    post = tokens[chg_idx + 1:]
    nums = []; delta = 0; i = 0
    while i < len(post):
        t = post[i]
        if t == '----': i += 1; continue
        if t in ('+','-') and i+1 < len(post) and re.match(r'^\d+$', post[i+1]):
            d = to_int(post[i+1]); delta = d if t == '+' else -d; i += 2; continue
        if re.match(r'^[+\-]\d+$', t): delta = to_int(t); i += 1; continue
        if re.match(r'^[\d,]+\.?\d*[BA]$', t): break
        if re.match(r'^[\d,]+\.?\d*$', t): nums.append(t)
        i += 1

    rth = glob = oi = 0
    if len(nums) >= 3: rth, glob, oi = to_int(nums[0]), to_int(nums[1]), to_int(nums[2])
    elif len(nums) == 2: glob, oi = to_int(nums[0]), to_int(nums[1])
    elif len(nums) == 1: oi = to_int(nums[0])
    vol = rth + glob

    print(f"[DEBUG] ✅ {product_name} {month}: Sett={sett} | Chg={chg} | Vol={vol} | OI={oi} | Delta={delta}")
    return {"Product": product_name, "Month": month, "Sett": sett,
            "Change": chg, "Volume": vol, "OI": oi, "Delta": delta}

# ─────────────────────────────────────────────
# OPTIONS TOTAL PARSER
# ─────────────────────────────────────────────

def process_options_total(current_name, month, line, side):
    tokens = line.replace(',','').split()
    try: ti = tokens.index('TOTAL')
    except: return None
    rest = [t for t in tokens[ti+1:] if not re.match(r'^[A-Z]{2,}$', t)]
    if len(rest) < 2: return None
    vol = to_int(rest[0]); oi = to_int(rest[1]); delta = 0
    if len(rest) >= 4 and rest[2] in ('+','-'):
        delta = to_int(rest[3]); delta = -delta if rest[2] == '-' else delta
    elif len(rest) >= 3 and re.match(r'^[+\-]\d+$', rest[2]):
        delta = to_int(rest[2])
    return {"Series": current_name, "Month": month, "Volume": vol,
            "OI": oi, "Delta": delta, "Side": side}

# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────

def run_comprehensive_vacuum():
    print("--- STARTING BITCOIN CME PARSER ---")
    scraper   = cloudscraper.create_scraper(browser='chrome')
    pdf_bytes = io.BytesIO(scraper.get(PDF_URL).content)

    futures_results, options_results = [], []
    trade_date = "Unknown Date"

    with pdfplumber.open(pdf_bytes) as pdf:
        active_f    = None
        in_opt      = False
        c_name      = "UNKNOWN"
        c_opt_month = "UNKNOWN"
        side        = "CALLS"

        for p_idx, page in enumerate(pdf.pages):
            text = page.extract_text() or ""
            if p_idx == 0:
                d_match = re.search(r'[A-Z][a-z]{2}, ([A-Z][a-z]{2} \d{2}, \d{4})', text)
                if d_match: trade_date = d_match.group(1)

            for line in text.split('\n'):
                clean = line.strip().upper()
                if not clean: continue

                has_month = bool(MONTH_RE.search(clean))

                # Block header: product name line, no month, no TOTAL
                if not has_month and 'TOTAL' not in clean:
                    for f_key in TARGET_FUTS:
                        if f_key in clean:
                            active_f = f_key; in_opt = False
                            print(f"[BLOCK->FUT] {f_key}"); break
                    else:
                        for o_key in TARGET_OPTS:
                            if o_key in clean:
                                active_f = None; in_opt = True; c_name = o_key
                                print(f"[BLOCK->OPT] {o_key}"); break

                if 'CALLS' in clean and not has_month: side = "CALLS"; continue
                if 'PUTS'  in clean and not has_month: side = "PUTS";  continue

                if 'TOTAL' in clean:
                    if in_opt:
                        res = process_options_total(c_name, c_opt_month, clean, side)
                        if res: options_results.append(res)
                    if active_f and active_f.replace(' ','') in clean.replace(' ',''):
                        active_f = None
                    continue

                if active_f and has_month:
                    res = process_futures_block(active_f, clean)
                    if res: futures_results.append(res)

                if in_opt and has_month:
                    m = MONTH_RE.search(clean)
                    if m and any(k in clean for k in TARGET_OPTS):
                        c_opt_month = m.group()

    # --- AGGREGATION FUTURES ---
    f_sum = {}
    for r in futures_results:
        m, w = r["Month"], W_FUT.get(r["Product"], 0)
        if m not in f_sum: f_sum[m] = {"av":0,"ao":0,"ad":0,"rv":0,"ro":0,"rd":0,"s":0,"c":0}
        if r["Product"] == "BTC FUT" and r["Sett"] > 0:
            f_sum[m]["s"] = r["Sett"]; f_sum[m]["c"] = r["Change"]
        f_sum[m]["av"] += r["Volume"] * w
        f_sum[m]["ao"] += r["OI"]     * w
        f_sum[m]["ad"] += r["Delta"]  * w
        if w < 1.0:
            f_sum[m]["rv"] += r["Volume"] * w
            f_sum[m]["ro"] += r["OI"]     * w
            f_sum[m]["rd"] += r["Delta"]  * w

    # --- AGGREGATION OPTIONS ---
    opt_sum = {}
    for r in options_results:
        m, w = r["Month"], W_OPT_SIZE.get(r["Series"], 1.0)
        if m not in opt_sum: opt_sum[m] = {"total_vol":0,"net_oi":0,"net_delta":0,"vc":0,"vp":0}
        v = r["Volume"]*w; oi = r["OI"]*w; d = r["Delta"]*w
        opt_sum[m]["total_vol"] += v
        if r["Side"] == "CALLS":
            opt_sum[m]["vc"]        += v
            opt_sum[m]["net_oi"]    += oi
            opt_sum[m]["net_delta"] += d
        else:
            opt_sum[m]["vp"]        += v
            opt_sum[m]["net_oi"]    -= oi
            opt_sum[m]["net_delta"] -= d

    # --- PREPARE RECORDS FOR CSV/HTML ---
    records = []
    for m in sorted(f_sum.keys(), key=get_month_score):
        s = f_sum[m]
        records.append({"Type":"ALL","Month":m,"Sett_PC":f"{s['s']:.0f}",
                         "Change":f"{s['c']:+.0f}","Vol":s['av'],"OI":s['ao'],"Delta":s['ad']})
        records.append({"Type":"RET","Month":m,"Sett_PC":f"{s['s']:.0f}",
                         "Change":f"{s['c']:+.0f}","Vol":s['rv'],"OI":s['ro'],"Delta":s['rd']})
    for m in sorted(opt_sum.keys(), key=get_month_score):
        s = opt_sum[m]
        if s["total_vol"] == 0: continue
        pc = s["vp"] / s["vc"] if s["vc"] > 0 else 0.0
        records.append({"Type":"OPT","Month":m,"Sett_PC":f"{pc:.2f}",
                         "Change":"-","Vol":s['total_vol'],"OI":s['net_oi'],"Delta":s['net_delta']})

    link = archive_and_publish(records, trade_date)

    # --- TELEGRAM ---
    tg_msg = [
        f"🟠 <b>BITCOIN - {trade_date}</b>",
        "",
        "<b>FUTURES (STANDARD UNITS)</b>",
        "<code>MO   |TYP|  ST  |  CHG | VOL| OI  | ΔOI</code>",
    ]

    for m in sorted(f_sum.keys(), key=get_month_score):
        s = f_sum[m]
        if s['s'] == 0 and s['av'] == 0 and s['ao'] == 0: continue
        tg_msg.append(f"<code>{m:5}|ALL|{s['s']:6.0f}|{s['c']:+6.0f}|{format_num(s['av']):>4}|{format_num(s['ao']):>5}|{format_num(s['ad']):>4}</code>")
        tg_msg.append(f"<code>{m:5}|RET|{s['s']:6.0f}|{s['c']:+6.0f}|{format_num(s['rv']):>4}|{format_num(s['ro']):>5}|{format_num(s['rd']):>4}</code>")
        tg_msg.append("-------------------------------")

    tg_msg.append("\n<b>OPTIONS SUMMARY</b>\n<code>MO   | VOL | P/C | OI  | ΔOI</code>")
    if not opt_sum:
        tg_msg.append("<code>No options data found</code>")
    else:
        for m in sorted(opt_sum.keys(), key=get_month_score):
            s  = opt_sum[m]
            pc = s["vp"] / s["vc"] if s["vc"] > 0 else 0.0
            row = f"{m:5}|{format_num(s['total_vol']):>5}|{pc:5.2f}|{format_num(s['net_oi']):>5}|{format_num(s['net_delta']):>5}"
            tg_msg.append(f"<code>{row}</code>")

    if link:
        tg_msg.append(f"\n<a href='{link}'>🔍 Interactive History</a>")

    msg = "\n".join(tg_msg)
    print("\n" + msg + "\n")
    requests.post(
        f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
        json={"chat_id": CHAT_ID, "text": msg, "parse_mode": "HTML",
              "disable_web_page_preview": True}
    )
    print("--- DONE ---")

if __name__ == "__main__":
    run_comprehensive_vacuum()
