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
            "https://feeds.feedburner.com/dailyfx/news",
            "https://www.whitehouse.gov/briefing-room/statements-releases/feed/", # Official WH releases
            "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=401&keywords=Trump", # CNBC Trump News
            "https://www.investing.com/rss/news_285.rss" # Investing.com Central Banks
        ]
        self.keywords = {
            "BUY": ["surge", "rally", "soar", "jump", "bull", "climb", "gain", "breakout", "high", "positive", "hawkish", "expansion"],
            "SELL": ["plunge", "crash", "drop", "sink", "bear", "slide", "loss", "breakdown", "low", "negative", "dovish", "contraction"],
            "TRUMP": ["Trump", "Tariff", "Trade War", "Policy", "MAGA", "Deportation", "Deregulation"],
            "WHITEHOUSE": ["White House", "President", "Executive Order", "Administration", "Treasury"]
        }
        self.asset_map = {
            "XAU": ["GOLD", "XAU", "METAL", "SAFE HAVEN"],
            "BTC": ["BITCOIN", "BTC", "CRYPTO", "ETHEREUM", "ELON"],
            "EUR": ["EUR", "EURO", "ECB"],
            "USD": ["USD", "DOLLAR", "DXY", "FED", "FOMC", "POWELL", "INFLATION", "CPI"]
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
                for item in root.findall('.//item')[:15]: # Scan more items
                    title = item.find('title').text
                    if not title: continue
                    title_upper = title.upper()
                    
                    # 1. Check for TRUMP or WHITE HOUSE (General Market Drivers)
                    is_political = any(kw.upper() in title_upper for kw in self.keywords["TRUMP"] + self.keywords["WHITEHOUSE"])
                    is_relevant = any(tk in title_upper for tk in target_keywords)

                    if not (is_political or is_relevant):
                        continue
                        
                    # 2. Check Direction (Prioritize Sell/Risk-Off if 'Tariff' or 'Trade War')
                    if any(w.upper() in title_upper for w in ["TARIFF", "TRADE WAR", "SANCTION"]):
                         found_signal = ("SELL", f"🚨 Politic/Trade: {title[:50]}...")
                         break

                    for word in self.keywords["BUY"]:
                        if word.upper() in title_upper:
                             header = "📈 Politic/WH" if is_political else "News"
                             found_signal = ("BUY", f"{header}: {title[:50]}...")
                             break
                    
                    if found_signal[0] != "NEUTRAL": break

                    for word in self.keywords["SELL"]:
                        if word.upper() in title_upper:
                             header = "📉 Politic/WH" if is_political else "News"
                             found_signal = ("SELL", f"{header}: {title[:50]}...")
                             break
                    
                    # If political but no direct direction, mark as Neutral but show anyway
                    if is_political and found_signal[0] == "NEUTRAL":
                         found_signal = ("NEUTRAL", f"🏛 {title[:60]}...")
                    
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