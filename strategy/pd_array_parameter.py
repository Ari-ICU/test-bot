import pandas as pd
import numpy as np
from typing import Tuple, Dict, Any
def analyze_pd_parameter_setup(candles: list, df: pd.DataFrame, detected_patterns: Dict = None) -> Tuple[str, Any]:
    if len(df) < 50:
        return "NEUTRAL", "Insufficient data for PD Array analysis."
    swing_highs, swing_lows = _detect_swings(df)
    recent_high = df['high'].rolling(20).max().iloc[-1]
    recent_low = df['low'].rolling(20).min().iloc[-1]
    equilibrium = (recent_high + recent_low) / 2
    current_price = df['close'].iloc[-1]
    is_premium = current_price > equilibrium
    is_discount = current_price < equilibrium
    fvgs = _detect_fvgs(df)
    bullish_fvg = any(fvg['type'] == 'bullish' and fvg['active'] for fvg in fvgs[-3:])
    bearish_fvg = any(fvg['type'] == 'bearish' and fvg['active'] for fvg in fvgs[-3:])
    rsi = df['rsi'].iloc[-1]
    ema_50 = df['ema_50'].iloc[-1]
    ema_200 = df['ema_200'].iloc[-1]
    trend_bull = current_price > ema_50 > ema_200
    trend_bear = current_price < ema_50 < ema_200
    if (is_discount and 
        bullish_fvg and 
        rsi < 40 and
        (current_price > swing_lows[-1] if swing_lows else True) and
        trend_bull):
        reason = {
            "Zone": "Discount PD Array",
            "Confluence": "Bullish FVG + RSI<40 + EMA Bull",
            "Equilibrium": f"{equilibrium:.5f}"
        }
        return "BUY", reason
    elif (is_premium and 
          bearish_fvg and 
          rsi > 60 and
          (current_price < swing_highs[-1] if swing_highs else True) and
          trend_bear):
        reason = {
            "Zone": "Premium PD Array",
            "Confluence": "Bearish FVG + RSI>60 + EMA Bear",
            "Equilibrium": f"{equilibrium:.5f}"
        }
        return "SELL", reason
    reason = {
        "Zone": "Premium" if is_premium else "Discount" if is_discount else "Equilibrium",
        "FVG": "None Recent",
        "RSI": f"{rsi:.1f}",
        "Trend": "Bull" if trend_bull else "Bear" if trend_bear else "Sideways"
    }
    return "NEUTRAL", reason
def _detect_swings(df: pd.DataFrame, window: int = 5) -> Tuple[list, list]:
    highs = []
    lows = []
    for i in range(window, len(df) - window):
        high_slice = df['high'].iloc[i-window:i+window+1]
        if df['high'].iloc[i] == high_slice.max():
            highs.append((df['close'].iloc[i], df.index[i]))
        low_slice = df['low'].iloc[i-window:i+window+1]
        if df['low'].iloc[i] == low_slice.min():
            lows.append((df['close'].iloc[i], df.index[i]))
    return [h[0] for h in highs[-5:]], [l[0] for l in lows[-5:]]
def _detect_fvgs(df: pd.DataFrame) -> list:
    fvgs = []
    for i in range(2, len(df)):
        prev_high = df['high'].iloc[i-2]
        curr_low = df['low'].iloc[i]
        if prev_high < curr_low:
            gap_top = curr_low
            gap_bottom = prev_high
            filled = False
            for j in range(i+1, min(i+10, len(df))):
                if df['low'].iloc[i:j+1].min() <= gap_bottom:
                    filled = True
                    break
            fvgs.append({
                'type': 'bullish',
                'top': gap_top,
                'bottom': gap_bottom,
                'active': not filled,
                'index': i
            })
        prev_low = df['low'].iloc[i-2]
        curr_high = df['high'].iloc[i]
        if prev_low > curr_high:
            gap_bottom = curr_high
            gap_top = prev_low
            filled = False
            for j in range(i+1, min(i+10, len(df))):
                if df['high'].iloc[i:j+1].max() >= gap_top:
                    filled = True
                    break
            fvgs.append({
                'type': 'bearish',
                'top': gap_top,
                'bottom': gap_bottom,
                'active': not filled,
                'index': i
            })
    return fvgs