import logging
import time

logger = logging.getLogger("Strategy")

class TradingStrategy:
    def __init__(self, connector, news_engine, config):
        self.connector = connector
        self.news_engine = news_engine
        self.active = True
        
        # --- Settings ---
        self.max_positions = config.get('auto_trading', {}).get('max_positions', 5)
        self.lot_size = config.get('auto_trading', {}).get('lot_size', 0.01)
        self.max_trade_duration = 0 # Default disabled
        
        # CRT Settings
        self.crt_lookback = 2      # Candle defining the Range (Index 2)
        self.crt_signal_idx = 1    # Candle confirming the Sweep (Index 1)
        
        # --- State ---
        self.pending_setup = None  # <--- Stores signal while waiting for test
        self.trend = "NEUTRAL"
        self.swing_highs = []  
        self.swing_lows = []
        
        self.last_scan_log = 0 
        self.auto_close_profit = True
        self.profit_close_interval = 1 

    def start(self):
        logger.info("CRT Strategy | Retest Mode ACTIVE")

    def stop(self):
        self.active = False
        logger.info("Strategy PAUSED")

    def set_active(self, active):
        self.active = bool(active)
        state = "ACTIVE" if self.active else "PAUSED"
        logging.info(f"Strategy state set to: {state}")

    def on_tick(self, symbol, bid, ask, balance, profit, acct_name, positions, buy_count, sell_count, avg_entry, candles=None):
        if not candles or len(candles) < 20: return

        # 1. PRIORITY: Check Signals & Retests
        if self.active and positions < self.max_positions:
            self.check_crt_signals(symbol, bid, ask, candles)

        # 2. Analyze Trend
        self.analyze_structure(symbol, candles)

        # 3. Manage Profit / Duration
        if self.auto_close_profit:
            self.check_and_close_profit(symbol)

        # 4. Status Log
        if time.time() % 10 < 1: 
            status = "Scanning"
            if self.pending_setup: status = f"WAITING FOR TEST ({self.pending_setup['direction']})"
            logger.info(f"Status: {symbol} | Trend: {self.trend} | State: {status}")

    def check_crt_signals(self, symbol, bid, ask, candles):
        # --- A. EXECUTE PENDING SETUP (THE RETEST) ---
        if self.pending_setup:
            setup = self.pending_setup
            
            # 1. Check Timeout (e.g., if retest doesn't happen within 10 minutes)
            if time.time() - setup['timestamp'] > 600: # 10 mins expiration
                logger.info("⚠️ Signal Timed Out - Retest didn't happen.")
                self.pending_setup = None
                return

            # 2. Check BUY Test
            if setup['direction'] == "BUY":
                # Wait for Ask to drop near the entry level (Retest)
                # entry_level is range_low. We want price <= level + buffer
                dist = ask - setup['entry_level']
                if ask <= (setup['entry_level'] + setup['buffer']):
                    logger.info(f"⚡ RETEST CONFIRMED ⚡ Price {ask:.2f} tested {setup['entry_level']:.2f}")
                    self.execute_trade("BUY", symbol, self.lot_size, "CRT_RETEST", setup['sl'], setup['tp'])
                    self.pending_setup = None
                    return
                
            # 3. Check SELL Test
            elif setup['direction'] == "SELL":
                # Wait for Bid to rise near the entry level
                dist = setup['entry_level'] - bid
                if bid >= (setup['entry_level'] - setup['buffer']):
                    logger.info(f"⚡ RETEST CONFIRMED ⚡ Price {bid:.2f} tested {setup['entry_level']:.2f}")
                    self.execute_trade("SELL", symbol, self.lot_size, "CRT_RETEST", setup['sl'], setup['tp'])
                    self.pending_setup = None
                    return

        # --- B. FIND NEW SIGNALS ---
        c_range = candles[self.crt_lookback]    # Range Candle
        c_signal = candles[self.crt_signal_idx] # Sweep Candle (Closed)
        
        # If we already have a setup for this specific candle, don't overwrite it
        if self.pending_setup and self.pending_setup['candle_time'] == c_signal['time']:
            return 

        range_high = c_range['high']
        range_low = c_range['low']

        # Gold vs Forex Settings
        if candles[0]['close'] > 500: # Gold
            sl_padding = 2.00
            tp_dist = 5.00
            retest_buffer = 0.50 # Price must come within $0.50 of the level
        else: # Forex
            sl_padding = 0.0015
            tp_dist = 0.0030
            retest_buffer = 0.0005

        # 1. BULLISH SWEEP DETECTED
        if c_signal['low'] < range_low and c_signal['close'] > range_low:
            if self.trend != "DOWNTREND":
                logger.info(f"👀 CRT BUY FOUND | Range Low: {range_low} | Waiting for Retest...")
                self.pending_setup = {
                    'direction': "BUY",
                    'entry_level': range_low,
                    'buffer': retest_buffer,
                    'sl': c_signal['low'] - sl_padding,
                    'tp': ask + tp_dist,
                    'timestamp': time.time(),
                    'candle_time': c_signal['time']
                }
                # Draw Box
                self.connector.send_draw_command(f"CRT_{c_range['time']}", range_high, range_low, self.crt_lookback, self.crt_signal_idx, 16776960)

        # 2. BEARISH SWEEP DETECTED
        elif c_signal['high'] > range_high and c_signal['close'] < range_high:
            if self.trend != "UPTREND":
                logger.info(f"👀 CRT SELL FOUND | Range High: {range_high} | Waiting for Retest...")
                self.pending_setup = {
                    'direction': "SELL",
                    'entry_level': range_high,
                    'buffer': retest_buffer,
                    'sl': c_signal['high'] + sl_padding,
                    'tp': bid - tp_dist,
                    'timestamp': time.time(),
                    'candle_time': c_signal['time']
                }
                # Draw Box
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
        logger.info(f"🚀 EXECUTED {direction} {symbol} | Vol: {volume}")

    def check_and_close_profit(self, symbol):
        if not hasattr(self, 'last_profit_close_time'): self.last_profit_close_time = 0
        if time.time() - self.last_profit_close_time < self.profit_close_interval: return
        self.connector.close_profit(symbol)
        
        # Check Max Duration
        if self.max_trade_duration > 0:
            # Note: This requires the connector to return open times, which it currently doesn't fully support in this snippet.
            # We can implement a simple safety close if needed later.
            pass
            
        self.last_profit_close_time = time.time()

    def analyze_patterns(self, candles):
        return {'fvg_zone': None, 'bullish_fvg': False, 'bearish_fvg': False}
    def _update_range_from_history(self, candles): pass