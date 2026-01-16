import pandas as pd
from core.indicators import Indicators

def analyze_scalping_setup(candles):
    """
    M1/M5 Scalping Strategy:
    1. Trend: Price relative to EMA 50.
    2. Momentum: RSI (14) Overbought/Oversold.
    3. Trigger: Stochastic Cross in extreme zones.
    """
    if not candles or len(candles) < 50:
        return "NEUTRAL", ""

    df = pd.DataFrame(candles)
    
    # Calculate Indicators
    df['ema_50'] = Indicators.calculate_ema(df['close'], 50)
    df['rsi'] = Indicators.calculate_rsi(df['close'], 14)
    # Assuming your Indicators class has calculate_stoch
    df['stoch_k'], df['stoch_d'] = Indicators.calculate_stoch(df)
    
    current = df.iloc[-1]
    prev = df.iloc[-2]
    
    signal = "NEUTRAL"
    reasons = []

    # --- SCALP BUY LOGIC ---
    # Price above EMA 50 (Short-term trend up)
    if current['close'] > current['ema_50']:
        # RSI oversold or moving up from oversold (< 40)
        if current['rsi'] < 40:
            # Stochastic Cross below 20
            if prev['stoch_k'] < prev['stoch_d'] and current['stoch_k'] > current['stoch_d']:
                if current['stoch_k'] < 20:
                    signal = "BUY"
                    reasons.append("Scalp: Trend Up + RSI Low + Stoch Cross")

    # --- SCALP SELL LOGIC ---
    elif current['close'] < current['ema_50']:
        # RSI overbought or moving down from overbought (> 60)
        if current['rsi'] > 60:
            # Stochastic Cross above 80
            if prev['stoch_k'] > prev['stoch_d'] and current['stoch_k'] < current['stoch_d']:
                if current['stoch_k'] > 80:
                    signal = "SELL"
                    reasons.append("Scalp: Trend Down + RSI High + Stoch Cross")

    return signal, ", ".join(reasons)