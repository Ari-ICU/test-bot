import feedparser
import logging
from datetime import datetime, timedelta

logger = logging.getLogger("NewsFilter")

class NewsFilter:
    def __init__(self, sources):
        self.sources = sources
        self.last_signal_time = datetime.now() - timedelta(minutes=10)
        
        # Asset Class Keywords
        self.forex_keywords = ["USD", "EUR", "GBP", "JPY", "GOLD", "XAU", "CENTRAL BANK"]
        
        # Fundamental Economic Indicators
        self.econ_keywords = ["CPI", "GDP", "FOMC", "INTEREST RATE", "INFLATION", "EMPLOYMENT", "PAYROLLS"]

        # Psychological Sentiment Keywords
        self.bullish_keywords = ["surge", "rally", "growth", "stable", "hawkish", "bull"]
        self.bearish_keywords = ["crash", "plunge", "risk", "panic", "dovish", "bear", "slump"]

    def analyze_sentiment_multiplier(self, title):
        """
        Market Psychology Advice: Fear and greed drive fluctuations.
        Returns a risk multiplier (0.5 for high fear/volatility, 1.0 for stable).
        """
        t = title.lower()
        # High-impact 'Panic' or 'Crash' words should trigger a safety reduction in lot sizes
        if any(word in t for word in ["crash", "panic", "crisis", "black swan"]):
            return 0.5 
        return 1.0

    def get_news_category(self, title):
        t = title.upper()
        if any(k in t for k in self.econ_keywords):
            return "FUNDAMENTAL" # Prioritize economic indicators
        if any(k in t for k in self.forex_keywords):
            return "FOREX"
        return "UNKNOWN"

    def get_sentiment_signal(self, current_symbol="XAUUSD"):
        """
        Returns: (Action, Reason, Category, RiskMultiplier)
        """
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

                    # Bearish/Fear Sentiment
                    for kw in self.bearish_keywords:
                        if kw in title.lower():
                            self.last_signal_time = datetime.now()
                            logger.warning(f"🧠 Market Psychology (Fear): {title}")
                            return "SELL", f"Fund. ({kw}): {title[:30]}", category, risk_mod

                    # Bullish Sentiment
                    for kw in self.bullish_keywords:
                        if kw in title.lower():
                            self.last_signal_time = datetime.now()
                            logger.info(f"🧠 Market Psychology (Greed): {title}")
                            return "BUY", f"Fund. ({kw}): {title[:30]}", category, risk_mod
                            
            except Exception as e:
                logger.error(f"News Analysis Error: {e}")
        
        return "NEUTRAL", "", "NONE", 1.0