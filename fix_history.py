import pandas as pd

print("Loading existing Parquet file...")
df = pd.read_parquet('col4_options_history.parquet')

# Sort chronologically so yesterday comes before today
df = df.sort_values(by=['Ticker', 'Date'])

# Recalculate the historical deltas correctly using pandas .diff()
# This subtracts the previous day's NetOI from the current day's NetOI
print("Recalculating Delta OI...")
df['M1_DeltaNetOI'] = df.groupby('Ticker')['M1_NetOI'].diff().fillna(0).astype(int)
df['M2_DeltaNetOI'] = df.groupby('Ticker')['M2_NetOI'].diff().fillna(0).astype(int)

# Save it back out, overwriting the old file
df.sort_values(by=['Date', 'Ticker'], ascending=[False, True]).to_parquet('col4_options_history.parquet')

print("Success! Your historical data is now fixed. Upload this to GitHub!")
