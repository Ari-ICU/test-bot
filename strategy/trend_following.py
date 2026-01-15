from core.indicators import calculate_rsi, calculate_macd
from core.patterns import detect_engulfing

def analyze_trend_setup(candles):
    score = 0
    reasons = []
    
    # 1. Indicators
    rsi = calculate_rsi(candles)
    macd, signal = calculate_macd(candles)
    
    if rsi < 40: score += 1
    elif rsi > 60: score -= 1 # Sell bias
    
    if macd > signal: 
        score += 1
        reasons.append("MACD_Cross")
    
    # 2. Patterns
    pattern = detect_engulfing(candles)
    if pattern == "BULLISH": 
        score += 2
        reasons.append("BullishEngulfing")
    elif pattern == "BEARISH": 
        score -= 2
        reasons.append("BearishEngulfing")
        
    decision = "NEUTRAL"
    if score >= 3: decision = "BUY"
    elif score <= -3: decision = "SELL"
    
    return decision, reasons