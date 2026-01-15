import time
import logging
import sys
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

# --- 1. Custom Colorful Logger ---
class CustomFormatter(logging.Formatter):
    grey = "\x1b[38;20m"
    green = "\x1b[32;20m"
    yellow = "\x1b[33;20m"
    red = "\x1b[31;20m"
    bold_red = "\x1b[31;1m"
    blue = "\x1b[34;20m"
    reset = "\x1b[0m"
    format_str = "%(asctime)s | %(levelname)-8s | %(message)s"

    FORMATS = {
        logging.DEBUG: grey + format_str + reset,
        logging.INFO: green + format_str + reset,
        logging.WARNING: yellow + format_str + reset,
        logging.ERROR: red + format_str + reset,
        logging.CRITICAL: bold_red + format_str + reset
    }

    def format(self, record):
        log_fmt = self.FORMATS.get(record.levelno)
        formatter = logging.Formatter(log_fmt, datefmt="%H:%M:%S")
        return formatter.format(record)

handler = logging.StreamHandler()
handler.setFormatter(CustomFormatter())
logging.basicConfig(level=logging.INFO, handlers=[handler], force=True)
logger = logging.getLogger("Main")

def get_symbol_category(symbol):
    """Returns 'CRYPTO' or 'FOREX' based on symbol name."""
    s = symbol.upper()
    if any(x in s for x in ["BTC", "ETH", "XRP", "SOL", "COIN"]):
        return "CRYPTO"
    return "FOREX"

def bot_logic(app):
    conf = Config()
    connector = app.connector
    risk = app.risk
    news_filter = NewsFilter(conf.get('sources', []))
    
    logger.info(f"✅ Bot logic initialized.")
    
    while app.bot_running:
        try:
            # 1. Check Auto-Trade Toggle
            if hasattr(app, 'auto_trade_var') and not app.auto_trade_var.get():
                time.sleep(1)
                continue

            # 2. Check Max Positions Limit (FROM UI)
            # Retrieve max positions dynamically from the UI
            try:
                max_positions = int(app.max_pos_var.get())
            except:
                max_positions = 10 # Default fallback
            
            current_trades = connector.account_info.get('total_count', 0)
            if current_trades >= max_positions:
                # Log only once every 10 seconds to avoid spamming
                if int(time.time()) % 10 == 0:
                    logger.debug(f"⚠️ Max positions reached ({current_trades}/{max_positions}). Waiting...")
                time.sleep(1)
                continue

            # 3. Market Status Check
            if not is_market_open("Auto"):
                time.sleep(5)
                continue

            # 4. Process Data
            candles = connector.get_latest_candles()
            if not candles or len(candles) < 20: 
                time.sleep(1)
                continue

            # 5. Strategy Analysis
            decisions = []
            
            # --- A. Check News Sentiment (Global Scan) ---
            news_action, news_reason, news_category = news_filter.get_sentiment_signal()
            
            if news_action != "NEUTRAL":
                active_symbol = app.symbol_var.get() if hasattr(app, 'symbol_var') else "XAUUSD"
                symbol_category = get_symbol_category(active_symbol)
                
                if news_category == "ALL" or news_category == symbol_category:
                    decisions.append((news_action, news_reason))
                    logger.info(f"📰 News Signal: {news_action} for {symbol_category} ({news_reason})")
                else:
                    logger.warning(f"⚠️ Skipping News: {news_category} news doesn't match active {symbol_category} symbol.")
            
            # --- B. Technical Strategies (Active Chart Only) ---
            decisions.append(trend.analyze_trend_setup(candles))
            decisions.append(reversal.analyze_reversal_setup(candles, 0, 0))
            decisions.append(breakout.analyze_breakout_setup(candles))
            
            # 6. Aggregate Decisions
            final_action = "NEUTRAL"
            execution_reason = ""
            
            for action, reasons in decisions:
                if action != "NEUTRAL":
                    final_action = action
                    execution_reason = reasons
                    break
            
            # 7. Execute Trade
            if final_action in ["BUY", "SELL"]:
                lot = 0.01
                if hasattr(app, 'lot_var'):
                    try: lot = float(app.lot_var.get())
                    except: lot = 0.01
                
                symbol = app.symbol_var.get() if hasattr(app, 'symbol_var') else "XAUUSD"

                # Use Live Price
                info = connector.account_info
                current_price = info.get('ask', 0.0) if final_action == "BUY" else info.get('bid', 0.0)
                if current_price == 0.0: current_price = candles[-1]['close']

                sl, tp = risk.calculate_sl_tp(current_price, final_action, 1.0)
                
                logger.info(f"🚀 EXECUTING: {final_action} {symbol} | Price: {current_price} | {execution_reason}")
                connector.send_order(final_action, symbol, lot, sl, tp)
                
                cooldown = 300 if "News" in execution_reason else 60
                time.sleep(cooldown)

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