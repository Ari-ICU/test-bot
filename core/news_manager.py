import requests
import json
import logging
import time
from datetime import datetime, timedelta
import pytz

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
        Returns the closest upcoming High Impact event for the symbol.
        Returns: (EventName, MinutesUntil) or (None, None)
        """
        if time.time() - self.last_fetch > self.cache_duration:
            self._fetch_calendar()

        currencies = self._get_currencies(symbol)
        now_utc = datetime.now(pytz.utc)
        
        closest_event = None
        min_diff = float('inf')

        for event in self.events:
            if event.get('impact') != 'High': continue
            if event.get('country') not in currencies and event.get('currency') not in currencies: continue
            
            try:
                event_date_str = event.get('date')
                if not event_date_str: continue
                event_dt = datetime.fromisoformat(event_date_str).astimezone(pytz.utc)
                
                diff = (event_dt - now_utc).total_seconds() / 60
                if diff > 0 and diff < min_diff:
                    min_diff = diff
                    closest_event = event.get('title', 'News')
            except: continue
        
        if closest_event:
            return closest_event, int(min_diff), "https://www.forexfactory.com/calendar"
        return None, None, None

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
