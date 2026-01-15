# strategy/ict_silver_bullet.py

import pandas as pd
from core.patterns import detect_ict_patterns

def analyze_ict_setup(candles):
    if not candles or len(candles) < 30: return "NEUTRAL", ""
    
    df = pd.DataFrame(candles)
    ict = detect_ict_patterns(df)
    
    curr = df.iloc[-1]
    
    # ICT BUY: MSS occurred AND price is currently inside/touching a Bullish FVG
    if ict['ict_bullish_mss'] and ict['ict_bullish_fvg']:
        return "BUY", "ICT: MSS + FVG Displacement"

    # ICT SELL: MSS occurred AND price is currently inside/touching a Bearish FVG
    if ict['ict_bearish_mss'] and ict['ict_bearish_fvg']:
        return "SELL", "ICT: MSS + FVG Displacement"
            
    return "NEUTRAL", ""