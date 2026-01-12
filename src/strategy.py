import logging
import time
import pandas as pd
import numpy as np
from datetime import datetime
try:
    from zoneinfo import ZoneInfo
except ImportError:
    from backports.zoneinfo import ZoneInfo

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
        
        # --- MARKET SESSIONS (Local Hours) ---
        self.SESSIONS = {
            "London": {"start": 8, "end": 17, "tz": "Europe/London"},
            "New York": {"start": 8, "end": 17, "tz": "America/New_York"},
            "Tokyo": {"start": 9, "end": 18, "tz": "Asia/Tokyo"},
            "Sydney": {"start": 7, "end": 16, "tz": "Australia/Sydney"}
        }

        # --- TIME FILTER ---
        self.use_time_filter = True
        self.time_zone = "Auto" # "Local", "London", "New York", "Tokyo", "Sydney", "Auto"
        self.start_hour = 8   
        self.end_hour = 20    

        # --- PROFIT SETTINGS ---
        self.use_profit_management = True
        self.min_profit_target = 0.10    # Default if not in UI
        
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

        # CRT Settings
        self.crt_htf = 240
        self.crt_zone_size = 0.50 # Expanded to 50% (Premium/Discount) for more entries

        # --- State ---
        self.last_trade_time = 0         
        self.last_log_time = 0           
        self.last_status_time = 0        # NEW: Timer for DASHBOARD logs
        self.last_crt_diag_time = 0      # NEW: Timer for CRT diagnostics
        self.last_crt_draw = 0           # NEW: Timer for CRT MT5 visuals
        self.last_crt_summary_time = 0   # NEW: Timer for CRT range summary logs
        self.last_hist_req = 0           # NEW: Timer for history requests
        self.trend = "NEUTRAL"
        self.active_session_name = "None"
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
        
        # --- NEW: TRADE PROTECTION ---
        self.break_even_activation = 0.50  # Move SL to Entry when profit hits $0.50
        self.break_even_active = False

    def start(self):
        tz_info = f"Zone: {self.time_zone}" if self.time_zone != "Auto" else "Zone: AUTO (Rotation)"
        logger.info(f"Strategy ACTIVE | Mode: {self.strategy_mode} | {tz_info}")

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
        current_time = time.time()
        
        # Determine MT5 Server Time for logging sync
        server_time_str = "??:??:??"
        if candles and len(candles) > 0:
            server_time_str = datetime.fromtimestamp(candles[-1]['time']).strftime('%H:%M:%S')

        # 0. Data Validation & Automated History Fetching
        min_needed = 200 # Standard for indicators like 200 EMA
        if self.strategy_mode == "CRT":
            # CRT needs enough candles to build at least 2 HTF candles
            ltf_mins = 5
            if candles and len(candles) > 1:
                ltf_mins = (candles[1]['time'] - candles[0]['time']) // 60
            min_needed = (self.crt_htf // ltf_mins) * 3 # 3 candles for safety

        if not candles or len(candles) < min_needed:
            # Request more history if we haven't asked recently (every 5s)
            if current_time - self.last_hist_req > 5:
                # Ask for slightly more than we need
                self.connector.request_history(symbol, min_needed + 50)
                self.last_hist_req = current_time
                logging.info(f"Requesting {min_needed + 50} candles for {symbol}...")
            
            if candles and len(candles) > 0:
                self._log_skip(f"Gathering data... ({len(candles)}/{min_needed} candles)")
            return

        # --- FIX: Standardize to [Oldest, ..., Newest] ---
        # MT5 sends [Newest, ..., Oldest] by default
        if candles[0]['time'] > candles[-1]['time']:
            candles = candles[::-1]
        
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

        # 3. Status Dashboard (Every 10 seconds)
        if current_time - self.last_status_time >= 10:
            self.last_status_time = current_time
            conf_score, conf_txt = self.get_prediction_score(symbol, bid, ask, candles)
            
            near_supp = self._get_nearest_zone(bid, is_support=True)
            near_res = self._get_nearest_zone(bid, is_support=False)
            s_val = f"{near_supp['top']:.2f}" if near_supp else "None"
            r_val = f"{near_res['bottom']:.2f}" if near_res else "None"
            
            active_txt = "AUTO-ON" if self.active else "AUTO-OFF"
            logger.info(f"📊 [MT5:{server_time_str}] {active_txt} | {symbol} | Mode: {self.strategy_mode} | S: {s_val} | R: {r_val} | Conf: {conf_score}% | PnL: {profit:.2f}")

        # 4. Manage Profit 
        if positions > 0 and self.use_profit_management:
            self.check_and_close_profit(symbol)

    def get_prediction_score(self, symbol, bid, ask, candles, is_reversal=False):
        """
        Synthesizes a confidence score (0-100%) for the current direction.
        This acts as the 'Prediction' engine.
        If is_reversal=True, trend component is handled as potential turn, not continuation.
        """
        if not candles or len(candles) < 50: return 0, "No Data"
        
        rsi, macd, macd_sig = self.calculate_indicators(candles)
        atr = self.calculate_atr(candles)
        
        # 1. Indicator-based score (Base Weight 40%)
        # Determine inherent strength of markers regardless of trend
        buy_strength = 0
        sell_strength = 0
        
        if rsi < 50: buy_strength += 20
        else: sell_strength += 20
        
        if macd > macd_sig: buy_strength += 20
        else: sell_strength += 20
        
        # 2. Zone Proximity (Weight 20%)
        near_supp = self._get_nearest_zone(bid, is_support=True)
        if near_supp and (bid - near_supp['top']) < (atr * 2):
            buy_strength += 20
            
        near_res = self._get_nearest_zone(bid, is_support=False)
        if near_res and (near_res['bottom'] - bid) < (atr * 2):
            sell_strength += 20
                
        # 3. News Sentiment (Weight 20%)
        if self.news_engine:
            sentiment = self.news_engine.get_market_sentiment()
            if sentiment == "BULLISH": buy_strength += 20
            elif sentiment == "BEARISH": sell_strength += 20
            elif sentiment == "NEUTRAL": 
                buy_strength += 10
                sell_strength += 10
        
        # 4. Trend Context (Weight 20%)
        if is_reversal:
            # For Reversals, we don't strictly follow the 200 EMA trend as a filter,
            # but we look for "Exhaustion" or "Turn" signals. 
            # If RSI/MACD already support the move, we give the trend weight to the signal.
            buy_strength += 10
            sell_strength += 10
        else:
            if "BULLISH" in self.trend: buy_strength += 20
            elif "BEARISH" in self.trend: sell_strength += 20

        # 5. DIVERGENCE BOOST (Weight +20%)
        divergence = self.calculate_divergence(candles)
        if divergence == "BULLISH": buy_strength = min(100, buy_strength + 20)
        elif divergence == "BEARISH": sell_strength = min(100, sell_strength + 20)

        # Result Logic
        if buy_strength >= sell_strength:
            return buy_strength, "BUY"
        else:
            return sell_strength, "SELL"

    def calculate_divergence(self, candles):
        """Detects if price movement and RSI are moving in opposite directions."""
        try:
            if len(candles) < 20: return "NONE"
            df = pd.DataFrame(candles[-20:])
            rsi_vals = df['close'].rolling(14).mean() # Simplified RSI proxy or use real RSI
            
            price_trend = df['close'].iloc[-1] - df['close'].iloc[-10]
            # Real RSI calc for the window
            delta = df['close'].diff()
            gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
            rs = gain / loss
            rsi = 100 - (100 / (1 + rs))
            
            rsi_trend = rsi.iloc[-1] - rsi.iloc[-10]
            
            if price_trend < 0 and rsi_trend > 0: return "BULLISH"
            if price_trend > 0 and rsi_trend < 0: return "BEARISH"
            return "NONE"
        except: return "NONE"

    # =========================================================================
    # --- TRADECIETY S&R LOGIC ---
    # =========================================================================

    def analyze_structure_zones(self, symbol, candles):
        """
        Identifies Support & Resistance Zones.
        FIXED: Reverses candle order to ensure [-1] is the Current Price.
        """
        if not candles: return

        # Candles are already [Oldest -> Newest] from on_tick check
        ts_candles = candles
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
        """Checks if current time is within allowed trading hours in the selected timezone/session."""
        if not self.use_time_filter: return True
        
        try:
            # --- AUTO SESSION ROTATION ---
            if self.time_zone == "Auto":
                active_session = None
                active_any = False # Initialize to False
                for session_name, config in self.SESSIONS.items():
                    tz = ZoneInfo(config['tz'])
                    now = datetime.now(tz)
                    hour = now.hour
                    
                    start, end = config['start'], config['end']
                    is_active = False
                    if start <= end:
                        if start <= hour < end: is_active = True
                    else: # Overnight
                        if hour >= start or hour < end: is_active = True
                    
                    if is_active:
                        active_session = session_name
                        active_any = True
                        break
                
                self.active_session_name = active_session if active_session else "Closed"
                
                if active_any:
                    if time.time() - self.last_log_time > 60:
                        logger.info(f"🌐 Running in AUTO Session: {active_session} Active")
                return active_any

            # --- SPECIFIC TIMEZONE ---
            # ... (Existing mapping)
            tz_map = {
                "London": "Europe/London",
                "New York": "America/New_York",
                "Tokyo": "Asia/Tokyo",
                "Sydney": "Australia/Sydney"
            }
            
            if self.time_zone in tz_map:
                self.active_session_name = self.time_zone
                tz = ZoneInfo(tz_map[self.time_zone])
                now = datetime.now(tz)
            else:
                self.active_session_name = "Local"
                now = datetime.now() # Local
            
            curr_hour = now.hour
            if self.start_hour <= self.end_hour:
                return self.start_hour <= curr_hour < self.end_hour
            else:
                return curr_hour >= self.start_hour or curr_hour < self.end_hour
                
        except Exception as e:
            logger.error(f"Time Filter Error: {e}")
            return True

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
            # Candles are already chronological [Oldest -> Newest]
            
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


    def _check_filters(self, direction, current_price):
        """Returns True if trade is allowed, False if blocked by filters."""
        # Symbol-agnostic Digit Handling
        is_high_value = current_price > 100 
        
        # 0. NEWS PAUSE
        if self.news_engine and self.news_engine.trading_pause:
            self._log_skip("News Filter: Trading is currently PAUSED due to high-impact news.")
            return False

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
            # Reversal strategies (CRT/SMC) often trade against the 200 EMA trend
            is_reversal_mode = self.strategy_mode in ["CRT", "SMC", "BOLLINGER"]
            
            if not is_reversal_mode:
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
                conf, dir = self.get_prediction_score(symbol, bid, ask, candles, is_reversal=True)
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
                conf, dir = self.get_prediction_score(symbol, bid, ask, candles, is_reversal=True)
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

    # =========================================================================
    # --- UPDATED: BOLLINGER BANDS + RSI STRATEGY (PDF Page 6) ---
    # =========================================================================

    def check_signals_bollinger(self, symbol, bid, ask, candles):
        """
        Implementation of the Bollinger Bands + RSI Reversal Strategy.
        Ref: Bollinger-Bands-Trading-Strategy.pdf
        """
        if len(candles) < 50: return

        # 1. Prepare Dataframe for Lookback
        df = pd.DataFrame(candles)
        df['close'] = df['close'].astype(float)
        
        # 2. Calculate Indicators on the whole series
        # RSI (14)
        delta = df['close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / loss
        df['rsi'] = 100 - (100 / (1 + rs))
        
        # Bollinger Bands (20, 2)
        df['sma'] = df['close'].rolling(window=20).mean() # Middle Band
        df['std'] = df['close'].rolling(window=20).std()
        df['upper'] = df['sma'] + (df['std'] * 2.0)
        df['lower'] = df['sma'] - (df['std'] * 2.0)
        
        # Get Current and Previous Candle
        # We use -1 (last completed candle) vs -2 for crossover checks
        # Or -1 (forming) vs -2 (completed) depending on if you want confirmed close.
        # Strategy usually requires a CLOSE past the middle band.
        curr = df.iloc[-1]
        prev = df.iloc[-2]
        
        atr = self.calculate_atr(candles)

        # -----------------------------------------------------------
        # BUY LOGIC: Setup (Oversold) -> Trigger (Cross Middle Band Up)
        # -----------------------------------------------------------
        
        # TRIGGER: Price closes ABOVE Middle Band (Validation) 
        cross_up = prev['close'] < prev['sma'] and curr['close'] > curr['sma']
        
        if cross_up:
            # SETUP CHECK: Look back 20 candles for the "Setup"
            # Condition: Price was < Lower Band AND RSI < 30 
            lookback = df.iloc[-20:-1] 
            setup_valid = False
            swing_low = curr['low']
            
            for idx, row in lookback.iterrows():
                if row['low'] < swing_low: swing_low = row['low'] # Track swing low
                
                # Check if we had the extreme condition recently
                if row['close'] < row['lower'] and row['rsi'] < 30:
                    setup_valid = True
            
            if setup_valid:
                if self._check_filters("BUY", ask):
                    # SL: Below Swing Low 
                    sl = swing_low - (atr * 0.2)
                    # TP: Target Upper Band or Next Overbought Area 
                    tp = curr['upper'] 
                    
                    logger.info(f"✅ BUY (BB-RSI) | Reversal Confirmed | Cross Middle Band")
                    self.execute_trade("BUY", symbol, self.lot_size, "BB_RSI_REV", sl, tp)
                    return

        # -----------------------------------------------------------
        # SELL LOGIC: Setup (Overbought) -> Trigger (Cross Middle Band Down)
        # -----------------------------------------------------------
        
        # TRIGGER: Price closes BELOW Middle Band (Validation)
        cross_down = prev['close'] > prev['sma'] and curr['close'] < curr['sma']
        
        if cross_down:
            # SETUP CHECK: Look back 20 candles
            # Condition: Price was > Upper Band AND RSI > 70 
            lookback = df.iloc[-20:-1]
            setup_valid = False
            swing_high = curr['high']
            
            for idx, row in lookback.iterrows():
                if row['high'] > swing_high: swing_high = row['high']
                
                if row['close'] > row['upper'] and row['rsi'] > 70:
                    setup_valid = True
            
            if setup_valid:
                if self._check_filters("SELL", bid):
                    # SL: Above Swing High
                    sl = swing_high + (atr * 0.2)
                    # TP: Target Lower Band
                    tp = curr['lower']
                    
                    logger.info(f"✅ SELL (BB-RSI) | Reversal Confirmed | Cross Middle Band")
                    self.execute_trade("SELL", symbol, self.lot_size, "BB_RSI_REV", sl, tp)

    # =========================================================================
    # --- UPDATED: 9/30 EMA TRADING STRATEGY (PDF Page 4) ---
    # =========================================================================

    def check_signals_ema_cross(self, symbol, bid, ask, candles):
        # Ensure we have enough data for the Slow WMA
        min_needed = self.ema_slow + 5
        if len(candles) < min_needed: return

        # 1. Prepare Data
        df = pd.DataFrame(candles)
        df['close'] = df['close'].astype(float)
        
        # 2. Calculate Indicators using UI Variables
        fast_period = self.ema_fast
        slow_period = self.ema_slow

        # Fast EMA
        df['fast_ema'] = df['close'].ewm(span=fast_period, adjust=False).mean()
        
        # Slow WMA (Weighted Moving Average)
        weights = np.arange(1, slow_period + 1)
        wma_func = lambda x: np.dot(x, weights) / weights.sum()
        df['slow_wma'] = df['close'].rolling(window=slow_period).apply(wma_func, raw=True)

        curr = df.iloc[-1]
        atr = self.calculate_atr(candles)

        # -----------------------------------------------------------
        # BUY SCENARIO (Bullish Trend)
        # -----------------------------------------------------------
        # Condition 1: Fast EMA > Slow WMA
        if curr['fast_ema'] > curr['slow_wma']:
            
            # Condition 2: Spot Retracement (Pullback to Fast EMA)
            pullback_candle = None
            lookback_slice = df.iloc[-6:-1]
            
            for idx, row in lookback_slice.iterrows():
                if row['low'] <= row['fast_ema']:
                    pullback_candle = row
            
            # Condition 3: Trigger (Break of Structure)
            if pullback_candle is not None:
                trigger_price = pullback_candle['high']
                
                if ask > trigger_price and ask < (trigger_price + atr):
                    if self._check_filters("BUY", ask):
                        sl = pullback_candle['low'] - (atr * 0.2)
                        tp = ask + ((ask - sl) * 2.0)
                        
                        logger.info(f"✅ BUY (EMA {fast_period}/{slow_period}) | Trend Pullback | Break {trigger_price:.2f}")
                        self.execute_trade("BUY", symbol, self.lot_size, "EMA_RET_FLEX", sl, tp)
                        return

        # -----------------------------------------------------------
        # SELL SCENARIO (Bearish Trend)
        # -----------------------------------------------------------
        # Condition 1: Fast EMA < Slow WMA
        elif curr['fast_ema'] < curr['slow_wma']:
            
            pullback_candle = None
            lookback_slice = df.iloc[-6:-1]
            
            for idx, row in lookback_slice.iterrows():
                if row['high'] >= row['fast_ema']:
                    pullback_candle = row
            
            if pullback_candle is not None:
                trigger_price = pullback_candle['low']
                
                if bid < trigger_price and bid > (trigger_price - atr):
                    if self._check_filters("SELL", bid):
                        sl = pullback_candle['high'] + (atr * 0.2)
                        tp = bid - ((sl - bid) * 2.0)
                        
                        logger.info(f"✅ SELL (EMA {fast_period}/{slow_period}) | Trend Pullback | Break {trigger_price:.2f}")
                        self.execute_trade("SELL", symbol, self.lot_size, "EMA_RET_FLEX", sl, tp)

    # =========================================================================
    # --- UPDATED: SMART MONEY CONCEPTS (SMC) PER BLOG ---
    # =========================================================================

    def detect_market_structure(self, candles):
        """
        Determines Market Structure based on Break of Structure (BOS).
        Returns: 'BULLISH', 'BEARISH', or 'NEUTRAL'
        """
        if len(candles) < 50: return "NEUTRAL"
        
        # 1. Identify Swings (Fractals)
        # We look back to find the most recent major swing points
        highs, lows = self._get_fractals(candles, window=3)
        
        if not highs or not lows: return "NEUTRAL"
        
        # Most recent confirmed swing points
        last_high = highs[-1]
        last_low = lows[-1]
        
        current_close = candles[-1]['close']
        
        # 2. Check for Break of Structure (BOS)
        # If price is trading above the last major swing high -> Bullish Flow
        if current_close > last_high:
            return "BULLISH"
        
        # If price is trading below the last major swing low -> Bearish Flow
        elif current_close < last_low:
            return "BEARISH"
            
        # If inside the range, look at previous BOS direction
        # (Simplified: assumes continuation of last known break)
        prev_close = candles[-20]['close']
        if current_close > prev_close: return "BULLISH" # Weak proxy if ranging
        
        return "NEUTRAL"

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

    def calculate_order_blocks(self, candles):
        """
        Identifies valid Order Blocks (OB) responsible for a BOS/Strong Move.
        Refined to look for the specific 'Institutional Footprint'.
        """
        bullish_ob = None
        bearish_ob = None
        
        if len(candles) < 20: return None, None
        
        # Scan last 50 candles for the most recent valid OB
        for i in range(len(candles) - 3, len(candles) - 30, -1):
            curr = candles[i]
            next_1 = candles[i+1]
            next_2 = candles[i+2]
            
            # --- BULLISH OB (Sell before Buy) ---
            # 1. Bearish Candle (Down)
            # 2. Followed by aggressive displacement (Gap/Large Green Candle)
            if curr['close'] < curr['open']: # Red Candle
                displacement = (next_1['close'] > curr['high']) or \
                               (next_2['close'] > curr['high'] and next_2['close'] > next_2['open'])
                
                if displacement:
                    # Found a valid demand zone
                    bullish_ob = {
                        'top': curr['high'], 
                        'bottom': curr['low'], 
                        'time': curr['time']
                    }
                    break # Use the most recent one

            # --- BEARISH OB (Buy before Sell) ---
            # 1. Bullish Candle (Up)
            # 2. Followed by aggressive displacement down
            if curr['close'] > curr['open']: # Green Candle
                displacement = (next_1['close'] < curr['low']) or \
                               (next_2['close'] < curr['low'] and next_2['close'] < next_2['open'])
                
                if displacement:
                    # Found a valid supply zone
                    bearish_ob = {
                        'top': curr['high'], 
                        'bottom': curr['low'], 
                        'time': curr['time']
                    }
                    break

        return bullish_ob, bearish_ob

    def check_signals_smc(self, symbol, bid, ask, candles):
        """
        SMC Strategy Implementation:
        1. STRUCTURE: Identify Trend via BOS (Break of Structure).
        2. AREA OF INTEREST: Wait for return to Order Block (OB) or FVG.
        3. ENTRY: Limit/Market execution on tap.
        """
        # 1. Determine Structure (The "Story" of price)
        structure = self.detect_market_structure(candles)
        
        # 2. Identify AOIs (Areas of Interest)
        bullish_ob, bearish_ob = self.calculate_order_blocks(candles)
        bullish_fvg, bearish_fvg = self.calculate_smc(candles)
        
        atr = self.calculate_atr(candles)
        current_price = (bid + ask) / 2
        
        # Get machine learning/algo confidence score as confluence (Reversal mode)
        conf, direction = self.get_prediction_score(symbol, bid, ask, candles, is_reversal=True)
        
        # --- BUY LOGIC (BULLISH STRUCTURE) ---
        if structure == "BULLISH":
            # Scenario A: Return to Bullish Order Block (Primary)
            if bullish_ob:
                # Price dipped into OB zone
                if bullish_ob['bottom'] <= ask <= (bullish_ob['top'] + atr*0.2):
                    if self._check_filters("BUY", ask):
                        sl = bullish_ob['bottom'] - (atr * 0.2) # Stop below OB
                        tp = ask + ((ask - sl) * 3.0) # 1:3 RR for OBs
                        logger.info(f"✅ BUY (SMC-OB) | Structure: Bullish | Tapped Order Block")
                        self.execute_trade("BUY", symbol, self.lot_size, "SMC_OB_BOS", sl, tp)
                        return

            # Scenario B: Return to Bullish FVG (Continuation)
            if bullish_fvg:
                low, high = bullish_fvg
                # Price dipped into FVG
                if low <= ask <= high:
                    if self._check_filters("BUY", ask):
                        sl = low - (atr * 0.5)
                        tp = ask + ((ask - sl) * 2.0)
                        logger.info(f"✅ BUY (SMC-FVG) | Structure: Bullish | Filled Imbalance")
                        self.execute_trade("BUY", symbol, self.lot_size, "SMC_FVG_BOS", sl, tp)

        # --- SELL LOGIC (BEARISH STRUCTURE) ---
        elif structure == "BEARISH":
            # Scenario A: Return to Bearish Order Block
            if bearish_ob:
                # Price rallied into OB zone
                if (bearish_ob['bottom'] - atr*0.2) <= bid <= bearish_ob['top']:
                    if self._check_filters("SELL", bid):
                        sl = bearish_ob['top'] + (atr * 0.2) # Stop above OB
                        tp = bid - ((sl - bid) * 3.0)
                        logger.info(f"✅ SELL (SMC-OB) | Structure: Bearish | Tapped Order Block")
                        self.execute_trade("SELL", symbol, self.lot_size, "SMC_OB_BOS", sl, tp)
                        return

            # Scenario B: Return to Bearish FVG
            if bearish_fvg:
                low, high = bearish_fvg
                if low <= bid <= high:
                    if self._check_filters("SELL", bid):
                        sl = high + (atr * 0.5)
                        tp = bid - ((sl - bid) * 2.0)
                        logger.info(f"✅ SELL (SMC-FVG) | Structure: Bearish | Filled Imbalance")
                        self.execute_trade("SELL", symbol, self.lot_size, "SMC_FVG_BOS", sl, tp)

    # =========================================================================
    # --- UPDATED: CANDLE RANGE THEORY (CRT) STRATEGY ---
    # =========================================================================

    def get_htf_structure(self, candles, timeframe_minutes=240):
        """
        Reconstructs the Previous Higher Timeframe (HTF) Candle from M5 data.
        Default: 240 minutes (4 Hours).
        Returns: (prev_high, prev_low, range_status)
        """
        if not candles or len(candles) < 20: 
            return None, None, "NO_DATA"

        # 1. Convert list of dicts to DataFrame for easy resampling
        df = pd.DataFrame(candles)
        # Ensure 'time' is datetime (MT5 sends epoch int)
        df['dt'] = pd.to_datetime(df['time'], unit='s')
        df.set_index('dt', inplace=True)

        # 2. Resample to HTF (e.g., 4H)
        # Logic: Aggregate 5m candles into 4h blocks
        htf_rule = f"{timeframe_minutes}min"
        htf_candles = df.resample(htf_rule).agg({
            'high': 'max',
            'low': 'min',
            'close': 'last',
            'open': 'first'
        }).dropna()

        # We need at least 2 completed HTF candles to identify the "Previous" range
        if len(htf_candles) < 2:
            return None, None, "INSUFFICIENT_DATA"

        # 3. Get the "Previous" completed HTF candle
        # [-1] is the current forming candle, [-2] is the last completed one
        prev_htf = htf_candles.iloc[-2]
        
        return prev_htf['high'], prev_htf['low'], "OK"

    def check_signals_crt(self, symbol, bid, ask, candles):
        """
        Candle Range Theory (CRT) - Fixed 'Missing Symbol' Error.
        """
        if len(candles) < 10: return
        
        # 1. Helper: Estimate Timeframe & Requirements
        ltf_mins = (candles[1]['time'] - candles[0]['time']) // 60
        if ltf_mins <= 0: ltf_mins = 5
        
        htf_minutes = getattr(self, 'crt_htf', 240)
        htf_label = "H4" if htf_minutes == 240 else "H1" if htf_minutes == 60 else f"{htf_minutes}m"
        
        needed_candles = (htf_minutes // ltf_mins) * 2
        if len(candles) < needed_candles: return

        # 2. Get HTF Range
        crt_high, crt_low, status = self.get_htf_structure(candles, htf_minutes)
        if status != "OK": return


        # 3. Parameters
        lookback = getattr(self, 'crt_lookback', 10)
        range_width = crt_high - crt_low
        if range_width <= 0: return 
        
        entry_threshold = range_width * getattr(self, 'crt_zone_size', 0.25) 
        atr = self.calculate_atr(candles)

        # -----------------------------------------------------------
        # SECURE LOGIC: Analyze PREVIOUS CLOSED CANDLE ([-2])
        # -----------------------------------------------------------
        last_closed = candles[-2]
        close_price = last_closed['close']
        open_price = last_closed['open']
        
        # Identify Candle Color
        is_red = close_price < open_price
        candle_color = "RED" if is_red else "GREEN"
        display_color = "255,69,0" if is_red else "0,255,0" 

        # --- PERIODIC RANGE SUMMARY ---
        if time.time() - self.last_crt_summary_time > 30:
            # Calculate HTF Age (how many minutes passed in the current HTF candle)
            last_time = candles[-1]['time']
            elapsed_mins = (last_time % (htf_minutes * 60)) // 60
            
            clr_ansi = "\033[91m" if is_red else "\033[92m"
            logger.info(f"📍 CRT {htf_label} [{int(elapsed_mins)}/{htf_minutes}m]: \033[91mHigh {crt_high:.2f}\033[0m | \033[92mLow {crt_low:.2f}\033[0m | Secure: {clr_ansi}{candle_color}\033[0m")
            self.last_crt_summary_time = time.time()

        # Scan recent history for the Sweep
        recent_history = candles[-(lookback+1):-1] 
        recent_lows = [c['low'] for c in recent_history]
        recent_highs = [c['high'] for c in recent_history]
        
        has_swept_low = min(recent_lows) < crt_low
        has_swept_high = max(recent_highs) > crt_high
        is_sweep_active = has_swept_low or has_swept_high

        # -----------------------------------------------------------
        # VISUAL UPDATE (Send to MT5)
        # -----------------------------------------------------------
        if time.time() - self.last_crt_draw > 5:
            # 1. Determine Box Color based on Sweep Status
            box_color = "64,224,208" # Turquoise (Default)
            if has_swept_high: box_color = "255,69,0" # Red
            elif has_swept_low: box_color = "0,255,0"  # Green

            # 2. Draw Range Box (Outline)
            self.connector.send_draw_command(f"CRT_BOX_{symbol}", crt_high, crt_low, 20, 0, box_color)
            
            # 3. Draw Level Lines (Red High, Green Low)
            self.connector.send_hline_command(f"CRT_HI_{symbol}", crt_high, "255,0,0", 2) # Solid Red
            self.connector.send_hline_command(f"CRT_LO_{symbol}", crt_low, "0,255,0", 2)  # Solid Green

            # 4. Draw Status Label
            status_tag = "SWEEP" if is_sweep_active else "MONITOR"
            lbl_text = f"CRT {htf_label} {status_tag} | Secure: {candle_color}"
            lbl_color = "0,255,0" if candle_color == "GREEN" else "255,69,0"
            self.connector.send_label_command(f"CRT_STATUS_{symbol}", lbl_text, lbl_color, 50)
            
            self.last_crt_draw = time.time()

        # 4. Small TF Prediction (Confirmation)
        # We pass is_reversal=True because CRT is a range reversal strategy.
        conf, direction = self.get_prediction_score(symbol, bid, ask, candles, is_reversal=True)
        if conf < 45: return # Slightly lower threshold allowed for HTF setups

        # --- BULLISH SETUP (Sweep Low -> Buy Reversal) ---
        if has_swept_low:
            # High TF Setup: Sweep occurred
            # Small TF Confirmation: Price reclaimed range AND LTF Prediction is Bullish AND candle is Green (Secure)
            is_reclaimed = close_price > crt_low
            in_range_buy = crt_low < ask < (crt_low + entry_threshold)
            is_secure = (candle_color == "GREEN")

            if is_reclaimed and in_range_buy and direction == "BUY" and is_secure:
                if self._check_filters("BUY", ask):
                    sweep_low = min(recent_lows)
                    sl = sweep_low - (atr * 0.2)
                    tp = crt_high 
                    
                    if (tp - ask) > (ask - sl):
                        logger.info(f"✅ BUY (CRT) | Secure: {candle_color} | {htf_label} Reclaim")
                        self.execute_trade("BUY", symbol, self.lot_size, f"CRT_RANGE_{htf_label}", sl, tp)
                    else:
                        self._log_crt_diag(f"CRT Skip: RR ratio < 1 ({tp-ask:.5f} vs {ask-sl:.5f})")
            else:
                if time.time() - self.last_crt_diag_time > 10:
                    status = "Reclaimed" if is_reclaimed else "Below Range"
                    zone = "In Entry Zone" if in_range_buy else "Outside Entry Zone"
                    self._log_crt_diag(f"⏳ CRT BULLish Setup: {status} | {zone} | Conf: {conf}%")

        # --- BEARISH SETUP (Sweep High -> Sell Reversal) ---
        elif has_swept_high:
            # High TF Setup: Sweep occurred
            # Small TF Confirmation: Price reclaimed range AND LTF Prediction is Bearish AND candle is Red (Secure)
            is_reclaimed = close_price < crt_high
            in_range_sell = (crt_high - entry_threshold) < bid < crt_high
            is_secure = (candle_color == "RED")

            if is_reclaimed and in_range_sell and direction == "SELL" and is_secure:
                if self._check_filters("SELL", bid):
                    sweep_high = max(recent_highs)
                    sl = sweep_high + (atr * 0.2)
                    tp = crt_low 
                    
                    if (bid - tp) > (sl - bid):
                        logger.info(f"✅ SELL (CRT) | Secure: {candle_color} | {htf_label} Reclaim")
                        self.execute_trade("SELL", symbol, self.lot_size, f"CRT_RANGE_{htf_label}", sl, tp)
                    else:
                        self._log_crt_diag(f"CRT Skip: RR ratio < 1 ({bid-tp:.5f} vs {sl-bid:.5f})")
            else:
                if time.time() - self.last_crt_diag_time > 10:
                    status = "Reclaimed" if is_reclaimed else "Above Range"
                    zone = "In Entry Zone" if in_range_sell else "Outside Entry Zone"
                    self._log_crt_diag(f"⏳ CRT BEARish Setup: {status} | {zone} | Conf: {conf}%")

        # --- MONITORING (No active sweep) ---
        else:
            if time.time() - self.last_crt_diag_time > 20:
                self._log_crt_diag(f"Monitoring... Range is safe. Waiting for High/Low Sweep.")

    def _log_crt_diag(self, message):
        """Dedicated throttled logger for CRT conditions to avoid flooding."""
        if time.time() - self.last_crt_diag_time > 12:
            # We don't have server_time_str here easily, but we can pass it if needed. 
            # For now, CRT H1 Range already has it.
            logger.info(f"🔎 {message}")
            self.last_crt_diag_time = time.time()

    def get_session_times(self):
        """Returns a string description of current session times for the UI."""
        results = []
        for name, config in self.SESSIONS.items():
            tz = ZoneInfo(config['tz'])
            now = datetime.now(tz)
            results.append(f"{name}: {now.strftime('%H:%M')}")
        return " | ".join(results)

    def _log_skip(self, message):
        if time.time() - self.last_log_time > 15:
            logger.info(f"❌ {message}")
            self.last_log_time = time.time()

    def analyze_trend(self, candles):
        try:
            df = pd.DataFrame(candles)
            # Chronological order guaranteed by standardized on_tick
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
        
        # 1. Break-Even Protection (NEW)
        # If we hit 50% of our target, we move SL to entry so we can't lose money anymore.
        if not self.break_even_active and self.current_profit >= self.break_even_activation:
            logger.info(f"🛡️ BREAK-EVEN ACTIVATED: Profit ${self.current_profit:.2f}. Locking in position.")
            self.break_even_active = True
            # Note: Actual MT5 SL modification would happen here if we had position tickets.
            # For now, we logically mark it as 'safe'.

        # 2. Take Profit Target
        if self.current_profit >= self.min_profit_target:
            logger.info(f"💰 TARGET HIT: ${self.current_profit:.2f}. Closing...")
            self.connector.close_profit(symbol)
            self.break_even_active = False