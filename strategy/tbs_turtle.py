# strategy/tbs_turtle.py

import pandas as pd
from core.indicators import Indicators
from core.patterns import detect_patterns

def analyze_tbs_turtle_setup(candles):
    if not candles or len(candles) < 30: return "NEUTRAL", ""
    
    df = pd.DataFrame(candles)
    is_squeezing = Indicators.is_bollinger_squeeze(df)
    patterns = detect_patterns(candles)
    
    # CRT + TBS Buy: Turtle Soup occurs while/after a Bollinger Squeeze
    if patterns.get('turtle_soup_buy') and is_squeezing:
        return "BUY", "CRT + TBS: Squeeze + Turtle Soup Bullish Reversal"

    # CRT + TBS Sell: Turtle Soup occurs while/after a Bollinger Squeeze
    if patterns.get('turtle_soup_sell') and is_squeezing:
        return "SELL", "CRT + TBS: Squeeze + Turtle Soup Bearish Reversal"
        
    return "NEUTRAL", ""