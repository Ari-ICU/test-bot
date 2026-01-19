from datetime import datetime, timedelta
import pandas as pd
from core.indicators import Indicators
from core.patterns import detect_patterns

def analyze_crt_tbs_setup(ltf_candles, htf_candles, symbol, ltf_tf, htf_tf):
    """
    Implements the CRT + TBS Multi-Timeframe Strategy.
    1. Identify HTF CRT expansion & Key Levels (FVG/OB).
    2. Confirm LTF Turtle Soup (TBS) within HTF level.
    3. Look for LTF Market Structure Shift (MSS).
    """
    if not ltf_candles or len(ltf_candles) < 30:
        return "NEUTRAL", "Insufficient LTF data"
    if not htf_candles or len(htf_candles) < 30:
        return "NEUTRAL", f"Insufficient HTF ({htf_tf}) data"

    ltf_df = pd.DataFrame(ltf_candles)
    htf_df = pd.DataFrame(htf_candles)
    
    # --- STEP 1: HTF ANALYSIS (CRT & KEY LEVELS) ---
    htf_patterns = detect_patterns(htf_candles, df=htf_df)
    
    # CRT Expansion detection on HTF
    # We look for a recent large candle (displacement)
    def is_crt_expansion(candle, avg_body):
        body = abs(candle['close'] - candle['open'])
        return body > (avg_body * 2.0)

    htf_avg_body = htf_df['close'].diff().abs().rolling(20).mean().iloc[-1]
    
    # Check the last 3 HTF candles for a CRT expansion
    htf_crt_bullish = False
    htf_crt_bearish = False
    htf_key_price = 0
    
    # Look for bullish CRT + FVG/OB
    for i in range(1, 4):
        c = htf_df.iloc[-i]
        if is_crt_expansion(c, htf_avg_body) and c['close'] > c['open']:
            if htf_patterns.get('bullish_fvg') or htf_patterns.get('demand_zone'):
                htf_crt_bullish = True
                htf_key_price = c['low'] # Target the discount of the CRT
                break
        if is_crt_expansion(c, htf_avg_body) and c['close'] < c['open']:
            if htf_patterns.get('bearish_fvg') or htf_patterns.get('supply_zone'):
                htf_crt_bearish = True
                htf_key_price = c['high'] # Target the premium of the CRT
                break

    if not (htf_crt_bullish or htf_crt_bearish):
        return "NEUTRAL", f"No CRT Expansion on HTF ({htf_tf})"

    # --- STEP 2 & 3: LTF ANALYSIS (TBS + MSS) ---
    ltf_patterns = detect_patterns(ltf_candles, df=ltf_df)
    curr_price = ltf_df.iloc[-1]['close']
    
    if htf_crt_bullish:
        # We are looking for a BUY
        # TBS Requirement: Liquidity grab on LTF (turtle_soup_buy)
        if ltf_patterns.get('turtle_soup_buy') or ltf_patterns.get('bullish_pinbar'):
            # Confirmation: Market Structure Shift (MSS)
            if ltf_patterns.get('ict_bullish_mss'):
                return "BUY", f"CRT HTF({htf_tf}) + LTF TBS/MSS Confirmation"
            return "NEUTRAL", "CRT: Waiting for LTF MSS Confirmation"
        return "NEUTRAL", f"CRT: HTF Bullish, Waiting for LTF TBS on {ltf_tf}"

    if htf_crt_bearish:
        # We are looking for a SELL
        if ltf_patterns.get('turtle_soup_sell') or ltf_patterns.get('bearish_pinbar'):
            if ltf_patterns.get('ict_bearish_mss'):
                return "SELL", f"CRT HTF({htf_tf}) + LTF TBS/MSS Confirmation"
            return "NEUTRAL", "CRT: Waiting for LTF MSS Confirmation"
        return "NEUTRAL", f"CRT: HTF Bearish, Waiting for LTF TBS on {ltf_tf}"

    return "NEUTRAL", "Scanning CRT/TBS..."
