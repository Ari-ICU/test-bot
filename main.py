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
import strategy.ict_silver_bullet as ict_strat
import strategy.scalping as scalping
import strategy.tbs_turtle as tbs_turtle

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
    news_filter = NewsFilter(conf.get('sources', []))
    
    logger.info("Bot logic running: Enhanced MTF Confluence (H1/M15/M5) active.") 
    
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
                logger.info(f"❤️ Heartbeat | {symbol} | Equity: ${equity:,.2f} | Positions: {curr_positions}")
                last_heartbeat = time.time()

            # --- MTF Data Fetching ---
            # Increased buffer to ensure enough data for indicators like EMA 200
            d1_candles = connector.get_tf_candles("D1", 50)
            h1_candles = connector.get_tf_candles("H1", 100)
            m15_candles = connector.get_tf_candles("M15", 100)
            m5_candles = connector.get_tf_candles("M5", 300) 

            # Validation Gate: Ensure we have enough data to calculate indicators
            if any(len(c) < 20 for c in [d1_candles, h1_candles, m15_candles]):
                time.sleep(1); continue
            if len(m5_candles) < 210: # EMA 200 needs 200+ bars
                logger.warning(f"Waiting for more M5 data... ({len(m5_candles)}/210)")
                time.sleep(2); continue

            # --- Trend Verification ---
            # Global Bias (D1) - Optional but logged
            d1_trend = "BUY" if d1_candles[-1]['close'] > d1_candles[-10]['close'] else "SELL"
            # Structural Confirmation (H1 & M15) - Required
            h1_trend = "BUY" if h1_candles[-1]['close'] > h1_candles[-20]['close'] else "SELL"
            m15_trend = "BUY" if m15_candles[-1]['close'] > m15_candles[-10]['close'] else "SELL"

            # --- Psychology & Session Gates ---
            is_open, session_name, session_risk_mod = get_detailed_session_status()
            if not is_open: 
                time.sleep(5); continue

            drawdown_pct = ((curr_balance - equity) / curr_balance) * 100 if curr_balance > 0 else 0
            can_trade, psych_reason = risk.can_trade(drawdown_pct) #
            
            if not can_trade:
                logger.debug(f"Risk Gate: {psych_reason}")
                time.sleep(5); continue
            
            if curr_positions >= max_pos_allowed:
                time.sleep(5); continue

            # --- Strategy Decisions ---
            decisions = []
            news_action, _, _, news_risk_mod = news_filter.get_sentiment_signal(symbol)
            
            decisions.append((news_action, "News Sentiment"))
            decisions.append(ict_strat.analyze_ict_setup(m5_candles)) #
            decisions.append(trend.analyze_trend_setup(m5_candles)) #
            decisions.append(scalping.analyze_scalping_setup(m5_candles)) #
            decisions.append(tbs_turtle.analyze_tbs_turtle_setup(m5_candles)) #

            final_action = "NEUTRAL"
            execution_reason = ""

            for action, reason in decisions:
                if action == "NEUTRAL":
                    continue
                
                # FIXED LOGIC: Match M5 signal with H1 and M15 Structural Trends
                if action == h1_trend == m15_trend:
                    final_action = action
                    execution_reason = f"{reason} | MTF Confluence (H1/M15/M5)"
                    
                    # Add bonus weight if D1 Global Bias also aligns
                    if action == d1_trend:
                        execution_reason += " + D1 Global Bias"
                    break
            
            if final_action in ["BUY", "SELL"]:
                current_price = info.get('ask') if final_action == "BUY" else info.get('bid')
                
                # Ensure ATR is calculated for SL/TP
                latest_atr = m5_candles[-1].get('atr', 0)
                
                sl, tp = risk.calculate_sl_tp(current_price, final_action, latest_atr) #
                lot = risk.calculate_lot_size(curr_balance, current_price, sl, symbol, equity) #
                
                # Apply multipliers from News and Market Sessions
                lot = lot * news_risk_mod * session_risk_mod 

                if connector.send_order(final_action, symbol, lot, sl, tp):
                    logger.info(f"🚀 {final_action} EXECUTED: {execution_reason}")
                    risk.record_trade() #
                
                time.sleep(60) # Prevent multiple entries on the same candle

            time.sleep(1)
        except Exception as e:
            logger.error(f"Logic Error: {e}"); time.sleep(5)

def main():
    conf = Config()
    connector = MT5Connector(host=conf.get('mt5', {}).get('host', '127.0.0.1'), port=8001)
    
    tg_conf = conf.get('telegram', {})
    telegram_bot = TelegramBot(token=tg_conf.get('bot_token', ''), authorized_chat_id=tg_conf.get('chat_id', ''), connector=connector)
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