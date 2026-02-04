from datetime import datetime
import pandas as pd
from core.patterns import detect_patterns

def analyze_crt_tbs_setup(ltf_candles, htf_candles, symbol, ltf_tf, htf_tf, reclaim_pct=0.25):
    if not ltf_candles or len(ltf_candles) < 20:
        return "NEUTRAL", "Insufficient LTF data"
    if not htf_candles or len(htf_candles) < 10:
        return "NEUTRAL", "Insufficient HTF data"

    ltf_df = pd.DataFrame(ltf_candles)
    htf_df = pd.DataFrame(htf_candles)
    
    # CRT Range: Previous HTF Candle
    prev_htf = htf_df.iloc[-2]
    crt_high = prev_htf['high']
    crt_low = prev_htf['low']
    crt_range = crt_high - crt_low
    crt_mid = (crt_high + crt_low) / 2
    
    curr_price = ltf_df.iloc[-1]['close']
    ltf_patterns = detect_patterns(ltf_candles, df=ltf_df)
    
    # Threshold for a "valid" reclaim (optional)
    reclaim_threshold = crt_range * reclaim_pct

    # --- Bullish CRT Setup (Sweep Low -> Reclaim) ---
    # Manipulation: High probability if price breaks CRT Low recently
    sweep_low = ltf_df['low'].tail(20).min() < crt_low
    
    if sweep_low and curr_price > crt_low:
        # Reclaim occurred. Check for LTF confluence (TBS or MSS)
        has_confluence = ltf_patterns.get('turtle_soup_buy') or ltf_patterns.get('ict_bullish_mss') or ltf_patterns.get('bullish_pinbar')
        
        if has_confluence:
            # Targets as per CRT: TP1 @ 50%, TP2 @ 100%
            tp1 = crt_mid
            tp2 = crt_high
            sl = ltf_df['low'].tail(10).min() # Stop loss below manipulation low
            
            return "BUY", {
                "reason": f"Bullish CRT Reclaim | Range: {crt_low:.2f}-{crt_high:.2f}",
                "tp1": tp1,
                "tp2": tp2,
                "sl": sl,
                "crt_range": crt_range
            }

    # --- Bearish CRT Setup (Sweep High -> Reclaim) ---
    sweep_high = ltf_df['high'].tail(20).max() > crt_high
    
    if sweep_high and curr_price < crt_high:
        # Reclaim occurred.
        has_confluence = ltf_patterns.get('turtle_soup_sell') or ltf_patterns.get('ict_bearish_mss') or ltf_patterns.get('bearish_pinbar')
        
        if has_confluence:
            tp1 = crt_mid
            tp2 = crt_low
            sl = ltf_df['high'].tail(10).max() # Stop loss above manipulation high
            
            return "SELL", {
                "reason": f"Bearish CRT Reclaim | Range: {crt_low:.2f}-{crt_high:.2f}",
                "tp1": tp1,
                "tp2": tp2,
                "sl": sl,
                "crt_range": crt_range
            }

    return "NEUTRAL", "CRT: No valid setup (Waiting for Sweep/Reclaim)"