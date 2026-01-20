import json
import os
from dotenv import load_dotenv

# Load variables from .env file
load_dotenv()

class Config:
    def __init__(self, path="config.json"):
        # Resolve config.json relative to this file's directory
        base_dir = os.path.dirname(os.path.abspath(__file__))
        self.path = os.path.join(base_dir, path)
        self.data = self._load()

    def _load(self):
        try:
            with open(self.path, 'r') as f:
                return json.load(f)
        except FileNotFoundError:
            return {}

    def get(self, key, default=None):
        # Check Environment Variables first (for Telegram keys)
        env_val = os.getenv(key.upper())
        if env_val:
            return env_val
            
        # Fallback to the JSON file
        return self.data.get(key, default)