import pandas as pd
from core.indicators import Indicators
from core.patterns import detect_patterns


def is_ict_killzone():
    """Checks if current time is within ICT Silver Bullet windows (EST)"""
    now_hour = datetime.utcnow().hour # Adjust based on your server offset
    # NY AM Session: 10:00 - 11:00 AM EST (approx 15:00-16:00 UTC)
    return 15 <= now_hour <= 16

def analyze_ict_setup(candles):
    if not candles or len(candles) < 30: return "NEUTRAL", ""
    
    df = pd.DataFrame(candles)
    # Check for Bollinger Squeeze (TBS)
    is_squeezing = Indicators.is_bollinger_squeeze(df)
    ict = detect_patterns(candles) 

    # 1. Check Time Filter
    if not is_ict_killzone():
        return "NEUTRAL", "Outside ICT Killzone"

    # 2. Check Squeeze
    if not is_squeezing:
        return "NEUTRAL", "No Bollinger Squeeze"
    
    # ICT TBS BUY: MSS + FVG Displacement during a Squeeze
    if is_squeezing and ict.get('ict_bullish_mss') and ict.get('ict_bullish_fvg'):
        return "BUY", "ICT + TBS: Squeeze + MSS/FVG Displacement"

    # ICT TBS SELL: MSS + FVG Displacement during a Squeeze
    if is_squeezing and ict.get('ict_bearish_mss') and ict.get('ict_bearish_fvg'):
        return "SELL", "ICT + TBS: Squeeze + MSS/FVG Displacement"
            
    return "NEUTRAL", ""