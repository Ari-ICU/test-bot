import os
import sys
import pandas as pd
import time
import logging
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from core.execution import MT5Connector
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("DataFetcher")
def fetch_and_save():
    connector = MT5Connector(host='127.0.0.1', port=8001)
    if not connector.start():
        logger.error("❌ Could not connect to MT5. Make sure the MetaTrader 5 and Bridge EA are running.")
        return
    logger.info("📡 Connecting to MT5 Bridge...")
    for i in range(15):
        if connector.account_info.get('balance', 0) > 0 or len(connector.available_symbols) > 0:
            break
        time.sleep(1)
    symbol = connector.active_symbol  
    tf = "M5"
    count = 2000
    logger.info(f"🔄 Requesting {count} candles of {tf} data for {symbol}...")
    candles = []
    for i in range(60):
        candles = connector.request_history(tf, count=count)
        if len(candles) >= count * 0.9:
            logger.info(f"✅ Received {len(candles)} candles.")
            break
        if i % 10 == 0:
            logger.info(f"⏳ Syncing... ({len(candles)} candles received)")
            connector.force_sync()
        time.sleep(1)
    if not candles or len(candles) < 100:
        logger.error(f"❌ Not enough data! Check if symbol {symbol} is active in MT5.")
        connector.stop()
        return
    df = pd.DataFrame(candles)
    csv_path = os.path.join(os.path.dirname(__file__), "real_data.csv")
    df.to_csv(csv_path, index=False)
    logger.info(f"💾 Real data saved successfully to {csv_path}")
    connector.stop()
if __name__ == "__main__":
    fetch_and_save()
