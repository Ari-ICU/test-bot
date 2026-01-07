import threading
import time
import logging
from src.connector import MT5Connector
from src.strategy import TradingStrategy
from src.news import NewsEngine
from src.ui import TradingBotUI


logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger("Main")

def main():
    connector = MT5Connector()
    news_engine = NewsEngine()
    
    # Load config to pass to strategy
    config = news_engine.config 
    
    strategy = TradingStrategy(connector, news_engine, config)
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

    # FIX: Sync UI defaults to strategy before start
    app._sync_ui_to_strategy()

    # START STRATEGY
    strategy.start()

    try:
        app.mainloop()
    except KeyboardInterrupt:
        pass
    finally:
        connector.stop()
        logger.info("Shutdown complete.")

if __name__ == "__main__":
    main()