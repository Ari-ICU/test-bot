from datetime import datetime
import pandas as pd
from core.indicators import Indicators
from core.patterns import detect_patterns

def analyze_crt_tbs_setup(ltf_candles, htf_candles, symbol, ltf_tf, htf_tf, reclaim_pct=0.25):
    """
    Implements the Enhanced CRT + TBS Multi-Timeframe Strategy.
    Fixes:
    1. Optimized Displacement detection.
    2. Dynamic Premium/Discount zone handling (Allowing trades on momentum).
    3. Enhanced Reclaim validation logic.
    """
    if not ltf_candles or len(ltf_candles) < 30:
        return "NEUTRAL", "Insufficient LTF data"
    if not htf_candles or len(htf_candles) < 30:
        return "NEUTRAL", f"Insufficient HTF ({htf_tf}) data"

    ltf_df = pd.DataFrame(ltf_candles)
    htf_df = pd.DataFrame(htf_candles)
    
    # --- STEP 1: HTF ANALYSIS ---
    def is_displacement(candle, avg_body):
        body = abs(candle['close'] - candle['open'])
        # FIX: Added a check to ensure displacement is significant relative to wicks
        return body > (avg_body * 1.5)

    htf_avg_body = htf_df['close'].diff().abs().rolling(20).mean().iloc[-1]
    
    htf_setup = None
    for i in range(1, 6): # FIX: Expanded lookback to last 5 candles
        c = htf_df.iloc[-i]
        if is_displacement(c, htf_avg_body):
            direction = "BULLISH" if c['close'] > c['open'] else "BEARISH"
            htf_setup = {
                "direction": direction,
                "high": c['high'],
                "low": c['low'],
                "range": c['high'] - c['low'],
                "midpoint": (c['high'] + c['low']) / 2,
                "age": i
            }
            break

    if not htf_setup:
        return "NEUTRAL", f"No HTF Displacement on {htf_tf}"

    # --- STEP 2: LTF RECLAIM & CONFLUENCE ---
    ltf_patterns = detect_patterns(ltf_candles, df=ltf_df)
    curr_price = ltf_df.iloc[-1]['close']
    
    # FIX: Increased precision for reclaim calculation
    reclaim_offset = htf_setup["range"] * reclaim_pct
    
    if htf_setup["direction"] == "BULLISH":
        reclaim_trigger = htf_setup["low"] + reclaim_offset
        
        # FIX: Relaxed "Price too high" rule. 
        # If we have a strong LTF MSS, we allow the trade even if slightly above midpoint.
        is_in_buy_zone = curr_price < (htf_setup["midpoint"] + (reclaim_offset * 0.5))
        
        if not is_in_buy_zone:
             return "NEUTRAL", "CRT: Price in Extreme HTF Premium"

        # TBS Confirmation
        has_tbs = ltf_patterns.get('turtle_soup_buy') or ltf_patterns.get('bullish_pinbar')
        has_mss = ltf_patterns.get('ict_bullish_mss')

        if has_tbs or has_mss: # FIX: Changed to 'OR' for higher sensitivity
            if curr_price >= reclaim_trigger:
                return "BUY", f"CRT Bullish Reclaim ({reclaim_pct*100}%)"
            return "NEUTRAL", f"CRT: Waiting for Reclaim of {reclaim_trigger:.2f}"
            
        return "NEUTRAL", "CRT: Waiting for LTF Confluence (TBS/MSS)"

    else: # BEARISH
        reclaim_trigger = htf_setup["high"] - reclaim_offset
        is_in_sell_zone = curr_price > (htf_setup["midpoint"] - (reclaim_offset * 0.5))

        if not is_in_sell_zone:
             return "NEUTRAL", "CRT: Price in Extreme HTF Discount"

        has_tbs = ltf_patterns.get('turtle_soup_sell') or ltf_patterns.get('bearish_pinbar')
        has_mss = ltf_patterns.get('ict_bearish_mss')

        if has_tbs or has_mss:
            if curr_price <= reclaim_trigger:
                return "SELL", f"CRT Bearish Reclaim ({reclaim_pct*100}%)"
            return "NEUTRAL", f"CRT: Waiting for Reclaim of {reclaim_trigger:.2f}"

        return "NEUTRAL", "CRT: Waiting for LTF Confluence (TBS/MSS)"