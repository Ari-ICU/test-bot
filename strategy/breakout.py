from core.indicators import calculate_bollinger_bands, calculate_atr

def analyze_breakout_setup(candles):
    upper, lower, sma = calculate_bollinger_bands(candles)
    current = candles[-1]['close']
    prev = candles[-2]['close']
    atr = calculate_atr(candles)
    
    # Breakout with momentum
    if current > upper and current > prev + atr:
        return "BUY", ["BB_Breakout"]
    elif current < lower and current < prev - atr:
        return "SELL", ["BB_Breakout"]
        
    return "NEUTRAL", []