import time
import logging
from config import Config
from core.execution import MT5Connector
from core.risk import RiskManager
from core.session import is_market_open
from filters.news import NewsFilter
from filters.volatility import is_volatility_safe
# Import strategies
from strategy import trend_following, reversal, breakout

logging.basicConfig(level=logging.INFO)

def main():
    # 1. Setup
    conf = Config()
    connector = MT5Connector(
        host=conf.get('mt5', {}).get('host', '127.0.0.1'),
        port=conf.get('mt5', {}).get('port', 8001)
    )
    risk = RiskManager(conf.data)
    news_filter = NewsFilter(conf.get('sources', []))
    
    connector.start()
    
    # 2. Main Loop
    try:
        while True:
            # Check Filters
            if news_filter.fetch_news():
                time.sleep(60) # Pause on high impact news
                continue
                
            if not is_market_open("Auto"):
                time.sleep(60)
                continue

            # Process Data
            candles = connector.get_latest_candles()
            if not candles: 
                time.sleep(1)
                continue

            # Run Strategies (Weighted Mix)
            decisions = []
            decisions.append(trend_following.analyze_trend_setup(candles))
            decisions.append(reversal.analyze_reversal_setup(candles, 0, 0)) # pass bid/ask in real flow
            decisions.append(breakout.analyze_breakout_setup(candles))
            
            # Aggregate Logic (Simplified)
            final_action = "NEUTRAL"
            for action, reasons in decisions:
                if action != "NEUTRAL":
                    final_action = action
                    logging.info(f"Signal: {action} | Reasons: {reasons}")
                    break
            
            # Execute
            if final_action in ["BUY", "SELL"]:
                symbol = "XAUUSDm" # Dynamic in real app
                lot = risk.get_lot_size(1000)
                atr = 1.0 # Calculate real ATR
                sl, tp = risk.calculate_sl_tp(candles[-1]['close'], final_action, atr)
                
                connector.send_order(final_action, symbol, lot, sl, tp)
                time.sleep(15) # Cooldown

            time.sleep(1)

    except KeyboardInterrupt:
        logger.info("Shutting down...")

if __name__ == "__main__":
    main()