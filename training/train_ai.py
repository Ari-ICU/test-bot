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
    
    # NEW: Use the CURRENTLY ACTIVE timeframe from MT5 for training.
    # This ensures the AI is trained for the specific TF the user is trading.
    tf_str = connector.active_tf 
    
    count = 10000 
    
    logger.info(f"🔄 Requesting {count} candles of {tf_str} data for training symbol: {symbol}...")
    # Trigger history collection
    connector.request_history(count) 
    
    # Wait for candles
    candles = []
    for i in range(120):
        candles = connector.get_tf_candles(tf_str, count=count)
        if len(candles) >= 5000: # Threshold for high-quality training
            logger.info(f"✅ Received {len(candles)} candles. Starting training...")
            break
        if i % 5 == 0:
            logger.info(f"⏳ Syncing... ({len(candles)} candles received)")
            connector.force_sync()
        time.sleep(1)

    if not candles or len(candles) < 1000:
        logger.error(f"❌ Not enough data! Check if symbol {symbol} is active and Market Watch is filled.")
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

    # Use absolute path for models directory relative to this script
    current_dir = os.path.dirname(os.path.abspath(__file__))
    models_dir = os.path.join(current_dir, "..", "models")
    
    predictor = AIPredictor(model_dir=models_dir)
    
    for style in ["scalp", "swing", "sniper", "intraday"]:
        success = predictor.train_model(df, asset_type=asset_type, style=style)
        if success:
            logger.info(f"✅ {style.upper()} training complete.")
        
    connector.stop()
    logger.info("🏁 Trainer Finished.")

if __name__ == "__main__":
    download_and_train()
