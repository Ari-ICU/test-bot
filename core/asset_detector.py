import logging

logger = logging.getLogger("AssetDetector")

def detect_asset_type(symbol: str) -> str:
    """
    Classify symbol as 'forex' or 'crypto'.
    Examples: XAUUSD/EURUSD -> 'forex'; BTCUSD/ETHUSD -> 'crypto'.
    """
    symbol_upper = symbol.upper().replace('M', '')  # Ignore suffixes like 'm'
    
    forex_keywords = ["XAU", "EUR", "GBP", "USD", "JPY", "AUD", "CAD", "CHF", "NZD"]
    crypto_keywords = ["BTC", "ETH", "ADA", "DOT", "SOL", "CRYPTO"]
    
    if any(kw in symbol_upper for kw in crypto_keywords):
        logger.info(f"Detected CRYPTO: {symbol}")
        return "crypto"
    elif any(kw in symbol_upper for kw in forex_keywords):
        logger.info(f"Detected FOREX: {symbol}")
        return "forex"
    else:
        logger.warning(f"Unknown asset type for {symbol}; defaulting to forex")
        return "forex"