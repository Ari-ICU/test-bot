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
    def __init__(self, model_dir="models"):
        self.model_dir = model_dir
        self.model = None
        self.current_asset_type = None
        self.current_style = None  # scalp vs swing
        self.feature_cols = [
            'rsi', 'adx', 'macd_hist', 'stoch_k', 'stoch_d', 
            'price_vs_ema200', 'bb_width', 'is_squeezing',
            'supertrend_active' # Trend direction feature
        ]
        
        # Create models directory if not exists
        os.makedirs(self.model_dir, exist_ok=True)

    def _get_model_path(self, asset_type, style="scalp"):
        """Helper to get path based on asset type and style"""
        if not asset_type:
            return os.path.join(self.model_dir, f"trading_model_{style}.joblib")
        return os.path.join(self.model_dir, f"trading_model_{asset_type}_{style}.joblib")

    def load_model(self, asset_type="forex", style="scalp"):
        """Load the pre-trained model for a specific asset type and style"""
        # Avoid reloading if already loaded
        if self.model is not None and self.current_asset_type == asset_type and self.current_style == style:
            return

        model_path = self._get_model_path(asset_type, style)
        if os.path.exists(model_path):
            try:
                self.model = joblib.load(model_path)
                self.current_asset_type = asset_type
                self.current_style = style
                logger.info(f"✅ AI Model loaded: {asset_type} | {style} from {model_path}")
            except Exception as e:
                logger.error(f"❌ Failed to load model for {asset_type}/{style}: {e}")
                self.model = None
        else:
            # Fallback to generic if specific not found
            logger.warning(f"⚠️ No AI Model found for {asset_type}/{style}. Predictions will be NEUTRAL.")
            self.model = None

    def prepare_features(self, df):
        """
        Convert indicator data into a format the AI can read.
        """
        try:
            # 1. Price vs EMA Ratio
            df['price_vs_ema200'] = (df['close'] - df['ema_200']) / df['ema_200'] * 100
            
            # 2. Bollinger Width (Volatility)
            df['bb_width'] = (df['upper_bb'] - df['lower_bb']) / df['ema_200'] * 100
            
            # 3. SuperTrend Direction (Binary Feature)
            # If supertrend column exists, convert to 1/0
            if 'supertrend' in df.columns:
                df['supertrend_active'] = df['supertrend'].astype(int)
            else:
                df['supertrend_active'] = 0
            
            # Select only the features the model was trained on
            features = df[self.feature_cols].tail(1)
            features = features.fillna(0)
            
            return features
        except Exception as e:
            logger.error(f"Error preparing AI features: {e}")
            return None

    def predict(self, df, asset_type="forex", style="scalp"):
        """
        Returns: 'BUY', 'SELL', or 'NEUTRAL'
        """
        # Ensure correct model is loaded
        self.load_model(asset_type, style)
        
        if self.model is None:
            return "NEUTRAL", 0.0

        features = self.prepare_features(df)
        if features is None or features.empty:
            return "NEUTRAL", 0.0

        try:
            preds = self.model.predict(features)
            prediction = preds[0] if hasattr(preds, "__iter__") else preds
            
            probs = self.model.predict_proba(features)
            probs_flat = np.array(probs).flatten()
            
            classes = list(self.model.classes_)
            if prediction in classes:
                idx = classes.index(prediction)
                confidence = float(probs_flat[idx]) if idx < len(probs_flat) else 0.0
            else:
                confidence = 0.0

            mapping = {1: "BUY", -1: "SELL", 0: "NEUTRAL"}
            action = mapping.get(prediction, "NEUTRAL")
            
            # Higher confidence threshold for Swing
            min_conf = 0.65 if style == "swing" else 0.60
            if confidence < min_conf:
                return "NEUTRAL", confidence
                
            return action, confidence
        except Exception as e:
            logger.error(f"AI Prediction error: {e}")
            return "NEUTRAL", 0.0

    def train_model(self, historical_df, asset_type="forex", style="scalp"):
        """
        Trains and saves a model for a specific asset type and trading style.
        """
        logger.info(f"🧠 Training AI Model ({style}) for {asset_type}...")
        
        data = historical_df.copy()
        
        # 1. Feature Prep
        data['price_vs_ema200'] = (data['close'] - data['ema_200']) / data['ema_200'] * 100
        data['bb_width'] = (data['upper_bb'] - data['lower_bb']) / data['ema_200'] * 100
        if 'supertrend' in data.columns:
            data['supertrend_active'] = data['supertrend'].astype(int)
        else:
            data['supertrend_active'] = 0
            
        # 2. Advanced Labeling (Target)
        # Horizon: Scalp = 10 candles, Swing = 40 candles
        horizon = 10 if style == "scalp" else 40
        
        # Use future max/min within horizon for Swing to catch 'peaks'
        if style == "swing":
            # For swing, we want to know if price hit a target high/low before the horizon ends
            future_max = data['high'].shift(-horizon).rolling(window=horizon).max()
            future_min = data['low'].shift(-horizon).rolling(window=horizon).min()
            
            # Calculate returns based on best move in the window
            buy_ret = (future_max - data['close']) / data['close']
            sell_ret = (data['close'] - future_min) / data['close']
        else:
            # Scalp labeling: simpler point-in-time check
            future_return = (data['close'].shift(-horizon) - data['close']) / data['close']
            buy_ret = future_return
            sell_ret = -future_return
        
        # Determine threshold based on volatility (adaptive)
        mult = 1.5 if style == "scalp" else 3.5
        vol_ref = (data['high'] - data['low']) / data['close']
        threshold = vol_ref.median() * mult
        
        # Min thresholds
        min_threshold = 0.0005 if asset_type == "forex" else 0.003
        if style == "swing": min_threshold *= 2.0 # Swing target is larger
        
        if threshold < min_threshold: threshold = min_threshold
        
        logger.info(f"📈 {asset_type} | {style} Training Threshold: {threshold*100:.3f}% | Horizon: {horizon}")
        
        data['target'] = 0
        data.loc[buy_ret > threshold, 'target'] = 1   
        data.loc[sell_ret > threshold, 'target'] = -1 
        
        # 3. Fit Random Forest
        data = data.dropna(subset=self.feature_cols + ['target'])
        if len(data) < 200:
            logger.error("❌ Not enough valid data points for training.")
            return False

        X = data[self.feature_cols]
        y = data['target']
        
        # Swing trades need more complex trees to find the "swing" setup
        n_est = 150 if style == "scalp" else 250
        depth = 12 if style == "scalp" else 15
        
        clf = RandomForestClassifier(n_estimators=n_est, max_depth=depth, random_state=42)
        clf.fit(X, y)
        
        # 4. Save
        model_path = self._get_model_path(asset_type, style)
        joblib.dump(clf, model_path)
        self.model = clf
        self.current_asset_type = asset_type
        self.current_style = style
        
        logger.info(f"🚀 AI Model for {asset_type} ({style}) saved to {model_path}")
        return True
