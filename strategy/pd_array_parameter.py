import pandas as pd
from core.indicators import Indicators

def analyze_pd_parameter_setup(candles, df=None):
    """
    Implements the logic from the 'Parameters' and 'Area of Opportunity' slides.
    1. Identify Bearish FVG (Bearish Argument)
    2. Identify Bullish FVG (Bullish Argument)
    3. Identify Rejection High (The Parameter)
    4. IF Price > Rejection High: THEN Bearish Argument is removed -> LONG
    """
    if df is None:
        df = pd.DataFrame(candles)

    if len(df) < 10:
        return "NEUTRAL", "Insufficient data"

    # --- STEP 1: Identify Arguments (FVGs) ---
    # Bearish FVG (Slide 4): Gap between Candle 1 High and Candle 3 Low
    df['bearish_fvg'] = (df['high'].shift(2) < df['low'])
    
    # Bullish FVG (Slide 4): Gap between Candle 1 Low and Candle 3 High
    df['bullish_fvg'] = (df['low'].shift(2) > df['high'])

    # --- STEP 2: Identify the 'Parameter' (Rejection High) ---
    # Rejection High is defined as the high formed while respecting the Bearish FVG
    # We find the most recent high where a Bearish FVG was active
    rejection_highs = df['high'].where(df['bearish_fvg']).ffill()
    curr_rejection_high = rejection_highs.iloc[-1]
    
    if pd.isna(curr_rejection_high):
        return "NEUTRAL", "No Rejection High (Parameter) identified"

    curr_price = df['close'].iloc[-1]
    prev_price = df['close'].iloc[-2]

    # --- STEP 3: The Logic (Slide 3 & 5) ---
    # IF Gold runs the Rejection High -> THEN Bullish Area of Opportunity
    if prev_price <= curr_rejection_high and curr_price > curr_rejection_high:
        return "BUY", f"Parameter Met: Rejection High {curr_rejection_high:.2f} broken (AoO)"

    # --- STEP 4: The 'Else' (Slide 8) ---
    # Gold doesn't run the Rejection High -> Do nothing
    if curr_price <= curr_rejection_high:
        return "NEUTRAL", f"Parameter Not Met: Waiting for break of {curr_rejection_high:.2f}"

    return "NEUTRAL", "Scanning PD Arrays..."