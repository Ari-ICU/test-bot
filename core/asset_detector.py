import logging

logger = logging.getLogger("AssetDetector")

def detect_asset_type(symbol: str) -> str:
    """
    Classify symbol as 'forex' or 'crypto'.
    """
    symbol_upper = symbol.upper().replace('M', '').replace('.', '')
    
    crypto_keywords = ["BTC", "ETH", "ADA", "DOT", "SOL", "CRYPTO", "XRP", "LTC", "LINK", "XLM", "BNB", "AVAX", "DOGE", "SHIB", "TRX", "MATIC"]
    if any(kw in symbol_upper for kw in crypto_keywords):
        return "crypto"
    return "forex"

def detect_sector(symbol: str) -> str:
    """
    Categorize asset into sectors for concentration risk management (Image Ref: Concentration risk).
    For Forex, it groups by the primary currency to avoid over-exposure to one economy (Country Risk).
    """
    symbol_upper = symbol.upper().replace('M', '').replace('.', '')
    
    if any(kw in symbol_upper for kw in ["XAU", "GOLD"]):
        return "sector_gold"
    if any(kw in symbol_upper for kw in ["XAG", "SILVER"]):
        return "sector_silver"
    if any(kw in symbol_upper for kw in ["BTC", "ETH", "SOL", "DOGE"]):
        return "sector_crypto"
    if any(kw in symbol_upper for kw in ["US30", "NAS100", "SPX500", "GER30", "HK50"]):
        return "sector_indices"
    
    # Forex Sectors (grouped by major currency to handle Country/Economy Risk)
    if "USD" in symbol_upper: return "sector_usd"
    if "EUR" in symbol_upper: return "sector_eur"
    if "GBP" in symbol_upper: return "sector_gbp"
    if "JPY" in symbol_upper: return "sector_jpy"
    if "CHF" in symbol_upper: return "sector_chf"
    if "AUD" in symbol_upper: return "sector_aud"
    if "CAD" in symbol_upper: return "sector_cad"
    if "NZD" in symbol_upper: return "sector_nzd"
    
    return "sector_other"

def get_risk_profile(symbol: str) -> str:
    """
    Classify assets as 'risk-on' or 'risk-off' for liquidity risk diversification (Image Ref: Liquidity risk).
    """
    symbol_upper = symbol.upper().replace('M', '').replace('.', '')
    
    # Risk-Off Assets (Safe Havens)
    risk_off_keywords = ["XAU", "GOLD", "JPY", "CHF", "USD"]
    
    # If it's a pair like EURUSD, it's a mix, but we'll classify based on the presence of safety.
    if any(kw in symbol_upper for kw in ["XAU", "GOLD", "JPY", "CHF"]):
        return "risk-off"
    return "risk-on"