import logging
import time

logger = logging.getLogger("Strategy")

class TradingStrategy:
    def __init__(self, connector, news_engine, config):
        self.connector = connector
        self.news_engine = news_engine
        self.config = config
        self.active = False  # Start inactive; UI/config will set
        
        # --- Settings (from config) ---
        self.max_positions = config.get('auto_trading', {}).get('max_positions', 100)
        self.lot_size = config.get('auto_trading', {}).get('lot_size', 0.01)
        self.risk_reward_ratio = 2.0
        self.entry_buffer_pips = 0.1  # For XAUUSD
        
        # --- FIX: Add current_profit storage ---
        self.current_profit = 0.0
        
        # --- Market Structure State ---
        self.trend = "NEUTRAL"
        self.swing_highs = []  
        self.swing_lows = []
        self.last_bos_price = 0.0
        self.last_choch_price = 0.0
        
        # --- Trading State ---
        self.trade_cooldown = 5
        self.last_trade_time = 0
        self.auto_close_profit = True
        self.profit_close_interval = 5  # FIX: Less aggressive (was 1s)

        self.use_dynamic_range = True
        self.zone_percent = 20 
        self.min_price = 0 
        self.max_price = 0
        self.use_fvg = True
        self.use_ob = True
        self.use_zone_confluence = True 
        self.use_trend_filter = True 

        # Log throttling
        self.last_status_log = 0

    def set_active(self, enabled):
        """For UI toggle - sets active state reliably."""
        self.active = enabled
        status = "ENABLED" if enabled else "DISABLED"
        logger.info(f"Auto-Trading: {status} (UI Toggle)")

    def start(self):
        # FIX: Start active by default; UI can toggle. Use config for settings only.
        self.set_active(True)
        logger.info("Strategy STARTED | SMC Logic Active")

    def stop(self):
        self.set_active(False)
        logger.info("Strategy PAUSED")

    def on_tick(self, symbol, bid, ask, balance, profit, acct_name, positions, buy_count, sell_count, avg_entry, candles=None):
        # FIX: Store current profit for close logic
        self.current_profit = profit
        
        candle_count = len(candles) if candles else 0
        if candle_count < 20: 
            return  # Still waiting for data

        self._update_range_from_history(candles)
        self.analyze_structure(symbol, candles)

        # FIX: Throttled status log (every 10s)
        current_time = time.time()
        if current_time - self.last_status_log > 10:
            logger.info(f"Status: {symbol} | Trend: {self.trend} | Pos: {positions}/{self.max_positions} | Active: {self.active}")
            self.last_status_log = current_time

        if self.active and positions < self.max_positions:
            self.check_entry_signals(symbol, bid, ask, candles)
        else:
            if self.active and positions >= self.max_positions:
                logger.debug(f"Max positions reached: {positions}/{self.max_positions} - Skipping entry")

        if self.auto_close_profit:
            self.check_and_close_profit(symbol)

    def analyze_structure(self, symbol, candles):
        """
        Identifies Swing Highs and Lows using a 3-bar fractal method.
        Draws the Zig-Zag lines using TIMESTAMPS to keep records stable.
        """
        swings = [] 
        
        # FIX: Prevent index error
        max_lookback = min(50, len(candles) - 1)
        for i in range(2, max_lookback):
            c_curr = candles[i]
            c_prev = candles[i + 1]
            c_next = candles[i - 1]
            
            # Swing High
            if c_curr['high'] > c_prev['high'] and c_curr['high'] > c_next['high']:
                swings.append({'type': 'H', 'price': c_curr['high'], 'index': i, 'time': c_curr['time']})
            # Swing Low
            elif c_curr['low'] < c_prev['low'] and c_curr['low'] < c_next['low']:
                swings.append({'type': 'L', 'price': c_curr['low'], 'index': i, 'time': c_curr['time']})

        swings.sort(key=lambda x: x['index'], reverse=True)  # Oldest to newest
        self.swing_highs = [s for s in swings if s['type'] == 'H']
        self.swing_lows = [s for s in swings if s['type'] == 'L']
        
        # --- DRAW ZIGZAG (STABLE RECORD) ---
        for k in range(len(swings) - 1):
            s1 = swings[k]
            s2 = swings[k + 1]
            
            line_name = f"ZZ_{int(s1['time'])}_{int(s2['time'])}"  # FIX: int() for unique ID
            color = 32768 if s1['type'] == 'L' else 255
            self.connector.send_trend_command(line_name, s1['index'], s1['price'], s2['index'], s2['price'], color, 2)

        # --- DETECT TREND & BREAKS (Relaxed: independent HH/HL) ---
        if len(swings) < 4: return
        
        highs = self.swing_highs
        lows = self.swing_lows
        if not highs or not lows: return
        
        recent_high = highs[-1]['price']
        recent_low = lows[-1]['price']
        current_price = candles[0]['close']

        # FIX: Relaxed - up if HH, down if LL
        self.trend = "NEUTRAL"
        if len(highs) >= 2 and highs[-1]['price'] > highs[-2]['price']:
            self.trend = "UPTREND"
        elif len(lows) >= 2 and lows[-1]['price'] < lows[-2]['price']:
            self.trend = "DOWNTREND"
        
        # BOS Logic (unchanged, with timestamp fix)
        if self.trend == "UPTREND" and current_price > recent_high:
            if abs(recent_high - self.last_bos_price) > 0.001:
                self.last_bos_price = recent_high
                ts = int(highs[-1]['time'])
                self.connector.send_hline_command(f"BOS_{symbol}_{ts}", recent_high, 16711935, 1)
                self.connector.send_text_command(f"Txt_BOS_{ts}", highs[-1]['index'], recent_high, 16711935, "BOS")

        elif self.trend == "DOWNTREND" and current_price < recent_low:
             if abs(recent_low - self.last_bos_price) > 0.001:
                self.last_bos_price = recent_low
                ts = int(lows[-1]['time'])
                self.connector.send_hline_command(f"BOS_{symbol}_{ts}", recent_low, 16711935, 1)
                self.connector.send_text_command(f"Txt_BOS_{ts}", lows[-1]['index'], recent_low, 16711935, "BOS")

    def check_entry_signals(self, symbol, bid, ask, candles):
        if not self.active: return
        
        cooldown_remaining = self.trade_cooldown - (time.time() - self.last_trade_time)
        if cooldown_remaining > 0:
            return

        fvg_bull = None
        fvg_bear = None
        
        c1 = candles[3]  # Older
        c3 = candles[1]  # Recent
        
        # Bullish Gap
        if c3['low'] > c1['high']:
             lower = c1['high']
             upper = c3['low']
             fvg_bull = (lower, upper)
             self.connector.send_draw_command(f"FVG_{symbol}_Bull_{int(c3['time'])}", lower, upper, 3, 1, 32768)
        
        # Bearish Gap
        if c3['high'] < c1['low']:
             lower = c3['high']
             upper = c1['low']
             fvg_bear = (lower, upper)
             self.connector.send_draw_command(f"FVG_{symbol}_Bear_{int(c3['time'])}", lower, upper, 3, 1, 255)

        buffer = self.entry_buffer_pips / 1000.0  # ~0.0001 for XAUUSD
        
        # --- Entry Logic (Full zone check + debug) ---
        if self.trend == "UPTREND" and fvg_bull:
            lower, upper = fvg_bull
            in_zone = lower - buffer <= ask <= upper + buffer
            logger.info(f"BUY CHECK: {symbol} Ask={ask:.5f} | FVG={lower:.5f}-{upper:.5f} | In Zone: {in_zone}")
            if in_zone:
                sl = lower - 0.05 
                tp = ask + (ask - sl) * self.risk_reward_ratio
                self.execute_trade("BUY", symbol, self.lot_size, "FVG_BULL", sl, tp)
            else:
                logger.debug("BUY missed: Price outside FVG zone")

        elif self.trend == "DOWNTREND" and fvg_bear:
            lower, upper = fvg_bear
            in_zone = lower - buffer <= bid <= upper + buffer
            logger.info(f"SELL CHECK: {symbol} Bid={bid:.5f} | FVG={lower:.5f}-{upper:.5f} | In Zone: {in_zone}")
            if in_zone:
                sl = upper + 0.05
                tp = bid - (sl - bid) * self.risk_reward_ratio
                self.execute_trade("SELL", symbol, self.lot_size, "FVG_BEAR", sl, tp)
            else:
                logger.debug("SELL missed: Price outside FVG zone")

    def execute_trade(self, direction, symbol, volume, reason, sl, tp):
        logger.info(f"SIGNAL [{reason}]: {direction} {symbol} {volume} SL={sl:.5f} TP={tp:.5f}")
        self.connector.send_command(direction, symbol, volume, sl, tp, 0)
        self.last_trade_time = time.time()

    # FINAL FIX: Use connector.close_position (sends CLOSE_ALL); raised threshold; added debug
    def check_and_close_profit(self, symbol):
        if not hasattr(self, 'last_profit_close_time'): self.last_profit_close_time = 0
        current_time = time.time()
        if current_time - self.last_profit_close_time < self.profit_close_interval: return
        
        try:
            # FIX: Emergency close if deeply negative (raised to -150 for safety)
            if self.current_profit < -150:  # Threshold for ~10 pos on XAUUSD
                logger.warning(f"Emergency close ALL: P/L {self.current_profit:.2f} < -150 for {symbol}")
                self.connector.close_position(symbol)  # Sends "CLOSE_ALL|{symbol}"
                logger.debug(f"Sent CLOSE_ALL command for {symbol}")
            else:
                logger.debug(f"Closing profits only for {symbol} (P/L: {self.current_profit:.2f})")
                self.connector.close_profit(symbol)  # Sends "CLOSE_WIN|{symbol}"
        except Exception as e:
            logger.error(f"Profit close error: {e} - Skipping this interval")
        finally:
            self.last_profit_close_time = current_time

    def _update_range_from_history(self, candles):
        if not candles or not self.use_dynamic_range: return
        highs = [c['high'] for c in candles]
        lows = [c['low'] for c in candles]
        if highs and lows:
            self.max_price = max(highs)
            self.min_price = min(lows)
    
    def analyze_patterns(self, candles):
        res = {
            'fvg_zone': None, 
            'ob_zone': None, 
            'c3_high': 0.0, 
            'c1_low': 0.0, 
            'bullish_fvg': False, 
            'bearish_fvg': False
        }
        
        if not candles or len(candles) < 5: 
            return res

        try:
            res['c3_high'] = candles[1]['high']
            res['c1_low'] = candles[3]['low']

            if candles[1]['low'] > candles[3]['high']:
                 res['fvg_zone'] = (candles[3]['high'], candles[1]['low'])  # lower, upper
                 res['bullish_fvg'] = True
            
            elif candles[1]['high'] < candles[3]['low']:
                 res['fvg_zone'] = (candles[1]['high'], candles[3]['low'])
                 res['bearish_fvg'] = True
                 
        except Exception as e: 
            pass
            
        return res