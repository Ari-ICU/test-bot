from datetime import datetime, time
try:
    from zoneinfo import ZoneInfo
except ImportError:
    from backports.zoneinfo import ZoneInfo

SESSIONS = {
    "London": {"start": 8, "end": 17, "tz": "Europe/London"},
    "New York": {"start": 8, "end": 17, "tz": "America/New_York"},
    "Tokyo": {"start": 9, "end": 18, "tz": "Asia/Tokyo"},
    "Sydney": {"start": 7, "end": 16, "tz": "Australia/Sydney"}
}

def get_detailed_session_status():
    """
    Advice: Volatility peaks during the London-New York overlap (08:00–12:00 GMT).
    Returns: (bool is_open, str session_type, float risk_multiplier)
    """
    ny_tz = ZoneInfo("America/New_York")
    now_ny = datetime.now(ny_tz)
    h_ny = now_ny.hour
    
    london_tz = ZoneInfo("Europe/London")
    now_lon = datetime.now(london_tz)
    h_lon = now_lon.hour

    # 1. London-NY Overlap: High Liquidity & Volatility (13:00-16:00 GMT / 08:00-11:00 NY)
    if (8 <= h_lon < 17) and (8 <= h_ny < 12):
        return True, "LONDON_NY_OVERLAP", 1.2  # Increase risk slightly for high liquidity

    # 2. NY Close / Low Liquidity Gap (Advice: Avoid range-bound strategies here)
    if 17 <= h_ny < 22:
        return True, "NY_LATE_SESSION", 0.5  # Reduce risk during liquidity drain

    # Standard check for any open session
    for name, config in SESSIONS.items():
        tz = ZoneInfo(config['tz'])
        h = datetime.now(tz).hour
        if config['start'] <= h < config['end']:
            return True, name.upper(), 1.0
            
    return False, "CLOSED", 0.0

def is_market_open(tz_name="Auto", start_hour=8, end_hour=20):
    is_open, _, _ = get_detailed_session_status()
    return is_open

def is_silver_bullet():
    """ICT Silver Bullet hours (NY Time)."""
    try:
        ny_tz = ZoneInfo("America/New_York")
        h = datetime.now(ny_tz).hour
        return h in [10, 14]
    except: return False