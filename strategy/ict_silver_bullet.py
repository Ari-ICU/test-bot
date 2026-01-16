from datetime import datetime, timedelta
import pandas as pd
from core.indicators import Indicators
from core.patterns import detect_patterns

def analyze_ict_setup(candles):
    if not candles or len(candles) < 30: return "NEUTRAL", ""
    
    # Get current time in Cambodia (UTC+7)
    # Using UTC + 7 hours offset
    now_kh = datetime.utcnow() + timedelta(hours=7)
    now_hour = now_kh.hour

    # ICT Silver Bullet Windows (Converted to Cambodia Time GMT+7):
    # London Session: 10:00 - 11:00 AM (NYC) -> 21:00 - 22:00 (KH)
    # PM Session: 2:00 - 3:00 PM (NYC) -> 01:00 - 02:00 AM (KH)
    is_london_sb = (21 <= now_hour < 22)
    is_pm_sb = (1 <= now_hour < 2)

    if not (is_london_sb or is_pm_sb):
        return "NEUTRAL", f"Outside ICT Silver Bullet Hours (KH Time: {now_kh.strftime('%H:%M')})"

    df = pd.DataFrame(candles)
    is_squeezing = Indicators.is_bollinger_squeeze(df)
    ict = detect_patterns(candles) 
    
    # ICT TBS BUY: MSS + FVG Displacement during a Squeeze
    if is_squeezing and ict.get('ict_bullish_mss') and ict.get('ict_bullish_fvg'):
        return "BUY", "ICT + TBS: Squeeze + MSS/FVG Displacement"

    # ICT TBS SELL: MSS + FVG Displacement during a Squeeze
    if is_squeezing and ict.get('ict_bearish_mss') and ict.get('ict_bearish_fvg'):
        return "SELL", "ICT + TBS: Squeeze + MSS/FVG Displacement"
            
    return "NEUTRAL", ""