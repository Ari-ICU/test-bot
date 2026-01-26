# strategy/pd_array_parameter.py
# PD Array Logic Strategy Implementation
# This strategy identifies Premium/Discount zones (PD Arrays) based on ICT/SMC concepts.
# - Discount: Areas below the 50% equilibrium (potential buy zones).
# - Premium: Areas above the 50% equilibrium (potential sell zones).
# - Uses swing highs/lows, FVG (Fair Value Gaps), and confluence with EMAs for signals.
# - Recommended TFs: H4/D1 for structure, but adaptable to lower TFs.
# - Output: "BUY" if discount confluence, "SELL" if premium confluence, else "NEUTRAL".
# FIXED: Handle detected_patterns param (ignore if unused) + Proper FVG filled slicing (no any() errors).

import pandas as pd
import numpy as np
from typing import Tuple, Dict, Any

def analyze_pd_parameter_setup(candles: list, df: pd.DataFrame, detected_patterns: Dict = None) -> Tuple[str, Any]:
    """
    Analyzes PD Array setups for buy/sell signals.
    
    Args:
        candles: List of candle dicts (OHLCV data).
        df: Pandas DataFrame with pre-computed indicators (ema_200, ema_50, rsi, atr, etc.).
        detected_patterns: Optional patterns dict (ignored for now).
    
    Returns:
        Tuple of (action: str, reason: dict/str) where action is "BUY", "SELL", or "NEUTRAL".
    """
    if len(df) < 50:  # Need sufficient history for swings/FVGs
        return "NEUTRAL", "Insufficient data for PD Array analysis."
    
    # Step 1: Identify Swing Highs/Lows (for PD structure)
    swing_highs, swing_lows = _detect_swings(df)
    
    # Step 2: Calculate Equilibrium (50% level from recent range)
    recent_high = df['high'].rolling(20).max().iloc[-1]
    recent_low = df['low'].rolling(20).min().iloc[-1]
    equilibrium = (recent_high + recent_low) / 2
    
    current_price = df['close'].iloc[-1]
    is_premium = current_price > equilibrium
    is_discount = current_price < equilibrium
    
    # Step 3: Detect Fair Value Gaps (FVG) as PD Array proxies
    fvgs = _detect_fvgs(df)
    bullish_fvg = any(fvg['type'] == 'bullish' and fvg['active'] for fvg in fvgs[-3:])  # Recent FVGs
    bearish_fvg = any(fvg['type'] == 'bearish' and fvg['active'] for fvg in fvgs[-3:])
    
    # Step 4: Confluence Checks
    rsi = df['rsi'].iloc[-1]
    ema_50 = df['ema_50'].iloc[-1]
    ema_200 = df['ema_200'].iloc[-1]
    trend_bull = current_price > ema_50 > ema_200
    trend_bear = current_price < ema_50 < ema_200
    
    # BUY Signal: Discount zone + Bullish FVG + RSI oversold + Bullish trend confluence
    if (is_discount and 
        bullish_fvg and 
        rsi < 40 and  # Oversold
        (current_price > swing_lows[-1] if swing_lows else True) and  # Above recent low
        trend_bull):
        reason = {
            "Zone": "Discount PD Array",
            "Confluence": "Bullish FVG + RSI<40 + EMA Bull",
            "Equilibrium": f"{equilibrium:.5f}"
        }
        return "BUY", reason
    
    # SELL Signal: Premium zone + Bearish FVG + RSI overbought + Bearish trend confluence
    elif (is_premium and 
          bearish_fvg and 
          rsi > 60 and  # Overbought
          (current_price < swing_highs[-1] if swing_highs else True) and  # Below recent high
          trend_bear):
        reason = {
            "Zone": "Premium PD Array",
            "Confluence": "Bearish FVG + RSI>60 + EMA Bear",
            "Equilibrium": f"{equilibrium:.5f}"
        }
        return "SELL", reason
    
    # NEUTRAL: No strong confluence
    reason = {
        "Zone": "Premium" if is_premium else "Discount" if is_discount else "Equilibrium",
        "FVG": "None Recent",
        "RSI": f"{rsi:.1f}",
        "Trend": "Bull" if trend_bull else "Bear" if trend_bear else "Sideways"
    }
    return "NEUTRAL", reason

def _detect_swings(df: pd.DataFrame, window: int = 5) -> Tuple[list, list]:
    """Detect swing highs and lows using a simple zigzag-like method."""
    highs = []
    lows = []
    for i in range(window, len(df) - window):
        high_slice = df['high'].iloc[i-window:i+window+1]
        if df['high'].iloc[i] == high_slice.max():
            highs.append((df['close'].iloc[i], df.index[i]))
        
        low_slice = df['low'].iloc[i-window:i+window+1]
        if df['low'].iloc[i] == low_slice.min():
            lows.append((df['close'].iloc[i], df.index[i]))
    
    return [h[0] for h in highs[-5:]], [l[0] for l in lows[-5:]]  # Last 5 swings

def _detect_fvgs(df: pd.DataFrame) -> list:
    """Detect Fair Value Gaps (imbalances between candles)."""
    fvgs = []
    for i in range(2, len(df)):
        prev_high = df['high'].iloc[i-2]
        curr_low = df['low'].iloc[i]
        
        # Bullish FVG: Gap up (prev high < curr low, and price hasn't filled it)
        if prev_high < curr_low:
            gap_top = curr_low
            gap_bottom = prev_high
            # FIXED: Proper filled check with slicing (avoids any() on empty)
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
        
        # Bearish FVG: Gap down (prev low > curr high)
        prev_low = df['low'].iloc[i-2]
        curr_high = df['high'].iloc[i]
        if prev_low > curr_high:  # Gap down
            gap_bottom = curr_high
            gap_top = prev_low
            # FIXED: Proper filled check with slicing
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