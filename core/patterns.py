import pandas as pd

def detect_patterns(candles):
    """
    Analyzes candlestick data for advanced patterns.
    Returns a dictionary of boolean signals.
    """
    df = pd.DataFrame(candles)
    if len(df) < 30: return {} # Increased history requirement

    c = df.iloc[-1]   # Current candle
    p1 = df.iloc[-2]  # Previous
    p2 = df.iloc[-3]  # 2 candles ago
    p3 = df.iloc[-4]  # 3 candles ago

    signals = {
        'bullish_engulfing': False, 'bearish_engulfing': False,
        'bullish_pinbar': False, 'bearish_pinbar': False,
        'bullish_fvg': False, 'bearish_fvg': False,
        'bullish_flag': False, 'bearish_flag': False,
        'supply_zone': False, 'demand_zone': False,
        'double_top': False, 'double_bottom': False,
        'inside_bar': False, 'turtle_soup_buy': False, 'turtle_soup_sell': False,
        'ict_bullish_mss': False, 'ict_bearish_mss': False, 
        'ict_bullish_fvg': False, 'ict_bearish_fvg': False
    }

    # 1. Engulfing Patterns
    if c['close'] > c['open'] and p1['close'] < p1['open']:
        if c['close'] > p1['open'] and c['open'] < p1['close']:
            signals['bullish_engulfing'] = True

    if c['close'] < c['open'] and p1['close'] > p1['open']:
        if c['close'] < p1['open'] and c['open'] > p1['close']:
            signals['bearish_engulfing'] = True

    # 2. Pinbars
    total_len = c['high'] - c['low']
    if total_len > 0:
        lower_wick = min(c['close'], c['open']) - c['low']
        upper_wick = c['high'] - max(c['close'], c['open'])
        
        if lower_wick > (total_len * 0.6) and upper_wick < (total_len * 0.2):
            signals['bullish_pinbar'] = True
        if upper_wick > (total_len * 0.6) and lower_wick < (total_len * 0.2):
            signals['bearish_pinbar'] = True

    # 3. Fair Value Gaps (FVG)
    if p3['high'] < p1['low']: signals['bullish_fvg'] = True
    if p3['low'] > p1['high']: signals['bearish_fvg'] = True

    # 4. Flag Patterns
    pole_len = 8; flag_len = 6
    if len(df) >= (pole_len + flag_len + 1):
        flag_subset = df.iloc[-(flag_len+1):-1]
        pole_subset = df.iloc[-(pole_len+flag_len+1):-(flag_len+1)]
        
        pole_start = pole_subset.iloc[0]['open']; pole_end = pole_subset.iloc[-1]['close']
        pole_move = pole_end - pole_start; pole_height = abs(pole_move)
        flag_max = flag_subset['high'].max(); flag_min = flag_subset['low'].min()
        
        is_valid_structure = pole_height > ((flag_max - flag_min) * 1.5)

        if pole_move > 0 and is_valid_structure:
            if (pole_end - flag_min) < (pole_height * 0.5) and c['close'] > flag_max:
                signals['bullish_flag'] = True

        if pole_move < 0 and is_valid_structure:
            if (flag_max - pole_end) < (pole_height * 0.5) and c['close'] < flag_min:
                signals['bearish_flag'] = True

    # 5. Supply and Demand
    def body(k): return abs(k['close'] - k['open'])
    avg_body = df['close'].diff().abs().rolling(14).mean().iloc[-1]
    
    # Demand (Drop-Base-Rally)
    if (p2['close'] < p2['open']) and (body(p1) < avg_body * 0.6) and (c['close'] > c['open']):
        if c['close'] > p1['high']: signals['demand_zone'] = True

    # Supply (Rally-Base-Drop)
    if (p2['close'] > p2['open']) and (body(p1) < avg_body * 0.6) and (c['close'] < c['open']):
        if c['close'] < p1['low']: signals['supply_zone'] = True

    # 6. Double Top / Bottom [NEW]
    history = df.iloc[-25:-5] # Look at past 20 candles, skipping recent 5
    if len(history) > 0:
        swing_high = history['high'].max()
        swing_low = history['low'].min()
        
        # Double Top (Price returns to High, rejects)
        if abs(c['high'] - swing_high) < (swing_high * 0.001): # 0.1% tolerance
             signals['double_top'] = True

        # Double Bottom (Price returns to Low, rejects)
        if abs(c['low'] - swing_low) < (swing_low * 0.001):
             signals['double_bottom'] = True

    # 7. Inside Bar (Volatility Contraction) [NEW]
    # Current candle is completely inside previous candle
    if c['high'] < p1['high'] and c['low'] > p1['low']:
        signals['inside_bar'] = True

    # 8. Turtle Soup (CRT) - 20 Period Fakeout
    if len(df) >= 20:
        prev_20_high = df['high'].iloc[-21:-1].max()
        prev_20_low = df['low'].iloc[-21:-1].min()
        
        # CRT Buy: Price drops below 20-period low but closes back above it
        if p1['low'] < prev_20_low and c['close'] > prev_20_low:
            signals['turtle_soup_buy'] = True
            
        # CRT Sell: Price breaks above 20-period high but closes back below it
        if p1['high'] > prev_20_high and c['close'] < prev_20_high:
            signals['turtle_soup_sell'] = True

    # 9. ICT: Market Structure Shift (MSS)
    recent_high = df['high'].iloc[-15:-2].max()
    recent_low = df['low'].iloc[-15:-2].min()
    if c['close'] > recent_high: signals['ict_bullish_mss'] = True
    if c['close'] < recent_low: signals['ict_bearish_mss'] = True

    # 10. ICT: Fair Value Gap with Displacement
    avg_body = df['close'].diff().abs().rolling(14).mean().iloc[-1]
    if p3['high'] < p1['low'] and abs(p2['close'] - p2['open']) > (avg_body * 1.5):
        signals['ict_bullish_fvg'] = True
    if p3['low'] > p1['high'] and abs(p2['close'] - p2['open']) > (avg_body * 1.5):
        signals['ict_bearish_fvg'] = True

    return signals