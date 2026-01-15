import pandas as pd

def detect_patterns(candles):
    """
    Analyzes candlestick data for advanced patterns.
    Returns a dictionary of boolean signals.
    """
    df = pd.DataFrame(candles)
    if len(df) < 20: return {}

    c = df.iloc[-1]   # Current candle
    p1 = df.iloc[-2]  # Previous (Base candidate)
    p2 = df.iloc[-3]  # 2 candles ago (Leg-in candidate)
    p3 = df.iloc[-4]  # 3 candles ago (Used for FVG)

    signals = {
        'bullish_engulfing': False,
        'bearish_engulfing': False,
        'bullish_pinbar': False,
        'bearish_pinbar': False,
        'bullish_fvg': False,
        'bearish_fvg': False,
        'bullish_flag': False,
        'bearish_flag': False,
        'supply_zone': False,  # NEW
        'demand_zone': False   # NEW
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
    if p3['high'] < p1['low']:
        signals['bullish_fvg'] = True
    if p3['low'] > p1['high']:
        signals['bearish_fvg'] = True

    # 4. Flag Patterns
    pole_len = 8
    flag_len = 6
    if len(df) >= (pole_len + flag_len + 1):
        flag_subset = df.iloc[-(flag_len+1):-1]
        pole_subset = df.iloc[-(pole_len+flag_len+1):-(flag_len+1)]
        
        pole_start = pole_subset.iloc[0]['open']
        pole_end = pole_subset.iloc[-1]['close']
        pole_move = pole_end - pole_start
        pole_height = abs(pole_move)
        
        flag_max = flag_subset['high'].max()
        flag_min = flag_subset['low'].min()
        flag_range = flag_max - flag_min
        
        is_valid_structure = pole_height > (flag_range * 1.5)

        if pole_move > 0 and is_valid_structure:
            retracement = pole_end - flag_min
            if retracement < (pole_height * 0.5) and c['close'] > flag_max:
                signals['bullish_flag'] = True

        if pole_move < 0 and is_valid_structure:
            retracement = flag_max - pole_end
            if retracement < (pole_height * 0.5) and c['close'] < flag_min:
                signals['bearish_flag'] = True

    # 5. Supply and Demand (Drop-Base-Rally / Rally-Base-Drop) [NEW]
    # Helper to calculate candle body size
    def body(candle): return abs(candle['close'] - candle['open'])
    avg_body = df['close'].diff().abs().rolling(14).mean().iloc[-1]

    # Demand Zone (Drop -> Base -> Rally)
    # P2: Drop (Red candle), P1: Base (Small body), C: Rally (Strong Green)
    is_drop = p2['close'] < p2['open']
    is_base = body(p1) < (avg_body * 0.6)  # Small body candle
    is_rally = c['close'] > c['open'] and body(c) > avg_body
    
    # Check if Rally broke the Base high
    if is_drop and is_base and is_rally and c['close'] > p1['high']:
        signals['demand_zone'] = True

    # Supply Zone (Rally -> Base -> Drop)
    # P2: Rally (Green candle), P1: Base (Small body), C: Drop (Strong Red)
    is_rally_prev = p2['close'] > p2['open']
    is_drop_curr = c['close'] < c['open'] and body(c) > avg_body
    
    # Check if Drop broke the Base low
    if is_rally_prev and is_base and is_drop_curr and c['close'] < p1['low']:
        signals['supply_zone'] = True

    return signals