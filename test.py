from bot_settings import Config
import logging
logging.basicConfig(level=logging.WARNING)
conf = Config()
print(f"Token: {conf.get('telegram.bot_token')[:10]}...")
print(f"Chat ID: {conf.get('telegram.chat_id')} (type: {type(conf.get('telegram.chat_id'))})")
print(f"Risk per Trade: {conf.get('risk.risk_per_trade')}")
print(f"Max Trades: {conf.get('risk.max_trades')}")
print(f"RSI Period: {conf.get('scalping.rsi_period')}")
print(f"MT5 Host: {conf.get('mt5.host')}")