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
    
    symbol = connector.active_symbol  # Use current symbol from MT5
    asset_type = detect_asset_type(symbol)
    
    tf_str = "H1" if asset_type == "forex" else "M15" # Higher TFs for Swing
    tf_mins = 60 if asset_type == "forex" else 15
    count = 10000 # Increase data for better swing patterns
    
    # NEW: Actively tell the EA to switch to the training timeframe
    logger.info(f"🔄 Requesting {tf_str} data from MT5 for SWING training...")
    connector.change_timeframe(symbol, tf_mins)
    
    logger.info(f"📥 Target: {symbol} (Type: {asset_type}, TF: {tf_str}). Waiting for {count} candles...")
    
    # Wait for candles
    candles = []
    for i in range(120): # Wait up to 120 seconds for larger dataset
        candles = connector.get_tf_candles(tf_str, count=count)
        if len(candles) >= 2000:
            logger.info(f"✅ Received {len(candles)} candles. Starting training...")
            break
        
        if i % 5 == 0:
            logger.info(f"⏳ Still waiting... ({len(candles)} candles received so far)")
            connector.force_sync()
            
        time.sleep(1)

    if not candles or len(candles) < 1000:
        logger.error(f"❌ Not enough data! Got {len(candles)} candles.")
        connector.stop()
        return

    df = pd.DataFrame(candles)
    
    # Pre-calculate all indicators
    logger.info("📊 Calculating indicators (including SuperTrend for Swing)...")
    df['ema_200'] = Indicators.calculate_ema(df['close'], 200)
    df['rsi'] = Indicators.calculate_rsi(df['close'], 14)
    df['adx'] = Indicators.calculate_adx(df)
    
    macd_res = Indicators.calculate_macd(df['close'])
    df['macd'], df['macd_signal'], df['macd_hist'] = macd_res
    
    bb_upper, bb_lower = Indicators.calculate_bollinger_bands(df['close'])
    df['upper_bb'], df['lower_bb'] = bb_upper, bb_lower
    
    stoch_k, stoch_d = Indicators.calculate_stoch(df)
    df['stoch_k'], df['stoch_d'] = stoch_k, stoch_d
    
    # SuperTrend for trend-aware swing training
    st_res = Indicators.calculate_supertrend(df)
    df['supertrend'] = st_res[0]

    # Bollinger Squeeze
    kc_upper, kc_lower = Indicators.calculate_keltner_channels(df, 20, 1.5)
    df['is_squeezing'] = ((df['upper_bb'] < kc_upper) & (df['lower_bb'] > kc_lower)).astype(int)

    # Initialize predictor
    predictor = AIPredictor(model_dir="../models")
    
    # Train both modes
    for style in ["scalp", "swing"]:
        success = predictor.train_model(df, asset_type=asset_type, style=style)
        if success:
            logger.info(f"✅ {style.upper()} training for {asset_type} complete.")
        else:
            logger.error(f"❌ {style.upper()} training for {asset_type} failed.")
        
    connector.stop()

if __name__ == "__main__":
    download_and_train()
