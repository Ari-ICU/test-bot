# training/train_ai.py
import os
import sys
import pandas as pd
import logging
import time

# Add parent directory to path so we can import core modules
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from core.execution import MT5Connector
from core.indicators import Indicators
from core.predictor import AIPredictor
from core.asset_detector import detect_asset_type

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("Trainer")

def download_and_train():
    connector = MT5Connector(host='127.0.0.1', port=8001)
    if not connector.start():
        logger.error("❌ Could not connect to MT5. Make sure the MetaTrader 5 and Bridge EA are running.")
        return

    # Wait for initial connection
    logger.info("📡 Connecting to MT5 Bridge... (Make sure EA is running)")
    for i in range(30):
        if connector.account_info.get('balance', 0) > 0 or len(connector.available_symbols) > 0:
            break
        time.sleep(1)
    
    symbol = connector.active_symbol  
    asset_type = detect_asset_type(symbol)
    original_tf_mins = connector.active_tf # Save original (e.g. M5)
    
    # Map back to minutes for restoration
    tf_to_mins = {"M1": 1, "M5": 5, "M15": 15, "M30": 30, "H1": 60, "H4": 240, "D1": 1440}
    orig_mins = tf_to_mins.get(original_tf_mins, 5)

    tf_str = "H1" if asset_type == "forex" else "M15" 
    tf_mins = 60 if asset_type == "forex" else 15
    count = 10000 
    count = 5000 # Changed from 10000 to 5000 as per instruction
    
    logger.info(f"🔄 Requesting {tf_str} data from MT5 for training... (Original was {original_tf_mins})")
    connector.change_timeframe(symbol, tf_mins)
    time.sleep(2) # Give it a moment to switch
    connector.request_history(count) # Explicitly ask for 5000 (or whatever 'count' is)
    
    # Wait for candles
    candles = []
    for i in range(120):
        candles = connector.get_tf_candles(tf_str, count=count)
        if len(candles) >= 3000: # Threshold for high-quality training
            logger.info(f"✅ Received {len(candles)} candles. Starting training...")
            break
        if i % 5 == 0:
            logger.info(f"⏳ Syncing... ({len(candles)} candles received)")
            connector.force_sync()
        time.sleep(1)

    if not candles or len(candles) < 1000:
        logger.error(f"❌ Not enough data! Reverting to {original_tf_mins}...")
        connector.change_timeframe(symbol, orig_mins)
        connector.stop()
        return

    df = pd.DataFrame(candles)
    
    # Indicator calculation
    logger.info("📊 Processing Features...")
    df['ema_200'] = Indicators.calculate_ema(df['close'], 200)
    df['rsi'] = Indicators.calculate_rsi(df['close'], 14)
    df['adx'] = Indicators.calculate_adx(df)
    
    macd_res = Indicators.calculate_macd(df['close'])
    df['macd'], df['macd_signal'], df['macd_hist'] = macd_res
    
    bb_upper, bb_lower = Indicators.calculate_bollinger_bands(df['close'])
    df['upper_bb'], df['lower_bb'] = bb_upper, bb_lower
    
    stoch_k, stoch_d = Indicators.calculate_stoch(df)
    df['stoch_k'], df['stoch_d'] = stoch_k, stoch_d
    
    st_res = Indicators.calculate_supertrend(df)
    df['supertrend'] = st_res[0]

    kc_upper, kc_lower = Indicators.calculate_keltner_channels(df, 20, 1.5)
    df['is_squeezing'] = ((df['upper_bb'] < kc_upper) & (df['lower_bb'] > kc_lower)).astype(int)

    predictor = AIPredictor(model_dir="../models")
    
    for style in ["scalp", "swing"]:
        success = predictor.train_model(df, asset_type=asset_type, style=style)
        if success:
            logger.info(f"✅ {style.upper()} training complete.")
        
    # RESTORE Timeframe
    logger.info(f"🔄 Restoration: Switching chart back to {original_tf_mins}...")
    connector.change_timeframe(symbol, orig_mins)
    time.sleep(1)
    connector.stop()
    logger.info("🏁 Trainer Finished.")

if __name__ == "__main__":
    download_and_train()
