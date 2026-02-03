import logging
from core.asset_detector import detect_asset_type
logger = logging.getLogger("SpreadFilter")
def is_spread_fine(symbol, bid, ask, max_spread_limit=0.50):
    """
    Checks if the current market spread is within acceptable limits.
    Dynamic based on asset type.
    """
    logger.debug(f"Spread Check for {symbol}: Bid={bid}, Ask={ask}")
    if bid == 0 or ask == 0:
        logger.warning(f"Invalid prices for {symbol}: Bid={bid}, Ask={ask} – Check MT5 symbol selection")
        return False
    current_spread = ask - bid
    asset_type = detect_asset_type(symbol)
    if asset_type == "crypto":
        max_allowed = 100.0
    elif "XAU" in symbol.upper():
        max_allowed = 1.0
    else:
        max_allowed = max_spread_limit
    is_fine = current_spread <= max_allowed
    if not is_fine:
        logger.warning(f"Spread too wide for {symbol} ({asset_type}): {current_spread} > {max_allowed}")
    return is_fine
