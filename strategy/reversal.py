import pandas as pd
from core.indicators import Indicators
from core.patterns import detect_patterns

def analyze_reversal_setup(candles, rsi_threshold=30, bb_period=20):
    if not candles or len(candles) < 30: return "NEUTRAL", ""
    
    df = pd.DataFrame(candles)
    
    # Calculate RSI & Bollinger Bands
    df['rsi'] = Indicators.calculate_rsi(df['close'])
    df['sma'] = Indicators.calculate_sma(df['close'], bb_period)
    std = df['close'].rolling(window=bb_period).std()
    df['upper_bb'] = df['sma'] + (std * 2)
    df['lower_bb'] = df['sma'] - (std * 2)
    
    curr = df.iloc[-1]
    patterns = detect_patterns(candles)
    
    # BUY Reversal (Oversold + Pinbar at Lower Band)
    if curr['close'] < curr['lower_bb'] or curr['rsi'] < 30:
        if patterns.get('bullish_pinbar') or patterns.get('bullish_engulfing'):
            return "BUY", "Reversal: RSI Oversold + Bullish Pattern"

    # SELL Reversal (Overbought + Pinbar at Upper Band)
    if curr['close'] > curr['upper_bb'] or curr['rsi'] > 70:
        if patterns.get('bearish_pinbar') or patterns.get('bearish_engulfing'):
            return "SELL", "Reversal: RSI Overbought + Bearish Pattern"
            
    return "NEUTRAL", ""