import cloudscraper
import pdfplumber
import io
import re
import sys
import time
import os
import csv
import pandas as pd
import requests
from datetime import datetime
from itertools import combinations
from pathlib import Path

# ===== CONFIGURATION =====
TELEGRAM_TOKEN = "8577879935:AAEpSjAz4wdcZ9Lb7AJpURRk8haADlPCbHo"
CHAT_ID = "876384974"
CSV_FILE = "fx_options_history.csv"
GITHUB_TOKEN = os.environ.get("GIST_TOKEN", "")
GIST_ID_FILE = "gist_fx_id.txt"

CURRENCIES = [
    {'code': 'AUD', 'flag': '🇦🇺', 'search_report': 'AUD Options', 'search_pc': ['AUSTRALIAN DOLLAR', 'AUD/USD', 'ADU/USD']},
    {'code': 'CAD', 'flag': '🇨🇦', 'search_report': 'CAD Options', 'search_pc': ['CANADIAN DOLLAR', 'CAD/USD']},
    {'code': 'CHF', 'flag': '🇨🇭', 'search_report': 'CHF Options', 'search_pc': ['SWISS FRANC', 'CHF/USD']},
    {'code': 'EUR', 'flag': '🇪🇺', 'search_report': 'EUR Options', 'search_pc': ['EUROPEAN MONETARY UNIT', 'EURO FX', 'EUR/USD']},
    {'code': 'GBP', 'flag': '🇬🇧', 'search_report': 'GBP Options', 'search_pc': ['BRITISH POUND', 'GBP/USD']},
    {'code': 'JPY', 'flag': '🇯🇵', 'search_report': 'JPY Options', 'search_pc': ['JAPANESE YEN', 'JPY/USD']}
]

t = int(time.time())
URL_REPORT = f"https://www.cmegroup.com/reports/fx-report.pdf?t={t}"
URL_PUT_CALL = f"https://www.cmegroup.com/reports/fx-put-call.pdf?t={t}"

# --- HELPERS ---
def clean_numeric(val):
    if val is None: return 0.0
    s = str(val).strip()
    if s in ['', '-', '--', 'None', '$ -', '$0']: return 0.0
    cleaned = re.sub(r'[^\d.]', '', s)
    try: return float(cleaned) if cleaned else 0.0
    except ValueError: return 0.0

def format_vol(val):
    val_m = val / 1_000_000
    if val_m >= 1000: return f"${val_m/1000:.1f}B"
    return f"${int(round(val_m))}M"

def get_pdf(url):
    scraper = cloudscraper.create_scraper(browser={'browser': 'chrome', 'platform': 'windows', 'desktop': True})
    try:
        resp = scraper.get(url, timeout=45)
        resp.raise_for_status()
        if not resp.content.startswith(b'%PDF'):
            raise ValueError("CME returned a non-PDF response.")
        return io.BytesIO(resp.content)
    except Exception as e:
        print(f"❌ Scraping Failure for {url}: {e}")
        raise

# --- SCRAPING LOGIC (UNTOUCHED PER REQUEST) ---
def parse_fx_report(pdf_stream):
    results = {c['code']: {'nv_c': 0, 'nv_p': 0, 'oi_c': 0, 'oi_p': 0, 'e1_c':0, 'e1_p':0, 'e8_c':0, 'e8_p':0} for c in CURRENCIES}
    trade_date = ""
    with pdfplumber.open(pdf_stream) as pdf:
        for p in pdf.pages[:3]:
            text = p.extract_text() or ""
            date_match = re.search(r'(?:Trade Date|Update|Traded On)[:\s]*(\d{1,2}/\d{1,2}/\d{2,4})', text, re.IGNORECASE)
            if date_match:
                raw_date = date_match.group(1)
                try:
                    fmt = '%m/%d/%y' if len(raw_date.split('/')[-1]) == 2 else '%m/%d/%Y'
                    trade_date = datetime.strptime(raw_date, fmt).strftime('%Y-%m-%d')
                    break
                except: continue
        for page in pdf.pages:
            text = page.extract_text() or ""
            table = page.extract_table()
            if not table: continue
            target_key = None
            if "Notional Value: Put-Call Breakdown" in text: target_key = 'nv'
            elif "Notional Open Interest: Put-Call Breakdown" in text: target_key = 'oi'
            if target_key:
                for row in table:
                    if not row or len(row) < 3: continue
                    curr_name = str(row[0]).upper()
                    for c in CURRENCIES:
                        if c['search_report'].upper() in curr_name:
                            results[c['code']][f'{target_key}_c'] = clean_numeric(row[1])
                            results[c['code']][f'{target_key}_p'] = clean_numeric(row[2])
    return trade_date, results

def find_best_combination(puzzle_rows, target_gap):
    n = len(puzzle_rows)
    best_combo, best_diff, best_affinity_score = [], float('inf'), -1
    for r in range(n + 1):
        for combo in combinations(range(n), r):
            current_sum = sum(puzzle_rows[i]['raw_val'] for i in combo)
            diff = abs(current_sum - target_gap)
            affinity = sum(1 for i in combo if puzzle_rows[i]['hint'] == 'C') - sum(1 for i in combo if puzzle_rows[i]['hint'] == 'P')
            if diff <= 1.0:
                if affinity > best_affinity_score:
                    best_affinity_score = affinity
                    best_combo = list(combo)
                if best_affinity_score >= 0: return best_combo
            if diff < best_diff:
                best_diff, best_combo, best_affinity_score = diff, list(combo), affinity
    return best_combo

def parse_expiry_breakdown(pdf_stream, results):
    with pdfplumber.open(pdf_stream) as pdf:
        current_currency = None
        all_anchors = {c['code']: {'call': 0, 'put': 0} for c in CURRENCIES}
        currency_rows = {c['code']: [] for c in CURRENCIES}
        for page in pdf.pages:
            text = (page.extract_text() or "").upper()
            lines = text.split('\n')
            for line in lines:
                for c in CURRENCIES:
                    if any(term.upper() in line for term in c['search_pc']):
                        current_currency = c['code']
                        nums = [clean_numeric(s) for s in line.split() if clean_numeric(s) > 1000]
                        if len(nums) >= 2:
                            all_anchors[current_currency]['call'], all_anchors[current_currency]['put'] = nums[0], nums[1]
                        break
            tables = page.extract_tables()
            for table in tables:
                if not current_currency: continue
                for row in table:
                    clean_row = [str(r).strip() if r is not None else "" for r in row]
                    dte_found = next((int(clean_row[i]) for i in [1, 2] if i < len(clean_row) and clean_row[i].isdigit()), None)
                    if dte_found is None: continue
                    c_idx, p_idx, t_idx = (4, 5, 6) if not clean_row[1].isdigit() and clean_row[2].isdigit() else (3, 4, 5)
                    c_val_raw, p_val_raw = (clean_row[c_idx] if c_idx < len(clean_row) else ""), (clean_row[p_idx] if p_idx < len(clean_row) else "")
                    c_num, p_num = clean_numeric(c_val_raw), clean_numeric(p_val_raw)
                    if c_val_raw and p_val_raw:
                        currency_rows[current_currency].append({'dte': dte_found, 'c': c_num, 'p': p_num, 'type': 'certain'})
                    else:
                        vals = [clean_numeric(v) for v in clean_row[c_idx:t_idx] if clean_numeric(v) > 0 or v == '0']
                        if not vals: continue
                        raw_val = vals[0]
                        hint = 'C' if clean_numeric(c_val_raw) == raw_val and c_val_raw != "" else 'P'
                        currency_rows[current_currency].append({'dte': dte_found, 'raw_val': raw_val, 'hint': hint, 'c': 0, 'p': 0, 'type': 'puzzle'})
        for code in [c['code'] for c in CURRENCIES]:
            rows, anchors = currency_rows[code], all_anchors[code]
            if not rows or anchors['call'] == 0: continue
            known_c = sum(r['c'] for r in rows if r['type'] == 'certain')
            puzzles = [r for r in rows if r['type'] == 'puzzle']
            if puzzles:
                winning_indices = find_best_combination(puzzles, anchors['call'] - known_c)
                for idx, r in enumerate(puzzles):
                    if idx in winning_indices: r['c'], r['p'] = r['raw_val'], 0.0
                    else: r['c'], r['p'] = 0.0, r['raw_val']
            for r in rows:
                group = 'e1' if r['dte'] <= 7 else 'e8'
                results[code][f'{group}_c'] += r['c']
                results[code][f'{group}_p'] += r['p']
    return results

# --- HTML & GIST BUILDER ---
def build_fx_html_page(df):
    ids = sorted(df["ID"].unique().tolist())
    filter_buttons = "\n    ".join([f'<button onclick="filterID(\'{i}\')" data-id="{i}">{i}</button>' for i in ids])
    rows_html = ""
    for _, r in df.iterrows():
        rows_html += f'<tr data-id="{r["ID"]}" data-date="{r["Date"]}"><td>{r["Date"]}</td><td class="id-cell">{r["ID"]}</td><td>{r["Metric"]}</td><td class="pos">{r["CallPct"]}</td><td class="neg">{r["PutPct"]}</td><td>{format_vol(r["TotalVol"])}</td></tr>\n'
    
    dates = sorted(df["Date"].unique().tolist(), reverse=True)
    date_options = "\n".join([f'<option value="{d}">{d}</option>' for d in dates])

    html_start = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1, user-scalable=no">
<title>FX Options Put/Call History</title>
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
  .table-wrap {{ width: 100%; }}
  table {{ border-collapse: collapse; font-size: 0.72rem; white-space: nowrap; width: 100%; table-layout: fixed; }}
  th, td {{ border: 1px solid #2a2a2a; padding: 5px 3px; text-align: right; overflow: hidden; position: relative; }}
  th {{ text-align: left; background: #161616; color: #00aaff; position: sticky; top: 0; z-index: 1; user-select: none; touch-action: manipulation; }}
  th:nth-child(1), td:nth-child(1) {{ width: 22%; }}
  th:nth-child(2), td:nth-child(2) {{ width: 12%; }}
  th:nth-child(3), td:nth-child(3) {{ width: 20%; }}
  th:nth-child(4), td:nth-child(4) {{ width: 15%; }}
  th:nth-child(5), td:nth-child(5) {{ width: 15%; }}
  th:nth-child(6), td:nth-child(6) {{ width: 16%; }}
  th .arrow {{ font-size: 0.6rem; color: #444; }}
  th.sorted .arrow {{ color: #00aaff; }}
  th .sort-rank {{ position: absolute; top: 1px; right: 1px; font-size: 0.55rem; color: #ff5252; font-weight: bold; }}
  td.id-cell {{ color: #ffd700; font-weight: bold; text-align: center; }}
  td.pos {{ color: #00e676; }}
  td.neg {{ color: #ff5252; }}
</style>
</head>
<body>
<h2>FX Options Put/Call History</h2>
<div class="controls">
  <label>CCY:</label>
  <button onclick="filterID('ALL')" data-id="ALL" class="active">ALL</button>
  {filter_buttons}
  <label style="margin-left:4px">Date:</label>
  <select id="dateSelect" onchange="applyFilters()">
    <option value="">All dates</option>
    {date_options}
  </select>
</div>
<div class="count" id="rowCount">Loading...</div>
<div class="table-wrap">
<table id="tbl">
  <thead>
    <tr>
      <th onclick="handleMultiSort(0)">Date <span class="arrow">▼</span></th>
      <th onclick="handleMultiSort(1)">ID <span class="arrow">▼</span></th>
      <th onclick="handleMultiSort(2)">Metric <span class="arrow">▼</span></th>
      <th onclick="handleMultiSort(3)">Call% <span class="arrow">▼</span></th>
      <th onclick="handleMultiSort(4)">Put% <span class="arrow">▼</span></th>
      <th onclick="handleMultiSort(5)">Total <span class="arrow">▼</span></th>
    </tr>
  </thead>
  <tbody id="tbody">
{rows_html}
  </tbody>
</table>
</div>
"""
    html_end = r"""
<script>
let activeID = 'ALL', sortStack = [];
function filterID(id) {
    activeID = id;
    document.querySelectorAll('button[data-id]').forEach(b => b.classList.toggle('active', b.dataset.id === id));
    applyFilters();
}
function applyFilters() {
    const dateQ = document.getElementById('dateSelect').value;
    const rows = document.querySelectorAll('#tbody tr');
    let visible = 0;
    rows.forEach(row => {
        let show = (activeID === 'ALL' || row.dataset.id === activeID) && (!dateQ || row.dataset.date === dateQ);
        row.style.display = show ? '' : 'none';
        if (show) visible++;
    });
    document.getElementById('rowCount').textContent = 'Showing ' + visible + ' rows';
}
function handleMultiSort(col) {
    let idx = sortStack.findIndex(s => s.col === col);
    if (idx !== -1) {
        if (!sortStack[idx].asc) sortStack[idx].asc = true;
        else sortStack.splice(idx, 1);
    } else {
        sortStack.push({col: col, asc: false});
    }
    renderSortUI(); executeSort();
}
function renderSortUI() {
    const ths = document.querySelectorAll('th');
    ths.forEach((th, i) => {
        const rank = sortStack.findIndex(s => s.col === i);
        const oldRank = th.querySelector('.sort-rank');
        if (oldRank) oldRank.remove();
        if (rank !== -1) {
            th.classList.add('sorted'); 
            th.querySelector('.arrow').innerHTML = sortStack[rank].asc ? '▲' : '▼';
            const span = document.createElement('span'); 
            span.className = 'sort-rank'; span.innerHTML = (rank + 1); th.appendChild(span);
        } else { 
            th.classList.remove('sorted'); th.querySelector('.arrow').innerHTML = '▼'; 
        }
    });
}
function executeSort() {
    const tbody = document.getElementById('tbody');
    const rows = Array.from(tbody.querySelectorAll('tr'));
    rows.sort((a, b) => {
        for (let s of sortStack) {
            let av = a.cells[s.col].textContent.trim(), bv = b.cells[s.col].textContent.trim();
            const parse = (str) => { 
                if (/^\d{4}-\d{2}-\d{2}$/.test(str)) return Date.parse(str);
                let n = parseFloat(str.replace(/[\$%BM,]/g, '')); 
                if (str.includes('B')) n *= 1000000000;
                else if (str.includes('M')) n *= 1000000;
                return n;
            };
            };
            const an = parse(av), bn = parse(bv);
            let res = (!isNaN(an) && !isNaN(bn)) ? an - bn : av.localeCompare(bv);
            if (res !== 0) return s.asc ? res : -res;
        }
        return 0;
    }).forEach(r => tbody.appendChild(r));
}
window.onload = applyFilters;
</script>
</body>
</html>
"""
    return html_start + html_end

def archive_and_publish_fx(trade_date, data):
    file_exists = os.path.isfile(CSV_FILE)
    already_exists = False
    if file_exists:
        with open(CSV_FILE, 'r') as f:
            lines = f.readlines()
            if lines and lines[-1].split(',')[0] == trade_date: already_exists = True
    
    if not already_exists:
        with open(CSV_FILE, 'a', newline='') as f:
            writer = csv.writer(f)
            if not file_exists: writer.writerow(['Date', 'ID', 'Metric', 'CallPct', 'PutPct', 'TotalVol'])
            for c in CURRENCIES:
                entry = data[c['code']]
                for label, key in [('NOTIONAL', 'nv'), ('OPEN INT.', 'oi'), ('≤ 1W', 'e1'), ('> 1W', 'e8')]:
                    c_v, p_v = entry.get(f'{key}_c', 0), entry.get(f'{key}_p', 0)
                    total = c_v + p_v
                    cp = int(round((c_v/total)*100)) if total > 0 else 0
                    writer.writerow([trade_date, c['code'], label, f"{cp}%", f"{100-cp}%", total])

    df = pd.read_csv(CSV_FILE).sort_values(by=['Date', 'ID'], ascending=[False, True])
    html = build_fx_html_page(df)
    Path("fx_options.html").write_text(html, encoding="utf-8")
    
    if GITHUB_TOKEN:
        headers = {"Authorization": f"token {GITHUB_TOKEN}", "Accept": "application/vnd.github+json"}
        payload = {"description": "FX Options History", "public": True, "files": {"fx_options.html": {"content": html}}}
        gid = Path(GIST_ID_FILE).read_text().strip() if os.path.isfile(GIST_ID_FILE) else ""
        try:
            if gid:
                resp = requests.patch(f"https://api.github.com/gists/{gid}", headers=headers, json=payload)
                if resp.status_code == 200: return "https://htmlpreview.github.io/?" + resp.json()["files"]["fx_options.html"]["raw_url"]
            resp = requests.post("https://api.github.com/gists", headers=headers, json=payload)
            if resp.status_code == 201:
                Path(GIST_ID_FILE).write_text(resp.json()["id"])
                return "https://htmlpreview.github.io/?" + resp.json()["files"]["fx_options.html"]["raw_url"]
        except: pass
    return None

if __name__ == "__main__":
    try:
        print("🚀 Fetching FX Reports...")
        report_pdf = get_pdf(URL_REPORT)
        t_date, results = parse_fx_report(report_pdf)
        
        print("🔍 Solving Expiry Reconciliation...")
        expiry_pdf = get_pdf(URL_PUT_CALL)
        final_results = parse_expiry_breakdown(expiry_pdf, results)
        
        if t_date:
            print(f"📊 Archiving data for {t_date}...")
            link = archive_and_publish_fx(t_date, final_results)
            
            output = [f"📊 <b>FX Options — {t_date}</b>", "<code>🌎|METRIC   |CALL / PUT   | VOL  </code>"]
            for c in CURRENCIES:
                entry = final_results[c['code']]
                for label, key in [('NOTIONAL', 'nv'), ('OPEN INT.', 'oi'), ('≤ 1W', 'e1'), ('> 1W', 'e8')]:
                    c_v, p_v = entry.get(f'{key}_c', 0), entry.get(f'{key}_p', 0)
                    total = c_v + p_v
                    cp = int(round((c_v/total)*100)) if total > 0 else 0
                    output.append(f"<code>{c['flag']}|{label:<9}|🟢{cp:>3}% 🔴{100-cp:>3}%|{format_vol(total):>6}</code>")
            
            if link: output.append(f"\n<a href='{link}'>🔍 Interactive History</a>")
            
            requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", json={"chat_id": CHAT_ID, "text": "\n".join(output), "parse_mode": "HTML", "disable_web_page_preview": True})
            print("✅ Done.")
        else:
            print("❌ Failure: Trade Date missing.")
            sys.exit(1)
    except Exception as e:
        print(f"💥 Fatal Error: {e}")
        sys.exit(1)
