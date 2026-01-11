import logging
import time
import pandas as pd
import numpy as np

logger = logging.getLogger("Strategy")

class TradingStrategy:
    def __init__(self, connector, news_engine, config):
        self.connector = connector
        self.news_engine = news_engine
        self.active = True
        
        # --- STRATEGY CONFIGURATION ---
        self.risk_reward_ratio = 2.0     
        self.max_positions = 1           
        self.lot_size = config.get('auto_trading', {}).get('lot_size', 0.01)
        self.trade_cooldown = 15.0       
        
        # --- MODES & FILTERS ---
        # UPDATED: Default to ZONE_BOUNCE for "Buy Low, Sell High" logic
        self.strategy_mode = "ZONE_BOUNCE" 
        self.use_trend_filter = True
        self.use_zone_filter = True

        # --- TIME FILTER (Applied to Pullbacks/Entries) ---
        self.use_time_filter = True
        self.start_hour = 8   # Example: Start trading at 08:00
        self.end_hour = 20    # Example: Stop trading at 20:00

        # --- PROFIT SETTINGS ---
        self.min_profit_target = 0.50    
        self.trailing_activation = 0.80  
        self.trailing_offset = 0.20      
        
        # Indicator Settings
        self.rsi_period = 14
        self.rsi_buy_threshold = 40      
        self.rsi_sell_threshold = 60     
        
        self.macd_fast = 12
        self.macd_slow = 26
        self.macd_signal = 9
        
        self.bb_period = 20
        self.bb_dev = 2.0
        
        self.ema_fast = 9
        self.ema_slow = 21

        # --- State ---
        self.last_trade_time = 0         
        self.last_log_time = 0           
        self.trend = "NEUTRAL"
        self.swing_highs = []  
        self.swing_lows = []
        
        # --- S&R Zones (Tradeciety Method) ---
        self.support_zones = []     
        self.resistance_zones = []
        self.zone_min_touches = 1   
        self.zone_tolerance = 0.0   # [FIX] Initialized to 0, will be set dynamically
        self.last_draw_time = 0     

        self.current_profit = 0.0 
        self.peak_profit = 0.0        
        self.last_profit_close_time = 0
        self.profit_close_interval = 1 

    def start(self):
        logger.info(f"Strategy ACTIVE | Mode: {self.strategy_mode}")

    def stop(self):
        self.active = False
        logger.info("Strategy PAUSED")

    def set_active(self, active):
        self.active = bool(active)
        state = "ACTIVE" if self.active else "PAUSED"
        logging.info(f"Strategy state set to: {state}")

    def reset_state(self):
        """Clears symbol-specific data when switching symbols."""
        self.trend = "NEUTRAL"
        self.support_zones = []
        self.resistance_zones = []
        self.swing_highs = []
        self.swing_lows = []
        self.peak_profit = 0.0
        logging.info("Strategy state reset for new symbol.")

    def on_tick(self, symbol, bid, ask, balance, profit, acct_name, positions, buy_count, sell_count, avg_entry, candles=None):
        if not candles or len(candles) < 200: return
        self.current_profit = profit 

        # --- Track Peak Profit ---
        if positions > 0:
            if profit > self.peak_profit: self.peak_profit = profit
        else:
            self.peak_profit = 0.0

        # --- 1. PRIORITY: Analyze Structure (S&R Zones) & Trend ---
        if self.use_zone_filter: 
            self.analyze_structure_zones(symbol, candles)
            
        if self.use_trend_filter: 
            self.analyze_trend(candles)

        # --- 2. Check Signals based on Selected Mode ---
        if self.active and positions < self.max_positions:
            if (time.time() - self.last_trade_time) > self.trade_cooldown:
                
                # Mode Dispatcher
                if self.strategy_mode == "ZONE_BOUNCE":
                    self.check_signals_zone_bounce(symbol, bid, ask, candles)
                elif self.strategy_mode == "MACD_RSI":
                    self.check_signals_macd_rsi(symbol, bid, ask, candles)
                elif self.strategy_mode == "BOLLINGER":
                    self.check_signals_bollinger(symbol, bid, ask, candles)
                elif self.strategy_mode == "EMA_CROSS":
                    self.check_signals_ema_cross(symbol, bid, ask, candles)
                elif self.strategy_mode == "SMC":
                    self.check_signals_smc(symbol, bid, ask, candles)
                elif self.strategy_mode == "CRT":
                    self.check_signals_crt(symbol, bid, ask, candles)

        # 3. Manage Profit 
        if positions > 0:
            self.check_and_close_profit(symbol)

            # 4. Status Log (Once per 10 seconds)
            if current_time - self.last_log_time >= 10:
                self.last_log_time = current_time
                
                # Prediction/Confidence check
                conf_score, conf_txt = self.get_prediction_score(symbol, bid, ask, candles)
                
                # Zone info
                nearest_supp = self._get_nearest_zone(bid, is_support=True)
                nearest_res = self._get_nearest_zone(bid, is_support=False)
                s_txt = f"{nearest_supp['top']:.2f}" if nearest_supp else "None"
                r_txt = f"{nearest_res['bottom']:.2f}" if nearest_res else "None"
                zone_txt = f"S: {s_txt} | R: {r_txt}" if self.use_zone_filter else "Zone: OFF"
                
                active_txt = "AUTO-ON" if self.active else "AUTO-OFF"
                logger.info(f"📊 {active_txt} | {symbol} | Mode: {self.strategy_mode} | {zone_txt} | Conf: {conf_score}% ({conf_txt}) | PnL: {profit:.2f}")

    def get_prediction_score(self, symbol, bid, ask, candles):
        """
        Synthesizes a confidence score (0-100%) for the current direction.
        This acts as the 'Prediction' engine.
        """
        if not candles or len(candles) < 50: return 0, "No Data"
        
        rsi, macd, macd_sig = self.calculate_indicators(candles)
        atr = self.calculate_atr(candles)
        
        # 1. Trend Alignment (Weight 30%)
        trend_score = 0
        direction = "NEUTRAL"
        if "BULLISH" in self.trend:
            trend_score = 30
            direction = "BUY"
        elif "BEARISH" in self.trend:
            trend_score = 30
            direction = "SELL"
            
        # 2. Indicator Confluence (Weight 30%)
        ind_score = 0
        if direction == "BUY":
            if rsi < 50: ind_score += 15
            if macd > macd_sig: ind_score += 15
        elif direction == "SELL":
            if rsi > 50: ind_score += 15
            if macd < macd_sig: ind_score += 15
            
        # 3. Zone Proximity (Weight 20%)
        zone_score = 0
        if direction == "BUY":
            near_supp = self._get_nearest_zone(bid, is_support=True)
            if near_supp and (bid - near_supp['top']) < (atr * 2):
                zone_score = 20
        elif direction == "SELL":
            near_res = self._get_nearest_zone(bid, is_support=False)
            if near_res and (near_res['bottom'] - bid) < (atr * 2):
                zone_score = 20
                
        # 4. News Sentiment (Weight 20%)
        news_score = 0
        if self.news_engine:
            sentiment = self.news_engine.get_market_sentiment()
            if (direction == "BUY" and sentiment == "BULLISH") or (direction == "SELL" and sentiment == "BEARISH"):
                news_score = 20
            elif sentiment == "NEUTRAL":
                news_score = 10
                
        total_score = trend_score + ind_score + zone_score + news_score
        return total_score, direction

    # =========================================================================
    # --- TRADECIETY S&R LOGIC ---
    # =========================================================================

    def analyze_structure_zones(self, symbol, candles):
        """
        Identifies Support & Resistance Zones.
        FIXED: Reverses candle order to ensure [-1] is the Current Price.
        """
        if not candles: return

        # --- FIX 1: Reverse Data to be [Oldest, ..., Newest] ---
        # MT5 sends [Newest, ..., Oldest], so we flip it.
        ts_candles = candles[::-1]

        # Now ts_candles[-1] is the REAL current price
        current_price = ts_candles[-1]['close']
        
        # Dynamic Tolerance (0.05% of price)
        self.zone_tolerance = current_price * 0.0005 

        # 1. Get Fractals using the TIME SERIES sorted list
        highs, lows = self._get_fractals(ts_candles)
        
        # 2. Cluster Swings into Zones
        all_swings = highs + lows
        zones = self._cluster_levels(all_swings, threshold=self.zone_tolerance)
        
        # 3. Classify Zones
        self.support_zones = []
        self.resistance_zones = []
        
        for zone in zones:
            if zone['count'] >= self.zone_min_touches:
                if zone['top'] < current_price:
                    self.support_zones.append(zone)
                elif zone['bottom'] > current_price:
                    self.resistance_zones.append(zone)
        
        self.support_zones.sort(key=lambda x: x['top'], reverse=True)
        self.resistance_zones.sort(key=lambda x: x['bottom'])
        
        # 4. Visualize
        if time.time() - self.last_draw_time > 5.0:
            self._draw_zones(symbol)
            self.last_draw_time = time.time()

    def _get_fractals(self, candles, window=2):
        highs = []
        lows = []
        
        if len(candles) < (window * 2 + 1): return [], []

        for i in range(window, len(candles) - window - 1):
            curr = candles[i]
            
            is_high = True
            for j in range(1, window + 1):
                if candles[i-j]['high'] > curr['high'] or candles[i+j]['high'] > curr['high']:
                    is_high = False
                    break
            if is_high:
                highs.append(curr['high'])

            is_low = True
            for j in range(1, window + 1):
                if candles[i-j]['low'] < curr['low'] or candles[i+j]['low'] < curr['low']:
                    is_low = False
                    break
            if is_low:
                lows.append(curr['low'])
                
        return highs, lows

    def _cluster_levels(self, levels, threshold):
        if not levels: return []
        
        levels.sort()
        zones = []
        current_cluster = [levels[0]]
        
        for i in range(1, len(levels)):
            price = levels[i]
            if price - current_cluster[-1] <= threshold:
                current_cluster.append(price)
            else:
                zones.append(self._make_zone_dict(current_cluster))
                current_cluster = [price]
        
        if current_cluster:
            zones.append(self._make_zone_dict(current_cluster))
            
        return zones

    def _make_zone_dict(self, cluster):
        return {
            'top': max(cluster),
            'bottom': min(cluster),
            'center': sum(cluster) / len(cluster),
            'count': len(cluster)
        }

    def _get_nearest_zone(self, price, is_support):
        zones = self.support_zones if is_support else self.resistance_zones
        if not zones: return None
        return zones[0]

    def _draw_zones(self, symbol):
        for i, zone in enumerate(self.support_zones[:3]):
            name = f"Supp_{i}"
            self.connector.send_draw_command(name, zone['top'], zone['bottom'], 100, 0, "0x008000") 

        for i, zone in enumerate(self.resistance_zones[:3]):
            name = f"Res_{i}"
            self.connector.send_draw_command(name, zone['top'], zone['bottom'], 100, 0, "0x000080") 

    # =========================================================================

    def _is_trading_time(self):
        """Checks if current time is within allowed trading hours."""
        if not self.use_time_filter: return True
        
        curr_hour = time.localtime().tm_hour
        
        if self.start_hour <= self.end_hour:
            # Intra-day (e.g., 08:00 to 20:00)
            return self.start_hour <= curr_hour < self.end_hour
        else:
            # Overnight (e.g., 22:00 to 06:00)
            return curr_hour >= self.start_hour or curr_hour < self.end_hour

        return True

    def calculate_atr(self, candles, window=14):
        """Calculates Average True Range for symbol-agnostic volatility."""
        try:
            if len(candles) < window + 1: return 0.0
            df = pd.DataFrame(candles)
            # Ensure chronological order
            if df['time'].iloc[0] > df['time'].iloc[-1]:
                df = df.iloc[::-1].reset_index(drop=True)
            
            high_low = df['high'] - df['low']
            high_pc = (df['high'] - df['close'].shift(1)).abs()
            low_pc = (df['low'] - df['close'].shift(1)).abs()
            tr = pd.concat([high_low, high_pc, low_pc], axis=1).max(axis=1)
            atr = tr.rolling(window=window).mean().iloc[-1]
            return float(atr)
        except:
            return 0.0

    def calculate_indicators(self, candles):
        try:
            df = pd.DataFrame(candles)
            df = df.iloc[::-1].reset_index(drop=True) 
            
            # RSI
            delta = df['close'].diff()
            gain = (delta.where(delta > 0, 0)).rolling(window=self.rsi_period).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(window=self.rsi_period).mean()
            rs = gain / loss
            df['rsi'] = 100 - (100 / (1 + rs))

            # MACD
            short_ema = df['close'].ewm(span=self.macd_fast, adjust=False).mean()
            long_ema = df['close'].ewm(span=self.macd_slow, adjust=False).mean()
            df['macd'] = short_ema - long_ema
            df['macd_signal'] = df['macd'].ewm(span=self.macd_signal, adjust=False).mean()

            last_closed = df.iloc[-2] 
            return last_closed['rsi'], last_closed['macd'], last_closed['macd_signal']
        except Exception as e:
            return 50, 0, 0

    def calculate_bollinger(self, candles):
        try:
            df = pd.DataFrame(candles)
            df = df.iloc[::-1].reset_index(drop=True)
            df['sma'] = df['close'].rolling(window=self.bb_period).mean()
            df['std'] = df['close'].rolling(window=self.bb_period).std()
            df['upper'] = df['sma'] + (df['std'] * self.bb_dev)
            df['lower'] = df['sma'] - (df['std'] * self.bb_dev)
            last = df.iloc[-2]
            return last['upper'], last['lower'], last['close']
        except: return 0,0,0

    def calculate_ema_cross(self, candles):
        try:
            df = pd.DataFrame(candles)
            df = df.iloc[::-1].reset_index(drop=True)
            df['fast'] = df['close'].ewm(span=self.ema_fast, adjust=False).mean()
            df['slow'] = df['close'].ewm(span=self.ema_slow, adjust=False).mean()
            
            curr = df.iloc[-2]
            prev = df.iloc[-3]
            
            cross_up = prev['fast'] <= prev['slow'] and curr['fast'] > curr['slow']
            cross_down = prev['fast'] >= prev['slow'] and curr['fast'] < curr['slow']
            return cross_up, cross_down
        except: return False, False

    def calculate_smc(self, candles):
        """Detects the latest Fair Value Gap (FVG) using ATR for normalization."""
        try:
            atr = self.calculate_atr(candles)
            if atr == 0: return None, None
            
            bullish_fvg = None
            bearish_fvg = None
            for i in range(-2, -6, -1):
                try:
                    c3 = candles[i]
                    c1 = candles[i-2]

                    # Bullish FVG (Gap between Candle 1 High and Candle 3 Low)
                    if c3['low'] > c1['high']:
                        gap_size = c3['low'] - c1['high']
                        if gap_size > (atr * 0.1): 
                            bullish_fvg = (c1['high'], c3['low']) 
                            break 

                    # Bearish FVG (Gap between Candle 1 Low and Candle 3 High)
                    if c3['high'] < c1['low']:
                        gap_size = c1['low'] - c3['high']
                        if gap_size > (atr * 0.1):
                            bearish_fvg = (c3['high'], c1['low']) 
                            break
                except IndexError: pass
            
            return bullish_fvg, bearish_fvg
        except: return None, None

    def _check_filters(self, direction, current_price):
        """Returns True if trade is allowed, False if blocked by filters."""
        # Symbol-agnostic Digit Handling
        is_high_value = current_price > 100 
        
        # 1. TIME FILTER
        if not self._is_trading_time():
            self._log_skip(f"Time Filter: Outside trading hours ({self.start_hour}:00 - {self.end_hour}:00)")
            return False

        # 2. ZONE FILTER
        if self.use_zone_filter:
            # Distances are already normalized by zone_tolerance (0.05% of price)
            if direction == "BUY":
                nearest_res = self._get_nearest_zone(current_price, is_support=False)
                if nearest_res:
                    dist_to_res = nearest_res['bottom'] - current_price
                    if dist_to_res < (self.zone_tolerance * 0.5): 
                        self._log_skip("Zone Filter: Too close to Resistance")
                        return False

            if direction == "SELL":
                nearest_supp = self._get_nearest_zone(current_price, is_support=True)
                if nearest_supp:
                    dist_to_supp = current_price - nearest_supp['top']
                    if dist_to_supp < (self.zone_tolerance * 0.5):
                        self._log_skip("Zone Filter: Too close to Support")
                        return False

        # 3. Trend Filter
        if self.use_trend_filter:
            if direction == "BUY" and "BEARISH" in self.trend:
                self._log_skip(f"Trend Filter: Trend is {self.trend}.")
                return False
            if direction == "SELL" and "BULLISH" in self.trend:
                self._log_skip(f"Trend Filter: Trend is {self.trend}.")
                return False
        
        return True
    
    # =========================================================================
    # --- NEW: ZONE BOUNCE STRATEGY (Buy Low, Sell High) ---
    # =========================================================================
    
    def check_signals_zone_bounce(self, symbol, bid, ask, candles):
        """
        Implements 'Buy Low, Sell High' using S&R Zones.
        - BUY when Price is near Support (Low).
        - SELL when Price is near Resistance (High).
        """
        atr = self.calculate_atr(candles)
        if atr == 0: return

        # 1. BUY LOW (Support)
        nearest_supp = self._get_nearest_zone(bid, is_support=True)
        if nearest_supp:
            dist = bid - nearest_supp['top']
            
            # Use ATR-based proximity for entry
            near_entry = dist <= (atr * 1.5)
            not_broken = bid >= (nearest_supp['bottom'] - (atr * 0.5))
            
            if near_entry and not_broken:
                conf, dir = self.get_prediction_score(symbol, bid, ask, candles)
                if conf >= 60 and dir == "BUY":
                    if self._check_filters("BUY", ask):
                        sl, tp = self.calculate_safe_risk("BUY", ask, candles)
                        logger.info(f"✅ BUY (PREDICTED) | Conf: {conf}% | Zone: Support | ATR: {atr:.5f}")
                        self.execute_trade("BUY", symbol, self.lot_size, "PREDICTION", sl, tp)

        # 2. SELL HIGH (Resistance)
        nearest_res = self._get_nearest_zone(bid, is_support=False)
        if nearest_res:
            dist = nearest_res['bottom'] - bid
            
            near_entry = dist <= (atr * 1.5)
            not_broken = bid <= (nearest_res['top'] + (atr * 0.5))
            
            if near_entry and not_broken:
                conf, dir = self.get_prediction_score(symbol, bid, ask, candles)
                if conf >= 60 and dir == "SELL":
                    if self._check_filters("SELL", bid):
                        sl, tp = self.calculate_safe_risk("SELL", bid, candles)
                        logger.info(f"✅ SELL (PREDICTED) | Conf: {conf}% | Zone: Resistance | ATR: {atr:.5f}")
                        self.execute_trade("SELL", symbol, self.lot_size, "PREDICTION", sl, tp)

    # =========================================================================

    def check_signals_macd_rsi(self, symbol, bid, ask, candles):
        rsi, macd, macd_signal = self.calculate_indicators(candles)
        conf, dir = self.get_prediction_score(symbol, bid, ask, candles)
        
        # LOG DETAILED SKIP (Optional/Internal)
        if conf < 50:
            self._log_skip(f"Low Confidence: {conf}% (Need 50%) | Indicators: RSI={rsi:.1f}, MACD={macd:.5f}")

        if rsi < self.rsi_buy_threshold and macd > macd_signal and conf >= 50:
            if self._check_filters("BUY", ask):
                sl, tp = self.calculate_safe_risk("BUY", ask, candles)
                logger.info(f"✅ BUY (MACD) | Conf: {conf}% | RSI: {rsi:.1f}")
                self.execute_trade("BUY", symbol, self.lot_size, "MACD_RSI", sl, tp)

        elif rsi > self.rsi_sell_threshold and macd < macd_signal and conf >= 50:
            if self._check_filters("SELL", bid):
                sl, tp = self.calculate_safe_risk("SELL", bid, candles)
                logger.info(f"✅ SELL (MACD) | Conf: {conf}% | RSI: {rsi:.1f}")
                self.execute_trade("SELL", symbol, self.lot_size, "MACD_RSI", sl, tp)

    def check_signals_bollinger(self, symbol, bid, ask, candles):
        upper, lower, close = self.calculate_bollinger(candles)
        rsi, _, _ = self.calculate_indicators(candles)
        conf, dir = self.get_prediction_score(symbol, bid, ask, candles)
        
        if close < lower and rsi < self.rsi_buy_threshold and conf >= 50:
            if self._check_filters("BUY", ask):
                sl, tp = self.calculate_safe_risk("BUY", ask, candles)
                logger.info(f"✅ BUY (BB) | Conf: {conf}% | Price < Lower | RSI: {rsi:.1f}")
                self.execute_trade("BUY", symbol, self.lot_size, "BB_RSI", sl, tp)
        
        elif close > upper and rsi > self.rsi_sell_threshold and conf >= 50:
            if self._check_filters("SELL", bid):
                sl, tp = self.calculate_safe_risk("SELL", bid, candles)
                logger.info(f"✅ SELL (BB) | Conf: {conf}% | Price > Upper | RSI: {rsi:.1f}")
                self.execute_trade("SELL", symbol, self.lot_size, "BB_RSI", sl, tp)

    def check_signals_ema_cross(self, symbol, bid, ask, candles):
        cross_up, cross_down = self.calculate_ema_cross(candles)
        conf, dir = self.get_prediction_score(symbol, bid, ask, candles)
        
        if cross_up and conf >= 50:
            if self._check_filters("BUY", ask):
                sl, tp = self.calculate_safe_risk("BUY", ask, candles)
                logger.info(f"✅ BUY (EMA CROSS) | Conf: {conf}%")
                self.execute_trade("BUY", symbol, self.lot_size, "EMA_CROSS", sl, tp)
        
        elif cross_down and conf >= 50:
            if self._check_filters("SELL", bid):
                sl, tp = self.calculate_safe_risk("SELL", bid, candles)
                logger.info(f"✅ SELL (EMA CROSS) | Conf: {conf}%")
                self.execute_trade("SELL", symbol, self.lot_size, "EMA_CROSS", sl, tp)

    def check_signals_smc(self, symbol, bid, ask, candles):
        bullish_fvg, bearish_fvg = self.calculate_smc(candles)
        current_price = (bid + ask) / 2
        conf, dir = self.get_prediction_score(symbol, bid, ask, candles)
        
        if bullish_fvg and conf >= 50:
            low, high = bullish_fvg
            if low <= current_price <= high:
                if self._check_filters("BUY", ask):
                    sl, tp = self.calculate_safe_risk("BUY", ask, candles)
                    logger.info(f"✅ BUY (SMC) | Conf: {conf}% | Inside Bullish FVG")
                    self.execute_trade("BUY", symbol, self.lot_size, "SMC_FVG", sl, tp)

        if bearish_fvg and conf >= 50:
            low, high = bearish_fvg
            if low <= current_price <= high:
                if self._check_filters("SELL", bid):
                    sl, tp = self.calculate_safe_risk("SELL", bid, candles)
                    logger.info(f"✅ SELL (SMC) | Conf: {conf}% | Inside Bearish FVG")
                    self.execute_trade("SELL", symbol, self.lot_size, "SMC_FVG", sl, tp)

    def check_signals_crt(self, symbol, bid, ask, candles):
        if len(candles) < 3: return
        prev = candles[1] 
        conf, dir = self.get_prediction_score(symbol, bid, ask, candles)
        
        if ask > prev['high'] and conf >= 60:
            if self._check_filters("BUY", ask):
                sl, tp = self.calculate_safe_risk("BUY", ask, candles)
                logger.info(f"✅ BUY (CRT) | Conf: {conf}% | Breakout High {prev['high']}")
                self.execute_trade("BUY", symbol, self.lot_size, "CRT_BREAK", sl, tp)

        elif bid < prev['low'] and conf >= 60:
            if self._check_filters("SELL", bid):
                sl, tp = self.calculate_safe_risk("SELL", bid, candles)
                logger.info(f"✅ SELL (CRT) | Conf: {conf}% | Breakout Low {prev['low']}")
                self.execute_trade("SELL", symbol, self.lot_size, "CRT_BREAK", sl, tp)

    def _log_skip(self, message):
        if time.time() - self.last_log_time > 15:
            logger.info(f"❌ {message}")
            self.last_log_time = time.time()

    def analyze_trend(self, candles):
        try:
            df = pd.DataFrame(candles)
            df = df.iloc[::-1].reset_index(drop=True) 
            ema200 = df['close'].ewm(span=200, adjust=False).mean().iloc[-1]
            current = df['close'].iloc[-1]
            
            if current > ema200:
                self.trend = "BULLISH_STRONG" if current > (ema200 * 1.001) else "BULLISH_WEAK"
            else:
                self.trend = "BEARISH_STRONG" if current < (ema200 * 0.999) else "BEARISH_WEAK"
        except:
            self.trend = "NEUTRAL"

    def calculate_safe_risk(self, direction, entry_price, candles):
        """
        Adaptive Risk Management using ATR.
        Works for all symbols (Forex, Crypto, Gold) automatically.
        """
        sl = 0.0
        tp = 0.0
        
        atr = self.calculate_atr(candles)
        if atr == 0:
            # Fallback to 0.1% of price if ATR not available
            atr = entry_price * 0.001
        
        # Stop Loss at 2.0x ATR for safety
        sl_dist = atr * 2.0
        
        if direction == "BUY":
            nearest_supp = self._get_nearest_zone(entry_price, is_support=True)
            if nearest_supp and (entry_price - nearest_supp['bottom']) < (sl_dist * 1.5):
                # If zone is nearby, put SL just below the zone
                sl = nearest_supp['bottom'] - (atr * 0.2)
            else:
                sl = entry_price - sl_dist
            
            tp = entry_price + ((entry_price - sl) * self.risk_reward_ratio)

        elif direction == "SELL":
            nearest_res = self._get_nearest_zone(entry_price, is_support=False)
            if nearest_res and (nearest_res['top'] - entry_price) < (sl_dist * 1.5):
                sl = nearest_res['top'] + (atr * 0.2)
            else:
                sl = entry_price + sl_dist
            
            tp = entry_price - ((sl - entry_price) * self.risk_reward_ratio)

        return float(sl), float(tp)

    def execute_trade(self, direction, symbol, volume, reason, sl, tp):
        self.last_trade_time = time.time()
        self.connector.send_command(direction, symbol, volume, sl, tp, 0)
        logger.info(f"🚀 EXECUTED {direction} {symbol} | Vol: {volume} | SL: {sl:.4f} | TP: {tp:.4f}")

    def check_and_close_profit(self, symbol):
        if time.time() - self.last_profit_close_time < self.profit_close_interval: return
        self.last_profit_close_time = time.time()
        
        if self.peak_profit >= self.trailing_activation:
            if self.current_profit <= (self.peak_profit - self.trailing_offset):
                logger.info(f"🔒 TRAILING STOP HIT: Peak {self.peak_profit:.2f} -> Current {self.current_profit:.2f}")
                self.connector.close_profit(symbol)
                return

        if self.current_profit >= self.min_profit_target and self.peak_profit < self.trailing_activation:
            logger.info(f"💰 TARGET HIT: {self.current_profit:.2f}")
            self.connector.close_profit(symbol)