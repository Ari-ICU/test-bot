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


# --- SENTIMENT ANALYSIS (RSS) ---
import requests
import xml.etree.ElementTree as ET
from datetime import datetime

class NewsSentimentAnalyzer:
    def __init__(self):
        self.rss_urls = [
            "https://www.forexlive.com/feed/news", 
            "https://feeds.feedburner.com/dailyfx/news" 
        ]
        self.keywords = {
            "BUY": ["surge", "rally", "soar", "jump", "bull", "climb", "gain", "breakout", "high"],
            "SELL": ["plunge", "crash", "drop", "sink", "bear", "slide", "loss", "breakdown", "low"]
        }
        self.asset_map = {
            "XAU": ["GOLD", "XAU", "METAL"],
            "BTC": ["BITCOIN", "BTC", "CRYPTO"],
            "EUR": ["EUR", "EURO"],
            "USD": ["USD", "DOLLAR", "DXY"]
        }
        # Caching
        self.last_fetch_time = 0
        self.cached_result = ("NEUTRAL", "No news")

    def fetch_signals(self, symbol):
        """
        Scans RSS feeds with 60s caching.
        """
        import time
        if time.time() - self.last_fetch_time < 60:
            return self.cached_result
            
        sym_upper = symbol.upper()
        target_keywords = []
        for k, v in self.asset_map.items():
            if k in sym_upper: target_keywords.extend(v); break
        if not target_keywords: target_keywords = [sym_upper]
        
        headers = {'User-Agent': 'Mozilla/5.0'}
        
        found_signal = ("NEUTRAL", "No significant news sentiment")
        
        for url in self.rss_urls:
            try:
                resp = requests.get(url, headers=headers, timeout=5)
                if resp.status_code != 200: continue
                
                # Parse XML
                root = ET.fromstring(resp.content)
                
                # Scan Items
                for item in root.findall('.//item')[:10]: # Top 10 only
                    title = item.find('title').text
                    if not title: continue
                    title_upper = title.upper()
                    
                    # 1. Check if relevant to symbol
                    if not any(tk in title_upper for tk in target_keywords):
                        continue
                        
                    # 2. Check Direction
                    for word in self.keywords["BUY"]:
                        if word.upper() in title_upper:
                             found_signal = ("BUY", f"News Sentiment: {title[:40]}...")
                             break
                    
                    for word in self.keywords["SELL"]:
                        if word.upper() in title_upper:
                             found_signal = ("SELL", f"News Sentiment: {title[:40]}...")
                             break
                    
                    if found_signal[0] != "NEUTRAL": break
            except Exception as e:
                logger.debug(f"RSS Scan Error ({url}): {e}")
            if found_signal[0] != "NEUTRAL": break

        self.cached_result = found_signal
        self.last_fetch_time = time.time()
        return found_signal

_sentiment_analyzer = NewsSentimentAnalyzer()

def analyze_sentiment(symbol):
    return _sentiment_analyzer.fetch_signals(symbol)