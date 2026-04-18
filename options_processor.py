import pandas as pd
import yfinance as yf
import datetime
import time
import os
import io
import requests
import random
from curl_cffi import requests as cffi_requests
from dateutil.relativedelta import relativedelta

# --- TANK CONFIG ---
FILE_NAME = 'col4_options_history.parquet'
# CHANGED: Auto-save every 1 ticker instead of 50
SAVE_INTERVAL = 1  

# Stealth User Agent
UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36'

# UNAFFECTED: fetch_universe function remains exactly the same
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

# UNAFFECTED: get_options_snapshot function remains exactly the same
def get_options_snapshot(ticker, index_name):
    try:
        # Create a fresh, safe session for this specific request
        safe_session = cffi_requests.Session(impersonate="chrome")
        tkr = yf.Ticker(ticker, session=safe_session)
        
        expirations = tkr.options
        if not expirations:
            return None

        now = datetime.datetime.now()
        m1_prefix = now.strftime("%Y-%m")
        m2_prefix = (now + relativedelta(months=1)).strftime("%Y-%m")

        data = {'Date': now.strftime('%Y-%m-%d'), 'Ticker': ticker, 'Index': index_name}
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
    except Exception as e:
        err_msg = str(e).split('.')[0]
        if "Too Many Requests" in err_msg or "RateLimitError" in err_msg:
            # Pass the rate limit exception up to trigger the play-dead logic
            raise Exception("RateLimited")
        print(f"    [!] Skipping {ticker} due to data error: {err_msg}")
        return None

def run_harvest():
    start_time = time.time()
    df_uni = fetch_universe()
    if df_uni.empty: 
        print("[!] Aborting: Universe is empty.")
        return

    if os.path.exists(FILE_NAME):
        print(f"[2/4] Loading existing history from {FILE_NAME}...")
        df_hist = pd.read_parquet(FILE_NAME)

        # THE FIX: Ignore data from *today* so we only compare against past days
        today_str = datetime.datetime.now().strftime('%Y-%m-%d')
        df_past = df_hist[df_hist['Date'] < today_str]
        
        if not df_past.empty:
            # Grab the single most recent past row for each ticker
            df_prev = df_past.sort_values('Date').drop_duplicates(subset=['Ticker'], keep='last').set_index('Ticker')
        else:
            df_prev = pd.DataFrame()
        
        #latest_date = df_hist['Date'].max()
        #df_prev = df_hist[df_hist['Date'] == latest_date].drop_duplicates(subset=['Ticker']).set_index('Ticker')
    else:
        print("[2/4] No existing history found. Creating new database.")
        df_hist, df_prev = pd.DataFrame(), pd.DataFrame()

    print("[3/4] Harvesting Options Data (Sequential Tank Mode)...")
    new_results = []
    
    total = len(df_uni)
    processed = 0

    # PURE SEQUENTIAL LOOP
    for _, row in df_uni.iterrows():
        t = row['Ticker']
        idx = row['Index']
        processed += 1
        
        retry_count = 3
        success = False
        
        while retry_count > 0 and not success:
            try:
                res = get_options_snapshot(t, idx)
                if res:
                    # Calculate Delta
                    if t in df_prev.index:
                        prev_m1 = int(df_prev.loc[t].get('M1_NetOI', 0)) if 'M1_NetOI' in df_prev.columns else 0
                        prev_m2 = int(df_prev.loc[t].get('M2_NetOI', 0)) if 'M2_NetOI' in df_prev.columns else 0
                        res['M1_DeltaNetOI'] = res['M1_NetOI'] - prev_m1
                        res['M2_DeltaNetOI'] = res['M2_NetOI'] - prev_m2
                    else:
                        res['M1_DeltaNetOI'], res['M2_DeltaNetOI'] = 0, 0
                    
                    new_results.append(res)
                
                success = True
                
                # CHANGED: Static 0.08s delay per user request
                time.sleep(0.08)
                
            except Exception as e:
                if "RateLimited" in str(e):
                    penalty = 60 * (4 - retry_count) # Escalating penalty: 60s, 120s, 180s
                    print(f"\n  [RATE LIMIT] Hit a wall on {t}. Playing dead for {penalty} seconds...")
                    time.sleep(penalty)
                    retry_count -= 1
                else:
                    break # Unrelated error, skip ticker
        
        # UI Progress & Auto-Save
        if processed % 10 == 0:
            print(f"  ... Progress: {processed}/{total} processed.")
            
        if processed % SAVE_INTERVAL == 0 and len(new_results) > 0:
            # We mute the print statement here so it doesn't spam your console every single ticker
            # print(f"  [AUTO-SAVE] Checkpoint reached at {processed}. Saving database...") 
            df_temp = pd.DataFrame(new_results)
            df_checkpoint = pd.concat([df_hist, df_temp]).drop_duplicates(subset=['Ticker', 'Date'], keep='last')
            df_checkpoint.sort_values(by=['Date', 'Ticker'], ascending=[False, True]).to_parquet(FILE_NAME)

    # Final Save
    if new_results:
        print(f"\n[4/4] Finalizing save of {len(new_results)} valid option chains...")
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
