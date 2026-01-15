# strategy/ict_silver_bullet.py

import pandas as pd
from core.patterns import detect_patterns # Fix: Use the correct function name

def analyze_ict_setup(candles):
    if not candles or len(candles) < 30: return "NEUTRAL", ""
    
    # Fix: Call the correct function name defined in patterns.py
    ict = detect_patterns(candles) 
    
    # ICT BUY: MSS occurred AND price is currently inside/touching a Bullish FVG
    if ict.get('ict_bullish_mss') and ict.get('ict_bullish_fvg'):
        return "BUY", "ICT: MSS + FVG Displacement"

    # ICT SELL: MSS occurred AND price is currently inside/touching a Bearish FVG
    if ict.get('ict_bearish_mss') and ict.get('ict_bearish_fvg'):
        return "SELL", "ICT: MSS + FVG Displacement"
            
    return "NEUTRAL", ""