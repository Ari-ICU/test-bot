import pandas as pd
import logging
from core.indicators import Indicators
from core.patterns import detect_patterns

logger = logging.getLogger(__name__)

def analyze_trend_setup(candles, df=None, patterns=None):
    """
    Advanced Trend Strategy (Confluence):
    1. Trend: Price > EMA200 + SuperTrend Green.
    2. Momentum: MACD > Signal Line (Bullish).
    3. Strength: ADX > 25.
    4. Trigger: Pattern (Flag, FVG, Demand, Engulfing).
    """
    if df is None:
        if not candles or len(candles) < 50:
            return "NEUTRAL", "Insufficient data (<50 candles)"
        df = pd.DataFrame(candles)
    
    try:
        # Calculate Indicators only if not present
        if 'ema_200' not in df:
            df['ema_200'] = Indicators.calculate_ema(df['close'], 200)
        if 'adx' not in df:
            df['adx'] = Indicators.calculate_adx(df)
        
        # SuperTrend
        if 'supertrend' not in df:
            st_result = Indicators.calculate_supertrend(df)
            df['supertrend'] = st_result[0] if isinstance(st_result, (tuple, list)) else pd.Series([False]*len(df))
        
        # MACD
        if 'macd' not in df:
            macd_res = Indicators.calculate_macd(df['close'])
            if isinstance(macd_res, (tuple, list)) and len(macd_res) >= 2:
                df['macd'], df['macd_signal'] = macd_res[0], macd_res[1]
            else:
                df['macd'] = df['macd_signal'] = pd.Series([0]*len(df))
        
        # Drop NaN rows
        df = df.dropna()
        if len(df) < 1:
            return "NEUTRAL", "No valid data after NaN drop"
        
        current = df.iloc[-1]
        
        if patterns is None:
            from core.patterns import detect_patterns
            patterns = detect_patterns(candles, df=df)
        
        signal = "NEUTRAL"
        reasons = []

        # --- TREND DIRECTION ---
        is_uptrend = current['close'] > current['ema_200'] and current['supertrend'] == True
        is_downtrend = current['close'] < current['ema_200'] and current['supertrend'] == False

        if not is_uptrend and not is_downtrend:
            return "NEUTRAL", "Trend: Mixed/Sideways (EMA vs ST)"

        # --- BUY LOGIC ---
        if is_uptrend:
            # B. Momentum Confirmation (Dynamic)
            # Normal: MACD > Signal
            # Aggressive: MACD > 0 (Bullish bias) even if below signal
            is_momentum_bullish = current['macd'] > current['macd_signal'] or (current['macd'] > 0 and current['adx'] > 30)
            
            if not is_momentum_bullish:
                return "NEUTRAL", "Trend: Bullish but MACD Bearish/Weak"
            
            # C. Trend Strength (Already filtered by Aggressive ADX check later)
            
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
            elif current['adx'] > 25:
                return "BUY", "Trend: Aggressive (Strong ADX)"
            else:
                return "NEUTRAL", "Trend: Bullish but No Pattern/Weak ADX"

        # --- SELL LOGIC ---
        if is_downtrend:
            # B. Momentum Confirmation (Dynamic)
            is_momentum_bearish = current['macd'] < current['macd_signal'] or (current['macd'] < 0 and current['adx'] > 30)
            
            if not is_momentum_bearish:
                return "NEUTRAL", "Trend: Bearish but MACD Bullish/Weak"
            
            trigger_found = False
            trigger_name = ""

            if patterns.get('supply_zone'): trigger_found = True; trigger_name = "Supply Zone"
            elif patterns.get('bearish_flag'): trigger_found = True; trigger_name = "Bear Flag"
            elif patterns.get('bearish_fvg'): trigger_found = True; trigger_name = "FVG"
            elif patterns.get('bearish_engulfing'): trigger_found = True; trigger_name = "Engulfing"
            elif patterns.get('double_top'): trigger_found = True; trigger_name = "Double Top"

            if trigger_found:
                return "SELL", f"Trend: Confluence ({trigger_name})"
            elif current['adx'] > 25:
                return "SELL", "Trend: Aggressive (Strong ADX)"
            else:
                return "NEUTRAL", "Trend: Bearish but No Pattern/Weak ADX"

        return "NEUTRAL", "Trend: No Trade Setup"
        
    except Exception as e:
        logger.error(f"💥 Trend Strategy Error: {e}")
        return "NEUTRAL", f"Trend: Error {str(e)[:20]}"