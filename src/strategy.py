import logging
import time

logger = logging.getLogger("Strategy")

class TradingStrategy:
    def __init__(self, connector, news_engine, config):
        self.connector = connector
        self.news_engine = news_engine
        self.active = True
        
        # --- Settings for Small Balance ---
        self.max_positions = 1  # Force 1 position to protect small balance
        self.lot_size = config.get('auto_trading', {}).get('lot_size', 0.01)
        
        # --- Profit Settings (Scalping Mode) ---
        self.min_profit_target = 0.50    # Secure profit early (50 cents)
        self.trailing_activation = 0.80  # Start trailing after 80 cents profit
        self.trailing_offset = 0.20      # Close if profit drops 20 cents from peak
        
        # CRT Settings
        self.crt_lookback = 2      
        self.crt_signal_idx = 1    
        
        # --- State ---
        self.pending_setup = None  
        self.trend = "NEUTRAL"
        self.swing_highs = []  
        self.swing_lows = []
        
        self.current_profit = 0.0 
        self.peak_profit = 0.0        # Track highest profit for trailing
        self.last_profit_close_time = 0
        self.profit_close_interval = 1 

    def start(self):
        logger.info("Strategy ACTIVE | Backtest Entry Mode | Smart Profit Locking")

    def stop(self):
        self.active = False
        logger.info("Strategy PAUSED")

    def set_active(self, active):
        self.active = bool(active)
        state = "ACTIVE" if self.active else "PAUSED"
        logging.info(f"Strategy state set to: {state}")

    def on_tick(self, symbol, bid, ask, balance, profit, acct_name, positions, buy_count, sell_count, avg_entry, candles=None):
        if not candles or len(candles) < 20: return
        self.current_profit = profit 

        # --- Track Peak Profit (For Trailing Stop) ---
        if positions > 0:
            if profit > self.peak_profit:
                self.peak_profit = profit
        else:
            self.peak_profit = 0.0 # Reset when no trades

        # 1. PRIORITY: Check Signals (Only if we have no positions)
        if self.active and positions < self.max_positions:
            self.check_crt_signals(symbol, bid, ask, candles)

        # 2. Analyze Trend Structure
        self.analyze_structure(symbol, candles)

        # 3. Manage Profit (Smart Trailing)
        if positions > 0:
            self.check_and_close_profit(symbol)

        # 4. Status Log
        if time.time() % 10 < 1: 
            status = "Scanning"
            if self.pending_setup: status = f"WAITING FOR BACKTEST ({self.pending_setup['direction']} at {self.pending_setup['entry_level']:.2f})"
            logger.info(f"Status: {symbol} | Trend: {self.trend} | PnL: {profit:.2f} | Peak: {self.peak_profit:.2f} | {status}")

    # --- SECURE CANDLE PREDICTION ---
    def predict_momentum(self, candles):
        """
        Uses Heikin Ashi on CLOSED candles to confirm trend strength.
        Returns: 'BULLISH', 'BEARISH', or 'NEUTRAL'
        """
        try:
            # We use index 1 (Last Closed Candle) and index 2 (Previous)
            c1 = candles[1] 
            c2 = candles[2]
            
            # Heikin Ashi Calculation
            ha_close = (c1['open'] + c1['high'] + c1['low'] + c1['close']) / 4
            ha_open = (c2['open'] + c2['close']) / 2
            
            # Body Size Check (Candle must be strong)
            body_size = abs(c1['close'] - c1['open'])
            avg_body = abs(c2['close'] - c2['open'])
            is_strong = body_size > (avg_body * 0.5)

            if ha_close > ha_open and is_strong:
                return "BULLISH"
            elif ha_close < ha_open and is_strong:
                return "BEARISH"
            
            return "NEUTRAL"
        except:
            return "NEUTRAL"

    def check_crt_signals(self, symbol, bid, ask, candles):
        
        # --- B. FIND NEW SIGNALS ---
        c_range = candles[self.crt_lookback]    
        c_signal = candles[self.crt_signal_idx] 
        
        range_high = c_range['high']
        range_low = c_range['low']

        # Asset Class Adjustments
        is_gold = candles[0]['close'] > 500
        if is_gold:
            tp_dist = 4.00
        else:
            tp_dist = 0.0030

        # --- CONFLUENCE CHECKS ---
        market_sentiment = self.news_engine.get_market_sentiment()
        candle_prediction = self.predict_momentum(candles) 

        # 1. BUY SIGNAL LOGIC
        if c_signal['low'] < range_low and c_signal['close'] > range_low:
            if self.trend != "DOWNTREND":
                if market_sentiment == "BULLISH" or candle_prediction == "BULLISH":
                    
                    # FIX: Execute Immediately instead of waiting
                    logger.info(f"⚡ BUY SIGNAL FOUND (Entering Immediately at {ask:.2f})")
                    self.execute_trade("BUY", symbol, self.lot_size, "CRT_INSTANT", 0.0, ask + tp_dist)
                    
                    # Draw the box for visual reference
                    self.connector.send_draw_command(f"CRT_{c_range['time']}", range_high, range_low, self.crt_lookback, self.crt_signal_idx, 16776960)

        # 2. SELL SIGNAL LOGIC
        elif c_signal['high'] > range_high and c_signal['close'] < range_high:
            if self.trend != "UPTREND":
                if market_sentiment == "BEARISH" or candle_prediction == "BEARISH":
                    
                    # FIX: Execute Immediately instead of waiting
                    logger.info(f"⚡ SELL SIGNAL FOUND (Entering Immediately at {bid:.2f})")
                    self.execute_trade("SELL", symbol, self.lot_size, "CRT_INSTANT", 0.0, bid - tp_dist)

                    # Draw the box for visual reference
                    self.connector.send_draw_command(f"CRT_{c_range['time']}", range_high, range_low, self.crt_lookback, self.crt_signal_idx, 16776960)

    def analyze_structure(self, symbol, candles):
        swings = [] 
        lookback = min(len(candles) - 2, 50)
        for i in range(2, lookback): 
            c_curr = candles[i]
            c_prev = candles[i+1]
            c_next = candles[i-1]
            if c_curr['high'] > c_prev['high'] and c_curr['high'] > c_next['high']:
                swings.append({'type': 'H', 'price': c_curr['high'], 'index': i, 'time': c_curr['time']})
            elif c_curr['low'] < c_prev['low'] and c_curr['low'] < c_next['low']:
                swings.append({'type': 'L', 'price': c_curr['low'], 'index': i, 'time': c_curr['time']})

        swings.sort(key=lambda x: x['index'], reverse=True)
        self.swing_highs = [s for s in swings if s['type'] == 'H']
        self.swing_lows = [s for s in swings if s['type'] == 'L']
        
        if len(self.swing_highs) >= 2 and len(self.swing_lows) >= 2:
            h1 = self.swing_highs[-1]['price']
            h2 = self.swing_highs[-2]['price']
            l1 = self.swing_lows[-1]['price']
            l2 = self.swing_lows[-2]['price']
            if h1 > h2 and l1 > l2: self.trend = "UPTREND"
            elif h1 < h2 and l1 < l2: self.trend = "DOWNTREND"
            else: self.trend = "NEUTRAL"
        
        if time.time() % 5 < 0.1:
            for k in range(len(swings) - 1):
                s1 = swings[k]
                s2 = swings[k+1]
                line_name = f"ZZ_{s1['time']}_{s2['time']}"
                color = 32768 if s1['type'] == 'L' else 255 
                self.connector.send_trend_command(line_name, s1['index'], s1['price'], s2['index'], s2['price'], color, 2)

    def execute_trade(self, direction, symbol, volume, reason, sl, tp):
        self.connector.send_command(direction, symbol, volume, sl, tp, 0)
        logger.info(f"🚀 EXECUTED {direction} {symbol} | Vol: {volume} | SL: {sl} (None) | TP: {tp:.2f}")

    def check_and_close_profit(self, symbol):
        if time.time() - self.last_profit_close_time < self.profit_close_interval: return
        self.last_profit_close_time = time.time()
        
        # --- TRAILING STOP (PROFIT BETTER) ---
        # 1. Check if we reached the Activation Level ($0.80)
        if self.peak_profit >= self.trailing_activation:
            # 2. Check if price dropped back by Offset ($0.20)
            if self.current_profit <= (self.peak_profit - self.trailing_offset):
                logger.info(f"🔒 TRAILING STOP HIT: Peak {self.peak_profit:.2f} -> Current {self.current_profit:.2f} | CLOSING")
                self.connector.close_profit(symbol)
                return

        # --- BASIC TAKE PROFIT ---
        # Only use this if we haven't activated the trailing stop yet
        if self.current_profit >= self.min_profit_target and self.peak_profit < self.trailing_activation:
            logger.info(f"💰 TARGET HIT: {self.current_profit:.2f} | CLOSING")
            self.connector.close_profit(symbol)

    def analyze_patterns(self, candles):
        return {'fvg_zone': None, 'bullish_fvg': False, 'bearish_fvg': False}
    def _update_range_from_history(self, candles): pass