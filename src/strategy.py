import logging
import time
import pandas as pd
import numpy as np
from datetime import datetime

logger = logging.getLogger("Strategy")

class TradingStrategy:
    def __init__(self, connector, news_engine, config, webhook=None):
        self.connector = connector
        self.active = True
        
        self.lot_size = config.get('auto_trading', {}).get('lot_size', 0.01)
        self.trade_cooldown = 15.0       
        self.target_timeframe = "5min" 
        self.strategy_mode = "CONFLUENCE" 
        
        # Filters
        self.use_trend_filter = True
        self.use_zone_filter = True
        
        self.webhook = webhook
        self.last_trade_time = 0
        self.last_status_time = 0
        self.last_hist_req = 0
        self.trend = "NEUTRAL"
        self.support_zones = []     
        self.resistance_zones = []
        
        # Performance Cache
        self.last_zone_analysis_time = 0
        
        # Default settings
        self.rsi_period = 14
        self.use_profit_management = True
        self.min_profit_target = 0.10
        self.break_even_activation = 0.50
        self.break_even_active = False
        self.current_profit = 0.0

    def update_timeframe(self, new_tf):
        if self.target_timeframe == new_tf: return
        logger.info(f"🔄 Strategy sync: TF changed to {new_tf}")
        self.target_timeframe = new_tf
        self.last_zone_analysis_time = 0 # Force refresh
        
        # Mapping to send clean command
        self.connector.change_timeframe("XAUUSDm", new_tf) # Symbol usually updated dynamically

    def on_tick(self, symbol, bid, ask, balance, profit, acct_name, positions, buy_count, sell_count, avg_entry, candles=None):
        current_time = time.time()
        
        # 1. SYNC CHECK
        tf_map = {"1min": 1, "5min": 5, "15min": 15, "30min": 30, "H1": 60, "H4": 240}
        tf_minutes = tf_map.get(self.target_timeframe, 5)

        if candles and len(candles) > 2:
            data_diff = (candles[1]['time'] - candles[0]['time']) // 60
            data_minutes = data_diff if data_diff > 0 else 5
            
            # If mismatch, request history and STOP processing
            if data_minutes != tf_minutes:
                if current_time - self.last_hist_req > 5:
                    logger.info(f"⏳ Syncing data... Target: {self.target_timeframe} | Received: {data_minutes}min candles")
                    self.connector.request_history(symbol, 1000)
                    self.connector.change_timeframe(symbol, self.target_timeframe) # Force Switch again
                    self.last_hist_req = current_time
                return

        # 2. ANALYSIS
        self.analyze_structure_zones(symbol, candles)
        self.analyze_trend(candles)

        # 3. TRADING LOGIC
        actual_positions = max(positions, len(self.connector.open_positions))
        if self.active and actual_positions < 1:
            if (time.time() - self.last_trade_time) > self.trade_cooldown:
                self.check_signals_confluence(symbol, bid, ask, candles)

        self.current_profit = profit
        if positions > 0: self.check_and_close_profit(symbol)

    def analyze_trend(self, candles):
        try:
            df = pd.DataFrame(candles)
            ema200 = df['close'].ewm(span=200, adjust=False).mean().iloc[-1]
            current = df['close'].iloc[-1]
            self.trend = "BULLISH" if current > ema200 else "BEARISH"
        except: self.trend = "NEUTRAL"

    def analyze_structure_zones(self, symbol, candles):
        if not candles: return
        
        # PERFORMANCE: Only calculate when new candle closes
        last_time = candles[-1]['time']
        if self.last_zone_analysis_time == last_time: return
        self.last_zone_analysis_time = last_time

        ts_candles = candles
        current_price = ts_candles[-1]['close']
        zone_tolerance = current_price * 0.0005 

        highs, lows = self._get_fractals(ts_candles)
        zones = self._cluster_levels(highs + lows, zone_tolerance)
        
        self.support_zones = [z for z in zones if z['top'] < current_price]
        self.resistance_zones = [z for z in zones if z['bottom'] > current_price]
        self.support_zones.sort(key=lambda x: x['top'], reverse=True)
        self.resistance_zones.sort(key=lambda x: x['bottom'])
        
        self._draw_zones(symbol)

    def _draw_zones(self, symbol):
        for i, zone in enumerate(self.support_zones[:2]):
            self.connector.send_draw_command(f"Supp_{i}", zone['top'], zone['bottom'], 100, 0, "3498db") 
        for i, zone in enumerate(self.resistance_zones[:2]):
            self.connector.send_draw_command(f"Res_{i}", zone['top'], zone['bottom'], 100, 0, "e74c3c") 

    def _get_fractals(self, candles, window=2):
        highs = []; lows = []
        if len(candles) < (window * 2 + 1): return [], []
        for i in range(window, len(candles) - window):
            curr = candles[i]
            if all(candles[i-j]['high'] <= curr['high'] for j in range(1, window + 1)): highs.append(curr['high'])
            if all(candles[i-j]['low'] >= curr['low'] for j in range(1, window + 1)): lows.append(curr['low'])
        return highs, lows

    def _cluster_levels(self, levels, threshold):
        if not levels: return []
        levels.sort()
        zones = []; current = [levels[0]]
        for i in range(1, len(levels)):
            if levels[i] - current[-1] <= threshold: current.append(levels[i])
            else:
                zones.append({'top': max(current), 'bottom': min(current), 'center': sum(current)/len(current)})
                current = [levels[i]]
        if current: zones.append({'top': max(current), 'bottom': min(current), 'center': sum(current)/len(current)})
        return zones

    def _make_zone_dict(self, cluster):
        return {'top': max(cluster), 'bottom': min(cluster), 'center': sum(cluster)/len(cluster), 'count': len(cluster)}

    def _get_nearest_zone(self, price, is_support):
        zones = self.support_zones if is_support else self.resistance_zones
        if not zones: return None
        return min(zones, key=lambda z: abs(price - z['center']))

    # --- MAIN STRATEGY LOGIC ---
    def check_signals_confluence(self, symbol, bid, ask, candles):
        """
        STRICT CONFLUENCE: Trend + Zone + Trigger
        1. Trend: 200 EMA
        2. Structure: Support/Resistance Zone
        3. Trigger: Candle Pattern + RSI Reset
        """
        atr = self.calculate_atr(candles)
        rsi, _, _ = self.calculate_indicators(candles)
        pattern = self.detect_candle_patterns(candles)
        
        is_uptrend = "BULLISH" in self.trend
        is_downtrend = "BEARISH" in self.trend

        # Check Zones
        near_supp = self._get_nearest_zone(bid, is_support=True)
        on_support = False
        supp_dist = 9999
        if near_supp:
            supp_dist = abs(bid - near_supp['top'])
            if supp_dist < (atr * 1.5): on_support = True
            
        near_res = self._get_nearest_zone(ask, is_support=False)
        on_resistance = False
        res_dist = 9999
        if near_res:
            res_dist = abs(near_res['bottom'] - ask)
            if res_dist < (atr * 1.5): on_resistance = True

        # BUY LOGIC
        if is_uptrend and on_support:
            # RSI < 60 (Not overbought) + Bullish Pattern
            if rsi < 60 and pattern in ["BULLISH_ENGULFING", "HAMMER"]:
                if self._check_filters("BUY", ask):
                    sl_dist = atr * 2.0
                    sl = bid - sl_dist
                    tp = bid + (sl_dist * 2.0)
                    
                    logger.info(f"⚡ BUY SIGNAL DETECTED | {symbol}")
                    logger.info(f"   ├── Price: {bid:.2f} | RSI: {rsi:.1f} | Trend: {self.trend}")
                    logger.info(f"   ├── Trigger: {pattern} at Support Zone {near_supp['top']:.2f} (Dist: {supp_dist:.2f})")
                    
                    self.execute_trade("BUY", symbol, self.lot_size, f"Conf_Bounce_{pattern}", sl, tp)

        # SELL LOGIC
        elif is_downtrend and on_resistance:
             # RSI > 40 (Not oversold) + Bearish Pattern
            if rsi > 40 and pattern in ["BEARISH_ENGULFING", "SHOOTING_STAR"]:
                if self._check_filters("SELL", bid):
                    sl_dist = atr * 2.0
                    sl = ask + sl_dist
                    tp = ask - (sl_dist * 2.0)
                    
                    logger.info(f"⚡ SELL SIGNAL DETECTED | {symbol}")
                    logger.info(f"   ├── Price: {bid:.2f} | RSI: {rsi:.1f} | Trend: {self.trend}")
                    logger.info(f"   ├── Trigger: {pattern} at Resistance Zone {near_res['bottom']:.2f} (Dist: {res_dist:.2f})")
                    
                    self.execute_trade("SELL", symbol, self.lot_size, f"Conf_Reject_{pattern}", sl, tp)

    def get_prediction_score(self, symbol, bid, ask, candles):
        """Simplified for Logging purposes."""
        if not candles or len(candles) < 50: return 0, "NEUTRAL"
        rsi, macd, macd_sig = self.calculate_indicators(candles)
        buy_str = 0; sell_str = 0
        
        if rsi < 50: buy_str += 1
        else: sell_str += 1
        
        if "BULLISH" in self.trend: buy_str += 1
        elif "BEARISH" in self.trend: sell_str += 1
        
        if buy_str > sell_str: return 75, "BUY"
        elif sell_str > buy_str: return 75, "SELL"
        else: return 50, "NEUTRAL"

    # --- EXECUTION & FILTERS ---
    def _is_trading_time(self):
        if not self.use_time_filter: return True
        try:
            if self.time_zone == "Auto":
                for session_name, config in self.SESSIONS.items():
                    tz = ZoneInfo(config['tz'])
                    now = datetime.now(tz)
                    hour = now.hour; start = config['start']; end = config['end']
                    is_active = (start <= hour < end) if start <= end else (hour >= start or hour < end)
                    if is_active:
                        self.active_session_name = session_name
                        return True
                self.active_session_name = "Closed"
                return False
            # Fixed Time logic (Simplified)
            now = datetime.now()
            return (self.start_hour <= now.hour < self.end_hour)
        except: return True

    def _check_filters(self, direction, current_price):
        if self.news_engine and self.news_engine.trading_pause:
            self._log_skip("News Filter: Trading PAUSED (High Impact).")
            return False
        if not self._is_trading_time():
            self._log_skip(f"Time Filter: Outside trading hours.")
            return False
        return True

    def _log_skip(self, message):
        if time.time() - self.last_log_time > 15:
            logger.info(f"⚠️ Filter Skip: {message}")
            self.last_log_time = time.time()

    def execute_trade(self, direction, symbol, volume, reason, sl, tp):
        self.last_trade_time = time.time()
        success = self.connector.send_command(direction, symbol, volume, sl, tp, 0)
        if success:
            logger.info(f"🚀 ORDER SENT: {direction} {symbol} | Lot: {volume} | SL: {sl:.2f} | TP: {tp:.2f} | {reason}")
            if self.webhook:
                self.webhook.notify_trade(direction, symbol, volume, sl, tp, reason)
        else:
            logger.error(f"❌ EXECUTION FAILED: {direction} {symbol} - Check Connector/MT5 Connection")

    def check_and_close_profit(self, symbol):
        if time.time() - self.last_profit_close_time < self.profit_close_interval: return
        self.last_profit_close_time = time.time()
        try:
            if not self.break_even_active and self.current_profit >= self.break_even_activation:
                msg = f"🛡️ BREAK-EVEN ACTIVATED: Profit ${self.current_profit:.2f}. Locking."
                logger.info(msg)
                self.break_even_active = True
                if self.webhook: self.webhook.notify_protection(symbol, msg)
            
            if self.current_profit >= self.min_profit_target:
                logger.info(f"💰 TARGET HIT: ${self.current_profit:.2f}. Closing Position.")
                self.connector.close_profit(symbol)
                if self.webhook: self.webhook.notify_close(symbol, self.current_profit, "Target Hit")
                self.break_even_active = False
                self.peak_profit = 0.0
        except Exception as e:
            logger.error(f"❌ Error in check_and_close_profit: {e}")

    # --- TELEGRAM HANDLERS (Simplified) ---
    def _handle_telegram_positions_command(self):
        raw_positions = getattr(self.connector, 'open_positions', [])
        self.webhook.notify_active_positions(raw_positions if raw_positions else [])

    def _handle_telegram_mode_command(self):
        self.active = not self.active
        state = "ACTIVE" if self.active else "PAUSED"
        self.webhook.send_message(f"🔄 **Strategy Updated**\nNew State: **{state}**")

    def _handle_telegram_trade(self, action, symbol=None, volume=None):
        if not symbol: return
        if not volume: volume = self.lot_size
        self.connector.send_command(action, symbol, volume, 0.0, 0.0, 0)
        self.webhook.send_message(f"Sent {action} for {symbol}")

    def _handle_telegram_close_ticket(self, ticket_id):
        self.connector.close_ticket(ticket_id)
        self.webhook.send_message(f"Closing Ticket #{ticket_id}")

    def _handle_telegram_news_command(self):
        if self.news_engine:
            self.news_engine.fetch_latest()
            news_str = self.news_engine.get_latest_news(3)
            self.webhook.send_message(f"📰 *Latest News*\n{news_str}" if news_str else "No news.")

    def _handle_telegram_accounts_command(self):
        acct = self.connector.account_info
        if acct:
            self.webhook.send_message(f"🔑 Account: {acct.get('name')}\nBalance: ${acct.get('balance')}")

    def _handle_telegram_select_account(self, idx):
        self.webhook.send_message("Account switching not implemented in simple mode.")

    def _handle_telegram_status_command(self):
        self.webhook.notify_account_summary(self.last_balance, self.current_profit, self.last_positions_count, self.strategy_mode, self.lot_size)

    def _handle_telegram_analysis(self):
        if self.last_candles:
            score, signal = self.get_prediction_score(self.last_symbol, 0, 0, self.last_candles)
            self.webhook.notify_analysis(self.last_symbol, self.trend, 0, 0, score, signal, 0, "N/A")

    def _handle_telegram_strategy_select(self, mode_name):
        self.webhook.send_message("Strategy mode is fixed to CONFLUENCE.")

    def _handle_telegram_lot_change(self, delta):
        self.lot_size = round(max(0.01, self.lot_size + delta), 2)
        self.webhook.send_message(f"Lot size: {self.lot_size}")