import pandas as pd
import logging
from core.patterns import detect_patterns

logger = logging.getLogger("PowerTF")

def analyze_power_tf_setup(candles_ltf, df_ltf, candles_htf1, df_htf1, candles_htf2, df_htf2, patterns_ltf=None):
    if len(df_ltf) < 20 or len(df_htf1) < 20 or len(df_htf2) < 20:
        return "NEUTRAL", "Insufficient data for Multi-TF"
    
    h4_ema = df_htf2['close'].ewm(span=200).mean().iloc[-1]
    h4_price = df_htf2['close'].iloc[-1]
    h4_bias = "BULLISH" if h4_price > h4_ema else "BEARISH"
    
    h4_high = df_htf2['high'].iloc[-50:-1].max()
    h4_low = df_htf2['low'].iloc[-50:-1].min()
    h4_at_high_liq = h4_price >= h4_high * 0.999
    h4_at_low_liq = h4_price <= h4_low * 1.001

    h1_ema_fast = df_htf1['close'].ewm(span=50).mean()
    h1_ema_slow = df_htf1['close'].ewm(span=200).mean()
    h1_trend = "UP" if h1_ema_fast.iloc[-1] > h1_ema_slow.iloc[-1] else "DOWN"
    
    h1_patterns = detect_patterns(candles_htf1, df=df_htf1)
    
    if patterns_ltf is None:
        patterns_ltf = detect_patterns(candles_ltf, df=df_ltf)
        
    m15_confirm = False
    entry_reason = ""
    
    if h4_bias == "BULLISH" and h1_trend == "UP":
        if patterns_ltf.get('bullish_engulfing') or patterns_ltf.get('morning_star') or patterns_ltf.get('hammer') or patterns_ltf.get('ict_bullish_mss'):
            m15_confirm = True
            entry_reason = "Bullish Multi-TF alignment (4H Bias + 1H Trend + 15M PA)"
            
    elif h4_bias == "BEARISH" and h1_trend == "DOWN":
        if patterns_ltf.get('bearish_engulfing') or patterns_ltf.get('evening_star') or patterns_ltf.get('shooting_star') or patterns_ltf.get('ict_bearish_mss'):
            m15_confirm = True
            entry_reason = "Bearish Multi-TF alignment (4H Bias + 1H Trend + 15M PA)"

    if m15_confirm:
        direction = "BUY" if h4_bias == "BULLISH" else "SELL"
        return direction, entry_reason

    return "NEUTRAL", "PowerTF: Waiting for H4/H1/M15 confluence"

