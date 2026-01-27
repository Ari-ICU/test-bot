import requests
import json
import logging
import time
from datetime import datetime, timedelta
import pytz
import xml.etree.ElementTree as ET
import re

logger = logging.getLogger("NewsManager")

class NewsManager:
    def __init__(self):
        self.url = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
        self.events = []
        self.last_fetch = 0
        self.cache_duration = 300  # Refresh every 5 mins (Real-Time)
        
        # Currency Mapping for common assets
        self.asset_map = {
            "XAU": ["USD"], # Gold is moved by USD news
            "BTC": ["USD"], # Crypto moved by USD
            "EUR": ["EUR", "USD"],
            "GBP": ["GBP", "USD"],
            "JPY": ["JPY", "USD"],
            "AUD": ["AUD", "USD"],
            "CAD": ["CAD", "USD"],
            "USD": ["USD"]
        }
        
        # News Toggles & State
        self.headlines = []
        self.last_headline_fetch = 0
        self.headline_cache_duration = 900  # 15 mins
        
        # High Impact Keywords (Sentiment Scorers)
        self.sentiment_weights = {
            "negative": ["war", "conflict", "tariff", "attack", "sanction", "tension", "strike", "escalat", "crash", "fear", "crisis", "shutdown"],
            "positive": ["growth", "deal", "improvement", "surge", "resolution", "bullish", "recovery", "peace", "agreement"],
            "volatile": ["trump", "fed", "election", "policy", "powell", "emergency", "abrupt"]
        }

    def _fetch_calendar(self):
        try:
            logger.info("📡 Fetching Economic Calendar (Live)...")
            # Fake User-Agent to avoid simple blocking
            headers = {
                'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.114 Safari/537.36'
            }
            resp = requests.get(self.url, headers=headers, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                self.events = data
                self.last_fetch = time.time()
                logger.debug(f"✅ News Sync: {len(data)} events loaded.")
            else:
                logger.warning(f"⚠️ Failed to fetch news. Status: {resp.status_code}")
        except Exception as e:
            logger.error(f"❌ News Fetch Error: {e}")

    def get_upcoming_event(self, symbol):
        """
        Returns the closest upcoming High Impact event for the symbol with detailed stats.
        Returns: (EventName, MinutesUntil, Link, Details)
        """
        if time.time() - self.last_fetch > self.cache_duration:
            self._fetch_calendar()

        currencies = self._get_currencies(symbol)
        now_utc = datetime.now(pytz.utc)
        
        closest_event = None
        min_diff = float('inf')
        details = ""

        for event in self.events:
            if event.get('impact') not in ['High', 'Medium']: continue
            if event.get('country') not in currencies and event.get('currency') not in currencies: continue
            
            try:
                event_date_str = event.get('date')
                if not event_date_str: continue
                event_dt = datetime.fromisoformat(event_date_str).astimezone(pytz.utc)
                
                diff = (event_dt - now_utc).total_seconds() / 60
                if diff > 0 and diff < min_diff:
                    min_diff = diff
                    closest_event = event.get('title', 'News')
                    forecast = event.get('forecast', 'N/A')
                    previous = event.get('previous', 'N/A')
                    details = f"F: {forecast} | P: {previous}"
            except: continue
        
        if closest_event:
            return closest_event, int(min_diff), "https://www.forexfactory.com/calendar", details
        return None, None, None, ""

    def get_calendar_summary(self, symbol, count=5):
        """
        Returns a list of upcoming events with detailed forecast/previous values.
        """
        if time.time() - self.last_fetch > self.cache_duration:
            self._fetch_calendar()

        currencies = self._get_currencies(symbol)
        now_utc = datetime.now(pytz.utc)
        upcoming = []

        for event in self.events:
            if event.get('country') not in currencies and event.get('currency') not in currencies: continue
            
            try:
                event_dt = datetime.fromisoformat(event.get('date')).astimezone(pytz.utc)
                diff = (event_dt - now_utc).total_seconds() / 60
                
                if diff > -60: # Show recent and future
                    upcoming.append({
                        "time": event_dt.strftime("%H:%M"),
                        "title": event.get('title'),
                        "impact": event.get('impact'),
                        "forecast": event.get('forecast', '-'),
                        "previous": event.get('previous', '-'),
                        "actual": event.get('actual', '-'),
                        "mins": int(diff)
                    })
            except: continue
            
        upcoming.sort(key=lambda x: x['mins'])
        return upcoming[:count]

    def _get_currencies(self, symbol):
        currencies = ["USD"]
        sym_upper = symbol.upper()
        for k, v in self.asset_map.items():
            if k in sym_upper:
                currencies.extend(v)
        return list(set(currencies))

    def get_active_impact(self, symbol, buffer_minutes=30):
        """
        Checks if there is High Impact news for the symbol's currencies 
        within +/- buffer_minutes of NOW.
        Returns: (ActiveBool, EventName, MinutesLeft)
        """
        # ... existing logic ...
        if time.time() - self.last_fetch > self.cache_duration:
            self._fetch_calendar()

        if not self.events:
            return False, None, 0

        currencies = self._get_currencies(symbol)
        now_utc = datetime.now(pytz.utc)
        
        for event in self.events:
            # Filter by Impact
            if event.get('impact') != 'High':
                continue
                
            # Filter by Currency
            if event.get('country') not in currencies and event.get('currency') not in currencies:
                continue
                
            # Check Time
            try:
                event_date_str = event.get('date')
                if not event_date_str: continue
                event_dt = datetime.fromisoformat(event_date_str).astimezone(pytz.utc)
                diff = (event_dt - now_utc).total_seconds() / 60 # minutes
                
                if -buffer_minutes <= diff <= buffer_minutes:
                    name = event.get('title', 'News')
                    return True, name, int(diff)
            except Exception as e:
                pass
                
        return False, None, 0

    def _fetch_headlines(self):
        """Fetches latest headlines from Google News RSS for key themes."""
        try:
            now = time.time()
            if now - self.last_headline_fetch < self.headline_cache_duration:
                return

            queries = ["Trump%20Forex", "World%20War%20Risk", "Economic%20Crisis"]
            all_headlines = []
            
            headers = {'User-Agent': 'Mozilla/5.0'}
            
            for q in queries:
                url = f"https://news.google.com/rss/search?q={q}&hl=en-US&gl=US&ceid=US:en"
                resp = requests.get(url, headers=headers, timeout=10)
                if resp.status_code == 200:
                    root = ET.fromstring(resp.content)
                    items = root.findall('.//item')
                    for item in items[:5]:
                        title = item.find('title').text
                        all_headlines.append(title)
            
            self.headlines = list(set(all_headlines)) # Dedup
            self.last_headline_fetch = now
            logger.info(f"📰 Fetched {len(self.headlines)} global news headlines.")
        except Exception as e:
            logger.error(f"❌ Headline Fetch Error: {e}")

    def get_market_sentiment(self):
        """
        Analyzes current headlines and returns a sentiment summary.
        Returns: (SentimentScore, SummaryText, TopHeadlines)
        Score: -10 (Very Bearish/Risky) to +10 (Very Bullish/Stable)
        """
        self._fetch_headlines()
        
        if not self.headlines:
            return 0, "Neutral (No Data)", []

        score = 0
        risks = []
        
        for h in self.headlines:
            h_lower = h.lower()
            
            # Check for negative/risk words
            for word in self.sentiment_weights["negative"]:
                if word in h_lower:
                    score -= 1.5
                    risks.append(h)
                    break # Don't double count same headline
            
            # Check for positive words
            for word in self.sentiment_weights["positive"]:
                if word in h_lower:
                    score += 1.0
                    break
            
            # Check for high volatility names (Trump etc)
            for word in self.sentiment_weights["volatile"]:
                if word in h_lower:
                    score -= 0.5 # Volatility is usually perceived as risk
                    break

        # Normalize score
        score = max(min(score, 10), -10)
        
        status = "NEUTRAL"
        if score <= -3: status = "RISK-OFF (Bearish)"
        elif score >= 3: status = "RISK-ON (Bullish)"
        elif score < 0: status = "CAUTIOUS"
        
        summary = f"{status} (Score: {score:.1f})"
        return score, summary, risks[:3]
