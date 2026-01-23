from bot_settings import Config
import logging
logging.basicConfig(level=logging.WARNING)

conf = Config()
print(f"Token: {conf.get('telegram.bot_token')[:10]}...")  # Redacted
print(f"Chat ID: {conf.get('telegram.chat_id')} (type: {type(conf.get('telegram.chat_id'))})")  # int
print(f"Risk per Trade: {conf.get('risk.risk_per_trade')}")  # 1.0
print(f"Max Trades: {conf.get('risk.max_trades')}")  # 20
print(f"RSI Period: {conf.get('scalping.rsi_period')}")  # 14
print(f"MT5 Host: {conf.get('mt5.host')}")  # 127.0.0.1