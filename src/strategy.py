import logging
import time

logger = logging.getLogger("Strategy")

class TradingStrategy:
    def __init__(self, connector, news_engine, config):
        self.connector = connector
        self.news_engine = news_engine
        self.active = True
        
        # --- Strict Safety Settings ---
        self.max_positions = 1  
        self.lot_size = config.get('auto_trading', {}).get('lot_size', 0.01)
        self.use_auto_risk = True
        
        # --- Profit Settings ---
        self.min_profit_target = 0.50    
        self.trailing_activation = 0.80  
        self.trailing_offset = 0.20      
        
        # --- Strategy Parameters ---
        self.crt_lookback = 2      
        self.crt_signal_idx = 1    
        
        # --- State ---
        self.trend = "NEUTRAL"
        self.swing_highs = []  
        self.swing_lows = []
        
        self.current_profit = 0.0 
        self.peak_profit = 0.0        
        self.last_profit_close_time = 0
        self.profit_close_interval = 1 

    def start(self):
        logger.info("Strategy ACTIVE | Strict Entry Mode | System Risk Management")

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

        # --- Track Peak Profit ---
        if positions > 0:
            if profit > self.peak_profit: self.peak_profit = profit
        else:
            self.peak_profit = 0.0

        # 1. PRIORITY: Check Signals (Only if active & no max positions)
        if self.active and positions < self.max_positions:
            self.check_crt_signals(symbol, bid, ask, candles)

        # 2. Analyze Trend Structure
        self.analyze_structure(symbol, candles)

        # 3. Manage Profit
        if positions > 0:
            self.check_and_close_profit(symbol)

        # 4. Status Log (Periodic)
        if time.time() % 10 < 1: 
            logger.info(f"Status: {symbol} | Trend: {self.trend} | PnL: {profit:.2f} | Peak: {self.peak_profit:.2f}")

    # --- STRICT SYSTEM CALCULATED RISK ---
    def calculate_safe_risk(self, direction, entry_price):
        """
        Calculates logical SL based on Structure and TP for 1:1.5 Risk-Reward.
        """
        sl = 0.0
        tp = 0.0
        is_gold = entry_price > 500
        min_dist = 2.00 if is_gold else 0.0020  
        
        if direction == "BUY":
            # SL below recent Swing Low
            if self.swing_lows:
                last_low = self.swing_lows[-1]['price']
                if (entry_price - last_low) < min_dist: sl = entry_price - min_dist
                else: sl = last_low
            else:
                sl = entry_price - min_dist 

            # TP = 1.5x Risk
            risk = entry_price - sl
            tp = entry_price + (risk * 1.5)

        elif direction == "SELL":
            # SL above recent Swing High
            if self.swing_highs:
                last_high = self.swing_highs[-1]['price']
                if (last_high - entry_price) < min_dist: sl = entry_price + min_dist
                else: sl = last_high
            else:
                sl = entry_price + min_dist 

            # TP = 1.5x Risk
            risk = sl - entry_price
            tp = entry_price - (risk * 1.5)

        return float(sl), float(tp)

    def validate_signal_quality(self, candle, type):
        """
        Ensures the candle is a valid Rejection Candle (Hammer/Shooting Star).
        Returns True only if the wick is significant.
        """
        body = abs(candle['close'] - candle['open'])
        upper_wick = candle['high'] - max(candle['open'], candle['close'])
        lower_wick = min(candle['open'], candle['close']) - candle['low']
        
        total_range = candle['high'] - candle['low']
        if total_range == 0: return False

        if type == "BUY":
            # Require Lower Wick to be at least 2x the Body (Hammer)
            # OR Lower Wick is > 50% of total range
            if lower_wick > (body * 1.5) or lower_wick > (total_range * 0.5):
                return True
        elif type == "SELL":
            # Require Upper Wick to be at least 2x the Body (Shooting Star)
            # OR Upper Wick is > 50% of total range
            if upper_wick > (body * 1.5) or upper_wick > (total_range * 0.5):
                return True
        
        return False

    def predict_momentum(self, candles):
        try:
            c1 = candles[1] 
            c2 = candles[2]
            ha_close = (c1['open'] + c1['high'] + c1['low'] + c1['close']) / 4
            ha_open = (c2['open'] + c2['close']) / 2
            
            # Body Size Check
            body_size = abs(c1['close'] - c1['open'])
            avg_body = abs(c2['close'] - c2['open'])
            is_strong = body_size > (avg_body * 0.5)

            if ha_close > ha_open and is_strong: return "BULLISH"
            elif ha_close < ha_open and is_strong: return "BEARISH"
            return "NEUTRAL"
        except:
            return "NEUTRAL"

    def check_crt_signals(self, symbol, bid, ask, candles):
        c_range = candles[self.crt_lookback]    
        c_signal = candles[self.crt_signal_idx] 
        range_high = c_range['high']
        range_low = c_range['low']

        market_sentiment = self.news_engine.get_market_sentiment()
        candle_prediction = self.predict_momentum(candles) 

        # 1. BUY SIGNAL LOGIC
        # Signal: Wick broke below range_low but closed above it
        if c_signal['low'] < range_low and c_signal['close'] > range_low:
            
            # --- STRICT FILTER 1: Trend Alignment ---
            if self.trend == "UPTREND": 
                
                # --- STRICT FILTER 2: Candle Shape Quality ---
                if self.validate_signal_quality(c_signal, "BUY"):
                    
                    # --- STRICT FILTER 3: Confluence ---
                    if market_sentiment == "BULLISH" or candle_prediction == "BULLISH":
                        
                        # ALL CHECKS PASSED -> EXECUTE
                        sl, tp = self.calculate_safe_risk("BUY", ask)
                        logger.info(f"✅ STRICT BUY SIGNAL | Trend: {self.trend} | Risk: SL {sl:.2f} TP {tp:.2f}")
                        self.execute_trade("BUY", symbol, self.lot_size, "STRICT_CRT", sl, tp)
                        self.connector.send_draw_command(f"CRT_{c_range['time']}", range_high, range_low, self.crt_lookback, self.crt_signal_idx, 65280) # Green Box
                        return
                    else:
                        logger.info("❌ Skipped BUY: No Confluence (News/Candle Neutral)")
                else:
                    # Debug log to ensure we know why it didn't trade
                    # logger.info("❌ Skipped BUY: Weak Candle Shape") 
                    pass
            elif self.trend == "DOWNTREND":
                 # logger.info("❌ Skipped BUY: Against Downtrend")
                 pass

        # 2. SELL SIGNAL LOGIC
        # Signal: Wick broke above range_high but closed below it
        elif c_signal['high'] > range_high and c_signal['close'] < range_high:
            
            # --- STRICT FILTER 1: Trend Alignment ---
            if self.trend == "DOWNTREND":
                
                # --- STRICT FILTER 2: Candle Shape Quality ---
                if self.validate_signal_quality(c_signal, "SELL"):
                    
                    # --- STRICT FILTER 3: Confluence ---
                    if market_sentiment == "BEARISH" or candle_prediction == "BEARISH":
                        
                        # ALL CHECKS PASSED -> EXECUTE
                        sl, tp = self.calculate_safe_risk("SELL", bid)
                        logger.info(f"✅ STRICT SELL SIGNAL | Trend: {self.trend} | Risk: SL {sl:.2f} TP {tp:.2f}")
                        self.execute_trade("SELL", symbol, self.lot_size, "STRICT_CRT", sl, tp)
                        self.connector.send_draw_command(f"CRT_{c_range['time']}", range_high, range_low, self.crt_lookback, self.crt_signal_idx, 255) # Red Box
                        return
                    else:
                        logger.info("❌ Skipped SELL: No Confluence (News/Candle Neutral)")

    def analyze_structure(self, symbol, candles):
        swings = [] 
        lookback = min(len(candles) - 2, 50)
        for i in range(2, lookback): 
            c_curr = candles[i]
            c_prev = candles[i+1]
            c_next = candles[i-1]
            # Simple Swing High/Low Detection
            if c_curr['high'] > c_prev['high'] and c_curr['high'] > c_next['high']:
                swings.append({'type': 'H', 'price': c_curr['high'], 'index': i, 'time': c_curr['time']})
            elif c_curr['low'] < c_prev['low'] and c_curr['low'] < c_next['low']:
                swings.append({'type': 'L', 'price': c_curr['low'], 'index': i, 'time': c_curr['time']})

        swings.sort(key=lambda x: x['index'], reverse=True)
        self.swing_highs = [s for s in swings if s['type'] == 'H']
        self.swing_lows = [s for s in swings if s['type'] == 'L']
        
        # Trend Determination based on last 2 swings
        if len(self.swing_highs) >= 2 and len(self.swing_lows) >= 2:
            h1 = self.swing_highs[-1]['price']
            h2 = self.swing_highs[-2]['price']
            l1 = self.swing_lows[-1]['price']
            l2 = self.swing_lows[-2]['price']
            if h1 > h2 and l1 > l2: self.trend = "UPTREND"
            elif h1 < h2 and l1 < l2: self.trend = "DOWNTREND"
            else: self.trend = "NEUTRAL"
        
        # Visuals
        if time.time() % 5 < 0.1:
            for k in range(len(swings) - 1):
                s1 = swings[k]
                s2 = swings[k+1]
                line_name = f"ZZ_{s1['time']}_{s2['time']}"
                color = 32768 if s1['type'] == 'L' else 255 
                self.connector.send_trend_command(line_name, s1['index'], s1['price'], s2['index'], s2['price'], color, 2)

    def execute_trade(self, direction, symbol, volume, reason, sl, tp):
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
    def _update_range_from_history(self, candles): pass