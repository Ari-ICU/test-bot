from datetime import datetime, timedelta
import pandas as pd
from core.indicators import Indicators
from core.patterns import detect_patterns

def analyze_ict_setup(candles, df=None, patterns=None):
    if df is None:
        if not candles or len(candles) < 30: return "NEUTRAL", "Insufficient data"
        df = pd.DataFrame(candles)
    
    # Get current time in Cambodia (UTC+7)
    now_kh = datetime.utcnow() + timedelta(hours=7)
    now_hour = now_kh.hour

    # ICT Silver Bullet Windows (Converted to Cambodia Time GMT+7):
    # London Session: 21:00 - 22:00 (KH) | PM Session: 01:00 - 02:00 AM (KH)
    is_london_sb = (21 <= now_hour < 22)
    is_pm_sb = (1 <= now_hour < 2)

    if not (is_london_sb or is_pm_sb):
        return "NEUTRAL", f"Outside ICT Silver Bullet Hours (KH Time: {now_kh.strftime('%H:%M')})"

    # Use pre-calculated squeeze if available
    if 'is_squeezing' in df:
        is_squeezing = df['is_squeezing'].iloc[-1]
    else:
        is_squeezing = Indicators.is_bollinger_squeeze(df)
        
    if patterns is None:
        ict = detect_patterns(candles, df=df) 
    else:
        ict = patterns
    
    # ICT TBS BUY: MSS + FVG Displacement during a Squeeze
    if is_squeezing:
        if ict.get('ict_bullish_mss') and ict.get('ict_bullish_fvg'):
            return "BUY", "ICT + TBS: Squeeze + MSS/FVG Displacement"
        if ict.get('ict_bearish_mss') and ict.get('ict_bearish_fvg'):
            return "SELL", "ICT + TBS: Squeeze + MSS/FVG Displacement"
        return "NEUTRAL", "ICT: Squeeze active, waiting for MSS/FVG"
            
    return "NEUTRAL", "ICT: No Bollinger Squeeze"