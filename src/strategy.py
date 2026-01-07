import logging
import time

logger = logging.getLogger("Strategy")

class TradingStrategy:
    def __init__(self, connector, news_engine, config):
        self.connector = connector
        self.news_engine = news_engine
        self.active = False
        
        # --- Settings ---
        self.max_positions = config.get('auto_trading', {}).get('max_positions', 1)
        self.lot_size = config.get('auto_trading', {}).get('lot_size', 0.01)
        self.risk_reward_ratio = 2.0
        
        # --- Market Structure State ---
        self.trend = "NEUTRAL"
        self.swing_highs = []  
        self.swing_lows = []
        self.last_bos_price = 0.0
        self.last_choch_price = 0.0
        
        # --- Trading State ---
        self.trade_cooldown = 5 # Reduced cooldown
        self.last_trade_time = 0
        self.auto_close_profit = True
        self.profit_close_interval = 1 

        self.use_dynamic_range = True
        self.zone_percent = 20 
        self.min_price = 0 
        self.max_price = 0
        self.use_fvg = True
        self.use_ob = True
        self.use_zone_confluence = True 
        self.use_trend_filter = True 

    def start(self):
        self.active = True
        logger.info("Strategy STARTED | SMC Logic Active")

    def stop(self):
        self.active = False
        logger.info("Strategy PAUSED")

    def on_tick(self, symbol, bid, ask, balance, profit, acct_name, positions, buy_count, sell_count, avg_entry, candles=None):
        # DEBUG: Check if data is arriving
        candle_count = len(candles) if candles else 0
        if candle_count < 20: 
            logger.debug(f"Waiting for more data... Current candles: {candle_count}/20")
            return

        self._update_range_from_history(candles)
        self.analyze_structure(symbol, candles)

        # DEBUG: Periodic state log
        if time.time() % 10 < 1: # Log every ~10 seconds
            logger.info(f"Status: {symbol} | Trend: {self.trend} | Pos: {positions}/{self.max_positions} | Active: {self.active}")

        if self.active and positions < self.max_positions:
            self.check_entry_signals(symbol, bid, ask, candles)

        if self.auto_close_profit:
            self.check_and_close_profit(symbol)

    def analyze_structure(self, symbol, candles):
        """
        Identifies Swing Highs and Lows using a 3-bar fractal method.
        Draws the Zig-Zag lines using TIMESTAMPS to keep records stable.
        """
        swings = [] 
        
        for i in range(2, 50): 
            c_curr = candles[i]
            c_prev = candles[i+1]
            c_next = candles[i-1]
            
            # Swing High
            if c_curr['high'] > c_prev['high'] and c_curr['high'] > c_next['high']:
                swings.append({'type': 'H', 'price': c_curr['high'], 'index': i, 'time': c_curr['time']})
            # Swing Low
            elif c_curr['low'] < c_prev['low'] and c_curr['low'] < c_next['low']:
                swings.append({'type': 'L', 'price': c_curr['low'], 'index': i, 'time': c_curr['time']})

        swings.sort(key=lambda x: x['index'], reverse=True) # Oldest to Newest
        self.swing_highs = [s for s in swings if s['type'] == 'H']
        self.swing_lows = [s for s in swings if s['type'] == 'L']
        
        # --- DRAW ZIGZAG (STABLE RECORD) ---
        for k in range(len(swings) - 1):
            s1 = swings[k]
            s2 = swings[k+1]
            
            # UNIQUE ID: ZZ_{Time1}_{Time2} -> This ensures the line stays recorded and doesn't flicker
            line_name = f"ZZ_{s1['time']}_{s2['time']}"
            
            color = 32768 if s1['type'] == 'L' else 255 # Green if L->H, Red if H->L
            self.connector.send_trend_command(line_name, s1['index'], s1['price'], s2['index'], s2['price'], color, 2)

        # --- DETECT TREND & BREAKS ---
        if len(swings) < 4: return
        
        highs = self.swing_highs
        lows = self.swing_lows
        if not highs or not lows: return
        
        recent_high = highs[-1]['price']
        recent_low = lows[-1]['price']
        current_price = candles[0]['close']

        if len(highs) >= 2 and len(lows) >= 2:
            if highs[-1]['price'] > highs[-2]['price'] and lows[-1]['price'] > lows[-2]['price']:
                self.trend = "UPTREND"
            elif highs[-1]['price'] < highs[-2]['price'] and lows[-1]['price'] < lows[-2]['price']:
                self.trend = "DOWNTREND"
        
        # BOS Logic
        if self.trend == "UPTREND" and current_price > recent_high:
            if abs(recent_high - self.last_bos_price) > 0.001:
                self.last_bos_price = recent_high
                self.connector.send_hline_command(f"BOS_{symbol}_{highs[-1]['time']}", recent_high, 16711935, 1)
                self.connector.send_text_command(f"Txt_BOS_{highs[-1]['time']}", highs[-1]['index'], recent_high, 16711935, "BOS")

        elif self.trend == "DOWNTREND" and current_price < recent_low:
             if abs(recent_low - self.last_bos_price) > 0.001:
                self.last_bos_price = recent_low
                self.connector.send_hline_command(f"BOS_{symbol}_{lows[-1]['time']}", recent_low, 16711935, 1)
                self.connector.send_text_command(f"Txt_BOS_{lows[-1]['time']}", lows[-1]['index'], recent_low, 16711935, "BOS")

    def check_entry_signals(self, symbol, bid, ask, candles):
        if not self.active: return
        
        cooldown_remaining = self.trade_cooldown - (time.time() - self.last_trade_time)
        if cooldown_remaining > 0:
            return

        fvg_bull = None
        fvg_bear = None
        
        c1 = candles[3] 
        c2 = candles[2]
        c3 = candles[1]
        
        # Bullish Gap detection
        if c3['low'] > c1['high']:
             fvg_bull = (c3['low'], c1['high'])
             self.connector.send_draw_command(f"FVG_{symbol}_Bull_{c3['time']}", c3['high'], c1['low'], 3, 1, 32768)
        
        # Bearish Gap detection
        if c3['high'] < c1['low']:
             fvg_bear = (c3['high'], c1['low'])
             self.connector.send_draw_command(f"FVG_{symbol}_Bear_{c3['time']}", c1['high'], c3['low'], 3, 1, 255)

        # --- DEBUG LOGGING FOR SIGNALS ---
        if self.trend == "UPTREND" and fvg_bull:
            buy_zone_top = fvg_bull[0]
            logger.info(f"🔍 BUY SIGNAL PENDING: Price {ask} | FVG Top {buy_zone_top:.5f}")
            if ask <= buy_zone_top + 0.0010: # Increased buffer to 10 pips
                sl = fvg_bull[1] - 0.05 
                tp = ask + (ask - sl) * self.risk_reward_ratio
                self.execute_trade("BUY", symbol, self.lot_size, "FVG_ENTRY", sl, tp)

        elif self.trend == "DOWNTREND" and fvg_bear:
            sell_zone_btm = fvg_bear[0]
            logger.info(f"🔍 SELL SIGNAL PENDING: Price {bid} | FVG Btm {sell_zone_btm:.5f}")
            if bid >= sell_zone_btm - 0.0010:
                sl = fvg_bear[1] + 0.05
                tp = bid - (sl - bid) * self.risk_reward_ratio
                self.execute_trade("SELL", symbol, self.lot_size, "FVG_ENTRY", sl, tp)

    def execute_trade(self, direction, symbol, volume, reason, sl, tp):
        logger.info(f"🚀 SIGNAL [{reason}]: {direction} {symbol} {volume} SL={sl:.2f} TP={tp:.2f}")
        self.connector.send_command(direction, symbol, volume, sl, tp, 0)
        self.last_trade_time = time.time()

    def check_and_close_profit(self, symbol):
        if not hasattr(self, 'last_profit_close_time'): self.last_profit_close_time = 0
        current_time = time.time()
        if current_time - self.last_profit_close_time < self.profit_close_interval: return
        self.connector.close_profit(symbol)
        self.last_profit_close_time = current_time

    def _update_range_from_history(self, candles):
        if not candles or not self.use_dynamic_range: return
        highs = [c['high'] for c in candles]
        lows = [c['low'] for c in candles]
        if highs and lows:
            self.max_price = max(highs)
            self.min_price = min(lows)
    
    def analyze_patterns(self, candles):
        # UI Helper - Returns dict for UI labels
        # Initialize with default 0s so UI doesn't show empty
        res = {
            'fvg_zone': None, 
            'ob_zone': None, 
            'c3_high': 0.0, 
            'c1_low': 0.0, 
            'bullish_fvg': False, 
            'bearish_fvg': False
        }
        
        # Safety check: ensure we have enough candles
        if not candles or len(candles) < 5: 
            return res

        try:
            # 1. Populate Debug Values for UI
            res['c3_high'] = candles[1]['high']
            res['c1_low'] = candles[3]['low']

            # 2. Check for Bullish FVG (Buying Gap)
            if candles[1]['low'] > candles[3]['high']:
                 res['fvg_zone'] = (candles[1]['low'], candles[3]['high'])
                 res['bullish_fvg'] = True
            
            # 3. Check for Bearish FVG (Selling Gap)
            elif candles[1]['high'] < candles[3]['low']:
                 res['fvg_zone'] = (candles[1]['high'], candles[3]['low'])
                 res['bearish_fvg'] = True
                 
        except Exception as e: 
            pass
            
        return res