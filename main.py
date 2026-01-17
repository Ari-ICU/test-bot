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

# --- Enhanced Logger Setup (Structured, No Duplicates, Rate-Limiting) ---
def setup_logger():
    logger = logging.getLogger("Main")
    if logger.hasHandlers():
        logger.handlers.clear()  # Clear existing handlers to prevent duplicates
    
    logger.setLevel(logging.INFO)
    logger.propagate = False  # Stop messages from climbing to the root logger

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
    """Simple rate-limiter for logs to prevent spam (e.g., per message type)."""
    def __init__(self, window=30, max_per_window=3):  # 3 logs per 30s
        self.window = window
        self.max_per_window = max_per_window
        self.log_history = deque()  # (timestamp, msg_key)

    def allow(self, msg_key):
        now = time.time()
        # Prune old entries
        while self.log_history and now - self.log_history[0][0] > self.window:
            self.log_history.popleft()
        # Check count in window
        recent_count = sum(1 for ts, key in self.log_history if now - ts <= self.window and key == msg_key)
        if recent_count < self.max_per_window:
            self.log_history.append((now, msg_key))
            return True
        return False

logger = setup_logger()

# Global rate limiters for common spam-prone logs
sync_limiter = RateLimiter(window=10, max_per_window=1)  # Sync logs: 1 per 10s
heartbeat_limiter = RateLimiter(window=60, max_per_window=1)  # Heartbeat: 1 per min
filter_limiter = RateLimiter(window=30, max_per_window=2)  # Filters: 2 per 30s

def bot_logic(app):
    connector = app.connector
    risk = app.risk
    last_heartbeat = 0  
    news_cooldown = 0  # Track news cooldown manually

    # Initialize last_symbol and last_tf before loop
    last_symbol = None
    last_tf = None

    logger.info("🤖 Bot Logic Initialized: Real-Time Signals Active (Forex/Crypto Support). Logging Optimized.") 
    
    cycle_start = time.time()
    while app.bot_running:
        try:
            cycle_start = time.time()
            # 1. Pull dynamic settings from the UI
            symbol = connector.active_symbol  # Use connector's confirmed/optimistic value
            execution_tf = connector.active_tf  # Use connector's confirmed/optimistic value
            max_pos_allowed = app.max_pos_var.get()
            user_lot = app.lot_var.get()

            info = connector.account_info
            curr_balance = info.get('balance', 0.0)
            curr_positions = info.get('total_count', 0)
            equity = info.get('equity', 0.0)
            bid, ask = info.get('bid', 0.0), info.get('ask', 0.0)
            
            # FIXED: Early Price Validation – Skip if invalid (e.g., MT5 not synced)
            if bid <= 0 or ask <= 0:
                # Check if we are even receiving account updates
                if info.get('name') == 'Disconnected':
                    logger.error("❌ MT5 DISCONNECTED: No account data received. Retrying in 10s.")
                else:
                    logger.warning(f"⏳ Invalid Prices for {symbol} (Bid: {bid}, Ask: {ask}). Skipping cycle.")
                time.sleep(10)
                continue
            
            # FIXED: Asset Type Detection & Logging (now after price check) - Rate-limited
            asset_type = detect_asset_type(symbol)
            if sync_limiter.allow(f"cycle_start_{symbol}"):  # Key per symbol to allow changes
                logger.info(f"--- 🔄 Cycle | {symbol} ({asset_type}) | Pos: {curr_positions}/{max_pos_allowed} | Equity: ${equity:,.2f} | Ask: {ask:.5f} ---")

            # Detect change and log/shorten sleep
            if last_symbol != symbol:
                logger.info(f"🎯 Symbol Switch Detected: {last_symbol or 'None'} → {symbol} ({asset_type})")
                last_symbol = symbol
                time.sleep(1)  # Short sleep on change
                continue
            elif last_tf != execution_tf:
                logger.info(f"🎯 TF Switch Detected: {last_tf or 'None'} → {execution_tf}")
                last_tf = execution_tf
                time.sleep(1)  # Short sleep on change
                continue

            # 2. Heartbeat Monitor (Rate-limited to once per minute)
            if time.time() - last_heartbeat > 60 and heartbeat_limiter.allow("heartbeat"):
                logger.info(f"❤️ Heartbeat OK | {symbol} ({asset_type}) @ {ask:.5f} | Equity: ${equity:,.2f} | Pos: {curr_positions} | Uptime: {time.time() - cycle_start:.0f}s")
                last_heartbeat = time.time()

            # 3. Pre-Trade Filters (Dynamic for Asset) - Rate-limited warnings
            if curr_positions >= max_pos_allowed:
                if filter_limiter.allow(f"max_pos_{symbol}"):
                    logger.info(f"🛑 Max Positions Hit: {curr_positions}/{max_pos_allowed} for {symbol}. Pausing.")
                time.sleep(10); continue

            if not volatility.is_volatility_sufficient(connector.get_tf_candles(execution_tf), symbol):
                if filter_limiter.allow(f"vol_filter_{symbol}"):
                    logger.debug(f"📉 Low Volatility Skipped for {symbol} on {execution_tf}")
                time.sleep(5); continue

            if not spread.is_spread_fine(symbol, bid, ask):
                if filter_limiter.allow(f"spread_filter_{symbol}"):
                    logger.debug(f"📊 High Spread Skipped for {symbol}: {ask - bid:.5f} pips")
                time.sleep(5); continue

            session_open, session_details = get_detailed_session_status(symbol)
            if not session_open:
                if filter_limiter.allow(f"session_closed_{symbol}"):
                    logger.info(f"⏰ Market Closed for {symbol}: {session_details}")
                time.sleep(30); continue

            # 4. News Filter (High-Impact Block) – FIXED: Tunable cooldown with logging
            news_blocked, news_details = news.is_high_impact_news_near(symbol)
            if news_blocked:
                if filter_limiter.allow(f"news_block_{symbol}"):
                    logger.warning(f"📰 High-Impact News Alert for {symbol}: {news_details} – Blocking Trades")
                if news_cooldown > 0:
                    remaining = max(0, news_cooldown - 5)
                    if remaining % 60 < 5:  # Log remaining every minute
                        logger.info(f"⏳ News Cooldown Active: {remaining}s left for {symbol}")
                    news_cooldown = remaining
                    time.sleep(5); continue
                news_cooldown = 300  # Reset to 5 min on new hit
                time.sleep(5); continue
            else:
                if news_cooldown > 0:
                    logger.info(f"✅ News Window Cleared for {symbol} – Resuming Trades")
                news_cooldown = 0  # Clear if no news

            # 5. Pull Candles & Analyze Strategies (with Real-Time Reason Logging)
            candles = connector.get_tf_candles(execution_tf)
            if len(candles) < 50:
                logger.warning(f"❌ Insufficient Data: Only {len(candles)} candles for {symbol} on {execution_tf}. Fetching more...")
                time.sleep(10); continue

            # FIXED: Skip ATR if no candles (edge case)
            if not candles:
                logger.warning(f"❌ Empty Candles for {symbol} on {execution_tf}. Skipping cycle.")
                time.sleep(5); continue

            # Locally calculate current ATR for the Risk Manager
            df = pd.DataFrame(candles)
            atr_series = Indicators.calculate_atr(df)
            current_atr = atr_series.iloc[-1] if not atr_series.empty else 0

            # FIXED: Robust strategy analysis with safe unpacking & debug logging
            strategy_results = []
            base_strategies = [
                ("ICT_SB", lambda: ict_strat.analyze_ict_setup(candles) if is_silver_bullet(symbol) else ("NEUTRAL", "Outside Silver Bullet Time")),
                ("Trend", lambda: trend.analyze_trend_setup(candles)),
                ("Scalp", lambda: scalping.analyze_scalping_setup(candles)),
                ("Turtle", lambda: tbs_strat.analyze_tbs_turtle_setup(candles)),
                ("Breakout", lambda: breakout.analyze_breakout_setup(candles))
            ]

            for name, strat_func in base_strategies:
                try:
                    result = strat_func()
                    # Ensure it's a tuple/list with at least 2 items; pad/truncate if needed
                    if isinstance(result, (tuple, list)):
                        if len(result) < 2:
                            result = (*result, "Incomplete signal data")  # Pad with default reason
                        elif len(result) > 2:
                            logger.warning(f"⚠️ Strategy '{name}' returned {len(result)} items (expected 2). Truncating extras: {result}")
                            result = result[:2]  # Keep only action + reason
                    else:
                        logger.warning(f"⚠️ Strategy '{name}' returned non-iterable: {type(result)}. Fallback to NEUTRAL.")
                        result = ("NEUTRAL", f"Invalid return from {name}")
                    
                    strategy_results.append((name, result))
                except Exception as e:
                    logger.error(f"💥 Strategy '{name}' crashed: {e}. Fallback to NEUTRAL.")
                    strategy_results.append((name, ("NEUTRAL", f"Error in {name}: {str(e)}")))

            strategies = strategy_results  # Now safe: all are (name, (action, reason))

            trade_executed = False
            for name, (action, reason) in strategies:  # Now guaranteed to unpack to 2
                if action != "NEUTRAL" and not trade_executed:
                    current_price = ask if action == "BUY" else bid
                    # Dynamic SL/TP & Lot via RiskManager
                    sl, tp = risk.calculate_sl_tp(current_price, action, current_atr, symbol)
                    dynamic_lot = risk.calculate_lot_size(curr_balance, current_price, sl, symbol, equity)
                    
                    if connector.send_order(action, symbol, dynamic_lot, sl, tp):
                        logger.info(f"🚀 TRADE EXECUTED | {action} {symbol} ({asset_type}) | Strategy: {name} | Reason: {reason} | Lot: {dynamic_lot:.3f} | SL: {sl:.5f} | TP: {tp:.5f}")
                        risk.record_trade()
                        if app.telegram_bot:
                            app.telegram_bot.send_message(f"🚀 {action} {symbol}: {name} - {reason} | Lot: {dynamic_lot:.3f}")
                        trade_executed = True
                        logger.info(f"😌 Post-Trade Cooldown: 60s for {symbol}")
                        time.sleep(60); break  # Cool-off after trade
                    else:
                        logger.warning(f"❌ Order Failed for {action} {symbol} ({name}): Check MT5/Connector")
                else:
                    # Log neutral reasons sparingly (DEBUG level, or rate-limit)
                    if logger.isEnabledFor(logging.DEBUG) and filter_limiter.allow(f"strategy_neutral_{name}_{symbol}"):
                        logger.debug(f"📡 {name} Neutral ({asset_type}): {reason if reason else 'No Clear Setup'}")
                
            # End-of-cycle sleep (adjusted for changes)
            if last_symbol == symbol and last_tf == execution_tf:
                time.sleep(2)  # Normal cycle sleep
            else:
                time.sleep(1)  # Already handled above, but safety
                
        except Exception as e:
            logger.error(f"💥 Critical Loop Error for {symbol or 'Unknown'}: {type(e).__name__}: {e}. Retrying in 5s.")
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
        logger.error("❌ Connector Startup Failed – Exiting Application.")
        return

    risk = RiskManager(conf.data)
    app = TradingApp(bot_logic, connector, risk, telegram_bot)
    
    logger.info("🎉 MT5 Algo Terminal Launched – Monitoring Active.")
    
    try:
        app.mainloop()
    except KeyboardInterrupt: 
        logger.info("🛑 Shutdown Requested by User – Graceful Exit.")
    except Exception as e:
        logger.error(f"💥 App Crash: {e} – Emergency Shutdown.")
    finally: 
        logger.info("🔄 Stopping Connector & Cleaning Up...")
        connector.stop()

if __name__ == "__main__":
    main()