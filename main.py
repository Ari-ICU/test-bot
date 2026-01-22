# main.py 
import time
import logging
import pandas as pd
from datetime import datetime, timedelta
from collections import deque
import tkinter as tk
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
import strategy.tbs_breakout_retest as tbs_retest
import strategy.reversal as reversal_strat
import strategy.crt_tbs_master as crt_tbs
import strategy.pd_array_parameter as pd_strat
import filters.volatility as volatility
import filters.spread as spread
import filters.news as news
from core.indicators import Indicators 
from core.asset_detector import detect_asset_type
from core.predictor import AIPredictor
from core.patterns import detect_patterns

# --- Multiple TF PROFIT PROTECTION LOGIC ---
def manage_all_tf_secure_profit(connector, risk, logger):
    """
    Monitors all open positions and uses their native TF data to:
    1. Move to Break-Even after a certain profit.
    2. Trail SL behind the previous candle Low/High ONLY if it moves favorably.
    """
    positions = connector.get_open_positions()
    if not positions:
        return

    for pos in positions:
        ticket = pos['ticket']
        symbol = pos['symbol']
        p_type = "BUY" if pos['type'] == 0 else "SELL"
        entry = pos.get('open_price', 0)
        curr_sl = pos.get('sl', 0)
        curr_tp = pos.get('tp', 0)
        
        # Use the bot's current Active TF for granular trailing
        pos_tf = connector.active_tf 
        
        tf_candles = connector.get_tf_candles(pos_tf, count=5)
        if not tf_candles:
            continue

        # Use the most recently COMPLETED candle
        prev_candle = tf_candles[1] if len(tf_candles) >= 2 else tf_candles[0]
        asset_val = detect_asset_type(symbol)
        
        curr_price = connector.account_info['bid'] if p_type == "BUY" else connector.account_info['ask']
        
        # BE and Trailing settings
        min_be_dist = entry * 0.0005 if asset_val == "forex" else entry * 0.005
        buffer = entry * 0.0001 if asset_val == "forex" else entry * 0.001
        
        if p_type == "BUY":
            # For BUY: profit when price rises above entry + min_be_dist
            if curr_price > entry + min_be_dist:
                # Trail SL below the previous candle's LOW for protection
                target_sl = prev_candle['low'] - buffer
                # Only move SL UP if it improves protection (higher SL = better break-even)
                if target_sl > curr_sl:
                    if connector.modify_order(ticket, target_sl, curr_tp, symbol=symbol):
                        logger.info(f"🛡️ Profit Secured ({pos_tf}): Moved {symbol} BUY SL to {target_sl:.2f}")
        else: # SELL
            # For SELL: profit when price drops below entry - min_be_dist
            if curr_price < entry - min_be_dist:
                # Trail SL above the previous candle's HIGH for protection
                target_sl = prev_candle['high'] + buffer
                # Only move SL DOWN if it improves protection (lower SL = better break-even)
                if curr_sl == 0 or target_sl < curr_sl:
                    if connector.modify_order(ticket, target_sl, curr_tp, symbol=symbol):
                        logger.info(f"🛡️ Profit Secured ({pos_tf}): Moved {symbol} SELL SL to {target_sl:.2f}")

# --- Enhanced Logger Setup ---
def setup_logger():
    import sys
    # Use the ROOT logger to capture logs from all modules (predictor, risk, etc.)
    root_logger = logging.getLogger()
    
    # Clear existing handlers to prevent duplicates
    if root_logger.hasHandlers():
        root_logger.handlers.clear()
    
    root_logger.setLevel(logging.INFO)

    class CustomFormatter(logging.Formatter):
        format_str = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
        def format(self, record):
            formatter = logging.Formatter(self.format_str, datefmt="%H:%M:%S")
            return formatter.format(record)

    # Stream Handler (Forced to STDOUT for terminal visibility)
    stdout_handler = logging.StreamHandler(sys.stdout)
    stdout_handler.setFormatter(CustomFormatter())
    root_logger.addHandler(stdout_handler)

    # File Handler (Persistent Log)
    file_handler = logging.FileHandler("bot_activity.log", encoding='utf-8')
    file_handler.setFormatter(logging.Formatter("%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"))
    root_logger.addHandler(file_handler)
    
    print("📢 Terminal Logger Initialized (Level: INFO)")
    sys.stdout.flush()
    
    return logging.getLogger("Main")

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
heartbeat_limiter = RateLimiter(window=30, max_per_window=1) # Reduced from 60s
filter_limiter = RateLimiter(window=10, max_per_window=1)
scan_limiter = RateLimiter(window=10, max_per_window=1) # NEW: 10s feedback loop

def get_htf_from_ltf(ltf):
    mapping = {
        "M1": "H1",
        "M5": "H4",
        "M15": "D1",
        "M30": "D1",
        "H1": "D1",
        "H4": "D1"
    }
    return mapping.get(ltf, "D1")

# main.py 

AUTO_TABS = ["M1", "M5", "M15", "M30", "H1", "H4", "D1"]

def bot_logic(app):
    connector = app.connector
    risk = app.risk
    last_heartbeat = 0  
    news_cooldown = 0
    last_processed_times = {tf: 0 for tf in AUTO_TABS}
    ai_predictor = AIPredictor()

    logger.info("🤖 Multi-TF Bot Logic Initialized: Scanning M1 to 1D.") 
    
    while app.bot_running:
        try:
            now_ts = time.time()
            if not app.auto_trade_var.get():
                time.sleep(0.5)
                continue

            manage_all_tf_secure_profit(connector, risk, logger)

            if heartbeat_limiter.allow("bot_heartbeat"):
                logger.info(f"💓 Bot Heartbeat | Symbol: {connector.active_symbol} | UI TF: {connector.active_tf}")

            # --- 1. DEFINE GLOBAL VARIABLES FOR THIS CYCLE ---
            symbol = connector.active_symbol
            info = connector.account_info
            asset_type = detect_asset_type(symbol) 
            selected_style = app.style_var.get()
            ui_reclaim = app.crt_reclaim_var.get()
            
            if info.get('bid', 0) <= 0:
                time.sleep(1); continue

            for scan_tf in AUTO_TABS:
                candles = connector.get_tf_candles(scan_tf, count=500)
                if not candles or len(candles) < 200:
                    continue

                current_candle_time = candles[-1]['time']
                if current_candle_time <= last_processed_times[scan_tf]:
                    continue
                
                last_processed_times[scan_tf] = current_candle_time
                df = pd.DataFrame(candles)
                
                # --- 2. CALCULATE ALL REQUIRED INDICATORS ---
                df['ema_200'] = Indicators.calculate_ema(df['close'], 200)
                df['ema_50'] = Indicators.calculate_ema(df['close'], 50)
                df['rsi'] = Indicators.calculate_rsi(df['close'], 14)
                df['adx'] = Indicators.calculate_adx(df)
                
                # Bollinger Bands (Fixes the 'upper_bb' error)
                bb_upper, bb_lower = Indicators.calculate_bollinger_bands(df['close'])
                df['upper_bb'], df['lower_bb'] = bb_upper, bb_lower
                
                # Stochastic
                stoch_k, stoch_d = Indicators.calculate_stoch(df)
                df['stoch_k'], df['stoch_d'] = stoch_k, stoch_d
                
                atr_series = Indicators.calculate_atr(df)
                current_atr = atr_series.iloc[-1] if not atr_series.empty else 0
                patterns = detect_patterns(candles, df=df)

                # --- 3. RUN STRATEGIES ---
                htf_tf = "H4" 
                htf_candles = connector.get_tf_candles(htf_tf, count=200)

                all_strategies = [
                    ("AI_Predict", lambda: ai_predictor.predict(df, asset_type=asset_type, style=selected_style)),
                    ("Trend", lambda: trend.analyze_trend_setup(candles, df=df, patterns=patterns)),
                    ("Scalp", lambda: scalping.analyze_scalping_setup(candles, df=df)),
                    ("Breakout", lambda: breakout.analyze_breakout_setup(candles, df=df)),
                    ("TBS_Retest", lambda: tbs_retest.analyze_tbs_retest_setup(candles, df=df, patterns=patterns)),
                    ("ICT_SB", lambda: ict_strat.analyze_ict_setup(candles, df=df, patterns=patterns)),
                    ("TBS_Turtle", lambda: tbs_strat.analyze_tbs_turtle_setup(candles, df=df, patterns=patterns)),
                    ("CRT_TBS", lambda: crt_tbs.analyze_crt_tbs_setup(candles, htf_candles, symbol, scan_tf, htf_tf, reclaim_pct=ui_reclaim)),
                    ("PD_Parameter", lambda: pd_strat.analyze_pd_parameter_setup(candles, df=df)),
                    ("Reversal", lambda: reversal_strat.analyze_reversal_setup(candles, df=df, patterns=patterns))
                ]

                trade_executed_on_tf = False
                for name, engine in all_strategies:
                    if not app.strat_vars.get(name, tk.BooleanVar(value=True)).get():
                        continue

                    action, reason = engine()
                    
                    if scan_tf == app.tf_var.get():
                        app.update_strategy_status(name, action, reason)

                    if action != "NEUTRAL" and not trade_executed_on_tf:
                        if info.get('total_count', 0) >= app.max_pos_var.get():
                            continue
                        
                        bid, ask = info.get('bid'), info.get('ask')
                        current_price = ask if action == "BUY" else bid
                        sl, tp = risk.calculate_sl_tp(current_price, action, current_atr, symbol, timeframe=scan_tf)
                        
                        if connector.send_order(action, symbol, app.lot_var.get(), sl, tp):
                            logger.info(f"🚀 {action} {symbol} found on {scan_tf} | Strategy: {name} | Reason: {reason}")
                            risk.record_trade()
                            trade_executed_on_tf = True 
                            time.sleep(1)

            time.sleep(0.1)
                
        except Exception as e:
            logger.error(f"💥 Multi-TF Loop Error: {e}")
            time.sleep(2)
    
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
    
    # Sync initial trade count with existing positions (wait for first poll)
    logger.info("📡 Syncing Initial Account State...")
    for _ in range(10): # Wait up to 10s
        current_pos = connector.account_info.get('total_count', 0)
        if current_pos > 0 or connector.server: # Found data or at least connection
            break
        time.sleep(1)
    
    current_pos = connector.account_info.get('total_count', 0)
    if current_pos > 0:
        for _ in range(current_pos):
            risk.record_trade()
        logger.info(f"📋 Risk Sync: Detected {current_pos} existing positions on {connector.active_symbol}. Daily Discipline updated.")
    else:
        logger.info("📋 Risk Sync: No active positions detected.")

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