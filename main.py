# main.py (Fully Fixed: Robust Strategy Unpacking, Error Isolation, Rate-Limiting)
import time
import logging
import pandas as pd
from datetime import datetime, timedelta
from collections import deque
from bot_settings import Config
from core.execution import MT5Connector
from core.risk import RiskManager
from core.session import get_detailed_session_status, is_silver_bullet
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
from core.asset_detector import detect_asset_type

# --- Enhanced Logger Setup ---
def setup_logger():
    logger = logging.getLogger("Main")
    if logger.hasHandlers():
        logger.handlers.clear()
    
    logger.setLevel(logging.INFO)
    logger.propagate = False

    class CustomFormatter(logging.Formatter):
        format_str = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
        def format(self, record):
            formatter = logging.Formatter(self.format_str, datefmt="%H:%M:%S")
            return formatter.format(record)

    handler = logging.StreamHandler()
    handler.setFormatter(CustomFormatter())
    logger.addHandler(handler)
    return logger

class RateLimiter:
    def __init__(self, window=30, max_per_window=3):
        self.window = window
        self.max_per_window = max_per_window
        self.log_history = deque()

    def allow(self, msg_key):
        now = time.time()
        while self.log_history and now - self.log_history[0][0] > self.window:
            self.log_history.popleft()
        recent_count = sum(1 for ts, key in self.log_history if now - ts <= self.window and key == msg_key)
        if recent_count < self.max_per_window:
            self.log_history.append((now, msg_key))
            return True
        return False

logger = setup_logger()
sync_limiter = RateLimiter(window=10, max_per_window=1)
heartbeat_limiter = RateLimiter(window=60, max_per_window=1)
filter_limiter = RateLimiter(window=30, max_per_window=2)

# main.py (Final Corrected Version)
def bot_logic(app):
    connector = app.connector
    risk = app.risk
    last_heartbeat = 0  
    news_cooldown = 0
    last_symbol = None
    last_tf = None

    logger.info("🤖 Bot Logic Initialized: Real-Time Signals Active.") 
    
    while app.bot_running:
        try:
            cycle_start = time.time()
            symbol = connector.active_symbol
            execution_tf = connector.active_tf
            max_pos_allowed = app.max_pos_var.get()

            info = connector.account_info
            bid, ask = info.get('bid', 0.0), info.get('ask', 0.0)
            curr_balance = info.get('balance', 0.0)
            curr_positions = info.get('total_count', 0)
            equity = info.get('equity', 0.0)
            
            if bid <= 0 or ask <= 0:
                time.sleep(5); continue
            
            # --- FIXED NEWS FILTER CALL ---
            # Correctly handle the single boolean return
            is_news_blocked = news.is_high_impact_news_near(symbol)
            if is_news_blocked:
                if filter_limiter.allow(f"news_block_{symbol}"):
                    logger.warning(f"📰 News Filter Active: Trades blocked for {symbol}")
                time.sleep(10); continue

            # --- PRE-TRADE FILTERS ---
            if curr_positions >= max_pos_allowed:
                time.sleep(10); continue

            candles = connector.get_tf_candles(execution_tf)
            if not candles or len(candles) < 50:
                time.sleep(10); continue

            df = pd.DataFrame(candles)
            atr_series = Indicators.calculate_atr(df)
            current_atr = atr_series.iloc[-1] if not atr_series.empty else 0

            # --- ROBUST STRATEGY ANALYSIS ---
            strategy_results = []
            base_strategies = [
                ("Trend", lambda: trend.analyze_trend_setup(candles)),
                ("Scalp", lambda: scalping.analyze_scalping_setup(candles)),
                ("Breakout", lambda: breakout.analyze_breakout_setup(candles))
            ]

            for name, strat_func in base_strategies:
                try:
                    result = strat_func()
                    # Defensive check for consistent (action, reason) unpacking
                    if isinstance(result, (tuple, list)) and len(result) >= 2:
                        strategy_results.append((name, (result[0], result[1])))
                except Exception as e:
                    logger.error(f"Strategy {name} failed: {e}")

            # --- EXECUTION ---
            trade_executed = False
            for name, (action, reason) in strategy_results:
                if action != "NEUTRAL" and not trade_executed:
                    current_price = ask if action == "BUY" else bid
                    sl, tp = risk.calculate_sl_tp(current_price, action, current_atr, symbol)
                    dynamic_lot = risk.calculate_lot_size(curr_balance, current_price, sl, symbol, equity)
                    
                    if connector.send_order(action, symbol, dynamic_lot, sl, tp):
                        logger.info(f"🚀 {action} {symbol} | Strategy: {name} | Reason: {reason}")
                        trade_executed = True
                        time.sleep(60); break

            time.sleep(2)
                
        except Exception as e:
            logger.error(f"💥 Critical Loop Error: {e}")
            time.sleep(5)

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

    if not connector.start(): 
        logger.error("❌ Connector Startup Failed.")
        return

    risk = RiskManager(conf.data)
    app = TradingApp(bot_logic, connector, risk, telegram_bot)
    logger.info("🎉 MT5 Algo Terminal Launched.")
    
    try:
        app.mainloop()
    except KeyboardInterrupt: 
        logger.info("🛑 Shutdown Requested.")
    finally: 
        connector.stop()

if __name__ == "__main__":
    main()