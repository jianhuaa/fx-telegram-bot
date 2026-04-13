import pandas as pd
import requests
import io
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
import warnings

warnings.filterwarnings('ignore')

# --- CONFIGURATION ---
OUTPUT_FILE = 'col4_insider_trades.parquet'
MAX_WORKERS = 5 # Fetches 5 tickers at a time to be fast but respectful

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

all_tickers = set()
for df in [df_spx, df_rmc, df_rut]:
    for _, row in df.iterrows():
        try:
            t = str(row['Symbol']).strip().replace('.', '-')
            if t != 'nan' and t:
                all_tickers.add(t)
        except:
            pass

tickers_list = sorted(list(all_tickers))
print(f"Loaded {len(tickers_list)} unique tickers.")

# --- 2. YOUR EXACT OPENINSIDER FUNCTION ---
def get_insider_trades(ticker):
    # OpenInsider requires dots (BRK.B), but your sheets use hyphens (BRK-B)
    search_ticker = ticker.replace('-', '.')
    
    url = f"http://openinsider.com/screener?s={search_ticker}&o=&pl=&ph=&ll=&lh=&fd=0&fdr=&td=0&tdr=&fdlyl=&fdlyh=&daysago=&xp=1&xs=1&xa=0&xd=0&xg=0&xf=0&xm=0&xx=0&xc=0&xw=0&excludeDerivRelated=1&tmult=1&sortcol=0&cnt=5000&page=1"
    req_headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    }
    try:
        response = requests.get(url, headers=req_headers, timeout=10)
        response.raise_for_status()
        tables = pd.read_html(io.StringIO(response.text), attrs={'class': 'tinytable'})
        if tables:
            df = tables[0]
            df.columns = df.columns.astype(str).str.replace(r'\s+', ' ', regex=True).str.strip()

            dashboard_cols = ['Ticker', 'Trade Date', 'Insider Name', 'Title', 'Trade Type', 'Price', 'Value', 'ΔOwn']
            available_cols = [col for col in dashboard_cols if col in df.columns]
            clean_df = df[available_cols].copy()

            if 'Trade Type' in clean_df.columns:
                clean_df['Trade Type'] = clean_df['Trade Type'].astype(str).apply(
                    lambda x: x.split('- ')[-1] if '- ' in x else x
                )
            
            # Force the Ticker column back to your format (e.g. BRK-B)
            if 'Ticker' in clean_df.columns:
                clean_df['Ticker'] = ticker 
                
            return clean_df
    except Exception as e:
        pass
    return pd.DataFrame()

# --- 3. RUN CONCURRENTLY ---
print(f"Scraping {len(tickers_list)} tickers one by one using {MAX_WORKERS} workers...")
all_trades = []
count = 0

with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
    futures = {executor.submit(get_insider_trades, t): t for t in tickers_list}
    for future in as_completed(futures):
        count += 1
        ticker = futures[future]
        df = future.result()
        if not df.empty:
            all_trades.append(df)
            print(f"[{count}/{len(tickers_list)}] {ticker}: Found {len(df)} trades.")
        else:
            print(f"[{count}/{len(tickers_list)}] {ticker}: 0 trades.")

# --- 4. SAVE TO PARQUET ---
if all_trades:
    final_df = pd.concat(all_trades, ignore_index=True)
    
    # Sort and clean
    final_df['Trade Date'] = pd.to_datetime(final_df['Trade Date'], errors='coerce')
    final_df = final_df.sort_values(by=['Ticker', 'Trade Date'], ascending=[True, False])
    final_df['Trade Date'] = final_df['Trade Date'].dt.strftime('%Y-%m-%d')
    
    final_df.to_parquet(OUTPUT_FILE)
    print(f"\nSaved {len(final_df)} trades to {OUTPUT_FILE}")
else:
    print("\nNo trades found at all.")
    pd.DataFrame(columns=['Ticker', 'Trade Date', 'Insider Name', 'Title', 'Trade Type', 'Price', 'Value', 'ΔOwn']).to_parquet(OUTPUT_FILE)
