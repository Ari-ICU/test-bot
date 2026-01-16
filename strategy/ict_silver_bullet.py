import pandas as pd
from core.indicators import Indicators
from core.patterns import detect_patterns

def analyze_ict_setup(candles):
    if not candles or len(candles) < 30: return "NEUTRAL", ""
    
    df = pd.DataFrame(candles)
    # Check for Bollinger Squeeze (TBS)
    is_squeezing = Indicators.is_bollinger_squeeze(df)
    ict = detect_patterns(candles) 
    
    # ICT TBS BUY: MSS + FVG Displacement during a Squeeze
    if is_squeezing and ict.get('ict_bullish_mss') and ict.get('ict_bullish_fvg'):
        return "BUY", "ICT + TBS: Squeeze + MSS/FVG Displacement"

    # ICT TBS SELL: MSS + FVG Displacement during a Squeeze
    if is_squeezing and ict.get('ict_bearish_mss') and ict.get('ict_bearish_fvg'):
        return "SELL", "ICT + TBS: Squeeze + MSS/FVG Displacement"
            
    return "NEUTRAL", ""