import json
import os
from dotenv import load_dotenv
from typing import Any, Dict, Optional
import logging
load_dotenv()
logger = logging.getLogger(__name__)
class Config:
    def __init__(self, path: str = "config.json"):
        base_dir = os.path.dirname(os.path.abspath(__file__))
        self.path = os.path.join(base_dir, path)
        self.data: Dict[str, Any] = self._load()
        self._validate_required()
    def _load(self) -> Dict[str, Any]:
        """Load JSON with error handling."""
        try:
            if os.path.exists(self.path):
                with open(self.path, 'r') as f:
                    return json.load(f)
            else:
                logger.warning(f"⚠️ {self.path} not found – using defaults")
                return self._get_defaults()
        except json.JSONDecodeError as e:
            logger.error(f"❌ Invalid JSON in {self.path}: {e} – using defaults")
            return self._get_defaults()
    def _get_defaults(self) -> Dict[str, Any]:
        """Sane defaults matching your risk/scalping setup."""
        return {
            "mt5": {"host": "127.0.0.1", "port": 8001, "enabled": True, "active_account": 0},
            "telegram": {"enabled": True, "bot_token": "", "chat_id": ""},
        "risk": {
            "max_drawdown": 5.0,
            "daily_loss_limit": 5.0,
            "risk_per_trade": 1.0,
            "max_trades": 15,
            "cool_off_seconds": 300,
            "max_open_positions": 10,
            "max_positions_per_symbol": 3,
            "max_positions_per_sector": 5,
            "reputable_brokers": ["MetaQuotes", "ICMarkets", "Exness", "Pepperstone", "FXTM", "XM", "Hantec"],
            "require_validated_model": True,
            "hedging_allowed": True,
            "lot_size": 0.01,
            "crypto_risk_multiplier": 0.5,
            "forex_risk_multiplier": 1.0
        },
        "auto_trading": {"enabled": True, "max_positions": 5, "lot_size": 0.01},
        "scalping": {
            "rsi_period": 14,
            "tp_amount": 0.50,
            "max_spread": 20,
            "crt_htf_minutes": 240,
            "crypto_atr_multiplier": 1.5,
            "forex_atr_multiplier": 1.5,
            "risk_reward_ratio": 1.5
        },
        "update_interval_seconds": 60,
        "sentiment": {"enabled": True, "min_score": 0.2}
    }
    def get(self, key: str, default: Any = None) -> Any:
        """Get value: Env (with aliases) > Nested JSON > default. Auto-convert types."""
        env_key_standard = key.upper().replace('.', '_')
        env_keys = [env_key_standard, f"BOT_{env_key_standard}"]
        env_val = None
        for ek in env_keys:
            env_val = os.getenv(ek)
            if env_val is not None:
                break
        if env_val is not None:
            if any(x in key.lower() for x in ['id', 'port', 'trades', 'positions']):
                try: return int(env_val)
                except ValueError: pass
            if any(x in key.lower() for x in ['risk', 'lot', 'multiplier', 'amount', 'drawdown']):
                try: return float(env_val)
                except ValueError: pass
            return env_val
        if '.' in key:
            parts = key.split('.')
            val = self.data
            for part in parts:
                if isinstance(val, dict):
                    val = val.get(part, {})
                else:
                    return default
            return val if val != {} else default
        return self.data.get(key, default)
    def _validate_required(self):
        """Warn on missing Telegram/MT5 keys."""
        missing = []
        if not self.get('telegram.bot_token') and not os.getenv('TELEGRAM_BOT_TOKEN'):
            missing.append('telegram.bot_token / TELEGRAM_BOT_TOKEN')
        if not self.get('telegram.chat_id') and not os.getenv('TELEGRAM_CHAT_ID'):
            missing.append('telegram.chat_id / TELEGRAM_CHAT_ID')
        if not self.get('mt5.host'):
            missing.append('mt5.host')
        if missing:
            logger.warning(f"⚠️ Missing config keys: {', '.join(missing)} – Set in .env or config.json")
