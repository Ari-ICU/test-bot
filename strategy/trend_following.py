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
            return "NEUTRAL", "Insufficient data"
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
            # Ensure we handle tuple return from Indicators
            df['supertrend'] = st_result[0] if isinstance(st_result, (tuple, list)) else st_result
        
        # MACD
        if 'macd' not in df:
            macd_res = Indicators.calculate_macd(df['close'])
            if isinstance(macd_res, (tuple, list)) and len(macd_res) >= 2:
                df['macd'], df['macd_signal'] = macd_res[0], macd_res[1]
            else:
                df['macd'] = df['macd_signal'] = pd.Series([0]*len(df))
        
        # Filter data to ensure we have valid values for the current bar
        df_clean = df.dropna(subset=['ema_200', 'adx', 'macd'])
        if df_clean.empty:
            return "NEUTRAL", "Indicators warming up"
        
        current = df_clean.iloc[-1]
        
        if patterns is None:
            patterns = detect_patterns(candles, df=df)
        
        # --- TREND DIRECTION ---
        # Image of a bullish trend with price above EMA 200 and positive MACD
        
        
        is_uptrend = current['close'] > current['ema_200'] and current['supertrend'] == True
        is_downtrend = current['close'] < current['ema_200'] and current['supertrend'] == False

        if not is_uptrend and not is_downtrend:
            return "NEUTRAL", "Mixed/Sideways"

        # --- BUY LOGIC ---
        if is_uptrend:
            is_momentum_bullish = current['macd'] > current['macd_signal'] or (current['macd'] > 0 and current['adx'] > 30)
            
            if not is_momentum_bullish:
                return "NEUTRAL", "Bullish Trend / Weak Momentum"
            
            trigger_name = ""
            if patterns.get('demand_zone'): trigger_name = "Demand"
            elif patterns.get('bullish_flag'): trigger_name = "Flag"
            elif patterns.get('bullish_fvg'): trigger_name = "FVG"
            elif patterns.get('bullish_engulfing'): trigger_name = "Engulfing"
            elif patterns.get('double_bottom'): trigger_name = "Double Bottom"

            if trigger_name:
                return "BUY", f"Trend Confluence ({trigger_name})"
            elif current['adx'] > 25:
                return "BUY", "Trend Strong (High ADX)"
            else:
                return "NEUTRAL", "Bullish / No Trigger"

        # --- SELL LOGIC ---
        if is_downtrend:
            is_momentum_bearish = current['macd'] < current['macd_signal'] or (current['macd'] < 0 and current['adx'] > 30)
            
            if not is_momentum_bearish:
                return "NEUTRAL", "Bearish Trend / Weak Momentum"
            
            trigger_name = ""
            if patterns.get('supply_zone'): trigger_name = "Supply"
            elif patterns.get('bearish_flag'): trigger_name = "Flag"
            elif patterns.get('bearish_fvg'): trigger_name = "FVG"
            elif patterns.get('bearish_engulfing'): trigger_name = "Engulfing"
            elif patterns.get('double_top'): trigger_name = "Double Top"

            if trigger_name:
                return "SELL", f"Trend Confluence ({trigger_name})"
            elif current['adx'] > 25:
                return "SELL", "Trend Strong (High ADX)"
            else:
                return "NEUTRAL", "Bearish / No Trigger"

        return "NEUTRAL", "No Setup"
        
    except Exception as e:
        # Crucial: Log the error here, but return a clean string to the main loop
        # to prevent the "Format specifier missing precision" crash in main.py
        logger.error(f"Trend Strategy Logic Error: {e}", exc_info=True)
        return "NEUTRAL", "Strategy Error"