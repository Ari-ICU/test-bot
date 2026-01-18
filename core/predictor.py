# core/predictor.py
import os
import joblib
import pandas as pd
import numpy as np
import logging
from sklearn.ensemble import RandomForestClassifier
from core.indicators import Indicators

logger = logging.getLogger("AIPredictor")

class AIPredictor:
    def __init__(self, model_path="models/trading_model.joblib"):
        self.model_path = model_path
        self.model = None
        self.feature_cols = [
            'rsi', 'adx', 'macd_hist', 'stoch_k', 'stoch_d', 
            'price_vs_ema200', 'bb_width', 'is_squeezing'
        ]
        
        # Create models directory if not exists
        os.makedirs(os.path.dirname(self.model_path), exist_ok=True)
        self.load_model()

    def load_model(self):
        """Load the pre-trained model from disk"""
        if os.path.exists(self.model_path):
            try:
                self.model = joblib.load(self.model_path)
                logger.info(f"✅ AI Model loaded successfully: {self.model_path}")
            except Exception as e:
                logger.error(f"❌ Failed to load model: {e}")
        else:
            logger.warning("⚠️ No AI Model found. Predictions will be NEUTRAL until trained.")

    def prepare_features(self, df):
        """
        Convert indicator data into a format the AI can read.
        We use ratios and oscillators so the model works across different assets.
        """
        try:
            # Ensure price vs EMA is a percentage (Scale Independent)
            df['price_vs_ema200'] = (df['close'] - df['ema_200']) / df['ema_200'] * 100
            
            # Bollinger Width as a volatility feature
            df['bb_width'] = (df['upper_bb'] - df['lower_bb']) / df['ema_200'] * 100
            
            # Select only the features the model was trained on
            features = df[self.feature_cols].tail(1)
            
            # Fill any NaNs
            features = features.fillna(0)
            
            return features
        except Exception as e:
            logger.error(f"Error preparing AI features: {e}")
            return None

    def predict(self, df):
        """
        Returns: 'BUY', 'SELL', or 'NEUTRAL'
        """
        if self.model is None:
            return "NEUTRAL", 0.0

        features = self.prepare_features(df)
        if features is None:
            return "NEUTRAL", 0.0

        # Get Prediction and Probability
        try:
            # 1. Get raw prediction
            preds = self.model.predict(features)
            # Extract scalar prediction (handles both array-like and scalar outputs)
            prediction = preds[0] if hasattr(preds, "__iter__") else preds
            
            # 2. Get probabilities
            probs = self.model.predict_proba(features)
            # Flatten to 1D to safely handle (1, n_classes) or (n_classes,) shapes
            probs_flat = np.array(probs).flatten()
            
            # 3. Safely find the index of the predicted class
            classes = list(self.model.classes_)
            if prediction in classes:
                idx = classes.index(prediction)
                # Safely extract confidence from the flattened array
                confidence = float(probs_flat[idx]) if idx < len(probs_flat) else 0.0
            else:
                confidence = 0.0

            # 4. Map to trade action
            mapping = {1: "BUY", -1: "SELL", 0: "NEUTRAL"}
            action = mapping.get(prediction, "NEUTRAL")
            
            # Filter by confidence (min 60% threshold)
            if confidence < 0.60:
                return "NEUTRAL", confidence
                
            return action, confidence
        except Exception as e:
            logger.error(f"AI Prediction error: {e}")
            return "NEUTRAL", 0.0

    def train_model(self, historical_df):
        """
        Basic training logic:
        Labels: 
           1  (BUY)  if price goes up 1% in the next 10 candles
           -1 (SELL) if price goes down 1% in the next 10 candles
           0  (NEUTRAL) otherwise
        """
        logger.info("🧠 Training AI Model on historical data...")
        
        # 1. Prepare Features (Calculate indicators first if needed)
        # Assuming indicators are already in historical_df
        data = historical_df.copy()
        data['price_vs_ema200'] = (data['close'] - data['ema_200']) / data['ema_200'] * 100
        data['bb_width'] = (data['upper_bb'] - data['lower_bb']) / data['ema_200'] * 100
        
        # 2. Create Target (Labeling)
        # Target: What happened 10 candles later?
        # Use a dynamic threshold based on 0.5% return for Crypto, 0.1% for Forex? 
        # Better: Use ATR or just a sensible default that works for both.
        future_return = (data['close'].shift(-10) - data['close']) / data['close']
        
        # Determine threshold based on mean absolute return to be asset-adaptive
        threshold = future_return.abs().median() * 1.5 
        if threshold < 0.001: threshold = 0.001 # Min 0.1%
        
        logger.info(f"📈 AI Training Threshold set to {threshold*100:.3f}% based on volatility.")
        
        data['target'] = 0
        data.loc[future_return > threshold, 'target'] = 1   
        data.loc[future_return < -threshold, 'target'] = -1 
        
        # 3. Clean up
        data = data.dropna(subset=self.feature_cols + ['target'])
        
        X = data[self.feature_cols]
        y = data['target']
        
        # 4. Fit Random Forest
        clf = RandomForestClassifier(n_estimators=100, max_depth=10, random_state=42)
        clf.fit(X, y)
        
        # 5. Save
        self.model = clf
        joblib.dump(clf, self.model_path)
        logger.info(f"🚀 AI Model trained and saved to {self.model_path}")
