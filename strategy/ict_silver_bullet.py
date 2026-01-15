# strategy/ict_silver_bullet.py
import pandas as pd
from core.patterns import detect_patterns # Use the main detect_patterns

def analyze_ict_setup(candles):
    if not candles or len(candles) < 30: return "NEUTRAL", ""
    
    # Get the signals from the updated patterns file
    ict = detect_patterns(candles) 
    
    # ICT BUY: MSS + FVG Displacement
    if ict.get('ict_bullish_mss') and ict.get('ict_bullish_fvg'):
        return "BUY", "ICT: MSS + FVG Displacement"

    # ICT SELL: MSS + FVG Displacement
    if ict.get('ict_bearish_mss') and ict.get('ict_bearish_fvg'):
        return "SELL", "ICT: MSS + FVG Displacement"
            
    return "NEUTRAL", ""