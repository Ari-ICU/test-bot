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
        # Available Modes: 
        # "ZONE_BOUNCE", "MACD_RSI", "BOLLINGER", "EMA_CROSS", "SMC", "CRT"
        # "STOCHASTIC", "ICHIMOKU", "PRICE_ACTION"
        # "MASTER_CONFLUENCE" (Combines All)
        self.strategy_mode = "MASTER_CONFLUENCE" 
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
        self.time_zone = "Auto" 
        self.start_hour = 8   
        self.end_hour = 20    

        # --- PROFIT SETTINGS ---
        self.use_profit_management = True
        self.min_profit_target = 0.10    
        
        # --- INDICATOR SETTINGS ---
        # RSI
        self.rsi_period = 14
        self.rsi_buy_threshold = 40      
        self.rsi_sell_threshold = 60     
        
        # MACD
        self.macd_fast = 12
        self.macd_slow = 26
        self.macd_signal = 9
        
        # Bollinger
        self.bb_period = 20
        self.bb_dev = 2.0
        
        # EMA
        self.ema_fast = 9
        self.ema_slow = 21

        # NEW: Stochastic
        self.stoch_k = 14
        self.stoch_d = 3
        self.stoch_overbought = 80
        self.stoch_oversold = 20

        # NEW: Ichimoku
        self.ichi_tenkan = 9
        self.ichi_kijun = 26
        self.ichi_senkou_b = 52

        # NEW: ADX (Trend Strength)
        self.adx_period = 14

        # CRT Settings
        self.crt_htf = 240
        self.crt_zone_size = 0.50 

        # --- State ---
        self.last_trade_time = 0         
        self.last_log_time = 0           
        self.last_status_time = 0        
        self.last_crt_diag_time = 0      
        self.last_crt_draw = 0           
        self.last_crt_summary_time = 0   
        self.last_hist_req = 0           
        self.trend = "NEUTRAL"
        self.active_session_name = "None"
        self.swing_highs = []  
        self.swing_lows = []
        
        # --- S&R Zones ---
        self.support_zones = []     
        self.resistance_zones = []
        self.zone_min_touches = 1   
        self.zone_tolerance = 0.0   
        self.last_draw_time = 0     

        self.current_profit = 0.0 
        self.peak_profit = 0.0        
        self.last_profit_close_time = 0
        self.profit_close_interval = 1 
        
        # --- TRADE PROTECTION ---
        self.break_even_activation = 0.50  
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
        self.trend = "NEUTRAL"
        self.support_zones = []
        self.resistance_zones = []
        self.peak_profit = 0.0
        logging.info("Strategy state reset for new symbol.")

    def on_tick(self, symbol, bid, ask, balance, profit, acct_name, positions, buy_count, sell_count, avg_entry, candles=None):
        current_time = time.time()
        
        server_time_str = "??:??:??"
        if candles and len(candles) > 0:
            server_time_str = datetime.fromtimestamp(candles[-1]['time']).strftime('%H:%M:%S')

        # 0. Data Validation & Automated History Fetching
        # Master Confluence/CRT need more data
        min_needed = 300 
        
        if not candles or len(candles) < min_needed:
            if current_time - self.last_hist_req > 5:
                self.connector.request_history(symbol, min_needed + 50)
                self.last_hist_req = current_time
                logging.info(f"Requesting {min_needed + 50} candles for {symbol}...")
            if candles and len(candles) > 0:
                self._log_skip(f"Gathering data... ({len(candles)}/{min_needed} candles)")
            return

        # Standardize to [Oldest, ..., Newest]
        if candles[0]['time'] > candles[-1]['time']:
            candles = candles[::-1]
        
        self.current_profit = profit 

        if positions > 0:
            if profit > self.peak_profit: self.peak_profit = profit
        else:
            self.peak_profit = 0.0

        # --- 1. GLOBAL ANALYSIS (Structure & Trend) ---
        if self.use_zone_filter: 
            self.analyze_structure_zones(symbol, candles)
            
        if self.use_trend_filter: 
            self.analyze_trend(candles)

        # --- 2. STRATEGY ROUTING ---
        if self.active and positions < self.max_positions:
            if (time.time() - self.last_trade_time) > self.trade_cooldown:
                
                mode = self.strategy_mode
                
                # --- ORIGINAL MODES ---
                if mode == "ZONE_BOUNCE":
                    self.check_signals_zone_bounce(symbol, bid, ask, candles)
                elif mode == "MACD_RSI":
                    self.check_signals_macd_rsi(symbol, bid, ask, candles)
                elif mode == "BOLLINGER":
                    self.check_signals_bollinger(symbol, bid, ask, candles)
                elif mode == "EMA_CROSS":
                    self.check_signals_ema_cross(symbol, bid, ask, candles)
                elif mode == "SMC":
                    self.check_signals_smc(symbol, bid, ask, candles)
                elif mode == "CRT":
                    self.check_signals_crt(symbol, bid, ask, candles)
                
                # --- NEW FOREX MODES ---
                elif mode == "STOCHASTIC":
                    self.check_signals_stochastic(symbol, bid, ask, candles)
                elif mode == "ICHIMOKU":
                    self.check_signals_ichimoku(symbol, bid, ask, candles)
                elif mode == "PRICE_ACTION":
                    self.check_signals_price_action(symbol, bid, ask, candles)
                
                # --- MASTER COMBINED MODE ---
                elif mode == "MASTER_CONFLUENCE":
                    self.check_signals_master_confluence(symbol, bid, ask, candles)

        # 3. Status Dashboard (Every 10 seconds)
        if current_time - self.last_status_time >= 10:
            self.last_status_time = current_time
            conf_score, conf_txt = self.get_prediction_score(symbol, bid, ask, candles)
            
            near_supp = self._get_nearest_zone(bid, is_support=True)
            s_val = f"{near_supp['top']:.2f}" if near_supp else "None"
            
            active_txt = "AUTO-ON" if self.active else "AUTO-OFF"
            logger.info(f"📊 [MT5:{server_time_str}] {active_txt} | {symbol} | Mode: {self.strategy_mode} | S: {s_val} | Conf: {conf_score}% | PnL: {profit:.2f}")

        # 4. Manage Profit 
        if positions > 0 and self.use_profit_management:
            self.check_and_close_profit(symbol)

    # =========================================================================
    # --- HELPER CALCULATIONS ---
    # =========================================================================

    def calculate_atr(self, candles, window=14):
        try:
            if len(candles) < window + 1: return 0.0
            df = pd.DataFrame(candles)
            high_low = df['high'] - df['low']
            high_pc = (df['high'] - df['close'].shift(1)).abs()
            low_pc = (df['low'] - df['close'].shift(1)).abs()
            tr = pd.concat([high_low, high_pc, low_pc], axis=1).max(axis=1)
            atr = tr.rolling(window=window).mean().iloc[-1]
            return float(atr)
        except: return 0.0

    def calculate_indicators(self, candles):
        try:
            df = pd.DataFrame(candles)
            delta = df['close'].diff()
            gain = (delta.where(delta > 0, 0)).rolling(window=self.rsi_period).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(window=self.rsi_period).mean()
            rs = gain / loss
            df['rsi'] = 100 - (100 / (1 + rs))

            short_ema = df['close'].ewm(span=self.macd_fast, adjust=False).mean()
            long_ema = df['close'].ewm(span=self.macd_slow, adjust=False).mean()
            df['macd'] = short_ema - long_ema
            df['macd_signal'] = df['macd'].ewm(span=self.macd_signal, adjust=False).mean()

            last = df.iloc[-1] 
            return last['rsi'], last['macd'], last['macd_signal']
        except: return 50, 0, 0

    def calculate_stochastic(self, candles):
        try:
            df = pd.DataFrame(candles)
            low_min = df['low'].rolling(window=self.stoch_k).min()
            high_max = df['high'].rolling(window=self.stoch_k).max()
            
            df['k_percent'] = 100 * ((df['close'] - low_min) / (high_max - low_min))
            df['d_percent'] = df['k_percent'].rolling(window=self.stoch_d).mean()
            
            return df.iloc[-1]['k_percent'], df.iloc[-1]['d_percent']
        except: return 50, 50

    def calculate_adx(self, candles):
        try:
            df = pd.DataFrame(candles)
            df['up_move'] = df['high'] - df['high'].shift(1)
            df['down_move'] = df['low'].shift(1) - df['low']
            
            df['plus_dm'] = np.where((df['up_move'] > df['down_move']) & (df['up_move'] > 0), df['up_move'], 0)
            df['minus_dm'] = np.where((df['down_move'] > df['up_move']) & (df['down_move'] > 0), df['down_move'], 0)
            
            h_l = df['high'] - df['low']
            h_pc = (df['high'] - df['close'].shift(1)).abs()
            l_pc = (df['low'] - df['close'].shift(1)).abs()
            df['tr'] = pd.concat([h_l, h_pc, l_pc], axis=1).max(axis=1)
            
            window = self.adx_period
            df['tr_smooth'] = df['tr'].rolling(window).sum()
            df['plus_di'] = 100 * (df['plus_dm'].rolling(window).sum() / df['tr_smooth'])
            df['minus_di'] = 100 * (df['minus_dm'].rolling(window).sum() / df['tr_smooth'])
            
            df['dx'] = 100 * abs(df['plus_di'] - df['minus_di']) / (df['plus_di'] + df['minus_di'])
            df['adx'] = df['dx'].rolling(window).mean()
            
            return df.iloc[-1]['adx']
        except: return 0

    def calculate_ichimoku(self, candles):
        try:
            df = pd.DataFrame(candles)
            nine_high = df['high'].rolling(window=self.ichi_tenkan).max()
            nine_low = df['low'].rolling(window=self.ichi_tenkan).min()
            df['tenkan'] = (nine_high + nine_low) / 2
            
            twenty_six_high = df['high'].rolling(window=self.ichi_kijun).max()
            twenty_six_low = df['low'].rolling(window=self.ichi_kijun).min()
            df['kijun'] = (twenty_six_high + twenty_six_low) / 2
            
            df['span_a'] = ((df['tenkan'] + df['kijun']) / 2).shift(self.ichi_kijun)
            
            fifty_two_high = df['high'].rolling(window=self.ichi_senkou_b).max()
            fifty_two_low = df['low'].rolling(window=self.ichi_senkou_b).min()
            df['span_b'] = ((fifty_two_high + fifty_two_low) / 2).shift(self.ichi_kijun)
            
            curr = df.iloc[-1]
            return curr['tenkan'], curr['kijun'], curr['span_a'], curr['span_b'], curr['close']
        except: return 0,0,0,0,0

    def detect_candle_patterns(self, candles):
        if len(candles) < 3: return "NONE"
        c1 = candles[-2] # Previous
        c2 = candles[-1] # Current
        
        # Bullish Engulfing
        if c1['close'] < c1['open'] and c2['close'] > c2['open']:
            if c2['close'] > c1['open'] and c2['open'] < c1['close']:
                return "BULLISH_ENGULFING"

        # Bearish Engulfing
        if c1['close'] > c1['open'] and c2['close'] < c2['open']:
            if c2['close'] < c1['open'] and c2['open'] > c1['close']:
                return "BEARISH_ENGULFING"
        
        # Hammer
        body = abs(c2['close'] - c2['open'])
        lower_wick = min(c2['close'], c2['open']) - c2['low']
        upper_wick = c2['high'] - max(c2['close'], c2['open'])
        if lower_wick > (body * 2) and upper_wick < body:
            return "HAMMER"

        # Shooting Star
        if upper_wick > (body * 2) and lower_wick < body:
            return "SHOOTING_STAR"

        return "NONE"

    # =========================================================================
    # --- NEW STRATEGIES ---
    # =========================================================================

    def check_signals_stochastic(self, symbol, bid, ask, candles):
        k, d = self.calculate_stochastic(candles)
        
        if k < self.stoch_oversold and d < self.stoch_oversold and k > d:
            if self._check_filters("BUY", ask):
                sl, tp = self.calculate_safe_risk("BUY", ask, candles)
                logger.info(f"✅ BUY (STOCH) | K: {k:.1f} / D: {d:.1f}")
                self.execute_trade("BUY", symbol, self.lot_size, "STOCHASTIC", sl, tp)

        elif k > self.stoch_overbought and d > self.stoch_overbought and k < d:
            if self._check_filters("SELL", bid):
                sl, tp = self.calculate_safe_risk("SELL", bid, candles)
                logger.info(f"✅ SELL (STOCH) | K: {k:.1f} / D: {d:.1f}")
                self.execute_trade("SELL", symbol, self.lot_size, "STOCHASTIC", sl, tp)

    def check_signals_ichimoku(self, symbol, bid, ask, candles):
        tenkan, kijun, span_a, span_b, price = self.calculate_ichimoku(candles)
        
        above_cloud = price > max(span_a, span_b)
        below_cloud = price < min(span_a, span_b)
        tk_cross_bull = tenkan > kijun
        tk_cross_bear = tenkan < kijun
        
        if above_cloud and tk_cross_bull:
            if self._check_filters("BUY", ask):
                sl, tp = self.calculate_safe_risk("BUY", ask, candles)
                logger.info(f"✅ BUY (ICHIMOKU) | Above Cloud + TK Cross")
                self.execute_trade("BUY", symbol, self.lot_size, "ICHIMOKU", sl, tp)

        elif below_cloud and tk_cross_bear:
            if self._check_filters("SELL", bid):
                sl, tp = self.calculate_safe_risk("SELL", bid, candles)
                logger.info(f"✅ SELL (ICHIMOKU) | Below Cloud + TK Cross")
                self.execute_trade("SELL", symbol, self.lot_size, "ICHIMOKU", sl, tp)

    def check_signals_price_action(self, symbol, bid, ask, candles):
        pattern = self.detect_candle_patterns(candles)
        
        if pattern == "BULLISH_ENGULFING" or pattern == "HAMMER":
            if self._check_filters("BUY", ask):
                sl, tp = self.calculate_safe_risk("BUY", ask, candles)
                logger.info(f"✅ BUY (PRICE ACTION) | Pattern: {pattern}")
                self.execute_trade("BUY", symbol, self.lot_size, "PA_" + pattern, sl, tp)
                
        elif pattern == "BEARISH_ENGULFING" or pattern == "SHOOTING_STAR":
            if self._check_filters("SELL", bid):
                sl, tp = self.calculate_safe_risk("SELL", bid, candles)
                logger.info(f"✅ SELL (PRICE ACTION) | Pattern: {pattern}")
                self.execute_trade("SELL", symbol, self.lot_size, "PA_" + pattern, sl, tp)

    # =========================================================================
    # --- MASTER CONFLUENCE STRATEGY (Combines Everything) ---
    # =========================================================================
    
    def check_signals_master_confluence(self, symbol, bid, ask, candles):
        buy_score = 0
        sell_score = 0
        reasons = []

        # 1. Indicator Layer
        rsi, macd, sig = self.calculate_indicators(candles)
        k, d = self.calculate_stochastic(candles)
        adx = self.calculate_adx(candles)
        tenkan, kijun, span_a, span_b, price = self.calculate_ichimoku(candles)
        
        # RSI Votes
        if rsi < 40: buy_score += 1
        elif rsi > 60: sell_score += 1
        
        # MACD Votes
        if macd > sig: buy_score += 1
        else: sell_score += 1
        
        # Stochastic Votes
        if k < 25 and k > d: buy_score += 1; reasons.append("StochOvS")
        if k > 75 and k < d: sell_score += 1; reasons.append("StochOvB")
        
        # Ichimoku Votes
        if price > span_a and price > span_b: buy_score += 1
        if price < span_a and price < span_b: sell_score += 1
        
        # 2. Price Action / Structure Layer
        pattern = self.detect_candle_patterns(candles)
        if "BULLISH" in pattern or pattern == "HAMMER": buy_score += 2; reasons.append(pattern)
        if "BEARISH" in pattern or pattern == "SHOOTING_STAR": sell_score += 2; reasons.append(pattern)
        
        structure = self.detect_market_structure(candles) 
        if structure == "BULLISH": buy_score += 1
        elif structure == "BEARISH": sell_score += 1
        
        # 3. Trend Filter Layer
        if adx > 25:
            if self.trend == "BULLISH_STRONG": buy_score += 1
            if self.trend == "BEARISH_STRONG": sell_score += 1

        # 4. Zone Filter
        nearest_supp = self._get_nearest_zone(bid, is_support=True)
        nearest_res = self._get_nearest_zone(bid, is_support=False)
        atr = self.calculate_atr(candles)
        
        if nearest_supp and (bid - nearest_supp['top']) < atr: buy_score += 2; reasons.append("SuppBounce")
        if nearest_res and (nearest_res['bottom'] - bid) < atr: sell_score += 2; reasons.append("ResReject")

        # --- EXECUTION LOGIC ---
        THRESHOLD = 4 
        
        if buy_score >= THRESHOLD and buy_score > sell_score:
            if self._check_filters("BUY", ask):
                sl, tp = self.calculate_safe_risk("BUY", ask, candles)
                reason_str = ",".join(reasons)
                logger.info(f"🌟 BUY (MASTER) | Score: {buy_score} | Reasons: {reason_str}")
                self.execute_trade("BUY", symbol, self.lot_size, "MASTER_CONFLUENCE", sl, tp)

        elif sell_score >= THRESHOLD and sell_score > buy_score:
            if self._check_filters("SELL", bid):
                sl, tp = self.calculate_safe_risk("SELL", bid, candles)
                reason_str = ",".join(reasons)
                logger.info(f"🌟 SELL (MASTER) | Score: {sell_score} | Reasons: {reason_str}")
                self.execute_trade("SELL", symbol, self.lot_size, "MASTER_CONFLUENCE", sl, tp)

    # =========================================================================
    # --- STRUCTURE / ZONES / CRT HELPERS ---
    # =========================================================================

    def analyze_structure_zones(self, symbol, candles):
        if not candles: return
        ts_candles = candles
        current_price = ts_candles[-1]['close']
        self.zone_tolerance = current_price * 0.0005 

        highs, lows = self._get_fractals(ts_candles)
        all_swings = highs + lows
        zones = self._cluster_levels(all_swings, threshold=self.zone_tolerance)
        
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

        # VISUALIZE ZONES (RESTORED)
        if time.time() - self.last_draw_time > 5.0:
            self._draw_zones(symbol)
            self.last_draw_time = time.time()

    def _draw_zones(self, symbol):
        # Sends draw commands to MT5 for visual debugging
        for i, zone in enumerate(self.support_zones[:3]):
            name = f"Supp_{i}"
            self.connector.send_draw_command(name, zone['top'], zone['bottom'], 100, 0, "0x008000") 

        for i, zone in enumerate(self.resistance_zones[:3]):
            name = f"Res_{i}"
            self.connector.send_draw_command(name, zone['top'], zone['bottom'], 100, 0, "0x000080") 

    def _get_fractals(self, candles, window=2):
        highs = []
        lows = []
        if len(candles) < (window * 2 + 1): return [], []
        for i in range(window, len(candles) - window - 1):
            curr = candles[i]
            is_high = True
            for j in range(1, window + 1):
                if candles[i-j]['high'] > curr['high'] or candles[i+j]['high'] > curr['high']:
                    is_high = False; break
            if is_high: highs.append(curr['high'])

            is_low = True
            for j in range(1, window + 1):
                if candles[i-j]['low'] < curr['low'] or candles[i+j]['low'] < curr['low']:
                    is_low = False; break
            if is_low: lows.append(curr['low'])
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
        if current_cluster: zones.append(self._make_zone_dict(current_cluster))
        return zones

    def _make_zone_dict(self, cluster):
        return {'top': max(cluster), 'bottom': min(cluster), 'center': sum(cluster)/len(cluster), 'count': len(cluster)}

    def _get_nearest_zone(self, price, is_support):
        zones = self.support_zones if is_support else self.resistance_zones
        if not zones: return None
        return zones[0]

    def analyze_trend(self, candles):
        try:
            df = pd.DataFrame(candles)
            ema200 = df['close'].ewm(span=200, adjust=False).mean().iloc[-1]
            current = df['close'].iloc[-1]
            if current > ema200:
                self.trend = "BULLISH_STRONG" if current > (ema200 * 1.001) else "BULLISH_WEAK"
            else:
                self.trend = "BEARISH_STRONG" if current < (ema200 * 0.999) else "BEARISH_WEAK"
        except: self.trend = "NEUTRAL"

    # =========================================================================
    # --- ORIGINAL STRATEGIES (RESTORED FULLY) ---
    # =========================================================================

    def get_htf_structure(self, candles, timeframe_minutes=240):
        """Restored CRT Helper"""
        if not candles or len(candles) < 20: 
            return None, None, "NO_DATA"
        df = pd.DataFrame(candles)
        df['dt'] = pd.to_datetime(df['time'], unit='s')
        df.set_index('dt', inplace=True)
        htf_rule = f"{timeframe_minutes}min"
        htf_candles = df.resample(htf_rule).agg({
            'high': 'max', 'low': 'min', 'close': 'last', 'open': 'first'
        }).dropna()
        if len(htf_candles) < 2: return None, None, "INSUFFICIENT_DATA"
        prev_htf = htf_candles.iloc[-2]
        return prev_htf['high'], prev_htf['low'], "OK"

    def check_signals_crt(self, symbol, bid, ask, candles):
        """Restored Full CRT Logic"""
        if len(candles) < 10: return
        ltf_mins = (candles[1]['time'] - candles[0]['time']) // 60
        if ltf_mins <= 0: ltf_mins = 5
        htf_minutes = getattr(self, 'crt_htf', 240)
        htf_label = "H4" if htf_minutes == 240 else f"{htf_minutes}m"
        needed = (htf_minutes // ltf_mins) * 2
        if len(candles) < needed: return

        crt_high, crt_low, status = self.get_htf_structure(candles, htf_minutes)
        if status != "OK": return

        lookback = 10
        range_width = crt_high - crt_low
        entry_threshold = range_width * getattr(self, 'crt_zone_size', 0.25)
        atr = self.calculate_atr(candles)
        last_closed = candles[-2]
        close_price = last_closed['close']
        open_price = last_closed['open']
        is_red = close_price < open_price
        candle_color = "RED" if is_red else "GREEN"

        # CRT Drawing Logic
        if time.time() - self.last_crt_draw > 5:
            self.connector.send_draw_command(f"CRT_BOX_{symbol}", crt_high, crt_low, 20, 0, "64,224,208")
            self.connector.send_hline_command(f"CRT_HI_{symbol}", crt_high, "255,0,0", 2) 
            self.connector.send_hline_command(f"CRT_LO_{symbol}", crt_low, "0,255,0", 2)
            self.last_crt_draw = time.time()

        recent_history = candles[-(lookback+1):-1]
        recent_lows = [c['low'] for c in recent_history]
        recent_highs = [c['high'] for c in recent_history]
        has_swept_low = min(recent_lows) < crt_low
        has_swept_high = max(recent_highs) > crt_high
        
        conf, direction = self.get_prediction_score(symbol, bid, ask, candles)
        if conf < 50: return

        if has_swept_low:
            is_reclaimed = close_price > crt_low
            in_range = crt_low < ask < (crt_low + entry_threshold)
            if is_reclaimed and in_range and direction == "BUY" and self._check_filters("BUY", ask):
                sl = min(recent_lows) - (atr * 0.2)
                tp = crt_high
                self.execute_trade("BUY", symbol, self.lot_size, f"CRT_RANGE_{htf_label}", sl, tp)

        elif has_swept_high:
            is_reclaimed = close_price < crt_high
            in_range = (crt_high - entry_threshold) < bid < crt_high
            if is_reclaimed and in_range and direction == "SELL" and self._check_filters("SELL", bid):
                sl = max(recent_highs) + (atr * 0.2)
                tp = crt_low
                self.execute_trade("SELL", symbol, self.lot_size, f"CRT_RANGE_{htf_label}", sl, tp)

    def check_signals_zone_bounce(self, symbol, bid, ask, candles):
        atr = self.calculate_atr(candles)
        if atr == 0: return
        nearest_supp = self._get_nearest_zone(bid, is_support=True)
        if nearest_supp:
            dist = bid - nearest_supp['top']
            if dist <= (atr * 1.5) and bid >= (nearest_supp['bottom'] - (atr * 0.5)):
                conf, dir = self.get_prediction_score(symbol, bid, ask, candles)
                if conf >= 60 and dir == "BUY" and self._check_filters("BUY", ask):
                    sl, tp = self.calculate_safe_risk("BUY", ask, candles)
                    self.execute_trade("BUY", symbol, self.lot_size, "ZONE_BOUNCE", sl, tp)
        nearest_res = self._get_nearest_zone(bid, is_support=False)
        if nearest_res:
            dist = nearest_res['bottom'] - bid
            if dist <= (atr * 1.5) and bid <= (nearest_res['top'] + (atr * 0.5)):
                conf, dir = self.get_prediction_score(symbol, bid, ask, candles)
                if conf >= 60 and dir == "SELL" and self._check_filters("SELL", bid):
                    sl, tp = self.calculate_safe_risk("SELL", bid, candles)
                    self.execute_trade("SELL", symbol, self.lot_size, "ZONE_BOUNCE", sl, tp)

    def check_signals_macd_rsi(self, symbol, bid, ask, candles):
        rsi, macd, macd_signal = self.calculate_indicators(candles)
        conf, dir = self.get_prediction_score(symbol, bid, ask, candles)
        if rsi < self.rsi_buy_threshold and macd > macd_signal and conf >= 50 and self._check_filters("BUY", ask):
            sl, tp = self.calculate_safe_risk("BUY", ask, candles)
            self.execute_trade("BUY", symbol, self.lot_size, "MACD_RSI", sl, tp)
        elif rsi > self.rsi_sell_threshold and macd < macd_signal and conf >= 50 and self._check_filters("SELL", bid):
            sl, tp = self.calculate_safe_risk("SELL", bid, candles)
            self.execute_trade("SELL", symbol, self.lot_size, "MACD_RSI", sl, tp)

    def check_signals_bollinger(self, symbol, bid, ask, candles):
        if len(candles) < 50: return
        df = pd.DataFrame(candles)
        df['sma'] = df['close'].rolling(20).mean()
        curr = df.iloc[-1]
        prev = df.iloc[-2]
        cross_up = prev['close'] < prev['sma'] and curr['close'] > curr['sma']
        cross_down = prev['close'] > prev['sma'] and curr['close'] < curr['sma']
        if cross_up and self._check_filters("BUY", ask):
             sl, tp = self.calculate_safe_risk("BUY", ask, candles)
             self.execute_trade("BUY", symbol, self.lot_size, "BB_RSI", sl, tp)
        elif cross_down and self._check_filters("SELL", bid):
             sl, tp = self.calculate_safe_risk("SELL", bid, candles)
             self.execute_trade("SELL", symbol, self.lot_size, "BB_RSI", sl, tp)

    def check_signals_ema_cross(self, symbol, bid, ask, candles):
        if len(candles) < 50: return
        df = pd.DataFrame(candles)
        df['fast'] = df['close'].ewm(span=self.ema_fast, adjust=False).mean()
        df['slow'] = df['close'].rolling(window=self.ema_slow).mean()
        curr = df.iloc[-1]
        if curr['fast'] > curr['slow'] and self._check_filters("BUY", ask):
             sl, tp = self.calculate_safe_risk("BUY", ask, candles)
             self.execute_trade("BUY", symbol, self.lot_size, "EMA_CROSS", sl, tp)
        elif curr['fast'] < curr['slow'] and self._check_filters("SELL", bid):
             sl, tp = self.calculate_safe_risk("SELL", bid, candles)
             self.execute_trade("SELL", symbol, self.lot_size, "EMA_CROSS", sl, tp)

    def check_signals_smc(self, symbol, bid, ask, candles):
        structure = self.detect_market_structure(candles)
        bullish_ob, bearish_ob = self.calculate_order_blocks(candles)
        atr = self.calculate_atr(candles)
        if structure == "BULLISH" and bullish_ob and self._check_filters("BUY", ask):
            if bullish_ob['bottom'] <= ask <= (bullish_ob['top'] + atr*0.2):
                sl, tp = self.calculate_safe_risk("BUY", ask, candles)
                self.execute_trade("BUY", symbol, self.lot_size, "SMC_OB", sl, tp)
        elif structure == "BEARISH" and bearish_ob and self._check_filters("SELL", bid):
            if (bearish_ob['bottom'] - atr*0.2) <= bid <= bearish_ob['top']:
                sl, tp = self.calculate_safe_risk("SELL", bid, candles)
                self.execute_trade("SELL", symbol, self.lot_size, "SMC_OB", sl, tp)

    def detect_market_structure(self, candles):
        if len(candles) < 50: return "NEUTRAL"
        highs, lows = self._get_fractals(candles, window=3)
        if not highs or not lows: return "NEUTRAL"
        current_close = candles[-1]['close']
        if current_close > highs[-1]: return "BULLISH"
        elif current_close < lows[-1]: return "BEARISH"
        return "NEUTRAL"

    def calculate_order_blocks(self, candles):
        if len(candles) < 20: return None, None
        bullish_ob, bearish_ob = None, None
        for i in range(len(candles) - 3, len(candles) - 30, -1):
            curr = candles[i]
            if curr['close'] < curr['open']: # Red
                if candles[i+1]['close'] > curr['high']:
                    bullish_ob = {'top': curr['high'], 'bottom': curr['low']}
                    break
        for i in range(len(candles) - 3, len(candles) - 30, -1):
            curr = candles[i]
            if curr['close'] > curr['open']: # Green
                if candles[i+1]['close'] < curr['low']:
                    bearish_ob = {'top': curr['high'], 'bottom': curr['low']}
                    break
        return bullish_ob, bearish_ob

    # =========================================================================
    # --- FILTERS & UTILS ---
    # =========================================================================

    def get_prediction_score(self, symbol, bid, ask, candles):
        if not candles or len(candles) < 50: return 0, "No Data"
        rsi, macd, macd_sig = self.calculate_indicators(candles)
        buy_strength = 0
        sell_strength = 0
        
        if rsi < 50: buy_strength += 20
        else: sell_strength += 20
        
        if macd > macd_sig: buy_strength += 20
        else: sell_strength += 20
        
        if "BULLISH" in self.trend: buy_strength += 20
        elif "BEARISH" in self.trend: sell_strength += 20

        if buy_strength >= sell_strength: return buy_strength, "BUY"
        else: return sell_strength, "SELL"

    def _is_trading_time(self):
        if not self.use_time_filter: return True
        try:
            if self.time_zone == "Auto":
                active_session = None
                active_any = False
                for session_name, config in self.SESSIONS.items():
                    tz = ZoneInfo(config['tz'])
                    now = datetime.now(tz)
                    hour = now.hour
                    start, end = config['start'], config['end']
                    is_active = False
                    if start <= end:
                        if start <= hour < end: is_active = True
                    else: 
                        if hour >= start or hour < end: is_active = True
                    if is_active:
                        active_session = session_name
                        active_any = True
                        break
                self.active_session_name = active_session if active_session else "Closed"
                return active_any

            tz_map = {"London": "Europe/London", "New York": "America/New_York", "Tokyo": "Asia/Tokyo", "Sydney": "Australia/Sydney"}
            if self.time_zone in tz_map:
                now = datetime.now(ZoneInfo(tz_map[self.time_zone]))
            else:
                now = datetime.now()
            
            curr_hour = now.hour
            if self.start_hour <= self.end_hour:
                return self.start_hour <= curr_hour < self.end_hour
            else:
                return curr_hour >= self.start_hour or curr_hour < self.end_hour
        except: return True

    def _check_filters(self, direction, current_price):
        if self.news_engine and self.news_engine.trading_pause:
            self._log_skip("News Filter: Trading is currently PAUSED due to high-impact news.")
            return False
        if not self._is_trading_time():
            self._log_skip(f"Time Filter: Outside trading hours.")
            return False
        if self.use_zone_filter:
            if direction == "BUY":
                nearest_res = self._get_nearest_zone(current_price, is_support=False)
                if nearest_res and (nearest_res['bottom'] - current_price) < (self.zone_tolerance * 0.5): 
                    return False
            if direction == "SELL":
                nearest_supp = self._get_nearest_zone(current_price, is_support=True)
                if nearest_supp and (current_price - nearest_supp['top']) < (self.zone_tolerance * 0.5):
                    return False
        if self.use_trend_filter and self.strategy_mode != "MASTER_CONFLUENCE":
             if direction == "BUY" and "BEARISH" in self.trend: return False
             if direction == "SELL" and "BULLISH" in self.trend: return False
        return True

    def _log_skip(self, message):
        if time.time() - self.last_log_time > 15:
            logger.info(f"❌ {message}")
            self.last_log_time = time.time()

    def calculate_safe_risk(self, direction, entry_price, candles):
        atr = self.calculate_atr(candles)
        if atr == 0: atr = entry_price * 0.001
        sl_dist = atr * 2.0
        
        if direction == "BUY":
            nearest_supp = self._get_nearest_zone(entry_price, is_support=True)
            if nearest_supp and (entry_price - nearest_supp['bottom']) < (sl_dist * 1.5):
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
        
        if not self.break_even_active and self.current_profit >= self.break_even_activation:
            logger.info(f"🛡️ BREAK-EVEN ACTIVATED: Profit ${self.current_profit:.2f}. Locking in position.")
            self.break_even_active = True

        if self.current_profit >= self.min_profit_target:
            logger.info(f"💰 TARGET HIT: ${self.current_profit:.2f}. Closing...")
            self.connector.close_profit(symbol)
            self.break_even_active = False