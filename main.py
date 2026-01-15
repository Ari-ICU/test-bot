import time
import logging
from config import Config
from core.execution import MT5Connector
from core.risk import RiskManager
from core.session import is_market_open
from core.telegram_bot import TelegramBot
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
            # 1. Check Auto-Trade Toggle
            if hasattr(app, 'auto_trade_var') and not app.auto_trade_var.get():
                time.sleep(1)
                continue

            # 2. Market Status Check
            if not is_market_open("Auto"):
                time.sleep(5)
                continue

            # 3. Process Data
            candles = connector.get_latest_candles()
            if not candles or len(candles) < 20: 
                time.sleep(1)
                continue

            # 4. Strategy Analysis
            decisions = []
            
            # --- A. Check News Sentiment First ---
            news_action, news_reason = news_filter.get_sentiment_signal()
            if news_action != "NEUTRAL":
                # High priority: News can trigger immediate action
                decisions.append((news_action, news_reason))
            
            # --- B. Technical Strategies ---
            decisions.append(trend.analyze_trend_setup(candles))
            decisions.append(reversal.analyze_reversal_setup(candles, 0, 0))
            decisions.append(breakout.analyze_breakout_setup(candles))
            
            # 5. Aggregate Decisions
            final_action = "NEUTRAL"
            execution_reason = ""
            
            for action, reasons in decisions:
                if action != "NEUTRAL":
                    final_action = action
                    execution_reason = reasons
                    logger.info(f"Signal Found: {action} | Reason: {reasons}")
                    break
            
            # 6. Execute Trade
            if final_action in ["BUY", "SELL"]:
                # Get volume from UI or Config
                lot = 0.01
                if hasattr(app, 'lot_var'):
                    try: lot = float(app.lot_var.get())
                    except: lot = 0.01
                
                # Get symbol from UI
                symbol = "XAUUSD"
                if hasattr(app, 'symbol_var'):
                    symbol = app.symbol_var.get()

                # Calculate SL/TP
                current_price = candles[-1]['close']
                sl, tp = risk.calculate_sl_tp(current_price, final_action, 1.0)
                
                connector.send_order(final_action, symbol, lot, sl, tp)
                logger.info(f"Auto-Trade Executed: {final_action} {symbol} | {execution_reason}")
                
                # Shorter cooldown for news trading, longer for technicals
                cooldown = 300 if "News" in execution_reason else 60
                time.sleep(cooldown)

            time.sleep(1)

        except Exception as e:
            logger.error(f"Logic Error: {e}")
            time.sleep(5)

def main():
    conf = Config()
    
    # 1. Setup Connector
    connector = MT5Connector(
        host=conf.get('mt5', {}).get('host', '127.0.0.1'),
        port=conf.get('mt5', {}).get('port', 8001)
    )
    
    # 2. Setup Telegram
    tg_conf = conf.get('telegram', {})
    # Note: Using 'bot_token' as corrected in previous step
    telegram_bot = TelegramBot(
        token=tg_conf.get('bot_token', ''),
        authorized_chat_id=tg_conf.get('chat_id', ''),
        connector=connector
    )
    connector.set_telegram(telegram_bot)

    if connector.start():
        logger.info("MT5 Connector started.")
    else:
        logger.error("Failed to start MT5 Connector.")
        return

    risk = RiskManager(conf.data)
    
    # 3. Setup UI
    app = TradingApp(bot_logic, connector, risk, telegram_bot)
    
    try:
        app.mainloop()
    except KeyboardInterrupt:
        pass
    finally:
        connector.stop()
        logger.info("Shutdown complete.")

if __name__ == "__main__":
    main()