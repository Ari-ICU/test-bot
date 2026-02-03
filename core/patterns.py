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
        'bullish_ifvg': False, 'bearish_ifvg': False,
        'bullish_flag': False, 'bearish_flag': False,
        'supply_zone': False, 'demand_zone': False,
        'double_top': False, 'double_bottom': False,
        'inside_bar': False, 
        'turtle_soup_buy': False, 'turtle_soup_sell': False,
        'ict_bullish_mss': False, 'ict_bearish_mss': False, 
        'ict_bullish_fvg': False, 'ict_bearish_fvg': False,
        'ote_bullish': False, 'ote_bearish': False,
        'cisd_bullish': False, 'cisd_bearish': False,
        'po3_accumulation': False, 'po3_manipulation': False
    }

    def body(k): return abs(k['close'] - k['open'])
    avg_body = df['close'].diff().abs().rolling(14).mean().iloc[-1]

    # --- 1. REGULAR FAIR VALUE GAPS (FVG) ---
    if p1['low'] > p3['high']:
        signals['bullish_fvg'] = True
        if body(p2) > (avg_body * 1.5): signals['ict_bullish_fvg'] = True

    if p1['high'] < p3['low']:
        signals['bearish_fvg'] = True
        if body(p2) > (avg_body * 1.5): signals['ict_bearish_fvg'] = True

    # --- 2. INVERSE FAIR VALUE GAPS (iFVG) ---
    if p3['low'] > p1['high'] and c['close'] > p3['low']:
        signals['bullish_ifvg'] = True
    if p3['high'] < p1['low'] and c['close'] < p3['high']:
        signals['bearish_ifvg'] = True

    # --- 3. ICT: MARKET STRUCTURE SHIFT (MSS) ---
    recent_high = df['high'].iloc[-15:-2].max()
    recent_low = df['low'].iloc[-15:-2].min()
    if c['close'] > recent_high: signals['ict_bullish_mss'] = True
    if c['close'] < recent_low: signals['ict_bearish_mss'] = True

    # --- 4. OTE (Optimal Trade Entry: 0.618 - 0.786) ---
    # We look for a retracement into the OTE zone after a displacement move.
    if signals['ict_bullish_mss']:
        swing_low = df['low'].iloc[-10:].min()
        swing_high = df['high'].iloc[-10:].max()
        range_size = swing_high - swing_low
        if range_size > 0:
            ote_low = swing_low + (range_size * 0.618)
            ote_high = swing_low + (range_size * 0.786)
            if ote_low <= c['close'] <= ote_high:
                signals['ote_bullish'] = True

    if signals['ict_bearish_mss']:
        swing_high = df['high'].iloc[-10:].max()
        swing_low = df['low'].iloc[-10:].min()
        range_size = swing_high - swing_low
        if range_size > 0:
            ote_high = swing_high - (range_size * 0.618)
            ote_low = swing_high - (range_size * 0.786)
            if ote_low <= c['close'] <= ote_high:
                signals['ote_bearish'] = True

    # --- 5. CISD (Change in State of Delivery) ---
    # Happens after a sweep when price closes back inside the previous candle's range with momentum.
    if signals['ict_bullish_mss'] and c['close'] > p2['high']:
        signals['cisd_bullish'] = True
    if signals['ict_bearish_mss'] and c['close'] < p2['low']:
        signals['cisd_bearish'] = True

    # --- 6. PO3 (Power of 3: Accumulation, Manipulation, Distribution) ---
    # Look for low volume accumulation followed by a quick manipulation wick.
    vol_avg = df['volume'].rolling(20).mean().iloc[-1] if 'volume' in df else 1
    is_low_vol = df['volume'].iloc[-5:-1].mean() < vol_avg if 'volume' in df else True
    if is_low_vol and abs(df['close'].iloc[-5:-1].mean() - df['open'].iloc[-5:-1].mean()) < avg_body:
        signals['po3_accumulation'] = True
        
    if signals['po3_accumulation'] and (signals['turtle_soup_buy'] or signals['turtle_soup_sell']):
        signals['po3_manipulation'] = True

    # --- 7. TURTLE SOUP ---
    if len(df) >= 20:
        prev_20_high = df['high'].iloc[-21:-1].max()
        prev_20_low = df['low'].iloc[-21:-1].min()
        if p1['low'] < prev_20_low and c['close'] > prev_20_low:
            signals['turtle_soup_buy'] = True
        if p1['high'] > prev_20_high and c['close'] < prev_20_high:
            signals['turtle_soup_sell'] = True

    return signals