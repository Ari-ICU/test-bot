import feedparser
import time
import json
import logging
from datetime import datetime
from nltk.sentiment.vader import SentimentIntensityAnalyzer
import nltk

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

    def load_config(self, path):
        with open(path, 'r') as f:
            self.config = json.load(f)
        logger.info(f"Loaded {len(self.config['sources'])} news sources.")

    def init_analyzer(self):
        try:
            nltk.data.find('sentiment/vader_lexicon.zip')
        except LookupError:
            logger.info("Downloading VADER lexicon...")
            nltk.download('vader_lexicon', quiet=True)
        return SentimentIntensityAnalyzer()

    def analyze_sentiment(self, text):
        scores = self.sia.polarity_scores(text)
        compound = scores['compound']
        
        if compound >= 0.05: return "BULLISH", compound
        if compound <= -0.05: return "BEARISH", compound
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
                        
                        # Output format
                        print(f"\n[{source['name']}] ({source['category']})")
                        print(f"TITLE: {entry.title}")
                        print(f"SENTIM: {sentiment} ({score:+.2f})")
                        print(f"LINK : {entry.link}")
                        print("-" * 50)
                        
                        self.seen_news.add(entry.title)
                        found_new += 1
                        
            except Exception as e:
                logger.error(f"Failed to fetch {source['name']}: {e}")

        if found_new == 0:
            logger.info("No new updates found.")
        else:
            logger.info(f"Processed {found_new} new headlines.")

    def run(self):
        logger.info("Starting News Engine (one-time fetch)...")
        try:
            self.fetch_latest()
            logger.info("News fetch complete.")
        except KeyboardInterrupt:
            logger.info("Shutting down engine.")

if __name__ == "__main__":
    engine = NewsEngine()
    engine.run()
