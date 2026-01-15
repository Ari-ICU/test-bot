import time
import logging
from config import Config
from core.execution import MT5Connector
from core.risk import RiskManager
from core.session import is_market_open
from filters.news import NewsFilter
from filters.volatility import is_volatility_safe
# Import strategies
from strategy import trend_following, reversal, breakout
from ui import TradingApp

# Configure logging without basicConfig to allow UI handler to take precedence if needed
logger = logging.getLogger("Main")
logger.setLevel(logging.INFO)

def bot_logic(app_instance):
    """
    The main trading loop, now running in a separate thread controlled by the UI.
    """
    conf = Config()
    
    # Access components passed from main
    connector = app_instance.connector
    risk = app_instance.risk
    news_filter = NewsFilter(conf.get('sources', []))
    
    logger.info("Bot logic loop initialized.")
    
    while app_instance.bot_running:
        try:
            # 1. Check Filters
            if news_filter.fetch_news():
                logger.warning("High impact news detected. Pausing...")
                time.sleep(60)
                continue
                
            if not is_market_open("Auto"):
                # logger.info("Market closed. Waiting...")
                time.sleep(5) # check less frequently
                continue

            # 2. Process Data
            candles = connector.get_latest_candles()
            if not candles or len(candles) < 20: 
                time.sleep(1)
                continue

            # 3. Run Strategies
            decisions = []
            decisions.append(trend_following.analyze_trend_setup(candles))
            decisions.append(reversal.analyze_reversal_setup(candles, 0, 0))
            decisions.append(breakout.analyze_breakout_setup(candles))
            
            # 4. Aggregate Logic
            final_action = "NEUTRAL"
            for action, reasons in decisions:
                if action != "NEUTRAL":
                    final_action = action
                    logger.info(f"Signal: {action} | Reasons: {reasons}")
                    break
            
            # 5. Execute
            if final_action in ["BUY", "SELL"]:
                symbol = "XAUUSD" # Default, or make dynamic
                lot = risk.get_lot_size(1000)
                atr = 1.0 # Should calculate real ATR here
                
                # Get close price safely
                current_price = candles[-1]['close']
                
                sl, tp = risk.calculate_sl_tp(current_price, final_action, atr)
                
                connector.send_order(final_action, symbol, lot, sl, tp)
                logger.info(f"Auto-Trade Executed: {final_action} {lot} lots")
                time.sleep(15) # Cooldown

            time.sleep(1) # Loop delay

        except Exception as e:
            logger.error(f"Error in logic loop: {e}")
            time.sleep(5)

def main():
    # 1. Setup Core Components
    conf = Config()
    
    # Initialize Connector (Server)
    connector = MT5Connector(
        host=conf.get('mt5', {}).get('host', '127.0.0.1'),
        port=conf.get('mt5', {}).get('port', 8001)
    )
    
    if connector.start():
        logging.info("MT5 Connector started successfully")
    else:
        logging.error("Failed to start MT5 Connector")
        return

    risk = RiskManager(conf.data)

    # 2. Initialize UI
    # Pass the bot_logic function, connector, and risk manager to the UI
    app = TradingApp(bot_logic, connector, risk)
    
    # 3. Start Application
    try:
        app.mainloop()
    except KeyboardInterrupt:
        pass
    finally:
        connector.stop()
        logging.info("Application Shutdown")

if __name__ == "__main__":
    main()