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
    """
    Core bot loop refactored for Strategy-Only execution.
    Removed all D1, H1, and M15 trend alignment requirements.
    """
    conf = Config()
    connector = app.connector
    risk = app.risk
    news_filter = NewsFilter(conf.get('sources', []))
    
    logger.info("Bot logic running: Strategy-Only Mode (M5) active.") 
    
    max_pos_allowed = risk.config.get('max_positions', 5)
    last_heartbeat = 0  
    
    while app.bot_running:
        try:
            info = connector.account_info
            curr_balance = info.get('balance', 0.0)
            curr_positions = info.get('total_count', 0)
            equity = info.get('equity', 0.0)
            symbol = app.symbol_var.get() if hasattr(app, 'symbol_var') else "XAUUSD"
            
            # --- Heartbeat Monitor ---
            if time.time() - last_heartbeat > 60:
                logger.info(f"❤️ Heartbeat | {symbol} | Equity: ${equity:,.2f}")
                last_heartbeat = time.time()

            # --- SINGLE TIMEFRAME FETCHING ---
            # Now only fetches the M5 execution timeframe candles
            m5_candles = connector.get_tf_candles("M5", 300)

            # Validation: Ensure sufficient data for indicator calculations
            if len(m5_candles) < 210:
                logger.warning(f"Insufficient M5 data: {len(m5_candles)}/210")
                time.sleep(2); continue

            # --- RISK & SESSION GATES ---
            is_open, _, session_risk_mod = get_detailed_session_status()
            if not is_open: 
                time.sleep(5); continue

            drawdown_pct = ((curr_balance - equity) / curr_balance) * 100 if curr_balance > 0 else 0
            can_trade, _ = risk.can_trade(drawdown_pct)
            if not can_trade or curr_positions >= max_pos_allowed:
                time.sleep(5); continue

            # --- STRATEGY EXECUTION ---
            # Evaluate strategies directly based on M5 data
            decisions = [
                ict_strat.analyze_ict_setup(m5_candles),
                trend.analyze_trend_setup(m5_candles),
                scalping.analyze_scalping_setup(m5_candles)
            ]

            final_action = "NEUTRAL"
            execution_reason = ""

            for action, reason in decisions:
                # Execution triggers immediately on strategy signal
                if action != "NEUTRAL":
                    final_action = action
                    execution_reason = reason
                    break
            
            if final_action in ["BUY", "SELL"]:
                current_price = info.get('ask') if final_action == "BUY" else info.get('bid')
                latest_atr = m5_candles[-1].get('atr', 0)
                
                sl, tp = risk.calculate_sl_tp(current_price, final_action, latest_atr)
                lot = risk.calculate_lot_size(curr_balance, current_price, sl, symbol, equity)
                lot = lot * session_risk_mod # Volatility adjustment from session status

                if connector.send_order(final_action, symbol, lot, sl, tp):
                    logger.info(f"🚀 {final_action} EXECUTED: {execution_reason}")
                    risk.record_trade()
                
                # Cool-down to prevent immediate double-triggering
                time.sleep(60) 

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

    if not connector.start(): 
        return

    risk = RiskManager(conf.data)
    app = TradingApp(bot_logic, connector, risk, telegram_bot)
    
    try:
        app.mainloop()
    except KeyboardInterrupt: 
        pass
    finally: 
        connector.stop()

if __name__ == "__main__":
    main()