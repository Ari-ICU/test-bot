import pandas as pd
import logging
from core.patterns import detect_patterns

logger = logging.getLogger("SMCMaster")

def analyze_smc_setup(candles, df=None, patterns=None):
    if df is None:
        if not candles or len(candles) < 30:
            return "NEUTRAL", "Insufficient data"
        df = pd.DataFrame(candles)
    
    if patterns is None:
        patterns = detect_patterns(candles, df=df)
    
    curr = df.iloc[-1]
    p1 = df.iloc[-2]
    
    is_bullish_structure = patterns.get('ict_bullish_mss')
    is_bearish_structure = patterns.get('ict_bearish_mss')

    bu_conf = any([
        patterns.get('bullish_engulfing'),
        patterns.get('morning_star'),
        patterns.get('hammer'),
        patterns.get('tweezer_bottom')
    ])
    
    be_conf = any([
        patterns.get('bearish_engulfing'),
        patterns.get('evening_star'),
        patterns.get('shooting_star'),
        patterns.get('tweezer_top')
    ])

    bullish_confluence = patterns.get('bullish_fvg') or patterns.get('ote_bullish')
    bearish_confluence = patterns.get('bearish_fvg') or patterns.get('ote_bearish')

    if is_bullish_structure and bu_conf:
        return "BUY", "SMC Model #1: MSS + Candle Confirmation"
    
    if is_bearish_structure and be_conf:
        return "SELL", "SMC Model #1: MSS + Candle Confirmation"

    if bullish_confluence and bu_conf:
        return "BUY", "SMC Model #2: FVG/OTE + Candle Confirmation"
    
    if bearish_confluence and be_conf:
        return "SELL", "SMC Model #2: FVG/OTE + Candle Confirmation"

    if patterns.get('turtle_soup_buy') and bu_conf:
        return "BUY", "SMC Model #3: Stop Hunt + Candle Confirmation"
        
    if patterns.get('turtle_soup_sell') and be_conf:
        return "SELL", "SMC Model #3: Stop Hunt + Candle Confirmation"

    return "NEUTRAL", "SMC: Waiting for high-probability PA trigger"

