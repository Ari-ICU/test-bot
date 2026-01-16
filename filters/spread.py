import logging

logger = logging.getLogger("SpreadFilter")

def is_spread_fine(symbol, bid, ask, max_spread_limit=0.50):
    """
    Checks if the current market spread is within acceptable limits.
    """
    if bid == 0 or ask == 0:
        return False
        
    current_spread = ask - bid
    
    # Example logic: XAUUSD typically needs tighter spreads
    if "XAU" in symbol.upper() and current_spread > max_spread_limit:
        return False
        
    return current_spread <= max_spread_limit