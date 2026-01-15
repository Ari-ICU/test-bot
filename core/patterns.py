import pandas as pd

def detect_patterns(candles):
    """
    Analyzes candlestick data for advanced patterns.
    Returns a dictionary of boolean signals.
    """
    df = pd.DataFrame(candles)
    if len(df) < 5: return {}

    c = df.iloc[-1]   # Current candle
    p1 = df.iloc[-2]  # Previous
    p2 = df.iloc[-3]  # 2 candles ago
    p3 = df.iloc[-4]  # 3 candles ago (Used for FVG)

    signals = {
        'bullish_engulfing': False,
        'bearish_engulfing': False,
        'bullish_pinbar': False,
        'bearish_pinbar': False,
        'bullish_fvg': False,
        'bearish_fvg': False
    }

    # 1. Engulfing Patterns (Strong Reversal)
    body_c = abs(c['close'] - c['open'])
    body_p1 = abs(p1['close'] - p1['open'])
    
    if c['close'] > c['open'] and p1['close'] < p1['open']:
        if c['close'] > p1['open'] and c['open'] < p1['close']:
            signals['bullish_engulfing'] = True

    if c['close'] < c['open'] and p1['close'] > p1['open']:
        if c['close'] < p1['open'] and c['open'] > p1['close']:
            signals['bearish_engulfing'] = True

    # 2. Pinbars (Rejection wicks)
    total_len = c['high'] - c['low']
    if total_len > 0:
        lower_wick = min(c['close'], c['open']) - c['low']
        upper_wick = c['high'] - max(c['close'], c['open'])
        
        # Bullish Pinbar (Long lower wick rejecting lows)
        if lower_wick > (total_len * 0.6) and upper_wick < (total_len * 0.2):
            signals['bullish_pinbar'] = True
            
        # Bearish Pinbar (Long upper wick rejecting highs)
        if upper_wick > (total_len * 0.6) and lower_wick < (total_len * 0.2):
            signals['bearish_pinbar'] = True

    # 3. Fair Value Gaps (FVG) - Smart Money Concept
    # Bullish FVG: Gap between Candle 1 High and Candle 3 Low
    if p3['high'] < p1['low']:
        signals['bullish_fvg'] = True
    
    # Bearish FVG: Gap between Candle 1 Low and Candle 3 High
    if p3['low'] > p1['high']:
        signals['bearish_fvg'] = True

    return signals