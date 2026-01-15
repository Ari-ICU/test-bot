import pandas as pd
from core.indicators import Indicators
from core.patterns import detect_patterns

def analyze_trend_setup(candles):
    """
    Advanced Trend Strategy:
    1. Check SuperTrend for direction.
    2. Check ADX for trend strength (>25).
    3. Wait for FVG, Engulfing, Flag, or Supply/Demand for entry.
    """
    if not candles or len(candles) < 50:
        return "NEUTRAL", ""

    df = pd.DataFrame(candles)
    
    # 1. Calculate Indicators
    df['ema_50'] = Indicators.calculate_ema(df['close'], 50)
    df['ema_200'] = Indicators.calculate_ema(df['close'], 200)
    df['adx'] = Indicators.calculate_adx(df)
    df['supertrend'], _, _ = Indicators.calculate_supertrend(df)
    
    current = df.iloc[-1]
    
    # 2. Pattern Recognition (Trigger)
    patterns = detect_patterns(candles)
    
    signal = "NEUTRAL"
    reasons = []

    # --- BUY LOGIC ---
    # Condition A: Strong Uptrend (Price > EMA200 and SuperTrend is Green)
    if current['close'] > current['ema_200'] and current['supertrend'] == True:
        if current['adx'] > 25:
            # Condition C: Entry Trigger
            # Added 'demand_zone' as a trigger
            if (patterns.get('bullish_fvg') or 
                patterns.get('bullish_engulfing') or 
                patterns.get('bullish_flag') or 
                patterns.get('demand_zone')):
                
                signal = "BUY"
                reasons.append("Trend: SuperTrend Bullish")
                reasons.append("Strength: ADX > 25")
                
                # Identify the specific trigger
                trigger = "Pattern"
                if patterns.get('demand_zone'): trigger = "Demand Zone (Drop-Base-Rally)"
                elif patterns.get('bullish_flag'): trigger = "Bull Flag"
                elif patterns.get('bullish_fvg'): trigger = "Fair Value Gap"
                elif patterns.get('bullish_engulfing'): trigger = "Bullish Engulfing"
                
                reasons.append(f"Trigger: {trigger}")

    # --- SELL LOGIC ---
    elif current['close'] < current['ema_200'] and current['supertrend'] == False:
        if current['adx'] > 25:
            # Condition C: Entry Trigger
            # Added 'supply_zone' as a trigger
            if (patterns.get('bearish_fvg') or 
                patterns.get('bearish_engulfing') or 
                patterns.get('bearish_flag') or 
                patterns.get('supply_zone')):
                
                signal = "SELL"
                reasons.append("Trend: SuperTrend Bearish")
                reasons.append("Strength: ADX > 25")
                
                # Identify the specific trigger
                trigger = "Pattern"
                if patterns.get('supply_zone'): trigger = "Supply Zone (Rally-Base-Drop)"
                elif patterns.get('bearish_flag'): trigger = "Bear Flag"
                elif patterns.get('bearish_fvg'): trigger = "Fair Value Gap"
                elif patterns.get('bearish_engulfing'): trigger = "Bearish Engulfing"
                
                reasons.append(f"Trigger: {trigger}")

    return signal, ", ".join(reasons)