import logging
import time

logger = logging.getLogger("Strategy")

class TradingStrategy:
    def __init__(self, connector, news_engine, config):
        self.connector = connector
        self.news_engine = news_engine
        
        # --- FIX 1: Start Active by Default ---
        self.active = True 
        
        # --- Settings ---
        self.max_positions = config.get('auto_trading', {}).get('max_positions', 1)
        self.lot_size = config.get('auto_trading', {}).get('lot_size', 0.01)
        self.risk_reward_ratio = 2.0
        
        # --- Market Structure State ---
        self.trend = "NEUTRAL"
        self.swing_highs = []  
        self.swing_lows = []
        
        # --- Trading State ---
        self.trade_cooldown = 5 
        self.last_trade_time = 0
        self.last_scan_log = 0  # To control log spam
        self.auto_close_profit = True
        self.profit_close_interval = 1 

        self.use_dynamic_range = True
        self.min_price = 0 
        self.max_price = 0

    def start(self):
        logger.info("Strategy Started | Auto-Trading is ACTIVE")

    def stop(self):
        self.active = False
        logger.info("Strategy PAUSED")

    def set_active(self, active):
        self.active = bool(active)
        state = "ACTIVE" if self.active else "PAUSED"
        logging.info(f"Strategy state set to: {state}")

    def on_tick(self, symbol, bid, ask, balance, profit, acct_name, positions, buy_count, sell_count, avg_entry, candles=None):
        # We need at least 20 candles to calculate structure
        if not candles or len(candles) < 20: 
            return

        self._update_range_from_history(candles)
        self.analyze_structure(symbol, candles)

        # Log Status every 10 seconds
        if time.time() % 10 < 1: 
            logger.info(f"Status: {symbol} | Trend: {self.trend} | Pos: {positions}/{self.max_positions} | Active: {self.active}")

        if self.active and positions < self.max_positions:
            self.check_entry_signals(symbol, bid, ask, candles)

        if self.auto_close_profit:
            self.check_and_close_profit(symbol)

    def analyze_structure(self, symbol, candles):
        swings = [] 
        # --- FIX 2: Dynamic Range Safety (Don't crash if < 50 candles) ---
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
        
        # Draw ZigZag lines on MT5
        for k in range(len(swings) - 1):
            s1 = swings[k]
            s2 = swings[k+1]
            line_name = f"ZZ_{s1['time']}_{s2['time']}"
            color = 32768 if s1['type'] == 'L' else 255 
            self.connector.send_trend_command(line_name, s1['index'], s1['price'], s2['index'], s2['price'], color, 2)

        # Detect Trend
        if len(self.swing_highs) >= 2 and len(self.swing_lows) >= 2:
            h1 = self.swing_highs[-1]['price']
            h2 = self.swing_highs[-2]['price']
            l1 = self.swing_lows[-1]['price']
            l2 = self.swing_lows[-2]['price']

            if h1 > h2 and l1 > l2:
                self.trend = "UPTREND"
            elif h1 < h2 and l1 < l2:
                self.trend = "DOWNTREND"

    def check_entry_signals(self, symbol, bid, ask, candles):
        if not self.active: return
        
        # Trade Cooldown
        if (time.time() - self.last_trade_time) < self.trade_cooldown:
            return

        # Need recent candles for FVG
        if len(candles) < 5: return
        
        # --- AUTO SCALING FOR GOLD VS FOREX ---
        price_level = candles[0]['close']
        
        if price_level > 500: # GOLD / INDICES
            entry_buffer = 1.50   
            sl_padding = 3.00     
            asset_type = "GOLD/INDEX"
        else: # FOREX
            entry_buffer = 0.0010 
            sl_padding = 0.0020
            asset_type = "FOREX"

        c1 = candles[3] 
        c3 = candles[1]
        
        fvg_bull = None
        fvg_bear = None

        # FVG Detection
        if c3['low'] > c1['high']:
             fvg_bull = (c1['high'], c3['low']) 
             self.connector.send_draw_command(f"FVG_{symbol}_Bull_{c3['time']}", c1['high'], c3['low'], 3, 1, 32768)  
        
        if c3['high'] < c1['low']:
             fvg_bear = (c3['high'], c1['low']) 
             self.connector.send_draw_command(f"FVG_{symbol}_Bear_{c3['time']}", c3['high'], c1['low'], 3, 1, 255)  

        # --- LOGGING THROTTLE (To avoid spamming console every tick) ---
        should_log = False
        if time.time() - self.last_scan_log > 5: # Log scan results every 5 seconds
            should_log = True
            self.last_scan_log = time.time()

        # --- SIGNAL LOGIC ---
        
        # BUY Logic
        if fvg_bull:
            if self.trend == "UPTREND":
                zone_top = fvg_bull[1]
                zone_btm = fvg_bull[0]
                
                # Check Entry
                if ask <= (zone_top + entry_buffer) and ask >= zone_btm:
                    sl = zone_btm - sl_padding
                    if sl >= ask: return 
                    risk = ask - sl
                    tp = ask + (risk * self.risk_reward_ratio)
                    
                    logger.info(f"*** BUY SIGNAL *** Range: {zone_btm}-{zone_top} | Ask: {ask}")
                    self.execute_trade("BUY", symbol, self.lot_size, "FVG_ENTRY", sl, tp)
                elif should_log:
                    dist = ask - zone_top
                    logger.info(f"Scan ({asset_type}): Bullish FVG Found but Price too high. Ask: {ask:.2f} | Need < {zone_top + entry_buffer:.2f} (Dist: {dist:.2f})")
            elif should_log:
                logger.info(f"Scan: Bullish FVG Found, but Trend is {self.trend} (Ignored)")

        # SELL Logic
        elif fvg_bear:
            if self.trend == "DOWNTREND":
                zone_btm = fvg_bear[0]
                zone_top = fvg_bear[1]
                
                # Check Entry
                if bid >= (zone_btm - entry_buffer) and bid <= zone_top:
                    sl = zone_top + sl_padding
                    if sl <= bid: return 
                    risk = sl - bid
                    tp = bid - (risk * self.risk_reward_ratio)
                    if tp >= bid: return

                    logger.info(f"*** SELL SIGNAL *** Range: {zone_btm}-{zone_top} | Bid: {bid}")
                    self.execute_trade("SELL", symbol, self.lot_size, "FVG_ENTRY", sl, tp)
                elif should_log:
                    dist = zone_btm - bid
                    logger.info(f"Scan ({asset_type}): Bearish FVG Found but Price too low. Bid: {bid:.2f} | Need > {zone_btm - entry_buffer:.2f} (Dist: {dist:.2f})")
            elif should_log:
                logger.info(f"Scan: Bearish FVG Found, but Trend is {self.trend} (Ignored)")
        
        elif should_log:
             logger.info("Scan: No valid FVG patterns in immediate candles.")

    def execute_trade(self, direction, symbol, volume, reason, sl, tp):
        logger.info(f"EXECUTING {direction} {symbol} | Vol: {volume} | SL: {sl:.2f} | TP: {tp:.2f}")
        self.connector.send_command(direction, symbol, volume, sl, tp, 0)
        self.last_trade_time = time.time()

    def check_and_close_profit(self, symbol):
        if not hasattr(self, 'last_profit_close_time'): self.last_profit_close_time = 0
        if time.time() - self.last_profit_close_time < self.profit_close_interval: return
        self.connector.close_profit(symbol)
        self.last_profit_close_time = time.time()

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
            'bullish_fvg': False, 
            'bearish_fvg': False
        }
        if not candles or len(candles) < 5: return res

        try:
            c1 = candles[3]
            c3 = candles[1]
            if c3['low'] > c1['high']:
                 res['fvg_zone'] = (c1['high'], c3['low']) 
                 res['bullish_fvg'] = True
            elif c3['high'] < c1['low']:
                 res['fvg_zone'] = (c3['high'], c1['low']) 
                 res['bearish_fvg'] = True
        except: pass
        return res