import feedparser
import time
import json
import logging
from datetime import datetime
from nltk.sentiment.vader import SentimentIntensityAnalyzer
import nltk
import threading

# Initialize Logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger("NewsEngine")

class NewsEngine:
    def __init__(self, config_path="config.json"):
        self.load_config(config_path)
        self.sia = self.init_analyzer()
        self.seen_news = set()
        self.news_items = []  
        self.update_interval = self.config.get('update_interval_seconds', 60)
        self.trading_pause = False  
        self.last_pause_time = 0  
        
        # Start periodic fetching in background thread
        self.thread = threading.Thread(target=self._periodic_fetch, daemon=True)
        self.thread.start()
        logger.info(f"News Engine started with {self.update_interval}s interval.")

    def load_config(self, path):
        with open(path, 'r') as f:
            self.config = json.load(f)
        logger.info(f"Loaded {len(self.config['sources'])} news sources.")

    def init_analyzer(self):
        try:
            nltk.data.find('vader_lexicon')
        except LookupError:
            logger.info("Downloading VADER lexicon...")
            nltk.download('vader_lexicon', quiet=True)
        return SentimentIntensityAnalyzer()

    def analyze_sentiment(self, text):
        scores = self.sia.polarity_scores(text)
        compound = scores['compound']
        
        if compound >= 0.05: 
            return "BULLISH", compound
        if compound <= -0.05: 
            return "BEARISH", compound
        return "NEUTRAL", compound

    def fetch_latest(self):
        logger.info("Scanning feeds for updates...")
        found_new = 0
        
        for source in self.config['sources']:
            try:
                feed = feedparser.parse(source['url'])
                for entry in feed.entries:
                    if entry.title not in self.seen_news:
                        sentiment, score = self.analyze_sentiment(entry.title)
                        
                        # Check for trading pause (high-impact bearish)
                        if self.config['sentiment']['enabled'] and sentiment == "BEARISH" and abs(score) > self.config['sentiment']['min_score']:
                            self.trading_pause = True
                            self.last_pause_time = time.time()
                            logger.warning(f"Trading PAUSED: High-impact bearish news - {entry.title} (score: {score:+.2f})")
                        
                        news_item = {
                            'title': entry.title,
                            'summary': entry.get('summary', entry.title),  
                            'time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                            'sentiment': sentiment,
                            'score': f"{score:+.2f}",
                            'source': source['name'],
                            'link': entry.link
                        }
                        self.news_items.append(news_item)
                        if len(self.news_items) > 50:  
                            self.news_items = self.news_items[-50:]
                        
                        logger.info(f"Added new: {entry.title} - {sentiment} ({score:+.2f}) from {source['name']}")
                        self.seen_news.add(entry.title)
                        found_new += 1
                        
            except Exception as e:
                logger.error(f"Failed to fetch {source['name']}: {e}")

        if found_new == 0:
            logger.info("No new updates found.")
        else:
            logger.info(f"Processed {found_new} new headlines.")

    def get_latest_news(self, count=5):
        return self.get_recent_news(count)

    def get_recent_news(self, count=5):
        recent = self.news_items[-count:]
        formatted = [f"{item['time']} | {item['title']} ({item['sentiment']}: {item['score']}) [{item['source']}]" for item in recent]
        return "\n".join(formatted) if formatted else "No recent news."

    # --- NEW: Get Overall Market Sentiment ---
    def get_market_sentiment(self):
        """Calculates global market sentiment based on average of last 5 headlines."""
        if not self.news_items:
            return "NEUTRAL"
        
        recent_items = self.news_items[-5:]
        total_score = 0.0
        count = 0
        
        for item in recent_items:
            try:
                total_score += float(item['score'])
                count += 1
            except ValueError:
                continue
                
        if count == 0: return "NEUTRAL"
            
        avg_score = total_score / count
        
        # Determine overall direction
        if avg_score >= 0.05: return "BULLISH"
        elif avg_score <= -0.05: return "BEARISH"
        else: return "NEUTRAL"

    def _periodic_fetch(self):
        while True:
            self.fetch_latest()
            if self.trading_pause and time.time() - self.last_pause_time > 300:
                self.trading_pause = False
                logger.info("Trading pause lifted - no ongoing high-impact news.")
            time.sleep(self.update_interval)

    def run(self):
        logger.info("Running initial News Engine fetch...")
        try:
            self.fetch_latest()
            logger.info("Initial news fetch complete.")
        except KeyboardInterrupt:
            logger.info("Shutting down engine.")

if __name__ == "__main__":
    engine = NewsEngine()
    engine.run()