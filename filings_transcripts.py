import pandas as pd
import requests
from datetime import datetime
import time
import os
import io
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from DrissionPage import ChromiumPage, ChromiumOptions
import warnings

warnings.filterwarnings('ignore')

EMAIL_SEC = "chanjurong@gmail.com"
FETCH_WORKERS_SEC = 5
MAX_TICKERS = int(os.environ.get('MAX_TICKERS', 9999))
STALE_DAYS_THRESHOLD = 75

TICKER_ALIASES = {'BRKB': 'BRK-B', 'LENB': 'LEN-B', 'GEFB': 'GEF-B', 'UHALB': 'UHAL-B', 'BFB': 'BF-B', 'BFA': 'BF-A'}
FALLBACK_MB_URLS = {
    'SNL': 'https://www.marketbeat.com/stocks/NYSE/SNL/earnings/',
    'PG': 'https://www.marketbeat.com/stocks/NYSE/PG/earnings/',
    'CCL': 'https://www.marketbeat.com/stocks/NYSE/CCL/earnings/',
    'NFLX': 'https://www.marketbeat.com/stocks/NASDAQ/NFLX/earnings/'
}

SEC_MAP = {
    "Communication Services": "XLC", "Consumer Cyclical": "XLY", "Consumer Defensive": "XLP",
    "Energy": "XLE", "Financial Services": "XLF", "Healthcare": "XLV",
    "Industrials": "XLI", "Technology": "XLK", "Materials": "XLB",
    "Real Estate": "XLRE", "Utilities": "XLU", "Financials": "XLF", "Health Care": "XLV",
    "Information Technology": "XLK", "Consumer Discretionary": "XLY", "Consumer Staples": "XLP"
}

# --- 1. BUILD UNIVERSE FROM GOOGLE SHEETS ---
print("Fetching Universe from Google Sheets...")
headers = {'User-Agent': 'Mozilla/5.0'}
def fetch_sheet(url, skip_str):
    res = requests.get(url, headers=headers)
    lines = res.text.splitlines()
    h_idx = next((i for i, l in enumerate(lines) if skip_str in l), 0)
    return pd.read_csv(io.StringIO("\n".join(lines[h_idx:])))

spx_url = "https://docs.google.com/spreadsheets/d/e/2PACX-1vSpFLwMNa0AUsSC62LQZCQfIvvXRPPmX00cY7DO2sbiHu47Z72aJ_R-F_IrILBbKqIZGdSFgXFUrZyJ/pub?gid=0&single=true&output=csv"
rmc_url = "https://docs.google.com/spreadsheets/d/e/2PACX-1vSpFLwMNa0AUsSC62LQZCQfIvvXRPPmX00cY7DO2sbiHu47Z72aJ_R-F_IrILBbKqIZGdSFgXFUrZyJ/pub?gid=679638722&single=true&output=csv"
rut_url = "https://docs.google.com/spreadsheets/d/e/2PACX-1vRrTpcehWaL1Aq-uTn986nie8Hwrs_uHUOYr-E_wCG0jtLKQjvpw0V8x1wVz8yJdxFhqr7mz07jjpkM/pub?gid=0&single=true&output=csv"

df_spx = fetch_sheet(spx_url, 'Symbol')
df_rmc = fetch_sheet(rmc_url, 'Symbol')
df_rut = fetch_sheet(rut_url, 'Symbol')

universe = []
def add_to_uni(df, idx_name):
    for _, row in df.iterrows():
        try:
            t = str(row['Symbol']).strip().replace('.', '-')
            if t != 'nan' and t:
                sec, ind = str(row.iloc[2]).strip(), str(row.iloc[3]).strip()
                universe.append({'Ticker': t, 'Index': idx_name, 'Sector': sec, 'Industry': ind})
        except: pass

add_to_uni(df_spx, 'SPX')
add_to_uni(df_rmc, 'RMC')
add_to_uni(df_rut, 'RTY')

df_universe = pd.DataFrame(universe).drop_duplicates(subset=['Ticker'])
all_tickers = df_universe['Ticker'].tolist()[:MAX_TICKERS]
df_universe = df_universe[df_universe['Ticker'].isin(all_tickers)]
print(f"Loaded {len(all_tickers)} tickers from sheets.")

# --- 2. SMART INCREMENTAL LOGIC ---
print("Checking local databases for stale tickers...")
now = datetime.now()

try:
    df_sec_old = pd.read_parquet('col4_sec.parquet')
    df_sec_old['Date_Parsed'] = pd.to_datetime(df_sec_old['Date'] + f" {now.year}", format="%d %b %Y", errors='coerce')
    last_sec_dates = df_sec_old.groupby('Ticker')['Date_Parsed'].max().to_dict()
except:
    df_sec_old = pd.DataFrame(columns=['Date', 'Ticker', 'Index', 'Sector', 'Industry', 'Type', 'Link'])
    last_sec_dates = {}

try:
    df_trans_old = pd.read_parquet('col4_transcripts.parquet')
    df_trans_old['Date_Parsed'] = pd.to_datetime(df_trans_old['Date'] + f" {now.year}", format="%d %b %Y", errors='coerce')
    last_trans_dates = df_trans_old.groupby('Ticker')['Date_Parsed'].max().to_dict()
except:
    df_trans_old = pd.DataFrame(columns=['Date', 'Ticker', 'Index', 'Sector', 'Industry', 'Link'])
    last_trans_dates = {}

tickers_to_update_sec, tickers_to_update_trans = [], []
for t in all_tickers:
    if t not in last_sec_dates or pd.isna(last_sec_dates[t]) or (now - last_sec_dates[t]).days > STALE_DAYS_THRESHOLD:
        tickers_to_update_sec.append(t)
    if t not in last_trans_dates or pd.isna(last_trans_dates[t]) or (now - last_trans_dates[t]).days > STALE_DAYS_THRESHOLD:
        tickers_to_update_trans.append(t)

print(f"Tickers needing SEC update: {len(tickers_to_update_sec)}")
print(f"Tickers needing Transcript update: {len(tickers_to_update_trans)}")

# --- 3. FETCH SEC FILINGS ---
new_sec_data = []
if tickers_to_update_sec:
    import threading
    class TokenBucket:
        def __init__(self, rate):
            self.capacity = rate; self.tokens = rate; self.rate = rate
            self.last_fill = time.time(); self.lock = threading.Lock()
        def consume(self):
            with self.lock:
                now_t = time.time()
                self.tokens = min(self.capacity, self.tokens + (now_t - self.last_fill) * self.rate)
                self.last_fill = now_t
                if self.tokens < 1:
                    time.sleep((1 - self.tokens) / self.rate); self.tokens = 0; self.last_fill = time.time()
                else: self.tokens -= 1
    
    sec_limiter = TokenBucket(8)
    headers_sec = {'User-Agent': f'JianHua_Research ({EMAIL_SEC})', 'Accept-Encoding': 'gzip, deflate'}
    res_m = requests.get("https://www.sec.gov/files/company_tickers.json", headers=headers_sec)
    cik_map = {v['ticker']: str(v['cik_str']).zfill(10) for v in res_m.json().values()} if res_m.status_code == 200 else {}

    def fetch_sec(ticker, cik):
        if not cik: return None
        sec_limiter.consume()
        url = f"https://data.sec.gov/submissions/CIK{cik}.json"
        try:
            resp = requests.get(url, headers=headers_sec, timeout=10)
            if resp.status_code == 200:
                p = resp.json().get('filings', {}).get('recent', {})
                forms = p.get('form', [])
                for i in range(len(forms)):
                    if forms[i] in ['10-K', '10-Q', '10K', '10Q']:
                        dt_str = pd.to_datetime(p['filingDate'][i]).strftime("%d %b").lstrip('0')
                        link = f"<a href='https://www.sec.gov/Archives/edgar/data/{cik}/{p['accessionNumber'][i].replace('-', '')}/{p['primaryDocument'][i]}'>[Click!]</a>"
                        return {'Date': dt_str, 'Ticker': ticker, 'Type': forms[i], 'Link': link}
        except: pass
        return None

    with ThreadPoolExecutor(max_workers=FETCH_WORKERS_SEC) as ex:
        futures = {ex.submit(fetch_sec, t, cik_map.get(t)): t for t in tickers_to_update_sec}
        for f in as_completed(futures):
            res = f.result()
            if res:
                row_info = df_universe[df_universe['Ticker'] == res['Ticker']].iloc[0]
                res['Index'] = row_info['Index']
                res['Sector'] = SEC_MAP.get(row_info['Sector'], row_info['Sector'])
                res['Industry'] = row_info['Industry']
                new_sec_data.append(res)

    if new_sec_data:
        df_new_sec = pd.DataFrame(new_sec_data)
        if 'Date_Parsed' in df_sec_old.columns: df_sec_old = df_sec_old.drop(columns=['Date_Parsed'])
        df_sec_final = pd.concat([df_sec_old, df_new_sec]).drop_duplicates(subset=['Ticker', 'Type', 'Date'], keep='last')
        df_sec_final = df_sec_final.sort_values(by=['Sector', 'Industry', 'Index'], ascending=[True, True, False])
        df_sec_final.to_parquet('col4_sec.parquet')
        print(f"Saved {len(df_new_sec)} new SEC records.")
    else: print("No new SEC records found.")
elif not df_sec_old.empty:
    if 'Date_Parsed' in df_sec_old.columns: df_sec_old = df_sec_old.drop(columns=['Date_Parsed'])
    df_sec_old.to_parquet('col4_sec.parquet')

# --- 4. FETCH TRANSCRIPTS ---
new_trans_data = []
if tickers_to_update_trans:
    os.system("pkill -f chrome")
    time.sleep(1)
    co = ChromiumOptions()
    co.set_browser_path('/usr/bin/google-chrome-stable')
    co.set_local_port(9333)
    co.set_argument('--headless=new')
    co.set_argument('--no-sandbox')
    co.set_argument('--disable-dev-shm-usage')
    co.set_user_agent('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')
    page = ChromiumPage(addr_or_opts=co)

    try:
        for ticker in tickers_to_update_trans:
            search_ticker = TICKER_ALIASES.get(ticker, ticker).replace('.', '-')
            if ticker in FALLBACK_MB_URLS: target_url = FALLBACK_MB_URLS[ticker]
            else: target_url = f"https://www.marketbeat.com/stocks/{search_ticker[0]}/{search_ticker}/earnings/"

            try:
                page.get(target_url, timeout=2.0, retry=0)
                t_ele = page.ele('text:Conference Call Transcript & Audio', timeout=0.5)
                if t_ele and t_ele.link:
                    match_date = now.strftime("%d %b").lstrip('0')
                    row_info = df_universe[df_universe['Ticker'] == ticker].iloc[0]
                    clean_mb_link = f"<a href='{t_ele.link}'>[Link]</a>"
                    new_trans_data.append({
                        'Date': match_date, 'Ticker': ticker, 
                        'Index': row_info['Index'], 'Sector': SEC_MAP.get(row_info['Sector'], row_info['Sector']), 
                        'Industry': row_info['Industry'], 'Link': clean_mb_link
                    })
                    print(f"Found transcript for {ticker}")
            except: pass
    finally:
        page.quit()

    if new_trans_data:
        df_new_trans = pd.DataFrame(new_trans_data)
        if 'Date_Parsed' in df_trans_old.columns: df_trans_old = df_trans_old.drop(columns=['Date_Parsed'])
        df_trans_final = pd.concat([df_trans_old, df_new_trans]).drop_duplicates(subset=['Ticker', 'Link'], keep='last')
        df_trans_final = df_trans_final.sort_values(by=['Sector', 'Industry', 'Index'], ascending=[True, True, False])
        df_trans_final.to_parquet('col4_transcripts.parquet')
        print(f"Saved {len(df_new_trans)} new Transcript records.")
    else: print("No new Transcript records found.")
elif not df_trans_old.empty:
    if 'Date_Parsed' in df_trans_old.columns: df_trans_old = df_trans_old.drop(columns=['Date_Parsed'])
    df_trans_old.to_parquet('col4_transcripts.parquet')

print("Update complete.")
