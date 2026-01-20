from core.news_manager import NewsManager
import logging

logger = logging.getLogger("NewsFilter")

# Singleton instance of the robust Calendar Manager
_manager = NewsManager()

def is_high_impact_news_near(symbol):
    """
    Checks ForexFactory Calendar for high impact news within 30 mins (pre/post).
    Returns (is_blocked, headline, time_info)
    """
    try:
        # Check buffer: 35 mins before/after to be safe
        is_active, event_name, mins_diff = _manager.get_active_impact(symbol, buffer_minutes=35)
        
        if is_active:
            status = "Upcoming" if mins_diff > 0 else "Ongoing/Recent"
            headline = f"BIG NEWS: {event_name}"
            time_info = f"{status} ({abs(mins_diff)}m)"
            return True, headline, time_info
        
            return True, headline, time_info
        
        return False, "", ""
        
    except Exception as e:
        logger.error(f"News Check Error: {e}")
        return False, "", ""

def get_next_news_info(symbol):
    """
    Returns (EventName, MinutesUntil, Link) for display purposes.
    """
    try:
        return _manager.get_upcoming_event(symbol)
    except:
        return None, None, None