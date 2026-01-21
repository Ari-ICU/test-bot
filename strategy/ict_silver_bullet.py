from datetime import datetime
import pytz
import pandas as pd
from core.indicators import Indicators
from core.patterns import detect_patterns

def analyze_ict_setup(candles, df=None, patterns=None):
    if df is None:
        if not candles or len(candles) < 30: return "NEUTRAL", "Insufficient data"
        df = pd.DataFrame(candles)
    
    # 1. Setup Timezones
    ny_tz = pytz.timezone('America/New_York')
    kh_tz = pytz.timezone('Asia/Phnom_Penh') # Cambodia Time
    
    # 2. Get Current Time in New York (Algorithmic Standard)
    now_ny = datetime.now(ny_tz)
    now_hour = now_ny.hour
    
    # 3. ICT Silver Bullet Windows (New York Local Time)
    # These are the precise institutional hours for the strategy
    is_london_sb = (3 <= now_hour < 4)    # London Open: 3 AM - 4 AM NY Time
    is_am_sb     = (10 <= now_hour < 11)  # NY AM: 10 AM - 11 AM NY Time
    is_pm_sb     = (14 <= now_hour < 15)  # NY PM: 2 PM - 3 PM NY Time

    if not (is_london_sb or is_am_sb or is_pm_sb):
        local_time = datetime.now(kh_tz).strftime('%H:%M')
        ny_time = now_ny.strftime('%H:%M')
        return "NEUTRAL", f"Outside SB Hours (NY: {ny_time} | Local: {local_time})"

    # 4. Pattern Detection
    ict = patterns if patterns else detect_patterns(candles, df=df)
    
    # 5. Volatility Filter (Squeeze)
    is_squeezing = df['is_squeezing'].iloc[-1] if 'is_squeezing' in df else Indicators.is_bollinger_squeeze(df)

    # --- ENTRY STRATEGIES (Aligned with your FVG Slides) ---
    
    # Strategy A: Standard ICT (MSS + FVG Displacement)
    if ict.get('ict_bullish_mss') and ict.get('ict_bullish_fvg'):
        return "BUY", "ICT SB: MSS + FVG Displacement (NY Session)"

    if ict.get('ict_bearish_mss') and ict.get('ict_bearish_fvg'):
        return "SELL", "ICT SB: MSS + FVG Displacement (NY Session)"

    # Strategy B: Inverse FVG (Gap Violation)
    if ict.get('bullish_ifvg'):
        return "BUY", "ICT SB: iFVG Violation/Retest"
        
    if ict.get('bearish_ifvg'):
        return "SELL", "ICT SB: iFVG Violation/Retest"

    if is_squeezing:
        return "NEUTRAL", "ICT: Squeeze active, waiting for MSS/FVG"
            
    return "NEUTRAL", "ICT: Scanning for setups in SB window"