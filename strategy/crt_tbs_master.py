from datetime import datetime
import pandas as pd
from core.indicators import Indicators
from core.patterns import detect_patterns

def analyze_crt_tbs_setup(ltf_candles, htf_candles, symbol, ltf_tf, htf_tf, reclaim_pct=0.25):
    """
    Implements the Enhanced CRT + TBS Multi-Timeframe Strategy.
    1. Identify HTF CRT expansion (Large Displacement).
    2. Check if price HAS RECLAIMED a specific % of the expansion candle on LTF.
    3. Confirm LTF Turtle Soup (TBS) / Liquidity Grab.
    4. Confirm LTF Market Structure Shift (MSS) for entry.
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
        return body > (avg_body * 1.5)

    htf_avg_body = htf_df['close'].diff().abs().rolling(20).mean().iloc[-1]
    
    # Look for the most recent HTF expansion candle
    htf_setup = None
    for i in range(1, 5): # Check last 4 HTF candles
        c = htf_df.iloc[-i]
        if is_displacement(c, htf_avg_body):
            direction = "BULLISH" if c['close'] > c['open'] else "BEARISH"
            htf_setup = {
                "direction": direction,
                "high": c['high'],
                "low": c['low'],
                "open": c['open'],
                "close": c['close'],
                "range": c['high'] - c['low'],
                "body_high": max(c['open'], c['close']),
                "body_low": min(c['open'], c['close']),
                "age": i
            }
            break

    if not htf_setup:
        return "NEUTRAL", f"No HTF Displacement on {htf_tf}"

    # --- STEP 2: LTF RECLAIM & CONFLUENCE ---
    ltf_patterns = detect_patterns(ltf_candles, df=ltf_df)
    curr_price = ltf_df.iloc[-1]['close']
    prev_price = ltf_df.iloc[-2]['close']
    
    # Calculate Reclaim Levels
    # Bullish CRT: Price should dip below HTF Low (Liquidity) then reclaim HTF Low + %
    # Bearish CRT: Price should spike above HTF High then reclaim HTF High - %
    
    if htf_setup["direction"] == "BULLISH":
        # Target: Buy in the Discount of the HTF expansion
        # Reclaim definition: Price went into discount (<50% of candle) and is moving back up
        reclaim_trigger = htf_setup["low"] + (htf_setup["range"] * reclaim_pct)
        mean_threshold = (htf_setup["high"] + htf_setup["low"]) / 2
        
        # Check if we are in the zone
        in_discount = curr_price < mean_threshold
        reclaimed = curr_price > reclaim_trigger and prev_price <= reclaim_trigger
        
        if not in_discount and curr_price > mean_threshold:
             return "NEUTRAL", f"CRT: Price too high (Premium of HTF)"

        # TBS Confirmation (Liquidity Grab)
        has_tbs = ltf_patterns.get('turtle_soup_buy') or ltf_patterns.get('bullish_pinbar')
        has_mss = ltf_patterns.get('ict_bullish_mss')

        if has_tbs and has_mss:
            if curr_price >= reclaim_trigger:
                return "BUY", f"CRT Reclaim {reclaim_pct*100}% + TBS/MSS"
            return "NEUTRAL", f"CRT: Waiting for Reclaim of {reclaim_trigger:.2f}"
            
        return "NEUTRAL", f"CRT Bullish: Waiting for LTF TBS/MSS in HTF Discount"

    else: # BEARISH
        reclaim_trigger = htf_setup["high"] - (htf_setup["range"] * reclaim_pct)
        mean_threshold = (htf_setup["high"] + htf_setup["low"]) / 2
        
        in_premium = curr_price > mean_threshold
        reclaimed = curr_price < reclaim_trigger and prev_price >= reclaim_trigger

        if not in_premium and curr_price < mean_threshold:
             return "NEUTRAL", f"CRT: Price too low (Discount of HTF)"

        has_tbs = ltf_patterns.get('turtle_soup_sell') or ltf_patterns.get('bearish_pinbar')
        has_mss = ltf_patterns.get('ict_bearish_mss')

        if has_tbs and has_mss:
            if curr_price <= reclaim_trigger:
                return "SELL", f"CRT Reclaim {reclaim_pct*100}% + TBS/MSS"
            return "NEUTRAL", f"CRT: Waiting for Reclaim of {reclaim_trigger:.2f}"

        return "NEUTRAL", f"CRT Bearish: Waiting for LTF TBS/MSS in HTF Premium"

    return "NEUTRAL", "Scanning CRT/TBS..."

