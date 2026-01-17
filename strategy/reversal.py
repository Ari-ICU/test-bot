import pandas as pd
import logging
from core.indicators import Indicators
from core.patterns import detect_patterns

logger = logging.getLogger(__name__)

def analyze_reversal_setup(candles, rsi_threshold=30, bb_period=20):
    if not candles or len(candles) < 30: 
        return "NEUTRAL", "Insufficient data (<30 candles)"
    
    df = pd.DataFrame(candles)
    
    try:
        # Calculate RSI & Bollinger Bands
        df['rsi'] = Indicators.calculate_rsi(df['close'])
        df['sma'] = Indicators.calculate_sma(df['close'], bb_period)
        std = df['close'].rolling(window=bb_period).std()
        df['upper_bb'] = df['sma'] + (std * 2)
        df['lower_bb'] = df['sma'] - (std * 2)
        
        df = df.dropna()
        if len(df) < 1:
            return "NEUTRAL", "No valid data after NaN drop"
        
        curr = df.iloc[-1]
        patterns = detect_patterns(candles)
        
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