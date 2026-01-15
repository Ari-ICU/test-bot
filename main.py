import time
import logging
import sys
from config import Config
from core.execution import MT5Connector
from core.risk import RiskManager
from core.session import is_market_open
from core.telegram_bot import TelegramBot, TelegramLogHandler # <--- Import Handler
from filters.news import NewsFilter
from ui import TradingApp
import strategy.trend_following as trend
import strategy.reversal as reversal
import strategy.breakout as breakout

# --- Custom Logger ---
class CustomFormatter(logging.Formatter):
    format_str = "%(asctime)s | %(levelname)-8s | %(message)s"
    def format(self, record):
        formatter = logging.Formatter(self.format_str, datefmt="%H:%M:%S")
        return formatter.format(record)

handler = logging.StreamHandler()
handler.setFormatter(CustomFormatter())
logging.basicConfig(level=logging.INFO, handlers=[handler], force=True)
logger = logging.getLogger("Main")

def bot_logic(app):
    conf = Config()
    connector = app.connector
    risk = app.risk
    news_filter = NewsFilter(conf.get('sources', []))
    
    logger.info(f"✅ Bot logic initialized.")
    
    # --- TRADE MONITOR VARIABLES ---
    last_balance = 0.0
    last_positions = 0
    first_run = True
    
    while app.bot_running:
        try:
            # 1. Get Current Account State
            info = connector.account_info
            curr_balance = info.get('balance', 0.0)
            curr_positions = info.get('total_count', 0)
            
            # Initialize tracker on first run
            if first_run and curr_balance > 0:
                last_balance = curr_balance
                last_positions = curr_positions
                first_run = False

            # ----------------------------------------
            # 🛑 REAL-TIME SL / TP MONITOR
            # ----------------------------------------
            if not first_run:
                # Logic: If positions DECREASED, a trade must have closed
                if curr_positions < last_positions:
                    pnl = curr_balance - last_balance
                    
                    # Filter out tiny changes (swaps/commissions without close)
                    if abs(pnl) > 0.01: 
                        if pnl > 0:
                            msg = f"💰 <b>TAKE PROFIT HIT!</b>\nProfit: +${pnl:.2f}\nNew Balance: ${curr_balance:,.2f}"
                            logger.info(f"💰 TP Hit: +${pnl:.2f}") # Logs to Console + Telegram
                        else:
                            msg = f"🛑 <b>STOP LOSS HIT!</b>\nLoss: -${abs(pnl):.2f}\nNew Balance: ${curr_balance:,.2f}"
                            logger.warning(f"🛑 SL Hit: -${abs(pnl):.2f}") # Logs to Console + Telegram
                        
                        # Explicitly send the formatted message if needed
                        # (The logger above will send it, but this ensures a clean format)
                        if app.telegram_bot:
                            app.telegram_bot.send_message(msg)

                # Update trackers for next loop
                last_positions = curr_positions
                last_balance = curr_balance
            # ----------------------------------------

            # 2. Check Auto-Trade Toggle
            if hasattr(app, 'auto_trade_var') and not app.auto_trade_var.get():
                time.sleep(1)
                continue

            # 3. Market Status Check
            if not is_market_open("Auto"):
                time.sleep(5)
                continue

            # 4. Strategy & Execution Logic ...
            candles = connector.get_latest_candles()
            if not candles or len(candles) < 20: 
                time.sleep(1)
                continue

            # (Your existing strategy logic here...)
            decisions = []
            
            # Check News
            news_action, news_reason, news_category = news_filter.get_sentiment_signal()
            if news_action != "NEUTRAL":
                decisions.append((news_action, news_reason))
            
            # Check Tech
            decisions.append(trend.analyze_trend_setup(candles))
            decisions.append(reversal.analyze_reversal_setup(candles, 0, 0))
            decisions.append(breakout.analyze_breakout_setup(candles))
            
            final_action = "NEUTRAL"
            execution_reason = ""
            
            for action, reasons in decisions:
                if action != "NEUTRAL":
                    final_action = action
                    execution_reason = reasons
                    break
            
            if final_action in ["BUY", "SELL"]:
                lot = 0.01
                if hasattr(app, 'lot_var'):
                    try: lot = float(app.lot_var.get())
                    except: lot = 0.01
                
                symbol = app.symbol_var.get() if hasattr(app, 'symbol_var') else "XAUUSD"
                
                # Get current price
                current_price = info.get('ask', 0.0) if final_action == "BUY" else info.get('bid', 0.0)
                if current_price == 0.0: current_price = candles[-1]['close']

                sl, tp = risk.calculate_sl_tp(current_price, final_action, 1.0)
                
                logger.info(f"🚀 EXECUTING: {final_action} {symbol} | Price: {current_price} | {execution_reason}")
                connector.send_order(final_action, symbol, lot, sl, tp)
                
                time.sleep(60) # Cooldown

            time.sleep(1)

        except Exception as e:
            logger.error(f"❌ Logic Error: {e}")
            time.sleep(5)

def main():
    conf = Config()
    
    connector = MT5Connector(
        host=conf.get('mt5', {}).get('host', '127.0.0.1'),
        port=conf.get('mt5', {}).get('port', 8001)
    )
    
    tg_conf = conf.get('telegram', {})
    telegram_bot = TelegramBot(
        token=tg_conf.get('bot_token', ''),
        authorized_chat_id=tg_conf.get('chat_id', ''),
        connector=connector
    )
    connector.set_telegram(telegram_bot)

    if connector.start():
        logger.info("✅ MT5 Connector started.")
    else:
        logger.error("❌ Failed to start MT5 Connector.")
        return

    # --- ATTACH REAL-TIME LOGGING ---
    tg_handler = TelegramLogHandler(telegram_bot)
    tg_handler.setLevel(logging.INFO) # Sends INFO, WARNING, ERROR to Telegram
    logging.getLogger().addHandler(tg_handler)
    # --------------------------------

    risk = RiskManager(conf.data)
    app = TradingApp(bot_logic, connector, risk, telegram_bot)
    
    try:
        app.mainloop()
    except KeyboardInterrupt:
        pass
    finally:
        connector.stop()
        logger.info("🛑 Shutdown complete.")

if __name__ == "__main__":
    main()