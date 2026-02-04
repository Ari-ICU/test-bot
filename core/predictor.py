import os
import joblib
import pandas as pd
import numpy as np
import logging
from sklearn.ensemble import RandomForestClassifier
from core.indicators import Indicators
logger = logging.getLogger("AIPredictor")
class AIPredictor:
    def __init__(self, model_dir=None):
        if model_dir is None:
            current_dir = os.path.dirname(os.path.abspath(__file__))
            self.model_dir = os.path.join(current_dir, "..", "models")
        else:
            self.model_dir = model_dir
        self.model = None
        self.current_asset_type = None
        self.current_style = None
        self.feature_cols = [
            'rsi', 'adx', 'macd_hist', 'stoch_k', 'stoch_d', 
            'price_vs_ema200', 'bb_width', 'is_squeezing',
            'supertrend_active',
            'market_structure',
            'bos_signal',
            'bos_pullback_zone',
            'choch_signal',
            'buyside_liquidity',
            'sellside_liquidity',
            'liquidity_sweep',
            'bullish_ob_strength',
            'bearish_ob_strength',
            'ob_confluence',
            'fresh_demand_zone',
            'fresh_supply_zone',
            'zone_strength',
            'bullish_fvg',
            'bearish_fvg',
            'fvg_size',
            'price_in_discount',
            'price_in_premium',
            'equilibrium_dist',
            'htf_trend',
            'ltf_trend',
            'tf_alignment',
            'in_kill_zone',
            'session_bias'
        ]
        os.makedirs(self.model_dir, exist_ok=True)
    def _get_model_path(self, asset_type, style="scalp"):
        if not asset_type:
            return os.path.join(self.model_dir, f"trading_model_{style}.joblib")
        return os.path.join(self.model_dir, f"trading_model_{asset_type}_{style}.joblib")
    def load_model(self, asset_type="forex", style="scalp"):
        if self.model is not None and self.current_asset_type == asset_type and self.current_style == style:
            return
        specific_path = self._get_model_path(asset_type, style)
        style_path = os.path.join(self.model_dir, f"trading_model_{style}.joblib")
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
                logging.getLogger("Main").info(f"✅ AI Model loaded: {asset_type} | {style} (using {os.path.basename(model_path)})")
            except Exception as e:
                logging.getLogger("Main").error(f"❌ Failed to load model from {model_path}: {e}")
                self.model = None
        else:
            logging.getLogger("Main").warning(f"⚠️ No AI Model found for {asset_type}/{style}. Checked: {[specific_path, style_path, generic_path]}")
            self.model = None
    def _detect_market_structure(self, df, lookback=20):
        highs = df['high'].tail(lookback)
        lows = df['low'].tail(lookback)
        recent_high = highs.max()
        recent_low = lows.min()
        prev_high = highs.iloc[:-5].max() if len(highs) > 5 else recent_high
        prev_low = lows.iloc[:-5].min() if len(lows) > 5 else recent_low
        if recent_high > prev_high and recent_low > prev_low:
            return 1
        elif recent_high < prev_high and recent_low < prev_low:
            return -1
        return 0
    def _detect_bos_choch(self, df, lookback=30):
        bos = 0
        bos_strength = 0
        choch = 0
        pullback_zone = 0
        if len(df) < lookback:
            return bos, choch
        recent = df.tail(lookback)
        current_close = recent['close'].iloc[-1]
        current_open = recent['open'].iloc[-1]
        prev_close = recent['close'].iloc[-2]
        structure = self._detect_market_structure(df, lookback)
        atr = (recent['high'] - recent['low']).rolling(14).mean().iloc[-1]
        min_swing_size = atr * 0.5
        swing_highs = []
        swing_lows = []
        for i in range(2, len(recent) - 2):
            if (recent['high'].iloc[i] > recent['high'].iloc[i-1] and 
                recent['high'].iloc[i] > recent['high'].iloc[i-2] and
                recent['high'].iloc[i] > recent['high'].iloc[i+1] and
                recent['high'].iloc[i] > recent['high'].iloc[i+2]):
                swing_highs.append((i, recent['high'].iloc[i]))
            if (recent['low'].iloc[i] < recent['low'].iloc[i-1] and 
                recent['low'].iloc[i] < recent['low'].iloc[i-2] and
                recent['low'].iloc[i] < recent['low'].iloc[i+1] and
                recent['low'].iloc[i] < recent['low'].iloc[i+2]):
                swing_lows.append((i, recent['low'].iloc[i]))
        if structure == 1 and swing_highs:
            most_recent_swing_high = max(swing_highs, key=lambda x: x[0])[1]
            if current_close > most_recent_swing_high:
                body_close_beyond = current_close > most_recent_swing_high
                strong_momentum = abs(current_close - current_open) > atr * 0.3
                is_liquidity_sweep = (recent['high'].iloc[-1] > most_recent_swing_high and 
                                     current_close < most_recent_swing_high)
                if body_close_beyond and strong_momentum and not is_liquidity_sweep:
                    bos = 1
                    body_size = abs(current_close - current_open)
                    candle_range = recent['high'].iloc[-1] - recent['low'].iloc[-1]
                    bos_strength = (body_size / candle_range) if candle_range > 0 else 0
                    pullback_zone = (current_close - most_recent_swing_high) / current_close
        elif structure == -1 and swing_lows:
            most_recent_swing_low = min(swing_lows, key=lambda x: x[0])[1]
            if current_close < most_recent_swing_low:
                body_close_beyond = current_close < most_recent_swing_low
                strong_momentum = abs(current_close - current_open) > atr * 0.3
                is_liquidity_sweep = (recent['low'].iloc[-1] < most_recent_swing_low and 
                                     current_close > most_recent_swing_low)
                if body_close_beyond and strong_momentum and not is_liquidity_sweep:
                    bos = -1
                    body_size = abs(current_close - current_open)
                    candle_range = recent['high'].iloc[-1] - recent['low'].iloc[-1]
                    bos_strength = (body_size / candle_range) if candle_range > 0 else 0
                    pullback_zone = (most_recent_swing_low - current_close) / current_close
        if structure == 1 and swing_lows:
            recent_swing_low = min([s[1] for s in swing_lows[-3:]] if len(swing_lows) >= 3 else [s[1] for s in swing_lows])
            if current_close < recent_swing_low:
                if current_close < recent_swing_low and abs(current_close - current_open) > atr * 0.3:
                    choch = -1
        elif structure == -1 and swing_highs:
            recent_swing_high = max([s[1] for s in swing_highs[-3:]] if len(swing_highs) >= 3 else [s[1] for s in swing_highs])
            if current_close > recent_swing_high:
                if current_close > recent_swing_high and abs(current_close - current_open) > atr * 0.3:
                    choch = 1
        bos_weighted = bos * max(0.5, bos_strength)
        return bos_weighted, pullback_zone, choch
    def _detect_liquidity_zones(self, df, lookback=30):
        recent = df.tail(lookback)
        current_price = df['close'].iloc[-1]
        highs = recent['high']
        high_clusters = []
        for i in range(len(highs) - 3):
            if abs(highs.iloc[i] - highs.iloc[i+1]) / highs.iloc[i] < 0.001:
                high_clusters.append(highs.iloc[i])
        buyside_liq = (max(high_clusters) - current_price) / current_price if high_clusters else 0
        lows = recent['low']
        low_clusters = []
        for i in range(len(lows) - 3):
            if abs(lows.iloc[i] - lows.iloc[i+1]) / lows.iloc[i] < 0.001:
                low_clusters.append(lows.iloc[i])
        sellside_liq = (current_price - min(low_clusters)) / current_price if low_clusters else 0
        sweep = 0
        if len(df) > 5:
            if df['high'].iloc[-2] > df['high'].iloc[-5:-2].max() and df['close'].iloc[-1] < df['close'].iloc[-2]:
                sweep = -1
            elif df['low'].iloc[-2] < df['low'].iloc[-5:-2].min() and df['close'].iloc[-1] > df['close'].iloc[-2]:
                sweep = 1
        return buyside_liq, sellside_liq, sweep
    def _detect_order_blocks(self, df, lookback=20):
        bullish_ob = 0
        bearish_ob = 0
        confluence = 0
        if len(df) < lookback:
            return bullish_ob, bearish_ob, confluence
        recent = df.tail(lookback)
        current_price = df['close'].iloc[-1]
        for i in range(len(recent) - 3, 0, -1):
            if (recent['close'].iloc[i] < recent['open'].iloc[i] and
                recent['close'].iloc[i+1] > recent['open'].iloc[i+1] and
                recent['close'].iloc[i+1] > recent['high'].iloc[i]):
                ob_distance = (current_price - recent['low'].iloc[i]) / current_price
                if -0.02 < ob_distance < 0.05:
                    bullish_ob = max(bullish_ob, 1 - abs(ob_distance) * 20)
                    break
        for i in range(len(recent) - 3, 0, -1):
            if (recent['close'].iloc[i] > recent['open'].iloc[i] and
                recent['close'].iloc[i+1] < recent['open'].iloc[i+1] and
                recent['close'].iloc[i+1] < recent['low'].iloc[i]):
                ob_distance = (recent['high'].iloc[i] - current_price) / current_price
                if -0.02 < ob_distance < 0.05:
                    bearish_ob = max(bearish_ob, 1 - abs(ob_distance) * 20)
                    break
        confluence = (bullish_ob + bearish_ob) / 2
        return bullish_ob, bearish_ob, confluence
    def _detect_supply_demand_zones(self, df, lookback=40):
        fresh_demand = 0
        fresh_supply = 0
        zone_strength = 0
        if len(df) < lookback:
            return fresh_demand, fresh_supply, zone_strength
        recent = df.tail(lookback)
        current_price = df['close'].iloc[-1]
        for i in range(len(recent) - 10, 0, -1):
            if recent['close'].iloc[i+5] > recent['close'].iloc[i] * 1.02:
                zone_low = recent['low'].iloc[i-2:i+2].min()
                zone_high = recent['high'].iloc[i-2:i+2].min()
                retested = any(recent['low'].iloc[i+5:] < zone_high)
                if not retested and zone_low < current_price < zone_high * 1.1:
                    fresh_demand = 1
                    zone_strength = 0.8
                    break
        for i in range(len(recent) - 10, 0, -1):
            if recent['close'].iloc[i+5] < recent['close'].iloc[i] * 0.98:
                zone_high = recent['high'].iloc[i-2:i+2].max()
                zone_low = recent['low'].iloc[i-2:i+2].max()
                retested = any(recent['high'].iloc[i+5:] > zone_low)
                if not retested and zone_high * 0.9 < current_price < zone_high:
                    fresh_supply = 1
                    zone_strength = 0.8
                    break
        return fresh_demand, fresh_supply, zone_strength
    def _detect_fvg(self, df):
        bullish_fvg = 0
        bearish_fvg = 0
        fvg_size = 0
        if len(df) < 3:
            return bullish_fvg, bearish_fvg, fvg_size
        if df['low'].iloc[-1] > df['high'].iloc[-3]:
            gap = df['low'].iloc[-1] - df['high'].iloc[-3]
            fvg_size = gap / df['close'].iloc[-1]
            bullish_fvg = 1
        elif df['high'].iloc[-1] < df['low'].iloc[-3]:
            gap = df['low'].iloc[-3] - df['high'].iloc[-1]
            fvg_size = gap / df['close'].iloc[-1]
            bearish_fvg = 1
        return bullish_fvg, bearish_fvg, fvg_size
    def _calculate_premium_discount(self, df, lookback=50):
        recent = df.tail(lookback)
        high = recent['high'].max()
        low = recent['low'].min()
        current = df['close'].iloc[-1]
        range_size = high - low
        if range_size == 0:
            return 0, 0, 0
        fib_50 = low + (range_size * 0.5)
        price_position = (current - low) / range_size
        discount = 1 if price_position < 0.5 else 0
        premium = 1 if price_position > 0.5 else 0
        equilibrium_dist = abs(current - fib_50) / fib_50
        return discount, premium, equilibrium_dist
    def _detect_session_timing(self, df):
        in_kill_zone = 0.5
        session_bias = 0
        return in_kill_zone, session_bias
    def prepare_features(self, df):
        try:
            df = df.copy()
            df['price_vs_ema200'] = (df['close'] - df['ema_200']) / df['ema_200'] * 100
            df['bb_width'] = (df['upper_bb'] - df['lower_bb']) / df['ema_200'] * 100
            if 'supertrend' in df.columns:
                df['supertrend_active'] = df['supertrend'].astype(int)
            else:
                df['supertrend_active'] = 0
            market_structure = self._detect_market_structure(df)
            bos, bos_pullback, choch = self._detect_bos_choch(df)
            buyside_liq, sellside_liq, liq_sweep = self._detect_liquidity_zones(df)
            bull_ob, bear_ob, ob_conf = self._detect_order_blocks(df)
            fresh_demand, fresh_supply, zone_str = self._detect_supply_demand_zones(df)
            bull_fvg, bear_fvg, fvg_sz = self._detect_fvg(df)
            discount, premium, eq_dist = self._calculate_premium_discount(df)
            htf_trend = market_structure
            ltf_trend = 1 if df['close'].iloc[-1] > df['close'].iloc[-5] else -1
            tf_alignment = 1 if htf_trend == ltf_trend else 0
            kill_zone, sess_bias = self._detect_session_timing(df)
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
                'bos_pullback_zone': bos_pullback,
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
        self.load_model(asset_type, style)
        if self.model is None:
            return "NEUTRAL", 0.0
        features = self.prepare_features(df)
        if features is None or features.empty:
            return "NEUTRAL", 0.0
        try:
            if hasattr(self.model, "feature_names_in_"):
                expected_features = list(self.model.feature_names_in_)
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
            if style in ["swing", "intraday"]:
                min_conf = 0.65
            else:
                min_conf = 0.60
            if confidence < min_conf:
                return "NEUTRAL", confidence
            return action, confidence
        except Exception as e:
            if "feature names" in str(e).lower() and "supertrend_active" in features.columns:
                try:
                    legacy_features = features.drop(columns=['supertrend_active'])
                    preds = self.model.predict(legacy_features)
                except: pass
            logging.getLogger("Main").error(f"AI Prediction error: {e}")
            return "NEUTRAL", 0.0
    def train_model(self, historical_df, asset_type="forex", style="scalp"):
        logger.info(f"🧠 Training AI Model ({style}) for {asset_type}...")
        data = historical_df.copy()
        data['price_vs_ema200'] = (data['close'] - data['ema_200']) / data['ema_200'] * 100
        data['bb_width'] = (data['upper_bb'] - data['lower_bb']) / data['ema_200'] * 100
        if 'supertrend' in data.columns:
            data['supertrend_active'] = data['supertrend'].astype(int)
        else:
            data['supertrend_active'] = 0
        logger.info("📊 Calculating Smart Money Concept features for training...")
        data['market_structure'] = 0
        data['bos_signal'] = 0.0
        data['bos_pullback_zone'] = 0.0
        data['choch_signal'] = 0
        data['buyside_liquidity'] = 0.0
        data['sellside_liquidity'] = 0.0
        data['liquidity_sweep'] = 0
        data['bullish_ob_strength'] = 0.0
        data['bearish_ob_strength'] = 0.0
        data['ob_confluence'] = 0.0
        data['fresh_demand_zone'] = 0
        data['fresh_supply_zone'] = 0
        data['zone_strength'] = 0.0
        data['bullish_fvg'] = 0
        data['bearish_fvg'] = 0
        data['fvg_size'] = 0.0
        data['price_in_discount'] = 0
        data['price_in_premium'] = 0
        data['equilibrium_dist'] = 0.0
        data['htf_trend'] = 0
        data['ltf_trend'] = 0
        data['tf_alignment'] = 0
        data['in_kill_zone'] = 0.5
        data['session_bias'] = 0
        lookback = 50
        for i in range(lookback, len(data)):
            window_df = data.iloc[:i+1].copy()
            try:
                market_structure = self._detect_market_structure(window_df)
                bos, bos_pullback, choch = self._detect_bos_choch(window_df)
                buyside_liq, sellside_liq, liq_sweep = self._detect_liquidity_zones(window_df)
                bull_ob, bear_ob, ob_conf = self._detect_order_blocks(window_df)
                fresh_demand, fresh_supply, zone_str = self._detect_supply_demand_zones(window_df)
                bull_fvg, bear_fvg, fvg_sz = self._detect_fvg(window_df)
                discount, premium, eq_dist = self._calculate_premium_discount(window_df)
                htf_trend = market_structure
                ltf_trend = 1 if window_df['close'].iloc[-1] > window_df['close'].iloc[-5] else -1
                tf_alignment = 1 if htf_trend == ltf_trend else 0
                kill_zone, sess_bias = self._detect_session_timing(window_df)
                data.at[data.index[i], 'market_structure'] = market_structure
                data.at[data.index[i], 'bos_signal'] = bos
                data.at[data.index[i], 'bos_pullback_zone'] = bos_pullback
                data.at[data.index[i], 'choch_signal'] = choch
                data.at[data.index[i], 'buyside_liquidity'] = buyside_liq
                data.at[data.index[i], 'sellside_liquidity'] = sellside_liq
                data.at[data.index[i], 'liquidity_sweep'] = liq_sweep
                data.at[data.index[i], 'bullish_ob_strength'] = bull_ob
                data.at[data.index[i], 'bearish_ob_strength'] = bear_ob
                data.at[data.index[i], 'ob_confluence'] = ob_conf
                data.at[data.index[i], 'fresh_demand_zone'] = fresh_demand
                data.at[data.index[i], 'fresh_supply_zone'] = fresh_supply
                data.at[data.index[i], 'zone_strength'] = zone_str
                data.at[data.index[i], 'bullish_fvg'] = bull_fvg
                data.at[data.index[i], 'bearish_fvg'] = bear_fvg
                data.at[data.index[i], 'fvg_size'] = fvg_sz
                data.at[data.index[i], 'price_in_discount'] = discount
                data.at[data.index[i], 'price_in_premium'] = premium
                data.at[data.index[i], 'equilibrium_dist'] = eq_dist
                data.at[data.index[i], 'htf_trend'] = htf_trend
                data.at[data.index[i], 'ltf_trend'] = ltf_trend
                data.at[data.index[i], 'tf_alignment'] = tf_alignment
                data.at[data.index[i], 'in_kill_zone'] = kill_zone
                data.at[data.index[i], 'session_bias'] = sess_bias
            except Exception as e:
                logger.warning(f"SMC calculation failed for candle {i}: {e}")
                continue
        logger.info(f"✅ SMC features calculated for {len(data) - lookback} candles")
        if style == "sniper":
            horizon = 3
        elif style == "scalp":
            horizon = 10
        elif style == "intraday":
            horizon = 20
        else:
            horizon = 40
        if style in ["swing", "intraday"]:
            future_max = data['high'].shift(-horizon).rolling(window=horizon).max()
            future_min = data['low'].shift(-horizon).rolling(window=horizon).min()
            buy_ret = (future_max - data['close']) / data['close']
            sell_ret = (data['close'] - future_min) / data['close']
        else:
            future_return = (data['close'].shift(-horizon) - data['close']) / data['close']
            buy_ret = future_return
            sell_ret = -future_return
        if style == "sniper":
            mult = 1.0
        elif style == "scalp":
            mult = 2.0
        elif style == "intraday":
            mult = 2.5
        else:
            mult = 4.0
        vol_ref = (data['high'] - data['low']) / data['close']
        profit_hurdle = vol_ref.median() * mult
        min_hurdle = 0.0008 if asset_type == "forex" else 0.005
        if style in ["swing", "intraday"]: min_hurdle *= 2.0
        profit_hurdle = max(profit_hurdle, min_hurdle)
        stop_hurdle = profit_hurdle * 0.5
        logger.info(f"📈 {asset_type} | {style} Profit Hurdle: {profit_hurdle*100:.3f}% | Stop Hurdle: {stop_hurdle*100:.3f}% | Horizon: {horizon}")
        data['target'] = 0
        for i in range(len(data) - horizon):
            window = data.iloc[i+1 : i+1+horizon]
            entry_price = data.iloc[i]['close']
            max_high = window['high'].max()
            min_low = window['low'].min()
            if (max_high - entry_price) / entry_price >= profit_hurdle:
                if (entry_price - min_low) / entry_price < stop_hurdle:
                    data.at[data.index[i], 'target'] = 1
            if (entry_price - min_low) / entry_price >= profit_hurdle:
                if (max_high - entry_price) / entry_price < stop_hurdle:
                    data.at[data.index[i], 'target'] = -1
        data = data.dropna(subset=self.feature_cols + ['target'])
        if len(data) < 200:
            logger.error("❌ Not enough valid data points for training.")
            return False
        X = data[self.feature_cols]
        y = data['target']
        n_est = 150 if style == "scalp" else 250
        depth = 12 if style == "scalp" else 15
        clf = RandomForestClassifier(n_estimators=n_est, max_depth=depth, random_state=42)
        clf.fit(X, y)
        model_path = self._get_model_path(asset_type, style)
        joblib.dump(clf, model_path)
        self.model = clf
        self.current_asset_type = asset_type
        self.current_style = style
        logger.info(f"🚀 AI Model for {asset_type} ({style}) saved to {model_path}")
        return True