from datetime import datetime
import pytz
import pandas as pd
from core.indicators import Indicators
from core.patterns import detect_patterns
def analyze_ict_setup(candles, df=None, patterns=None):
    if df is None:
        if not candles or len(candles) < 30: return "NEUTRAL", "Insufficient data"
        df = pd.DataFrame(candles)
    ict = patterns if patterns else detect_patterns(candles, df=df)
    ny_tz = pytz.timezone('America/New_York')
    now_ny = datetime.now(ny_tz)
    now_hour = now_ny.hour
    is_london_sb = (3 <= now_hour < 4)
    is_am_sb     = (10 <= now_hour < 11)
    is_pm_sb     = (14 <= now_hour < 15)
    in_sb_window = is_london_sb or is_am_sb or is_pm_sb
    if in_sb_window:
        if ict.get('ict_bullish_mss') and ict.get('ict_bullish_fvg'):
            return "BUY", "ICT M1: Silver Bullet (MSS + FVG)"
        if ict.get('ict_bearish_mss') and ict.get('ict_bearish_fvg'):
            return "SELL", "ICT M1: Silver Bullet (MSS + FVG)"
    if ict.get('turtle_soup_buy') and ict.get('ict_bullish_fvg'):
        return "BUY", "ICT M2: Cameron's Model (Sweep + FVG)"
    if ict.get('turtle_soup_sell') and ict.get('ict_bearish_fvg'):
        return "SELL", "ICT M2: Cameron's Model (Sweep + FVG)"
    if ict.get('bullish_ifvg') and ict.get('ict_bullish_mss'):
        return "BUY", "ICT M3: Inversion FVG (Violation)"
    if ict.get('bearish_ifvg') and ict.get('ict_bearish_mss'):
        return "SELL", "ICT M3: Inversion FVG (Violation)"
    if ict.get('turtle_soup_buy'):
        return "BUY", "ICT M4: Turtle Soup (Stop Hunt)"
    if ict.get('turtle_soup_sell'):
        return "SELL", "ICT M4: Turtle Soup (Stop Hunt)"
    if ict.get('ict_bullish_mss') and df['close'].iloc[-1] > df['open'].iloc[-1]:
        return "BUY", "ICT M5: CRT (Candle Reclaim)"
    if ict.get('ict_bearish_mss') and df['close'].iloc[-1] < df['open'].iloc[-1]:
        return "SELL", "ICT M5: CRT (Candle Reclaim)"
    if ict.get('ote_bullish'):
        return "BUY", "ICT M6: OTE (Optimal Trade Entry)"
    if ict.get('ote_bearish'):
        return "SELL", "ICT M6: OTE (Optimal Trade Entry)"
    if ict.get('cisd_bullish'):
        return "BUY", "ICT M7: CISD (Delivery Shift)"
    if ict.get('cisd_bearish'):
        return "SELL", "ICT M7: CISD (Delivery Shift)"
    if ict.get('po3_manipulation'):
        direction = "BUY" if ict.get('turtle_soup_buy') else "SELL"
        return direction, "ICT M8: PO3 (AMD Manipulation)"
    return "NEUTRAL", "ICT: Scanning for model confluence"