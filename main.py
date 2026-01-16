import time
import logging
import pandas as pd
from bot_settings import Config
from core.execution import MT5Connector
from core.risk import RiskManager
from core.session import get_detailed_session_status
from core.telegram_bot import TelegramBot
from ui import TradingApp
import strategy.trend_following as trend
import strategy.ict_silver_bullet as ict_strat
import strategy.scalping as scalping
import strategy.breakout as breakout
import strategy.tbs_turtle as tbs_strat
import filters.volatility as volatility
import filters.spread as spread
import filters.news as news
from core.indicators import Indicators 

# --- Fixed Logger Setup (Prevents Duplicates) ---
def setup_logger():
    logger = logging.getLogger("Main")
    if logger.hasHandlers():
        logger.handlers.clear() # Clear existing handlers to prevent duplicates
    
    logger.setLevel(logging.INFO)
    logger.propagate = False # Stop messages from climbing to the root logger

    class CustomFormatter(logging.Formatter):
        format_str = "%(asctime)s | %(levelname)-8s | %(message)s"
        def format(self, record):
            formatter = logging.Formatter(self.format_str, datefmt="%H:%M:%S")
            return formatter.format(record)

    handler = logging.StreamHandler()
    handler.setFormatter(CustomFormatter())
    logger.addHandler(handler)
    return logger

logger = setup_logger()

def bot_logic(app):
    connector = app.connector
    risk = app.risk
    last_heartbeat = 0  
    is_synced = False 

    logger.info("Bot logic running: Real-Time Signal Logging Active.") 
    
    while app.bot_running:
        try:
            # 1. Pull dynamic settings from the UI
            symbol = app.symbol_var.get() 
            execution_tf = app.tf_var.get()
            max_pos_allowed = app.max_pos_var.get()
            user_lot = app.lot_var.get()

            info = connector.account_info
            curr_balance = info.get('balance', 0.0)
            curr_positions = info.get('total_count', 0)
            equity = info.get('equity', 0.0)
            
            # 2. Heartbeat Monitor
            if time.time() - last_heartbeat > 60:
                logger.info(f"❤️ Heartbeat | {symbol} | Equity: ${equity:,.2f} | Pos: {curr_positions}/{max_pos_allowed}")
                last_heartbeat = time.time()

            # 3. Data Sync Check
            candles = connector.get_tf_candles(execution_tf, 300)
            if len(candles) < 200:
                is_synced = False
                time.sleep(2); continue

            if not is_synced:
                logger.info(f"✅ Data Sync Successful: {len(candles)} candles for {symbol} ({execution_tf})")
                is_synced = True

            # 4. Global Trade Guards
            if not app.auto_trade_var.get(): 
                time.sleep(1); continue

            is_open, session_name, session_multiplier = get_detailed_session_status()
            if not is_open: 
                time.sleep(5); continue

            drawdown_pct = ((curr_balance - equity) / curr_balance) * 100 if curr_balance > 0 else 0
            can_trade, risk_reason = risk.can_trade(drawdown_pct)
            if not can_trade:
                time.sleep(5); continue
                
            if curr_positions >= max_pos_allowed:
                time.sleep(5); continue

            # 5. Market Filters (With Warning Logs)
            if news.is_high_impact_news_near(symbol):
                logger.warning(f"⚠️ Filter Block: High Impact News detected for {symbol}")
                time.sleep(5); continue

            if not spread.is_spread_fine(symbol, info.get('bid', 0), info.get('ask', 0)):
                logger.warning(f"⚠️ Filter Block: Spread too wide for {symbol}")
                time.sleep(2); continue

            if not volatility.is_volatility_sufficient(candles):
                logger.warning(f"⚠️ Filter Block: Volatility insufficient for {symbol}")
                time.sleep(5); continue

            # 6. Strategy Evaluation with Real-Time Reason Logging
            strategies = [
                ("ICT_SB", ict_strat.analyze_ict_setup(candles)),
                ("Trend", trend.analyze_trend_setup(candles)),
                ("Scalp", scalping.analyze_scalping_setup(candles)),
                ("Turtle", tbs_strat.analyze_tbs_turtle_setup(candles)),
                ("Breakout", breakout.analyze_breakout_setup(candles))
            ]

            # Locally calculate current ATR for the Risk Manager
            df = pd.DataFrame(candles)
            atr_series = Indicators.calculate_atr(df)
            current_atr = atr_series.iloc[-1] if not atr_series.empty else 0

            for name, (action, reason) in strategies:
                if action != "NEUTRAL":
                    current_price = info.get('ask') if action == "BUY" else info.get('bid')
                    # Use local ATR to set dynamic SL/TP
                    sl, tp = risk.calculate_sl_tp(current_price, action, current_atr)
                    
                    if connector.send_order(action, symbol, user_lot, sl, tp):
                        logger.info(f"🚀 {action} EXECUTED: {name} - {reason}")
                        risk.record_trade()
                        time.sleep(60); break 
                else:
                    # Log neutral reasons every cycle to confirm the bot is "thinking"
                    logger.info(f"📡 {name} Check: {reason if reason else 'No Setup'}")
                
            time.sleep(2) # Prevent loop from burning CPU
        except Exception as e:
            logger.error(f"Logic Error: {e}"); time.sleep(5)

def main():
    conf = Config()
    connector = MT5Connector(host='127.0.0.1', port=8001)
    
    tg_conf = conf.get('telegram', {})
    telegram_bot = TelegramBot(
        token=tg_conf.get('bot_token', ''), 
        authorized_chat_id=tg_conf.get('chat_id', ''), 
        connector=connector
    )
    connector.set_telegram(telegram_bot)

    if not connector.start(): return

    risk = RiskManager(conf.data)
    app = TradingApp(bot_logic, connector, risk, telegram_bot)
    
    try:
        app.mainloop()
    except KeyboardInterrupt: pass
    finally: connector.stop()

if __name__ == "__main__":
    main()