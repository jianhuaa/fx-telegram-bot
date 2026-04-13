# 2. IMPORTS & SETUP
import pandas as pd
import requests
from datetime import datetime, timedelta
import time
import io
import os
import yfinance as yf
import subprocess
import sys
import pytz
from yahooquery import Ticker as YQTicker
import warnings

warnings.filterwarnings('ignore')
pd.options.mode.chained_assignment = None

NGROK_AUTH_TOKEN = "3BrXfaU4W1bXEOVG10V0oEz9eCA_6z9xyBggrFBrZLh176RLY"

# UNIVERSAL GLOBAL ETF MAPPER
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

# 3. BACKEND DATA HARVESTER & CUSTOM INDUSTRY MAPPING BRIDGE
start_all = time.time()
print("\n[INFO] --- STEP 0: FETCHING MASTER SHEETS (RUT, RMC, SPX) ---")

headers = {'User-Agent': 'Mozilla/5.0'}

# 3.1 Load Russell 2000 Google Sheet
rut_sheet_url = "https://docs.google.com/spreadsheets/d/e/2PACX-1vRrTpcehWaL1Aq-uTn986nie8Hwrs_uHUOYr-E_wCG0jtLKQjvpw0V8x1wVz8yJdxFhqr7mz07jjpkM/pub?gid=0&single=true&output=csv"
res_rut = requests.get(rut_sheet_url, headers=headers)
lines_rut = res_rut.text.splitlines()
h_idx_rut = next((i for i, l in enumerate(lines_rut) if 'Symbol' in l), 3)
rut_sheet_df = pd.read_csv(io.StringIO("\n".join(lines_rut[h_idx_rut:])))
rut_sheet_df.columns = rut_sheet_df.columns.astype(str).str.strip()
rut_sheet_df = rut_sheet_df.iloc[max(0, (4 - 1) - h_idx_rut - 1):].reset_index(drop=True) # FIX: Skip rows
rty_tickers = set(rut_sheet_df['Symbol'].dropna().astype(str).str.strip().str.replace('.', '-'))

# 3.2 Load RMC Google Sheet
rmc_url = "https://docs.google.com/spreadsheets/d/e/2PACX-1vSpFLwMNa0AUsSC62LQZCQfIvvXRPPmX00cY7DO2sbiHu47Z72aJ_R-F_IrILBbKqIZGdSFgXFUrZyJ/pub?gid=679638722&single=true&output=csv"
res_rmc = requests.get(rmc_url, headers=headers)
lines_rmc = res_rmc.text.splitlines()
h_idx_rmc = next((i for i, l in enumerate(lines_rmc) if 'Symbol' in l), 3)
rmc_sheet_df = pd.read_csv(io.StringIO("\n".join(lines_rmc[h_idx_rmc:])))
rmc_sheet_df.columns = rmc_sheet_df.columns.astype(str).str.strip()
rmc_sheet_df = rmc_sheet_df.iloc[max(0, (4 - 1) - h_idx_rmc - 1):].reset_index(drop=True) # FIX: Skip rows
rmc_tickers = set(rmc_sheet_df['Symbol'].dropna().astype(str).str.strip().str.replace('.', '-'))

# 3.3 Load S&P 500 Google Sheet
spx_url = "https://docs.google.com/spreadsheets/d/e/2PACX-1vSpFLwMNa0AUsSC62LQZCQfIvvXRPPmX00cY7DO2sbiHu47Z72aJ_R-F_IrILBbKqIZGdSFgXFUrZyJ/pub?gid=0&single=true&output=csv"
res_spx = requests.get(spx_url, headers=headers)
lines_spx = res_spx.text.splitlines()
h_idx_spx = next((i for i, l in enumerate(lines_spx) if 'Symbol' in l), 38)
sp500_df = pd.read_csv(io.StringIO("\n".join(lines_spx[h_idx_spx:])))
sp500_df.columns = sp500_df.columns.astype(str).str.strip()
sp500_df = sp500_df.iloc[max(0, (39 - 1) - h_idx_spx - 1):].reset_index(drop=True) # FIX: Skip rows
spx_tickers = set(sp500_df['Symbol'].dropna().astype(str).str.strip().str.replace('.', '-'))

# --- BUILD EXACT CUSTOM MAPPINGS FROM SHEETS WITH SPX PRECEDENCE ---
custom_exact_map = {}
for _, row in rut_sheet_df.iterrows():
    try:
        t = str(row['Symbol']).strip().replace('.', '-')
        etf, ind = str(row.iloc[2]).strip(), str(row.iloc[3]).strip()
        if etf and ind and etf != 'nan' and ind != 'nan': custom_exact_map[t] = (etf, ind)
    except: pass
for _, row in rmc_sheet_df.iterrows():
    try:
        t = str(row['Symbol']).strip().replace('.', '-')
        etf, ind = str(row.iloc[2]).strip(), str(row.iloc[3]).strip()
        if etf and ind and etf != 'nan' and ind != 'nan': custom_exact_map[t] = (etf, ind)
    except: pass
for _, row in sp500_df.iterrows():
    try:
        t = str(row['Symbol']).strip().replace('.', '-')
        etf, ind = str(row.iloc[2]).strip(), str(row.iloc[3]).strip()
        if etf and ind and etf != 'nan' and ind != 'nan': custom_exact_map[t] = (etf, ind)
    except: pass

print("\n[INFO] --- PHASE 1: GENERATING ALL RETURNS SCREENER (Sheets Bypass) ---")
def get_sheet_returns(df, idx_name):
    if df.empty or 'Symbol' not in df.columns: return pd.DataFrame()
    df_c = df.copy()
    df_c['Symbol'] = df_c['Symbol'].astype(str).str.strip().str.replace('.', '-')
    df_c = df_c[df_c['Symbol'] != 'nan']

    def parse_date(d):
        formats = ['%d %b %y', '%d %b %Y', '%Y-%m-%d', '%m/%d/%Y', '%d/%m/%Y', '%d-%b-%y', '%d-%b-%Y', '%b %d, %Y']
        for fmt in formats:
            try: return datetime.strptime(str(d).strip(), fmt)
            except: pass
        return None

    dated_cols = sorted([(c, parse_date(c)) for c in df_c.columns if parse_date(c)], key=lambda x: x[1], reverse=True)
    if not dated_cols: return pd.DataFrame()

    def clean_col(col_name):
        if col_name not in df_c.columns: return pd.Series([float('nan')]*len(df_c))
        s = df_c[col_name].astype(str).str.replace(r'[^0-9\.\-]', '', regex=True).replace('', float('nan'))
        return pd.to_numeric(s, errors='coerce')

    c_curr = 'Live' if 'Live' in df_c.columns else dated_cols[0][0]
    curr_vals = clean_col(c_curr)

    if curr_vals.isna().sum() > (len(curr_vals) * 0.5):
        for d_col, _ in dated_cols:
            c_curr = d_col
            curr_vals = clean_col(c_curr)
            if curr_vals.isna().sum() <= (len(curr_vals) * 0.5): break

    anchor = parse_date(c_curr) if c_curr != 'Live' else dated_cols[0][1]
    if not anchor: anchor = dated_cols[0][1]

    def get_closest(days):
        t = anchor - timedelta(days=days)
        diffs = [(c[0], abs((c[1] - t).days)) for c in dated_cols]
        valid = [d for d in diffs if d[1] <= 7]
        if not valid: return None
        valid.sort(key=lambda x: x[1])
        return valid[0][0]

    c_1d = get_closest(1)
    c_1w = get_closest(7)
    c_1m = get_closest(30)
    c_3m = get_closest(91)
    c_1y = get_closest(365)

    res = pd.DataFrame()
    res['Ticker'] = df_c['Symbol']
    res['Index'] = idx_name
    res['Sector'] = res['Ticker'].apply(lambda x: map_sec_to_etf(custom_exact_map.get(x, ('UNK', 'Unknown'))[0]))
    res['Industry'] = res['Ticker'].apply(lambda x: custom_exact_map.get(x, ('UNK', 'Unknown'))[1])
    res['1D_raw'] = (curr_vals / clean_col(c_1d) - 1) * 100 if c_1d else float('nan')
    res['1W_raw'] = (curr_vals / clean_col(c_1w) - 1) * 100 if c_1w else float('nan')
    res['1M_raw'] = (curr_vals / clean_col(c_1m) - 1) * 100 if c_1m else float('nan')
    res['3M_raw'] = (curr_vals / clean_col(c_3m) - 1) * 100 if c_3m else float('nan')
    res['1Y_raw'] = (curr_vals / clean_col(c_1y) - 1) * 100 if c_1y else float('nan')
    return res

df_spx_ret = get_sheet_returns(sp500_df, 'SPX')
df_rmc_ret = get_sheet_returns(rmc_sheet_df, 'RMC')
df_rut_ret = get_sheet_returns(rut_sheet_df, 'RTY')

df_all_returns = pd.concat([df_spx_ret, df_rmc_ret, df_rut_ret]).dropna(subset=['Ticker']).drop_duplicates(subset=['Ticker'])
df_all_returns.to_parquet('col4_all_returns.parquet')

print("\n" + "="*50 + f"\nDATA GENERATION SUCCESS! Total Time: {time.time()-start_all:.2f}s\n" + "="*50)


# ============================================================
# >>> UNAFFECTED CODE A START (Streamlit Initializer & Base UI) <<<
# ============================================================
code = r"""
import streamlit as st
import yfinance as yf
import datetime
import calendar
import time
import pytz
import warnings
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import requests
import io
import textwrap
import random
import os
from tradingview_screener import Query, col
from yahooquery import Ticker as YQTicker

warnings.filterwarnings("ignore")

sgt = pytz.timezone('Asia/Singapore')
time_str = datetime.datetime.now(sgt).strftime('%d %b %Y | %H:%M SGT')

st.set_page_config(page_title=time_str, page_icon="📊", layout="wide")

st.markdown('''
    <style>

        /* --- GXS Branded Loader Styles --- */
        @keyframes logo-pulse {
            0% { transform: scale(1); opacity: 0.8; }
            50% { transform: scale(1.05); opacity: 1; }
            100% { transform: scale(1); opacity: 0.8; }
        }

        .gxs-loader-container {
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            height: 100vh;
            width: 100vw;
            position: fixed;
            top: 0;
            left: 0;
            background: #161616;
            z-index: 99999;
        }

        .gxs-loader-logo {
            width: 320px;
            animation: logo-pulse 1.5s infinite ease-in-out;
        }

        .block-container {
            padding-top: 0.5rem !important;
            padding-bottom: 0rem !important;
            padding-left: 0.5rem !important;
            padding-right: 0.5rem !important;
            max-width: 100% !important;
        }
        header {visibility: hidden;}
        #MainMenu {visibility: hidden;}
        footer {visibility: hidden;}
        div[data-testid="column"] {
            padding: 0 0.3rem;
        }
        div[data-testid="stVerticalBlock"] {
            gap: 0.1rem !important;
        }

        /* ── CSS for Column 4 Buttons ── */
        div[data-testid="column"]:nth-of-type(4) button[kind="secondary"],
        div[data-testid="column"]:nth-of-type(5) button[kind="secondary"] {
            background-color: #1a1a1a !important;
            border: 1px solid #333 !important;
            border-radius: 4px !important;
            color: #00aaff !important;
            font-weight: bold !important;
            font-size: 13px !important;
            padding: 4px 8px !important;
            height: 32px !important;
            min-height: 32px !important;
            line-height: 1 !important;
            width: 100% !important;
            margin-bottom: 4px !important;
        }
        div[data-testid="column"]:nth-of-type(4) button[kind="secondary"]:hover,
        div[data-testid="column"]:nth-of-type(5) button[kind="secondary"]:hover {
            color: #ff4b4b !important;
            border-color: #ff4b4b !important;
        }

        /* ── Override Selectbox inside Column 4 (Timeframe) ── */
        div[data-testid="column"]:nth-of-type(4) div[data-baseweb="select"] {
            height: 32px !important;
            min-height: 32px !important;
            font-size: 13px !important;
        }
        div[data-testid="column"]:nth-of-type(4) div[data-baseweb="select"] > div {
            height: 32px !important;
            min-height: 32px !important;
            padding-top: 0px !important;
            padding-bottom: 0px !important;
        }

        div[data-testid="stDialog"] div[role="dialog"] {
            position: fixed !important;
            top: 1vh !important;
            left: 1vw !important;
            width: 98vw !important;
            max-width: 98vw !important;
            height: 98vh !important;
            max-height: 98vh !important;
            transform: none !important;
            margin: 0 !important;
            padding: 0px 8px 4px 8px !important;
            overflow: hidden !important;
        }
        div[data-testid="stDialog"] header {
            position: absolute !important;
            top: 0 !important;
            right: 0 !important;
            background: transparent !important;
            z-index: 9999 !important;
            padding: 10px !important;
            width: 40px !important;
            height: 40px !important;
        }

        div[data-testid="stDialog"] header h2 {
            visibility: hidden !important;
            font-size: 0px !important;
            color: transparent !important;
        }

        div[data-testid="stDialog"] div[role="dialog"] > div:nth-child(2) {
            margin-top: -60px !important;
            padding-right: 45px !important;
        }

        div[data-testid="stDialog"] div[data-testid="stVerticalBlock"] {
            gap: 0rem !important;
        }

        /* ── DIALOG DROPDOWN EXACT CSS OVERRIDE ── */
        div[data-testid="stDialog"] div[data-baseweb="select"] {
            min-height: 32px !important;
            height: 32px !important;
            max-height: 32px !important;
            padding-top: 0px !important;
            padding-bottom: 0px !important;
            font-size: 12px !important;
            background-color: #1a1a1a;
            display: flex !important;
            align-items: center !important;
        }
        div[data-testid="stDialog"] .stSelectbox div[data-baseweb="select"] > div {
            min-height: 32px !important;
            height: 32px !important;
            padding-top: 0px !important;
            padding-bottom: 0px !important;
            align-items: center !important;
        }
        div[data-testid="stDialog"] .stMultiSelect div[data-baseweb="select"] > div:first-child {
            min-height: 32px !important;
            height: 32px !important;
            flex-wrap: wrap !important;
            overflow-x: hidden !important;
            overflow-y: auto !important;
            align-items: center !important;
        }
        div[data-testid="stDialog"] .stMultiSelect div[data-baseweb="select"] > div:first-child::-webkit-scrollbar {
            height: 3px;
        }
        div[data-testid="stDialog"] .stMultiSelect div[data-baseweb="select"] > div:first-child::-webkit-scrollbar-thumb {
            background-color: #555;
            border-radius: 2px;
        }
        div[data-testid="stDialog"] div[data-testid="column"] {
            padding: 0 0.2rem !important;
        }
        button[data-baseweb="tab"] {
            padding-top: 4px !important;
            padding-bottom: 4px !important;
            font-size: 13px !important;
        }

    </style>
''', unsafe_allow_html=True)

# >>> UNAFFECTED CODE A START (Data Functions for Columns 1, 2, and 3) <<<
def get_vix_expiration(year, month):
    next_month = month + 1 if month < 12 else 1
    next_year = year if month < 12 else year + 1
    c = calendar.monthcalendar(next_year, next_month)
    fridays = [week[4] for week in c if week[4] != 0]
    return datetime.date(next_year, next_month, fridays[2]) - datetime.timedelta(days=30)

# PASTE THIS NEAR THE TOP OF YOUR FILE
@st.cache_data(ttl=3600)
def get_historical_options_data(ticker):
    try:
        GITHUB_RAW_URL = "https://raw.githubusercontent.com/jianhuaa/fx-telegram-bot/main/col4_options_history.parquet"
        df = pd.read_parquet(GITHUB_RAW_URL)
        df_tick = df[df['Ticker'] == ticker].sort_values('Date', ascending=False).head(10)

        if df_tick.empty:
            return None

        df_tick = df_tick.iloc[::-1]
        latest = df_tick.iloc[-1]
        dates = pd.to_datetime(df_tick['Date']).dt.strftime('%d %b').tolist()

        from dateutil.relativedelta import relativedelta # Ensure this is imported
        return {
            "m1_name": pd.to_datetime(latest['Date']).strftime("%b%y").upper(),
            "m2_name": (pd.to_datetime(latest['Date']) + relativedelta(months=1)).strftime("%b%y").upper(),
            "dates": dates,
            "m1_net": df_tick['M1_NetOI'].tolist(),
            "m1_delta": df_tick['M1_DeltaNetOI'].tolist(),
            "m1_pc": df_tick['M1_PC'].tolist(),
            "m2_net": df_tick['M2_NetOI'].tolist(),
            "m2_delta": df_tick['M2_DeltaNetOI'].tolist(),
            "m2_pc": df_tick['M2_PC'].tolist()
        }
    except Exception as e:
        print(f"Error loading options from GitHub: {e}")
        return None

@st.cache_data(ttl=60)
def get_historical_charts_data(tf):
    try:
        tf_period_map = {"1D": "1d", "1W": "5d", "1M": "1mo", "3M": "3mo", "1Y": "1y"}
        tf_int_map = {"1D": "1m", "1W": "5m", "1M": "15m", "3M": "1d", "1Y": "1d"}
        tickers = {"SPX": "^GSPC", "RUT": "^RUT", "VIX": "^VIX", "VIX3M": "^VIX3M", "VVIX": "^VVIX", "SVIX": "SVIX"}

        df = yf.download(list(tickers.values()), period=tf_period_map.get(tf, "1y"), interval=tf_int_map.get(tf, "1d"), progress=False, auto_adjust=True, threads=False)
        if isinstance(df.columns, pd.MultiIndex): df = df.xs('Close', level=0, axis=1)
        elif 'Close' in df.columns: df = df['Close']
        df.rename(columns={v: k for k, v in tickers.items()}, inplace=True)
        df.dropna(inplace=True)
        return df, ((df / df.iloc[0]) - 1) * 100
    except: return pd.DataFrame(), pd.DataFrame()

@st.cache_data(ttl=60)
def get_sector_data(tf):
    try:
        tf_period_map = {"1D": "1d", "1W": "5d", "1M": "1mo", "3M": "3mo", "1Y": "1y"}
        tf_int_map = {"1D": "1m", "1W": "5m", "1M": "15m", "3M": "1d", "1Y": "1d"}
        sector_map = {'XLK':'XLK', 'XLF':'XLF', 'XLV':'XLV', 'XLY':'XLY', 'XLP':'XLP', 'XLE':'XLE', 'XLI':'XLI', 'XLU':'XLU', 'XLB':'XLB', 'XLRE':'XLRE', 'XLC':'XLC'}

        df_price = yf.download(list(sector_map.keys()), period=tf_period_map.get(tf, "1y"), interval=tf_int_map.get(tf, "1d"), progress=False, auto_adjust=True, threads=False)
        if isinstance(df_price.columns, pd.MultiIndex): df_price = df_price.xs('Close', level=0, axis=1)
        elif 'Close' in df_price.columns: df_price = df_price['Close']
        df_price.rename(columns=sector_map, inplace=True)
        df_price.dropna(inplace=True)
        return df_price, ((df_price / df_price.iloc[0]) - 1) * 100
    except: return pd.DataFrame(), pd.DataFrame()

@st.cache_data(ttl=300)
def get_cme_historical_data():
    try:
        url = "https://raw.githubusercontent.com/jianhuaa/fx-telegram-bot/refs/heads/main/spdr_sectors_history.csv"
        df = pd.read_csv(url)
        df['Date'] = pd.to_datetime(df['Date'])
        recent_dates = sorted(df['Date'].unique(), reverse=True)[:5]
        df_recent = df[df['Date'].isin(recent_dates)].sort_values('Date')
        cme_xl_map = {'COMM':'XLC', 'DISC':'XLY', 'ENER':'XLE', 'FINA':'XLF', 'HLTH':'XLV', 'INDU':'XLI', 'MATL':'XLB', 'REIT':'XLRE', 'STAP':'XLP', 'TECH':'XLK', 'UTIL':'XLU'}
        df_recent['XL_ID'] = df_recent['ID'].map(cme_xl_map)
        return df_recent
    except: return pd.DataFrame()

def get_month_score(m_str):
    months = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]
    try:
        m, y = m_str[:3], int(m_str[3:5])
        return y * 100 + (months.index(m) + 1)
    except: return 9999

@st.cache_data(ttl=300)
def get_sp500_master_data():
    try:
        url = "https://raw.githubusercontent.com/jianhuaa/fx-telegram-bot/refs/heads/main/sp500_history.csv"
        df = pd.read_csv(url)
        df['Date'] = pd.to_datetime(df['Date'])
        recent_dates = sorted(df['Date'].unique(), reverse=True)[:5]
        df_recent = df[df['Date'].isin(recent_dates)].sort_values('Date')
        latest_date = df_recent['Date'].max()

        df_fut = df_recent[df_recent['Type'] == 'FUT'].copy()
        fut_months = df_fut[df_fut['Date'] == latest_date]['Month'].unique()
        front_2_fut = sorted(fut_months, key=get_month_score)[:2]
        df_fut_front = df_fut[df_fut['Month'].isin(front_2_fut)].copy()

        df_opt = df_recent[df_recent['Type'] == 'OPT'].copy()
        opt_months = df_opt[df_opt['Date'] == latest_date]['Month'].unique()
        front_2_opt = sorted(opt_months, key=get_month_score)[:2]
        df_opt_front = df_opt[df_opt['Month'].isin(front_2_opt)].copy()
        df_opt_front['Sett_PC'] = pd.to_numeric(df_opt_front['Sett_PC'], errors='coerce')

        return df_fut_front, front_2_fut, df_opt_front, front_2_opt
    except: return pd.DataFrame(), [], pd.DataFrame(), []

@st.cache_data(ttl=300)
def get_rut_master_data():
    try:
        url = "https://raw.githubusercontent.com/jianhuaa/fx-telegram-bot/refs/heads/main/russell_history.csv"
        df = pd.read_csv(url)
        df['Date'] = pd.to_datetime(df['Date'])
        recent_dates = sorted(df['Date'].unique(), reverse=True)[:5]
        df_recent = df[df['Date'].isin(recent_dates)].sort_values('Date')
        latest_date = df_recent['Date'].max()

        df_fut = df_recent[df_recent['Type'] == 'ALL'].copy()
        fut_months = df_fut[df_fut['Date'] == latest_date]['Month'].unique()
        front_2_fut = sorted(fut_months, key=get_month_score)[:2]
        df_fut_front = df_fut[df_fut['Month'].isin(front_2_fut)].copy()

        df_opt = df_recent[df_recent['Type'] == 'OPT'].copy()
        opt_months = df_opt[df_opt['Date'] == latest_date]['Month'].unique()
        front_2_opt = sorted(opt_months, key=get_month_score)[:2]
        df_opt_front = df_opt[df_opt['Month'].isin(front_2_opt)].copy()
        df_opt_front['Sett_PC'] = pd.to_numeric(df_opt_front['Sett_PC'], errors='coerce')

        return df_fut_front, front_2_fut, df_opt_front, front_2_opt
    except: return pd.DataFrame(), [], pd.DataFrame(), []

@st.cache_data(ttl=60)
def get_industry_table_data():
    try:
        def process_sheet(url, cap_label, start_row):
            res = requests.get(url)
            lines = res.text.splitlines()
            h_idx = next((i for i, l in enumerate(lines) if 'Symbol' in l), 0)
            df = pd.read_csv(io.StringIO("\n".join(lines[h_idx:])))
            df.columns = df.columns.astype(str).str.strip()

            def parse_date(d):
                formats = ['%d %b %y', '%d %b %Y', '%Y-%m-%d', '%m/%d/%Y', '%d/%m/%Y', '%d-%b-%y', '%d-%b-%Y', '%b %d, %Y']
                for fmt in formats:
                    try: return datetime.datetime.strptime(d.strip(), fmt)
                    except: pass
                return None

            dated_cols = sorted([(c, parse_date(c)) for c in df.columns if parse_date(c)], key=lambda x: x[1], reverse=True)
            if not dated_cols: return pd.DataFrame()

            def clean_col(col_name):
                if col_name not in df.columns: return pd.Series([float('nan')]*len(df))
                s = df[col_name].astype(str)
                s = s.str.replace(r'[^0-9\.\-]', '', regex=True)
                s = s.replace('', float('nan'))
                return pd.to_numeric(s, errors='coerce')

            c_curr = 'Live' if 'Live' in df.columns else dated_cols[0][0]
            curr_vals = clean_col(c_curr)

            if curr_vals.isna().sum() > (len(curr_vals) * 0.5):
                for d_col, d_obj in dated_cols:
                    c_curr = d_col
                    curr_vals = clean_col(c_curr)
                    if curr_vals.isna().sum() <= (len(curr_vals) * 0.5):
                        break

            anchor = parse_date(c_curr) if c_curr != 'Live' else dated_cols[0][1]
            if not anchor: anchor = dated_cols[0][1]

            def get_closest(days):
                t = anchor - datetime.timedelta(days=days)
                diffs = [(c[0], abs((c[1] - t).days)) for c in dated_cols]
                valid = [d for d in diffs if d[1] <= 7]
                if not valid: return None
                valid.sort(key=lambda x: x[1])
                return valid[0][0]

            c_1d = get_closest(1)
            c_1w = get_closest(7)
            c_1m = get_closest(30)
            c_3m = get_closest(91)
            c_1y = get_closest(365)

            df['1D_raw'] = (curr_vals / clean_col(c_1d) - 1) * 100 if c_1d else float('nan')
            df['1W_raw'] = (curr_vals / clean_col(c_1w) - 1) * 100 if c_1w else float('nan')
            df['1M_raw'] = (curr_vals / clean_col(c_1m) - 1) * 100 if c_1m else float('nan')
            df['3M_raw'] = (curr_vals / clean_col(c_3m) - 1) * 100 if c_3m else float('nan')
            df['1Y_raw'] = (curr_vals / clean_col(c_1y) - 1) * 100 if c_1y else float('nan')

            skip_rows = max(0, (start_row - 1) - h_idx - 1)
            stock_df = df.iloc[skip_rows:].copy().reset_index(drop=True)

            def map_sec(x):
                x_str = str(x).strip().upper()
                sec_map_inv = {
                    "COMMUNICATION": "XLC", "DISCRETIONARY": "XLY", "STAPLES": "XLP",
                    "ENERGY": "XLE", "FINANCIAL": "XLF", "HEALTH": "XLV", "INDUSTRIAL": "XLI",
                    "TECHNOLOGY": "XLK", "MATERIALS": "XLB", "REAL ESTATE": "XLRE", "UTILITIES": "XLU"
                }
                if x_str in sec_map_inv.values(): return x_str
                for k, v in sec_map_inv.items():
                    if k in x_str: return v
                return None

            stock_df['ETF'] = stock_df[stock_df.columns[2]].apply(map_sec)
            stock_df = stock_df.dropna(subset=['ETF'])

            def format_ind(x):
                val = str(x).strip()
                if not val or val.lower() in ['nan', 'none', 'n/a']: return 'UNKNOWN'
                return "<br>".join(textwrap.wrap(val, width=18))

            stock_df['IND_A'] = stock_df[stock_df.columns[3]].apply(format_ind)
            stock_df['Cap'] = cap_label
            return stock_df[['ETF', 'IND_A', 'Cap', '1D_raw', '1W_raw', '1M_raw', '3M_raw', '1Y_raw', 'Symbol']]

        spx_url = "https://docs.google.com/spreadsheets/d/e/2PACX-1vSpFLwMNa0AUsSC62LQZCQfIvvXRPPmX00cY7DO2sbiHu47Z72aJ_R-F_IrILBbKqIZGdSFgXFUrZyJ/pub?gid=0&single=true&output=csv"
        rmc_url = "https://docs.google.com/spreadsheets/d/e/2PACX-1vSpFLwMNa0AUsSC62LQZCQfIvvXRPPmX00cY7DO2sbiHu47Z72aJ_R-F_IrILBbKqIZGdSFgXFUrZyJ/pub?gid=679638722&single=true&output=csv"
        rut_url = "https://docs.google.com/spreadsheets/d/e/2PACX-1vRrTpcehWaL1Aq-uTn986nie8Hwrs_uHUOYr-E_wCG0jtLKQjvpw0V8x1wVz8yJdxFhqr7mz07jjpkM/pub?gid=0&single=true&output=csv"

        df_l = process_sheet(spx_url, 'L', 39)
        df_m = process_sheet(rmc_url, 'M', 4)
        df_s = process_sheet(rut_url, 'S', 4)

        df_all = pd.concat([df_l, df_m, df_s], ignore_index=True)
        res = df_all.groupby(['ETF', 'IND_A', 'Cap']).agg({'1D_raw':'mean', '1W_raw':'mean', '1M_raw':'mean', '3M_raw':'mean', '1Y_raw':'mean', 'Symbol':'count'}).reset_index()
        res.rename(columns={'Symbol': 'N'}, inplace=True)
        return res

    except Exception as e:
        print(f"Industry Table Error: {e}")
        return pd.DataFrame()

def load_vix_data():
    try:
        vix_df = yf.download("^VIX", period="1mo", progress=False, interval="1d", auto_adjust=True)
        if isinstance(vix_df.columns, pd.MultiIndex): vix_df.columns = vix_df.columns.get_level_values(0)
        vix_spot = float(vix_df['Close'].iloc[-1])
    except: vix_spot = 0.0

    month_codes = {1:'F', 2:'G', 3:'H', 4:'J', 5:'K', 6:'M', 7:'N', 8:'Q', 9:'U', 10:'V', 11:'X', 12:'Z'}
    today = datetime.datetime.now(pytz.timezone('US/Eastern')).date()
    futures_data = []
    for i in range(12):
        m, y = (today.month + i) % 12 or 12, today.year + (today.month + i - 1) // 12
        if today > get_vix_expiration(y, m): continue
        try:
            f_df = yf.download(f"^UZ{month_codes[m]}", period="1mo", progress=False, interval="1d", auto_adjust=True)
            if isinstance(f_df.columns, pd.MultiIndex): f_df.columns = f_df.columns.get_level_values(0)
            val = float(f_df['Close'].iloc[-1])
            if val > 0: futures_data.append(val)
        except: pass
        if len(futures_data) == 4: break
    return futures_data, vix_spot

def format_k(val):
    try:
        v = float(val)
        abs_v = abs(v)
        sign = "-" if v < 0 else ""
        if abs_v >= 100000: return f"{sign}{int(abs_v/1000)}k"
        elif abs_v >= 10000: return f"{sign}{abs_v/1000:.1f}k"
        elif abs_v >= 1000: return f"{sign}{abs_v/1000:.2f}k"
        else: return f"{sign}{int(abs_v)}"
    except: return str(val)

@st.cache_data(ttl=3600)
def get_all_insider_trades():
    try:
        GITHUB_RAW_URL = "https://raw.githubusercontent.com/jianhuaa/fx-telegram-bot/main/col4_insider_trades.parquet"
        return pd.read_parquet(GITHUB_RAW_URL)
    except Exception as e:
        print(f"Error loading insider trades from GitHub: {e}")
        return pd.DataFrame()

def get_insider_trades(ticker):
    df_all = get_all_insider_trades()
    if not df_all.empty and 'Ticker' in df_all.columns:
        # Filter the master dataframe for the specific ticker and return ALL records
        return df_all[df_all['Ticker'] == ticker]
    return pd.DataFrame()

@st.cache_data(ttl=3600)
@st.cache_data(ttl=3600)
def get_verified_fsli_data(ticker):
    # --- 1. Dynamic Ticker Translation ---
    tv_ticker = ticker.replace('-', '.') # TradingView expects BRK.B
    yf_ticker = ticker.replace('.', '-') # YFinance expects BRK-B

    field_mapping = {
        'Earnings Date': 'earnings_release_trading_date_fq',
        'Last Price': 'close',
        'Short Interest %': None,
        '1Y%': None,
        'Mkt Cap (M)': 'market_cap_basic',
        'P/E Ratio': 'price_earnings_ttm',
        'Revenue (M)': 'total_revenue_ttm',
        'Op CF (M)': 'cash_f_operating_activities_ttm',
        'FCF (M)': 'free_cash_flow_fy',
        'Inv CF (M)': 'cash_f_investing_activities_ttm',
        'Fin CF (M)': 'cash_f_financing_activities_ttm',
        'Cash & STI (M)': 'cash_n_short_term_invest_fq',
        'ST Debt (M)': 'short_term_debt_fq',
        'LT Debt (M)': 'long_term_debt_fq',
        'Total Debt (M)': 'total_debt_fq',
        'Gross Marg %': 'gross_margin_ttm',
        'Op Marg %': 'operating_margin_ttm',
        'Net Marg %': 'net_margin_ttm'
    }

    tv_fields = ['name', 'close', 'cash_n_equivalents_fq', 'gross_margin_fy'] + [v for v in field_mapping.values() if v is not None and v != 'close']
    tv_fields = list(set(tv_fields)) 
    
    try:
        # 2. TradingView Fetch (Using tv_ticker)
        query = Query().select(*tv_fields).where(col('name') == tv_ticker)
        num_rows, df = query.get_scanner_data()
        
        last_price = None
        if num_rows > 0:
            last_price = float(df['close'].values[0])
            
        # 3. YFinance Fetch: 1Y% (Isolated Try/Except using yf_ticker)
        one_y_val = None
        try:
            hist_raw = yf.download(yf_ticker, period='1y', interval='1d', progress=False, auto_adjust=True)
            if not hist_raw.empty and last_price is not None:
                cl = (hist_raw['Close'][yf_ticker] if isinstance(hist_raw.columns, pd.MultiIndex) else hist_raw['Close']).dropna()
                if not cl.empty: 
                    one_y_val = (cl.values <= last_price).mean() * 100
        except Exception as e:
            print(f"[1Y% YFinance Error] {yf_ticker}: {e}")

        # 4. YFinance Fetch: Short Interest (Isolated Try/Except using yf_ticker)
        short_interest_val = None
        try:
            tkr = yf.Ticker(yf_ticker)
            si_raw = tkr.info.get('shortPercentOfFloat')
            if si_raw is not None:
                short_interest_val = si_raw * 100
        except:
            pass

        # 5. YahooQuery Fallback for Short Interest
        if short_interest_val is None:
            try:
                yq = YQTicker(yf_ticker)
                stats = yq.get_modules('defaultKeyStatistics').get(yf_ticker, {})
                if isinstance(stats, dict):
                    short_interest_val = (stats.get('sharesShort', 0) / stats.get('sharesOutstanding', 1) * 100) if stats.get('sharesOutstanding') else None
            except:
                pass

        # 6. Compile Results
        res = {}
        for display_name, raw_key in field_mapping.items():
            if display_name == '1Y%':
                val = one_y_val
            elif display_name == 'Short Interest %':
                val = short_interest_val
            elif display_name == 'Last Price':
                val = last_price
            else:
                if num_rows > 0 and raw_key in df.columns:
                    val = df[raw_key].values[0]
                    if pd.isna(val):
                        if display_name == 'Cash & STI (M)' and 'cash_n_equivalents_fq' in df.columns:
                            val = df['cash_n_equivalents_fq'].values[0]
                        elif display_name == 'Gross Marg %' and 'gross_margin_fy' in df.columns:
                            val = df['gross_margin_fy'].values[0]
                else:
                    val = None

            if pd.isna(val) or val is None: 
                res[display_name] = "--"
            elif 'Earnings Date' in display_name: 
                res[display_name] = datetime.datetime.fromtimestamp(val).strftime('%y-%m-%d')
            elif '%' in display_name: 
                res[display_name] = f"{val:.2f}%"
            elif 'Price' in display_name: 
                res[display_name] = f"${val:,.2f}"
            elif display_name in ['P/E Ratio']: 
                res[display_name] = f"{val:,.2f}"
            else: 
                res[display_name] = f"${val / 1_000_000:,.0f}"
                
        return res

    except Exception as e:
        print(f"[CRITICAL FSLI ERROR] Failed to build FSLI for {ticker}. Reason: {str(e)}")
        return {m: "--" for m in field_mapping}
        
@st.cache_data(ttl=3600)
def get_dynamic_options_data(ticker):
    from dateutil.relativedelta import relativedelta
    import yfinance as yf
    import datetime

    now = datetime.datetime.now()
    m1_str = now.strftime("%Y-%m")
    m2_str = (now + relativedelta(months=1)).strftime("%Y-%m")

    try:
        tkr = yf.Ticker(ticker)
        expirations = tkr.options
        if not expirations: return None

        stats = {"M1_Call_Vol": 0, "M1_Put_Vol": 0, "M2_Call_Vol": 0, "M2_Put_Vol": 0}

        found_any = False
        for date in expirations:
            target = None
            if date.startswith(m1_str): target = "M1"
            elif date.startswith(m2_str): target = "M2"

            if target:
                chain = tkr.option_chain(date)
                stats[f"{target}_Call_Vol"] += chain.calls['openInterest'].fillna(0).sum()
                stats[f"{target}_Put_Vol"] += chain.puts['openInterest'].fillna(0).sum()
                found_any = True

        if not found_any: return None

        m1_name = datetime.datetime.strptime(m1_str, "%Y-%m").strftime("%b%y").upper()
        m2_name = datetime.datetime.strptime(m2_str, "%Y-%m").strftime("%b%y").upper()

        m1_sigma = stats["M1_Call_Vol"] - stats["M1_Put_Vol"]
        m1_delta = 0
        m1_pc = stats["M1_Put_Vol"] / stats["M1_Call_Vol"] if stats["M1_Call_Vol"] > 0 else 0
        m2_sigma = stats["M2_Call_Vol"] - stats["M2_Put_Vol"]
        m2_delta = 0
        m2_pc = stats["M2_Put_Vol"] / stats["M2_Call_Vol"] if stats["M2_Call_Vol"] > 0 else 0

        return {
            "m1_name": m1_name, "m1_sigma": m1_sigma, "m1_delta": m1_delta, "m1_pc": m1_pc,
            "m2_name": m2_name, "m2_sigma": m2_sigma, "m2_delta": m2_delta, "m2_pc": m2_pc
        }
    except Exception:
        return None

@st.cache_data(ttl=60)
def get_live_col4_data():
    try:
        try: df_all_ret = pd.read_parquet('col4_all_returns.parquet')
        except: df_all_ret = pd.DataFrame()

        base_url = "https://raw.githubusercontent.com/jianhuaa/fx-telegram-bot/main/"
        def safe_read_remote(fname):
            try:
                import requests, io
                res = requests.get(base_url + fname)
                if res.status_code == 200: return pd.read_parquet(io.BytesIO(res.content))
            except: pass
            try: return pd.read_parquet(fname)
            except: return pd.DataFrame()

        df_sec         = safe_read_remote('col4_sec.parquet')
        df_transcripts = safe_read_remote('col4_transcripts.parquet')

        return df_sec, df_transcripts, df_all_ret
    except: return pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

# ---------------------------------------------------------
# DIALOG 1: SUMMARY / TICKERS PLACEHOLDER
# ---------------------------------------------------------

@st.dialog("\u200B", width="large")
def show_summary_overlay(default_tf, default_sec, df_all_ret):
    st.markdown("<h4 style='color:#00aaff; margin-top:-15px;'>📊 Market Brief</h4>", unsafe_allow_html=True)

    # --- 1. LOCAL CONTROLS ---
    c_ctrl1, c_ctrl2, c_ctrl3, c_ctrl4 = st.columns([0.08, 0.15, 0.37, 0.40])

    with c_ctrl1:
        local_tf = st.selectbox("Tenor", ["1D", "1W", "1M", "3M", "1Y"], index=["1D", "1W", "1M", "3M", "1Y"].index(default_tf), label_visibility="collapsed")

    with c_ctrl2:
        sector_display_map = {
            'XLB': 'XLB (Materials)', 'XLC': 'XLC (Comm Svcs)', 'XLE': 'XLE (Energy)',
            'XLF': 'XLF (Financials)', 'XLI': 'XLI (Industrials)', 'XLK': 'XLK (Tech)',
            'XLP': 'XLP (Cons Staples)', 'XLRE': 'XLRE (Real Est)', 'XLU': 'XLU (Utilities)',
            'XLV': 'XLV (Health)', 'XLY': 'XLY (Cons Disc)'
        }
        sorted_keys = sorted(sector_display_map.keys())
        display_options = [sector_display_map[k] for k in sorted_keys]
        default_idx = sorted_keys.index(default_sec) if default_sec in sorted_keys else 3

        selected_display = st.selectbox("Sector Focus", display_options, index=default_idx, label_visibility="collapsed")
        local_sec = selected_display.split(' ')[0]

    with c_ctrl3:
        inds = sorted(df_all_ret[df_all_ret['Sector'] == local_sec]['Industry'].dropna().unique()) if not df_all_ret.empty else ["Unknown"]
        local_ind = st.selectbox("Industry Focus", inds, label_visibility="collapsed")

    with c_ctrl4:
        if st.button(f"🔭 Explore {local_sec}: {local_ind}", use_container_width=True):
            st.session_state['trigger_industry_dialog'] = True
            st.session_state['passed_sector'] = local_sec
            st.session_state['passed_industry'] = local_ind
            st.rerun()

    with st.spinner("Loading timeframe data..."):
        df_history, df_pct = get_historical_charts_data(local_tf)
        df_sectors_price, df_sectors_pct = get_sector_data(local_tf)
        df_inds = get_industry_table_data()

        dialog_x_axis = dict(showgrid=False)

        if not df_history.empty:
            fmt_d = "%d %b %H:%M" if local_tf in ["1D", "1W", "1M"] else "%d %b '%y"
            for df in [df_history, df_pct, df_sectors_price, df_sectors_pct]:
                if isinstance(df.index, pd.DatetimeIndex):
                    if getattr(df.index, 'tzinfo', None) is not None:
                        df.index = df.index.tz_convert('America/New_York')
                    df.index = df.index.strftime(fmt_d)

            last_date_d = df_history.index[-1]
            tick_map_d = {"1D": 4, "1W": 5, "1M": 5, "3M": 5, "1Y": 5}
            n_ticks_d = tick_map_d.get(local_tf, 5)

            total_pts_d = len(df_history)
            step_d = max(1, (total_pts_d - 1) // (n_ticks_d - 1)) if total_pts_d > 1 else 1
            t_vals_d = [df_history.index[i] for i in range(0, total_pts_d, step_d)]

            if t_vals_d[-1] != last_date_d:
                t_vals_d[-1] = last_date_d

            t_text_d = t_vals_d if local_tf == "1D" else [str(v).rsplit(' ', 1)[0] if ':' in str(v) else v for v in t_vals_d]
            dialog_x_axis = dict(showgrid=False, type='category', categoryorder='trace', tickmode='array', tickvals=t_vals_d, ticktext=t_text_d)

    st.markdown("<hr style='margin:10px 0; border-color:#333;'><div style='height: 10px;'></div>", unsafe_allow_html=True)

    # --- MASTER LAYOUT SPLIT ---
    col_left, col_right = st.columns([0.66, 0.34], gap="medium")

    with col_left:
        # --- ROW 1 (Left Side): Line Charts ---
        c1, c2 = st.columns(2)

        with c1:
            f1 = go.Figure()
            if not df_pct.empty and 'SPX' in df_pct and 'RUT' in df_pct:
                f1.add_trace(go.Scatter(x=df_pct.index, y=df_pct['SPX'], name='SPX', line=dict(color='#00aaff')))
                f1.add_trace(go.Scatter(x=df_pct.index, y=df_pct['RUT'], name='RTY', line=dict(color='#ab63fa')))

                spx_val, spx_pct = df_history['SPX'].iloc[-1], df_pct['SPX'].iloc[-1]
                rut_val, rut_pct = df_history['RUT'].iloc[-1], df_pct['RUT'].iloc[-1]
                s_shift, r_shift = (18, -18) if spx_pct >= rut_pct else (-18, 18)

                f1.add_annotation(x=last_date_d, y=spx_pct, text=f"{spx_val:.0f} ({spx_pct:+.1f}%)", showarrow=False, xanchor='right', xshift=-5, yshift=s_shift, font=dict(size=11, color="white"), bgcolor="rgba(0,0,0,0.8)", bordercolor="#00aaff", borderwidth=1, borderpad=3)
                f1.add_annotation(x=last_date_d, y=rut_pct, text=f"{rut_val:.0f} ({rut_pct:+.1f}%)", showarrow=False, xanchor='right', xshift=-5, yshift=r_shift, font=dict(size=11, color="white"), bgcolor="rgba(0,0,0,0.8)", bordercolor="#ab63fa", borderwidth=1, borderpad=3)

                f1.update_layout(
                    title=dict(text=f"SPX vs RTY ({local_tf})", x=0.0, y=0.99, yref="container", xanchor="left", yanchor="top", font=dict(size=14, color="white")),
                    xaxis=dialog_x_axis,
                    yaxis=dict(showgrid=False, ticksuffix="%"),
                    legend=dict(orientation="h", yanchor="bottom", y=1.06, xanchor="left", x=0.0, bgcolor="rgba(0,0,0,0)", font=dict(size=12)),
                    margin=dict(l=0,r=0,t=70,b=0),
                    height=300
                )
            st.plotly_chart(f1, use_container_width=True)

        with c2:
            f2 = go.Figure()
            if not df_sectors_pct.empty and not df_pct.empty:
                f2.add_trace(go.Scatter(x=df_pct.index, y=df_pct['SPX'], name='SPX', line=dict(color='white', width=3)))
                for col in df_sectors_pct.columns:
                    is_visible = True if col == local_sec else 'legendonly'
                    f2.add_trace(go.Scatter(x=df_sectors_pct.index, y=df_sectors_pct[col], name=col, visible=is_visible))

                spx_pct = df_pct['SPX'].iloc[-1]
                sec_val, sec_pct = df_sectors_price[local_sec].iloc[-1], df_sectors_pct[local_sec].iloc[-1]
                s_shift, sec_shift = (18, -18) if spx_pct >= sec_pct else (-18, 18)

                f2.add_annotation(x=last_date_d, y=spx_pct, text=f"SPX ({spx_pct:+.1f}%)", showarrow=False, xanchor='right', xshift=-5, yshift=s_shift, font=dict(size=11, color="white"), bgcolor="rgba(0,0,0,0.8)", bordercolor="white", borderwidth=1, borderpad=3)
                f2.add_annotation(x=last_date_d, y=sec_pct, text=f"{sec_val:.2f} ({sec_pct:+.1f}%)", showarrow=False, xanchor='right', xshift=-5, yshift=sec_shift, font=dict(size=11, color="white"), bgcolor="rgba(0,0,0,0.8)", bordercolor="#f4ca16", borderwidth=1, borderpad=3)

                f2.update_layout(
                    title=dict(text="SPX vs Sectors", x=0.0, y=0.99, yref="container", xanchor="left", yanchor="top", font=dict(size=14, color="white")),
                    xaxis=dialog_x_axis,
                    yaxis=dict(showgrid=False, ticksuffix="%"),
                    legend=dict(orientation="h", yanchor="bottom", y=0.95, xanchor="left", x=0.0, bgcolor="rgba(0,0,0,0)", font=dict(size=10), itemwidth=30),
                    margin=dict(l=0,r=0,t=70,b=0),
                    height=300
                )
            st.plotly_chart(f2, use_container_width=True)

        st.markdown("<hr style='margin:10px 0; border-color:#333;'>", unsafe_allow_html=True)

        # --- ROW 2 (Left Side): Tables ---
        t1, t2 = st.tabs(["🔴 Worst Sectors/Industries", "🔴 Worst Tickers"])

        mixed_data = []
        for idx_name in ['SPX', 'RUT']:
            row = {'Type': 'Index', 'Index': idx_name, 'Sector': '-', 'Industry': '-'}
            for t in ['1D', '1W', '1M', '3M', '1Y']:
                _, tf_p = get_historical_charts_data(t)
                row[f'{t}%'] = float(tf_p[idx_name].iloc[-1]) if (not tf_p.empty and idx_name in tf_p.columns) else float('nan')
            mixed_data.append(row)

        for sec_name in sorted_keys: # FIXED: Changed from sector_options to sorted_keys
            row = {'Type': 'Sector', 'Index': 'SPX', 'Sector': sec_name, 'Industry': '-'}
            for t in ['1D', '1W', '1M', '3M', '1Y']:
                _, tf_sec_pct = get_sector_data(t)
                row[f'{t}%'] = float(tf_sec_pct[sec_name].iloc[-1]) if (not tf_sec_pct.empty and sec_name in tf_sec_pct.columns) else float('nan')
            mixed_data.append(row)

        if not df_inds.empty:
            df_inds_filtered = df_inds[df_inds['ETF'] == local_sec]
            for _, row_ind in df_inds_filtered.iterrows():
                # Map the Cap letter back to a readable Index name for the table
                idx_map = {'L': 'SPX', 'M': 'RMC', 'S': 'RTY'}

                mixed_data.append({
                    'Type': 'Industry',
                    'Index': idx_map.get(row_ind['Cap'], row_ind['Cap']),
                    'Sector': row_ind['ETF'],
                    'Industry': str(row_ind['IND_A']).replace('<br>', ' '),
                    'Count': int(row_ind['N']), # <--- ADD THIS LINE
                    '1D%': float(row_ind['1D_raw']) if pd.notna(row_ind.get('1D_raw')) else float('nan'),
                    '1W%': float(row_ind['1W_raw']) if pd.notna(row_ind.get('1W_raw')) else float('nan'),
                    '1M%': float(row_ind['1M_raw']) if pd.notna(row_ind.get('1M_raw')) else float('nan'),
                    '3M%': float(row_ind['3M_raw']) if pd.notna(row_ind.get('3M_raw')) else float('nan'),
                    '1Y%': float(row_ind['1Y_raw']) if pd.notna(row_ind.get('1Y_raw')) else float('nan')
                })

        df_mixed = pd.DataFrame(mixed_data)
        sort_col_mixed = f"{local_tf}%"

        def style_mixed_table(row):
            if row['Type'] == 'Index': return ['background-color: #1a2a3a; color: #00aaff'] * len(row)
            if row['Type'] == 'Sector': return ['background-color: #3a2a1a; color: #f4ca16'] * len(row)
            return ['background-color: #0d0d0d; color: white'] * len(row)

        def f_pct(x): return f"{x:+.1f}%" if pd.notna(x) else "-"

        with t1:
            if not df_mixed.empty and sort_col_mixed in df_mixed.columns:
                df_m_sorted = df_mixed.dropna(subset=[sort_col_mixed]).sort_values(sort_col_mixed, ascending=True)

                st.dataframe(
                    df_m_sorted.style.apply(style_mixed_table, axis=1).format(f_pct, subset=['1D%', '1W%', '1M%', '3M%', '1Y%']),
                    hide_index=True,
                    use_container_width=True,
                    column_order=['Index', 'Sector', 'Industry', 'Count', '1D%', '1W%', '1M%', '3M%', '1Y%'],
                    height=275,
                    # We define column_config to fix widths and the integer formatting
                    column_config={
                        "Index": st.column_config.TextColumn(width=40),
                        "Sector": st.column_config.TextColumn(width=40),
                        "Industry": st.column_config.TextColumn(width=290),
                        "Count": st.column_config.NumberColumn(
                            "Count",
                            width=35,
                            format="%d"  # This removes the 6 decimal places (0 dp)
                        ),
                        "1D%": st.column_config.TextColumn(width=55),
                        "1W%": st.column_config.TextColumn(width=55),
                        "1M%": st.column_config.TextColumn(width=60),
                        "3M%": st.column_config.TextColumn(width=60),
                        "1Y%": st.column_config.TextColumn(width=60),
                    }
                )
            else:
                st.info("Loading table data...")

        with t2:
            if not df_all_ret.empty:
                df_t = df_all_ret.copy().rename(columns={'1D_raw':'1D%', '1W_raw':'1W%', '1M_raw':'1M%', '3M_raw':'3M%', '1Y_raw':'1Y%'})
                df_t = df_t[df_t['Sector'] == local_sec]
                if local_ind != "Unknown":
                    df_t = df_t[df_t['Industry'] == local_ind]

                if sort_col_mixed in df_t.columns and not df_t.empty:
                    df_t_sorted = df_t.dropna(subset=[sort_col_mixed]).sort_values(sort_col_mixed, ascending=True).head(50)
                    st.dataframe(
                      df_t_sorted[['Ticker', 'Index', 'Sector', 'Industry', '1D%', '1W%', '1M%', '3M%', '1Y%']].style.format(f_pct, subset=['1D%', '1W%', '1M%', '3M%', '1Y%']),
                      hide_index=True,
                      use_container_width=True,
                      height=275,
                      # We define column_config to fix widths and the integer formatting
                      column_config={
                        "Ticker": st.column_config.TextColumn(width=40),
                        "Index": st.column_config.TextColumn(width=40),
                        "Sector": st.column_config.TextColumn(width=40),
                        "Industry": st.column_config.TextColumn(width=290),
                        "1D%": st.column_config.TextColumn(width=55),
                        "1W%": st.column_config.TextColumn(width=55),
                        "1M%": st.column_config.TextColumn(width=55),
                        "3M%": st.column_config.TextColumn(width=60),
                        "1Y%": st.column_config.TextColumn(width=60),
                     })
                else:
                    st.info("No ticker data found for this selection.")

    with col_right:
        # --- ENTIRE RIGHT COLUMN (Column 3): Industry Bar Chart ---
        f3 = go.Figure()
        sort_col = f"{local_tf}_raw"

        has_data = False
        # 1. Calculate Benchmarks first so they are DEFINED for the lines later
        spx_ret = df_pct['SPX'].iloc[-1] if (not df_pct.empty and 'SPX' in df_pct.columns) else 0
        sec_ret = df_sectors_pct[local_sec].iloc[-1] if (not df_sectors_pct.empty and local_sec in df_sectors_pct.columns) else 0

        if not df_inds.empty and sort_col in df_inds.columns:
            # 2. Filter for the Sector
            ind_sub_raw = df_inds[df_inds['ETF'] == local_sec].copy()

            if not ind_sub_raw.empty:
                # 3. STRATEGIC GROUPING: Collapse L/M/S into one bar per Industry for the Visual
                ind_sub = ind_sub_raw.groupby('IND_A')[sort_col].mean().reset_index().sort_values(sort_col)

                if not ind_sub.empty:
                    has_data = True
                    #y_labels = ind_sub['IND_A'].str.replace('<br>', ' ').tolist()
                    # WORD WRAP LOGIC: If label has more than 2 spaces, wrap it
                    y_labels_raw = ind_sub['IND_A'].str.replace('<br>', ' ').tolist()
                    y_labels = [
                        "<br>".join(textwrap.wrap(label, width=20)) if label.count(' ') >= 2 else label
                        for label in y_labels_raw
                    ]
                    x_vals = ind_sub[sort_col].tolist()

                    # --- CALC DYNAMIC RANGE BUFFER ---
                    # We find the widest point (abs) to determine how much padding to add
                    all_vals = x_vals + [spx_ret, sec_ret, 0]
                    v_min, v_max = min(all_vals), max(all_vals)
                    v_range = v_max - v_min

                    # By adding 30% padding on each side, the bars "shrink" relative to the total width
                    padding = v_range * 0.30 if v_range > 0 else 2.0

                    max_abs = max(abs(v) for v in all_vals)
                    # Padding based on scale: 40% extra space usually fits the % labels
                    x_padding = max_abs * 0.40 if max_abs > 0 else 1.0

                    f3.add_trace(go.Bar(
                        x=x_vals,
                        y=y_labels,
                        orientation='h',
                        marker_color='#555555',
                        text=[f"{v:+.1f}%" for v in x_vals],
                        hoverinfo='x+y',
                        textposition='none',
                        # Ensures the font stays white and readable outside the bar
                        # textfont=dict(size=12, color="white"),
                        # cliponaxis=False # This prevents the 'clipped' look at the edges
                    ))

                    # 2. Add custom annotations to the RIGHT of the zero line for consistency
                    # This ensures negative numbers don't disappear to the left
                    for y, x in zip(y_labels, x_vals):
                        f3.add_annotation(
                            x=max(0, x) + (max(x_vals)*0.05), # Always stays on the positive side or at the tip
                            y=y,
                            text=f"{x:+.1f}%",
                            showarrow=False,
                            # Shift label to avoid overlapping the bar itself
                            xanchor='left' if x >= 0 else 'right',
                            xshift=8 if x >= 0 else -8,
                            font=dict(size=12, color="white"),
                            bgcolor="rgba(20, 20, 20, 0.85)", # Dark translucent box
                            bordercolor="#555",
                            borderwidth=1,
                            borderpad=3
                        )

                    # Blue line at the top
                    f3.add_vline(x=spx_ret, line_dash="dot", line_color="#00aaff",
                                 annotation_text=f"SPX ({spx_ret:+.1f}%)",
                                 annotation_position="top right",
                                 # Changed color to white and added bold tag in text for maximum contrast
                                 annotation_font=dict(color="white", size=13),
                                 annotation_bgcolor="rgba(0, 100, 200, 0.9)", # Deeper blue for better text "pop"
                                 annotation_bordercolor="#00aaff",
                                 annotation_borderwidth=2,
                                 annotation_borderpad=6,
                                 annotation_y=1.08)

                    # Yellow line at the bottom
                    f3.add_vline(x=sec_ret, line_dash="dash", line_color="#f4ca16",
                                 annotation_text=f"{local_sec} ({sec_ret:+.1f}%)",
                                 annotation_position="bottom right",
                                 # Changed color to white for clarity against the yellow box
                                 annotation_font=dict(color="white", size=13),
                                 annotation_bgcolor="rgba(180, 140, 0, 0.9)", # Darker gold/mustard for white text legibility
                                 annotation_bordercolor="#f4ca16",
                                 annotation_borderwidth=2,
                                 annotation_borderpad=6,
                                 annotation_y=-0.08)

        if not has_data:
            f3.add_annotation(text=f"No industry data for {local_sec} ({local_tf})", xref="paper", yref="paper", x=0.5, y=0.5, showarrow=False, font=dict(color="#888", size=12))

        # --- Edit B: The Layout Buffer ---
        # Calculate a 20% margin so 'outside' text has a landing pad
        xmin = min(x_vals + [spx_ret, sec_ret]) * 1.2
        xmax = max(x_vals + [spx_ret, sec_ret]) * 1.2

        f3.update_layout(
            title=dict(text=f"{local_sec} Industries (Avg)", x=0.0, y=0.99, yref="container", xanchor="left", yanchor="top", font=dict(size=14, color="white")),
            xaxis=dict(
                        #range=[min(x_vals + [0, spx_ret, sec_ret]) * 1.1, max(x_vals + [0, spx_ret, sec_ret]) * 1.3],
                        #range=[min(all_vals) - x_padding, max(all_vals) + x_padding],
                        range=[v_min - padding, v_max + padding], # This creates the "shrink" effect
                        showgrid=False,
                        ticksuffix="%",
                        zeroline=True,
                        zerolinecolor='white',
                        # Move the X-axis labels (0%, 5%, etc) further down
                        ticklabelstandoff=40,
                        side="bottom"
                    ),
            #yaxis=dict(showgrid=False, tickfont=dict(size=12), zeroline=False, visible=has_data),
            #margin=dict(l=0,r=0,t=40,b=0),
            # Reversing Y-axis makes sure the top item isn't buried behind the SPX title
            yaxis=dict(showgrid=False, tickfont=dict(size=11), domain=[0.15, 1.0] if has_data else True),
            # INCREASED TOP AND BOTTOM MARGINS (t=70, b=50) to make room for boxes
            margin=dict(l=0, r=10, t=85, b=20),
            height=640,
            showlegend=False,
            plot_bgcolor="rgba(0,0,0,0)",
            paper_bgcolor="rgba(0,0,0,0)"
        )
        st.plotly_chart(f3, use_container_width=True)

# ---------------------------------------------------------
# DIALOG 2: INDUSTRY OVERVIEW (Macro/Micro + Master Ticker Hub)
# ---------------------------------------------------------
@st.dialog("\u200B\u200B", width="large")
def show_industry_overview_overlay(df_all_returns, df_industries, selected_sector_default, df_sec_live, df_transcripts_live, df_history, df_sectors_price, passed_industry_default=None):

    st.markdown("<div style='height: 8px;'></div>", unsafe_allow_html=True)

    sector_display_map = {
    'XLB': 'XLB (Materials)', 'XLC': 'XLC (Comm Svcs)', 'XLE': 'XLE (Energy)',
    'XLF': 'XLF (Financials)', 'XLI': 'XLI (Industrials)', 'XLK': 'XLK (Tech)',
    'XLP': 'XLP (Cons Staples)', 'XLRE': 'XLRE (Real Est)', 'XLU': 'XLU (Utilities)',
    'XLV': 'XLV (Health)', 'XLY': 'XLY (Cons Disc)'
    }

    # 1. Filter the available sectors from your data
    available_sectors = sorted(df_all_returns['Sector'].dropna().unique()) if not df_all_returns.empty else []

    # 2. Build display list (e.g. "XLE (Energy)") and find default index
    display_options = [sector_display_map.get(s, s) for s in available_sectors]
    default_idx = available_sectors.index(selected_sector_default) if selected_sector_default in available_sectors else 0

    c1, c2, c3 = st.columns([0.15, 0.30, 0.55], vertical_alignment="bottom")
    # Generate unique keys based on the incoming request so Streamlit doesn't use old memory
    dyn_sec_key = f"dlg_sec_{selected_sector_default}_{passed_industry_default}"
    dyn_ind_key = f"dlg_ind_{selected_sector_default}_{passed_industry_default}"
    with c1:
        selected_display = st.selectbox("Sector", display_options, index=default_idx, label_visibility="collapsed", key=dyn_sec_key)
        # Extract the ticker back for data filtering (e.g., 'XLE' from 'XLE (Energy)')
        sel_sec = selected_display.split(' ')[0]

    inds = sorted(df_all_returns[df_all_returns['Sector'] == sel_sec]['Industry'].dropna().unique()) if not df_all_returns.empty else []
    idx_ind = inds.index(passed_industry_default) if passed_industry_default in inds else 0
    with c2:
        if inds:
            sel_ind = st.selectbox("Industry", inds, index=idx_ind, label_visibility="collapsed", key=dyn_ind_key)
        else:
            sel_ind = st.selectbox("Industry", ["Unknown"], label_visibility="collapsed", key=dyn_ind_key)
        #sel_ind = st.selectbox("Industry", inds, index=idx_ind, label_visibility="collapsed") if inds else st.selectbox("Industry", ["Unknown"], label_visibility="collapsed")

    ind_df = df_all_returns[(df_all_returns['Sector'] == sel_sec) & (df_all_returns['Industry'] == sel_ind)].copy() if not df_all_returns.empty else pd.DataFrame()

    # Exclude macro ETFs from the Ticker Select dropdown
    ETF_EXCLUSIONS = ['XLF', 'KBE', 'KRE', 'XLE', 'XOP', 'OIH', 'XLK', 'SMH', 'IGV', 'XLV', 'XBI', 'IHE', 'XLY', 'XRT', 'XLI', 'JETS', 'IYT', 'XLB', 'XME', 'XLP', 'XLU', 'XLRE', 'XLC', 'SPY', 'QQQ', 'IWM']
    ind_df_clean = ind_df[~ind_df['Ticker'].isin(ETF_EXCLUSIONS)].copy() if not ind_df.empty else pd.DataFrame()

    if not ind_df_clean.empty:
        ind_df_clean['Label'] = ind_df_clean['Ticker'] + " (" + ind_df_clean['Index'] + ")"
        available_tickers = sorted(ind_df_clean['Label'].tolist())
    else: available_tickers = []

    with c3:
        selected_labels = st.multiselect(
            "Tickers", available_tickers,
            default=available_tickers[:3] if len(available_tickers) >= 3 else available_tickers,
            label_visibility="collapsed", placeholder="Select tickers for FSLI/Options..."
        )

    st.markdown("<hr style='margin:10px 0; border-color:#333;'>", unsafe_allow_html=True)

    FSLI_H = 680
    MACRO_H = 215
    INS_H  = 250

    left_col, right_col = st.columns([0.5, 0.5], gap="small")
    selected_tickers = [lbl.split(' ')[0] for lbl in selected_labels] if selected_labels else []

    # LEFT COLUMN: FSLI TABLE
    with left_col:
        st.markdown("<div style='text-align: left; margin-top: 15px; margin-bottom: -17px; position: relative; z-index: 50; padding-left: 5px; pointer-events: none;'><span style='color:#00aaff; font-weight:bold; font-size:12px;'>📊 FSLI Fundamentals</span></div>", unsafe_allow_html=True)

        if selected_tickers:
            metric_rows = None; cell_vals = []
            for ticker in selected_tickers:
                res = get_verified_fsli_data(ticker)
                if metric_rows is None: metric_rows = list(res.keys())
                cell_vals.append([res.get(m, "--") for m in metric_rows])

            final_cell_vals = [metric_rows] + cell_vals
            hdr_vals = ['<b>METRIC</b>'] + [f'<b>{t}</b>' for t in selected_tickers]
            col_widths = [100] + [75] * len(selected_tickers)

            fig_fsli = go.Figure(data=[go.Table(columnwidth=col_widths, header=dict(values=hdr_vals, fill_color='#161616', font=dict(color='#00aaff', size=11), align='left', height=24), cells=dict(values=final_cell_vals, fill_color='#0d0d0d', font=dict(color='white', size=11), align='left', height=26))])
            fig_fsli.update_layout(margin=dict(l=0, r=4, t=45, b=0), height=FSLI_H)
            st.plotly_chart(fig_fsli, use_container_width=True)
        else:
            st.markdown(f"<div style='height:{FSLI_H}px; display:flex; align-items:center; justify-content:center; color:#00aaff; font-size:12px; border:1px dashed #444; border-radius:4px;'>Select tickers from the dropdown to load FSLI</div>", unsafe_allow_html=True)

    # RIGHT COLUMN: MACRO/MICRO TABS & INSIDER/OPTIONS/SEC TABS
    with right_col:
        def get_pct_returns(df, col):
            if not df.empty and col in df.columns:
                try:
                    p_1d = round((df[col].iloc[-1] / df[col].iloc[-2] - 1) * 100, 2) if len(df) > 1 else 0.0
                    p_1w = round((df[col].iloc[-1] / df[col].iloc[-6] - 1) * 100, 2) if len(df) > 5 else 0.0
                    p_1m = round((df[col].iloc[-1] / df[col].iloc[-22] - 1) * 100, 2) if len(df) > 21 else 0.0
                    p_3m = round((df[col].iloc[-1] / df[col].iloc[-64] - 1) * 100, 2) if len(df) > 63 else 0.0
                    return [p_1d, p_1w, p_1m, p_3m]
                except: pass
            return [0.0, 0.0, 0.0, 0.0]

        spx_vals = get_pct_returns(df_history, 'SPX')
        rut_vals = get_pct_returns(df_history, 'RUT')
        sec_vals = get_pct_returns(df_sectors_price, sel_sec)

        clean_ind_df = df_industries.copy()
        match_df = pd.DataFrame()
        if not clean_ind_df.empty:
            clean_ind_df['Match_Str'] = clean_ind_df['IND_A'].str.replace('<br>', '', regex=False).str.replace(' ', '').str.lower()
            target_str = sel_ind.replace(' ', '').lower()
            clean_ind_df['Type'] = clean_ind_df['Cap'].map({'L': 'SPX', 'M': 'RMC', 'S': 'RTY'})
            match_df = clean_ind_df[(clean_ind_df['ETF'] == sel_sec) & (clean_ind_df['Match_Str'] == target_str)]
            if match_df.empty: match_df = clean_ind_df[(clean_ind_df['ETF'] == sel_sec) & (clean_ind_df['Match_Str'].str.contains(target_str[:5], na=False))]

        # TABS: TOP HALF
        t_mac, t_mic = st.tabs(["📊 Macro", "🔬 Micro"])

        with t_mac:
            st.markdown("<div style='text-align: right; margin-top: -17px; margin-bottom: 5px; position: relative; z-index: 50; padding-right: 5px; pointer-events: none;'><span style='color:#f4ca16; font-weight:bold; font-size:12px;'>📊 Macro Return</span></div>", unsafe_allow_html=True)
            macro_names = ['SPX', 'RTY', sel_sec]
            macro_1d = [f"{spx_vals[0]:+.2f}%", f"{rut_vals[0]:+.2f}%", f"{sec_vals[0]:+.2f}%"]
            macro_1w = [f"{spx_vals[1]:+.2f}%", f"{rut_vals[1]:+.2f}%", f"{sec_vals[1]:+.2f}%"]
            macro_1m = [f"{spx_vals[2]:+.2f}%", f"{rut_vals[2]:+.2f}%", f"{sec_vals[2]:+.2f}%"]
            macro_3m = [f"{spx_vals[3]:+.2f}%", f"{rut_vals[3]:+.2f}%", f"{sec_vals[3]:+.2f}%"]

            if not match_df.empty:
                match_df['Type_Cat'] = match_df['Type'].map({'SPX': 1, 'RMC': 2, 'RTY': 3})
                for idx, row in match_df.sort_values('Type_Cat').iterrows():
                    n_count = int(row['N'])
                    clean_name = str(row['IND_A']).replace('<br>', ' ')
                    cap_name = f"{sel_sec} - {clean_name[:12]} ({row['Type']}) (n={n_count})"
                    macro_names.append(cap_name)
                    macro_1d.append(f"{row['1D_raw']:+.2f}%" if pd.notna(row['1D_raw']) else "-")
                    macro_1w.append(f"{row['1W_raw']:+.2f}%" if pd.notna(row['1W_raw']) else "-")
                    macro_1m.append(f"{row['1M_raw']:+.2f}%" if pd.notna(row['1M_raw']) else "-")
                    macro_3m.append(f"{row['3M_raw']:+.2f}%" if pd.notna(row['3M_raw']) else "-")

            fig_mac_tbl = go.Figure(data=[go.Table(
                columnwidth=[160, 40, 40, 40, 40],
                header=dict(values=['<b>INDEX/ETF</b>', '<b>1D</b>', '<b>1W</b>', '<b>1M</b>', '<b>3M</b>'], fill_color='#161616', font=dict(color='#f4ca16', size=11), align=['left','right','right','right','right'], height=24),
                cells=dict(values=[macro_names, macro_1d, macro_1w, macro_1m, macro_3m], fill_color='#0d0d0d', font=dict(color='white', size=11), align=['left','right','right','right','right'], height=26)
            )])
            fig_mac_tbl.update_layout(margin=dict(l=0, r=4, t=10, b=0), height=MACRO_H)
            st.plotly_chart(fig_mac_tbl, use_container_width=True)

        with t_mic:
            st.markdown("<div style='text-align: right; margin-top: -17px; margin-bottom: 5px; position: relative; z-index: 50; padding-right: 5px; pointer-events: none;'><span style='color:#ab63fa; font-weight:bold; font-size:12px;'>🔬 Momentum (1M vs 1W)</span></div>", unsafe_allow_html=True)
            if not ind_df.empty:
                plot_df = ind_df.copy()
                plot_df['1W_raw'] = plot_df['1W_raw'].fillna(0.0).round(2)
                plot_df['1M_raw'] = plot_df['1M_raw'].fillna(0.0).round(2)

                fig_scat = go.Figure()
                if spx_vals[2] or spx_vals[1]: fig_scat.add_trace(go.Scatter(x=[round(spx_vals[2], 2)], y=[round(spx_vals[1], 2)], mode='markers', marker=dict(symbol='star', size=12, color='#ffffff', line=dict(width=1, color='black')), name='SPX', hovertemplate="<b>SPX Index</b><br>1W: %{y:+.2f}%<br>1M: %{x:+.2f}%<extra></extra>"))
                if rut_vals[2] or rut_vals[1]: fig_scat.add_trace(go.Scatter(x=[round(rut_vals[2], 2)], y=[round(rut_vals[1], 2)], mode='markers', marker=dict(symbol='star', size=12, color='#888888', line=dict(width=1, color='black')), name='RTY', hovertemplate="<b>RTY Index</b><br>1W: %{y:+.2f}%<br>1M: %{x:+.2f}%<extra></extra>"))
                if sec_vals[2] or sec_vals[1]: fig_scat.add_trace(go.Scatter(x=[round(sec_vals[2], 2)], y=[round(sec_vals[1], 2)], mode='markers', marker=dict(symbol='star', size=12, color='#f4ca16', line=dict(width=1, color='black')), name=sel_sec, hovertemplate=f"<b>{sel_sec} ETF</b><br>1W: %{{y:+.2f}}%<br>1M: %{{x:+.2f}}%<extra></extra>"))

                if not match_df.empty:
                    for idx, row in match_df.sort_values('Type_Cat').iterrows():
                        name_str = f"Avg ({row['Type']})"
                        color = '#00aaff' if row['Type'] == 'SPX' else ('#ff5252' if row['Type'] == 'RMC' else '#ab63fa')
                        clean_name_hov = str(row['IND_A']).replace('<br>', ' ')
                        fig_scat.add_trace(go.Scatter(x=[round(row['1M_raw'], 2)], y=[round(row['1W_raw'], 2)], mode='markers', marker=dict(symbol='diamond', size=10, color=color, line=dict(width=1, color='white')), name=name_str, hovertemplate=f"<b>{sel_sec} - {clean_name_hov[:12]} ({row['Type']}) (n={int(row['N'])})</b><br>1W: %{{y:+.2f}}%<br>1M: %{{x:+.2f}}%<extra></extra>"))

                for idx_name, c_hex in [('SPX', '#00aaff'), ('RMC', '#ff5252'), ('RTY', '#ab63fa')]:
                    s_df = plot_df[plot_df['Index'] == idx_name]
                    if not s_df.empty:
                        fig_scat.add_trace(go.Scatter(x=s_df['1M_raw'], y=s_df['1W_raw'], mode='markers', marker=dict(color=c_hex, size=7), name=f'{idx_name} Stocks', text=s_df['Ticker'], hovertemplate="<b>%{text}</b><br>1W: %{y:+.2f}%<br>1M: %{x:+.2f}%<extra></extra>"))

                fig_scat.add_hline(y=0, line_dash="dot", line_color="#555"); fig_scat.add_vline(x=0, line_dash="dot", line_color="#555")
                fig_scat.update_layout(margin=dict(l=10, r=10, t=50, b=10), height=MACRO_H, xaxis_title="1M Return (%)", yaxis_title="1W Return (%)", legend=dict(title="", orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0.0, font=dict(size=10)))
                st.plotly_chart(fig_scat, use_container_width=True)
            else:
                st.markdown(f"<div style='height:{MACRO_H}px; display:flex; align-items:center; justify-content:center; color:#888; font-size:12px; border:1px dashed #444; border-radius:4px;'>No valid returns found for this industry.</div>", unsafe_allow_html=True)

        st.markdown("<hr style='margin:3px 0;border-color:#333;'>", unsafe_allow_html=True)
        st.markdown("<div style='height: 40px;'></div>", unsafe_allow_html=True)

        # UPDATED TABS: MASTER TICKER HUB
        t_ins, t_options, t_sec, t_transcript = st.tabs(["🕵️ Insider Trades", "📉 Options", "📄 SEC Filings", "🎙️ Transcript"])

        with t_ins:
            st.markdown("<div style='text-align: right; margin-bottom: -32px; position: relative; z-index: 50; padding-right: 5px; pointer-events: none;'><span style='color:#ff5252; font-weight:bold; font-size:12px;'>🕵️ Insider Trades</span></div>", unsafe_allow_html=True)
            if selected_tickers:
                ins_tabs2 = st.tabs(selected_tickers)
                for i, tick in enumerate(selected_tickers):
                    with ins_tabs2[i]:
                        ins_df = get_insider_trades(tick)
                        if not ins_df.empty:
                            hdr_vals = [f'<b>{c}</b>' for c in ins_df.columns]
                            cell_vals = [ins_df[c].tolist() for c in ins_df.columns]
                            col_widths = []
                            for col in ins_df.columns:
                                if col in ['Insider Name', 'Title']: col_widths.append(120)
                                elif col in ['Trade Date', 'Trade Type', 'Price', 'Value']: col_widths.append(70)
                                else: col_widths.append(50)
                            fig_ins = go.Figure(data=[go.Table(columnwidth=col_widths, header=dict(values=hdr_vals, fill_color='#161616', font=dict(color='#ff5252', size=11), align='left', height=24), cells=dict(values=cell_vals, fill_color='#0d0d0d', font=dict(color='white', size=11), align='left', height=26))])
                            fig_ins.update_layout(margin=dict(l=0, r=4, t=0, b=0), height=INS_H)
                            st.plotly_chart(fig_ins, use_container_width=True)
                        else:
                            st.markdown(f"<div style='height:{INS_H}px; display:flex; align-items:center; justify-content:center; color:#ff5252; font-size:12px; border:1px dashed #444; border-radius:4px;'>🕵️ No recent insider trades found for {tick}</div>", unsafe_allow_html=True)
            else:
                st.markdown(f"<div style='height:{INS_H}px; display:flex; align-items:center; justify-content:center; color:#ff5252; font-size:12px; border:1px dashed #444; border-radius:4px;'>Select tickers from the FSLI dropdown to load Insiders.</div>", unsafe_allow_html=True)

        with t_options:
            st.markdown("<div style='text-align: right; margin-bottom: -32px; position: relative; z-index: 50; padding-right: 5px; pointer-events: none;'><span style='color:#ab63fa; font-weight:bold; font-size:12px;'>📉 Options Flow (10D Trend)</span></div>", unsafe_allow_html=True)

            if selected_tickers:
                opt_tabs = st.tabs(selected_tickers)
                for i, tick in enumerate(selected_tickers):
                    with opt_tabs[i]:
                        # THIS IS WHERE IT CALLS THE FUNCTION YOU ADDED IN STEP 1
                        opt_data = get_historical_options_data(tick)

                        if opt_data:
                            m1 = opt_data["m1_name"]
                            m2 = opt_data["m2_name"]
                            dates = opt_data["dates"]

                            y_labels = [
                                f"NetOI&nbsp;&nbsp;{m1}", f"ΔOI&nbsp;&nbsp;&nbsp;&nbsp;{m1}", f"P/C&nbsp;&nbsp;&nbsp;&nbsp;{m1}",
                                f"NetOI&nbsp;&nbsp;{m2}", f"ΔOI&nbsp;&nbsp;&nbsp;&nbsp;{m2}", f"P/C&nbsp;&nbsp;&nbsp;&nbsp;{m2}"
                            ]

                            raw_z = [
                                opt_data["m1_net"], opt_data["m1_delta"], opt_data["m1_pc"],
                                opt_data["m2_net"], opt_data["m2_delta"], opt_data["m2_pc"]
                            ]

                            text_mat = []
                            for row_idx, row_vals in enumerate(raw_z):
                                if row_idx in [2, 5]:
                                    text_mat.append([f"{v:.2f}" for v in row_vals])
                                else:
                                    text_mat.append([format_k(v) for v in row_vals])

                            fig_opt = go.Figure(data=go.Heatmap(
                                z=[[0]*len(dates)]*6,
                                x=dates,
                                y=y_labels,
                                customdata=raw_z,
                                text=text_mat,
                                texttemplate="%{text}",
                                textfont=dict(size=11, color="white"),
                                colorscale=[[0, '#161616'], [1, '#161616']],
                                showscale=False,
                                hovertemplate="<b>%{x}</b><br>%{y}: %{customdata}<extra></extra>"
                            ))

                            fig_opt.add_hline(y=2.5, line_width=2, line_color="#333333")
                            fig_opt.update_layout(
                                title=dict(text=f"{tick} Open Interest Trend", x=0.02, y=0.98, font=dict(size=12, color="white")),
                                margin=dict(l=0, r=10, t=30, b=0),
                                height=INS_H,
                                yaxis=dict(autorange="reversed")
                            )
                            st.plotly_chart(fig_opt, use_container_width=True)
                        else:
                            st.markdown(f"<div style='height:{INS_H}px; display:flex; align-items:center; justify-content:center; color:#ab63fa; font-size:12px; border:1px dashed #444; border-radius:4px;'>⚠️ No Historical Options Data for {tick}</div>", unsafe_allow_html=True)
            else:
                st.markdown(f"<div style='height:{INS_H}px; display:flex; align-items:center; justify-content:center; color:#ab63fa; font-size:12px; border:1px dashed #444; border-radius:4px;'>Select tickers to load Options History.</div>", unsafe_allow_html=True)

        with t_sec:
            ind_tickers = ind_df['Ticker'].tolist() if not ind_df.empty else []
            sec_ind_df = df_sec_live[df_sec_live['Ticker'].isin(ind_tickers)] if not df_sec_live.empty else pd.DataFrame()

            if sec_ind_df.empty and not df_sec_live.empty:
                sec_ind_df = df_sec_live[df_sec_live['Sector'] == sel_sec].head(10)
                sec_fallback_msg = f" (Showing {sel_sec} Sector)"
            else:
                sec_fallback_msg = ""

            st.markdown(f"<div style='text-align: right; margin-top: -50px; margin-bottom: -32px; position: relative; z-index: 50; padding-right: 5px; pointer-events: none;'><span style='color:#00aaff; font-weight:bold; font-size:12px;'>📄 SEC Filings{sec_fallback_msg}</span></div>", unsafe_allow_html=True)

            if not sec_ind_df.empty:
                fig_sec2 = go.Figure(data=[go.Table(
                    columnwidth=[45,40,35,40,35],
                    header=dict(values=['<b>DATE</b>','<b>TICK</b>','<b>IDX</b>','<b>TYPE</b>','<b>LINK</b>'], fill_color='#161616', font=dict(color='#00aaff',size=11), align=['left','left','center','center','center'], height=24),
                    cells=dict(values=[sec_ind_df['Date'],sec_ind_df['Ticker'],sec_ind_df['Index'],sec_ind_df['Type'],sec_ind_df['Link']], fill_color='#0d0d0d', font=dict(color=['white','white','white','white','#00aaff'],size=11), align=['left','left','center','center','center'], height=26)
                )])
                fig_sec2.update_layout(margin=dict(l=0,r=4,t=0,b=0), height=INS_H)
                st.plotly_chart(fig_sec2, use_container_width=True)
            else:
                 st.markdown(f"<div style='height:{INS_H}px; display:flex; align-items:center; justify-content:center; color:#00aaff; font-size:12px; border:1px dashed #444; border-radius:4px;'>No recent SEC filings found for this sector.</div>", unsafe_allow_html=True)

        with t_transcript:
            trans_ind_df = df_transcripts_live[df_transcripts_live['Ticker'].isin(ind_tickers)] if not df_transcripts_live.empty else pd.DataFrame()

            if trans_ind_df.empty and not df_transcripts_live.empty:
                trans_ind_df = df_transcripts_live[df_transcripts_live['Sector'] == sel_sec].head(10)
                trans_fallback_msg = f" (Showing {sel_sec} Sector)"
            else:
                trans_fallback_msg = ""

            st.markdown(f"<div style='text-align: right; margin-top: -50px; margin-bottom: -32px; position: relative; z-index: 50; padding-right: 5px; pointer-events: none;'><span style='color:#ab63fa; font-weight:bold; font-size:12px;'>🎙️ Transcripts{trans_fallback_msg}</span></div>", unsafe_allow_html=True)

            if not trans_ind_df.empty:
                fig_trans2 = go.Figure(data=[go.Table(
                    columnwidth=[45,40,35,80,40],
                    header=dict(values=['<b>DATE</b>','<b>TICK</b>','<b>IDX</b>','<b>INDUSTRY</b>','<b>LINK</b>'], fill_color='#161616', font=dict(color='#ab63fa',size=11), align=['left','left','center','left','center'], height=24),
                    cells=dict(values=[trans_ind_df['Date'],trans_ind_df['Ticker'],trans_ind_df['Index'],trans_ind_df['Industry'],trans_ind_df['Link']], fill_color='#0d0d0d', font=dict(color=['white','white','white','white','white','#ab63fa'],size=11), align=['left','left','center','left','center'], height=26)
                )])
                fig_trans2.update_layout(margin=dict(l=0,r=4,t=0,b=0), height=INS_H)
                st.plotly_chart(fig_trans2, use_container_width=True)
            else:
                st.markdown(f"<div style='height:{INS_H}px; display:flex; align-items:center; justify-content:center; color:#ab63fa; font-size:12px; border:1px dashed #444; border-radius:4px;'>No recent transcripts found for this sector.</div>", unsafe_allow_html=True)

CHART_HEIGHT_1 = 185
TITLE_FONT = dict(size=14, color="white")

# ---------------------------------------------------------
# LAYOUT STRUCTURE & STATE CAPTURE
# ---------------------------------------------------------
c1, c2, c3, c4 = st.columns(4)

c4_top = c4.container()
c2_top = c2.container()

with c4_top:
    b_col1, b_col2, b_col3 = st.columns([0.30, 0.35, 0.35])
    with b_col1:
        tf_sel = st.selectbox("TF", ["1D", "1W", "1M", "3M", "1Y"], index=4, label_visibility="collapsed")

with c2_top:
    sector_display_map = {
        'XLB': 'XLB (Materials)', 'XLC': 'XLC (Comm Svcs)', 'XLE': 'XLE (Energy)',
        'XLF': 'XLF (Financials)', 'XLI': 'XLI (Industrials)', 'XLK': 'XLK (Tech)',
        'XLP': 'XLP (Cons Staples)', 'XLRE': 'XLRE (Real Est)', 'XLU': 'XLU (Utilities)',
        'XLV': 'XLV (Health)', 'XLY': 'XLY (Cons Disc)'
    }
    sorted_keys = sorted(sector_display_map.keys())
    display_options = [sector_display_map[k] for k in sorted_keys]
    default_idx = sorted_keys.index('XLF') if 'XLF' in sorted_keys else 0

    h_col1, h_col2 = st.columns([0.45, 0.55])
    with h_col1: st.markdown("<div style='font-size:14px; color:white; font-weight:bold; margin-top:2px;'>Sector SPDR</div>", unsafe_allow_html=True)
    with h_col2: selected_display = st.selectbox("Sector", display_options, index=default_idx, label_visibility="collapsed")
    selected_sector = selected_display.split(' ')[0]

#--- 1. GLOBAL GXS STYLES & PYTHON LOADER ---
st.markdown('''
    <style>
    @keyframes logo-pulse {
        0% { transform: scale(1); opacity: 0.8; }
        50% { transform: scale(1.05); opacity: 1; }
        100% { transform: scale(1); opacity: 0.8; }
    }
    .gxs-loader-container {
        display: flex;
        flex-direction: column;
        align-items: center;
        justify-content: center;
        height: 100vh;
        width: 100vw;
        position: fixed;
        top: 0;
        left: 0;
        background: rgba(0, 0, 0, 1);#background: rgba(22, 22, 22, 0.95);
        z-index: 999999;
    }
    .gxs-loader-logo {
        width: 320px;
        animation: logo-pulse 1s infinite ease-in-out;
    }
    </style>
''', unsafe_allow_html=True)

def show_gxs_loader():
    placeholder = st.empty()
    placeholder.markdown('''
        <div class="gxs-loader-container">
            <img src="https://help.gxs.com.sg/@api/deki/site/logo.png?default=https://a.mtstatic.com/skins/styles/elm/logo.svg%3F_%3D332bad4b9843cb2363df2f3702c706dc22d85dbe:site_14150" class="gxs-loader-logo">
            #https://raw.githubusercontent.com/jianhuaa/fx-telegram-bot/refs/heads/main/me.png
            <p style="color: #ffd700; font-family: sans-serif; margin-top: 20px; font-weight: bold; letter-spacing: 1px;">
                DESIGNED AND DEVELOPED BY CHAN JIAN HUA...
            </p>
        </div>
    ''', unsafe_allow_html=True)
    return placeholder

# ---------------------------------------------------------color was #ab63fa
# FETCH DATA USING DYNAMIC TIMEFRAME
# ---------------------------------------------------------

main_loader = show_gxs_loader()

with st.spinner(f"Fetching Market Flows ({tf_sel})..."):
    futures_levels, vix_spot = load_vix_data()
    df_history, df_pct = get_historical_charts_data(tf_sel)
    df_sectors_price, df_sectors_pct = get_sector_data(tf_sel)
    df_cme_recent = get_cme_historical_data()
    df_spx_fut, spx_fut_months, df_spx_opt, spx_opt_months = get_sp500_master_data()
    df_rut_fut, rut_fut_months, df_rut_opt,   rut_opt_months = get_rut_master_data()
    df_industries = get_industry_table_data()
    df_sec_live, df_transcripts_live, df_all_ret = get_live_col4_data()

main_loader.empty()

# ---------------------------------------------------------
# RENDER DIALOG BUTTONS (Now that Data is fetched)
# ---------------------------------------------------------
with c4_top:
    df_sec_filtered = df_sec_live[df_sec_live['Sector'] == selected_sector].copy() if not df_sec_live.empty else pd.DataFrame()
    df_trans_filtered = df_transcripts_live[df_transcripts_live['Sector'] == selected_sector].copy() if not df_transcripts_live.empty else pd.DataFrame()

    with b_col2:
        if st.button("📊 Brief", use_container_width=True):
            btn_loader = show_gxs_loader()
            time.sleep(2)
            btn_loader.empty()
            show_summary_overlay(tf_sel, selected_sector, df_all_ret)
            #show_summary_overlay(tf_sel, selected_sector, df_all_ret)
    with b_col3:
        if st.button("🔭 Industry", use_container_width=True):
            btn_loader = show_gxs_loader()
            time.sleep(2)
            btn_loader.empty()
            show_industry_overview_overlay(df_all_ret, df_industries, selected_sector, df_sec_filtered, df_trans_filtered, df_history, df_sectors_price)
            #show_industry_overview_overlay(df_all_ret, df_industries, selected_sector, df_sec_filtered, df_trans_filtered, df_history, df_sectors_price)

# ==========================================
# COLUMN 1: MACRO & VOLATILITY
# ==========================================
if not df_history.empty:
    # 1. Keep time internally so points spread out horizontally
    fmt = "%d %b %H:%M" if tf_sel in ["1D", "1W", "1M"] else "%d %b '%y"

    for df in [df_history, df_pct, df_sectors_price, df_sectors_pct]:
        if isinstance(df.index, pd.DatetimeIndex):
            if getattr(df.index, 'tzinfo', None) is not None:
                df.index = df.index.tz_convert('America/New_York')
            df.index = df.index.strftime(fmt)

    last_date = df_history.index[-1]
    colors = px.colors.qualitative.Plotly

    # 2. Limit 3M to 5 ticks
    tick_map = {"1D": 4, "1W": 5, "1M": 5, "3M": 5, "1Y": 5}
    n_ticks = tick_map.get(tf_sel, 5)

    total_pts = len(df_history)
    step = max(1, (total_pts - 1) // (n_ticks - 1)) if total_pts > 1 else 1
    t_vals = [df_history.index[i] for i in range(0, total_pts, step)]

    if t_vals[-1] != last_date:
        t_vals[-1] = last_date

    # 3. Visually hide time from labels for everything except 1D
    t_text = t_vals if tf_sel == "1D" else [str(v).rsplit(' ', 1)[0] if ':' in str(v) else v for v in t_vals]

    x_axis_config = dict(showgrid=False, type='category', categoryorder='trace', tickmode='array', tickvals=t_vals, ticktext=t_text)

    with c1:
        fig_spx = px.line(df_history, y="SPX")
        spx_val, spx_pct = df_history['SPX'].iloc[-1], df_pct['SPX'].iloc[-1]
        fig_spx.add_annotation(x=last_date, y=spx_val, text=f"{spx_val:.0f} ({spx_pct:+.1f}%)", showarrow=False, xanchor='right', xshift=-5, yshift=15, font=dict(size=11, color="white"), bgcolor="rgba(0,0,0,0.8)", bordercolor="white", borderwidth=1, borderpad=3)
        fig_spx.update_layout(title=dict(text=f"SPX Value ({tf_sel})", x=0.02, y=0.98, font=TITLE_FONT), xaxis_title=None, yaxis_title=None, xaxis=x_axis_config, yaxis=dict(showgrid=False), margin=dict(l=0, r=10, t=30, b=0), height=CHART_HEIGHT_1)
        st.plotly_chart(fig_spx, use_container_width=True)

        fig_vix_svix = go.Figure()
        fig_vix_svix.add_trace(go.Scatter(x=df_pct.index, y=df_pct['VIX'], name='VIX', line=dict(color=colors[0])))
        fig_vix_svix.add_trace(go.Scatter(x=df_pct.index, y=df_pct['SVIX'], name='SVIX', line=dict(color=colors[1])))
        vix_val, vix_pct = df_history['VIX'].iloc[-1], df_pct['VIX'].iloc[-1]
        svix_val, svix_pct = df_history['SVIX'].iloc[-1], df_pct['SVIX'].iloc[-1]
        v_shift, s_shift = (18, -18) if vix_pct >= svix_pct else (-18, 18)
        fig_vix_svix.add_annotation(x=last_date, y=vix_pct, text=f"{vix_val:.2f} ({vix_pct:+.1f}%)", showarrow=False, xanchor='right', xshift=-5, yshift=v_shift, font=dict(size=11, color="white"), bgcolor="rgba(0,0,0,0.8)", bordercolor=colors[0], borderwidth=1, borderpad=3)
        fig_vix_svix.add_annotation(x=last_date, y=svix_pct, text=f"{svix_val:.2f} ({svix_pct:+.1f}%)", showarrow=False, xanchor='right', xshift=-5, yshift=s_shift, font=dict(size=11, color="white"), bgcolor="rgba(0,0,0,0.8)", bordercolor=colors[1], borderwidth=1, borderpad=3)
        fig_vix_svix.update_layout(title=dict(text=f"VIX vs SVIX ({tf_sel})", x=0.02, y=0.98, font=TITLE_FONT), xaxis_title=None, yaxis_title=None, xaxis=x_axis_config, yaxis=dict(ticksuffix="%", showgrid=False), legend=dict(orientation="v", yanchor="top", y=0.95, xanchor="left", x=0.02, bgcolor="rgba(0,0,0,0.6)", font=dict(size=9)), margin=dict(l=0, r=10, t=30, b=0), height=CHART_HEIGHT_1)
        st.plotly_chart(fig_vix_svix, use_container_width=True)

        df_ratios = pd.DataFrame(index=df_history.index)
        df_ratios['VVIX/VIX'] = df_history['VVIX'] / df_history['VIX']
        df_ratios['VIX/VIX3M'] = df_history['VIX'] / df_history['VIX3M']
        fig_ratios = go.Figure()
        fig_ratios.add_trace(go.Scatter(x=df_ratios.index, y=df_ratios['VVIX/VIX'], name='VVIX/VIX', yaxis='y1', line=dict(color='#ab63fa')))
        fig_ratios.add_trace(go.Scatter(x=df_ratios.index, y=df_ratios['VIX/VIX3M'], name='VIX/VIX3M', yaxis='y2', line=dict(color='#ff5252')))
        last_vvix, last_vix3m = df_ratios['VVIX/VIX'].iloc[-1], df_ratios['VIX/VIX3M'].iloc[-1]
        r1_shift, r2_shift = (18, -18) if df_ratios['VVIX/VIX'].iloc[-1] >= df_ratios['VIX/VIX3M'].iloc[-1] else (-18, 18)
        fig_ratios.add_annotation(x=last_date, y=last_vvix, yref='y1', text=f"{last_vvix:.2f}", showarrow=False, xanchor='right', xshift=-5, yshift=r1_shift, font=dict(size=11, color="white"), bgcolor="rgba(0,0,0,0.8)", bordercolor='#ab63fa', borderwidth=1, borderpad=3)
        fig_ratios.add_annotation(x=last_date, y=last_vix3m, yref='y2', text=f"{last_vix3m:.2f}", showarrow=False, xanchor='right', xshift=-5, yshift=r2_shift, font=dict(size=11, color="white"), bgcolor="rgba(0,0,0,0.8)", bordercolor='#ff5252', borderwidth=1, borderpad=3)
        fig_ratios.update_layout(title=dict(text=f"Regime Ratios ({tf_sel})", x=0.02, y=0.98, font=TITLE_FONT), xaxis=x_axis_config, yaxis=dict(side='left', showgrid=False), yaxis2=dict(side='right', overlaying='y', showgrid=False), legend=dict(orientation="v", yanchor="top", y=0.95, xanchor="left", x=0.02, bgcolor="rgba(0,0,0,0.6)", font=dict(size=9)), margin=dict(l=0, r=10, t=30, b=0), height=CHART_HEIGHT_1)
        st.plotly_chart(fig_ratios, use_container_width=True)

        if futures_levels:
            term_labels = ["Spot"] + [f"M{i+1}" for i in range(len(futures_levels))]
            term_vals = [vix_spot] + futures_levels
            fig_term = px.line(x=term_labels, y=term_vals, text=term_vals, markers=True)
            fig_term.update_traces(textposition="top center", texttemplate="%{text:.2f}")
            fig_term.update_layout(title=dict(text="VIX Term Structure", x=0.02, y=0.98, font=TITLE_FONT), xaxis_title=None, yaxis_title=None, xaxis=dict(showgrid=False), yaxis=dict(range=[min(term_vals) * 0.85, max(term_vals) * 1.15], showgrid=False), margin=dict(l=0, r=10, t=30, b=0), height=CHART_HEIGHT_1)
            st.plotly_chart(fig_term, use_container_width=True)

    # ==========================================
    # COLUMN 2: SECTORS & SPX FLOWS
    # ==========================================
    with c2:
        if not df_sectors_pct.empty:
            fig_sectors = go.Figure()
            val = df_sectors_price[selected_sector].iloc[-1]
            pct = df_sectors_pct[selected_sector].iloc[-1]
            fig_sectors.add_trace(go.Scatter(x=df_sectors_pct.index, y=df_sectors_pct[selected_sector], mode='lines', line=dict(color=colors[2])))
            fig_sectors.add_annotation(x=last_date, y=pct, text=f"{val:.2f} ({pct:+.1f}%)", showarrow=False, xanchor='right', xshift=-5, yshift=15, font=dict(size=11, color="white"), bgcolor="rgba(0,0,0,0.8)", bordercolor="white", borderwidth=1, borderpad=3)
            fig_sectors.update_layout(title="", xaxis_title=None, yaxis_title=None, xaxis=x_axis_config, yaxis=dict(ticksuffix="%", showgrid=False), showlegend=False, margin=dict(l=0, r=10, t=5, b=0), height=142)
            st.plotly_chart(fig_sectors, use_container_width=True)

        if not df_cme_recent.empty:
            df_sec = df_cme_recent[df_cme_recent['XL_ID'] == selected_sector].copy()
            df_sec['Date_Str'] = df_sec['Date'].dt.strftime('%d %b')
            text_oi = [format_k(val) for val in df_sec['OI']]
            text_delta = [format_k(val) for val in df_sec['Delta']]
            fig_hm = go.Figure(data=go.Heatmap(z=[[0]*len(df_sec), [0]*len(df_sec)], x=df_sec['Date_Str'], y=['Σ OI', 'Δ OI'], customdata=[df_sec['OI'], df_sec['Delta']], text=[text_oi, text_delta], texttemplate="%{text}", textfont=dict(size=13, color="white"), colorscale=[[0, '#161616'], [1, '#161616']], showscale=False, hovertemplate="<b>%{x}</b><br>%{y}: %{customdata}<extra></extra>"))
            fig_hm.update_layout(title=dict(text=f"CME {selected_sector} Flows", x=0.02, y=0.98, font=TITLE_FONT), xaxis=dict(side='bottom'), yaxis=dict(autorange="reversed"), margin=dict(l=0, r=10, t=30, b=0), height=CHART_HEIGHT_1)
            st.plotly_chart(fig_hm, use_container_width=True)

        if len(spx_fut_months) == 2:
            m1, m2 = spx_fut_months[0], spx_fut_months[1]
            df_m1, df_m2 = df_spx_fut[df_spx_fut['Month'] == m1].copy(), df_spx_fut[df_spx_fut['Month'] == m2].copy()
            df_m1['Date_Str'] = df_m1['Date'].dt.strftime('%d %b')
            y_labels = [f"Σ&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;{m1}", f"Δ&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;{m1}", f"Σ&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;{m2}", f"Δ&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;{m2}"]
            raw_z = [df_m1['OI'].tolist(), df_m1['Delta'].tolist(), df_m2['OI'].tolist(), df_m2['Delta'].tolist()]
            text_matrix = [[format_k(v) for v in row] for row in raw_z]
            fig_spx_f = go.Figure(data=go.Heatmap(z=[[0]*len(df_m1)]*4, x=df_m1['Date_Str'], y=y_labels, customdata=raw_z, text=text_matrix, texttemplate="%{text}", textfont=dict(size=11, color="white"), colorscale=[[0, '#161616'], [1, '#161616']], showscale=False, hovertemplate="<b>%{x}</b><br>%{y}: %{customdata}<extra></extra>"))
            fig_spx_f.add_hline(y=1.5, line_width=2, line_color="#333333")
            fig_spx_f.update_layout(title=dict(text="SPX Futures Flow", x=0.02, y=0.98, font=TITLE_FONT), yaxis=dict(autorange="reversed"), margin=dict(l=0, r=10, t=30, b=0), height=CHART_HEIGHT_1)
            st.plotly_chart(fig_spx_f, use_container_width=True)

        if len(spx_opt_months) == 2:
            m1, m2 = spx_opt_months[0], spx_opt_months[1]
            df_m1, df_m2 = df_spx_opt[df_spx_opt['Month'] == m1].copy(), df_spx_opt[df_spx_opt['Month'] == m2].copy()
            df_m1['Date_Str'] = df_m1['Date'].dt.strftime('%d %b')
            y_labels = [f"Σ&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;{m1}", f"Δ&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;{m1}", f"P/C&nbsp;&nbsp;&nbsp;{m1}", f"Σ&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;{m2}", f"Δ&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;{m2}", f"P/C&nbsp;&nbsp;&nbsp;{m2}"]
            raw_z = [df_m1['OI'].tolist(), df_m1['Delta'].tolist(), df_m1['Sett_PC'].tolist(), df_m2['OI'].tolist(), df_m2['Delta'].tolist(), df_m2['Sett_PC'].tolist()]
            text_matrix = [[format_k(v) if i % 3 != 2 else f"{v:.2f}" for v in raw_z[i]] for i in range(6)]
            fig_spx_o = go.Figure(data=go.Heatmap(z=[[0]*len(df_m1)]*6, x=df_m1['Date_Str'], y=y_labels, customdata=raw_z, text=text_matrix, texttemplate="%{text}", textfont=dict(size=11, color="white"), colorscale=[[0, '#161616'], [1, '#161616']], showscale=False, hovertemplate="<b>%{x}</b><br>%{y}: %{customdata}<extra></extra>"))
            fig_spx_o.add_hline(y=2.5, line_width=2, line_color="#333333")
            fig_spx_o.update_layout(title=dict(text="SPX Options Flow", x=0.02, y=0.98, font=TITLE_FONT), yaxis=dict(autorange="reversed"), margin=dict(l=0, r=10, t=30, b=0), height=CHART_HEIGHT_1)
            st.plotly_chart(fig_spx_o, use_container_width=True)

    # ==========================================
    # COLUMN 3: RUSSELL 2000
    # ==========================================
    with c3:
        if "RUT" in df_history.columns:
            fig_rut = px.line(df_history, y="RUT")
            rut_val, rut_pct = df_history['RUT'].iloc[-1], df_pct['RUT'].iloc[-1]
            fig_rut.add_annotation(x=last_date, y=rut_val, text=f"{rut_val:.0f} ({rut_pct:+.1f}%)", showarrow=False, xanchor='right', xshift=-5, yshift=15, font=dict(size=11, color="white"), bgcolor="rgba(0,0,0,0.8)", bordercolor="white", borderwidth=1, borderpad=3)
            fig_rut.update_layout(title=dict(text=f"RTY Value ({tf_sel})", x=0.02, y=0.98, font=TITLE_FONT), xaxis_title=None, yaxis_title=None, xaxis=x_axis_config, yaxis=dict(showgrid=False), margin=dict(l=0, r=10, t=30, b=0), height=CHART_HEIGHT_1)
            st.plotly_chart(fig_rut, use_container_width=True)

        if not df_industries.empty:
            df_ind = df_industries[df_industries['ETF'] == selected_sector].copy()
            if not df_ind.empty:
                df_ind['Type'] = df_ind['Cap'].map({'S': 'RTY', 'M': 'RMC', 'L': 'SPX'})
                df_ind = df_ind.sort_values(by=['IND_A', 'Type'], ascending=[True, False])
                def fmt_pct(x): return f"{x:+.1f}%" if pd.notna(x) else "-"
                df_ind['1D'] = df_ind['1D_raw'].apply(fmt_pct)
                df_ind['1W'] = df_ind['1W_raw'].apply(fmt_pct)
                df_ind['1M'] = df_ind['1M_raw'].apply(fmt_pct)
                df_ind['3M'] = df_ind['3M_raw'].apply(fmt_pct)
                fig_tbl = go.Figure(data=[go.Table(columnwidth=[130, 42, 38, 40, 42, 42, 28], header=dict(values=['<b>INDUSTRY</b>', '<b>TYPE</b>', '<b>1D</b>', '<b>1W</b>', '<b>1M</b>', '<b>3M</b>', '<b>N</b>'], fill_color='#161616', font=dict(color='#00aaff', size=10), align=['left','center','right','right','right','right','right']), cells=dict(values=[df_ind['IND_A'], df_ind['Type'], df_ind['1D'], df_ind['1W'], df_ind['1M'], df_ind['3M'], df_ind['N']], fill_color='#0d0d0d', font=dict(color='white', size=10), align=['left','center','right','right','right','right','right']))])
                fig_tbl.update_layout(margin=dict(l=0, r=10, t=30, b=0), height=CHART_HEIGHT_1, title=dict(text=f"{selected_sector} Industries", x=0.02, y=0.98, font=TITLE_FONT))
                st.plotly_chart(fig_tbl, use_container_width=True)
            else: st.plotly_chart(go.Figure().update_layout(xaxis=dict(visible=False), yaxis=dict(visible=False), margin=dict(l=0, r=0, t=0, b=0), height=CHART_HEIGHT_1, plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)"), use_container_width=True)
        else: st.plotly_chart(go.Figure().update_layout(xaxis=dict(visible=False), yaxis=dict(visible=False), margin=dict(l=0, r=0, t=0, b=0), height=CHART_HEIGHT_1, plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)"), use_container_width=True)

        if len(rut_fut_months) == 2:
            m1, m2 = rut_fut_months[0], rut_fut_months[1]
            df_m1, df_m2 = df_rut_fut[df_rut_fut['Month'] == m1].copy(), df_rut_fut[df_rut_fut['Month'] == m2].copy()
            df_m1['Date_Str'] = df_m1['Date'].dt.strftime('%d %b')
            y_labels = [f"Σ&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;{m1}", f"Δ&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;{m1}", f"Σ&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;{m2}", f"Δ&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;{m2}"]
            raw_z = [df_m1['OI'].tolist(), df_m1['Delta'].tolist(), df_m2['OI'].tolist(), df_m2['Delta'].tolist()]
            text_matrix = [[format_k(v) for v in row] for row in raw_z]
            fig_rut_f = go.Figure(data=go.Heatmap(z=[[0]*len(df_m1)]*4, x=df_m1['Date_Str'], y=y_labels, customdata=raw_z, text=text_matrix, texttemplate="%{text}", textfont=dict(size=11, color="white"), colorscale=[[0, '#161616'], [1, '#161616']], showscale=False, hovertemplate="<b>%{x}</b><br>%{y}: %{customdata}<extra></extra>"))
            fig_rut_f.add_hline(y=1.5, line_width=2, line_color="#333333")
            fig_rut_f.update_layout(title=dict(text="RTY Futures Flow", x=0.02, y=0.98, font=TITLE_FONT), yaxis=dict(autorange="reversed"), margin=dict(l=0, r=10, t=30, b=0), height=CHART_HEIGHT_1)
            st.plotly_chart(fig_rut_f, use_container_width=True)

        if len(rut_opt_months) == 2:
            m1, m2 = rut_opt_months[0], rut_opt_months[1]
            df_m1, df_m2 = df_rut_opt[df_rut_opt['Month'] == m1].copy(), df_rut_opt[df_rut_opt['Month'] == m2].copy()
            df_m1['Date_Str'] = df_m1['Date'].dt.strftime('%d %b')
            y_labels = [f"Σ&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;{m1}", f"Δ&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;{m1}", f"P/C&nbsp;&nbsp;&nbsp;{m1}", f"Σ&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;{m2}", f"Δ&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;{m2}", f"P/C&nbsp;&nbsp;&nbsp;{m2}"]
            raw_z = [df_m1['OI'].tolist(), df_m1['Delta'].tolist(), df_m1['Sett_PC'].tolist(), df_m2['OI'].tolist(), df_m2['Delta'].tolist(), df_m2['Sett_PC'].tolist()]
            text_matrix = [[format_k(v) if i % 3 != 2 else f"{v:.2f}" for v in raw_z[i]] for i in range(6)]
            fig_rut_o = go.Figure(data=go.Heatmap(z=[[0]*len(df_m1)]*6, x=df_m1['Date_Str'], y=y_labels, customdata=raw_z, text=text_matrix, texttemplate="%{text}", textfont=dict(size=11, color="white"), colorscale=[[0, '#161616'], [1, '#161616']], showscale=False, hovertemplate="<b>%{x}</b><br>%{y}: %{customdata}<extra></extra>"))
            fig_rut_o.add_hline(y=2.5, line_width=2, line_color="#333333")
            fig_rut_o.update_layout(title=dict(text="RTY Options Flow", x=0.02, y=0.98, font=TITLE_FONT), yaxis=dict(autorange="reversed"), margin=dict(l=0, r=10, t=30, b=0), height=CHART_HEIGHT_1)
            st.plotly_chart(fig_rut_o, use_container_width=True)

    # ==========================================
    # COLUMN 4: SCREENER & TABS
    # ==========================================
    with c4:
        def get_sortable_date(d_str):
            try:
                dt = datetime.datetime.strptime(str(d_str).strip(), "%d %b")
                now = datetime.datetime.now()
                if dt.month > now.month + 1: return dt.replace(year=now.year - 1)
                return dt.replace(year=now.year)
            except: return datetime.datetime(1900, 1, 1)

        idx_map = {'SPX': 1, 'RMC': 2, 'RTY': 3}

        df_sec_filtered = df_sec_live[df_sec_live['Sector'] == selected_sector].copy() if not df_sec_live.empty else pd.DataFrame()
        df_trans_filtered = df_transcripts_live[df_transcripts_live['Sector'] == selected_sector].copy() if not df_transcripts_live.empty else pd.DataFrame()
        df_losers_filtered = df_all_ret[df_all_ret['Sector'] == selected_sector].copy() if not df_all_ret.empty else pd.DataFrame()

        if not df_sec_filtered.empty:
            df_sec_filtered['Date_Sort'] = df_sec_filtered['Date'].apply(get_sortable_date)
            df_sec_filtered['Index_Sort'] = df_sec_filtered['Index'].map(idx_map).fillna(99)
            df_sec_filtered = df_sec_filtered.sort_values(by=['Industry', 'Date_Sort', 'Index_Sort', 'Ticker'], ascending=[True, False, True, True])

        if not df_trans_filtered.empty:
            df_trans_filtered['Date_Sort'] = df_trans_filtered['Date'].apply(get_sortable_date)
            df_trans_filtered['Index_Sort'] = df_trans_filtered['Index'].map(idx_map).fillna(99)
            df_trans_filtered = df_trans_filtered.sort_values(by=['Industry', 'Date_Sort', 'Index_Sort', 'Ticker'], ascending=[True, False, True, True])

        if not df_losers_filtered.empty:
            sort_col = f"{tf_sel}_raw"
            if sort_col in df_losers_filtered.columns:
                df_losers_filtered['Index_Sort'] = df_losers_filtered['Index'].map(idx_map).fillna(99)
                df_losers_filtered = df_losers_filtered.sort_values(by=[sort_col, 'Industry', 'Index_Sort', 'Ticker'], ascending=[True, True, True, True]).head(50)

            df_losers_filtered['1D'] = df_losers_filtered['1D_raw'].apply(lambda x: f"{x:+.1f}%" if pd.notna(x) else "-")
            df_losers_filtered['1W'] = df_losers_filtered['1W_raw'].apply(lambda x: f"{x:+.0f}%" if pd.notna(x) else "-")
            df_losers_filtered['1M'] = df_losers_filtered['1M_raw'].apply(lambda x: f"{x:+.0f}%" if pd.notna(x) else "-")
            df_losers_filtered['3M'] = df_losers_filtered['3M_raw'].apply(lambda x: f"{x:+.0f}%" if pd.notna(x) else "-")
            df_losers_filtered['1Y'] = df_losers_filtered['1Y_raw'].apply(lambda x: f"{x:+.0f}%" if pd.notna(x) else "-")

        t_losers, t_sec, t_transcript = st.tabs(["🔴 Losers", "📄 SEC", "🎙️ Transcript"])
        TAB_HEIGHT = 640

        with t_losers:
            if not df_losers_filtered.empty:
                fig_losers = go.Figure(data=[go.Table(
                    columnwidth=[38,30,32,75,30,30,30,30,30],
                    header=dict(values=['<b>TICK</b>','<b>IDX</b>','<b>ETF</b>','<b>INDUSTRY</b>','<b>1D</b>','<b>1W</b>','<b>1M</b>','<b>3M</b>','<b>1Y</b>'], fill_color='#161616', font=dict(color='#ff5252',size=10), align=['left','center','center','left','center','center','center','center','center']),
                    cells=dict(values=[df_losers_filtered['Ticker'],df_losers_filtered['Index'],df_losers_filtered['Sector'],df_losers_filtered['Industry'],df_losers_filtered['1D'],df_losers_filtered['1W'],df_losers_filtered['1M'],df_losers_filtered['3M'],df_losers_filtered['1Y']], fill_color='#0d0d0d', font=dict(color='white',size=10), align=['left','center','center','left','center','center','center','center','center'], height=28)
                )])
                fig_losers.update_layout(margin=dict(l=0,r=10,t=5,b=0), height=TAB_HEIGHT)
                st.plotly_chart(fig_losers, use_container_width=True)
            else:
                st.warning(f"⚠️ No returns found for {selected_sector}.")

        with t_sec:
            if not df_sec_filtered.empty:
                fig_sec = go.Figure(data=[go.Table(
                    columnwidth=[45,40,30,35,75,40,35],
                    header=dict(values=['<b>DATE</b>','<b>TICK</b>','<b>IDX</b>','<b>ETF</b>','<b>INDUSTRY</b>','<b>TYPE</b>','<b>LINK</b>'], fill_color='#161616', font=dict(color='#00aaff',size=11), align=['left','left','center','center','left','center','center']),
                    cells=dict(values=[df_sec_filtered['Date'],df_sec_filtered['Ticker'],df_sec_filtered['Index'],df_sec_filtered['Sector'],df_sec_filtered['Industry'],df_sec_filtered['Type'],df_sec_filtered['Link']], fill_color='#0d0d0d', font=dict(color=['white','white','white','white','white','white','#00aaff'],size=11), align=['left','left','center','center','left','center','center'], height=28)
                )])
                fig_sec.update_layout(margin=dict(l=0,r=10,t=5,b=0), height=TAB_HEIGHT)
                st.plotly_chart(fig_sec, use_container_width=True)
            else:
                st.info(f"No 10-Q or 10-K filings found for {selected_sector}.")

        with t_transcript:
            if not df_trans_filtered.empty:
                fig_transcripts = go.Figure(data=[go.Table(
                    columnwidth=[45,40,30,35,80,40],
                    header=dict(values=['<b>DATE</b>','<b>TICK</b>','<b>IDX</b>','<b>ETF</b>','<b>INDUSTRY</b>','<b>LINK</b>'], fill_color='#161616', font=dict(color='#ab63fa',size=11), align=['left','left','center','center','left','center']),
                    cells=dict(values=[df_trans_filtered['Date'],df_trans_filtered['Ticker'],df_trans_filtered['Index'],df_trans_filtered['Sector'],df_trans_filtered['Industry'],df_trans_filtered['Link']], fill_color='#0d0d0d', font=dict(color=['white','white','white','white','white','#ab63fa'],size=11), align=['left','left','center','center','left','center'], height=28)
                )])
                fig_transcripts.update_layout(margin=dict(l=0,r=10,t=5,b=0), height=TAB_HEIGHT)
                st.plotly_chart(fig_transcripts, use_container_width=True)
            else:
                st.info(f"No recent transcripts found for {selected_sector}.")
# ---------------------------------------------------------
# DIALOG ROUTER (Catches cross-dialog navigation)
# ---------------------------------------------------------
if st.session_state.get('trigger_industry_dialog', False):
    st.session_state['trigger_industry_dialog'] = False

    target_sector = st.session_state.get('passed_sector', selected_sector)
    target_industry = st.session_state.get('passed_industry', None)

    df_sec_target = df_sec_live[df_sec_live['Sector'] == target_sector].copy() if not df_sec_live.empty else pd.DataFrame()
    df_trans_target = df_transcripts_live[df_transcripts_live['Sector'] == target_sector].copy() if not df_transcripts_live.empty else pd.DataFrame()

    # THE FIX: Use the new Python-controlled loader pattern here too!
    route_loader = show_gxs_loader()
    time.sleep(2)
    route_loader.empty()
    show_industry_overview_overlay(df_all_ret, df_industries, target_sector, df_sec_target, df_trans_target, df_history, df_sectors_price, target_industry)

"""

with open("app.py", "w") as f:
    f.write(code)

# 3. Start Streamlit with CORS disabled
print("\n🌐 Starting Streamlit App...")
subprocess.Popen([
    sys.executable, "-m", "streamlit", "run", "app.py",
    "--server.port", "8501",
    "--server.address", "127.0.0.1",
    "--server.headless", "true",
    "--server.enableCORS=false",
    "--server.enableXsrfProtection=false"
])
time.sleep(3)

print("🔗 Opening secure Ngrok tunnel...")
os.system(f"./ngrok config add-authtoken {NGROK_AUTH_TOKEN}")
os.system("pkill -f ngrok")
time.sleep(1)
#ngrok_process = subprocess.Popen(['./ngrok', 'http', '8501'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
# The --request-header-add flag bypasses the ngrok interstitial warning page
ngrok_process = subprocess.Popen(['./ngrok', 'http', '8501', '--request-header-add', 'ngrok-skip-browser-warning:true'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
time.sleep(3)

try:
    response   = requests.get("http://127.0.0.1:4040/api/tunnels")
    public_url = response.json()['tunnels'][0]['public_url']
    print("\n" + "="*70)
    print(f"👉 SUCCESS! Click here to open your live dashboard: {public_url}")
    print("="*70 + "\n")
except Exception as e:
    print(f"\nFailed to retrieve Ngrok tunnel URL. Error: {e}")
