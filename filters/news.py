import feedparser
import logging
from datetime import datetime, timedelta

logger = logging.getLogger("NewsFilter")

class NewsFilter:
    def __init__(self, sources):
        self.sources = sources
        self.last_signal_time = datetime.now() - timedelta(minutes=10)
        
        # 1. Assets to Watch (Currencies & Crypto)
        self.target_assets = [
            "USD", "EUR", "GBP", "JPY", "CAD", "AUD", "NZD", "CHF",  # Forex
            "BTC", "ETH", "BITCOIN", "ETHEREUM", "XRP", "SOL",       # Crypto
            "GOLD", "XAU", "OIL", "WTI"                              # Commodities
        ]

        # 2. High Impact Economic Keywords
        self.impact_keywords = [
            "CPI", "GDP", "NFP", "PAYROLL", "FOMC", "FED", 
            "RATE HIKE", "RATE CUT", "INFLATION", "CENTRAL BANK", "POWELL"
        ]

        # 3. Directional Sentiment
        self.bullish_keywords = [
            "surge", "soar", "jump", "rally", "record high", "bull", 
            "upgrade", "breakout", "gain", "climb", "strong", "positive",
            "hike", "beats", "exceeds" # 'Hike' usually good for currency value short-term
        ]
        
        self.bearish_keywords = [
            "crash", "plunge", "tumble", "slump", "bear", "collapse", 
            "downgrade", "loss", "drop", "weak", "negative", 
            "cut", "misses", "falls"
        ]

    def get_sentiment_signal(self):
        """
        Scans RSS feeds for Forex/Crypto news and returns a signal.
        Returns: ("BUY"|"SELL"|"NEUTRAL", "Headline Reason")
        """
        # Cooldown check (don't spam signals every second)
        if (datetime.now() - self.last_signal_time).seconds < 300: # 5 mins
            return "NEUTRAL", ""

        for source in self.sources:
            try:
                if not source.get('url'): continue
                
                # Parse RSS Feed
                feed = feedparser.parse(source['url'])
                
                # Check top 5 latest articles
                for entry in feed.entries[:5]:
                    title = entry.title.upper()
                    
                    # A. Check if news is relevant (contains Target Asset OR Impact Keyword)
                    is_relevant = any(asset in title for asset in self.target_assets) or \
                                  any(imp in title for imp in self.impact_keywords)
                    
                    if not is_relevant:
                        continue

                    # B. Determine Direction
                    # SELL Logic
                    for kw in self.bearish_keywords:
                        if kw.upper() in title:
                            self.last_signal_time = datetime.now()
                            # Special handling: "CPI Falls" -> Good for Stocks/Crypto, Bad for Currency?
                            # For simplicity: Negative words = SELL signal for the mentioned asset
                            logger.warning(f"📉 NEWS TRADE: {entry.title}")
                            return "SELL", f"News ({kw}): {entry.title}"

                    # BUY Logic
                    for kw in self.bullish_keywords:
                        if kw.upper() in title:
                            self.last_signal_time = datetime.now()
                            logger.info(f"📈 NEWS TRADE: {entry.title}")
                            return "BUY", f"News ({kw}): {entry.title}"
                            
            except Exception as e:
                logger.error(f"News fetch error: {e}")
        
        return "NEUTRAL", ""