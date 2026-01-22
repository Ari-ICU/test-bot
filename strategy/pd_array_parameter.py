import pandas as pd

def analyze_pd_parameter_setup(candles, df=None):
    if df is None:
        df = pd.DataFrame(candles)

    if len(df) < 10:
        return "NEUTRAL", "Insufficient data"

    # --- STEP 1: Correct ICT FVG Logic ---
    df['bearish_fvg'] = df['low'] > df['high'].shift(2)
    df['bullish_fvg'] = df['high'] < df['low'].shift(2)

    # --- STEP 2: Find Latest Rejection High ---
    rejection_levels = df.loc[df['bearish_fvg'], 'high']
    if rejection_levels.empty:
        return "NEUTRAL", "No Rejection High (Parameter) identified"

    curr_rejection_high = rejection_levels.iloc[-1]

    curr_price = df['close'].iloc[-1]
    prev_price = df['close'].iloc[-2]

    # --- STEP 3: Break Confirmation ---
    if prev_price <= curr_rejection_high and curr_price > curr_rejection_high:
        return "BUY", f"Parameter Met: Rejection High {curr_rejection_high:.5f} broken (AoO)"

    # --- STEP 4: Waiting State ---
    if curr_price <= curr_rejection_high:
        return "NEUTRAL", f"Parameter Not Met: Waiting for break of {curr_rejection_high:.5f}"

    return "NEUTRAL", "Scanning PD Arrays..."
