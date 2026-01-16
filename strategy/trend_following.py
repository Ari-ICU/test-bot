import pandas as pd
from core.indicators import Indicators
from core.patterns import detect_patterns

def analyze_trend_setup(candles):
    """
    Advanced Trend Strategy (Confluence):
    1. Trend: Price > EMA200 + SuperTrend Green.
    2. Momentum: MACD > Signal Line (Bullish).
    3. Strength: ADX > 25.
    4. Trigger: Pattern (Flag, FVG, Demand, Engulfing).
    """
    if not candles or len(candles) < 50:
        return "NEUTRAL", ""

    df = pd.DataFrame(candles)
    
    # 1. Calculate Indicators
    df['ema_200'] = Indicators.calculate_ema(df['close'], 200)
    df['adx'] = Indicators.calculate_adx(df)
    df['supertrend'], _, _ = Indicators.calculate_supertrend(df)
    
    # NEW: MACD Calculation
    df['macd'], df['macd_signal'], _ = Indicators.calculate_macd(df['close'])
    
    current = df.iloc[-1]
    patterns = detect_patterns(candles)
    
    signal = "NEUTRAL"
    reasons = []

    # --- BUY LOGIC ---
    # A. Trend Direction
    if current['close'] > current['ema_200'] and current['supertrend'] == True:
        # B. Momentum Confirmation (MACD) [NEW]
        if current['macd'] > current['macd_signal']:
            # C. Trend Strength
            if current['adx'] > 15:
                # D. Entry Trigger
                trigger_found = False
                trigger_name = ""

                # High Conviction Patterns
                if patterns.get('demand_zone'): 
                    trigger_found = True; trigger_name = "Demand Zone"
                elif patterns.get('bullish_flag'): 
                    trigger_found = True; trigger_name = "Bull Flag"
                elif patterns.get('bullish_fvg'): 
                    trigger_found = True; trigger_name = "FVG"
                elif patterns.get('bullish_engulfing'): 
                    trigger_found = True; trigger_name = "Engulfing"
                elif patterns.get('double_bottom'):
                    trigger_found = True; trigger_name = "Double Bottom"

                if trigger_found:
                    signal = "BUY"
                    reasons.append("Trend: SuperTrend+EMA")
                    reasons.append("Momentum: MACD Bullish")
                    reasons.append(f"Trigger: {trigger_name}")

    # --- SELL LOGIC ---
    elif current['close'] < current['ema_200'] and current['supertrend'] == False:
        # B. Momentum Confirmation (MACD) [NEW]
        if current['macd'] < current['macd_signal']:
            if current['adx'] > 15:
                trigger_found = False
                trigger_name = ""

                if patterns.get('supply_zone'): 
                    trigger_found = True; trigger_name = "Supply Zone"
                elif patterns.get('bearish_flag'): 
                    trigger_found = True; trigger_name = "Bear Flag"
                elif patterns.get('bearish_fvg'): 
                    trigger_found = True; trigger_name = "FVG"
                elif patterns.get('bearish_engulfing'): 
                    trigger_found = True; trigger_name = "Engulfing"
                elif patterns.get('double_top'):
                    trigger_found = True; trigger_name = "Double Top"

                if trigger_found:
                    signal = "SELL"
                    reasons.append("Trend: SuperTrend+EMA")
                    reasons.append("Momentum: MACD Bearish")
                    reasons.append(f"Trigger: {trigger_name}")

    return signal, ", ".join(reasons)