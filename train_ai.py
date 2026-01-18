# train_ai.py
import pandas as pd
import logging
from core.execution import MT5Connector
from core.indicators import Indicators
from core.predictor import AIPredictor
import time

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
    from core.asset_detector import detect_asset_type
    asset_type = detect_asset_type(symbol)
    
    tf_str = "M5"
    tf_mins = 5
    count = 5000 
    
    # NEW: Actively tell the EA to switch to the training timeframe
    logger.info(f"🔄 Requesting {tf_str} data from MT5...")
    connector.change_timeframe(symbol, tf_mins)
    
    logger.info(f"📥 Target: {symbol} (Type: {asset_type}, TF: {tf_str}). Waiting for {count} candles...")
    
    # Wait for candles
    candles = []
    for i in range(60): # Wait up to 60 seconds
        candles = connector.get_tf_candles(tf_str, count=count)
        if len(candles) >= 1000:
            logger.info(f"✅ Received {len(candles)} candles. Starting training...")
            break
        
        if i % 5 == 0:
            logger.info(f"⏳ Still waiting... ({len(candles)} candles received so far)")
            # Re-request sync if no data
            connector.force_sync()
            
        time.sleep(1)

    if not candles or len(candles) < 1000:
        logger.error(f"❌ Not enough data! Only got {len(candles)} candles. Increase MT5 Chart History or check connection.")
        connector.stop()
        return

    df = pd.DataFrame(candles)
    
    # Pre-calculate all indicators needed for features
    logger.info("📊 Calculating indicators...")
    df['ema_200'] = Indicators.calculate_ema(df['close'], 200)
    df['rsi'] = Indicators.calculate_rsi(df['close'], 14)
    df['adx'] = Indicators.calculate_adx(df)
    
    macd_res = Indicators.calculate_macd(df['close'])
    df['macd'], df['macd_signal'], df['macd_hist'] = macd_res
    
    bb_upper, bb_lower = Indicators.calculate_bollinger_bands(df['close'])
    df['upper_bb'], df['lower_bb'] = bb_upper, bb_lower
    
    stoch_k, stoch_d = Indicators.calculate_stoch(df)
    df['stoch_k'], df['stoch_d'] = stoch_k, stoch_d
    
    # Indicators.is_bollinger_squeeze returns a scalar, we need a series for training
    # Let's re-calculate it as a series for training
    kc_upper, kc_lower = Indicators.calculate_keltner_channels(df, 20, 1.5)
    df['is_squeezing'] = ((df['upper_bb'] < kc_upper) & (df['lower_bb'] > kc_lower)).astype(int)

    # Initialize predictor and train
    predictor = AIPredictor()
    predictor.train_model(df)
    
    logger.info("✅ Training complete! Re-launch your bot to use the new AI model.")
    connector.stop()

if __name__ == "__main__":
    download_and_train()
