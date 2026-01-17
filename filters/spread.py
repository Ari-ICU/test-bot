import logging

logger = logging.getLogger("SpreadFilter")

def is_spread_fine(symbol, bid, ask, max_spread_limit=0.50):
    """
    Checks if the current market spread is within acceptable limits.
    """
    if bid == 0 or ask == 0:
        return False
        
    current_spread = ask - bid
    
    # 1. Handle Bitcoin (BTC spreads are much larger, e.g., 10.0 - 50.0)
    if "BTC" in symbol.upper():
        return current_spread <= 50.0  # Allow up to 50.0 spread for BTC
        
    # 2. Handle Gold (XAU)
    # Increase the limit slightly (e.g., 0.80) to account for broker markups
    if "XAU" in symbol.upper():
        return current_spread <= 0.80
        
    # 3. Default fallback for other pairs
    return current_spread <= max_spread_limit