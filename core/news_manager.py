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
        self.cache_duration = 1800  # Refresh every 30 mins
        
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
            logger.info("📡 Fetching Economic Calendar...")
            # Fake User-Agent to avoid simple blocking
            headers = {
                'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.114 Safari/537.36'
            }
            resp = requests.get(self.url, headers=headers, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                self.events = data
                self.last_fetch = time.time()
                logger.info(f"✅ Loaded {len(data)} calendar events.")
            else:
                logger.warning(f"⚠️ Failed to fetch news. Status: {resp.status_code}")
        except Exception as e:
            logger.error(f"❌ News Fetch Error: {e}")

    def get_active_impact(self, symbol, buffer_minutes=30):
        """
        Checks if there is High Impact news for the symbol's currencies 
        within +/- buffer_minutes of NOW.
        Returns: (ActiveBool, EventName, MinutesLeft)
        """
        if time.time() - self.last_fetch > self.cache_duration:
            self._fetch_calendar()

        if not self.events:
            return False, None, 0

        # 1. Identify relevant currencies
        currencies = ["USD"] # Default
        sym_upper = symbol.upper()
        
        for k, v in self.asset_map.items():
            if k in sym_upper:
                currencies.extend(v)
        
        currencies = list(set(currencies)) # Dedup
        
        # 2. Check events
        # FF dates are UTC. Need to be careful. 
        # Actually usually they are ISO strings '2025-01-20T14:30:00+00:00'
        
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
                # valid structure: "date": "2025-01-20T13:30:00-05:00"
                event_date_str = event.get('date')
                if not event_date_str: continue
                
                # Parse
                event_dt = datetime.fromisoformat(event_date_str).astimezone(pytz.utc)
                
                # Diff
                diff = (event_dt - now_utc).total_seconds() / 60 # minutes
                
                # Logic: If pending within 30 mins, OR happened within past 30 mins (volatility wake)
                if -buffer_minutes <= diff <= buffer_minutes:
                    name = event.get('title', 'News')
                    return True, name, int(diff)
                    
            except Exception as e:
                pass
                
        return False, None, 0
