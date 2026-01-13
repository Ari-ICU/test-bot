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
import requests  # Added for robust HTTP handling
from time import sleep  # For backoff
# Note: We no longer need to import WebhookAlert here for instantiation, 
# but we keep it if you use type hinting, otherwise it's fine to remove.

# Initialize Logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger("NewsEngine")

class NewsEngine:
    # UPDATED INIT: Accepts webhook as an argument
    def __init__(self, config_path="config.json", webhook=None):
        self.load_config(config_path)
        self.sia = self.init_analyzer()
        self.seen_news = set()
        self.news_items = []  
        self.update_interval = self.config.get('update_interval_seconds', 60)
        self.trading_pause = False  
        self.last_pause_time = 0  
        self.is_starting = True 
        
        # USE THE SHARED WEBHOOK
        self.webhook = webhook
        
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
            source_name = source.get('name', 'Unknown')
            max_retries = 3
            for attempt in range(max_retries):
                try:
                    if source['name'] == "FF_Calendar":
                        new_from_cal = self._fetch_ff_calendar(source)
                        found_new += new_from_cal
                        break  # Calendar fetch doesn't need retries per se

                    # For RSS/API feeds: Use requests for robustness (better error handling than feedparser alone)
                    url = source['url']
                    headers = {
                        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
                        'Accept': 'application/rss+xml,application/xml,text/xml,*/*;q=0.9'
                    }
                    
                    # Sanitize any 'macd' params if present (quick hack for the leak)
                    if 'params' in source:
                        params = source['params'].copy()
                        params.pop('macd', None)  # Remove if it's causing the issue
                        response = requests.get(url, params=params, headers=headers, timeout=10)
                    else:
                        response = requests.get(url, headers=headers, timeout=10)
                    
                    response.raise_for_status()  # Raise on HTTP errors (4xx/5xx)
                    
                    feed = feedparser.parse(response.text)  # Parse with feedparser after fetch
                    
                    for entry in feed.entries:
                        if entry.title not in self.seen_news:
                            sentiment, score = self.analyze_sentiment(entry.title)
                            
                            if self.config['sentiment']['enabled'] and sentiment == "BEARISH" and abs(score) > 0.4 and not self.is_starting:
                                self.trading_pause = True
                                self.last_pause_time = time.time()
                                logger.warning(f"Trading PAUSED: High-impact news - {entry.title}")
                                if self.webhook:
                                    self.webhook.notify_news(entry.title, sentiment, score)
                            
                            pub_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                            if 'published_parsed' in entry and entry.published_parsed:
                                pub_time = time.strftime('%Y-%m-%d %H:%M:%S', entry.published_parsed)
                            elif 'updated_parsed' in entry and entry.updated_parsed:
                                pub_time = time.strftime('%Y-%m-%d %H:%M:%S', entry.updated_parsed)

                            # FIX: Safe access to 'link' – check if attribute exists
                            link = getattr(entry, 'link', '')  # Default to empty string if no 'link'

                            news_item = {
                                'title': entry.title,
                                'summary': getattr(entry, 'summary', entry.title),  # Safe summary access too
                                'time': pub_time,
                                'sentiment': sentiment,
                                'score': f"{score:+.2f}",
                                'source': source_name,
                                'link': link
                            }
                            self.news_items.append(news_item)
                            if len(self.news_items) > 50: self.news_items = self.news_items[-50:]
                            self.seen_news.add(entry.title)
                            found_new += 1
                    break  # Success, move to next source
                    
                except requests.exceptions.HTTPError as e:
                    if e.response.status_code == 403:
                        logger.error(f"403 Forbidden on {source_name}: Source blocked (e.g., geo/IP restriction). Skipping permanently.")
                        break  # Don't retry 403s – they're hard blocks
                    error_msg = str(e).replace('macd', '[REDACTED]')
                    if attempt < max_retries - 1:
                        wait_time = 2 ** attempt
                        logger.warning(f"HTTP Error on {source_name} (attempt {attempt+1}/{max_retries}): {error_msg}. Retrying in {wait_time}s...")
                        sleep(wait_time)
                    else:
                        logger.error(f"Failed {source_name} after {max_retries} retries: {error_msg}. Skipping source.")
                        continue
                        
                except requests.exceptions.RequestException as e:
                    error_msg = str(e).replace('macd', '[REDACTED]')
                    if attempt < max_retries - 1:
                        wait_time = 2 ** attempt
                        logger.warning(f"HTTP Error on {source_name} (attempt {attempt+1}/{max_retries}): {error_msg}. Retrying in {wait_time}s...")
                        sleep(wait_time)
                    else:
                        logger.error(f"Failed {source_name} after {max_retries} retries: {error_msg}. Skipping source.")
                        continue
                        
                except ET.ParseError as e:
                    logger.error(f"XML Parse Error in {source_name}: {e}. Skipping.")
                    break  # Don't retry parse errors
                    
                except Exception as e:
                    error_msg = str(e).replace('macd', '[REDACTED]')
                    logger.error(f"Unexpected error in {source_name}: {error_msg}")
                    break  # Don't retry unknowns to avoid loops

        if found_new > 0:
            logger.info(f"Processed {found_new} new headlines.")
        
        self.is_starting = False

    def _fetch_ff_calendar(self, source):
        new_count = 0
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
                # Use requests for consistency and better error handling
                response = requests.get(url, headers=headers, timeout=8)
                response.raise_for_status()
                xml_data = response.content
                
                if not xml_data: 
                    continue
                    
                root = ET.fromstring(xml_data)
                for event in root.findall('event'):
                    title_elem = event.find('title')
                    if title_elem is None: continue
                    title = title_elem.text
                    country_elem = event.find('country')
                    country = country_elem.text if country_elem is not None else "N/A"
                    impact_elem = event.find('impact')
                    impact = impact_elem.text if impact_elem is not None else "Low"
                    
                    if impact in ["High", "Medium"]:
                        full_title = f"[{impact}] {country}: {title}"
                        if full_title not in self.seen_news:
                            score = -0.6 if impact == "High" else -0.2
                            if impact == "High" and not self.is_starting:
                                self.trading_pause = True
                                self.last_pause_time = time.time()
                                logger.warning(f"🕒 CALENDAR ALERT: {full_title}. Trading PAUSED.")
                                if self.webhook:
                                    self.webhook.notify_news(full_title, "BEARISH", score)

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
                return new_count  # Success, return count
                
            except requests.exceptions.HTTPError as e:
                if e.response.status_code == 403:
                    logger.error(f"403 Forbidden on FF Calendar ({url}): Blocked. Skipping calendar fetch.")
                    break  # Hard skip for 403
                error_msg = str(e).replace('macd', '[REDACTED]')
                logger.warning(f"FF Calendar fetch error ({url}): {error_msg}")
                continue
            except requests.exceptions.RequestException as e:
                error_msg = str(e).replace('macd', '[REDACTED]')
                logger.warning(f"FF Calendar fetch error ({url}): {error_msg}")
                continue
            except ET.ParseError as e:
                logger.error(f"FF Calendar XML parse error: {e}")
                break  # Don't retry parse issues
            except Exception as e:
                error_msg = str(e).replace('macd', '[REDACTED]')
                logger.error(f"Unexpected FF Calendar error ({url}): {error_msg}")
                continue
        
        logger.debug("Automatic Calendar fetch skipped (all URLs failed)")
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
        formatted = []
        for item in recent:
            link_part = f"\n🔗 {item['link']}" if item.get('link') else ""
            formatted.append(f"📰 *{item['title']}*\nScore: {item['score']} | {item['source']}{link_part}")
        return "\n\n".join(formatted) if formatted else "No recent news."

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