import feedparser
import time
import json
import logging
import urllib.request
import xml.etree.ElementTree as ET
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
        self.is_starting = True # Skip pausing for old news on startup
        
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
        if compound >= 0.05: return "BULLISH", compound
        if compound <= -0.05: return "BEARISH", compound
        return "NEUTRAL", compound

    def fetch_latest(self):
        logger.info("Scanning feeds for updates...")
        found_new = 0
        
        for source in self.config['sources']:
            try:
                if source['name'] == "FF_Calendar":
                    found_new += self._fetch_ff_calendar(source)
                    continue

                feed = feedparser.parse(source['url'])
                for entry in feed.entries:
                    if entry.title not in self.seen_news:
                        sentiment, score = self.analyze_sentiment(entry.title)
                        
                        # High-impact bearish news pause (skip on startup)
                        if self.config['sentiment']['enabled'] and sentiment == "BEARISH" and abs(score) > 0.4 and not self.is_starting:
                            self.trading_pause = True
                            self.last_pause_time = time.time()
                            logger.warning(f"Trading PAUSED: High-impact news - {entry.title}")
                        
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
                        if len(self.news_items) > 50: self.news_items = self.news_items[-50:]
                        self.seen_news.add(entry.title)
                        found_new += 1
                        
            except Exception as e:
                logger.error(f"Failed to fetch {source['name']}: {e}")

        if found_new > 0:
            logger.info(f"Processed {found_new} new headlines.")
        
        self.is_starting = False

    def _fetch_ff_calendar(self, source):
        """Specially parses the Forex Factory Calendar XML feed with robust fallbacks."""
        new_count = 0
        # Try multiple variations to bypass DNS, SSL, or 403 errors
        urls_to_try = [
            "https://www.forexfactory.com/ffcal_week_this.xml",
            "http://www.forexfactory.com/ffcal_week_this.xml",
            "https://nfs.forexfactory.com/ffcal_week_this.xml",
            "http://nfs.forexfactory.com/ffcal_week_this.xml"
        ]
        
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
            'Accept': 'text/xml,application/xml,application/xhtml+xml,text/html;q=0.9',
            'Connection': 'close'
        }

        for url in urls_to_try:
            try:
                req = urllib.request.Request(url, headers=headers)
                with urllib.request.urlopen(req, timeout=8) as response:
                    xml_data = response.read()
                    if not xml_data: continue
                    
                    root = ET.fromstring(xml_data)
                    for event in root.findall('event'):
                        title = event.find('title').text
                        country = event.find('country').text
                        impact = event.find('impact').text
                        
                        if impact in ["High", "Medium"]:
                            full_title = f"[{impact}] {country}: {title}"
                            if full_title not in self.seen_news:
                                score = -0.6 if impact == "High" else -0.2
                                if impact == "High" and not self.is_starting:
                                    self.trading_pause = True
                                    self.last_pause_time = time.time()
                                    logger.warning(f"🕒 CALENDAR ALERT: {full_title}. Trading PAUSED.")

                                self.news_items.append({
                                    'title': full_title,
                                    'summary': f"Calendar Event: {title} ({country})",
                                    'time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                                    'sentiment': "BEARISH",
                                    'score': f"{score:+.2f}",
                                    'source': "FF_Calendar",
                                    'link': "https://www.forexfactory.com/calendar"
                                })
                                self.seen_news.add(full_title)
                                new_count += 1
                    return new_count # Success!
            except Exception:
                # Silently try next fallback
                continue
        
        # If all failed, don't spam the UI, just log a debug message
        logger.debug("Automatic Calendar fetch skipped (Network/DNS Timeout)")
        return 0

    def get_market_sentiment(self):
        if not self.news_items: return "NEUTRAL"
        recent = self.news_items[-5:]
        total_score = sum(float(item['score']) for item in recent if 'score' in item)
        avg = total_score / len(recent)
        if avg >= 0.05: return "BULLISH"
        if avg <= -0.05: return "BEARISH"
        return "NEUTRAL"

    def get_latest_news(self, count=5):
        return self.get_recent_news(count)

    def get_recent_news(self, count=5):
        recent = self.news_items[-count:]
        formatted = [f"{item['time']} | {item['title']} ({item['sentiment']}: {item['score']}) [{item['source']}]" for item in recent]
        return "\n".join(formatted) if formatted else "No recent news."

    def _periodic_fetch(self):
        while True:
            self.fetch_latest()
            if self.trading_pause and time.time() - self.last_pause_time > 300:
                self.trading_pause = False
                logger.info("Trading pause lifted.")
            time.sleep(self.update_interval)

    def run(self):
        self.fetch_latest()

if __name__ == "__main__":
    engine = NewsEngine()
    engine.run()