import pandas as pd
import yfinance as yf
import requests
import io
import time
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
urls = {
    'RTY': "https://docs.google.com/spreadsheets/d/e/2PACX-1vRrTpcehWaL1Aq-uTn986nie8Hwrs_uHUOYr-E_wCG0jtLKQjvpw0V8x1wVz8yJdxFhqr7mz07jjpkM/pub?gid=0&single=true&output=csv",
    'RMC': "https://docs.google.com/spreadsheets/d/e/2PACX-1vSpFLwMNa0AUsSC62LQZCQfIvvXRPPmX00cY7DO2sbiHu47Z72aJ_R-F_IrILBbKqIZGdSFgXFUrZyJ/pub?gid=679638722&single=true&output=csv",
    'SPX': "https://docs.google.com/spreadsheets/d/e/2PACX-1vSpFLwMNa0AUsSC62LQZCQfIvvXRPPmX00cY7DO2sbiHu47Z72aJ_R-F_IrILBbKqIZGdSFgXFUrZyJ/pub?gid=0&single=true&output=csv"
}

sheet_data = []
for idx_name, url in urls.items():
    res = requests.get(url, headers=headers)
    lines = res.text.splitlines()
    h_idx = next((i for i, l in enumerate(lines) if 'Symbol' in l), 3) if idx_name != 'SPX' else 38
    df_temp = pd.read_csv(io.StringIO("\n".join(lines[h_idx:])))
    df_temp['Index'] = idx_name
    sheet_data.append(df_temp)

df_sheets = pd.concat(sheet_data, ignore_index=True)
df_sheets = df_sheets.rename(columns={df_sheets.columns[0]: 'Ticker', df_sheets.columns[2]: 'Sector_Raw', df_sheets.columns[3]: 'Industry'})
df_sheets['Ticker'] = df_sheets['Ticker'].astype(str).str.strip().str.replace('.', '-')
df_sheets = df_sheets[df_sheets['Ticker'] != 'nan']
df_sheets['Sector'] = df_sheets['Sector_Raw'].apply(map_sec_to_etf)
master_tickers = df_sheets['Ticker'].unique().tolist()

print(f"2. Pulling TradingView Bulk FSLI (Filtering {len(master_tickers)} tickers)...")
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
# yfinance batch pull is incredibly fast and avoids IP bans
hist_raw = yf.download(master_tickers, period='1y', interval='1d', progress=False, auto_adjust=True)
cl = hist_raw['Close'] if isinstance(hist_raw.columns, pd.MultiIndex) else pd.DataFrame(hist_raw['Close'])

yq_data = []
# Fast chunking for YahooQuery Short Interest to avoid timeouts
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
df_1y = pd.DataFrame(one_y_data)

print("4. Merging Data & Calculating Industry Quartiles...")
df_master = pd.merge(df_sheets[['Ticker', 'Index', 'Sector', 'Industry']], df_tv, on='Ticker', how='inner')
df_master = pd.merge(df_master, df_1y, on='Ticker', how='left')
df_master = pd.merge(df_master, df_yq, on='Ticker', how='left')

# Rename to clean columns
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

# Define Logic Rules
# +1 means highest is green. -1 means highest is red.
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
        # Group strictly by Industry to find peers
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
