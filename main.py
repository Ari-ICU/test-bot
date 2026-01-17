# main.py (Fully Fixed - No changes needed from previous, but included for completeness)
import time
import logging
import pandas as pd
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

# --- Fixed Logger Setup (Prevents Duplicates) ---
def setup_logger():
    logger = logging.getLogger("Main")
    if logger.hasHandlers():
        logger.handlers.clear() # Clear existing handlers to prevent duplicates
    
    logger.setLevel(logging.INFO)
    logger.propagate = False # Stop messages from climbing to the root logger

    class CustomFormatter(logging.Formatter):
        format_str = "%(asctime)s | %(levelname)-8s | %(message)s"
        def format(self, record):
            formatter = logging.Formatter(self.format_str, datefmt="%H:%M:%S")
            return formatter.format(record)

    handler = logging.StreamHandler()
    handler.setFormatter(CustomFormatter())
    logger.addHandler(handler)
    return logger

logger = setup_logger()

def bot_logic(app):
    connector = app.connector
    risk = app.risk
    last_heartbeat = 0  
    news_cooldown = 0  # NEW: Track news cooldown manually

    # NEW: Initialize last_symbol and last_tf before loop
    last_symbol = None
    last_tf = None

    logger.info("Bot logic running: Real-Time Signal Logging Active (Forex/Crypto Support).") 
    
    while app.bot_running:
        try:
            # 1. Pull dynamic settings from the UI
            symbol = connector.active_symbol  # FIXED: Use connector's confirmed/optimistic value
            execution_tf = connector.active_tf  # FIXED: Use connector's confirmed/optimistic value
            max_pos_allowed = app.max_pos_var.get()
            user_lot = app.lot_var.get()

            info = connector.account_info
            curr_balance = info.get('balance', 0.0)
            curr_positions = info.get('total_count', 0)
            equity = info.get('equity', 0.0)
            bid, ask = info.get('bid', 0.0), info.get('ask', 0.0)
            
            # NEW: Asset Type Detection & Logging
            asset_type = detect_asset_type(symbol)
            logger.info(f"--- Cycle Start | {symbol} ({asset_type}) | Pos: {curr_positions} | Equity: ${equity:,.2f} ---")

            # NEW: Detect change and log/shorten sleep
            if last_symbol != symbol:
                logger.info(f"🎯 Bot Detected Symbol Change: {last_symbol} → {symbol}")
                last_symbol = symbol
                time.sleep(1)  # Short sleep on change
                continue
            elif last_tf != execution_tf:
                logger.info(f"🎯 Bot Detected TF Change: {last_tf} → {execution_tf}")
                last_tf = execution_tf
                time.sleep(1)  # Short sleep on change
                continue
            else:
                time.sleep(2)  # Normal sleep at end

            # 2. Heartbeat Monitor
            if time.time() - last_heartbeat > 60:
                logger.info(f"❤️ Heartbeat | {symbol} ({asset_type}) @ {ask:.5f} | Equity: ${equity:,.2f} | Pos: {curr_positions}")
                last_heartbeat = time.time()

            # 3. Pre-Trade Filters (Dynamic for Asset)
            if curr_positions >= max_pos_allowed:
                logger.info(f"Max positions reached: {curr_positions}/{max_pos_allowed}")
                time.sleep(10); continue

            if not volatility.is_volatility_sufficient(connector.get_tf_candles(execution_tf), symbol):
                logger.info(f"Volatility filter failed for {symbol}")
                time.sleep(5); continue

            if not spread.is_spread_fine(symbol, bid, ask):
                logger.info(f"Spread filter failed for {symbol}")
                time.sleep(5); continue

            if not get_detailed_session_status(symbol)[0]:  # is_open
                logger.info(f"Market closed for {symbol}")
                time.sleep(30); continue

            # 4. News Filter (High-Impact Block) – FIXED: Tunable cooldown
            news_blocked = news.is_high_impact_news_near(symbol)
            if news_blocked:
                logger.warning(f"High-impact news near for {symbol} – Skipping trades (cooldown: {news_cooldown}s remaining)")
                news_cooldown = max(0, news_cooldown - 5)  # Decrement per cycle (~5s)
                if news_cooldown > 0:
                    time.sleep(5); continue
                news_cooldown = 300  # Reset to 5 min on new hit
                time.sleep(5); continue
            else:
                news_cooldown = 0  # Clear if no news

            # 5. Pull Candles & Analyze Strategies (with Real-Time Reason Logging)
            candles = connector.get_tf_candles(execution_tf)
            if len(candles) < 50:
                logger.warning(f"❌ Insufficient Candles ({len(candles)}) for {symbol} on {execution_tf} – Symbol/TF Change Pending?")
                time.sleep(10); continue

            # Locally calculate current ATR for the Risk Manager
            df = pd.DataFrame(candles)
            atr_series = Indicators.calculate_atr(df)
            current_atr = atr_series.iloc[-1] if not atr_series.empty else 0

            strategies = [
                ("ICT_SB", ict_strat.analyze_ict_setup(candles) if is_silver_bullet(symbol) else ("NEUTRAL", "Outside Silver Bullet")),
                ("Trend", trend.analyze_trend_setup(candles)),
                ("Scalp", scalping.analyze_scalping_setup(candles)),
                ("Turtle", tbs_strat.analyze_tbs_turtle_setup(candles)),
                ("Breakout", breakout.analyze_breakout_setup(candles))
            ]

            trade_executed = False
            for name, (action, reason) in strategies:
                if action != "NEUTRAL" and not trade_executed:
                    current_price = ask if action == "BUY" else bid
                    # Dynamic SL/TP & Lot via RiskManager
                    sl, tp = risk.calculate_sl_tp(current_price, action, current_atr, symbol)
                    dynamic_lot = risk.calculate_lot_size(curr_balance, current_price, sl, symbol, equity)
                    
                    if connector.send_order(action, symbol, dynamic_lot, sl, tp):
                        logger.info(f"🚀 {action} EXECUTED on {symbol} ({asset_type}): {name} - {reason} | Lot: {dynamic_lot} | SL: {sl} | TP: {tp}")
                        risk.record_trade()
                        if app.telegram_bot:
                            app.telegram_bot.send_message(f"🚀 {action} {symbol}: {name} - {reason}")
                        trade_executed = True
                        time.sleep(60); break  # Cool-off after trade
                else:
                    # Log neutral reasons every cycle to confirm the bot is "thinking"
                    logger.debug(f"📡 {name} Check ({asset_type}): {reason if reason else 'No Setup'}")
                
        except Exception as e:
            logger.error(f"Logic Error for {symbol}: {e}"); time.sleep(5)

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
        logger.error("Failed to start connector – Exiting.")
        return

    risk = RiskManager(conf.data)
    app = TradingApp(bot_logic, connector, risk, telegram_bot)
    
    try:
        app.mainloop()
    except KeyboardInterrupt: 
        logger.info("Shutting down...")
    finally: 
        connector.stop()

if __name__ == "__main__":
    main()