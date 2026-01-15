from datetime import datetime
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

def is_market_open(tz_name="Auto", start_hour=8, end_hour=20):
    if tz_name == "Auto":
        # Check if ANY major session is open
        for _, config in SESSIONS.items():
            try:
                tz = ZoneInfo(config['tz'])
                now = datetime.now(tz)
                h = now.hour
                if config['start'] <= h < config['end']:
                    return True
            except: continue
        return False
    else:
        # Simple manual time check
        now = datetime.now()
        return start_hour <= now.hour < end_hour

def is_silver_bullet():
    """Checks for ICT Silver Bullet hours (NY Time)."""
    try:
        ny_tz = ZoneInfo("America/New_York")
        h = datetime.now(ny_tz).hour
        return h in [10, 14]
    except: return False