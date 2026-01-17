import pandas as pd
import logging
from core.indicators import Indicators

logger = logging.getLogger(__name__)

def analyze_scalping_setup(candles):
    """
    Optimized M1/M5 Scalping Strategy:
    1. Trend: Price relative to EMA 50.
    2. Momentum: RSI (14) expanded zones for better frequency.
    3. Trigger: Stochastic Cross with buffer logic.
    """
    if not candles or len(candles) < 50:
        return "NEUTRAL", "Insufficient data (<50 candles)"

    df = pd.DataFrame(candles)
    
    try:
        # 1. Calculate Indicators using the Indicators class
        df['ema_50'] = Indicators.calculate_ema(df['close'], 50)
        df['rsi'] = Indicators.calculate_rsi(df['close'], 14)
        
        # FIXED: Robust unpack for Stochastic (handle if returns >2, e.g., %K, %D, slow%D)
        stoch_result = Indicators.calculate_stoch(df)
        if isinstance(stoch_result, (tuple, list)):
            if len(stoch_result) < 2:
                logger.debug("⚠️ Stochastic returned <2 values; padding with NaN")
                stoch_k, stoch_d = pd.Series([None]*len(df)), pd.Series([None]*len(df))
            else:
                stoch_k = stoch_result[0]
                stoch_d = stoch_result[1]
                if len(stoch_result) > 2:
                    logger.debug(f"⚠️ Stochastic returned {len(stoch_result)} values; truncated to 2")
        else:
            logger.warning("⚠️ Stochastic returned non-iterable; fallback to NEUTRAL")
            return "NEUTRAL", "Stochastic calc failed"
        
        df['stoch_k'] = stoch_k
        df['stoch_d'] = stoch_d
        
        # Drop rows with NaN (edge case for short data)
        df = df.dropna()
        if len(df) < 2:
            return "NEUTRAL", "Insufficient valid data after NaN drop"
        
        current = df.iloc[-1]
        prev = df.iloc[-2]
        
        # 2. Logic Gates (Filters) - Handle NaN
        if pd.isna(current['rsi']) or pd.isna(current['stoch_k']):
            return "NEUTRAL", "NaN in indicators"
        
        # Use 45/55 instead of 40/60 to catch more signals on lower timeframes
        is_rsi_buy = current['rsi'] < 45 
        is_rsi_sell = current['rsi'] > 55
        
        # Check for Stochastic Crossover (Bullish/Bearish)
        bullish_cross = prev['stoch_k'] <= prev['stoch_d'] and current['stoch_k'] > current['stoch_d']
        bearish_cross = prev['stoch_k'] >= prev['stoch_d'] and current['stoch_k'] < current['stoch_d']

        # --- SCALP BUY LOGIC ---
        # Trigger if price is near/above EMA and momentum is recovering from low levels
        if current['close'] > current['ema_50']:
            if is_rsi_buy:
                if bullish_cross and current['stoch_k'] < 30: # Raised from 20 to 30 for better entry
                    return "BUY", "Scalp: Trend Up + RSI Oversold + Bullish Stoch Cross"
            
            # Added: Mean Reversion Buy (Price dip in uptrend)
            elif current['low'] < current['ema_50'] and bullish_cross:
                return "BUY", "Scalp: Dip to EMA + Stoch Recovery"

        # --- SCALP SELL LOGIC ---
        elif current['close'] < current['ema_50']:
            if is_rsi_sell:
                if bearish_cross and current['stoch_k'] > 70: # Lowered from 80 to 70 for better entry
                    return "SELL", "Scalp: Trend Down + RSI Overbought + Bearish Stoch Cross"
                    
            # Added: Mean Reversion Sell (Price spike in downtrend)
            elif current['high'] > current['ema_50'] and bearish_cross:
                return "SELL", "Scalp: Spike to EMA + Stoch Rejection"

        return "NEUTRAL", "No confluence of Trend/RSI/Stochastic"
        
    except Exception as e:
        logger.error(f"💥 Scalping Strategy Error: {e}")
        return "NEUTRAL", f"Scalping calc failed: {str(e)}"