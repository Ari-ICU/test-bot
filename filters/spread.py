# spread.py (Fixed: Added logger setup to prevent NameError)
import logging
from core.asset_detector import detect_asset_type  # Assuming this is imported elsewhere or add if needed

logger = logging.getLogger("SpreadFilter")  # FIXED: Define logger here, like in other filters

def is_spread_fine(symbol, bid, ask, max_spread_limit=0.50):
    """
    Checks if the current market spread is within acceptable limits.
    Dynamic based on asset type.
    """
    logger.debug(f"Spread Check for {symbol}: Bid={bid}, Ask={ask}")  # FIXED: Log raw values
    
    if bid == 0 or ask == 0:
        logger.warning(f"Invalid prices for {symbol}: Bid={bid}, Ask={ask} – Check MT5 symbol selection")  # FIXED: More specific warning
        return False
        
    current_spread = ask - bid
    asset_type = detect_asset_type(symbol)
    
    # Crypto: Allow wider spreads (e.g., 100+ for BTC during volatility)
    if asset_type == "crypto":
        max_allowed = 100.0
    # Forex: XAU tighter than majors
    elif "XAU" in symbol.upper():
        max_allowed = 1.0  # Increased from 0.80
    else:
        max_allowed = max_spread_limit
    
    is_fine = current_spread <= max_allowed
    if not is_fine:
        logger.warning(f"Spread too wide for {symbol} ({asset_type}): {current_spread} > {max_allowed}")
    
    return is_fine