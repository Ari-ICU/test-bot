import pandas as pd
from core.indicators import Indicators
from core.patterns import detect_patterns

def analyze_tbs_turtle_setup(candles, df=None, patterns=None):
    if df is None:
        if not candles or len(candles) < 30: return "NEUTRAL", "Insufficient data"
        df = pd.DataFrame(candles)

    # Use pre-calculated squeeze if available
    if 'is_squeezing' in df:
        is_squeezing = df['is_squeezing'].iloc[-1]
    else:
        is_squeezing = Indicators.is_bollinger_squeeze(df)
        
    if patterns is None:
        patterns = detect_patterns(candles, df=df)
    
    # CRT + TBS Buy: Turtle Soup occurs during a Squeeze
    if is_squeezing:
        if patterns.get('turtle_soup_buy'):
            return "BUY", "CRT + TBS: Squeeze + Turtle Soup Bullish"
        if patterns.get('turtle_soup_sell'):
            return "SELL", "CRT + TBS: Squeeze + Turtle Soup Bearish"
        return "NEUTRAL", "TBS: Squeeze active, waiting for Turtle Soup"
        
    return "NEUTRAL", "TBS: No Bollinger Squeeze"