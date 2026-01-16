import time
import logging
from logging.handlers import RotatingFileHandler
from bot_settings import Config
from core.execution import MT5Connector
from core.risk import RiskManager
from core.session import is_market_open, get_detailed_session_status
from core.telegram_bot import TelegramBot, TelegramLogHandler 
from filters.news import NewsFilter
from ui import TradingApp
import strategy.trend_following as trend
import strategy.reversal as reversal
import strategy.breakout as breakout
import strategy.tbs_turtle as tbs_turtle
import strategy.ict_silver_bullet as ict_strat
import strategy.scalping as scalping

# --- Console Logger ---
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
    news_filter = NewsFilter(conf.get('sources', []))
    
    logger.info("Bot logic initialized with Psychology & Fundamental Engine.") 
    
    max_pos_allowed = risk.config.get('max_positions', 5)
    
    last_balance = 0.0
    last_positions = 0
    first_run = True
    last_heartbeat = 0  
    
    while app.bot_running:
        try:
            info = connector.account_info
            curr_balance = info.get('balance', 0.0)
            curr_positions = info.get('total_count', 0)
            equity = info.get('equity', 0.0)
            symbol = app.symbol_var.get() if hasattr(app, 'symbol_var') else "XAUUSD"
            
            # --- REAL-TIME HEARTBEAT ---
            if time.time() - last_heartbeat > 60:
                bid = info.get('bid', 0.0)
                logger.info(f"❤️ Heartbeat | {symbol} @ {bid} | Equity: ${equity:,.2f}")
                last_heartbeat = time.time()

            if first_run and curr_balance > 0:
                last_balance = curr_balance
                last_positions = curr_positions
                first_run = False

            # --- TRADE MONITOR ---
            if not first_run:
                if curr_positions < last_positions:
                    pnl = curr_balance - last_balance
                    if abs(pnl) > 0.01: 
                        if pnl > 0:
                            logger.info(f"✅ TP Hit: +${pnl:.2f}")
                        else:
                            logger.warning(f"❌ SL Hit: -${abs(pnl):.2f}")
                last_positions = curr_positions
                last_balance = curr_balance

            if hasattr(app, 'auto_trade_var') and not app.auto_trade_var.get():
                time.sleep(1)
                continue

            # --- HYCM SESSION ADVICE ---
            is_open, session_name, session_risk_mod = get_detailed_session_status()
            if not is_open:
                time.sleep(5)
                continue

            # --- PSYCHOLOGY & RISK GATEKEEPER ---
            if curr_balance > 0:
                current_drawdown_pct = ((curr_balance - equity) / curr_balance) * 100
                can_trade, psych_reason = risk.can_trade(current_drawdown_pct)
                if not can_trade:
                    # Log psychology blocks periodically
                    if time.time() % 300 < 2: 
                        logger.warning(f"🧠 Bot Halted: {psych_reason}")
                    time.sleep(5)
                    continue

            if curr_positions >= max_pos_allowed:
                time.sleep(1)
                continue

            candles = connector.get_latest_candles()
            if not candles or len(candles) < 20: 
                time.sleep(1)
                continue

            # --- STRATEGIES & SIGNALS ---
            decisions = []
            
            # 1. News Filter (FIXED: Unpacks 4 values including Risk Multiplier)
            news_res = news_filter.get_sentiment_signal(symbol)
            news_action, news_reason, news_cat, news_risk_mod = news_res
            decisions.append((news_action, news_reason))
            
            # 2. Technical Strategies
            decisions.append(tbs_turtle.analyze_tbs_turtle_setup(candles))
            decisions.append(ict_strat.analyze_ict_setup(candles))
            decisions.append(trend.analyze_trend_setup(candles))
            decisions.append(reversal.analyze_reversal_setup(candles, 30, 20))
            decisions.append(breakout.analyze_breakout_setup(candles))
            decisions.append(scalping.analyze_scalping_setup(candles))
            
            final_action = "NEUTRAL"
            execution_reason = ""
            
            for action, reason in decisions:
                if action != "NEUTRAL":
                    final_action = action
                    execution_reason = reason
                    break
            
            if final_action in ["BUY", "SELL"]:
                current_price = info.get('ask') if final_action == "BUY" else info.get('bid')
                latest_atr = candles[-1].get('atr', 0)
                
                # Calculate SL/TP
                sl, tp = risk.calculate_sl_tp(current_price, final_action, latest_atr)
                
                # Calculate Lot with Session and Psychology Multipliers
                base_lot = risk.calculate_lot_size(curr_balance, current_price, sl, symbol, equity)
                lot = base_lot * news_risk_mod * session_risk_mod
                
                # Manual override if set in UI
                if hasattr(app, 'lot_var') and float(app.lot_var.get()) > 0:
                    lot = float(app.lot_var.get())
                
                logger.info(f"🚀 EXECUTING: {final_action} | Session: {session_name} | News Mod: {news_risk_mod}x")
                if connector.send_order(final_action, symbol, lot, sl, tp):
                    risk.record_trade() # Record for psychology trackers
                    logger.info(f"🧠 Discipline: Daily Trades {risk.daily_trades_count}/{risk.max_daily_trades}")
                
                time.sleep(60) 

            time.sleep(1)

        except Exception as e:
            logger.error(f"Logic Error: {e}")
            time.sleep(5)

def main():
    conf = Config()
    connector = MT5Connector(
        host=conf.get('mt5', {}).get('host', '127.0.0.1'),
        port=conf.get('mt5', {}).get('port', 8001)
    )
    
    tg_conf = conf.get('telegram', {})
    telegram_bot = TelegramBot(
        token=tg_conf.get('bot_token', ''),
        authorized_chat_id=tg_conf.get('chat_id', ''),
        connector=connector
    )
    connector.set_telegram(telegram_bot)

    if not connector.start():
        return

    # Attach Handlers
    logging.getLogger().addHandler(TelegramLogHandler(telegram_bot))
    file_handler = RotatingFileHandler('bot_activity.log', maxBytes=5*1024*1024, backupCount=3)
    file_handler.setFormatter(CustomFormatter())
    logging.getLogger().addHandler(file_handler)
    
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