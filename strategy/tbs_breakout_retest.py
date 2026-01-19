import pandas as pd
import numpy as np
from core.indicators import Indicators

class TBSBreakoutRetest:
    """
    Implementation of the TBS Breakout & Retest Strategy.
    Logic: 
    1. Identify a Break of Structure (BOS).
    2. Wait for a pullback to the breakout level (Retest).
    3. Enter on confirmation (Engulfing or Rejection candle).
    """
    def __init__(self):
        self.name = "TBS_Breakout_Retest"

    def analyze(self, df):
        if len(df) < 50:
            return None

        # Calculate indicators for confirmation
        df = Indicators.add_ema(df, period=20) # Trend filter
        df = Indicators.add_rsi(df, period=14)
        
        last_row = df.iloc[-1]
        prev_row = df.iloc[-2]
        
        # 1. Identify Local Highs/Lows (Potential Breakout Levels)
        recent_high = df['high'].iloc[-20:-5].max()
        recent_low = df['low'].iloc[-20:-5].min()

        # 2. Bullish Setup (Breakout Above Resistance)
        # Breakout: Previous candle closed above resistance
        is_breakout_up = prev_row['close'] > recent_high
        # Retest: Current price is touching/near the old resistance (now support)
        is_retest_up = last_row['low'] <= recent_high and last_row['close'] >= recent_high
        
        if is_breakout_up and is_retest_up and last_row['close'] > last_row['ema_20']:
            return {
                "action": "buy",
                "entry": last_row['close'],
                "sl": recent_low, # Below the breakout base
                "tp": last_row['close'] + (last_row['close'] - recent_low) * 2, # 1:2 RR
                "reason": "Bullish Breakout & Retest confirmed"
            }

        # 3. Bearish Setup (Breakout Below Support)
        is_breakout_down = prev_row['close'] < recent_low
        is_retest_down = last_row['high'] >= recent_low and last_row['close'] <= recent_low
        
        if is_breakout_down and is_retest_down and last_row['close'] < last_row['ema_20']:
            return {
                "action": "sell",
                "entry": last_row['close'],
                "sl": recent_high,
                "tp": last_row['close'] - (recent_high - last_row['close']) * 2,
                "reason": "Bearish Breakout & Retest confirmed"
            }

        return None