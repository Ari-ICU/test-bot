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
        
        # --- STRATEGY CONFIGURATION (MACD & RSI) ---
        self.risk_reward_ratio = 2.0     # Target 2x Profit for every 1x Risk
        self.max_positions = 1           # Strict limit
        self.lot_size = config.get('auto_trading', {}).get('lot_size', 0.01)
        
        # Indicator Settings (From Video)
        self.rsi_period = 14
        self.rsi_buy_threshold = 40      # Video uses 40 for Buy
        self.rsi_sell_threshold = 60     # Video uses 60 for Sell
        
        self.macd_fast = 12
        self.macd_slow = 26
        self.macd_signal = 9
        
        # --- Execution Safety ---
        self.trade_cooldown = 15.0       # Wait 15s after a trade
        self.last_trade_time = 0         
        self.last_log_time = 0           
        
        # --- State ---
        self.trend = "NEUTRAL"
        self.swing_highs = []  
        self.swing_lows = []
        self.current_profit = 0.0 
        self.peak_profit = 0.0        
        self.last_profit_close_time = 0
        self.profit_close_interval = 1 

    def start(self):
        logger.info("Strategy ACTIVE | MACD & RSI Strategy | RR 1:2")

    def stop(self):
        self.active = False
        logger.info("Strategy PAUSED")

    def set_active(self, active):
        self.active = bool(active)
        state = "ACTIVE" if self.active else "PAUSED"
        logging.info(f"Strategy state set to: {state}")

    def on_tick(self, symbol, bid, ask, balance, profit, acct_name, positions, buy_count, sell_count, avg_entry, candles=None):
        if not candles or len(candles) < 50: return
        self.current_profit = profit 

        # --- Track Peak Profit ---
        if positions > 0:
            if profit > self.peak_profit: self.peak_profit = profit
        else:
            self.peak_profit = 0.0

        # --- 1. PRIORITY: Check Signals ---
        if self.active and positions < self.max_positions:
            if (time.time() - self.last_trade_time) > self.trade_cooldown:
                self.check_signals_macd_rsi(symbol, bid, ask, candles)

        # 2. Analyze Structure (For Stop Loss)
        self.analyze_structure(symbol, candles)

        # 3. Manage Profit (Trailing Stop)
        if positions > 0:
            self.check_and_close_profit(symbol)

        # 4. Status Log
        if time.time() % 10 < 1: 
            logger.info(f"Status: {symbol} | PnL: {profit:.2f} | Peak: {self.peak_profit:.2f}")

    def calculate_indicators(self, candles):
        """Calculates RSI (14) and MACD (12, 26, 9)"""
        try:
            # Sort Oldest -> Newest for Pandas calculation
            df = pd.DataFrame(candles)
            df = df.iloc[::-1].reset_index(drop=True) 
            
            # --- RSI CALCULATION ---
            delta = df['close'].diff()
            gain = (delta.where(delta > 0, 0)).rolling(window=self.rsi_period).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(window=self.rsi_period).mean()
            rs = gain / loss
            df['rsi'] = 100 - (100 / (1 + rs))

            # --- MACD CALCULATION ---
            # Fast EMA (12)
            short_ema = df['close'].ewm(span=self.macd_fast, adjust=False).mean()
            # Slow EMA (26)
            long_ema = df['close'].ewm(span=self.macd_slow, adjust=False).mean()
            # MACD Line
            df['macd'] = short_ema - long_ema
            # Signal Line (9)
            df['macd_signal'] = df['macd'].ewm(span=self.macd_signal, adjust=False).mean()

            # Return the Last Closed Candle (Index -2)
            last_closed = df.iloc[-2] 
            return last_closed['rsi'], last_closed['macd'], last_closed['macd_signal']
        except Exception as e:
            logger.error(f"Indicator Error: {e}")
            return 50, 0, 0

    def calculate_safe_risk(self, direction, entry_price):
        """Finds Swing High/Low for SL and calculates TP for 1:2 Risk-Reward."""
        sl = 0.0
        tp = 0.0
        is_gold = entry_price > 500
        min_dist = 2.00 if is_gold else 0.0020  
        
        if direction == "BUY":
            # SL = Last Swing Low
            if self.swing_lows:
                last_low = self.swing_lows[-1]['price']
                if (entry_price - last_low) < min_dist: sl = entry_price - min_dist
                else: sl = last_low
            else:
                sl = entry_price - min_dist 
            tp = entry_price + ((entry_price - sl) * self.risk_reward_ratio)

        elif direction == "SELL":
            # SL = Last Swing High
            if self.swing_highs:
                last_high = self.swing_highs[-1]['price']
                if (last_high - entry_price) < min_dist: sl = entry_price + min_dist
                else: sl = last_high
            else:
                sl = entry_price + min_dist 
            tp = entry_price - ((sl - entry_price) * self.risk_reward_ratio)

        return float(sl), float(tp)

    def check_signals_macd_rsi(self, symbol, bid, ask, candles):
        # 1. Gather Data
        rsi, macd, macd_signal = self.calculate_indicators(candles)
        
        # === BUY SETUP ===
        # Video Rule: RSI < 40 AND MACD > Signal Line
        if rsi < self.rsi_buy_threshold and macd > macd_signal:
            sl, tp = self.calculate_safe_risk("BUY", ask)
            logger.info(f"✅ BUY SIGNAL (MACD/RSI) | RSI: {rsi:.1f} | MACD: {macd:.4f} > Sig: {macd_signal:.4f}")
            self.execute_trade("BUY", symbol, self.lot_size, "MACD_RSI", sl, tp)

        # === SELL SETUP ===
        # Video Rule: RSI > 60 AND MACD < Signal Line
        elif rsi > self.rsi_sell_threshold and macd < macd_signal:
            sl, tp = self.calculate_safe_risk("SELL", bid)
            logger.info(f"✅ SELL SIGNAL (MACD/RSI) | RSI: {rsi:.1f} | MACD: {macd:.4f} < Sig: {macd_signal:.4f}")
            self.execute_trade("SELL", symbol, self.lot_size, "MACD_RSI", sl, tp)
        
        else:
            self._log_skip(f"No Signal | RSI: {rsi:.1f} | MACD Gap: {macd - macd_signal:.5f}")

    def _log_skip(self, message):
        """Throttles skip messages to appear only once every 15 seconds."""
        if time.time() - self.last_log_time > 15:
            logger.info(f"❌ {message}")
            self.last_log_time = time.time()

    def analyze_structure(self, symbol, candles):
        """Identifies Swing Highs/Lows for Risk Management."""
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

    def execute_trade(self, direction, symbol, volume, reason, sl, tp):
        self.last_trade_time = time.time()
        self.connector.send_command(direction, symbol, volume, sl, tp, 0)
        logger.info(f"🚀 EXECUTED {direction} {symbol} | Vol: {volume} | SL: {sl:.4f} | TP: {tp:.4f}")

    def check_and_close_profit(self, symbol):
        """Trailing Stop."""
        if time.time() - self.last_profit_close_time < self.profit_close_interval: return
        self.last_profit_close_time = time.time()
        
        trailing_activation = 0.80  
        trailing_offset = 0.20      
        min_profit_target = 0.50

        if self.peak_profit >= trailing_activation:
            if self.current_profit <= (self.peak_profit - trailing_offset):
                logger.info(f"🔒 TRAILING STOP HIT: Peak {self.peak_profit:.2f} -> Current {self.current_profit:.2f}")
                self.connector.close_profit(symbol)
                return

        if self.current_profit >= min_profit_target and self.peak_profit < trailing_activation:
            logger.info(f"💰 TARGET HIT: {self.current_profit:.2f}")
            self.connector.close_profit(symbol)

    def analyze_patterns(self, candles):
        return {'fvg_zone': None, 'bullish_fvg': False, 'bearish_fvg': False}