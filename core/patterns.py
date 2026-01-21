import pandas as pd

def detect_patterns(candles, df=None):
    """
    Analyzes candlestick data for advanced patterns.
    Returns a dictionary of boolean signals, fully aligned with ICT/FVG guide.
    """
    if df is None:
        df = pd.DataFrame(candles)
    
    if len(df) < 30: return {}

    # Candle indices based on your FVG slides (1, 2, 3)
    # c: Price Action | p1: Candle 3 | p2: Candle 2 (Displacement) | p3: Candle 1
    c = df.iloc[-1]   
    p1 = df.iloc[-2]  
    p2 = df.iloc[-3]  
    p3 = df.iloc[-4]  

    signals = {
        'bullish_engulfing': False, 'bearish_engulfing': False,
        'bullish_pinbar': False, 'bearish_pinbar': False,
        'bullish_fvg': False, 'bearish_fvg': False,
        'bullish_ifvg': False, 'bearish_ifvg': False,  # Added Inverse FVG
        'bullish_flag': False, 'bearish_flag': False,
        'supply_zone': False, 'demand_zone': False,
        'double_top': False, 'double_bottom': False,
        'inside_bar': False, 'turtle_soup_buy': False, 'turtle_soup_sell': False,
        'ict_bullish_mss': False, 'ict_bearish_mss': False, 
        'ict_bullish_fvg': False, 'ict_bearish_fvg': False
    }

    def body(k): return abs(k['close'] - k['open'])
    avg_body = df['close'].diff().abs().rolling(14).mean().iloc[-1]

    # --- 1. REGULAR FAIR VALUE GAPS (FVG) ---
    # Bullish: Low of C3 (p1) is higher than High of C1 (p3). No overlapping wicks.
    if p1['low'] > p3['high']:
        signals['bullish_fvg'] = True
        # ICT Displacement: Quick move to the upside (Large body)
        if body(p2) > (avg_body * 1.5):
            signals['ict_bullish_fvg'] = True

    # Bearish: High of C3 (p1) is lower than Low of C1 (p3). No overlapping wicks.
    if p1['high'] < p3['low']:
        signals['bearish_fvg'] = True
        # ICT Displacement: Quick move to the downside (Large body)
        if body(p2) > (avg_body * 1.5):
            signals['ict_bearish_fvg'] = True

    # --- 2. INVERSE FAIR VALUE GAPS (iFVG) ---
    # Definition: A regular FVG that got "violated" or broken through.
    
    # Bullish iFVG: A previous Bearish FVG zone is violated by a close above it
    # Check if a Bearish FVG existed (p3_low > p1_high) and current price closed above C1 low
    if p3['low'] > p1['high'] and c['close'] > p3['low']:
        signals['bullish_ifvg'] = True

    # Bearish iFVG: A previous Bullish FVG zone is violated by a close below it
    # Check if a Bullish FVG existed (p3_high < p1_low) and current price closed below C1 high
    if p3['high'] < p1['low'] and c['close'] < p3['high']:
        signals['bearish_ifvg'] = True

    # --- 3. ICT: MARKET STRUCTURE SHIFT (MSS) ---
    # Price breaks recent high/low with displacement.
    recent_high = df['high'].iloc[-15:-2].max()
    recent_low = df['low'].iloc[-15:-2].min()
    if c['close'] > recent_high: signals['ict_bullish_mss'] = True
    if c['close'] < recent_low: signals['ict_bearish_mss'] = True

    # --- 4. ENGULFING PATTERNS ---
    if c['close'] > c['open'] and p1['close'] < p1['open']:
        if c['close'] > p1['open'] and c['open'] < p1['close']:
            signals['bullish_engulfing'] = True

    if c['close'] < c['open'] and p1['close'] > p1['open']:
        if c['close'] < p1['open'] and c['open'] > p1['close']:
            signals['bearish_engulfing'] = True

    # --- 5. PINBARS ---
    total_len = c['high'] - c['low']
    if total_len > 0:
        lower_wick = min(c['close'], c['open']) - c['low']
        upper_wick = c['high'] - max(c['close'], c['open'])
        if lower_wick > (total_len * 0.6) and upper_wick < (total_len * 0.2):
            signals['bullish_pinbar'] = True
        if upper_wick > (total_len * 0.6) and lower_wick < (total_len * 0.2):
            signals['bearish_pinbar'] = True

    # --- 6. TURTLE SOUP (CRT) ---
    if len(df) >= 20:
        prev_20_high = df['high'].iloc[-21:-1].max()
        prev_20_low = df['low'].iloc[-21:-1].min()
        if p1['low'] < prev_20_low and c['close'] > prev_20_low:
            signals['turtle_soup_buy'] = True
        if p1['high'] > prev_20_high and c['close'] < prev_20_high:
            signals['turtle_soup_sell'] = True

    # --- 7. ADDITIONAL FILTERS (Inside Bar, Double Top/Bottom) ---
    if c['high'] < p1['high'] and c['low'] > p1['low']:
        signals['inside_bar'] = True

    history = df.iloc[-25:-5]
    if len(history) > 0:
        swing_high = history['high'].max()
        swing_low = history['low'].min()
        if abs(c['high'] - swing_high) < (swing_high * 0.001): signals['double_top'] = True
        if abs(c['low'] - swing_low) < (swing_low * 0.001): signals['double_bottom'] = True

    return signals