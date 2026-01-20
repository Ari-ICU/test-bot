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
        # Smart Money Concept Features
        self.feature_cols = [
            # Traditional indicators (baseline)
            'rsi', 'adx', 'macd_hist', 'stoch_k', 'stoch_d', 
            'price_vs_ema200', 'bb_width', 'is_squeezing',
            'supertrend_active',
            
            # 1. Market Structure
            'market_structure',  # HH/HL (1), LH/LL (-1), Range (0)
            'bos_signal',        # Break of Structure detected
            'choch_signal',      # Change of Character detected
            
            # 2. Liquidity
            'buyside_liquidity',  # Distance to buy-side liquidity
            'sellside_liquidity', # Distance to sell-side liquidity
            'liquidity_sweep',    # Recent liquidity grab detected
            
            # 3. Order Blocks
            'bullish_ob_strength',  # Strength of nearest bullish OB
            'bearish_ob_strength',  # Strength of nearest bearish OB
            'ob_confluence',        # OB + FVG confluence score
            
            # 4. Supply & Demand Zones
            'fresh_demand_zone',    # Fresh demand zone present
            'fresh_supply_zone',    # Fresh supply zone present
            'zone_strength',        # Zone quality score
            
            # 5. Fair Value Gaps (FVG)
            'bullish_fvg',         # Bullish imbalance present
            'bearish_fvg',         # Bearish imbalance present
            'fvg_size',            # Size of nearest FVG
            
            # 6. Premium & Discount Zones
            'price_in_discount',   # Price in discount zone (0-50%)
            'price_in_premium',    # Price in premium zone (50-100%)
            'equilibrium_dist',    # Distance from 50% equilibrium
            
            # 7. Multi-Timeframe Analysis
            'htf_trend',           # Higher timeframe trend direction
            'ltf_trend',           # Lower timeframe trend direction
            'tf_alignment',        # Timeframe alignment score
            
            # 8. Session Timing
            'in_kill_zone',        # Currently in optimal trading session
            'session_bias'         # Session directional bias
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

        # 1. Try Specific Model (e.g. trading_model_forex_scalp.joblib)
        specific_path = self._get_model_path(asset_type, style)
        # 2. Try Style-only Model (e.g. trading_model_scalp.joblib)
        style_path = os.path.join(self.model_dir, f"trading_model_{style}.joblib")
        # 3. Try Legacy/Generic Model (trading_model.joblib)
        generic_path = os.path.join(self.model_dir, "trading_model.joblib")

        model_path = None
        for path in [specific_path, style_path, generic_path]:
            if os.path.exists(path):
                model_path = path
                break

        if model_path:
            try:
                self.model = joblib.load(model_path)
                self.current_asset_type = asset_type
                self.current_style = style
                # Use logging.getLogger("Main") to ensure it goes to the primary log file
                logging.getLogger("Main").info(f"✅ AI Model loaded: {asset_type} | {style} (using {os.path.basename(model_path)})")
            except Exception as e:
                logging.getLogger("Main").error(f"❌ Failed to load model from {model_path}: {e}")
                self.model = None
        else:
            # Fallback to generic if specific not found
            logging.getLogger("Main").warning(f"⚠️ No AI Model found for {asset_type}/{style}. Checked: {[specific_path, style_path, generic_path]}")
            self.model = None

    def _detect_market_structure(self, df, lookback=20):
        """Detect market structure: HH/HL (uptrend), LH/LL (downtrend), or range"""
        highs = df['high'].tail(lookback)
        lows = df['low'].tail(lookback)
        
        # Find swing highs and lows
        recent_high = highs.max()
        recent_low = lows.min()
        prev_high = highs.iloc[:-5].max() if len(highs) > 5 else recent_high
        prev_low = lows.iloc[:-5].min() if len(lows) > 5 else recent_low
        
        # HH and HL = Uptrend (1)
        if recent_high > prev_high and recent_low > prev_low:
            return 1
        # LH and LL = Downtrend (-1)
        elif recent_high < prev_high and recent_low < prev_low:
            return -1
        # Range (0)
        return 0
    
    def _detect_bos_choch(self, df, lookback=15):
        """Detect Break of Structure (BOS) and Change of Character (CHoCH)"""
        bos = 0
        choch = 0
        
        if len(df) < lookback:
            return bos, choch
        
        recent = df.tail(lookback)
        structure = self._detect_market_structure(df, lookback)
        
        # BOS: Price breaks previous structure high/low in trend direction
        if structure == 1:  # Uptrend
            prev_high = recent['high'].iloc[:-3].max()
            if recent['close'].iloc[-1] > prev_high:
                bos = 1
        elif structure == -1:  # Downtrend
            prev_low = recent['low'].iloc[:-3].min()
            if recent['close'].iloc[-1] < prev_low:
                bos = -1
        
        # CHoCH: Price breaks structure in OPPOSITE direction (trend reversal)
        if structure == 1 and recent['close'].iloc[-1] < recent['low'].iloc[:-5].min():
            choch = -1
        elif structure == -1 and recent['close'].iloc[-1] > recent['high'].iloc[:-5].max():
            choch = 1
        
        return bos, choch
    
    def _detect_liquidity_zones(self, df, lookback=30):
        """Detect buy-side and sell-side liquidity (equal highs/lows)"""
        recent = df.tail(lookback)
        current_price = df['close'].iloc[-1]
        
        # Buy-side liquidity: equal highs above current price
        highs = recent['high']
        high_clusters = []
        for i in range(len(highs) - 3):
            if abs(highs.iloc[i] - highs.iloc[i+1]) / highs.iloc[i] < 0.001:  # Within 0.1%
                high_clusters.append(highs.iloc[i])
        
        buyside_liq = (max(high_clusters) - current_price) / current_price if high_clusters else 0
        
        # Sell-side liquidity: equal lows below current price
        lows = recent['low']
        low_clusters = []
        for i in range(len(lows) - 3):
            if abs(lows.iloc[i] - lows.iloc[i+1]) / lows.iloc[i] < 0.001:
                low_clusters.append(lows.iloc[i])
        
        sellside_liq = (current_price - min(low_clusters)) / current_price if low_clusters else 0
        
        # Liquidity sweep: recent spike through liquidity then reversal
        sweep = 0
        if len(df) > 5:
            if df['high'].iloc[-2] > df['high'].iloc[-5:-2].max() and df['close'].iloc[-1] < df['close'].iloc[-2]:
                sweep = -1  # Bearish sweep
            elif df['low'].iloc[-2] < df['low'].iloc[-5:-2].min() and df['close'].iloc[-1] > df['close'].iloc[-2]:
                sweep = 1   # Bullish sweep
        
        return buyside_liq, sellside_liq, sweep
    
    def _detect_order_blocks(self, df, lookback=20):
        """Detect bullish and bearish order blocks (institutional entry zones)"""
        bullish_ob = 0
        bearish_ob = 0
        confluence = 0
        
        if len(df) < lookback:
            return bullish_ob, bearish_ob, confluence
        
        recent = df.tail(lookback)
        current_price = df['close'].iloc[-1]
        
        # Bullish OB: Last down candle before strong up move
        for i in range(len(recent) - 3, 0, -1):
            if (recent['close'].iloc[i] < recent['open'].iloc[i] and  # Down candle
                recent['close'].iloc[i+1] > recent['open'].iloc[i+1] and  # Next is up
                recent['close'].iloc[i+1] > recent['high'].iloc[i]):  # Strong move up
                ob_distance = (current_price - recent['low'].iloc[i]) / current_price
                if -0.02 < ob_distance < 0.05:  # Within 5% above OB
                    bullish_ob = max(bullish_ob, 1 - abs(ob_distance) * 20)
                    break
        
        # Bearish OB: Last up candle before strong down move
        for i in range(len(recent) - 3, 0, -1):
            if (recent['close'].iloc[i] > recent['open'].iloc[i] and  # Up candle
                recent['close'].iloc[i+1] < recent['open'].iloc[i+1] and  # Next is down
                recent['close'].iloc[i+1] < recent['low'].iloc[i]):  # Strong move down
                ob_distance = (recent['high'].iloc[i] - current_price) / current_price
                if -0.02 < ob_distance < 0.05:  # Within 5% below OB
                    bearish_ob = max(bearish_ob, 1 - abs(ob_distance) * 20)
                    break
        
        # Confluence: OB + FVG alignment
        confluence = (bullish_ob + bearish_ob) / 2
        
        return bullish_ob, bearish_ob, confluence
    
    def _detect_supply_demand_zones(self, df, lookback=40):
        """Detect fresh vs tested supply/demand zones"""
        fresh_demand = 0
        fresh_supply = 0
        zone_strength = 0
        
        if len(df) < lookback:
            return fresh_demand, fresh_supply, zone_strength
        
        recent = df.tail(lookback)
        current_price = df['close'].iloc[-1]
        
        # Demand zone: Strong departure from low, not retested
        for i in range(len(recent) - 10, 0, -1):
            if recent['close'].iloc[i+5] > recent['close'].iloc[i] * 1.02:  # 2% rally
                zone_low = recent['low'].iloc[i-2:i+2].min()
                zone_high = recent['high'].iloc[i-2:i+2].min()
                
                # Check if zone is fresh (not retested)
                retested = any(recent['low'].iloc[i+5:] < zone_high)
                if not retested and zone_low < current_price < zone_high * 1.1:
                    fresh_demand = 1
                    zone_strength = 0.8
                    break
        
        # Supply zone: Strong departure from high, not retested
        for i in range(len(recent) - 10, 0, -1):
            if recent['close'].iloc[i+5] < recent['close'].iloc[i] * 0.98:  # 2% drop
                zone_high = recent['high'].iloc[i-2:i+2].max()
                zone_low = recent['low'].iloc[i-2:i+2].max()
                
                retested = any(recent['high'].iloc[i+5:] > zone_low)
                if not retested and zone_high * 0.9 < current_price < zone_high:
                    fresh_supply = 1
                    zone_strength = 0.8
                    break
        
        return fresh_demand, fresh_supply, zone_strength
    
    def _detect_fvg(self, df):
        """Detect Fair Value Gaps (price imbalances)"""
        bullish_fvg = 0
        bearish_fvg = 0
        fvg_size = 0
        
        if len(df) < 3:
            return bullish_fvg, bearish_fvg, fvg_size
        
        # Bullish FVG: Gap between candle[i-2].high and candle[i].low
        if df['low'].iloc[-1] > df['high'].iloc[-3]:
            gap = df['low'].iloc[-1] - df['high'].iloc[-3]
            fvg_size = gap / df['close'].iloc[-1]
            bullish_fvg = 1
        
        # Bearish FVG: Gap between candle[i-2].low and candle[i].high
        elif df['high'].iloc[-1] < df['low'].iloc[-3]:
            gap = df['low'].iloc[-3] - df['high'].iloc[-1]
            fvg_size = gap / df['close'].iloc[-1]
            bearish_fvg = 1
        
        return bullish_fvg, bearish_fvg, fvg_size
    
    def _calculate_premium_discount(self, df, lookback=50):
        """Calculate if price is in premium (50-100%) or discount (0-50%) zone"""
        recent = df.tail(lookback)
        high = recent['high'].max()
        low = recent['low'].min()
        current = df['close'].iloc[-1]
        
        # Fibonacci levels
        range_size = high - low
        if range_size == 0:
            return 0, 0, 0
        
        fib_50 = low + (range_size * 0.5)
        price_position = (current - low) / range_size  # 0 to 1
        
        discount = 1 if price_position < 0.5 else 0
        premium = 1 if price_position > 0.5 else 0
        equilibrium_dist = abs(current - fib_50) / fib_50
        
        return discount, premium, equilibrium_dist
    
    def _detect_session_timing(self, df):
        """Detect if currently in kill zone (optimal trading session)"""
        # This is a simplified version - you'd need actual timestamp data
        # Kill zones: London (2-5 AM EST), New York (8-11 AM EST), Asian (7-10 PM EST)
        in_kill_zone = 0.5  # Placeholder - implement with actual time logic
        session_bias = 0    # Placeholder - would be based on session open direction
        
        return in_kill_zone, session_bias
    
    def prepare_features(self, df):
        """
        Convert indicator data + Smart Money Concepts into AI features.
        """
        try:
            # Traditional features
            df['price_vs_ema200'] = (df['close'] - df['ema_200']) / df['ema_200'] * 100
            df['bb_width'] = (df['upper_bb'] - df['lower_bb']) / df['ema_200'] * 100
            
            if 'supertrend' in df.columns:
                df['supertrend_active'] = df['supertrend'].astype(int)
            else:
                df['supertrend_active'] = 0
            
            # Smart Money Concept Features
            # 1. Market Structure
            market_structure = self._detect_market_structure(df)
            bos, choch = self._detect_bos_choch(df)
            
            # 2. Liquidity
            buyside_liq, sellside_liq, liq_sweep = self._detect_liquidity_zones(df)
            
            # 3. Order Blocks
            bull_ob, bear_ob, ob_conf = self._detect_order_blocks(df)
            
            # 4. Supply & Demand
            fresh_demand, fresh_supply, zone_str = self._detect_supply_demand_zones(df)
            
            # 5. FVG
            bull_fvg, bear_fvg, fvg_sz = self._detect_fvg(df)
            
            # 6. Premium/Discount
            discount, premium, eq_dist = self._calculate_premium_discount(df)
            
            # 7. Multi-Timeframe (simplified - would need actual HTF data)
            htf_trend = market_structure  # Placeholder
            ltf_trend = 1 if df['close'].iloc[-1] > df['close'].iloc[-5] else -1
            tf_alignment = 1 if htf_trend == ltf_trend else 0
            
            # 8. Session Timing
            kill_zone, sess_bias = self._detect_session_timing(df)
            
            # Create feature row
            features_dict = {
                'rsi': df['rsi'].iloc[-1] if 'rsi' in df.columns else 50,
                'adx': df['adx'].iloc[-1] if 'adx' in df.columns else 20,
                'macd_hist': df['macd_hist'].iloc[-1] if 'macd_hist' in df.columns else 0,
                'stoch_k': df['stoch_k'].iloc[-1] if 'stoch_k' in df.columns else 50,
                'stoch_d': df['stoch_d'].iloc[-1] if 'stoch_d' in df.columns else 50,
                'price_vs_ema200': df['price_vs_ema200'].iloc[-1],
                'bb_width': df['bb_width'].iloc[-1],
                'is_squeezing': df['is_squeezing'].iloc[-1] if 'is_squeezing' in df.columns else 0,
                'supertrend_active': df['supertrend_active'].iloc[-1],
                
                'market_structure': market_structure,
                'bos_signal': bos,
                'choch_signal': choch,
                
                'buyside_liquidity': buyside_liq,
                'sellside_liquidity': sellside_liq,
                'liquidity_sweep': liq_sweep,
                
                'bullish_ob_strength': bull_ob,
                'bearish_ob_strength': bear_ob,
                'ob_confluence': ob_conf,
                
                'fresh_demand_zone': fresh_demand,
                'fresh_supply_zone': fresh_supply,
                'zone_strength': zone_str,
                
                'bullish_fvg': bull_fvg,
                'bearish_fvg': bear_fvg,
                'fvg_size': fvg_sz,
                
                'price_in_discount': discount,
                'price_in_premium': premium,
                'equilibrium_dist': eq_dist,
                
                'htf_trend': htf_trend,
                'ltf_trend': ltf_trend,
                'tf_alignment': tf_alignment,
                
                'in_kill_zone': kill_zone,
                'session_bias': sess_bias
            }
            
            features = pd.DataFrame([features_dict])
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
            # DYNAMIC FEATURE MATCHING: 
            # If the model has 'feature_names_in_', use only those.
            # This handles models trained on different versions of the code.
            if hasattr(self.model, "feature_names_in_"):
                expected_features = list(self.model.feature_names_in_)
                # Ensure all expected features exist in our prepared dataframe
                for col in expected_features:
                    if col not in features.columns:
                        features[col] = 0.0
                features = features[expected_features]
            
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
            # If a feature error still occurs, attempt a final fallback by stripping 'supertrend_active'
            if "feature names" in str(e).lower() and "supertrend_active" in features.columns:
                try:
                    legacy_features = features.drop(columns=['supertrend_active'])
                    preds = self.model.predict(legacy_features)
                    # ... (rest of logic for fallback if we really wanted to be robust, 
                    # but feature_names_in_ check above is the standard way)
                except: pass
            
            logging.getLogger("Main").error(f"AI Prediction error: {e}")
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
        
        # Determine threshold based on median volatility (ATR-like)
        mult = 2.0 if style == "scalp" else 4.0
        vol_ref = (data['high'] - data['low']) / data['close']
        profit_hurdle = vol_ref.median() * mult
        
        # Min hurdle (avoid noise)
        min_hurdle = 0.0008 if asset_type == "forex" else 0.005 # 8 pips or 0.5%
        if style == "swing": min_hurdle *= 2.5
        
        profit_hurdle = max(profit_hurdle, min_hurdle)
        stop_hurdle = profit_hurdle * 0.5  # 2:1 RR simulated stop
        
        logger.info(f"📈 {asset_type} | {style} Profit Hurdle: {profit_hurdle*100:.3f}% | Stop Hurdle: {stop_hurdle*100:.3f}% | Horizon: {horizon}")
        
        data['target'] = 0
        
        # PROFIT-FIRST LABELING: 
        # Check if price hits PROFIT before STOP in the horizon window.
        for i in range(len(data) - horizon):
            window = data.iloc[i+1 : i+1+horizon]
            entry_price = data.iloc[i]['close']
            
            # Simulated BULLISH outcome
            max_high = window['high'].max()
            min_low = window['low'].min()
            
            # Check if Profit Hurdle hit before Stop Hurdle
            if (max_high - entry_price) / entry_price >= profit_hurdle:
                # Basic check for stop loss hit (rough approximation)
                if (entry_price - min_low) / entry_price < stop_hurdle:
                    data.at[data.index[i], 'target'] = 1
            
            # Simulated BEARISH outcome
            if (entry_price - min_low) / entry_price >= profit_hurdle:
                if (max_high - entry_price) / entry_price < stop_hurdle:
                    data.at[data.index[i], 'target'] = -1
        
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
