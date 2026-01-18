import feedparser
import logging
from datetime import datetime, timedelta
from core.asset_detector import detect_asset_type
from bot_settings import Config  # For sources

logger = logging.getLogger("NewsFilter")

class NewsFilter:
    def __init__(self, sources=None):
        conf = Config()
        self.sources = conf.get('sources', [])  # From config
        self.last_signal_time = datetime.now() - timedelta(minutes=10)
        
        # Asset Keywords (from config + extras)
        self.forex_keywords = ["USD", "EUR", "GBP", "JPY", "GOLD", "XAU", "CENTRAL BANK"]
        self.crypto_keywords = conf.get('sentiment', {}).get('crypto_keywords', []) + ["CRYPTO", "BITCOIN", "ETHEREUM"]
        
        # Fundamental/Economic
        self.econ_keywords = ["CPI", "GDP", "FOMC", "INTEREST RATE", "INFLATION", "EMPLOYMENT", "PAYROLLS", "HALVING", "ETF"]
        
        # Sentiment
        self.bullish_keywords = ["surge", "rally", "growth", "stable", "hawkish", "bull", "approval", "adoption"]
        self.bearish_keywords = ["crash", "plunge", "risk", "panic", "dovish", "bear", "slump", "ban", "hack"]

    def analyze_sentiment_multiplier(self, title):
        t = title.lower()
        if any(word in t for word in ["crash", "panic", "crisis", "black swan", "regulatory ban"]):
            return 0.5  # High risk mod
        if any(word in t for word in ["etf approval", "institutional buy"]):
            return 1.5  # Bullish boost for crypto
        return 1.0

    def get_news_category(self, title, symbol):
        t = title.upper()
        asset_type = detect_asset_type(symbol)
        if asset_type == "crypto" and any(k in t for k in self.crypto_keywords):
            return "CRYPTO"
        if asset_type == "forex" and any(k in t for k in self.forex_keywords):
            return "FOREX"
        if any(k in t for k in self.econ_keywords):
            return "FUNDAMENTAL"
        return "UNKNOWN"

    def get_sentiment_signal(self, current_symbol="XAUUSD"):
        if (datetime.now() - self.last_signal_time).seconds < 300:
            return "NEUTRAL", "", "NONE", 1.0, ""

        # Filter sources by asset type
        asset_type = detect_asset_type(current_symbol)
        relevant_sources = [s for s in self.sources if s.get('type') == asset_type or s.get('type') == 'forex']  # Forex as fallback

        for source in relevant_sources:
            try:
                if not source.get('url'): continue
                feed = feedparser.parse(source['url'])
                
                for entry in feed.entries[:3]:
                    title = entry.title
                    category = self.get_news_category(title, current_symbol)
                    risk_mod = self.analyze_sentiment_multiplier(title)
                    
                    if category == "UNKNOWN": continue 

                    for kw in self.bearish_keywords:
                        if kw in title.lower():
                            self.last_signal_time = datetime.now()
                            link = entry.link if hasattr(entry, 'link') else ""
                            return "SELL", f"News ({kw}): {title[:30]}", category, risk_mod, link

                    for kw in self.bullish_keywords:
                        if kw in title.lower():
                            self.last_signal_time = datetime.now()
                            link = entry.link if hasattr(entry, 'link') else ""
                            return "BUY", f"News ({kw}): {title[:30]}", category, risk_mod, link
                            
            except Exception as e:
                logger.error(f"News Analysis Error: {e}")
        
        return "NEUTRAL", "", "NONE", 1.0, ""

# --- FIXED: CACHING FOR NEWS FILTER ---
_news_cache = {
    'last_update': datetime.min,
    'blocked': False,
    'reason': "",
    'link': "",
    'expiry': 60  
}

def is_high_impact_news_near(symbol):
    """
    Checks if there is high-impact news for the symbol or USD/BTC.
    Returns (is_blocked, headline, link)
    """
    now = datetime.now()
    if (now - _news_cache['last_update']).total_seconds() < _news_cache['expiry']:
        return _news_cache['blocked'], _news_cache['reason'], _news_cache['link']

    try:
        nf = NewsFilter() 
        action, reason, category, risk_mod, link = nf.get_sentiment_signal(symbol)
        
        is_blocked = False
        if (category in ["FUNDAMENTAL", detect_asset_type(symbol).upper()]) and action != "NEUTRAL":
            is_blocked = True
            
        _news_cache['last_update'] = now
        _news_cache['blocked'] = is_blocked
        _news_cache['reason'] = reason
        _news_cache['link'] = link
        return is_blocked, reason, link
    except Exception as e:
        logger.error(f"Error in news filter wrapper: {e}")
        return False, "", ""