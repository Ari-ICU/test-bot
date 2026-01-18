import pandas as pd
from core.indicators import Indicators

def analyze_breakout_setup(candles):
    if not candles or len(candles) < 20: return "NEUTRAL", ""
    
    df = pd.DataFrame(candles)
    
    # Donchian Channels (20-period High/Low)
    high_20 = df['high'].rolling(window=20).max()
    low_20 = df['low'].rolling(window=20).min()
    
    curr = df.iloc[-1]
    
    # 1. Breakout UP
    high_target = high_20.iloc[-2]
    if curr['close'] > high_target:
        return "BUY", "Breakout: New 20-period High"
        
    # 2. Breakout DOWN
    low_target = low_20.iloc[-2]
    if curr['close'] < low_target:
        return "SELL", "Breakout: New 20-period Low"
        
    return "NEUTRAL", "Breakout: Price is Consolidating"