import time
import logging
import sys
import pandas as pd
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

# --- ENHANCED LOGGING SYSTEM ---
def setup_enhanced_logger():
    root_logger = logging.getLogger()
    if root_logger.hasHandlers(): root_logger.handlers.clear()
    root_logger.setLevel(logging.INFO)

    class TerminalFormatter(logging.Formatter):
        COLORS = {
            logging.DEBUG: Fore.LIGHTBLACK_EX,
            logging.INFO: Fore.CYAN,
            logging.WARNING: Fore.YELLOW,
            logging.ERROR: Fore.RED,
            logging.CRITICAL: Fore.RED + Style.BRIGHT
        }
        def format(self, record):
            color = self.COLORS.get(record.levelno, Fore.WHITE)
            timestamp = f"{Fore.GREEN}{datetime.now().strftime('%H:%M:%S')}{Style.RESET_ALL}"
            prefix = f"{color}[{record.levelname:<8}]{Style.RESET_ALL}"
            return f"{timestamp} | {prefix} | {record.name} | {record.getMessage()}"

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(TerminalFormatter())
    root_logger.addHandler(console_handler)
    
    file_handler = logging.FileHandler("bot_engine.log", encoding='utf-8')
    file_handler.setFormatter(logging.Formatter("%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"))
    root_logger.addHandler(file_handler)
    return logging.getLogger("Main")

logger = setup_enhanced_logger()

# --- CONSTANTS ---
AUTO_TABS = ["M1", "M5", "M15", "M30", "H1", "H4", "D1"]

def get_higher_tf(ltf):
    mapping = {"M1": "H1", "M5": "H1", "M15": "H4", "M30": "H4", "H1": "D1", "H4": "D1", "D1": "W1"}
    return mapping.get(ltf, "D1")

# --- PROFIT PROTECTION (FIXED TSL SPAM) ---
def manage_profit_protection(connector, risk):
    positions = connector.get_open_positions()
    if not positions: return

    for pos in positions:
        try:
            symbol = pos['symbol']
            p_type = "BUY" if pos['type'] == 0 else "SELL"
            curr_sl = pos.get('sl', 0)
            ticket = pos['ticket']
            tp = pos.get('tp', 0)
            
            # 1. Define minimum move threshold to prevent server spam
            asset_type = detect_asset_type(symbol)
            min_move = 0.15 if asset_type != "forex" else 0.00015 # e.g., 15 points for Gold
            
            candles = connector.get_tf_candles(connector.active_tf, count=2)
            if not candles: continue
            
            # Use most recently COMPLETED candle for trailing
            prev_candle = candles[0]
            
            if p_type == "BUY":
                target_sl = prev_candle['low']
                # Only move if the improvement is significant
                if target_sl > (curr_sl + min_move):
                    connector.modify_order(ticket, target_sl, tp, symbol=symbol)
                    logger.info(f"🛡️ TSL UP | {symbol} New SL: {target_sl:.5f}")
            else:
                target_sl = prev_candle['high']
                # Only move if new SL is significantly lower (or if SL is 0)
                if curr_sl == 0 or target_sl < (curr_sl - min_move):
                    connector.modify_order(ticket, target_sl, tp, symbol=symbol)
                    logger.info(f"🛡️ TSL DOWN | {symbol} New SL: {target_sl:.5f}")
                    
        except Exception as e:
            logger.error(f"Trailing Error: {e}")

# --- BOT LOGIC (FIXED STRATEGY CRASH) ---
def bot_logic(app):
    connector = app.connector
    risk = app.risk
    ai_predictor = AIPredictor()
    last_processed_bar = {tf: 0 for tf in AUTO_TABS}

    logger.info(f"{Fore.MAGENTA}==========================================")
    logger.info(f"{Fore.MAGENTA}  BOT INITIALIZED: ALL STRATEGIES ACTIVE")
    logger.info(f"{Fore.MAGENTA}==========================================")

    while app.bot_running:
        try:
            if not app.auto_trade_var.get():
                time.sleep(0.5); continue

            # Run Profit Protection
            manage_profit_protection(connector, risk)

            for scan_tf in AUTO_TABS:
                candles = connector.get_tf_candles(scan_tf, count=400)
                if not candles or len(candles) < 100: continue

                current_bar_time = candles[-1]['time']
                if current_bar_time <= last_processed_bar[scan_tf]: continue
                
                last_processed_bar[scan_tf] = current_bar_time
                logger.info(f"🔎 {Fore.YELLOW}{scan_tf}{Style.RESET_ALL} Scan: {connector.active_symbol}")

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
                        
                        # FIX: Sanitize the reason to prevent "Format specifier" error
                        safe_reason = str(reason).replace("{", "[").replace("}", "]")
                        
                        app.update_strategy_status(name, action, safe_reason)

                        if action != "NEUTRAL":
                            if connector.account_info.get('total_count', 0) >= app.max_pos_var.get():
                                logger.warning(f"⚠️ {name} signal ignored: Max Positions reached.")
                                break

                            price = connector.account_info['ask'] if action == "BUY" else connector.account_info['bid']
                            sl, tp = risk.calculate_sl_tp(price, action, current_atr, connector.active_symbol, scan_tf)
                            
                            logger.info(f"🎯 {Fore.GREEN}SIGNAL{Style.RESET_ALL} | {name} | {action} on {scan_tf} | Reason: {safe_reason}")
                            
                            if connector.send_order(action, connector.active_symbol, app.lot_var.get(), sl, tp):
                                logger.info(f"✅ {Fore.GREEN}EXECUTED{Style.RESET_ALL} | {name} | Price: {price:.5f}")
                                risk.record_trade()
                                break 
                    except Exception as strat_err:
                        # exc_info=True helps you find the exact line in the strategy that is broken
                        logger.error(f"Error in Strategy {name}: {strat_err}", exc_info=True)

            time.sleep(0.1)
        except Exception as e:
            logger.error(f"💥 Bot Loop Crash: {e}", exc_info=True)
            time.sleep(5)

def main():
    conf = Config()
    connector = MT5Connector(host='127.0.0.1', port=8001)
    
    tg_conf = conf.get('telegram', {})
    telegram_bot = TelegramBot(token=tg_conf.get('bot_token', ''), authorized_chat_id=tg_conf.get('chat_id', ''), connector=connector)
    connector.set_telegram(telegram_bot)
    telegram_bot.start_polling()
    
    tg_handler = TelegramLogHandler(telegram_bot)
    tg_handler.setLevel(logging.WARNING)
    logger.addHandler(tg_handler)

    if not connector.start():
        logger.critical("❌ FAILED TO CONNECT TO MT5 GATEWAY.")
        return

    risk = RiskManager(conf.data)
    app = TradingApp(bot_logic, connector, risk, telegram_bot)
    
    logger.info("系统就绪: UI and Backend Linked.")
    
    try:
        app.mainloop()
    except KeyboardInterrupt:
        logger.info("🛑 Keyboard interrupt received.")
    finally:
        connector.stop()
        logger.info("👋 Shutdown complete.")

if __name__ == "__main__":
    main()