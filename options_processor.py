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

# --- CONFIG ---
FILE_NAME = 'col4_options_history.parquet'
MAX_WORKERS = 8  # Throttled to ~8 requests per second to avoid IP bans

def retry(exceptions, tries=3, delay=2):
    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            _tries, _delay = tries, delay
            while _tries > 1:
                try: return f(*args, **kwargs)
                except exceptions:
                    time.sleep(_delay)
                    _tries -= 1
            return f(*args, **kwargs)
        return wrapper
    return decorator

def fetch_universe():
    print("Building Universe from Google Sheets...")
    headers = {'User-Agent': 'Mozilla/5.0'}
    urls = {
        'SPX': "https://docs.google.com/spreadsheets/d/e/2PACX-1vSpFLwMNa0AUsSC62LQZCQfIvvXRPPmX00cY7DO2sbiHu47Z72aJ_R-F_IrILBbKqIZGdSFgXFUrZyJ/pub?gid=0&single=true&output=csv",
        'RMC': "https://docs.google.com/spreadsheets/d/e/2PACX-1vSpFLwMNa0AUsSC62LQZCQfIvvXRPPmX00cY7DO2sbiHu47Z72aJ_R-F_IrILBbKqIZGdSFgXFUrZyJ/pub?gid=679638722&single=true&output=csv",
        'RTY': "https://docs.google.com/spreadsheets/d/e/2PACX-1vRrTpcehWaL1Aq-uTn986nie8Hwrs_uHUOYr-E_wCG0jtLKQjvpw0V8x1wVz8yJdxFhqr7mz07jjpkM/pub?gid=0&single=true&output=csv"
    }
    uni = []
    for idx, url in urls.items():
        try:
            res = requests.get(url, headers=headers)
            lines = res.text.splitlines()
            h_idx = next((i for i, l in enumerate(lines) if 'Symbol' in l), 0)
            df = pd.read_csv(io.StringIO("\n".join(lines[h_idx:])))
            for _, row in df.iterrows():
                t = str(row['Symbol']).strip().replace('.', '-')
                if t and t != 'nan':
                    uni.append({'Ticker': t, 'Index': idx})
        except: pass
    return pd.DataFrame(uni).drop_duplicates(subset=['Ticker'])

@retry(Exception, tries=2, delay=2)
def get_options_snapshot(row):
    ticker = row['Ticker']
    tkr = yf.Ticker(ticker)
    expirations = tkr.options
    if not expirations: return None

    now = datetime.datetime.now()
    m1_prefix = now.strftime("%Y-%m")
    m2_prefix = (now + relativedelta(months=1)).strftime("%Y-%m")

    data = {'Date': now.strftime('%Y-%m-%d'), 'Ticker': ticker, 'Index': row['Index']}
    stats = {"M1_C": 0, "M1_P": 0, "M2_C": 0, "M2_P": 0}
    
    for d in expirations:
        target = "M1" if d.startswith(m1_prefix) else ("M2" if d.startswith(m2_prefix) else None)
        if target:
            chain = tkr.option_chain(d)
            stats[f"{target}_C"] += chain.calls['openInterest'].fillna(0).sum()
            stats[f"{target}_P"] += chain.puts['openInterest'].fillna(0).sum()

    # Calculation logic: NetOI = Call OI - Put OI
    data['M1_NetOI'] = stats['M1_C'] - stats['M1_P']
    data['M1_PC'] = stats['M1_P'] / stats['M1_C'] if stats['M1_C'] > 0 else 0
    data['M2_NetOI'] = stats['M2_C'] - stats['M2_P']
    data['M2_PC'] = stats['M2_P'] / stats['M2_C'] if stats['M2_C'] > 0 else 0
    return data

def process():
    df_uni = fetch_universe()
    # Load History to calculate Delta (Change in NetOI)
    if os.path.exists(FILE_NAME):
        df_hist = pd.read_parquet(FILE_NAME)
        latest_date = df_hist['Date'].max()
        df_prev = df_hist[df_hist['Date'] == latest_date].set_index('Ticker')
    else:
        df_hist, df_prev = pd.DataFrame(), pd.DataFrame()

    tickers_list = df_uni.to_dict('records')
    new_snaps = []

    print(f"Harvesting NET OPEN INTEREST for {len(tickers_list)} tickers...")
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {executor.submit(get_options_snapshot, row): row['Ticker'] for row in tickers_list}
        for f in as_completed(futures):
            res = f.result()
            if res:
                t = res['Ticker']
                # Delta NetOI = Today's NetOI - Yesterday's NetOI
                if t in df_prev.index:
                    res['M1_DeltaNetOI'] = res['M1_NetOI'] - df_prev.loc[t, 'M1_NetOI']
                    res['M2_DeltaNetOI'] = res['M2_NetOI'] - df_prev.loc[t, 'M2_NetOI']
                else:
                    res['M1_DeltaNetOI'], res['M2_DeltaNetOI'] = 0, 0
                new_snaps.append(res)
            time.sleep(0.12) # Strict throttle

    if new_snaps:
        df_final = pd.concat([df_hist, pd.DataFrame(new_snaps)])
        df_final = df_final.drop_duplicates(subset=['Ticker', 'Date'], keep='last')
        df_final.sort_values(by=['Date', 'Ticker'], ascending=[False, True]).to_parquet(FILE_NAME)
        print("Update Success.")

if __name__ == "__main__":
    process()
