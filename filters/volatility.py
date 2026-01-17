import pandas as pd
import logging
from core.indicators import Indicators  # Fixed: Import the class, not a non-existent function

logger = logging.getLogger("VolatilityFilter")

def is_volatility_sufficient(candles, min_atr_threshold=0.01, max_atr_threshold=500.0):
    """
    FIXED: Renamed to match main.py expectations.
    Checks if market volatility is within safe and active limits using ATR.
    """
    try:
        if not candles or len(candles) < 20:
            return False

        # Convert candles list to DataFrame for indicator calculation
        df = pd.DataFrame(candles)
        
        # Fixed: Call the static method from the Indicators class
        atr_series = Indicators.calculate_atr(df)
        
        if atr_series.empty:
            return False
            
        current_atr = atr_series.iloc[-1]

        # 1. Check for 'Dead' Market (ATR too low)
        if current_atr < min_atr_threshold:
            # logger.warning(f"Volatility too low: {current_atr}")
            return False 

        # 2. Check for 'Chaotic' Market (ATR too high)
        if current_atr > max_atr_threshold:
            logger.warning(f"Volatility too high: {current_atr}")
            return False 

        return True
    except Exception as e:
        logger.error(f"Volatility check error: {e}")
        return False

