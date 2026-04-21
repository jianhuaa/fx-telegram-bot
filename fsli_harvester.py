import pandas as pd
import yfinance as yf
import requests
import io
from tradingview_screener import Query, col

def map_sec_to_etf(x):
    x_str = str(x).strip().upper()
    sec_map_inv = {
        "COMMUNICATION": "XLC", "DISCRETIONARY": "XLY", "STAPLES": "XLP",
        "ENERGY": "XLE", "FINANCIAL": "XLF", "HEALTH": "XLV", "INDUSTRIAL": "XLI",
        "TECHNOLOGY": "XLK", "MATERIALS": "XLB", "REAL ESTATE": "XLRE", "UTILITIES": "XLU"
    }
    if x_str in sec_map_inv.values(): return x_str
    for k, v in sec_map_inv.items():
        if k in x_str: return v
    return 'UNK'

print("1. Fetching Google Sheets (Universe Definition)...")
headers = {'User-Agent': 'Mozilla/5.0'}

sheet_data = []

# --- 1A: RUT SHEET (Starts Row 4) ---
rut_url = "https://docs.google.com/spreadsheets/d/e/2PACX-1vRrTpcehWaL1Aq-uTn986nie8Hwrs_uHUOYr-E_wCG0jtLKQjvpw0V8x1wVz8yJdxFhqr7mz07jjpkM/pub?gid=0&single=true&output=csv"
res_rut = requests.get(rut_url, headers=headers)
lines_rut = res_rut.text.splitlines()
h_idx_rut = next((i for i, l in enumerate(lines_rut) if 'Symbol' in l), 3)
df_rut = pd.read_csv(io.StringIO("\n".join(lines_rut[h_idx_rut:])))
df_rut.columns = df_rut.columns.astype(str).str.strip()
df_rut = df_rut.iloc[max(0, (4 - 1) - h_idx_rut - 1):].reset_index(drop=True)
df_rut['Index'] = 'RTY'
sheet_data.append(df_rut)

# --- 1B: RMC SHEET (Starts Row 4) ---
rmc_url = "https://docs.google.com/spreadsheets/d/e/2PACX-1vSpFLwMNa0AUsSC62LQZCQfIvvXRPPmX00cY7DO2sbiHu47Z72aJ_R-F_IrILBbKqIZGdSFgXFUrZyJ/pub?gid=679638722&single=true&output=csv"
res_rmc = requests.get(rmc_url, headers=headers)
lines_rmc = res_rmc.text.splitlines()
h_idx_rmc = next((i for i, l in enumerate(lines_rmc) if 'Symbol' in l), 3)
df_rmc = pd.read_csv(io.StringIO("\n".join(lines_rmc[h_idx_rmc:])))
df_rmc.columns = df_rmc.columns.astype(str).str.strip()
df_rmc = df_rmc.iloc[max(0, (4 - 1) - h_idx_rmc - 1):].reset_index(drop=True)
df_rmc['Index'] = 'RMC'
sheet_data.append(df_rmc)

# --- 1C: SPX SHEET (Starts Row 39) ---
spx_url = "https://docs.google.com/spreadsheets/d/e/2PACX-1vSpFLwMNa0AUsSC62LQZCQfIvvXRPPmX00cY7DO2sbiHu47Z72aJ_R-F_IrILBbKqIZGdSFgXFUrZyJ/pub?gid=0&single=true&output=csv"
res_spx = requests.get(spx_url, headers=headers)
lines_spx = res_spx.text.splitlines()
h_idx_spx = next((i for i, l in enumerate(lines_spx) if 'Symbol' in l), 38)
df_spx = pd.read_csv(io.StringIO("\n".join(lines_spx[h_idx_spx:])))
df_spx.columns = df_spx.columns.astype(str).str.strip()
df_spx = df_spx.iloc[max(0, (39 - 1) - h_idx_spx - 1):].reset_index(drop=True)
df_spx['Index'] = 'SPX'
sheet_data.append(df_spx)

# --- COMBINE AND CLEAN EXACTLY LIKE APP.PY ---
df_sheets = pd.concat(sheet_data, ignore_index=True)
df_clean = pd.DataFrame()

# We explicitly call 'Symbol' now so it can never grab 'Exchange' by mistake
df_clean['Ticker'] = df_sheets['Symbol'].astype(str).str.strip().str.replace('.', '-')
df_clean['Sector_Raw'] = df_sheets.iloc[:, 2].astype(str).str.strip() # Column index 2 is ETF
df_clean['Industry'] = df_sheets.iloc[:, 3].astype(str).str.strip()   # Column index 3 is Industry
df_clean['Index'] = df_sheets['Index']

df_clean = df_clean[(df_clean['Ticker'] != 'nan') & (df_clean['Ticker'] != '')]
# Filter out any literal junk headers that might have slipped in
df_clean = df_clean[~df_clean['Ticker'].isin(['Symbol', 'NASDAQ', 'NYSE', 'AMEX', 'INDEXRUSSELL', 'NYSEAMERICAN'])]
df_clean['Sector'] = df_clean['Sector_Raw'].apply(map_sec_to_etf)

master_tickers = df_clean['Ticker'].unique().tolist()

print(f"2. Pulling TradingView Bulk FSLI (Filtering {len(master_tickers)} valid tickers)...")
tv_fields = [
    'name', 'close', 'market_cap_basic', 'price_earnings_ttm', 'total_revenue_ttm',
    'cash_f_operating_activities_ttm', 'free_cash_flow_fy', 'cash_f_investing_activities_ttm', 
    'cash_f_financing_activities_ttm', 'cash_n_short_term_invest_fq', 'short_term_debt_fq', 
    'long_term_debt_fq', 'total_debt_fq', 'goodwill_fq', 'gross_margin_ttm', 
    'operating_margin_ttm', 'net_margin_ttm', 'cash_n_short_term_invest_to_total_debt_fq',
    'earnings_release_trading_date_fq', 'earnings_release_next_trading_date_fq'
]

query = Query().select(*tv_fields).where(col('exchange').isin(['AMEX', 'NASDAQ', 'NYSE']))
_, df_tv = query.get_scanner_data()
df_tv['Ticker'] = df_tv['ticker'].str.split(':').str[1]
df_tv['Ticker'] = df_tv['Ticker'].replace({'P': 'PSTG'}).str.replace('.', '-')

print("3. Batched YFinance Pull (1Y% & Fast Short Interest)...")
hist_raw = yf.download(master_tickers, period='1y', interval='1d', progress=False, auto_adjust=True)

if not hist_raw.empty and 'Close' in hist_raw.columns:
    cl = hist_raw['Close']
elif not hist_raw.empty and isinstance(hist_raw.columns, pd.MultiIndex):
    cl = hist_raw.xs('Close', level=0, axis=1)
else:
    cl = pd.DataFrame()

yq_data = []
from yahooquery import Ticker as YQTicker
chunk_size = 200
for i in range(0, len(master_tickers), chunk_size):
    chunk = master_tickers[i:i + chunk_size]
    try:
        yq = YQTicker(chunk, asynchronous=True)
        stats = yq.get_modules('defaultKeyStatistics')
        for t in chunk:
            if isinstance(stats, dict) and t in stats and isinstance(stats[t], dict):
                si = stats[t].get('sharesShort', 0)
                so = stats[t].get('sharesOutstanding', 1)
                si_pct = (si / so) * 100 if so > 0 else float('nan')
                yq_data.append({'Ticker': t, 'Short Interest %': si_pct})
    except Exception: pass

df_yq = pd.DataFrame(yq_data) if yq_data else pd.DataFrame(columns=['Ticker', 'Short Interest %'])

# Calculate 1Y% Distribution Rank
one_y_data = []
for t in master_tickers:
    if t in cl.columns and not cl[t].dropna().empty:
        s = cl[t].dropna()
        last_px = s.iloc[-1]
        pct_rank = (s <= last_px).mean() * 100
        one_y_data.append({'Ticker': t, '1Y%': pct_rank})

df_1y = pd.DataFrame(one_y_data) if one_y_data else pd.DataFrame(columns=['Ticker', '1Y%'])

print("4. Merging Data & Calculating Industry Quartiles...")
df_master = pd.merge(df_clean[['Ticker', 'Index', 'Sector', 'Industry']], df_tv, on='Ticker', how='inner')
df_master = pd.merge(df_master, df_1y, on='Ticker', how='left')
df_master = pd.merge(df_master, df_yq, on='Ticker', how='left')

rename_map = {
    'close': 'Last Price', 'market_cap_basic': 'Mkt Cap (M)', 'price_earnings_ttm': 'P/E Ratio',
    'cash_f_operating_activities_ttm': 'Op CF (M)', 'free_cash_flow_fy': 'FCF (M)',
    'cash_f_investing_activities_ttm': 'Inv CF (M)', 'cash_f_financing_activities_ttm': 'Fin CF (M)',
    'cash_n_short_term_invest_fq': 'Cash & STI (M)', 'short_term_debt_fq': 'ST Debt (M)',
    'long_term_debt_fq': 'LT Debt (M)', 'total_debt_fq': 'Total Debt (M)',
    'goodwill_fq': 'Goodwill, Net (M)', 'gross_margin_ttm': 'Gross Marg %',
    'operating_margin_ttm': 'Op Marg %', 'net_margin_ttm': 'Net Marg %',
    'cash_n_short_term_invest_to_total_debt_fq': 'Cash/Debt Ratio',
    'earnings_release_trading_date_fq': 'Recent Earnings Date',
    'earnings_release_next_trading_date_fq': 'Upcoming Earnings Date'
}
df_master = df_master.rename(columns=rename_map)

# Define Logic Rules (1 = Highest is Green, -1 = Highest is Red)
metric_rules = {
    'P/E Ratio': -1, 'Short Interest %': -1, '1Y%': 1, 'Mkt Cap (M)': 1,
    'Gross Marg %': 1, 'Op Marg %': 1, 'Net Marg %': 1,
    'Op CF (M)': 1, 'FCF (M)': 1,
    'Cash & STI (M)': 1, 'ST Debt (M)': -1, 'LT Debt (M)': -1, 
    'Total Debt (M)': -1, 'Cash/Debt Ratio': 1, 'Goodwill, Net (M)': -1
}

def score_quartile(val, q25, q75, polarity):
    if pd.isna(val): return 0
    if polarity == 1:
        return 1 if val >= q75 else (-1 if val <= q25 else 0)
    else:
        return -1 if val >= q75 else (1 if val <= q25 else 0)

for metric, polarity in metric_rules.items():
    if metric in df_master.columns:
        q_df = df_master.groupby('Industry')[metric].agg(q25=lambda x: x.quantile(0.25), q75=lambda x: x.quantile(0.75)).reset_index()
        df_master = pd.merge(df_master, q_df, on='Industry', how='left')
        df_master[f'{metric}_Score'] = df_master.apply(lambda x: score_quartile(x[metric], x['q25'], x['q75'], polarity), axis=1)
        df_master = df_master.drop(columns=['q25', 'q75'])

# Handle Binaries
if 'Inv CF (M)' in df_master.columns:
    df_master['Inv CF (M)_Score'] = df_master['Inv CF (M)'].apply(lambda x: 1 if pd.notna(x) and x < 0 else -1)

if all(c in df_master.columns for c in ['Op CF (M)', 'Inv CF (M)', 'Fin CF (M)']):
    df_master['Self-Funding_Score'] = df_master.apply(
        lambda x: 1 if pd.notna(x['Op CF (M)']) and x['Op CF (M)'] >= (abs(x.get('Inv CF (M)', 0)) + abs(x.get('Fin CF (M)', 0))) else -1, 
        axis=1
    )

df_master.to_parquet('fsli_master.parquet')
print("✅ Success! fsli_master.parquet created.")
