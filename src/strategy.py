import logging
import time
from datetime import datetime
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
        
        # --- PROFIT SETTINGS ---
        self.min_profit_target = 0.50    
        self.trailing_activation = 0.80  
        self.trailing_offset = 0.20      
        
        # --- NEW: Time Schedule ---
        self.trading_start_hour = 8
        self.trading_end_hour = 20

        # Indicator Settings
        self.rsi_period = 14
        self.rsi_buy_threshold = 40      
        self.rsi_sell_threshold = 60     
        
        self.macd_fast = 12
        self.macd_slow = 26
        self.macd_signal = 9
        
        # --- Execution Safety ---
        self.trade_cooldown = 15.0       
        self.last_trade_time = 0         
        self.last_log_time = 0           
        
        # --- State ---
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
        logger.info(f"Strategy ACTIVE | Target: ${self.min_profit_target} | Trail: ${self.trailing_activation}")

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
        self.analyze_structure(symbol, candles)
        self.analyze_trend(candles)

        # --- 2. Check Signals ---
        if self.active and positions < self.max_positions:
            if (time.time() - self.last_trade_time) > self.trade_cooldown:
                self.check_signals_macd_rsi(symbol, bid, ask, candles)

        # 3. Manage Profit 
        if positions > 0:
            self.check_and_close_profit(symbol)

        # 4. Status Log
        if time.time() % 10 < 1: 
            zone_info = f"{self.price_min:.2f}-{self.price_max:.2f}"
            eq_info = f"Eq: {self.equilibrium:.2f}"
            logger.info(f"Status: {symbol} | Zone: {zone_info} | {eq_info} | PnL: {profit:.2f}")

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
            logger.error(f"Indicator Error: {e}")
            return 50, 0, 0

    def calculate_safe_risk(self, direction, entry_price):
        sl = 0.0
        tp = 0.0
        is_gold = entry_price > 500
        min_dist = 2.00 if is_gold else 0.0020  
        
        if direction == "BUY":
            # SL below recent support
            if self.swing_lows:
                last_low = self.swing_lows[-1]['price']
                if (entry_price - last_low) < min_dist: sl = entry_price - min_dist
                else: sl = last_low
            else:
                sl = entry_price - min_dist 
            tp = entry_price + ((entry_price - sl) * self.risk_reward_ratio)

        elif direction == "SELL":
            # SL above recent resistance
            if self.swing_highs:
                last_high = self.swing_highs[-1]['price']
                if (last_high - entry_price) < min_dist: sl = entry_price + min_dist
                else: sl = last_high
            else:
                sl = entry_price + min_dist 
            tp = entry_price - ((sl - entry_price) * self.risk_reward_ratio)

        return float(sl), float(tp)

    def check_signals_macd_rsi(self, symbol, bid, ask, candles):
        current_price = (bid + ask) / 2
        
        # --- NEW: Check Time Schedule ---
        now_hour = datetime.now().hour
        # Logic to handle both standard (8-20) and overnight (22-5)
        if self.trading_start_hour < self.trading_end_hour:
             # Standard Day Range
             if not (self.trading_start_hour <= now_hour < self.trading_end_hour):
                 self._log_skip(f"Outside Trading Hours ({self.trading_start_hour}:00 - {self.trading_end_hour}:00)")
                 return
        else:
             # Overnight Range (e.g., Start 22, End 5)
             # Valid if >= 22 OR < 5
             if not (now_hour >= self.trading_start_hour or now_hour < self.trading_end_hour):
                 self._log_skip(f"Outside Trading Hours ({self.trading_start_hour}:00 - {self.trading_end_hour}:00)")
                 return

        # --- "Buy Low, Sell High" Logic (Premium vs Discount) ---
        if self.equilibrium > 0:
            if current_price > self.equilibrium:
                if self.trend != "BULLISH_STRONG": 
                    self._log_skip(f"Price {current_price:.2f} is in PREMIUM (> {self.equilibrium:.2f}). Wait for Discount to BUY.")
                    return 
            
            if current_price < self.equilibrium:
                if self.trend != "BEARISH_STRONG":
                    self._log_skip(f"Price {current_price:.2f} is in DISCOUNT (< {self.equilibrium:.2f}). Wait for Premium to SELL.")
                    return 

        # --- Indicator Logic ---
        rsi, macd, macd_signal = self.calculate_indicators(candles)
        
        # BUY SIGNAL
        if rsi < self.rsi_buy_threshold and macd > macd_signal:
            if self.trend == "BEARISH_STRONG":
                self._log_skip("Trend is Strong Bearish. Skipping Counter-Trend Buy.")
                return

            sl, tp = self.calculate_safe_risk("BUY", ask)
            logger.info(f"✅ BUY SIGNAL | Discount Zone Valid | RSI: {rsi:.1f}")
            self.execute_trade("BUY", symbol, self.lot_size, "MACD_RSI", sl, tp)

        # SELL SIGNAL
        elif rsi > self.rsi_sell_threshold and macd < macd_signal:
            if self.trend == "BULLISH_STRONG":
                self._log_skip("Trend is Strong Bullish. Skipping Counter-Trend Sell.")
                return

            sl, tp = self.calculate_safe_risk("SELL", bid)
            logger.info(f"✅ SELL SIGNAL | Premium Zone Valid | RSI: {rsi:.1f}")
            self.execute_trade("SELL", symbol, self.lot_size, "MACD_RSI", sl, tp)
        
        else:
            self._log_skip(f"No Signal | RSI: {rsi:.1f}")

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
        if self.swing_highs:
            self.price_max = self.swing_highs[-1]['price']
        
        if self.swing_lows:
            self.price_min = self.swing_lows[-1]['price']

        # Calculate Equilibrium (50% Retracement Level)
        if self.price_max > self.price_min:
            self.equilibrium = (self.price_max + self.price_min) / 2
        else:
            self.equilibrium = 0.0

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