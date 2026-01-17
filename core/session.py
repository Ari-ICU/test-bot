from datetime import datetime, time
try:
    from zoneinfo import ZoneInfo
except ImportError:
    from backports.zoneinfo import ZoneInfo

from core.asset_detector import detect_asset_type

SESSIONS = {
    "London": {"start": 8, "end": 17, "tz": "Europe/London"},
    "New York": {"start": 8, "end": 17, "tz": "America/New_York"},
    "Tokyo": {"start": 9, "end": 18, "tz": "Asia/Tokyo"},
    "Sydney": {"start": 7, "end": 16, "tz": "Australia/Sydney"}
}

def get_detailed_session_status(symbol="XAUUSD"):
    """
    Returns: (bool is_open, str session_type, float risk_multiplier)
    Crypto: Always open, but adjust risk during low-liq hours.
    """
    asset_type = detect_asset_type(symbol)
    if asset_type == "crypto":
        # Crypto 24/7, but reduce risk during weekends/low vol
        now_utc = datetime.utcnow()
        is_weekend = now_utc.weekday() >= 5
        risk_mult = 0.7 if is_weekend else 1.0
        return True, "CRYPTO_24_7", risk_mult

    # Forex logic (unchanged)
    ny_tz = ZoneInfo("America/New_York")
    now_ny = datetime.now(ny_tz)
    h_ny = now_ny.hour
    
    london_tz = ZoneInfo("Europe/London")
    now_lon = datetime.now(london_tz)
    h_lon = now_lon.hour

    if (8 <= h_lon < 17) and (8 <= h_ny < 12):
        return True, "LONDON_NY_OVERLAP", 1.2

    if 17 <= h_ny < 22:
        return True, "NY_LATE_SESSION", 0.5

    for name, config in SESSIONS.items():
        tz = ZoneInfo(config['tz'])
        h = datetime.now(tz).hour
        if config['start'] <= h < config['end']:
            return True, name.upper(), 1.0
            
    return False, "CLOSED", 0.0

def is_market_open(symbol, tz_name="Auto", start_hour=8, end_hour=20):
    is_open, _, _ = get_detailed_session_status(symbol)
    return is_open

def is_silver_bullet(symbol):
    """ICT Silver Bullet hours (NY Time) – Skip for crypto."""
    if detect_asset_type(symbol) == "crypto":
        return True  # Always eligible for crypto
    try:
        ny_tz = ZoneInfo("America/New_York")
        h = datetime.now(ny_tz).hour
        return h in [10, 14]
    except: 
        return False