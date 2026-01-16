import time
import logging
from bot_settings import Config
from core.execution import MT5Connector
from core.risk import RiskManager
from core.session import get_detailed_session_status
from core.telegram_bot import TelegramBot
from filters.news import NewsFilter
from ui import TradingApp
import strategy.trend_following as trend
import strategy.ict_silver_bullet as ict_strat
import strategy.scalping as scalping

# --- Logger Setup ---
class CustomFormatter(logging.Formatter):
    format_str = "%(asctime)s | %(levelname)-8s | %(message)s"
    def format(self, record):
        formatter = logging.Formatter(self.format_str, datefmt="%H:%M:%S")
        return formatter.format(record)

handler = logging.StreamHandler()
handler.setFormatter(CustomFormatter())
logging.basicConfig(level=logging.INFO, handlers=[handler], force=True)
logger = logging.getLogger("Main")

def bot_logic(app):
    conf = Config()
    connector = app.connector
    risk = app.risk
    
    logger.info("Bot logic running: Dynamic UI Mode active.") 
    last_heartbeat = 0  
    
    while app.bot_running:
        try:
            # --- DYNAMIC UI SETTINGS ---
            # Pull live values from UI instead of config files
            symbol = app.symbol_var.get() 
            execution_tf = app.tf_var.get()
            max_pos_allowed = app.max_pos_var.get()
            user_lot = app.lot_var.get()

            info = connector.account_info
            curr_balance = info.get('balance', 0.0)
            curr_positions = info.get('total_count', 0)
            equity = info.get('equity', 0.0)
            
            if time.time() - last_heartbeat > 60:
                logger.info(f"❤️ Heartbeat | {symbol} | Equity: ${equity:,.2f}")
                last_heartbeat = time.time()

            # --- DATA FETCHING ---
            # Uses the timeframe selected in the UI dropdown
            m5_candles = connector.get_tf_candles(execution_tf, 300)

            # Fix: Lowered requirement to 200 to match EA default output
            if len(m5_candles) < 200:
                logger.warning(f"Insufficient {execution_tf} data for {symbol}: {len(m5_candles)}/200")
                time.sleep(2); continue

            # --- RISK GATES ---
            is_open, _, session_risk_mod = get_detailed_session_status()
            if not is_open: 
                time.sleep(5); continue

            drawdown_pct = ((curr_balance - equity) / curr_balance) * 100 if curr_balance > 0 else 0
            can_trade, _ = risk.can_trade(drawdown_pct)
            
            # Uses live Max Positions from UI
            if not can_trade or curr_positions >= max_pos_allowed:
                time.sleep(5); continue

            # --- STRATEGY EVALUATION ---
            decisions = [
                ict_strat.analyze_ict_setup(m5_candles),
                trend.analyze_trend_setup(m5_candles),
                scalping.analyze_scalping_setup(m5_candles)
            ]

            for action, reason in decisions:
                if action != "NEUTRAL":
                    current_price = info.get('ask') if action == "BUY" else info.get('bid')
                    latest_atr = m5_candles[-1].get('atr', 0)
                    
                    # Calculate SL/TP but use UI Lot Size
                    sl, tp = risk.calculate_sl_tp(current_price, action, latest_atr)
                    
                    if connector.send_order(action, symbol, user_lot, sl, tp):
                        logger.info(f"🚀 {action} EXECUTED: {reason} | Lot: {user_lot}")
                        risk.record_trade()
                    time.sleep(60); break 

            time.sleep(1)
        except Exception as e:
            logger.error(f"Logic Error: {e}"); time.sleep(5)

def main():
    conf = Config()
    connector = MT5Connector(host=conf.get('mt5', {}).get('host', '127.0.0.1'), port=8001)
    
    tg_conf = conf.get('telegram', {})
    telegram_bot = TelegramBot(
        token=tg_conf.get('bot_token', ''), 
        authorized_chat_id=tg_conf.get('chat_id', ''), 
        connector=connector
    )
    connector.set_telegram(telegram_bot)

    if not connector.start(): return

    risk = RiskManager(conf.data)
    app = TradingApp(bot_logic, connector, risk, telegram_bot)
    
    try:
        app.mainloop()
    except KeyboardInterrupt: pass
    finally: connector.stop()

if __name__ == "__main__":
    main()