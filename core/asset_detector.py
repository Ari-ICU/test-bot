import logging

logger = logging.getLogger("AssetDetector")

def detect_asset_type(symbol: str) -> str:
    """
    Classify symbol as 'forex' or 'crypto'.
    Examples: XAUUSD/EURUSD -> 'forex'; BTCUSD/ETHUSD -> 'crypto'.
    """
    symbol_upper = symbol.upper().replace('M', '')  # Ignore suffixes like 'm'
    
    forex_keywords = [
        "XAU", "XAG", "EUR", "GBP", "USD", "JPY", "AUD", "CAD", "CHF", "NZD", 
        "HKD", "SGD", "MXN", "ZAR", "CNH", "TRY", "RUB", "BRL"
    ]
    crypto_keywords = [
        "BTC", "ETH", "ADA", "DOT", "SOL", "CRYPTO", "XRP", "LTC", "LINK", 
        "XLM", "BNB", "AVAX", "DOGE", "SHIB", "TRX", "MATIC"
    ]
    
    if any(kw in symbol_upper for kw in crypto_keywords):
        return "crypto"
    elif any(kw in symbol_upper for kw in forex_keywords):
        return "forex"
    else:
        # Check for common crypto suffixes or patterns if keywords fail
        if "USD" in symbol_upper and (len(symbol_upper) > 6 or symbol_upper[:3] in ["TRX", "XRP"]):
             return "crypto"
        return "forex"