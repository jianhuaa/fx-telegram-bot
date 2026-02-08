import cloudscraper
import pdfplumber
import io
import re
import sys
import time
from datetime import datetime
from itertools import combinations

# ===== CONFIGURATION =====
TELEGRAM_TOKEN = "7649050168:AAHNIYnrHzLOTcjNuMpeKgyUbfJB9x9an3c"
CHAT_ID = "876384974"

# Logic-based Currency Configuration - AUD terms expanded for safety
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

def clean_numeric(val):
    """Clean numeric values from PDF strings."""
    if val is None: return 0.0
    s = str(val).strip()
    if s in ['', '-', '--', 'None', '$ -', '$0']: return 0.0
    cleaned = re.sub(r'[^\d.]', '', s)
    try:
        return float(cleaned) if cleaned else 0.0
    except ValueError:
        return 0.0

def format_vol(val):
    """Format volume: Whole Millions, 1dp Billions."""
    val_m = val / 1_000_000
    if val_m >= 1000:
        return f"${val_m/1000:.1f}B"
    return f"${int(round(val_m))}M"

def get_pdf(url):
    """Fetch PDF with cloudscraper."""
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

def parse_fx_report(pdf_stream):
    """Get Notional and OI from report.pdf."""
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
                    trade_date = datetime.strptime(raw_date, fmt).strftime('%b %d %Y')
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
    """
    Sub-Sum Solver with Positional Affinity:
    Finds the combination that matches the budget AND respects column hints.
    """
    n = len(puzzle_rows)
    best_combo = []
    best_diff = float('inf')
    best_affinity_score = -1

    for r in range(n + 1):
        for combo in combinations(range(n), r):
            current_sum = sum(puzzle_rows[i]['raw_val'] for i in combo)
            diff = abs(current_sum - target_gap)
            
            # Affinity Score: How many rows in this combo "prefer" being a Call based on PDF position
            affinity = sum(1 for i in combo if puzzle_rows[i]['hint'] == 'C')
            # Penalize rows that were physically in the Put column but we are trying to call them Calls
            affinity -= sum(1 for i in combo if puzzle_rows[i]['hint'] == 'P')

            if diff <= 1.0:
                # If we have multiple perfect ties, take the one with better positional affinity
                if affinity > best_affinity_score:
                    best_affinity_score = affinity
                    best_combo = list(combo)
                # If perfect match found, we prioritize higher affinity immediately
                if best_affinity_score >= 0:
                    return best_combo
            
            if diff < best_diff:
                best_diff = diff
                best_combo = list(combo)
                best_affinity_score = affinity
    
    return best_combo

def parse_expiry_breakdown(pdf_stream, results):
    """
    Auditor-level parser using combinatorial reconciliation + Positional Affinity.
    Explicit logging of EVERY row (Certain + Puzzle) for full assurance.
    """
    print("--- 📑 FULL AUDIT LOG: ALL CURRENCIES RECONCILIATION ---")
    with pdfplumber.open(pdf_stream) as pdf:
        current_currency = None
        all_anchors = {c['code']: {'call': 0, 'put': 0} for c in CURRENCIES}
        currency_rows = {c['code']: [] for c in CURRENCIES}

        # --- STEP 1: SCAN PDF FOR ANCHORS AND ROWS ---
        for page in pdf.pages:
            text = (page.extract_text() or "").upper()
            lines = text.split('\n')
            
            # Identify current currency context and capture anchor totals
            for line in lines:
                for c in CURRENCIES:
                    if any(term.upper() in line for term in c['search_pc']):
                        current_currency = c['code']
                        # Look for large monetary pairs in the section header line
                        nums = [clean_numeric(s) for s in line.split() if clean_numeric(s) > 1000]
                        if len(nums) >= 2:
                            # Re-anchoring only if values are found
                            all_anchors[current_currency]['call'] = nums[0]
                            all_anchors[current_currency]['put'] = nums[1]
                        break

            tables = page.extract_tables()
            for table in tables:
                if not current_currency: continue
                for row in table:
                    clean_row = [str(r).strip() if r is not None else "" for r in row]
                    # Identify DTE
                    dte_found = next((int(clean_row[i]) for i in [1, 2] if i < len(clean_row) and clean_row[i].isdigit()), None)
                    if dte_found is None: continue
                    
                    # Indices verification
                    c_idx, p_idx, t_idx = 3, 4, 5
                    if not clean_row[1].isdigit() and clean_row[2].isdigit():
                        c_idx, p_idx, t_idx = 4, 5, 6 

                    c_val_raw = clean_row[c_idx] if c_idx < len(clean_row) else ""
                    p_val_raw = clean_row[p_idx] if p_idx < len(clean_row) else ""
                    
                    c_num = clean_numeric(c_val_raw)
                    p_num = clean_numeric(p_val_raw)
                    
                    # 1. CERTAIN ROW (Call + Put columns occupied in PDF)
                    if c_val_raw and p_val_raw:
                        currency_rows[current_currency].append({'dte': dte_found, 'c': c_num, 'p': p_num, 'type': 'certain'})
                    
                    # 2. PUZZLE ROW (One column empty, needs solving)
                    else:
                        vals = [clean_numeric(v) for v in clean_row[c_idx:t_idx] if clean_numeric(v) > 0 or v == '0']
                        if not vals: continue
                        raw_val = vals[0]
                        hint = 'C' if clean_numeric(c_val_raw) == raw_val and c_val_raw != "" else 'P'
                        currency_rows[current_currency].append({
                            'dte': dte_found, 'raw_val': raw_val, 'hint': hint,
                            'c': 0, 'p': 0, 'type': 'puzzle'
                        })

        # --- STEP 2: SOLVE RECONCILIATION FOR EVERY CURRENCY ---
        for code in [c['code'] for c in CURRENCIES]:
            rows = currency_rows[code]
            anchors = all_anchors[code]
            
            if not rows or anchors['call'] == 0:
                continue

            # Tally certain rows
            known_c = sum(r['c'] for r in rows if r['type'] == 'certain')
            gap_c = anchors['call'] - known_c
            
            puzzles = [r for r in rows if r['type'] == 'puzzle']
            
            print(f"🧩 Solving {code}: Budget Call ${anchors['call']:,.0f} | Gap ${gap_c:,.0f} | Puzzles: {len(puzzles)}")

            # Solve the puzzles
            if puzzles:
                winning_indices = find_best_combination(puzzles, gap_c)
                for idx, r in enumerate(puzzles):
                    if idx in winning_indices:
                        r['c'], r['p'] = r['raw_val'], 0.0
                    else:
                        r['c'], r['p'] = 0.0, r['raw_val']

            # FULL TRANSPARENCY LOG: Print every row processed
            for r in rows:
                if r['type'] == 'certain':
                    print(f"   [CERTAIN] DTE {r['dte']:2} -> Call: ${r['c']:,.0f} | Put: ${r['p']:,.0f}")
                else:
                    target_slot = "CALL" if r['c'] > 0 else "PUT"
                    slot_label = "[MATCH]" if r['c'] > 0 else "[RESDU]"
                    print(f"   {slot_label} DTE {r['dte']:2} -> Slotted ${r['raw_val']:,.0f} into {target_slot}")
            
            # --- NEW: BUCKET SUMMARY LOGS FOR VERIFICATION ---
            for g_key, g_name in [('e1', '≤1W'), ('e8', '>1W')]:
                c_sum = sum(r['c'] for r in rows if ('e1' if r['dte'] <= 7 else 'e8') == g_key)
                p_sum = sum(r['p'] for r in rows if ('e1' if r['dte'] <= 7 else 'e8') == g_key)
                total = c_sum + p_sum
                if total > 0:
                    pct = (c_sum / total) * 100
                    print(f"   📈 BUCKET {g_name} TOTALS: Call ${c_sum:,.0f} / Total ${total:,.0f} ({pct:.2f}%)")
            
            # Transfer to results for report
            for r in rows:
                group = 'e1' if r['dte'] <= 7 else 'e8'
                results[code][f'{group}_c'] += r['c']
                results[code][f'{group}_p'] += r['p']

    print("\n--- END OF AUDIT LOG ---\n")
    return results

def format_telegram_update(trade_date, data):
    output = [f"📊 <b>FX Options — {trade_date}</b>", "<code>🌎|METRIC   |CALL / PUT   | VOL  </code>"]
    for c in CURRENCIES:
        entry = data[c['code']]
        for label, key in [('NOTIONAL', 'nv'), ('OPEN INT.', 'oi'), ('≤1W', 'e1'), ('>1W', 'e8')]:
            c_v, p_v = entry.get(f'{key}_c', 0), entry.get(f'{key}_p', 0)
            total = c_v + p_v
            cp = int(round((c_v/total)*100)) if total > 0 else 0
            row = f"<code>{c['flag']}|{label:<9}|🟢{cp:>3}% 🔴{100-cp:>3}%|{format_vol(total):>6}</code>"
            output.append(row)
    return "\n".join(output)

def send_telegram_message(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    import requests as r_lib
    r_lib.post(url, json={"chat_id": CHAT_ID, "text": message, "parse_mode": "HTML"}, timeout=25).raise_for_status()
    print("✅ Live Report sent successfully.")

if __name__ == "__main__":
    try:
        print("🚀 Fetching Reports...")
        report_pdf = get_pdf(URL_REPORT)
        t_date, results = parse_fx_report(report_pdf)
        
        expiry_pdf = get_pdf(URL_PUT_CALL)
        final_results = parse_expiry_breakdown(expiry_pdf, results)
        
        if t_date:
            send_telegram_message(format_telegram_update(t_date, final_results))
        else:
            print("❌ Failure: Trade Date missing.")
            sys.exit(1)
    except Exception as e:
        print(f"💥 Fatal Error: {e}")
        sys.exit(1)
