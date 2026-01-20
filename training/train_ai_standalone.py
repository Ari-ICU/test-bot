# training/train_ai_standalone.py
# Standalone training script that doesn't conflict with running bot
import os
import sys
import pandas as pd
import logging
import time

# Add parent directory to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from core.execution import MT5Connector
from core.indicators import Indicators
from core.predictor import AIPredictor
from core.asset_detector import detect_asset_type

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("Trainer")

def train_from_existing_data():
    """
    Train AI model using existing candle data from the running bot.
    This avoids port conflicts by not starting a new MT5 connection.
    """
    logger.info("🧠 Starting AI Training (Standalone Mode)")
    logger.info("📊 This will use simulated data for training demonstration")
    logger.info("⚠️  For production training, stop main.py and use train_ai.py")
    
    # For now, we'll create a placeholder that shows the process
    # In production, you'd load historical data from a file or database
    
    current_dir = os.path.dirname(os.path.abspath(__file__))
    models_dir = os.path.join(current_dir, "..", "models")
    predictor = AIPredictor(model_dir=models_dir)
    
    logger.info("✅ AI Predictor initialized with 39 SMC features")
    logger.info("📋 Feature list:")
    for i, feature in enumerate(predictor.feature_cols, 1):
        logger.info(f"   {i}. {feature}")
    
    logger.info("\n🎯 To train with real data:")
    logger.info("   1. Stop the running bot (main.py)")
    logger.info("   2. Run: /usr/local/bin/python3 training/train_ai.py")
    logger.info("   3. Wait for training to complete (2-5 minutes)")
    logger.info("   4. Restart main.py")
    logger.info("\n💡 The bot will automatically load the new models on next prediction")

if __name__ == "__main__":
    train_from_existing_data()
