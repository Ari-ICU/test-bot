import time
import logging
import sys
import pandas as pd
import socket  # Added for connection stability
from datetime import datetime
from collections import deque
import tkinter as tk
from colorama import init, Fore, Style

# Core Framework Imports
from bot_settings import Config
from core.execution import MT5Connector
from core.risk import RiskManager
from core.session import get_detailed_session_status
from core.telegram_bot import TelegramBot, TelegramLogHandler
from ui import TradingApp

# --- ALL STRATEGY IMPORTS ---
import strategy.trend_following as trend
import strategy.ict_silver_bullet as ict_strat
import strategy.scalping as scalping
import strategy.breakout as breakout
import strategy.tbs_turtle as tbs_strat
import strategy.tbs_breakout_retest as tbs_retest
import strategy.reversal as reversal_strat
import strategy.crt_tbs_master as crt_tbs
import strategy.pd_array_parameter as pd_strat

# Analysis & Utilities
from core.indicators import Indicators 
from core.asset_detector import detect_asset_type
from core.predictor import AIPredictor
from core.patterns import detect_patterns

# Initialize Colorama
init(autoreset=True)

# --- REAL-TIME OPTIMIZED LOGGING ---
def setup_enhanced_logger():
    root_logger = logging.getLogger()
    if root_logger.hasHandlers(): root_logger.handlers.clear()
    root_logger.setLevel(logging.INFO)

    class RealTimeFormatter(logging.Formatter):
        COLORS = {
            logging.DEBUG: Fore.LIGHTBLACK_EX,
            logging.INFO: Fore.CYAN,
            logging.WARNING: Fore.YELLOW,
            logging.ERROR: Fore.RED,
            logging.CRITICAL: Fore.RED + Style.BRIGHT
        }
        def format(self, record):
            color = self.COLORS.get(record.levelno, Fore.WHITE)
            timestamp = f"{Fore.GREEN}{datetime.now().strftime('%H:%M:%S.%f')[:-3]}{Style.RESET_ALL}"
            prefix = f"{color}[{record.levelname:<8}]{Style.RESET_ALL}"
            return f"{timestamp} | {prefix} | {record.name} | {record.getMessage()}"

    class FlushStreamHandler(logging.StreamHandler):
        def emit(self, record):
            super().emit(record)
            self.flush()

    console_handler = FlushStreamHandler(sys.stdout)
    console_handler.setFormatter(RealTimeFormatter())
    root_logger.addHandler(console_handler)
    
    file_handler = logging.FileHandler("bot_engine.log", encoding='utf-8')
    file_handler.setFormatter(logging.Formatter("%(asctime)s.%(msecs)03d | %(levelname)-8s | %(name)s | %(message)s", datefmt="%H:%M:%S"))
    root_logger.addHandler(file_handler)
    
    return logging.getLogger("Main")

logger = setup_enhanced_logger()

# --- CONSTANTS ---
AUTO_TABS = ["M1", "M5", "M15", "M30", "H1", "H4", "D1"]

def get_higher_tf(ltf):
    mapping = {"M1": "H1", "M5": "H1", "M15": "H4", "M30": "H4", "H1": "D1", "H4": "D1", "D1": "W1"}
    return mapping.get(ltf, "D1")

def safe_reason_formatter(reason):
    """
    Convert strategy reason into a string safely for logging.
    Handles dict, None, NaN, or string values without crashing.
    """
    import math
    if isinstance(reason, dict):
        parts = []
        for k, v in reason.items():
            if v is None:
                parts.append(f"{k}=None")
            elif isinstance(v, (int, float)):
                if isinstance(v, float) and math.isnan(v):
                    parts.append(f"{k}=NaN")
                else:
                    parts.append(f"{k}={v:.5f}")
            else:
                parts.append(f"{k}={v}")
        return ", ".join(parts)
    else:
        return str(reason)

# --- BOT LOGIC (REAL-TIME OPTIMIZED) ---
def bot_logic(app):
    connector = app.connector
    risk = app.risk
    ai_predictor = AIPredictor()
    last_processed_bar = {tf: 0 for tf in AUTO_TABS}
    last_heartbeat = 0

    logger.info(f"{Fore.MAGENTA}==========================================")
    logger.info(f"{Fore.MAGENTA}  🚀 REAL-TIME ENGINE ACTIVE")
    logger.info(f"{Fore.MAGENTA}==========================================")

    while app.bot_running:
        try:
            # 1. Heartbeat Monitor
            if time.time() - last_heartbeat > 60:
                logger.info(f"💓 Multi-TF Heartbeat | Scanning Active for: {', '.join(AUTO_TABS)}")
                last_heartbeat = time.time()

            if not app.auto_trade_var.get():
                time.sleep(0.1); continue

            # 2. Multi-TF Scan Loop
            for scan_tf in AUTO_TABS:
                candles = connector.get_tf_candles(scan_tf, count=250)
                
                # FIX: Detailed logging for missing data
                if not candles or len(candles) < 100:
                    # Only log to console (not logger/Telegram) to avoid thread errors
                    if time.time() - last_heartbeat > 59: 
                        print(f"DEBUG: {scan_tf} insufficient data ({len(candles) if candles else 0}/100)")
                    continue

                current_bar_time = candles[-1]['time']
                
                # Check for new bar
                if current_bar_time <= last_processed_bar[scan_tf]:
                    continue
                
                start_time = time.perf_counter()
                last_processed_bar[scan_tf] = current_bar_time
                
                logger.info(f"⚡ {Fore.YELLOW}[REAL-TIME]{Style.RESET_ALL} New Bar {scan_tf} detected. Starting Scan...")

                # 3. Data Prep & Indicators
                df = pd.DataFrame(candles)
                df['ema_200'] = Indicators.calculate_ema(df['close'], 200)
                df['ema_50'] = Indicators.calculate_ema(df['close'], 50)
                df['rsi'] = Indicators.calculate_rsi(df['close'], 14)
                df['atr'] = Indicators.calculate_atr(df)
                bb_u, bb_l = Indicators.calculate_bollinger_bands(df['close'])
                df['upper_bb'], df['lower_bb'] = bb_u, bb_l
                
                patterns = detect_patterns(candles, df=df)
                current_atr = df['atr'].iloc[-1]
                asset_type = detect_asset_type(connector.active_symbol)
                htf_tf = get_higher_tf(scan_tf)
                htf_candles = connector.get_tf_candles(htf_tf, count=100)

                # 4. Strategy Routing
                all_strategies = [
                    ("AI_Predict", lambda: ai_predictor.predict(df, asset_type, app.style_var.get())),
                    ("Trend", lambda: trend.analyze_trend_setup(candles, df, patterns)),
                    ("Scalp", lambda: scalping.analyze_scalping_setup(candles, df)),
                    ("Breakout", lambda: breakout.analyze_breakout_setup(candles, df)),
                    ("TBS_Retest", lambda: tbs_retest.analyze_tbs_retest_setup(candles, df, patterns)),
                    ("ICT_SB", lambda: ict_strat.analyze_ict_setup(candles, df, patterns)),
                    ("TBS_Turtle", lambda: tbs_strat.analyze_tbs_turtle_setup(candles, df, patterns)),
                    ("CRT_TBS", lambda: crt_tbs.analyze_crt_tbs_setup(candles, htf_candles, connector.active_symbol, scan_tf, htf_tf, app.crt_reclaim_var.get())),
                    ("PD_Parameter", lambda: pd_strat.analyze_pd_parameter_setup(candles, df)),
                    ("Reversal", lambda: reversal_strat.analyze_reversal_setup(candles, df, patterns))
                ]

                for name, engine in all_strategies:
                    if not app.strat_vars.get(name, tk.BooleanVar(value=True)).get():
                        continue

                    try:
                        action, reason = engine()
                        safe_reason = safe_reason_formatter(reason)
                        app.update_strategy_status(name, action, safe_reason)

                        if action == "NEUTRAL":
                            logger.info(f"⚪ {Fore.LIGHTBLACK_EX}ANALYSIS{Style.RESET_ALL} | {name} | {scan_tf} | Status: {safe_reason}")
                        else:
                            logger.info(f"🎯 {Fore.GREEN}SIGNAL TRIGGERED{Style.RESET_ALL} | {name} | {action} on {scan_tf} | Reason: {safe_reason}")


                            # Position Check
                            if connector.account_info.get('total_count', 0) >= app.max_pos_var.get():
                                logger.warning(f"⏸️ Max Positions reached. Skipping {action} signal.")
                                break

                            try:
                                tick = None
                                for _ in range(5):  # Retry up to 5 times
                                    tick = connector.get_tick()
                                    if tick: break
                                    time.sleep(0.05)

                                if not tick:
                                    logger.warning(f"⚠️ No tick data for TBS_Retest on M15. Trade skipped.")
                                    continue

                                price = tick['ask'] if action == "BUY" else tick['bid']

                                if current_atr is None or pd.isna(current_atr) or current_atr <= 0:
                                    logger.warning(f"⚠️ Invalid ATR for TBS_Retest on M15. Trade skipped.")
                                    continue

                                sl, tp = risk.calculate_sl_tp(
                                    float(price),
                                    action,
                                    float(current_atr),
                                    connector.active_symbol,
                                    scan_tf
                                )

                                if connector.send_order(action, connector.active_symbol, app.lot_var.get(), sl, tp):
                                    latency = (time.perf_counter() - start_time) * 1000
                                    logger.info(f"✅ EXECUTED | TBS_Retest | Latency: {latency:.2f}ms")
                                    risk.record_trade()

                            except Exception as e:
                                logger.exception(f"🔥 Strategy crash [TBS_Retest] | Action safely skipped: {e}")


                    except Exception as e:
                        logger.exception(f"🔥 Strategy crash [{name}] | Action aborted")
                        app.update_strategy_status(name, "ERROR", str(e))


            time.sleep(0.01)
        except Exception as e:
            logger.error(f"💥 Bot Loop Crash: {e}", exc_info=True)
            time.sleep(1)

def main():
    conf = Config()
    # Ensure Port 8001 is clean
    connector = MT5Connector(host='127.0.0.1', port=8001)
    
    tg_conf = conf.get('telegram', {})
    telegram_bot = TelegramBot(
        token=tg_conf.get('bot_token', ''), 
        authorized_chat_id=tg_conf.get('chat_id', ''), 
        connector=connector
    )
    connector.set_telegram(telegram_bot)
    telegram_bot.start_polling()
    
    tg_handler = TelegramLogHandler(telegram_bot)
    tg_handler.setLevel(logging.INFO) 
    logger.addHandler(tg_handler)

    # Initialize connection
    if not connector.start():
        logger.critical("❌ FAILED TO CONNECT TO MT5 GATEWAY.")
        return

    risk = RiskManager(conf.data)
    app = TradingApp(bot_logic, connector, risk, telegram_bot)
    
    logger.info(f"系统就绪: {Fore.GREEN}Real-Time UI and Backend Linked.{Style.RESET_ALL}")
    
    try:
        app.mainloop()
    except KeyboardInterrupt:
        logger.info("🛑 Shutdown Requested.")
    finally:
        connector.stop()
        logger.info("👋 Shutdown complete.")

if __name__ == "__main__":
    main()