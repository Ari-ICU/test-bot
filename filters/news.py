import feedparser
import logging
from datetime import datetime, timedelta

logger = logging.getLogger("NewsFilter")

class NewsFilter:
    def __init__(self, sources=None):
        # Default source if none provided
        self.sources = sources if sources else [{"url": "https://www.forexfactory.com/ff_calendar_thisweek.xml"}]
        self.last_signal_time = datetime.now() - timedelta(minutes=10)
        
        # Asset Class Keywords
        self.forex_keywords = ["USD", "EUR", "GBP", "JPY", "GOLD", "XAU", "CENTRAL BANK"]
        
        # Fundamental Economic Indicators
        self.econ_keywords = ["CPI", "GDP", "FOMC", "INTEREST RATE", "INFLATION", "EMPLOYMENT", "PAYROLLS"]

        # Psychological Sentiment Keywords
        self.bullish_keywords = ["surge", "rally", "growth", "stable", "hawkish", "bull"]
        self.bearish_keywords = ["crash", "plunge", "risk", "panic", "dovish", "bear", "slump"]

    def analyze_sentiment_multiplier(self, title):
        t = title.lower()
        if any(word in t for word in ["crash", "panic", "crisis", "black swan"]):
            return 0.5 
        return 1.0

    def get_news_category(self, title):
        t = title.upper()
        if any(k in t for k in self.econ_keywords):
            return "FUNDAMENTAL"
        if any(k in t for k in self.forex_keywords):
            return "FOREX"
        return "UNKNOWN"

    def get_sentiment_signal(self, current_symbol="XAUUSD"):
        if (datetime.now() - self.last_signal_time).seconds < 300:
            return "NEUTRAL", "", "NONE", 1.0

        for source in self.sources:
            try:
                if not source.get('url'): continue
                feed = feedparser.parse(source['url'])
                
                for entry in feed.entries[:3]:
                    title = entry.title
                    category = self.get_news_category(title)
                    risk_mod = self.analyze_sentiment_multiplier(title)
                    
                    if category == "UNKNOWN": continue 

                    for kw in self.bearish_keywords:
                        if kw in title.lower():
                            self.last_signal_time = datetime.now()
                            return "SELL", f"Fund. ({kw}): {title[:30]}", category, risk_mod

                    for kw in self.bullish_keywords:
                        if kw in title.lower():
                            self.last_signal_time = datetime.now()
                            return "BUY", f"Fund. ({kw}): {title[:30]}", category, risk_mod
                            
            except Exception as e:
                logger.error(f"News Analysis Error: {e}")
        
        return "NEUTRAL", "", "NONE", 1.0

# --- FIXED: FUNCTION CALLED BY MAIN.PY ---
def is_high_impact_news_near(symbol):
    """
    Checks if there is high-impact news for the symbol or USD.
    This fulfills the requirement in main.py: 'if news.is_high_impact_news_near(symbol):'
    """
    try:
        # Initialize a temporary filter to check headlines
        nf = NewsFilter() 
        action, reason, category, risk_mod = nf.get_sentiment_signal(symbol)
        
        # If the news is 'Fundamental' (CPI, GDP, etc.), consider it high impact
        if category == "FUNDAMENTAL" and action != "NEUTRAL":
            logger.warning(f"High Impact News Detected: {reason}")
            return True
            
        return False
    except Exception as e:
        logger.error(f"Error in news filter wrapper: {e}")
        return False