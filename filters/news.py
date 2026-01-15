import feedparser
import logging
from datetime import datetime, timedelta

logger = logging.getLogger("NewsFilter")

class NewsFilter:
    def __init__(self, sources):
        self.sources = sources
        self.last_signal_time = datetime.now() - timedelta(minutes=10)
        
        # Asset Class Keywords
        self.crypto_keywords = ["BITCOIN", "BTC", "ETH", "ETHEREUM", "SOLANA", "CRYPTO"]
        self.forex_keywords = ["USD", "EUR", "GBP", "JPY", "CAD", "AUD", "GOLD", "XAU", "OIL"]
        
        # Economic Events (Affects EVERYTHING -> FOREX usually)
        self.econ_keywords = ["CPI", "GDP", "FOMC", "FED", "RATE HIKE", "INFLATION"]

        self.bullish_keywords = ["surge", "soar", "jump", "rally", "record", "bull", "gain"]
        self.bearish_keywords = ["crash", "plunge", "drop", "slump", "bear", "loss", "fall"]

    def get_news_category(self, title):
        """Determines if news is CRYPTO, FOREX, or ALL"""
        t = title.upper()
        if any(k in t for k in self.crypto_keywords):
            return "CRYPTO"
        if any(k in t for k in self.forex_keywords):
            return "FOREX"
        if any(k in t for k in self.econ_keywords):
            return "FOREX" # Economic news usually trades on Forex pairs (USD)
        return "UNKNOWN"

    def get_sentiment_signal(self):
        """
        Returns: ("BUY"|"SELL"|"NEUTRAL", "Reason", "CATEGORY")
        """
        if (datetime.now() - self.last_signal_time).seconds < 300:
            return "NEUTRAL", "", "NONE"

        for source in self.sources:
            try:
                if not source.get('url'): continue
                feed = feedparser.parse(source['url'])
                
                for entry in feed.entries[:3]:
                    title = entry.title
                    category = self.get_news_category(title)
                    
                    if category == "UNKNOWN": continue # Skip irrelevant news

                    # SELL Logic
                    for kw in self.bearish_keywords:
                        if kw in title.lower():
                            self.last_signal_time = datetime.now()
                            logger.warning(f"📉 {category} News: {title}")
                            return "SELL", f"News ({kw}): {title[:40]}...", category

                    # BUY Logic
                    for kw in self.bullish_keywords:
                        if kw in title.lower():
                            self.last_signal_time = datetime.now()
                            logger.info(f"📈 {category} News: {title}")
                            return "BUY", f"News ({kw}): {title[:40]}...", category
                            
            except Exception as e:
                logger.error(f"News Error: {e}")
        
        return "NEUTRAL", "", "NONE"