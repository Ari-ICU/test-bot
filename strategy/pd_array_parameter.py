import pandas as pd
import numpy as np
import logging

logger = logging.getLogger(__name__)

def analyze_pd_parameter_setup(candles, df=None):
    """
    Implements PD Array 'Parameter' and 'Area of Opportunity' (AoO) Logic:
    1. Identify Bearish FVG (The Argument).
    2. Identify Rejection High formed within/respecting that FVG (The Parameter).
    3. Trigger BUY when price breaks ABOVE the Parameter (Argument removed).
    """
    if df is None:
        if not candles or len(candles) < 20:
            return "NEUTRAL", "Insufficient data"
        df = pd.DataFrame(candles)

    try:
        # Ensure we have enough data to shift
        if len(df) < 10:
            return "NEUTRAL", "Warming up..."

        # --- STEP 1: Identify Arguments (FVGs) ---
        # Bearish FVG: Gap between Candle 1 High and Candle 3 Low
        # Using .values for safety against index mismatches
        high_shift_2 = df['high'].shift(2)
        low_curr = df['low']
        df['bearish_fvg'] = (high_shift_2 < low_curr)
        
        # --- STEP 2: Identify the 'Parameter' (Rejection High) ---
        # Rejection High is the 'high' price when a Bearish FVG was active.
        # we use ffill() to carry the "Parameter" forward until a new one is formed.
        df['rejection_high'] = df['high'].where(df['bearish_fvg']).ffill()
        
        if df['rejection_high'].isna().all():
            return "NEUTRAL", "No Rejection High (Parameter) found"

        curr_rejection_high = df['rejection_high'].iloc[-1]
        curr_price = df['close'].iloc[-1]
        prev_price = df['close'].iloc[-2]

        # --- SAFETY CHECK: Prevent Formatting Errors ---
        # If the parameter is NaN or not a number, we must exit to avoid "Format specifier" crashes
        if curr_rejection_high is None or np.isnan(curr_rejection_high):
            return "NEUTRAL", "Parameter is NaN"

        # --- STEP 3: Entry Logic (Area of Opportunity) ---
        # Logic: If price crosses ABOVE the Rejection High, the bearish argument 
        # is invalidated, creating a Bullish Area of Opportunity.
        
        # FIX: Explicit precision :.5f used here to prevent "Format specifier missing precision"
        if prev_price <= curr_rejection_high and curr_price > curr_rejection_high:
            return "BUY", f"Parameter Met: High {curr_rejection_high:.5f} broken (AoO)"

        # --- STEP 4: Status Update ---
        # Log the current target price with fixed precision
        return "NEUTRAL", f"Parameter Not Met: Waiting for break of {curr_rejection_high:.5f}"

    except Exception as e:
        logger.error(f"PD Parameter Logic Error: {e}")
        return "NEUTRAL", "Strategy Error"