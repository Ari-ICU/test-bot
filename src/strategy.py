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
        self.max_trade_duration = 0 
        self.min_profit_target = 0.50  
        
        # CRT Settings
        self.crt_lookback = 2      
        self.crt_signal_idx = 1    
        
        # --- State ---
        self.pending_setup = None  
        self.trend = "NEUTRAL"
        self.swing_highs = []  
        self.swing_lows = []
        
        self.current_profit = 0.0 
        self.last_profit_close_time = 0
        self.profit_close_interval = 1 

    def start(self):
        logger.info("CRT Strategy | Retest Mode ACTIVE | News Filter ACTIVE | NO SL")

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

        # 1. PRIORITY: Check Signals
        if self.active and positions < self.max_positions:
            self.check_crt_signals(symbol, bid, ask, candles)

        # 2. Analyze Trend
        self.analyze_structure(symbol, candles)

        # 3. Manage Profit (Auto Close)
        self.check_and_close_profit(symbol)

        # 4. Status Log
        if time.time() % 10 < 1: 
            status = "Scanning"
            if self.pending_setup: status = f"WAITING FOR TEST ({self.pending_setup['direction']})"
            logger.info(f"Status: {symbol} | Trend: {self.trend} | PnL: {profit:.2f} | State: {status}")

    def check_crt_signals(self, symbol, bid, ask, candles):
        # --- A. EXECUTE PENDING SETUP (THE RETEST) ---
        if self.pending_setup:
            setup = self.pending_setup
            if time.time() - setup['timestamp'] > 600: 
                logger.info("⚠️ Signal Timed Out")
                self.pending_setup = None
                return

            if setup['direction'] == "BUY":
                if ask <= (setup['entry_level'] + setup['buffer']):
                    logger.info(f"⚡ RETEST CONFIRMED ⚡ Price {ask:.2f} tested {setup['entry_level']:.2f}")
                    self.execute_trade("BUY", symbol, self.lot_size, "CRT_RETEST", 0.0, setup['tp'])
                    self.pending_setup = None
                    return
                
            elif setup['direction'] == "SELL":
                if bid >= (setup['entry_level'] - setup['buffer']):
                    logger.info(f"⚡ RETEST CONFIRMED ⚡ Price {bid:.2f} tested {setup['entry_level']:.2f}")
                    self.execute_trade("SELL", symbol, self.lot_size, "CRT_RETEST", 0.0, setup['tp'])
                    self.pending_setup = None
                    return

        # --- B. FIND NEW SIGNALS ---
        c_range = candles[self.crt_lookback]    
        c_signal = candles[self.crt_signal_idx] 
        if self.pending_setup and self.pending_setup['candle_time'] == c_signal['time']: return 

        range_high = c_range['high']
        range_low = c_range['low']

        if candles[0]['close'] > 500: # Gold
            tp_dist = 5.00
            retest_buffer = 0.50
        else: # Forex
            tp_dist = 0.0030
            retest_buffer = 0.0005

        # --- GET MARKET SENTIMENT FROM NEWS ENGINE ---
        market_sentiment = self.news_engine.get_market_sentiment()

        # 1. BULLISH SWEEP (BUY SIGNAL)
        if c_signal['low'] < range_low and c_signal['close'] > range_low:
            if self.trend != "DOWNTREND":
                # *** CONFLUENCE CHECK: NEWS MUST BE BULLISH ***
                if market_sentiment == "BULLISH":
                    logger.info(f"👀 CRT BUY FOUND (+News BULLISH) | Range Low: {range_low}")
                    self.pending_setup = { 
                        'direction': "BUY", 
                        'entry_level': range_low, 
                        'buffer': retest_buffer, 
                        'sl': 0.0,  
                        'tp': ask + tp_dist, 
                        'timestamp': time.time(), 
                        'candle_time': c_signal['time'] 
                    }
                    self.connector.send_draw_command(f"CRT_{c_range['time']}", range_high, range_low, self.crt_lookback, self.crt_signal_idx, 16776960)
                else:
                    if time.time() % 30 < 1: # Log rarely to avoid spam
                        logger.info(f"⛔ BUY Signal Ignored: Strategy=BUY but News={market_sentiment}")

        # 2. BEARISH SWEEP (SELL SIGNAL)
        elif c_signal['high'] > range_high and c_signal['close'] < range_high:
            if self.trend != "UPTREND":
                # *** CONFLUENCE CHECK: NEWS MUST BE BEARISH ***
                if market_sentiment == "BEARISH":
                    logger.info(f"👀 CRT SELL FOUND (+News BEARISH) | Range High: {range_high}")
                    self.pending_setup = { 
                        'direction': "SELL", 
                        'entry_level': range_high, 
                        'buffer': retest_buffer, 
                        'sl': 0.0, 
                        'tp': bid - tp_dist, 
                        'timestamp': time.time(), 
                        'candle_time': c_signal['time'] 
                    }
                    self.connector.send_draw_command(f"CRT_{c_range['time']}", range_high, range_low, self.crt_lookback, self.crt_signal_idx, 16776960)
                else:
                    if time.time() % 30 < 1:
                        logger.info(f"⛔ SELL Signal Ignored: Strategy=SELL but News={market_sentiment}")

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
        logger.info(f"🚀 EXECUTED {direction} {symbol} | Vol: {volume} | SL: {sl} | TP: {tp:.2f}")

    def check_and_close_profit(self, symbol):
        if time.time() - self.last_profit_close_time < self.profit_close_interval: return
        self.last_profit_close_time = time.time()
        
        if self.current_profit >= self.min_profit_target:
            logger.info(f"💰 PROFIT TARGET HIT: {self.current_profit:.2f} >= {self.min_profit_target:.2f}")
            self.connector.close_profit(symbol)

    def analyze_patterns(self, candles):
        return {'fvg_zone': None, 'bullish_fvg': False, 'bearish_fvg': False}
    def _update_range_from_history(self, candles): pass