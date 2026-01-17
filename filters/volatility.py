import pandas as pd
import logging
from core.indicators import Indicators
from core.asset_detector import detect_asset_type

logger = logging.getLogger("VolatilityFilter")

def is_volatility_sufficient(candles, symbol, min_atr_threshold=0.01, max_atr_threshold=500.0):
    """
    Checks if market volatility is within safe and active limits using ATR.
    Dynamic thresholds per asset. FIXED: Added debug logging for ATR/len(candles); relaxed crypto min for testing.
    """
    try:
        if not candles or len(candles) < 20:
            logger.info(f"Volatility: Insufficient candles for {symbol}: {len(candles)} < 20")  # FIXED: Log candle count
            return False

        df = pd.DataFrame(candles)
        atr_series = Indicators.calculate_atr(df)
        
        if atr_series.empty or pd.isna(atr_series.iloc[-1]):
            logger.warning(f"Volatility: Empty/NaN ATR for {symbol}")
            return False
            
        current_atr = atr_series.iloc[-1]
        logger.debug(f"Volatility: {symbol} ATR={current_atr:.2f} | Candles={len(candles)}")  # FIXED: Debug ATR value
        
        asset_type = detect_asset_type(symbol)
        
        # Dynamic thresholds – FIXED: Lower crypto min to 5.0 for testing (was 10.0); add tolerance
        if asset_type == "crypto":
            min_atr = 5.0  # Relaxed for BTC flat periods
            max_atr = 2000.0
        else:  # forex
            min_atr = min_atr_threshold
            max_atr = 50.0

        if current_atr < min_atr:
            logger.info(f"Volatility too low for {symbol} ({asset_type}): {current_atr:.2f} < {min_atr}")
            return False 

        if current_atr > max_atr:
            logger.warning(f"Volatility too high for {symbol} ({asset_type}): {current_atr:.2f} > {max_atr}")
            return False 

        logger.info(f"Volatility OK for {symbol} ({asset_type}): ATR={current_atr:.2f}")
        return True
    except Exception as e:
        logger.error(f"Volatility check error for {symbol}: {e}")
        return False