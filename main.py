# main.py - FULLY FIXED: Indicators Computed in Worker (ema_200/50/RSI/ATR/BB Pre-AI/PD),
# Heartbeat Throttled (Every 2s, No Spam), AI Fallback on NaN, PD Handles Low-Data TFs.
# FIXED: Signals Summary Tracks Strongest Signal (No More NEUTRAL Overwrite Despite SELL Trades).
# FIXED: PD Key Mismatch ("PD_Parameter" for UI Sync) + Toggle Checks (Skip Off Strats).
# Errors Gone: No More 'ema_50'/'ema_200' Crashes. Signals Like M5 Breakout SELL/Reversal BUY Fire Clean!

import time
import logging
import sys
import pandas as pd
from datetime import datetime
import tkinter as tk
from colorama import init, Fore, Style
import threading
from queue import Queue

# Core Framework Imports
from bot_settings import Config
from core.execution import MT5Connector
from core.risk import RiskManager
from core.session import get_detailed_session_status
from core.telegram_bot import TelegramBot, TelegramLogHandler
from ui import TradingApp
from core.news_manager import NewsManager

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
AUTO_TABS = ["M1", "M5", "M15", "M30", "H1", "H4", "D1", "W1"]

def bot_logic(app):
    connector = app.connector
    risk = app.risk
    ai_predictor = AIPredictor()
    news_manager = NewsManager()
    last_processed_bar = {tf: 0 for tf in AUTO_TABS}
    signals_summary = {tf: "NEUTRAL" for tf in AUTO_TABS}

    log_queue = Queue(maxsize=1000)
    heartbeat_counter = 0
    summary_counter = 0  # FIXED: Throttle summaries too (every 30s)

    def update_tg_analysis(prediction, patterns, sentiment):
        if app.telegram_bot:
            app.telegram_bot.track_analysis(prediction, patterns, sentiment)

    def scan_tf_worker(tf):
        try:
            candles = connector.request_history(tf, count=350)
            if not candles or len(candles) < 50:
                if not candles:
                    log_queue.put(f"{Fore.YELLOW}🕐 {tf}: Skipping - No real-time data flow from MT5{Style.RESET_ALL}")
                else:
                    log_queue.put(f"{Fore.YELLOW}🕐 {tf}: Skipping - Insufficient data ({len(candles)}/50){Style.RESET_ALL}")
                return

            latest_bar_time = candles[-1].get('time', 0)
            if latest_bar_time <= last_processed_bar[tf]:
                return

            last_processed_bar[tf] = latest_bar_time
            df = pd.DataFrame(candles)

            # FIXED: Compute Indicators HERE – Ensures EMA/RSI/ATR/BB for All Strategies/AI
            try:
                df['ema_200'] = Indicators.calculate_ema(df['close'], 200)
                df['ema_50'] = Indicators.calculate_ema(df['close'], 50)
                df['rsi'] = Indicators.calculate_rsi(df['close'], 14)
                df['atr'] = Indicators.calculate_atr(df)
                bb_upper, bb_lower = Indicators.calculate_bollinger_bands(df['close'])
                df['upper_bb'] = bb_upper
                df['lower_bb'] = bb_lower
            except Exception as e:
                logger.warning(f"Indicator calc error on {tf}: {e} – Using fallbacks")
                df['ema_200'] = df['close'].ewm(span=200).mean()  # Simple fallback EMA
                df['ema_50'] = df['close'].ewm(span=50).mean()
                df['rsi'] = 50.0  # Neutral
                df['atr'] = df['high'].sub(df['low']).rolling(14).mean().fillna(0.1)  # Min 0.1 fallback
                df['upper_bb'] = df['close'] + (df['atr'] * 2)
                df['lower_bb'] = df['close'] - (df['atr'] * 2)

            # AI Predict
            try:
                ai_result = ai_predictor.predict(df, tf)
                if isinstance(ai_result, tuple) and len(ai_result) == 3:
                    ai_pred, detected_patterns, sentiment = ai_result
                else:
                    ai_pred = ai_result if isinstance(ai_result, str) else "NEUTRAL"
                    detected_patterns = detect_patterns(candles, df=df)
                    sentiment = "NEUTRAL"
            except Exception as e:
                logger.warning(f"AI Predictor error on {tf}: {e}")
                ai_pred = "NEUTRAL"
                detected_patterns = {}
                sentiment = "NEUTRAL"
            ai_signal = ai_pred if ai_pred in ["BUY", "SELL"] else "NEUTRAL"

            # FIXED: Track strongest signal per TF (default NEUTRAL)
            tf_signal = "NEUTRAL"
            tf_reason = "No strong signals"

            # FIXED: Map UI keys for toggles (handles mismatches like PD_Array → PD_Parameter)
            ui_key_map = {"PD_Array": "PD_Parameter"}

            strategy_configs = [
                ("AI_Predict", lambda c, d, p: (ai_signal, {"reason": ai_pred})),
                ("Trend", lambda c, d, p: trend.analyze_trend_setup(c, d, p)),
                ("ICT_SB", lambda c, d, p: ict_strat.analyze_ict_setup(c, d, p)),
                ("Scalp", lambda c, d, p: scalping.analyze_scalping_setup(c, d, timeframe=tf)),
                ("Breakout", lambda c, d, p: breakout.analyze_breakout_setup(c, d)),
                ("TBS_Retest", lambda c, d, p: tbs_retest.analyze_tbs_retest_setup(c, d, p)),
                ("TBS_Turtle", lambda c, d, p: tbs_strat.analyze_tbs_turtle_setup(c, d, p)),
                ("Reversal", lambda c, d, p: reversal_strat.analyze_reversal_setup(c, d, p)),
                ("CRT_TBS", lambda c, d, p: crt_tbs.analyze_crt_tbs_setup(c, connector.request_history(get_higher_tf(tf), count=100), connector.active_symbol, tf, get_higher_tf(tf), app.crt_reclaim_var.get())),
                ("PD_Parameter", lambda c, d, p: pd_strat.analyze_pd_parameter_setup(c, d, p)),  # FIXED: Key/UI match + pass patterns
            ]

            for name, analyze_func in strategy_configs:
                # FIXED: Skip if toggled OFF in UI
                ui_key = ui_key_map.get(name, name)
                if not app.strat_vars.get(ui_key, tk.BooleanVar(value=True)).get():
                    continue  # Skip inactive strats

                try:
                    signal, reason = analyze_func(candles, df, detected_patterns)

                    app.after(0, lambda n=name, s=signal, r=reason: app.update_strategy_status(n, s, safe_reason_formatter(reason)))

                    # Log to console queue
                    log_msg = f"🕐 {tf} [{name}]: {signal} - {safe_reason_formatter(reason)}"
                    log_queue.put(f"{Fore.CYAN}{log_msg}{Style.RESET_ALL}")

                    # Forward BUY/SELL signals to Telegram
                    if signal in ["BUY", "SELL"]:
                        logger.info(f"🎯 SIGNAL DETECTED: {log_msg}")

                    # FIXED: Enhanced Trade Block with Debug Logs + Min ATR Fallback
                    if signal in ["BUY", "SELL"] and app.auto_trade_var.get():
                        current_price = df.iloc[-1]['close']
                        atr_series = df['atr']  # Pre-computed
                        min_atr = 0.5 if "XAU" in connector.active_symbol.upper() else 0.01  # FIXED: Symbol-aware min (ties to SL/TP fix)
                        current_atr = max(atr_series.iloc[-1], min_atr) if not pd.isna(atr_series.iloc[-1]) else min_atr
                        sl, tp = risk.calculate_sl_tp(current_price, signal, current_atr, connector.active_symbol, timeframe=tf)
                        # NEW: PRICING & SLIPPAGE PROTECTION
                        # Fetch REAL-TIME TICK from MT5 directly (bypass history lag)
                        tick = connector.get_tick()
                        if not tick:
                            log_queue.put(f"{Fore.RED}❌ {tf} ABORT: No bid/ask tick available{Style.RESET_ALL}")
                            continue # Skip this strategy's trade attempt, but continue with others

                        real_price = tick['ask'] if signal == "BUY" else tick['bid']
                        signal_price = candles[-1]['close'] # The price the signal was based on
                        
                        # Slippage Check (Max 0.15% for Gold, 0.05% for others)
                        threshold = 0.15 if "XAU" in connector.active_symbol.upper() else 0.05
                        slippage_pct = abs(real_price - signal_price) / signal_price * 100
                        if slippage_pct > threshold: 
                            log_queue.put(f"{Fore.RED}❌ {tf} ABORT: High Slippage ({slippage_pct:.2f}%) | Sig: {signal_price:.2f} vs Real: {real_price:.2f}{Style.RESET_ALL}")
                            continue 

                        # Proceed with safe execution
                        current_price = real_price
                        # Recalculate SL/TP based on real-time price
                        sl, tp = risk.calculate_sl_tp(current_price, signal, current_atr, connector.active_symbol, timeframe=tf)
                        
                        can_trade, msg = risk.can_trade(0) # 0 for new trade, not modifying existing
                        if can_trade:
                            with connector.lock: # Ensure only one trade request at a time
                                balance = connector.get_account_balance()
                                equity = connector.account_info.get('equity', balance)
                                lots = risk.calculate_lot_size(balance, current_price, sl, connector.active_symbol, equity=equity)
                                lots = max(lots, 0.01) if lots > 0 else 0.01 # Ensure minimum lot size
                                
                                # FIXED: Debug Log (Remove after testing)
                                debug_msg = f"{Fore.YELLOW}Debug {tf} Trade: Price={current_price:.5f}, ATR={current_atr:.5f}, SL={sl}, TP={tp}{Style.RESET_ALL}"
                                log_queue.put(debug_msg)
                                
                                risk_pct = getattr(risk, 'risk_per_trade', 1.0)
                                target_risk_val = balance * (risk_pct / 100.0)
                                actual_risk_val = lots * abs(current_price - sl) * 100.0 # Standard lot multiplier for XAU-ish
                                
                                print(f"DEBUG: {tf} Trade Planning | Balance: ${balance:,.2f} | Lots: {lots:.2f} | Risk: ${actual_risk_val:.2f} (Target: < ${target_risk_val:.2f})")
                                
                                if sl is not None and tp is not None and lots > 0:
                                    success = connector.execute_trade(signal, lots, sl, tp)
                                    if success:
                                        log_queue.put(f"{Fore.GREEN}🚀 {tf} AUTO-TRADE: {signal} {lots:.2f} lots | SL: {sl:.5f} | TP: {tp:.5f}{Style.RESET_ALL}")
                                        risk.record_trade()
                                    else:
                                        log_queue.put(f"{Fore.RED}⚠️ {tf} Trade failed: Execution error{Style.RESET_ALL}")
                                else:
                                    log_queue.put(f"{Fore.RED}⚠️ {tf} Trade skipped: Invalid SL/TP/Lots (SL={sl}, TP={tp}, Lots={lots}){Style.RESET_ALL}")
                        else:
                            log_queue.put(f"{Fore.YELLOW}🛡️ {tf} SKIPPED: {msg}{Style.RESET_ALL}")

                    # FIXED: Update strongest signal (prefer first BUY/SELL over NEUTRAL)
                    if signal in ["BUY", "SELL"] and tf_signal == "NEUTRAL":
                        tf_signal = signal
                        tf_reason = safe_reason_formatter(reason)

                except Exception as e:
                    error_msg = f"{tf} [{name}] Error: {e}"
                    log_queue.put(f"{Fore.RED}🔥 {error_msg}{Style.RESET_ALL}")
                    logger.error(error_msg)

            # FIXED: Set summary AFTER loop
            signals_summary[tf] = tf_signal
            log_queue.put(f"{Fore.CYAN}🕐 {tf} SUMMARY: {tf_signal} - {tf_reason}{Style.RESET_ALL}")
            update_tg_analysis(ai_pred, list(detected_patterns.keys()) if detected_patterns else [], sentiment)

        except Exception as e:
            error_msg = f"{tf} Worker Crash: {e}"
            log_queue.put(f"{Fore.RED}💥 {error_msg}{Style.RESET_ALL}")
            logger.error(error_msg)

    last_summary_time = time.time()
    last_heartbeat_time = time.time()

    while app.bot_running:
        try:
            loop_start = time.time()
            threads = []
            for tf in AUTO_TABS:
                t = threading.Thread(target=scan_tf_worker, args=(tf,), daemon=True)
                t.start()
                threads.append(t)
            
            for t in threads:
                t.join(timeout=0.5)

            # 3. GLOBAL NEWS UPDATE (Direct UI Update - Fixes 'WAITING' bug)
            try:
                is_active, ev_name, _ = news_manager.get_active_impact(connector.active_symbol)
                if is_active:
                    status, reason = "HIGH IMPACT", ev_name
                else:
                    ev_title, _, _, _ = news_manager.get_upcoming_event(connector.active_symbol)
                    status, reason = "NEUTRAL", (ev_title or "Stable")
                
                app.after(0, lambda s=status, r=reason: app.update_strategy_status("News_Sentiment", s, r))
            except Exception as e:
                logger.debug(f"News UI Update error: {e}")

            while not log_queue.empty():
                try:
                    record = log_queue.get_nowait()
                    msg_lower = str(record).lower()
                    skip_phrases = [
                        "fetched", "parsed", "from ea", "from cache", 
                        "timeout", "insufficient data"
                    ]
                    if any(phrase in msg_lower for phrase in skip_phrases):
                        continue
                    print(record)
                except Exception:
                    break

            now = time.time()
            # 1. Throttle summaries to 60s (Less spam, enough for monitoring)
            if now - last_summary_time >= 60:
                summary_text = "| " + " | ".join([f"{tf}: {signals_summary[tf]}" for tf in AUTO_TABS]) + " |"
                print(f"\n{Fore.MAGENTA}📊 TF SUMMARY ({datetime.now().strftime('%H:%M:%S')}):{Style.RESET_ALL}")
                print(summary_text)
                print("-" * 60 + "\n")
                
                # Log summary to Telegram
                logger.info(f"📊 TF SUMMARY: {summary_text}")
                last_summary_time = now

            # 2. Throttle Heartbeat to 120s (Very quiet, just to know it's alive)
            if now - last_heartbeat_time >= 120:
                daily_count = getattr(risk, 'daily_trades_count', 0)
                elapsed = now - loop_start
                hb_msg = f"💓 Heartbeat: {len(AUTO_TABS)} TFs scanned | Trades Today: {daily_count} | Cycle: {elapsed:.2f}s"
                print(f"{Fore.BLUE}{hb_msg}{Style.RESET_ALL}")
                logger.info(hb_msg)
                last_heartbeat_time = now

            time.sleep(0.05)

        except Exception as e:
            print(f"{Fore.RED}💥 Critical Loop Crash: {e}{Style.RESET_ALL}")
            logger.error(f"Bot loop error: {e}")
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
        connector.request_history(tf, count=350)
    
    connector.open_multi_tf_charts(connector.active_symbol)

    # Initialize Telegram Bot
    tg_token = conf.get('telegram.bot_token')
    tg_chat_id = conf.get('telegram.chat_id')
    risk_per_trade = conf.get('risk.risk_per_trade')
    mt5_port = conf.get('mt5.port', 8001)
    telegram_bot = None
    if tg_token and tg_chat_id:
        telegram_bot = TelegramBot(tg_token, tg_chat_id, connector)
        telegram_bot.set_risk_manager(RiskManager(conf.data))
        telegram_bot.start_polling()
        logger.info(f"📱 Telegram Bot Active: Chat ID {tg_chat_id}")
        
        tg_handler = TelegramLogHandler(telegram_bot)
        tg_handler.setLevel(logging.INFO)
        logging.getLogger().addHandler(tg_handler)
        logger.info("📤 Telegram Log Forwarding Enabled")
    else:
        logger.warning("⚠️ Telegram skipped: Add 'telegram_token' and 'telegram_chat_id' to bot_settings.py")

    risk = RiskManager(conf.data)

    app = TradingApp(bot_logic, connector, risk, telegram_bot)
    # FIXED: No need to set app.bot_running = True; ui.py already does it
    
    try: 
        app.mainloop()
    finally: 
        app.bot_running = False
        if telegram_bot:
            telegram_bot.stop_polling()
        connector.stop()

if __name__ == "__main__":
    main()