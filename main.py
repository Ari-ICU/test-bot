import threading
import time
import logging
import json
from src.connector import MT5Connector
from src.strategy import TradingStrategy
from src.news import NewsEngine
from src.ui import TradingBotUI
from src.webhook import WebhookAlert

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger("Main")

def main():
    # 1. LOAD CONFIG FIRST
    try:
        with open('config.json', 'r') as f:
            config = json.load(f)
    except FileNotFoundError:
        logger.error("config.json not found! Please ensure it exists.")
        return

    # 2. INITIALIZE WEBHOOK ONCE
    tg_config = config.get('telegram', {})
    webhook = None
    if tg_config.get('enabled'):
        webhook = WebhookAlert(
            bot_token=tg_config.get('bot_token'),
            chat_id=tg_config.get('chat_id')
        )
        logger.info("Webhook initialized in main.py")

    connector = MT5Connector()
    
    # 3. PASS WEBHOOK TO NEWS ENGINE
    news_engine = NewsEngine(webhook=webhook)
    
    # 4. PASS WEBHOOK TO STRATEGY
    # Note: Strategy constructor now accepts 'webhook' argument
    strategy = TradingStrategy(connector, news_engine, config, webhook=webhook)
    
    app = TradingBotUI(news_engine, connector)
    app.strategy = strategy

    def tick_router(symbol, bid, ask, balance, profit, acct_name, positions, buy_count, sell_count, avg_entry, candles):
        strategy.on_tick(symbol, bid, ask, balance, profit, acct_name, positions, buy_count, sell_count, avg_entry, candles)
        app._on_tick_received(symbol, bid, ask, balance, profit, acct_name, positions, buy_count, sell_count, avg_entry, candles)

    connector.on_tick_received = tick_router

    if connector.start():
        logger.info("MT5 Connector Started")
    else:
        logger.error("Failed to start MT5 Connector")
        return

    # START STRATEGY
    strategy.start()

    # FORCE UI SYNC TO ENSURE IT'S OFF
    app._sync_ui_to_strategy()

    try:
        app.mainloop()
    except KeyboardInterrupt:
        pass
    finally:
        # If webhook has a stop event, trigger it
        if webhook and hasattr(webhook, 'stop_event'):
            webhook.stop_event.set()
        connector.stop()
        logger.info("Shutdown complete.")

if __name__ == "__main__":
    main()