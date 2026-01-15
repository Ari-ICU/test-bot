import json

class Config:
    def __init__(self, path="config.json"):
        self.path = path
        self.data = self._load()

    def _load(self):
        try:
            with open(self.path, 'r') as f:
                return json.load(f)
        except FileNotFoundError:
            return {}

    def get(self, key, default=None):
        return self.data.get(key, default)