import pandas as pd
from core.indicators import Indicators
from core.patterns import detect_patterns
def analyze_tbs_retest_setup(candles, df=None, patterns=None):
    """
    Implementation of the TBS Breakout & Retest Strategy.
    Logic: 
    1. Identify a Break of Structure (BOS).
    2. Wait for a pullback to the breakout level (Retest).
    3. Enter on confirmation (Engulfing or Rejection candle).
    """
    if df is None:
        if not candles or len(candles) < 50:
            return "NEUTRAL", "Insufficient data"
        df = pd.DataFrame(candles)
    else:
        df = df.copy()
    if 'ema_20' not in df:
        df['ema_20'] = Indicators.calculate_ema(df['close'], 20)
    if patterns is None:
        patterns = detect_patterns(candles, df=df)
    last_row = df.iloc[-1]
    prev_row = df.iloc[-2]
    recent_high = df['high'].iloc[-25:-5].max()
    recent_low = df['low'].iloc[-25:-5].min()
    is_breakout_up = any(df['close'].iloc[-10:-1] > recent_high)
    is_retesting_high = last_row['low'] <= recent_high * 1.0005 and last_row['close'] >= recent_high * 0.9995
    if is_breakout_up and is_retesting_high:
        if last_row['close'] > last_row['ema_20']:
            if patterns.get('bullish_engulfing') or patterns.get('bullish_pinbar'):
                return "BUY", "TBS: Breakout & Retest Confirmed"
            return "NEUTRAL", "TBS: Waiting for Bullish Confirmation at Retest"
    is_breakout_down = any(df['close'].iloc[-10:-1] < recent_low)
    is_retesting_low = last_row['high'] >= recent_low * 0.9995 and last_row['close'] <= recent_low * 1.0005
    if is_breakout_down and is_retesting_low:
        if last_row['close'] < last_row['ema_20']:
            if patterns.get('bearish_engulfing') or patterns.get('bearish_pinbar'):
                return "SELL", "TBS: Breakout & Retest Confirmed"
            return "NEUTRAL", "TBS: Waiting for Bearish Confirmation at Retest"
    return "NEUTRAL", "Searching for Breakout/Retest..."
