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
PDF_URL        = "https://www.cmegroup.com/daily_bulletin/current/Section12_Equity_And_Index_Futures_Continued.pdf"
TELEGRAM_TOKEN = "8577879935:AAEpSjAz4wdcZ9Lb7AJpURRk8haADlPCbHo"
CHAT_ID        = "876384974"
CSV_FILE       = "spdr_sectors_history.csv"
GITHUB_TOKEN   = os.environ.get("GIST_TOKEN", "")
GIST_ID_FILE   = "gist_id.txt"

TARGET_SECTORS = {
    "E-MINI COM SERVICES SELECT SECTOR":   "COMM",
    "SP 500 CONS DISCRETIONARY SECTOR IX": "DISC",
    "SP 500 ENERGY SECTOR INDEX":          "ENER",
    "SP 500 FINANCIAL SECTOR INDEX":       "FINA",
    "SP 500 HEALTH CARE SECTOR INDEX":     "HLTH",
    "SP 500 INDUSTRIAL SECTOR INDEX":      "INDU",
    "SP 500 MATERIALS SECTOR INDEX":       "MATL",
    "REAL ESTATE SELECT SECTOR FUTURES":   "REIT",
    "SP 500 CONSUMER STAPLES SECTOR IX":   "STAP",
    "SP 500 TECHNOLOGY SECTOR INDEX":      "TECH",
    "SP 500 UTILITIES SECTOR INDEX":       "UTIL",
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

def process_futures_block(product_name, line):
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
        trailing_data = tokens[chg_idx+1:]
        nums = [t for t in trailing_data if '.' not in t]
        if len(nums) >= 3:
            vol = sum(int(to_float(n)) for n in nums[:-2])
            oi = int(to_float(nums[-2]))
            delta = int(to_float(nums[-1]))
        elif len(nums) == 2:
            vol = 0
            oi = int(to_float(nums[-2]))
            delta = int(to_float(nums[-1]))
        else:
            vol = oi = delta = 0
        return {"Product": product_name, "Month": month, "Sett": sett, "Change": chg, "Volume": vol, "OI": oi, "Delta": delta}
    except Exception:
        return None

# --- HTML PAGE BUILDER ---
def build_html_page(df):
    ids = sorted(df["ID"].unique().tolist())
    filter_buttons = "\n    ".join(
        f'<button onclick="filterID(\'{i}\')" data-id="{i}">{i}</button>'
        for i in ids
    )
    rows_html = ""
    for _, r in df.iterrows():
        pct_val = str(r["Pct"])
        try:
            pct_num   = float(pct_val.replace("%", ""))
            pct_class = "pos" if pct_num > 0 else ("neg" if pct_num < 0 else "")
        except:
            pct_class = ""
        rows_html += (
            f'<tr data-id="{r["ID"]}" data-date="{r["Date"]}">'
            f'<td>{r["Date"]}</td>'
            f'<td class="id-cell">{r["ID"]}</td>'
            f'<td>{r["Sett"]}</td>'
            f'<td class="{pct_class}">{r["Pct"]}</td>'
            f'<td>{format_num(float(str(r["Vol"]).replace(",", "")))}</td>'
            f'<td>{format_num(float(str(r["OI"]).replace(",", "")))}</td>'
            f'<td>{format_num(float(str(r["Delta"]).replace(",", "")))}</td>'
            f'</tr>\n'
        )
    dates        = sorted(df["Date"].unique().tolist(), reverse=True)
    date_options = "\n".join(f'<option value="{d}">{d}</option>' for d in dates)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>S&P 500 Sector Futures History</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: 'Courier New', monospace; background: #0d0d0d; color: #e0e0e0; padding: 12px; }}
  h2 {{ color: #00aaff; margin-bottom: 12px; font-size: 1.1rem; letter-spacing: 1px; }}
  .controls {{ display: flex; flex-wrap: wrap; gap: 8px; align-items: center; margin-bottom: 10px; }}
  .controls label {{ color: #888; font-size: 0.85rem; margin-right: -4px; }}
  button {{ padding: 6px 13px; cursor: pointer; background: #1a1a1a; color: #ccc; border: 1px solid #444; border-radius: 4px; font-size: 0.85rem; font-family: inherit; transition: background 0.15s, color 0.15s; }}
  button:hover {{ background: #2a2a2a; }}
  button.active {{ background: #00aaff; color: #000; border-color: #00aaff; font-weight: bold; }}
  select {{ padding: 6px 8px; background: #1a1a1a; color: #ccc; border: 1px solid #444; border-radius: 4px; font-size: 0.85rem; font-family: inherit; }}
  .table-wrap {{ width: 100%; }}
  table {{ border-collapse: collapse; font-size: 0.72rem; white-space: nowrap; width: 100%; table-layout: fixed; }}
  th, td {{ border: 1px solid #2a2a2a; padding: 5px 3px; text-align: right; overflow: hidden; }}
  th {{ text-align: left; }}
  th:nth-child(1), td:nth-child(1) {{ width: 22%; }}
  th:nth-child(2), td:nth-child(2) {{ width: 10%; }}
  th:nth-child(3), td:nth-child(3) {{ width: 14%; }}
  th:nth-child(4), td:nth-child(4) {{ width: 14%; }}
  th:nth-child(5), td:nth-child(5) {{ width: 13%; }}
  th:nth-child(6), td:nth-child(6) {{ width: 13%; }}
  th:nth-child(7), td:nth-child(7) {{ width: 14%; }}
  th {{ background: #161616; color: #00aaff; cursor: pointer; user-select: none; position: sticky; top: 0; z-index: 1; }}
  th:hover {{ background: #1e1e1e; }}
  th .arrow {{ font-size: 0.65rem; margin-left: 4px; color: #555; }}
  th.sorted .arrow {{ color: #00aaff; }}
  tr:hover td {{ background: #151515; }}
  td.id-cell {{ color: #ffd700; font-weight: bold; text-align: center; }}
  td.pos {{ color: #00e676; }}
  td.neg {{ color: #ff5252; }}
  .count {{ font-size: 0.8rem; color: #555; margin-bottom: 8px; }}
</style>
</head>
<body>
<h2>S&P 500 Sector Futures History</h2>
<div class="controls">
  <label>Sector:</label>
  <button onclick="filterID('ALL')" data-id="ALL" class="active">ALL</button>
  {filter_buttons}
  <label style="margin-left:4px">Date:</label>
  <select id="dateSelect" onchange="applyFilters()">
    <option value="">All dates</option>
    {date_options}
  </select>
</div>
<div class="count" id="rowCount"></div>
<div class="table-wrap">
<table id="tbl">
  <thead>
    <tr>
      <th onclick="sortTable(0)">Date <span class="arrow">&#9660;</span></th>
      <th onclick="sortTable(1)">ID <span class="arrow">&#9660;</span></th>
      <th onclick="sortTable(2)">Sett <span class="arrow">&#9660;</span></th>
      <th onclick="sortTable(3)">%Chg <span class="arrow">&#9660;</span></th>
      <th onclick="sortTable(4)">Vol <span class="arrow">&#9660;</span></th>
      <th onclick="sortTable(5)">OI <span class="arrow">&#9660;</span></th>
      <th onclick="sortTable(6)">&#916;OI <span class="arrow">&#9660;</span></th>
    </tr>
  </thead>
  <tbody id="tbody">
{rows_html}  </tbody>
</table>
</div>
<script>
let activeID = 'ALL', sortCol = 0, sortAsc = false;
function filterID(id) {{
  activeID = id;
  document.querySelectorAll('button[data-id]').forEach(b => b.classList.toggle('active', b.dataset.id === id));
  applyFilters();
}}
function applyFilters() {{
  const dateQ = document.getElementById('dateSelect').value;
  let visible = 0;
  document.querySelectorAll('#tbody tr').forEach(row => {{
    const show = (activeID === 'ALL' || row.dataset.id === activeID)
              && (!dateQ || row.dataset.date === dateQ);
    row.style.display = show ? '' : 'none';
    if (show) visible++;
  }});
  document.getElementById('rowCount').textContent = 'Showing ' + visible + ' rows';
}}
function sortTable(col) {{
  if (sortCol === col) sortAsc = !sortAsc; else {{ sortCol = col; sortAsc = true; }}
  document.querySelectorAll('th').forEach((th, i) => {{
    th.classList.toggle('sorted', i === col);
    const a = th.querySelector('.arrow');
    if (a) a.innerHTML = (i === col) ? (sortAsc ? '&#9650;' : '&#9660;') : '&#9660;';
  }});
  const tbody = document.getElementById('tbody');
  Array.from(tbody.querySelectorAll('tr')).sort((a, b) => {{
    let av = a.cells[col].textContent.trim(), bv = b.cells[col].textContent.trim();
    const an = parseFloat(av.replace(/[%k,]/g,'')) * (av.includes('k') ? 1000 : 1);
    const bn = parseFloat(bv.replace(/[%k,]/g,'')) * (bv.includes('k') ? 1000 : 1);
    if (!isNaN(an) && !isNaN(bn)) return sortAsc ? an-bn : bn-an;
    return sortAsc ? av.localeCompare(bv) : bv.localeCompare(av);
  }}).forEach(r => tbody.appendChild(r));
}}
window.onload = () => applyFilters();
</script>
</body>
</html>"""

# --- GIST HELPERS ---
def load_gist_id():
    if os.path.isfile(GIST_ID_FILE):
        return Path(GIST_ID_FILE).read_text().strip()
    return ""

def save_gist_id(gid):
    Path(GIST_ID_FILE).write_text(gid)

def push_to_gist(html_content):
    if not GITHUB_TOKEN:
        print(">>> No GIST_TOKEN found — skipping Gist upload.")
        return None
    headers = {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json",
    }
    payload = {
        "description": "S&P 500 Sector Futures - Filterable History",
        "public": True,
        "files": {"sectors.html": {"content": html_content}},
    }
    gist_id = load_gist_id()
    try:
        if gist_id:
            resp = requests.patch(
                f"https://api.github.com/gists/{gist_id}",
                headers=headers, json=payload, timeout=15,
            )
            if resp.status_code == 200:
                raw_url = "https://htmlpreview.github.io/?" + resp.json()["files"]["sectors.html"]["raw_url"]
                print(f">>> Gist updated: {raw_url}")
                return raw_url
            print(f">>> Gist update failed ({resp.status_code}) — creating new.")

        resp = requests.post(
            "https://api.github.com/gists",
            headers=headers, json=payload, timeout=15,
        )
        if resp.status_code == 201:
            data = resp.json()
            save_gist_id(data["id"])
            raw_url = "https://htmlpreview.github.io/?" + data["files"]["sectors.html"]["raw_url"]
            print(f">>> Gist created: {raw_url}")
            return raw_url
        print(f">>> Gist create failed ({resp.status_code}): {resp.text}")
        return None
    except Exception as e:
        print(f">>> Gist error: {e}")
        return None

# --- STORAGE & PUBLISH ---
def archive_and_publish(sorted_sectors, trade_date):
    try:
        clean_date = datetime.strptime(trade_date, "%b %d, %Y").strftime("%Y-%m-%d")
    except:
        clean_date = trade_date

    file_exists = os.path.isfile(CSV_FILE)
    already_exists = False

    if file_exists:
        try:
            with open(CSV_FILE, 'r') as f:
                lines = f.readlines()
                if len(lines) > 1:
                    last_line = lines[-1].strip().split(',')
                    if last_line[0] == clean_date:
                        already_exists = True
                        print(f">>> Data for {clean_date} already exists. Skipping append.")
        except Exception as e:
            print(f"Check Error: {e}")

    if not already_exists:
        with open(CSV_FILE, mode='a', newline='') as f:
            writer = csv.writer(f)
            if not file_exists:
                writer.writerow(['Date', 'ID', 'Sett', 'Pct', 'Vol', 'OI', 'Delta'])
            for s in sorted_sectors:
                writer.writerow([clean_date, s['ID'], s['Sett'], f"{s['Pct']:.2f}%", s['Vol'], s['OI'], s['Delta']])
        print(f">>> Successfully archived data for {clean_date}.")

    try:
        df = pd.read_csv(CSV_FILE)
        df = df.sort_values(by=['Date', 'ID'], ascending=[False, True])
        html_content = build_html_page(df)
        Path("sectors.html").write_text(html_content, encoding="utf-8")
        return push_to_gist(html_content)
    except Exception as e:
        print(f"HTML/Gist Error: {e}")
        return None

# --- MAIN VACUUM ---
def run_comprehensive_vacuum():
    print("=" * 80 + "\nSTARTING SECTOR VACUUM\n" + "=" * 80)

    scraper = cloudscraper.create_scraper(browser='chrome')
    resp = scraper.get(PDF_URL)
    pdf_bytes = io.BytesIO(resp.content)
    futures_results = []
    trade_date = "Unknown Date"

    with pdfplumber.open(pdf_bytes) as pdf:
        active_f = None
        last_printed_target = None
        for p_idx, page in enumerate(pdf.pages, start=1):
            text = page.extract_text() or ""
            if p_idx == 1:
                d_match = re.search(r'[A-Z][a-z]{2}, ([A-Z][a-z]{2} \d{2}, \d{4})', text)
                if d_match: trade_date = d_match.group(1)
            for line in text.split('\n'):
                clean = line.strip().upper()
                if not clean: continue
                found_target = False
                for f_key in TARGET_SECTORS.keys():
                    if f_key in clean and "TOTAL" not in clean:
                        active_f = f_key
                        found_target = True
                        if active_f != last_printed_target:
                            print(f"\n>>> Locked: {TARGET_SECTORS[f_key]}")
                            last_printed_target = active_f
                        break
                if not found_target and "TOTAL" in clean: active_f = None
                m_match = re.search(r'\b(?:JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)\d{2}\b', clean)
                if active_f and m_match and "TOTAL" not in clean:
                    res = process_futures_block(active_f, clean)
                    if res:
                        futures_results.append(res)
                        print(f"[SECTOR] {TARGET_SECTORS[active_f]} | SETT: {res['Sett']} | CHG: {res['Change']}")

    front_months = {}
    for r in futures_results:
        prod = r["Product"]
        if prod not in front_months:
            sett = r["Sett"]
            actual_chg = r["Change"] / 100.0
            prev_sett = sett - actual_chg
            pct = (actual_chg / prev_sett * 100) if prev_sett != 0 else 0.0
            front_months[prod] = {
                "ID": TARGET_SECTORS[prod], "Sett": sett, "Pct": pct,
                "Vol": r["Volume"], "OI": r["OI"], "Delta": r["Delta"]
            }

    sorted_sectors = sorted(front_months.values(), key=lambda x: x["ID"])
    iv_link = archive_and_publish(sorted_sectors, trade_date)

    tg_msg = [
        f"📊 <b>S&P 500 SECTORS - {trade_date}</b>",
        "",
        "<code>ID   | SETT |  %CHG | VOL |  OI |  ΔOI</code>",
        "<code>--------------------------------------</code>"
    ]
    for s in sorted_sectors:
        row = f"<code>{s['ID']:4} |{s['Sett']:6.0f}|{s['Pct']:+6.2f}%|{format_num(s['Vol']):>5}|{format_num(s['OI']):>5}|{format_num(s['Delta']):>5}</code>"
        tg_msg.append(row)

    if iv_link:
        tg_msg.append(f"\n<a href='{iv_link}'>🔍 View History</a>")

    requests.post(
        f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
        json={"chat_id": CHAT_ID, "text": "\n".join(tg_msg), "parse_mode": "HTML", "disable_web_page_preview": True}
    )
    print("\nDone.")

if __name__ == "__main__":
    run_comprehensive_vacuum()
