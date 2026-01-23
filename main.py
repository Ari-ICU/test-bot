import time
import logging
import sys
import pandas as pd
from datetime import datetime
import tkinter as tk
from colorama import init, Fore, Style

# Core Framework Imports
from bot_settings import Config
from core.execution import MT5Connector
from core.risk import RiskManager
from core.session import get_detailed_session_status
from core.telegram_bot import TelegramBot, TelegramLogHandler
from ui import TradingApp

# --- STRATEGY IMPORTS ---
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

init(autoreset=True)

# --- UTILITIES ---
def get_higher_tf(ltf):
    """Maps lower timeframes to higher timeframes for multi-TF strategies."""
    mapping = {
        "M1": "M15", "M5": "M30", "M15": "H1", 
        "M30": "H4", "H1": "H4", "H4": "D1", "D1": "W1"
    }
    return mapping.get(ltf, "D1")

def safe_reason_formatter(reason):
    """Safely converts dict or string reasons to string."""
    if isinstance(reason, dict):
        return ", ".join([f"{k}: {v}" for k, v in reason.items()])
    return str(reason)

def setup_enhanced_logger():
    root_logger = logging.getLogger()
    if root_logger.hasHandlers(): root_logger.handlers.clear()
    root_logger.setLevel(logging.INFO)
    console_handler = logging.StreamHandler(sys.stdout)
    formatter = logging.Formatter(f"{Fore.GREEN}%(asctime)s{Style.RESET_ALL} | [%(levelname)-8s] | %(name)s | %(message)s", datefmt="%H:%M:%S")
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)
    return logging.getLogger("Main")

logger = setup_enhanced_logger()
AUTO_TABS = ["M1", "M5", "M15", "M30", "H1", "H4", "D1"]

def bot_logic(app):
    connector = app.connector
    risk = app.risk
    ai_predictor = AIPredictor()
    last_processed_bar = {tf: 0 for tf in AUTO_TABS}

    # NEW: Track analysis for Telegram /analysis command
    def update_tg_analysis(prediction, patterns, sentiment):
        if app.telegram_bot:
            app.telegram_bot.track_analysis(prediction, patterns, sentiment)

    while app.bot_running:
        try:
            if not app.auto_trade_var.get():
                time.sleep(0.1); continue

            for scan_tf in AUTO_TABS:
                # Need at least 200 bars for EMA 200 + Bollinger Bands
                candles = connector.get_tf_candles(scan_tf, count=350)
                if not candles or len(candles) < 210: 
                    continue

                current_bar_time = candles[-1]['time']
                if current_bar_time <= last_processed_bar[scan_tf]: 
                    continue
                
                last_processed_bar[scan_tf] = current_bar_time
                df = pd.DataFrame(candles)

                # --- 1. FULL FEATURE PREPARATION (Required for AI & Scalp) ---
                try:
                    df['ema_200'] = Indicators.calculate_ema(df['close'], 200)
                    df['ema_50'] = Indicators.calculate_ema(df['close'], 50)
                    df['ema_20'] = Indicators.calculate_ema(df['close'], 20)
                    df['rsi'] = Indicators.calculate_rsi(df['close'], 14)
                    df['atr'] = Indicators.calculate_atr(df)
                    
                    # Fix: Add Bollinger Bands for AI Predictor
                    bb_upper, bb_lower = Indicators.calculate_bollinger_bands(df['close'])
                    df['upper_bb'] = bb_upper
                    df['lower_bb'] = bb_lower
                except Exception as e:
                    logger.error(f"Indicator calculation error on {scan_tf}: {e}")
                    continue
                
                # --- 2. MULTI-TF PREPARATION ---
                htf_tf = get_higher_tf(scan_tf)
                htf_candles = connector.get_tf_candles(htf_tf, count=100)

                patterns = detect_patterns(candles, df=df)
                current_atr = df['atr'].iloc[-1]
                asset_type = detect_asset_type(connector.active_symbol)

                # --- 3. ALL STRATEGIES ---
                all_strategies = [
                    ("AI_Predict", lambda: ai_predictor.predict(df, asset_type, app.style_var.get())),
                    ("Scalp", lambda: scalping.analyze_scalping_setup(candles, df, scan_tf)),  # FIXED: Pass scan_tf for guardrail
                    ("Trend", lambda: trend.analyze_trend_setup(candles, df, patterns)),
                    ("Breakout", lambda: breakout.analyze_breakout_setup(candles, df)),
                    ("ICT_SB", lambda: ict_strat.analyze_ict_setup(candles, df, patterns)),
                    ("CRT_TBS", lambda: crt_tbs.analyze_crt_tbs_setup(candles, htf_candles, connector.active_symbol, scan_tf, htf_tf, app.crt_reclaim_var.get())),
                    ("TBS_Turtle", lambda: tbs_strat.analyze_tbs_turtle_setup(candles, df, patterns)),
                    ("TBS_Retest", lambda: tbs_retest.analyze_tbs_retest_setup(candles, df, patterns)),
                    ("PD_Array", lambda: pd_strat.analyze_pd_parameter_setup(candles, df)),
                    ("Reversal", lambda: reversal_strat.analyze_reversal_setup(candles, df, patterns))
                ]

                # NEW: Aggregate for Telegram analysis cache
                ai_pred = "NEUTRAL"
                detected_patterns = []
                sentiment = "NEUTRAL"

                for name, engine in all_strategies:
                    try:
                        action, reason = engine()
                        app.update_strategy_status(name, action, safe_reason_formatter(reason))

                        # Aggregate for TG
                        if name == "AI_Predict" and action != "NEUTRAL":
                            ai_pred = action
                        if patterns:  # Simplified – track any patterns
                            detected_patterns = list(patterns.keys())[:3]  # Top 3
                        if action == "BUY":
                            sentiment = "BULLISH"
                        elif action == "SELL":
                            sentiment = "BEARISH"

                        if action != "NEUTRAL":
                            if pd.isna(current_atr) or current_atr <= 0: continue
                            tick = connector.get_tick()
                            if not tick: continue

                            price = float(tick['ask'] if action == "BUY" else tick['bid'])
                            sl, tp = risk.calculate_sl_tp(price, action, float(current_atr), connector.active_symbol, digits=5, timeframe=scan_tf)  # FIXED: Explicit digits=5

                            if sl is not None and tp is not None and not pd.isna(sl) and not pd.isna(tp):
                                if connector.send_order(action, connector.active_symbol, app.lot_var.get(), sl, tp):
                                    # Use round() to prevent "Precision" crash on string formatting
                                    logger.info(f"✅ EXECUTED {name} | Price: {price:.5f} | SL: {sl:.5f} | TP: {tp:.5f}")
                                    risk.record_trade()
                            else:
                                logger.warning(f"⚠️ Trade skipped for {name} on {scan_tf}: Invalid SL/TP calculation.")

                    except Exception as e:
                        logger.error(f"🔥 Strategy Error [{name}] on {scan_tf}: {e}")

                # Update TG cache after loop
                update_tg_analysis(ai_pred, detected_patterns, sentiment)

            time.sleep(0.01)
        except Exception as e:
            logger.error(f"💥 Critical Loop Crash: {e}")
            time.sleep(1)

def main():
    conf = Config()
    connector = MT5Connector(host='127.0.0.1', port=8001)
    if not connector.start():
        logger.critical("❌ FAILED TO CONNECT TO MT5 GATEWAY")
        return

    # Force warmup for all timeframes
    logger.info("📡 Warming up Multi-TF Data Sync...")
    for tf in AUTO_TABS: 
        connector.request_history(count=350)
    
    connector.open_multi_tf_charts(connector.active_symbol)

    # --- FIXED: Initialize Telegram Bot ---
    tg_token = conf.get('telegram.bot_token')  # Handles nest/env
    tg_chat_id = conf.get('telegram.chat_id')  # Auto-int
    risk_per_trade = conf.get('risk.risk_per_trade')  # 1.0 from your JSON
    mt5_port = conf.get('mt5.port', 8001)  # 8001 default
    telegram_bot = None
    if tg_token and tg_chat_id:
        telegram_bot = TelegramBot(tg_token, tg_chat_id, connector)
        telegram_bot.set_risk_manager(RiskManager(conf.data))  # Pass risk for /settings
        telegram_bot.start_polling()  # Starts background command listener
        logger.info(f"📱 Telegram Bot Active: Chat ID {tg_chat_id}")
        
        # Add Log Handler for Trade Alerts/Errors
        tg_handler = TelegramLogHandler(telegram_bot)
        tg_handler.setLevel(logging.WARNING)  # Tune: WARNING for less noise
        logging.getLogger().addHandler(tg_handler)
        logger.info("📤 Telegram Log Forwarding Enabled")
    else:
        logger.warning("⚠️ Telegram skipped: Add 'telegram_token' and 'telegram_chat_id' to bot_settings.py")

    risk = RiskManager(conf.data)  # FIXED: Instantiate risk here for Telegram

    app = TradingApp(bot_logic, connector, risk, telegram_bot)  # Now passes the instance
    
    try: 
        app.mainloop()
    finally: 
        if telegram_bot:
            telegram_bot.stop_polling()  # Graceful shutdown
        connector.stop()

if __name__ == "__main__":
    main()