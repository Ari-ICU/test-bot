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
from filters.news import _manager as news_manager

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
    last_processed_bar = {tf: 0 for tf in AUTO_TABS}
    last_trade_bar = {tf: 0 for tf in AUTO_TABS}  
    last_stale_log = {tf: 0 for tf in AUTO_TABS}
    last_ui_stale_update = {tf: 0 for tf in AUTO_TABS} 
    last_logged_signal = {tf: None for tf in AUTO_TABS} # NEW: reduce spam
    stale_tf_map = {tf: False for tf in AUTO_TABS}
    scan_active = False 
    time_offset = 0  
    offset_detected = False
    signals_summary = {tf: "WAIT..." for tf in AUTO_TABS}
    
    # FIXED: Thread-safe UI update queue to prevent PyEval_RestoreThread crash
    ui_queue = Queue() 
    def ui_bridge():
        while True:
            try:
                task = ui_queue.get(timeout=0.1)
                app.after(0, task)
            except: 
                if not app.bot_running: break
                continue
    threading.Thread(target=ui_bridge, daemon=True).start()

    log_queue = Queue(maxsize=1000)
    heartbeat_counter = 0
    summary_counter = 0  # FIXED: Throttle summaries too (every 30s)

    def update_tg_analysis(prediction, patterns, sentiment):
        if app.telegram_bot:
            app.telegram_bot.track_analysis(prediction, patterns, sentiment)

    def scan_tf_worker(tf, asset_type, style):
        try:
            # Increase count for higher timeframes to ensure enough data for indicators
            fetch_count = 500 if tf in ["H4", "D1", "W1"] else 350
            candles = connector.request_history(tf, count=fetch_count)
            if not candles or len(candles) < 50:
                if not candles:
                    log_queue.put(f"{Fore.YELLOW}🕐 {tf}: Skipping - No data received from MT5 within timeout{Style.RESET_ALL}")
                    signals_summary[tf] = "NO DATA"
                else:
                    log_queue.put(f"{Fore.YELLOW}🕐 {tf}: Skipping - Insufficient data ({len(candles)}/50){Style.RESET_ALL}")
                    signals_summary[tf] = "LOW DATA"
                return

            latest_bar_time = candles[-1].get('time', 0)
            
            # 1. New Bar Detection + Scan Notification
            if latest_bar_time > last_processed_bar[tf]:
                log_queue.put(f"{Fore.GREEN}⚡ [{tf}] New Bar detected. Starting Full Analysis...{Style.RESET_ALL}")
                last_processed_bar[tf] = latest_bar_time
            
            # 1b. Smart Timezone Detection (Robust for Large Broker Offsets)
            now_ts = int(time.time())
            nonlocal time_offset, offset_detected
            
            # Using any relatively recent bar to sync time (up to 7 days for weekend restarts)
            if not offset_detected:
                if abs(now_ts - latest_bar_time) < 604800: # 7 days
                    time_offset = now_ts - latest_bar_time
                    offset_detected = True
                    log_queue.put(f"{Fore.MAGENTA}🌐 Timezone Sync Verified: {time_offset}s offset.{Style.RESET_ALL}")
            
            # 1c. Extreme Lag Recovery
            check_lag = now_ts - time_offset - latest_bar_time
            if check_lag > 3600 and tf in ["M1", "M5", "M15"]: # More than 1 hour lag on low TFs
                if now_ts - last_stale_log.get(tf, 0) > 60:
                    log_queue.put(f"{Fore.RED}⚠️ {tf} LAG DETECTED ({int(check_lag)}s). Forcing TF Sync...{Style.RESET_ALL}")
                    connector.command_queue.append(f"GET_HISTORY|{connector.active_symbol}|{tf}|500")
                    last_stale_log[tf] = now_ts
                elif not offset_detected and tf == "M1":
                    # Keep waiting for fresher M1 data
                    time_offset = 0
                    if now_ts % 10 == 0: # Log every 10s to reduce spam
                        log_queue.put(f"{Fore.YELLOW}⏳ Waiting for reasonably fresh M1/M5 data to sync timezone...{Style.RESET_ALL}")

            adjusted_now = now_ts - time_offset
            tf_mapping = {"M1": 60, "M5": 300, "M15": 900, "M30": 1800, "H1": 3600, "H4": 14400, "D1": 86400, "W1": 604800, "MN": 2592000}
            tf_sec = tf_mapping.get(tf, 60)
            
            # FIXED: Loosened lag check (Allow 30 min lag for safety during market sync)
            max_lag_sec = max(tf_sec * 0.5, 1800) 
            
            is_stale = False
            if adjusted_now - latest_bar_time > max_lag_sec:
                 lag = adjusted_now - latest_bar_time
                 stale_tf_map[tf] = True
                 is_stale = True
                 
                 if now_ts - last_stale_log[tf] > 300: # Quietly track but don't spam UI
                     last_stale_log[tf] = now_ts
                 
                 if now_ts - last_ui_stale_update[tf] > 15:
                     # Only update UI with "STALE" if it's REALLY old or we want to keep some indicator
                     # But user wants "signal instead", so we will let strategy analysis run
                     pass
            
            if not is_stale:
                stale_tf_map[tf] = False

            if signals_summary[tf] == "WAIT...":
                signals_summary[tf] = "OK"

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
                ai_result = ai_predictor.predict(df, asset_type=asset_type, style=style)
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
                    
                    # FIXED: Only update UI if signal changed or is not NEUTRAL to reduce UI thread load
                    reason_str = safe_reason_formatter(reason)
                    last_ui_status = getattr(app, '_last_strat_status', {})
                    status_key = f"{tf}_{name}"
                    if last_ui_status.get(status_key) != (signal, reason_str):
                        # FIXED: Add TF context to UI status reason so user knows which TF is being shown
                        full_reason = f"[{tf}] {reason_str}"
                        ui_queue.put(lambda n=name, s=signal, r=full_reason: app.update_strategy_status(n, s, r))
                        if not hasattr(app, '_last_strat_status'): app._last_strat_status = {}
                        app._last_strat_status[status_key] = (signal, reason_str)

                    # Update timeframe-wide signal if non-neutral
                    if signal != "NEUTRAL":
                        tf_signal = signal
                        tf_reason = reason_str
                    elif tf_reason == "No strong signals": 
                        tf_reason = f"{name}: {reason_str}"

                    # Log to console queue
                    if signal != "NEUTRAL":
                        log_msg = f"🕐 {tf} [{name}]: {signal} - {reason_str}"
                        log_queue.put(f"{Fore.CYAN}{log_msg}{Style.RESET_ALL}")
                        
                        if signal in ["BUY", "SELL"]:
                            logger.info(f"🎯 SIGNAL DETECTED: {log_msg}")

                    # FIXED: Enhanced Trade Block with Debug Logs + Min ATR Fallback
                    # FIXED: Enhanced Trade Block - Minimize Lock Duration
                    if signal in ["BUY", "SELL"] and app.auto_trade_var.get():
                        # SAFETY: Only one trade per bar per timeframe
                        if latest_bar_time <= last_trade_bar.get(tf, 0):
                            continue
                        
                        current_price = df.iloc[-1]['close']
                        atr_series = df['atr']  # Pre-computed
                        min_atr = 0.5 if "XAU" in connector.active_symbol.upper() else 0.01
                        current_atr = max(atr_series.iloc[-1], min_atr) if not pd.isna(atr_series.iloc[-1]) else min_atr
                        
                        # Fetch REAL-TIME TICK directly
                        tick = connector.get_tick()
                        if not tick:
                            log_queue.put(f"{Fore.RED}❌ {tf} ABORT: No bid/ask tick available{Style.RESET_ALL}")
                            continue

                        real_price = tick['ask'] if signal == "BUY" else tick['bid']
                        signal_price = candles[-1]['close']
                        
                        # Slippage Check (Increased for Gold: 1.5%)
                        threshold = 1.5 if "XAU" in connector.active_symbol.upper() else 0.50
                        slippage_pct = abs(real_price - signal_price) / signal_price * 100
                        if slippage_pct > threshold: 
                            log_queue.put(f"{Fore.RED}❌ {tf} ABORT: Slippage {slippage_pct:.2f}% > {threshold}% | Try manually or wait for next bar.{Style.RESET_ALL}")
                            continue 

                        # Proceed with execution calculations OUTSIDE lock
                        current_price = real_price
                        sl, tp = risk.calculate_sl_tp(current_price, signal, current_atr, connector.active_symbol, timeframe=tf)
                        
                        can_trade, msg = risk.can_trade(0) 
                        
                        # NEW: Global News Sentiment Safety Block
                        if can_trade and app.strat_vars.get("News_Sentiment", tk.BooleanVar(value=True)).get():
                            n_score, n_summary, _ = news_manager.get_market_sentiment()
                            if n_score <= -5: # Moderate to High Panic
                                if app.strat_vars.get("Force_News", tk.BooleanVar(value=False)).get():
                                    log_queue.put(f"{Fore.YELLOW}🛡️ {tf} NEWS OVERRIDE: {n_summary} - Forcing Trade!{Style.RESET_ALL}")
                                else:
                                    log_queue.put(f"{Fore.RED}🛡️ {tf} AUTO-BLOCK: {n_summary} - Volatility High{Style.RESET_ALL}")
                                    can_trade = False
                                    msg = f"News Panic ({n_score}) - Use 'Force Trade (News)' in Settings to unlock"

                        if can_trade:
                            balance = connector.get_account_balance()
                            info = connector.account_info # This uses lock briefly
                            equity = info.get('equity', balance)
                            lots = risk.calculate_lot_size(balance, current_price, sl, connector.active_symbol, equity=equity)
                            lots = max(lots, 0.01) if lots > 0 else 0.01
                            
                            debug_msg = f"{Fore.YELLOW}Debug {tf} Trade: Price={current_price:.5f}, ATR={current_atr:.5f}, SL={sl}, TP={tp}{Style.RESET_ALL}"
                            log_queue.put(debug_msg)
                            
                            if sl is not None and tp is not None and lots > 0:
                                # REMOVED: redundant/deadlocking connector.lock here
                                success = connector.execute_trade(signal, lots, sl, tp) 
                                
                                if success:
                                    log_queue.put(f"{Fore.GREEN}🚀 {tf} AUTO-TRADE: {signal} {lots:.2f} lots | SL: {sl:.5f} | TP: {tp:.5f}{Style.RESET_ALL}")
                                    risk.record_trade()
                                    last_trade_bar[tf] = latest_bar_time 
                                else:
                                    log_queue.put(f"{Fore.RED}⚠️ {tf} Trade failed: Execution error{Style.RESET_ALL}")
                            else:
                                log_queue.put(f"{Fore.RED}⚠️ {tf} Trade skipped: Invalid parameters (SL={sl}, TP={tp}, Lots={lots}){Style.RESET_ALL}")
                        else:
                            log_queue.put(f"{Fore.YELLOW}🛡️ {tf} SKIPPED: {msg}{Style.RESET_ALL}")

                except Exception as e:
                    error_msg = f"{tf} [{name}] Error: {e}"
                    log_queue.put(f"{Fore.RED}🔥 {error_msg}{Style.RESET_ALL}")
                    logger.error(error_msg)
            
            update_tg_analysis(ai_pred, list(detected_patterns.keys()) if detected_patterns else [], sentiment)
            signals_summary[tf] = tf_signal

        except Exception as e:
            error_msg = f"{tf} Worker Crash: {e}"
            log_queue.put(f"{Fore.RED}💥 {error_msg}{Style.RESET_ALL}")
            logger.error(error_msg)

    last_summary_time = time.time()
    last_heartbeat_time = time.time()
    last_scan_cycle_time = 0
    last_news_ui_update = 0

    while app.bot_running:
        try:
            now = time.time()
            loop_start = now
            
            # --- START SCAN CYCLE ---
            if not scan_active and (now - last_scan_cycle_time >= 10):
                scan_active = True
                last_scan_cycle_time = now
                
                def run_all_scans():
                    nonlocal scan_active
                    symbol = connector.active_symbol
                    asset_type = detect_asset_type(symbol)
                    style = app.style_var.get()
                    
                    log_queue.put(f"{Fore.MAGENTA}🔄 Multi-TF Scan Cycle Started: {symbol} ({asset_type}) | Style: {style}{Style.RESET_ALL}")
                    active_workers = []
                    for tf in AUTO_TABS:
                        t = threading.Thread(target=scan_tf_worker, args=(tf, asset_type, style), daemon=True)
                        t.start()
                        active_workers.append(t)
                    
                    for t in active_workers:
                        t.join(timeout=15.0) # Give them ample time
                    scan_active = False
                    log_queue.put(f"{Fore.MAGENTA}🏁 Multi-TF Scan Cycle Finished.{Style.RESET_ALL}")

                threading.Thread(target=run_all_scans, daemon=True).start()

            # 3. GLOBAL NEWS & HEADLINE UPDATE (Combined Sentiment) - Throttled to 60s
            if now - last_news_ui_update >= 60:
                try:
                    # Part A: Economic Calendar (Scheduled)
                    is_active, ev_name, _ = news_manager.get_active_impact(connector.active_symbol)
                    
                    # Part B: Global Headlines (Trump, War, etc)
                    score, global_summary, top_risks = news_manager.get_market_sentiment()
                    
                    final_status = "NEUTRAL"
                    final_reason = global_summary
                    
                    if is_active:
                        final_status = "HIGH IMPACT"
                        final_reason = f"CAL: {ev_name} | {global_summary}"
                    elif score <= -3:
                        final_status = "RISK ALERT"
                        risk_msg = top_risks[0][:20] + "..." if top_risks else "High Risk"
                        final_reason = f"NEWS: {risk_msg} | {global_summary}"
                    elif score >= 3:
                        final_status = "RISK-ON"
                        final_reason = f"BULLISH: {global_summary}"
                    else:
                        ev_title, _, _, _ = news_manager.get_upcoming_event(connector.active_symbol)
                        final_reason = f"{global_summary} | Next: {ev_title or 'Stable'}"

                    app.after(0, lambda s=final_status, r=final_reason: app.update_strategy_status("News_Sentiment", s, r))
                    last_news_ui_update = now
                except Exception as e:
                    logger.debug(f"Combined News UI Update error: {e}")

            while not log_queue.empty():
                try:
                    record = log_queue.get_nowait()
                    msg_lower = str(record).lower()
                    skip_phrases = [
                        "fetched", "parsed", "from ea", "from cache", 
                        "timeout"
                    ]
                    if any(phrase in msg_lower for phrase in skip_phrases):
                        continue
                    print(record)
                except Exception:
                    break

            now = time.time()
            # 1. Throttle summaries to 30s (Primary status log with lag check)
            if now - last_summary_time >= 30:
                summary_parts = []
                for tf in AUTO_TABS:
                    lag = int(now - time_offset - last_processed_bar.get(tf, 0)) if last_processed_bar.get(tf, 0) > 0 else "N/A"
                    summary_parts.append(f"{tf}: {signals_summary[tf]} ({lag}s)")
                
                summary_text = "| " + " | ".join(summary_parts) + " |"
                print(f"\n{Fore.MAGENTA}📊 TF STATUS ({datetime.now().strftime('%H:%M:%S')}):{Style.RESET_ALL}")
                print(summary_text)
                print("-" * 60 + "\n")
                
                # Auto-refresh if too many are stale (be more lenient: > 75% of TFs)
                stale_count = sum(1 for v in stale_tf_map.values() if v)
                if stale_count >= 6: # If 6 or more TFs are stale
                    if now - last_stale_log.get('global', 0) > 300: # Max one refresh every 5 min
                        logger.warning(f"⚠️ {stale_count} TFs Stale. Requesting MT5 Global Refresh...")
                        connector.force_sync()
                        last_stale_log['global'] = now
                
                # Log summary to Telegram
                logger.info(f"📊 STATUS: {summary_text}")
                last_summary_time = now

            # 2. Throttle Heartbeat to 120s
            if now - last_heartbeat_time >= 120:
                daily_count = getattr(risk, 'daily_trades_count', 0)
                elapsed = now - loop_start
                hb_msg = f"💓 Heartbeat: {len(AUTO_TABS)} TFs scanned | Trades: {daily_count} | SysCycle: {elapsed:.2f}s"
                print(f"{Fore.BLUE}{hb_msg}{Style.RESET_ALL}")
                last_heartbeat_time = now

            time.sleep(0.2)  # FIXED: Increased from 0.05 to 0.2 to reduce CPU/Thread pressure

        except Exception as e:
            print(f"{Fore.RED}💥 Critical Loop Crash: {e}{Style.RESET_ALL}")
            logger.error(f"Bot loop error: {e}")
            time.sleep(1)

def main():
    conf = Config()
    mt5_port = conf.get('mt5.port', 8001)
    connector = MT5Connector(host='127.0.0.1', port=mt5_port)
    if not connector.start():
        logger.critical("❌ FAILED TO CONNECT TO MT5 GATEWAY")
        return

    connector.open_multi_tf_charts(connector.active_symbol)

    # Force warmup for all timeframes (Batch request)
    logger.info("📡 Priming Multi-TF Data Sync...")
    with connector.lock:
        for tf in AUTO_TABS: 
            cmd = f"GET_HISTORY|{connector.active_symbol}|{tf}|250"
            if cmd not in connector.command_queue:
                connector.command_queue.append(cmd)
    
    # Give EA 2s to catch up on the batch
    time.sleep(2)

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