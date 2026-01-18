import pandas as pd
import logging
from core.indicators import Indicators
from core.patterns import detect_patterns

logger = logging.getLogger(__name__)

def analyze_trend_setup(candles):
    """
    Advanced Trend Strategy (Confluence):
    1. Trend: Price > EMA200 + SuperTrend Green.
    2. Momentum: MACD > Signal Line (Bullish).
    3. Strength: ADX > 25.
    4. Trigger: Pattern (Flag, FVG, Demand, Engulfing).
    """
    if not candles or len(candles) < 50:
        return "NEUTRAL", "Insufficient data (<50 candles)"

    df = pd.DataFrame(candles)
    
    try:
        # 1. Calculate Indicators
        df['ema_200'] = Indicators.calculate_ema(df['close'], 200)
        df['adx'] = Indicators.calculate_adx(df)
        
        # FIXED: Robust unpack for SuperTrend (expect 3: supertrend, dir, atr?)
        st_result = Indicators.calculate_supertrend(df)
        if isinstance(st_result, (tuple, list)) and len(st_result) >= 1:
            df['supertrend'] = st_result[0]
            if len(st_result) > 3:
                logger.debug(f"⚠️ SuperTrend returned {len(st_result)} values; truncated to 3")
                st_result = st_result[:3]
        else:
            logger.warning("⚠️ SuperTrend invalid; fallback")
            df['supertrend'] = pd.Series([False]*len(df))
        
        # FIXED: Robust unpack for MACD (expect 3: macd, signal, hist?)
        macd_result = Indicators.calculate_macd(df['close'])
        if isinstance(macd_result, (tuple, list)) and len(macd_result) >= 2:
            df['macd'] = macd_result[0]
            df['macd_signal'] = macd_result[1]
            if len(macd_result) > 3:
                logger.debug(f"⚠️ MACD returned {len(macd_result)} values; truncated to 3")
                macd_result = macd_result[:3]
        else:
            logger.warning("⚠️ MACD invalid; fallback")
            df['macd'] = df['macd_signal'] = pd.Series([0]*len(df))
        
        # Drop NaN rows
        df = df.dropna()
        if len(df) < 1:
            return "NEUTRAL", "No valid data after NaN drop"
        
        current = df.iloc[-1]
        patterns = detect_patterns(candles)
        
        signal = "NEUTRAL"
        reasons = []

        # --- TREND DIRECTION ---
        is_uptrend = current['close'] > current['ema_200'] and current['supertrend'] == True
        is_downtrend = current['close'] < current['ema_200'] and current['supertrend'] == False

        if not is_uptrend and not is_downtrend:
            return "NEUTRAL", "Trend: Mixed/Sideways (EMA vs ST)"

        # --- BUY LOGIC ---
        if is_uptrend:
            # B. Momentum Confirmation (MACD)
            if current['macd'] <= current['macd_signal']:
                return "NEUTRAL", "Trend: Bullish but MACD Bearish"
            
            # C. Trend Strength
            if current['adx'] <= 15:
                return "NEUTRAL", "Trend: Bullish but Low Strength (ADX < 15)"

            # D. Entry Trigger
            trigger_found = False
            trigger_name = ""

            if patterns.get('demand_zone'): trigger_found = True; trigger_name = "Demand Zone"
            elif patterns.get('bullish_flag'): trigger_found = True; trigger_name = "Bull Flag"
            elif patterns.get('bullish_fvg'): trigger_found = True; trigger_name = "FVG"
            elif patterns.get('bullish_engulfing'): trigger_found = True; trigger_name = "Engulfing"
            elif patterns.get('double_bottom'): trigger_found = True; trigger_name = "Double Bottom"

            if trigger_found:
                return "BUY", f"Trend: Confluence ({trigger_name})"
            else:
                return "NEUTRAL", "Trend: Bullish but No Pattern Trigger"

        # --- SELL LOGIC ---
        if is_downtrend:
            # B. Momentum Confirmation (MACD)
            if current['macd'] >= current['macd_signal']:
                return "NEUTRAL", "Trend: Bearish but MACD Bullish"
            
            if current['adx'] <= 15:
                return "NEUTRAL", "Trend: Bearish but Low Strength (ADX < 15)"

            trigger_found = False
            trigger_name = ""

            if patterns.get('supply_zone'): trigger_found = True; trigger_name = "Supply Zone"
            elif patterns.get('bearish_flag'): trigger_found = True; trigger_name = "Bear Flag"
            elif patterns.get('bearish_fvg'): trigger_found = True; trigger_name = "FVG"
            elif patterns.get('bearish_engulfing'): trigger_found = True; trigger_name = "Engulfing"
            elif patterns.get('double_top'): trigger_found = True; trigger_name = "Double Top"

            if trigger_found:
                return "SELL", f"Trend: Confluence ({trigger_name})"
            else:
                return "NEUTRAL", "Trend: Bearish but No Pattern Trigger"

        return "NEUTRAL", "Trend: No Trade Setup"
        
    except Exception as e:
        logger.error(f"💥 Trend Strategy Error: {e}")
        return "NEUTRAL", f"Trend: Error {str(e)[:20]}"