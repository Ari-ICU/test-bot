def detect_engulfing(candles):
    if len(candles) < 2: return "NONE"
    c1, c2 = candles[-2], candles[-1]
    
    # Bullish Engulfing
    if c1['close'] < c1['open'] and c2['close'] > c2['open']:
        if c2['close'] > c1['open'] and c2['open'] < c1['close']:
            return "BULLISH"
            
    # Bearish Engulfing
    if c1['close'] > c1['open'] and c2['close'] < c2['open']:
        if c2['close'] < c1['open'] and c2['open'] > c1['close']:
            return "BEARISH"
    return "NONE"

def detect_fvg(candles):
    """Detects Fair Value Gaps in the last 3 candles."""
    if len(candles) < 3: return "NONE", 0, 0
    curr, prev2 = candles[-1], candles[-3]
    
    if curr['low'] > prev2['high']:
        return "BULLISH", curr['low'], prev2['high']
    if curr['high'] < prev2['low']:
        return "BEARISH", prev2['low'], curr['high']
    return "NONE", 0, 0

def detect_fractals(candles, window=2):
    """Identifies swing highs and lows."""
    highs, lows = [], []
    if len(candles) < (window * 2 + 1): return [], []
    for i in range(window, len(candles) - window):
        curr = candles[i]
        is_high = all(candles[i-j]['high'] <= curr['high'] and candles[i+j]['high'] <= curr['high'] for j in range(1, window + 1))
        if is_high: highs.append(curr['high'])
        is_low = all(candles[i-j]['low'] >= curr['low'] and candles[i+j]['low'] >= curr['low'] for j in range(1, window + 1))
        if is_low: lows.append(curr['low'])
    return highs, lows

def detect_structure(candles):
    """Determines basic market structure (Higher Highs/Lower Lows)."""
    highs, lows = detect_fractals(candles)
    if not highs or not lows: return "NEUTRAL"
    current_close = candles[-1]['close']
    if current_close > highs[-1]: return "BULLISH"
    elif current_close < lows[-1]: return "BEARISH"
    return "NEUTRAL"