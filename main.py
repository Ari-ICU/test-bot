# main.py 
import time
import logging
import pandas as pd
from datetime import datetime, timedelta
from collections import deque
from bot_settings import Config
from core.execution import MT5Connector
from core.risk import RiskManager
from core.session import get_detailed_session_status, is_silver_bullet
from core.telegram_bot import TelegramBot, TelegramLogHandler
from ui import TradingApp
import strategy.trend_following as trend
import strategy.ict_silver_bullet as ict_strat
import strategy.scalping as scalping
import strategy.breakout as breakout
import strategy.tbs_turtle as tbs_strat
import strategy.reversal as reversal_strat
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
    last_auto_state = app.auto_trade_var.get()

    logger.info("🤖 Bot Logic Initialized: Real-Time Signals Active.") 
    
    while app.bot_running:
        try:
            now_ts = time.time()
            curr_auto_state = app.auto_trade_var.get()

            # --- ENGINE STATE TRANSITION LOG ---
            if curr_auto_state != last_auto_state:
                if curr_auto_state:
                    logger.info("⚡ Engine Transition: AUTO-TRADING ENGAGED - Monitoring Markets...")
                else:
                    logger.info("🛑 Engine Transition: AUTO-TRADING DISENGAGED - Standing By.")
                last_auto_state = curr_auto_state
            
            # --- HEARTBEAT LOG (Every 60s) ---
            if heartbeat_limiter.allow("bot_alive"):
                status = "AUTO-ACTIVE" if curr_auto_state else "PAUSED (Manual Only)"
                logger.info(f"💓 Bot Heartbeat | Status: {status} | Symbol: {connector.active_symbol} | TF: {connector.active_tf}")

            if not app.auto_trade_var.get():
                time.sleep(2)
                continue

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

            # --- RISK MANAGEMENT GATEKEEPER ---
            drawdown = 0
            if curr_balance > 0:
                drawdown = ((curr_balance - equity) / curr_balance) * 100
            
            can_trade, reason = risk.can_trade(drawdown)
            if not can_trade:
                if filter_limiter.allow(f"risk_block_{reason[:10]}"):
                    logger.warning(f"🛡️ Risk Block: {reason}")
                time.sleep(10); continue
            
            # --- NEWS FILTER ---
            is_news_blocked, news_headline = news.is_high_impact_news_near(symbol)
            if is_news_blocked:
                if filter_limiter.allow(f"news_block_{symbol}"):
                    logger.warning(f"📰 News Block Active: {news_headline}")
                time.sleep(10); continue
            elif news_headline and filter_limiter.allow(f"news_info_{news_headline[:15]}"):
                logger.info(f"📰 News Update: {news_headline}")

            # --- DATA SYNC CHECK ---
            candles = connector.get_tf_candles(execution_tf, count=500)
            if not candles or len(candles) < 200:
                if heartbeat_limiter.allow("waiting_data"):
                    logger.info(f"⏳ Waiting for adequate candle data... Currently: {len(candles) if candles else 0}/200")
                time.sleep(5); continue

            # --- PRE-TRADE FILTERS ---
            if curr_positions >= max_pos_allowed:
                if filter_limiter.allow(f"max_pos_{symbol}"):
                    logger.info(f"⏸️ Max open positions ({max_pos_allowed}) reached for {symbol}")
                time.sleep(10); continue

            df = pd.DataFrame(candles)
            
            # --- CONSOLIDATED COMPUTATION (SINGLE-COMPUTE) ---
            # 1. Indicators
            df['ema_200'] = Indicators.calculate_ema(df['close'], 200)
            df['ema_50'] = Indicators.calculate_ema(df['close'], 50)
            df['rsi'] = Indicators.calculate_rsi(df['close'], 14)
            df['adx'] = Indicators.calculate_adx(df)
            
            st_res = Indicators.calculate_supertrend(df)
            df['supertrend'] = st_res[0] if isinstance(st_res, (tuple, list)) else pd.Series([False]*len(df))
            
            macd_res = Indicators.calculate_macd(df['close'])
            if isinstance(macd_res, (tuple, list)) and len(macd_res) >= 3:
                df['macd'], df['macd_signal'], df['macd_hist'] = macd_res
            
            bb_upper, bb_lower = Indicators.calculate_bollinger_bands(df['close'])
            df['upper_bb'], df['lower_bb'] = bb_upper, bb_lower
            df['is_squeezing'] = Indicators.is_bollinger_squeeze(df)
            
            stoch_k, stoch_d = Indicators.calculate_stoch(df)
            df['stoch_k'], df['stoch_d'] = stoch_k, stoch_d
            
            atr_series = Indicators.calculate_atr(df)
            current_atr = atr_series.iloc[-1] if not atr_series.empty else 0

            # 2. Patterns (Computed once per cycle)
            from core.patterns import detect_patterns
            patterns = detect_patterns(candles, df=df)

            # --- STRATEGY SCAN ---
            strategy_results = []
            
            # Diagnostic for visibility
            curr_adx = df['adx'].iloc[-1] if 'adx' in df else 0
            curr_rsi = df['rsi'].iloc[-1] if 'rsi' in df else 50
            if heartbeat_limiter.allow("market_diagnostics"):
                logger.info(f"📊 Market Health | Symbol: {symbol} | ADX: {curr_adx:.1f} | RSI: {curr_rsi:.1f}")

            base_strategies = [
                ("Trend", lambda: trend.analyze_trend_setup(candles, df=df, patterns=patterns)),
                ("Scalp", lambda: scalping.analyze_scalping_setup(candles, df=df)),
                ("Breakout", lambda: breakout.analyze_breakout_setup(candles, df=df)),
                ("ICT_SB", lambda: ict_strat.analyze_ict_setup(candles, df=df, patterns=patterns)),
                ("TBS_Turtle", lambda: tbs_strat.analyze_tbs_turtle_setup(candles, df=df, patterns=patterns)),
                ("Reversal", lambda: reversal_strat.analyze_reversal_setup(candles, df=df, patterns=patterns))
            ]

            signals_this_cycle = []
            neutral_summaries = []
            
            for name, strat_func in base_strategies:
                try:
                    action, reason = strat_func()
                    strategy_results.append((name, (action, reason)))
                    
                    # --- SYNC TO UI ---
                    color = "secondary"
                    if action != "NEUTRAL":
                        color = "success" if action == "BUY" else "danger"
                        signals_this_cycle.append(f"{name}: {action}")
                    elif reason and any(k in reason for k in ["Trend:", "Confluence", "Consolidating", "Outside", "No Pattern"]):
                        color = "warning"
                    
                    def update_ui(n=name, a=action, r=reason, c=color):
                        if n in app.strat_ui_items:
                            app.strat_ui_items[n]["status"].configure(text=a, bootstyle=f"{c}")
                            display_reason = r.replace(f"{n}:", "").strip()
                            if not display_reason: display_reason = "Scanning..."
                            app.strat_ui_items[n]["reason"].configure(text=display_reason[:40])
                    
                    app.after(0, update_ui)

                    if action == "NEUTRAL" and reason:
                        neutral_summaries.append(f"{name}: {reason[:30]}")

                except Exception as e:
                    logger.error(f"Strategy {name} failed: {e}")

            # Feedback log for active scanning
            if signals_this_cycle:
                logger.info(f"🎯 Signals Detected: {', '.join(signals_this_cycle)}")
            elif heartbeat_limiter.allow("scanning_feedback"):
                summary_str = " | ".join(neutral_summaries)
                logger.info(f"🔍 Scanning {symbol} ({execution_tf}) | Status: NEUTRAL | {summary_str}")

            # --- EXECUTION ---
            trade_executed = False
            for name, (action, reason) in strategy_results:
                if action != "NEUTRAL" and not trade_executed:
                    current_price = ask if action == "BUY" else bid
                    sl, tp = risk.calculate_sl_tp(current_price, action, current_atr, symbol)
                    dynamic_lot = risk.calculate_lot_size(curr_balance, current_price, sl, symbol, equity)
                    
                    if connector.send_order(action, symbol, dynamic_lot, sl, tp):
                        logger.info(f"🚀 {action} {symbol} Executed | Strategy: {name} | Reason: {reason} | Lot: {dynamic_lot}")
                        risk.record_trade()
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
    telegram_bot.start_polling() # Enable command listening
    
    # ADDED: Send all main logs to Telegram
    tg_handler = TelegramLogHandler(telegram_bot)
    tg_handler.setLevel(logging.INFO)
    logger.addHandler(tg_handler)

    if not connector.start(): 
        logger.error("❌ Connector Startup Failed.")
        return

    risk = RiskManager(conf.data)
    telegram_bot.set_risk_manager(risk)
    
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