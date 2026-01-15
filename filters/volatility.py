from core.indicators import calculate_atr

def is_volatility_safe(candles, max_atr_threshold=5.0):
    """
    Checks if market volatility is within safe limits using ATR.
    """
    try:
        atr = calculate_atr(candles)
        # If ATR is too high, it's too volatile
        if atr > max_atr_threshold:
            return False 
        # If ATR is 0, we likely have bad data
        if atr == 0:
            return False 
        return True
    except Exception:
        return False

def check_spread(bid, ask, max_spread):
    """
    Simple check to ensure spread is not too wide.
    """
    return (ask - bid) <= max_spread