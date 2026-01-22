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

# main.py (Final Corrected Version)
def bot_logic(app):
    connector = app.connector
    risk = app.risk
    last_heartbeat = 0  
    news_cooldown = 0
    last_auto_state = app.auto_trade_var.get()
    last_processed_candle_time = 0  # NEW: Smart Scan Tracker
    was_waiting_for_data = False    # Track data sync status
    
    # Initialize AI Predictor
    ai_predictor = AIPredictor()

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
            
            # --- PROFIT PROTECTION (M1 SECURE) ---
            manage_all_tf_secure_profit(connector, risk, logger)

            # --- BOT HEARTBEAT ---
            if heartbeat_limiter.allow("bot_heartbeat"):
                status = "AUTO-ACTIVE" if curr_auto_state else "PAUSED (Manual Only)"
                logger.info(f"💓 Bot Heartbeat | Status: {status} | Symbol: {connector.active_symbol} | TF: {connector.active_tf}")

            if not app.auto_trade_var.get():
                time.sleep(0.5)
                continue

            symbol = connector.active_symbol
            execution_tf = connector.active_tf
            # --- ACCOUNT HEALTH ---
            try:
                max_pos_allowed = app.max_pos_var.get()
                ui_lot_size = app.lot_var.get()
                ui_cool_off = app.cool_off_var.get()
            except Exception as e:
                logger.error(f"⚠️ UI Input Error: {e}. Using defaults.")
                max_pos_allowed = 1
                ui_lot_size = 0.01
                ui_cool_off = 10.0
            
            # Sync dynamic UI settings to RiskManager
            risk.cool_off_period = ui_cool_off

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
            is_news_blocked, news_headline, news_link = news.is_high_impact_news_near(symbol)
            if is_news_blocked:
                if filter_limiter.allow(f"news_block_{symbol}"):
                    logger.warning(f"📰 News Block Active: {news_headline} | Link: {news_link}")
                
                # --- SYNC TO UI ---
                def show_news_block():
                    for name in app.strat_ui_items:
                        app.strat_ui_items[name]["status"].configure(text="PAUSED", bootstyle="warning")
                        app.strat_ui_items[name]["reason"].configure(text=f"News: {news_headline[:15]}...")
                app.after(0, show_news_block)
                
                time.sleep(10); continue
            elif news_headline and filter_limiter.allow(f"news_info_{news_headline[:15]}"):
                logger.info(f"📰 News Update: {news_headline} | Link: {news_link}")

            # --- DATA SYNC CHECK ---
            candles = connector.get_tf_candles(execution_tf, count=500)
            if not candles or len(candles) < 200:
                if heartbeat_limiter.allow("waiting_data"):
                    logger.info(f"⏳ Waiting for adequate candle data... Currently: {len(candles) if candles else 0}/200")
                was_waiting_for_data = True
                time.sleep(5); continue
            
            if was_waiting_for_data:
                logger.info(f"✅ Data Synced Successfully! Buffer filled: {len(candles)} candles.")
                was_waiting_for_data = False

            # Fetch HTF data for CRT
            htf_tf = get_htf_from_ltf(execution_tf)
            htf_candles = connector.get_tf_candles(htf_tf, count=200)
            if not htf_candles:
                # If HTF is missing, the bridge might only be sending LTF. 
                # We can't do CRT, but we can continue with others.
                pass

            # --- SMART SCAN GATEKEEPER ---
            # Only run heavy calcs if a new candle is detected or it's been > 15s
            current_candle_time = candles[-1]['time'] if candles else 0
            is_new_candle = current_candle_time > last_processed_candle_time
            
            # Force scan if we haven't scanned in 1 second (High Responsiveness)
            force_time_refresh = (now_ts - news_cooldown) > 1.0 
            
            if not is_new_candle and not force_time_refresh:
                time.sleep(0.1); continue # Tiny sleep to prevent CPU spiking
            
            last_processed_candle_time = current_candle_time
            news_cooldown = now_ts 
            
            # --- ACCOUNT HEALTH & PRE-TRADE FILTERS ---
            if curr_positions >= max_pos_allowed:
                if filter_limiter.allow(f"max_pos_{symbol}"):
                    logger.info(f"⏸️ Max open positions ({max_pos_allowed}) reached for SYMBOL: {symbol}. Trading paused for this symbol.")
                time.sleep(10); continue

            df = pd.DataFrame(candles)
            
            # --- HIGH IMPACT NEWS FILTER & SENTIMENT OVERRIDE ---
            blocked, headline, wait_time = news.is_high_impact_news_near(symbol)
            
            # Check Sentiment explicitly for override
            news_action, news_reason = news.analyze_sentiment(symbol)
            sentiment_override = False

            if blocked:
                # If we have a STRONG news signal (Buy/Sell), we ignore the pause
                if news_action != "NEUTRAL":
                     if filter_limiter.allow("news_override"):
                        logger.warning(f"⚠️ {headline} | 🚀 SENTIMENT OVERRIDE: {news_action} based on {news_reason}")
                     sentiment_override = True
                
                # If no override, we enforce safety pause
                if not sentiment_override:
                    if filter_limiter.allow("news_block"):
                        logger.warning(f"⚠️ {headline} | Status: {wait_time} | ⛔ Trading Paused for Safety.")
                    
                    time.sleep(10)
                    continue

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
            stoch_k, stoch_d = Indicators.calculate_stoch(df)
            df['upper_bb'], df['lower_bb'] = bb_upper, bb_lower
            df['stoch_k'], df['stoch_d'] = stoch_k, stoch_d
            df['is_squeezing'] = Indicators.is_bollinger_squeeze(df)
            
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
            if scan_limiter.allow("market_diagnostics"):
                news_text = ""
                nxt_ev, nxt_min, nxt_link = news.get_next_news_info(symbol)
                if nxt_ev and nxt_min:
                    news_text = f" | 📰 Next: {nxt_ev} ({int(nxt_min)}m) [{nxt_link}]"
                logger.info(f"📊 Market Health | Symbol: {symbol} | ADX: {curr_adx:.1f} | RSI: {curr_rsi:.1f}{news_text}")

            asset_type = detect_asset_type(symbol)
            selected_style = app.style_var.get()
            
            ui_reclaim = app.crt_reclaim_var.get()
            
            # Define all available strategies
            all_strategies = [
                ("AI_Predict", lambda: ai_predictor.predict(df, asset_type=asset_type, style=selected_style)),
                ("Trend", lambda: trend.analyze_trend_setup(candles, df=df, patterns=patterns)),
                ("Scalp", lambda: scalping.analyze_scalping_setup(candles, df=df)),
                ("Breakout", lambda: breakout.analyze_breakout_setup(candles, df=df)),
                ("TBS_Retest", lambda: tbs_retest.analyze_tbs_retest_setup(candles, df=df, patterns=patterns)),
                ("ICT_SB", lambda: ict_strat.analyze_ict_setup(candles, df=df, patterns=patterns)),
                ("TBS_Turtle", lambda: tbs_strat.analyze_tbs_turtle_setup(candles, df=df, patterns=patterns)),
                ("CRT_TBS", lambda: crt_tbs.analyze_crt_tbs_setup(candles, htf_candles, symbol, execution_tf, htf_tf, reclaim_pct=ui_reclaim)),
                ("News_Sentiment", lambda: news.analyze_sentiment(symbol)),
                ("PD_Parameter", lambda: pd_strat.analyze_pd_parameter_setup(candles, df=df)),
                ("Reversal", lambda: reversal_strat.analyze_reversal_setup(candles, df=df, patterns=patterns))
            ]
            
            # Filter enabled strategies based on UI toggles
            base_strategies = []
            for name, func in all_strategies:
                # Check if strategy is enabled in UI (default to True if not found for safety)
                is_enabled = app.strat_vars.get(name, tk.BooleanVar(value=True)).get()
                if is_enabled:
                    base_strategies.append((name, func))
                else:
                    # Update status to DISABLED in UI if needed (skipping execution)
                    if hasattr(app, 'strat_ui_items') and name in app.strat_ui_items:
                        app.strat_ui_items[name]["status"].configure(text="DISABLED", bootstyle="secondary")
                        app.strat_ui_items[name]["reason"].configure(text="User Toggled Off")

            signals_this_cycle = []
            neutral_summaries = []
            
            for name, engine in base_strategies:
                try:
                    action, reason = engine()
                    strategy_results.append((name, (action, reason)))
                    
                    # --- LIVE UI FEEDBACK ---
                    app.update_strategy_status(name, action, reason) # Push to Dashboard
                    
                    # --- SYNC TO UI ---
                    color = "secondary"
                    if action != "NEUTRAL":
                        color = "success" if action == "BUY" else "danger"
                        signals_this_cycle.append(f"{name}: {action}")
                    elif isinstance(reason, str) and any(k in reason for k in ["Trend:", "Confluence", "Consolidating", "Outside", "No Pattern"]):
                        color = "warning"
                    
                    def update_ui(n=name, a=action, r=reason, c=color):
                        if n in app.strat_ui_items:
                            app.strat_ui_items[n]["status"].configure(text=a, bootstyle=f"{c}")
                            
                            # Handle different reason types (String vs Confidence Float)
                            if isinstance(r, (int, float)):
                                display_reason = f"Confidence: {r*100:.1f}%"
                            else:
                                display_reason = str(r).replace(f"{n}:", "").strip()
                            
                            if not display_reason or display_reason == "0.0%": 
                                display_reason = "Scanning..."
                            app.strat_ui_items[n]["reason"].configure(text=display_reason[:40])
                    
                    app.after(0, update_ui)

                    if action == "NEUTRAL" and reason:
                        display_reason = f"{reason*100:.1f}%" if isinstance(reason, (int, float)) else str(reason)[:30]
                        neutral_summaries.append(f"{name}: {display_reason}")

                except Exception as e:
                    logger.error(f"Strategy {name} failed: {e}")

            # Feedback log for active scanning
            if signals_this_cycle:
                logger.info(f"🎯 Signals Detected: {', '.join(signals_this_cycle)}")
            elif scan_limiter.allow("scanning_feedback"):
                summary_str = " | ".join(neutral_summaries)
                logger.info(f"🔍 Scanning {symbol} ({execution_tf}) | Status: NEUTRAL | {summary_str}")

            # --- UPDATE TELEGRAM PERSISTENT ANALYSIS ---
            active_patterns = [k.replace('_', ' ').title() for k,v in patterns.items() if v]
            pat_str = ", ".join(active_patterns[:3]) if active_patterns else "Consolidating"
            sentiment = "BULLISH" if df['close'].iloc[-1] > df['ema_200'].iloc[-1] else "BEARISH"
            
            # Use the first active signal for AI Prediction or NEUTRAL
            pred = signals_this_cycle[0].split(":")[1].strip() if signals_this_cycle else "NEUTRAL"
            
            if app.telegram_bot:
                app.telegram_bot.track_analysis(
                    prediction=pred,
                    patterns=pat_str,
                    sentiment=sentiment
                )

            # --- EXECUTION ---
            trade_executed = False
            for name, (action, reason) in strategy_results:
                if action != "NEUTRAL" and not trade_executed:
                    current_price = ask if action == "BUY" else bid
                    sl, tp = risk.calculate_sl_tp(current_price, action, current_atr, symbol, timeframe=execution_tf)
                    
                    # PRIORITY: Fetch the absolute latest lot size from the UI variable
                    final_lot = app.lot_var.get() 
                    
                    if connector.send_order(action, symbol, final_lot, sl, tp):
                        logger.info(f"🚀 {action} {symbol} Executed | Strategy: {name} | Reason: {reason} | Lot: {final_lot}")
                        risk.record_trade()
                        trade_executed = True
                        time.sleep(1); break # Short pause after trade to allow sync

            time.sleep(0.5) # Fast loop for real-time responsiveness
                
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