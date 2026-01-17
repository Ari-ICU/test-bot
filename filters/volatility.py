import pandas as pd
import logging
from core.indicators import Indicators
from core.asset_detector import detect_asset_type

logger = logging.getLogger("VolatilityFilter")

def is_volatility_sufficient(candles, symbol, min_atr_threshold=0.01, max_atr_threshold=500.0):
    """
    Checks if market volatility is within safe and active limits using ATR.
    Dynamic thresholds per asset.
    """
    try:
        if not candles or len(candles) < 20:
            return False

        df = pd.DataFrame(candles)
        atr_series = Indicators.calculate_atr(df)
        
        if atr_series.empty:
            return False
            
        current_atr = atr_series.iloc[-1]
        asset_type = detect_asset_type(symbol)
        
        # Dynamic thresholds
        if asset_type == "crypto":
            min_atr = 10.0  # BTC needs movement
            max_atr = 2000.0  # Allow spikes
        else:  # forex
            min_atr = min_atr_threshold
            max_atr = 50.0  # Tighter for XAU/EUR

        if current_atr < min_atr:
            logger.debug(f"Volatility too low for {symbol}: {current_atr} < {min_atr}")
            return False 

        if current_atr > max_atr:
            logger.warning(f"Volatility too high for {symbol}: {current_atr} > {max_atr}")
            return False 

        logger.debug(f"Volatility OK for {symbol}: ATR={current_atr}")
        return True
    except Exception as e:
        logger.error(f"Volatility check error: {e}")
        return False