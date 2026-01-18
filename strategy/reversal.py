import pandas as pd
import logging
from core.indicators import Indicators
from core.patterns import detect_patterns

logger = logging.getLogger(__name__)

def analyze_reversal_setup(candles, df=None, patterns=None, bb_period=20):
    if df is None:
        if not candles or len(candles) < 30: 
            return "NEUTRAL", "Insufficient data (<30 candles)"
        df = pd.DataFrame(candles)
    
    try:
        # 1. Reuse or Calculate RSI & Bollinger Bands
        if 'rsi' not in df:
            df['rsi'] = Indicators.calculate_rsi(df['close'])
        
        if 'upper_bb' not in df:
            bb_upper, bb_lower = Indicators.calculate_bollinger_bands(df['close'], bb_period)
            df['upper_bb'], df['lower_bb'] = bb_upper, bb_lower
        
        # Drop NaN safely
        df_clean = df.dropna(subset=['rsi', 'lower_bb', 'upper_bb'])
        if len(df_clean) < 1:
            return "NEUTRAL", "No valid data after NaN drop"
        
        curr = df_clean.iloc[-1]
        
        if patterns is None:
            patterns = detect_patterns(candles, df=df)
        
        if pd.isna(curr['rsi']) or pd.isna(curr['lower_bb']):
            return "NEUTRAL", "NaN in indicators"
        
        # BUY Reversal (Oversold + Pinbar at Lower Band)
        if curr['close'] < curr['lower_bb'] or curr['rsi'] < 30:
            if patterns.get('bullish_pinbar') or patterns.get('bullish_engulfing'):
                return "BUY", "Reversal: RSI Oversold + Bullish Pattern"

        # SELL Reversal (Overbought + Pinbar at Upper Band)
        if curr['close'] > curr['upper_bb'] or curr['rsi'] > 70:
            if patterns.get('bearish_pinbar') or patterns.get('bearish_engulfing'):
                return "SELL", "Reversal: RSI Overbought + Bearish Pattern"
                
        return "NEUTRAL", "No reversal confluence"
        
    except Exception as e:
        logger.error(f"💥 Reversal Strategy Error: {e}")
        return "NEUTRAL", f"Reversal calc failed: {str(e)}"