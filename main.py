import time
import logging
from config import Config
from core.execution import MT5Connector
from core.risk import RiskManager
from core.session import is_market_open
from filters.news import NewsFilter
from ui import TradingApp
import strategy.trend_following as trend
import strategy.reversal as reversal
import strategy.breakout as breakout

# Configure main logger
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("Main")

def bot_logic(app):
    """Logic loop running in background thread"""
    conf = Config()
    connector = app.connector
    risk = app.risk
    news_filter = NewsFilter(conf.get('sources', []))
    
    logger.info("Bot logic loop initialized.")
    
    while app.bot_running:
        try:
            # 1. Check Filters
            if news_filter.fetch_news():
                logger.warning("High impact news. Pausing 60s...")
                time.sleep(60)
                continue
                
            if not is_market_open("Auto"):
                time.sleep(5)
                continue

            # 2. Process Data
            candles = connector.get_latest_candles()
            if not candles or len(candles) < 20: 
                time.sleep(1)
                continue

            # 3. Strategy Analysis
            decisions = []
            decisions.append(trend.analyze_trend_setup(candles))
            decisions.append(reversal.analyze_reversal_setup(candles, 0, 0))
            decisions.append(breakout.analyze_breakout_setup(candles))
            
            final_action = "NEUTRAL"
            for action, reasons in decisions:
                if action != "NEUTRAL":
                    final_action = action
                    logger.info(f"Signal: {action} | Reasons: {reasons}")
                    break
            
            # 4. Execution
            if final_action in ["BUY", "SELL"]:
                lot = risk.get_lot_size(1000)
                sl, tp = risk.calculate_sl_tp(candles[-1]['close'], final_action, 1.0)
                connector.send_order(final_action, "XAUUSD", lot, sl, tp)
                logger.info(f"Trade Executed: {final_action}")
                time.sleep(15)

            time.sleep(1)

        except Exception as e:
            logger.error(f"Logic Error: {e}")
            time.sleep(5)

def main():
    conf = Config()
    
    # Init Connector
    connector = MT5Connector(
        host=conf.get('mt5', {}).get('host', '127.0.0.1'),
        port=conf.get('mt5', {}).get('port', 8001)
    )
    
    if connector.start():
        logger.info("MT5 Connector started.")
    else:
        logger.error("Failed to start MT5 Connector.")
        return

    risk = RiskManager(conf.data)
    
    # Init UI
    app = TradingApp(bot_logic, connector, risk)
    
    try:
        app.mainloop()
    except KeyboardInterrupt:
        pass
    finally:
        connector.stop()
        logger.info("Shutdown complete.")

if __name__ == "__main__":
    main()