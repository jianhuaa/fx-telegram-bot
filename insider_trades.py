import pandas as pd
import requests
import io
import time
import urllib.parse
import warnings

warnings.filterwarnings('ignore')

# --- CONFIGURATION ---
CHUNK_SIZE = 40  # Number of tickers to query per OpenInsider request
SLEEP_DELAY = 2.0  # Seconds to wait between requests to prevent IP bans
OUTPUT_FILE = 'col4_insider_trades.parquet'

headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
}

# --- 1. BUILD UNIVERSE FROM GOOGLE SHEETS ---
print("Fetching Universe from Google Sheets...")

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
print(f"Loaded {len(tickers_list)} unique tickers from sheets.")

# --- 2. BATCH & SCRAPE OPENINSIDER ---
print("Harvesting OpenInsider Data in batches...")

dashboard_cols = ['Ticker', 'Trade Date', 'Insider Name', 'Title', 'Trade Type', 'Price', 'Value', 'ΔOwn']
all_trades = []

# Break the massive list into chunks of 40
chunks = [tickers_list[i:i + CHUNK_SIZE] for i in range(0, len(tickers_list), CHUNK_SIZE)]

for i, chunk in enumerate(chunks):
    # Join tickers with a comma and URL-encode them
    ticker_str = urllib.parse.quote(",".join(chunk))
    
    # fd=0 (all recent), cnt=5000 (max results per page)
    url = f"http://openinsider.com/screener?s={ticker_str}&o=&pl=&ph=&ll=&lh=&fd=0&fdr=&td=0&tdr=&fdlyl=&fdlyh=&daysago=&xp=1&xs=1&xa=0&xd=0&xg=0&xf=0&xm=0&xx=0&xc=0&xw=0&excludeDerivRelated=1&tmult=1&sortcol=0&cnt=5000&page=1"
    
    try:
        response = requests.get(url, headers=headers, timeout=15)
        response.raise_for_status()
        
        tables = pd.read_html(io.StringIO(response.text), attrs={'class': 'tinytable'})
        if tables and not tables[0].empty:
            df = tables[0]
            # Clean column names
            df.columns = df.columns.astype(str).str.replace(r'\s+', ' ', regex=True).str.strip()
            
            # Filter only the columns we actually want for the dashboard
            available_cols = [col for col in dashboard_cols if col in df.columns]
            clean_df = df[available_cols].copy()
            
            # Clean the 'Trade Type' string (e.g., "P - Purchase" -> "Purchase")
            if 'Trade Type' in clean_df.columns:
                clean_df['Trade Type'] = clean_df['Trade Type'].astype(str).apply(
                    lambda x: x.split('- ')[-1] if '- ' in x else x
                )
            
            all_trades.append(clean_df)
            print(f"[{i+1}/{len(chunks)}] Fetched {len(clean_df)} trades for chunk...")
        else:
            print(f"[{i+1}/{len(chunks)}] No trades found for this chunk.")
            
    except Exception as e:
        print(f"[{i+1}/{len(chunks)}] Error fetching chunk: {e}")
    
    # Be polite to OpenInsider servers
    time.sleep(SLEEP_DELAY)

# --- 3. CONSOLIDATE AND SAVE ---
if all_trades:
    final_df = pd.concat(all_trades, ignore_index=True)
    
    # Sort so the newest trades are at the top
    final_df['Trade Date'] = pd.to_datetime(final_df['Trade Date'], errors='coerce')
    final_df = final_df.sort_values(by=['Ticker', 'Trade Date'], ascending=[True, False])
    
    # Convert date back to string for clean parquet serialization
    final_df['Trade Date'] = final_df['Trade Date'].dt.strftime('%Y-%m-%d %H:%M:%S')
    
    final_df.to_parquet(OUTPUT_FILE)
    print(f"\nSuccessfully saved {len(final_df)} total insider trades to {OUTPUT_FILE}.")
else:
    print("\nWarning: No insider trades were fetched across all chunks.")
    # Create empty parquet with correct schema so Streamlit doesn't break
    empty_df = pd.DataFrame(columns=dashboard_cols)
    empty_df.to_parquet(OUTPUT_FILE)
