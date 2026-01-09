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
        self.strategy_mode = "MACD_RSI" 
        self.use_trend_filter = True
        self.use_zone_filter = True

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
        
        # --- Auto-Detected Range & Zones ---
        self.price_min = 0.0  # Support
        self.price_max = 0.0  # Resistance
        self.equilibrium = 0.0 

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

    def on_tick(self, symbol, bid, ask, balance, profit, acct_name, positions, buy_count, sell_count, avg_entry, candles=None):
        if not candles or len(candles) < 200: return
        self.current_profit = profit 

        # --- Track Peak Profit ---
        if positions > 0:
            if profit > self.peak_profit: self.peak_profit = profit
        else:
            self.peak_profit = 0.0

        # --- 1. PRIORITY: Analyze Structure & Trend ---
        if self.use_zone_filter: self.analyze_structure(symbol, candles)
        if self.use_trend_filter: self.analyze_trend(candles)

        # --- 2. Check Signals based on Selected Mode ---
        if self.active and positions < self.max_positions:
            if (time.time() - self.last_trade_time) > self.trade_cooldown:
                
                # Mode Dispatcher
                if self.strategy_mode == "MACD_RSI":
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

        # 4. Status Log
        if time.time() % 10 < 1: 
            zone_txt = f"Zone: {self.price_min:.2f}-{self.price_max:.2f}" if self.use_zone_filter else "Zone: OFF"
            trend_txt = f"Trend: {self.trend}" if self.use_trend_filter else "Trend: OFF"
            logger.info(f"Status: {symbol} | Mode: {self.strategy_mode} | {zone_txt} | {trend_txt} | PnL: {profit:.2f}")

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
        """Detects the latest Fair Value Gap (FVG)."""
        try:
            # We look at the last few candles (3-candle formation)
            # FVG is formed by Candle i-2 and i. Candle i-1 is the impulsive move.
            # We scan the last 5 candles to find a recent open FVG.
            bullish_fvg = None
            bearish_fvg = None
            
            # Iterate backwards from current closed candle (-2)
            # Indices: -2=LatestClosed, -3=Prev, -4=PrevPrev
            for i in range(-2, -6, -1):
                try:
                    c3 = candles[i]     # Current (right)
                    # c2 = candles[i-1] # Middle (impulse)
                    c1 = candles[i-2]   # Left (start)

                    # Bullish FVG: Low of c3 > High of c1
                    if c3['low'] > c1['high']:
                        gap_size = c3['low'] - c1['high']
                        if gap_size > 0.0001: # Min filter
                            bullish_fvg = (c1['high'], c3['low']) # Zone
                            break # Use most recent

                    # Bearish FVG: High of c3 < Low of c1
                    if c3['high'] < c1['low']:
                        gap_size = c1['low'] - c3['high']
                        if gap_size > 0.0001:
                            bearish_fvg = (c3['high'], c1['low']) # Zone
                            break
                except IndexError: pass
            
            return bullish_fvg, bearish_fvg
        except: return None, None

    def _check_filters(self, direction, current_price):
        """Returns True if trade is allowed, False if blocked by filters."""
        # 1. Zone Filter (Buy Low / Sell High)
        if self.use_zone_filter and self.equilibrium > 0:
            if direction == "BUY" and current_price > self.equilibrium:
                if self.trend != "BULLISH_STRONG":
                    self._log_skip(f"Zone Filter: Price in Premium. Wait for Discount.")
                    return False
            if direction == "SELL" and current_price < self.equilibrium:
                if self.trend != "BEARISH_STRONG":
                    self._log_skip(f"Zone Filter: Price in Discount. Wait for Premium.")
                    return False

        # 2. Trend Filter (200 EMA)
        if self.use_trend_filter:
            if direction == "BUY" and "BEARISH" in self.trend:
                self._log_skip(f"Trend Filter: Trend is {self.trend}. No Buys.")
                return False
            if direction == "SELL" and "BULLISH" in self.trend:
                self._log_skip(f"Trend Filter: Trend is {self.trend}. No Sells.")
                return False
        
        return True

    def check_signals_macd_rsi(self, symbol, bid, ask, candles):
        rsi, macd, macd_signal = self.calculate_indicators(candles)
        
        if rsi < self.rsi_buy_threshold and macd > macd_signal:
            if self._check_filters("BUY", ask):
                sl, tp = self.calculate_safe_risk("BUY", ask)
                logger.info(f"✅ BUY (MACD) | RSI: {rsi:.1f}")
                self.execute_trade("BUY", symbol, self.lot_size, "MACD_RSI", sl, tp)

        elif rsi > self.rsi_sell_threshold and macd < macd_signal:
            if self._check_filters("SELL", bid):
                sl, tp = self.calculate_safe_risk("SELL", bid)
                logger.info(f"✅ SELL (MACD) | RSI: {rsi:.1f}")
                self.execute_trade("SELL", symbol, self.lot_size, "MACD_RSI", sl, tp)

    def check_signals_bollinger(self, symbol, bid, ask, candles):
        upper, lower, close = self.calculate_bollinger(candles)
        rsi, _, _ = self.calculate_indicators(candles)
        
        if close < lower and rsi < self.rsi_buy_threshold:
             if self._check_filters("BUY", ask):
                sl, tp = self.calculate_safe_risk("BUY", ask)
                logger.info(f"✅ BUY (BB) | Price < Lower | RSI: {rsi:.1f}")
                self.execute_trade("BUY", symbol, self.lot_size, "BB_RSI", sl, tp)
        
        elif close > upper and rsi > self.rsi_sell_threshold:
             if self._check_filters("SELL", bid):
                sl, tp = self.calculate_safe_risk("SELL", bid)
                logger.info(f"✅ SELL (BB) | Price > Upper | RSI: {rsi:.1f}")
                self.execute_trade("SELL", symbol, self.lot_size, "BB_RSI", sl, tp)

    def check_signals_ema_cross(self, symbol, bid, ask, candles):
        cross_up, cross_down = self.calculate_ema_cross(candles)
        
        if cross_up:
             if self._check_filters("BUY", ask):
                sl, tp = self.calculate_safe_risk("BUY", ask)
                logger.info(f"✅ BUY (EMA CROSS)")
                self.execute_trade("BUY", symbol, self.lot_size, "EMA_CROSS", sl, tp)
        
        elif cross_down:
             if self._check_filters("SELL", bid):
                sl, tp = self.calculate_safe_risk("SELL", bid)
                logger.info(f"✅ SELL (EMA CROSS)")
                self.execute_trade("SELL", symbol, self.lot_size, "EMA_CROSS", sl, tp)

    def check_signals_smc(self, symbol, bid, ask, candles):
        """SMC: Trade Retracements into FVG."""
        bullish_fvg, bearish_fvg = self.calculate_smc(candles)
        current_price = (bid + ask) / 2
        
        # Buy Signal: Price dips into Bullish FVG
        if bullish_fvg:
            low, high = bullish_fvg
            if low <= current_price <= high:
                if self._check_filters("BUY", ask):
                    sl, tp = self.calculate_safe_risk("BUY", ask)
                    logger.info(f"✅ BUY (SMC) | Inside Bullish FVG {low:.5f}-{high:.5f}")
                    self.execute_trade("BUY", symbol, self.lot_size, "SMC_FVG", sl, tp)

        # Sell Signal: Price rallies into Bearish FVG
        if bearish_fvg:
            low, high = bearish_fvg
            if low <= current_price <= high:
                if self._check_filters("SELL", bid):
                    sl, tp = self.calculate_safe_risk("SELL", bid)
                    logger.info(f"✅ SELL (SMC) | Inside Bearish FVG {low:.5f}-{high:.5f}")
                    self.execute_trade("SELL", symbol, self.lot_size, "SMC_FVG", sl, tp)

    def check_signals_crt(self, symbol, bid, ask, candles):
        """CRT: Candle Range Breakout (Continuation)."""
        if len(candles) < 3: return
        prev = candles[-2] # Last completed candle
        
        # Breakout Buy: Current Price > Prev High
        if ask > prev['high']:
            # Confirm with Trend
            if self._check_filters("BUY", ask):
                sl, tp = self.calculate_safe_risk("BUY", ask)
                logger.info(f"✅ BUY (CRT) | Breakout Prev High {prev['high']}")
                self.execute_trade("BUY", symbol, self.lot_size, "CRT_BREAK", sl, tp)

        # Breakout Sell: Current Price < Prev Low
        elif bid < prev['low']:
             if self._check_filters("SELL", bid):
                sl, tp = self.calculate_safe_risk("SELL", bid)
                logger.info(f"✅ SELL (CRT) | Breakout Prev Low {prev['low']}")
                self.execute_trade("SELL", symbol, self.lot_size, "CRT_BREAK", sl, tp)

    def _log_skip(self, message):
        if time.time() - self.last_log_time > 15:
            logger.info(f"❌ {message}")
            self.last_log_time = time.time()

    def analyze_structure(self, symbol, candles):
        """Auto-detects Support (Min) and Resistance (Max) from Swing Points."""
        swings = [] 
        lookback = min(len(candles) - 2, 50)
        
        for i in range(2, lookback): 
            c_curr = candles[i]
            c_prev = candles[i+1]
            c_next = candles[i-1]
            if c_curr['high'] > c_prev['high'] and c_curr['high'] > c_next['high']:
                swings.append({'type': 'H', 'price': c_curr['high']})
            elif c_curr['low'] < c_prev['low'] and c_curr['low'] < c_next['low']:
                swings.append({'type': 'L', 'price': c_curr['low']})

        self.swing_highs = [s for s in swings if s['type'] == 'H']
        self.swing_lows = [s for s in swings if s['type'] == 'L']

        # --- UPDATE ZONE ---
        if self.swing_highs: self.price_max = self.swing_highs[-1]['price']
        if self.swing_lows: self.price_min = self.swing_lows[-1]['price']
        if self.price_max > self.price_min:
            self.equilibrium = (self.price_max + self.price_min) / 2
        else: self.equilibrium = 0.0

    def analyze_trend(self, candles):
        """Simple Trend Filter using 200 EMA."""
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

    def calculate_safe_risk(self, direction, entry_price):
        sl = 0.0
        tp = 0.0
        is_gold = entry_price > 500
        min_dist = 2.00 if is_gold else 0.0020  
        
        if direction == "BUY":
            if self.swing_lows:
                last_low = self.swing_lows[-1]['price']
                if (entry_price - last_low) < min_dist: sl = entry_price - min_dist
                else: sl = last_low
            else:
                sl = entry_price - min_dist 
            tp = entry_price + ((entry_price - sl) * self.risk_reward_ratio)

        elif direction == "SELL":
            if self.swing_highs:
                last_high = self.swing_highs[-1]['price']
                if (last_high - entry_price) < min_dist: sl = entry_price + min_dist
                else: sl = last_high
            else:
                sl = entry_price + min_dist 
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

    def analyze_patterns(self, candles):
        return {'fvg_zone': None, 'bullish_fvg': False, 'bearish_fvg': False}