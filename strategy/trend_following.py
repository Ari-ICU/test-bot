import pandas as pd
from core.indicators import Indicators
from core.patterns import detect_patterns

def analyze_trend_setup(candles):
    """
    Advanced Trend Strategy:
    1. Check SuperTrend for direction.
    2. Check ADX for trend strength (>25).
    3. Wait for FVG or Pullback to EMA for entry.
    """
    if not candles or len(candles) < 50:
        return "NEUTRAL", ""

    df = pd.DataFrame(candles)
    
    # 1. Calculate Indicators
    df['ema_50'] = Indicators.calculate_ema(df['close'], 50)
    df['ema_200'] = Indicators.calculate_ema(df['close'], 200)
    df['adx'] = Indicators.calculate_adx(df)
    df['supertrend'], _, _ = Indicators.calculate_supertrend(df)
    
    current = df.iloc[-1]
    
    # 2. Pattern Recognition (Trigger)
    patterns = detect_patterns(candles)
    
    signal = "NEUTRAL"
    reasons = []

    # --- BUY LOGIC ---
    # Condition A: Strong Uptrend (Price > EMA200 and SuperTrend is Green)
    if current['close'] > current['ema_200'] and current['supertrend'] == True:
        # Condition B: Trend has strength?
        if current['adx'] > 25:
            # Condition C: Entry Trigger (Bullish FVG or Engulfing)
            if patterns.get('bullish_fvg') or patterns.get('bullish_engulfing'):
                signal = "BUY"
                reasons.append("Trend: SuperTrend Bullish")
                reasons.append("Strength: ADX > 25")
                reasons.append("Trigger: FVG/Engulfing")

    # --- SELL LOGIC ---
    # Condition A: Strong Downtrend
    elif current['close'] < current['ema_200'] and current['supertrend'] == False:
        if current['adx'] > 25:
            if patterns.get('bearish_fvg') or patterns.get('bearish_engulfing'):
                signal = "SELL"
                reasons.append("Trend: SuperTrend Bearish")
                reasons.append("Strength: ADX > 25")
                reasons.append("Trigger: FVG/Engulfing")

    return signal, ", ".join(reasons)