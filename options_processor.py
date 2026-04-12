import pandas as pd
import yfinance as yf
import datetime
import time
import os
import io
import requests
from dateutil.relativedelta import relativedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
from functools import wraps

# --- PRODUCTION CONFIG ---
FILE_NAME = 'col4_options_history.parquet'
MAX_WORKERS = 3  # 3 workers + 1s delay is the sweet spot for GitHub IPs

# Stealth User Agent
UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36'

def retry(exceptions, tries=3, delay=5):
    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            _tries, _delay = tries, delay
            while _tries > 1:
                try:
                    return f(*args, **kwargs)
                except exceptions as e:
                    err_msg = str(e).split('.')[0] 
                    print(f"  [RETRY] Error: {err_msg}. Waiting {_delay}s...")
                    time.sleep(_delay)
                    _tries -= 1
                    _delay *= 2 
            return f(*args, **kwargs)
        return wrapper
    return decorator

def fetch_universe():
    print("[1/4] Building Universe from Google Sheets...")
    urls = {
        'SPX': "https://docs.google.com/spreadsheets/d/e/2PACX-1vSpFLwMNa0AUsSC62LQZCQfIvvXRPPmX00cY7DO2sbiHu47Z72aJ_R-F_IrILBbKqIZGdSFgXFUrZyJ/pub?gid=0&single=true&output=csv",
        'RMC': "https://docs.google.com/spreadsheets/d/e/2PACX-1vSpFLwMNa0AUsSC62LQZCQfIvvXRPPmX00cY7DO2sbiHu47Z72aJ_R-F_IrILBbKqIZGdSFgXFUrZyJ/pub?gid=679638722&single=true&output=csv",
        'RTY': "https://docs.google.com/spreadsheets/d/e/2PACX-1vRrTpcehWaL1Aq-uTn986nie8Hwrs_uHUOYr-E_wCG0jtLKQjvpw0V8x1wVz8yJdxFhqr7mz07jjpkM/pub?gid=0&single=true&output=csv"
    }
    
    uni = []
    for idx, url in urls.items():
        try:
            res = requests.get(url, headers={'User-Agent': UA}, timeout=15)
            if res.status_code == 200:
                lines = res.text.splitlines()
                h_idx = next((i for i, l in enumerate(lines) if 'Symbol' in l), 0)
                df = pd.read_csv(io.StringIO("\n".join(lines[h_idx:])))
                df.columns = df.columns.str.strip()
                if 'Symbol' in df.columns:
                    for s in df['Symbol'].dropna().unique():
                        t = str(s).strip().replace('.', '-')
                        if t and t != 'nan':
                            uni.append({'Ticker': t, 'Index': idx})
        except Exception as e:
            print(f"  [!] Error fetching {idx}: {e}")
    
    df_uni = pd.DataFrame(uni).drop_duplicates(subset=['Ticker'])
    if not df_uni.empty:
        print(f"  [✓] Found {len(df_uni)} total tickers in universe.")
        return df_uni
    return pd.DataFrame()

@retry(Exception, tries=3, delay=5)
def get_options_snapshot(row):
    ticker = row['Ticker']
    
    # yfinance handles its own curl_cffi session automatically here
    tkr = yf.Ticker(ticker)
    expirations = tkr.options
    if not expirations:
        return None

    now = datetime.datetime.now()
    m1_prefix = now.strftime("%Y-%m")
    m2_prefix = (now + relativedelta(months=1)).strftime("%Y-%m")

    data = {'Date': now.strftime('%Y-%m-%d'), 'Ticker': ticker, 'Index': row['Index']}
    stats = {"M1_C": 0, "M1_P": 0, "M2_C": 0, "M2_P": 0}
    
    for d in expirations[:8]:
        target = "M1" if d.startswith(m1_prefix) else ("M2" if d.startswith(m2_prefix) else None)
        if target:
            chain = tkr.option_chain(d)
            stats[f"{target}_C"] += chain.calls['openInterest'].fillna(0).sum()
            stats[f"{target}_P"] += chain.puts['openInterest'].fillna(0).sum()

    data['M1_NetOI'] = int(stats['M1_C'] - stats['M1_P'])
    data['M2_NetOI'] = int(stats['M2_C'] - stats['M2_P'])
    data['M1_PC'] = stats['M1_P'] / stats['M1_C'] if stats['M1_C'] > 0 else 0
    data['M2_PC'] = stats['M2_P'] / stats['M2_C'] if stats['M2_C'] > 0 else 0
    
    return data

def run_harvest():
    start_time = time.time()
    df_uni = fetch_universe()
    if df_uni.empty: 
        print("[!] Aborting: Universe is empty.")
        return

    if os.path.exists(FILE_NAME):
        print(f"[2/4] Loading existing history from {FILE_NAME}...")
        df_hist = pd.read_parquet(FILE_NAME)
        latest_date = df_hist['Date'].max()
        df_prev = df_hist[df_hist['Date'] == latest_date].drop_duplicates(subset=['Ticker']).set_index('Ticker')
    else:
        print("[2/4] No existing history found. Creating new database.")
        df_hist, df_prev = pd.DataFrame(), pd.DataFrame()

    print(f"[3/4] Harvesting Options Data ({MAX_WORKERS} workers)...")
    new_results = []
    tickers_list = df_uni.to_dict('records')
    
    total = len(tickers_list)
    processed = 0

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {executor.submit(get_options_snapshot, row): row['Ticker'] for row in tickers_list}
        for f in as_completed(futures):
            processed += 1
            if processed % 100 == 0:
                print(f"  ... Progress: {processed}/{total} tickers checked.")
                
            try:
                res = f.result()
                if res:
                    t = res['Ticker']
                    if t in df_prev.index:
                        prev_m1 = int(df_prev.loc[t].get('M1_NetOI', 0)) if 'M1_NetOI' in df_prev.columns else 0
                        prev_m2 = int(df_prev.loc[t].get('M2_NetOI', 0)) if 'M2_NetOI' in df_prev.columns else 0
                        res['M1_DeltaNetOI'] = res['M1_NetOI'] - prev_m1
                        res['M2_DeltaNetOI'] = res['M2_NetOI'] - prev_m2
                    else:
                        res['M1_DeltaNetOI'], res['M2_DeltaNetOI'] = 0, 0
                    new_results.append(res)
            except Exception as e:
                print(f"  [ERROR] {futures[f]} failed: {e}")
            
            time.sleep(1.0) # Crucial delay to avoid GitHub Actions IP ban

    if new_results:
        print(f"\n[4/4] Saving {len(new_results)} valid option chains...")
        df_new = pd.DataFrame(new_results)
        df_final = pd.concat([df_hist, df_new]).drop_duplicates(subset=['Ticker', 'Date'], keep='last')
        df_final.sort_values(by=['Date', 'Ticker'], ascending=[False, True]).to_parquet(FILE_NAME)
        
        end_time = time.time()
        print("\n" + "="*50)
        print("          HARVEST SUCCESSFUL")
        print("="*50)
        print(f"Total Time : {(end_time - start_time) / 60:.1f} minutes")
        print(f"Rows Added : {len(df_new)}")
        print(f"Total DB   : {len(df_final)} rows")
        print("="*50)
    else:
        print("\n[!] Harvest completed but no data was collected.")

if __name__ == "__main__":
    run_harvest()
