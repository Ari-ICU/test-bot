import logging
import time
import pandas as pd
import numpy as np
from datetime import datetime
try:
    from zoneinfo import ZoneInfo
except ImportError:
    from backports.zoneinfo import ZoneInfo

import warnings
warnings.filterwarnings("ignore", message=".*'T' is deprecated.*")

logger = logging.getLogger("Strategy")

class TradingStrategy:
    def __init__(self, connector, news_engine, config, webhook=None):
        self.connector = connector
        self.news_engine = news_engine
        self.active = True
        
        # --- STRATEGY CONFIGURATION ---
        self.risk_reward_ratio = 1.5     
        self.max_positions = 1           
        self.lot_size = config.get('auto_trading', {}).get('lot_size', 0.01)
        self.trade_cooldown = 15.0       
        
        # --- TIMEFRAME STATE ---
        self.target_timeframe = "5min" 
        
        # --- MODES & FILTERS ---
        self.strategy_mode = "CONFLUENCE" # Updated name
        self.use_trend_filter = True
        self.use_zone_filter = True
        
        # Store config
        self.config = config
        
        # WEBHOOK
        self.webhook = webhook
        if self.webhook:
            self._setup_webhook_handlers()
        
        self.ui_callback = None 
        
        # --- MARKET SESSIONS ---
        self.SESSIONS = {
            "London": {"start": 8, "end": 17, "tz": "Europe/London"},
            "New York": {"start": 8, "end": 17, "tz": "America/New_York"},
            "Tokyo": {"start": 9, "end": 18, "tz": "Asia/Tokyo"},
            "Sydney": {"start": 7, "end": 16, "tz": "Australia/Sydney"}
        }

        # --- TIME FILTER ---
        self.use_time_filter = True
        self.time_zone = "Auto" 
        self.start_hour = 8   
        self.end_hour = 20    

        # --- PROFIT SETTINGS ---
        self.use_profit_management = True
        self.min_profit_target = 0.10    
        
        # --- INDICATOR SETTINGS (CONFLUENCE ONLY) ---
        self.rsi_period = 14
        self.macd_fast = 12
        self.macd_slow = 26
        self.macd_signal = 9
        
        # --- State ---
        self.last_trade_time = 0           
        self.last_log_time = 0           
        self.last_status_time = 0        
        self.last_hist_req = 0           
        self.trend = "NEUTRAL"
        self.active_session_name = "None"
        
        # --- S&R Zones ---
        self.support_zones = []     
        self.resistance_zones = []
        self.zone_min_touches = 2   # Increased to 2 for stronger levels
        self.zone_tolerance = 0.0   
        self.last_draw_time = 0     

        self.current_profit = 0.0 
        self.peak_profit = 0.0        
        self.last_profit_close_time = 0
        self.profit_close_interval = 1 
        self.last_positions_count = 0    
        self.last_balance = 0.0
        self.last_positions_list = []
        self.last_candles = None
        self.last_symbol = None
        
        # --- TRADE PROTECTION ---
        self.break_even_activation = 0.50  
        self.break_even_active = False

    def _setup_webhook_handlers(self):
        self.webhook.on_status_command = self._handle_telegram_status_command
        self.webhook.on_positions_command = self._handle_telegram_positions_command
        self.webhook.on_mode_command = self._handle_telegram_mode_command
        self.webhook.on_trade_command = self._handle_telegram_trade
        self.webhook.on_close_command = self._handle_telegram_close_ticket
        self.webhook.on_news_command = self._handle_telegram_news_command
        self.webhook.on_accounts_command = self._handle_telegram_accounts_command
        self.webhook.on_account_select = self._handle_telegram_select_account
        self.webhook.on_analysis_command = self._handle_telegram_analysis
        self.webhook.on_strategy_select = self._handle_telegram_strategy_select
        self.webhook.on_lot_change = self._handle_telegram_lot_change
        self.webhook.on_timeframe_select = self.update_timeframe

    def start(self):
        tz_info = f"Zone: {self.time_zone}" if self.time_zone != "Auto" else "Zone: AUTO (Rotation)"
        logger.info(f"✅ Strategy STARTED | Mode: {self.strategy_mode} | {tz_info}")

    def stop(self):
        self.active = False
        logger.info("🛑 Strategy STOPPED")

    def set_active(self, active):
        self.active = bool(active)
        state = "ACTIVE" if self.active else "PAUSED"
        logging.info(f"🔄 Strategy State Changed: {state}")

    def reset_state(self):
        self.trend = "NEUTRAL"
        self.support_zones = []
        self.resistance_zones = []
        self.peak_profit = 0.0
        self.last_positions_list = []
        logging.info("🧹 Strategy State Reset (New Symbol/TF)")

    def get_session_times(self):
        parts = []
        for city, data in self.SESSIONS.items():
            parts.append(f"{city[:3]}:{data['start']:02d}-{data['end']:02d}")
        return " | ".join(parts)

    def update_timeframe(self, new_tf):
        if self.target_timeframe == new_tf: return
        logger.info(f"⏱️ Timeframe Changing: {self.target_timeframe} -> {new_tf}")
        self.target_timeframe = new_tf
        if self.last_symbol:
             self.connector.change_timeframe(self.last_symbol, new_tf)
        self.last_candles = None
        self.last_hist_req = time.time() 
        self.reset_state()
        if self.webhook:
            self.webhook.send_message(f"⌛ **Timeframe Changed**\nTarget: `{new_tf}`\nBuffering new data...")

    def on_tick(self, symbol, bid, ask, balance, profit, acct_name, positions, buy_count, sell_count, avg_entry, candles=None):
        current_time = time.time()
        server_time_str = "??:??:??"
        if candles and len(candles) > 0:
            server_time_str = datetime.fromtimestamp(candles[-1]['time']).strftime('%H:%M:%S')

        self.last_candles = candles
        self.last_symbol = symbol
        
        # 1. TIMEFRAME SYNC
        tf_map = {"1min": 1, "5min": 5, "15min": 15, "30min": 30, "H1": 60, "H4": 240}
        tf_minutes = tf_map.get(self.target_timeframe, 5)

        if candles and len(candles) > 2:
            data_diff = (candles[1]['time'] - candles[0]['time']) // 60
            data_minutes = data_diff if data_diff > 0 else 5
            if data_minutes != tf_minutes:
                if current_time - self.last_hist_req > 5:
                    logger.info(f"⏳ Syncing data... Target: {self.target_timeframe} | Received: {data_minutes}min candles")
                    self.connector.request_history(symbol, 1000)
                    self.last_hist_req = current_time
                return

        # 2. DATA CHECK
        min_needed = 200
        if not candles or len(candles) < min_needed:
            if current_time - self.last_hist_req > 5:
                self.connector.request_history(symbol, min_needed + 50)
                self.last_hist_req = current_time
            return

        if candles[0]['time'] > candles[-1]['time']:
            candles = candles[::-1]
        
        self.current_profit = profit 
        self.last_positions_count = positions
        if positions > 0 and profit > self.peak_profit: self.peak_profit = profit
        elif positions == 0: self.peak_profit = 0.0

        # 3. ANALYSIS
        self.analyze_structure_zones(symbol, candles)
        self.analyze_trend(candles)

        # 4. TRADING LOGIC (CONFLUENCE)
        actual_positions = max(positions, len(getattr(self.connector, 'open_positions', [])))
        if self.active and actual_positions < self.max_positions:
            if (time.time() - self.last_trade_time) > self.trade_cooldown:
                self.check_signals_confluence(symbol, bid, ask, candles)

        # 5. STATUS LOGGING (Improved)
        if current_time - self.last_status_time >= 10:
            self.last_status_time = current_time
            conf_score, conf_txt = self.get_prediction_score(symbol, bid, ask, candles)
            near_supp = self._get_nearest_zone(bid, is_support=True)
            s_val = f"{near_supp['top']:.2f}" if near_supp else "None"
            active_txt = "🟢 ON " if self.active else "🔴 OFF"
            
            # Cleaner formatting
            log_msg = (
                f"📊 {active_txt} | {symbol} [{tf_minutes}m] | "
                f"Trend: {self.trend.replace('_STRONG', '++').replace('_WEAK', '+')} | "
                f"Supp: {s_val} | "
                f"Signal: {conf_txt} | "
                f"PnL: {profit:+.2f}"
            )
            logger.info(log_msg)

        # 6. PNL TRACKING
        current_positions_list = getattr(self.connector, 'open_positions', [])
        if not hasattr(self, 'last_positions_list'): self.last_positions_list = current_positions_list

        if hasattr(self, 'last_balance') and self.last_balance != 0:
             realized_pnl = balance - self.last_balance
             last_tickets = {p['ticket']: p for p in self.last_positions_list}
             curr_tickets = {p['ticket']: p for p in current_positions_list}
             closed_tickets = [t_data for t_id, t_data in last_tickets.items() if t_id not in curr_tickets]
             if closed_tickets and self.webhook:
                 self.webhook.notify_close(symbol, realized_pnl, f"Closed {len(closed_tickets)} ticket(s)")
        
        self.last_positions_list = current_positions_list
        self.last_positions_count = positions
        self.last_balance = balance

        if positions > 0 and self.use_profit_management:
            self.check_and_close_profit(symbol)

    # --- CORE INDICATORS (KEPT) ---
    def calculate_atr(self, candles, window=14):
        try:
            if len(candles) < window + 1: return 0.0
            df = pd.DataFrame(candles)
            high_low = df['high'] - df['low']
            high_pc = (df['high'] - df['close'].shift(1)).abs()
            low_pc = (df['low'] - df['close'].shift(1)).abs()
            tr = pd.concat([high_low, high_pc, low_pc], axis=1).max(axis=1)
            atr = tr.rolling(window=window).mean().iloc[-1]
            return float(atr)
        except: return 0.0

    def calculate_indicators(self, candles):
        try:
            df = pd.DataFrame(candles)
            delta = df['close'].diff()
            gain = (delta.where(delta > 0, 0)).rolling(window=self.rsi_period).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(window=self.rsi_period).mean()
            rs = gain / loss
            df['rsi'] = 100 - (100 / (1 + rs))
            short_ema = df['close'].ewm(span=self.macd_fast, adjust=False).mean()
            long_ema = df['close'].ewm(span=self.macd_slow, adjust=False).mean()
            df['macd'] = short_ema - long_ema
            df['macd_signal'] = df['macd'].ewm(span=self.macd_signal, adjust=False).mean()
            last = df.iloc[-1] 
            return last['rsi'], last['macd'], last['macd_signal']
        except: return 50, 0, 0

    def detect_candle_patterns(self, candles):
        if len(candles) < 3: return "NONE"
        c1 = candles[-2]; c2 = candles[-1]
        # Engulfing
        if c1['close'] < c1['open'] and c2['close'] > c2['open']:
            if c2['close'] > c1['open'] and c2['open'] < c1['close']: return "BULLISH_ENGULFING"
        if c1['close'] > c1['open'] and c2['close'] < c2['open']:
            if c2['close'] < c1['open'] and c2['open'] > c1['close']: return "BEARISH_ENGULFING"
        
        # Pinbars
        body = abs(c2['close'] - c2['open'])
        lower_wick = min(c2['close'], c2['open']) - c2['low']
        upper_wick = c2['high'] - max(c2['close'], c2['open'])
        if lower_wick > (body * 2) and upper_wick < body: return "HAMMER"
        if upper_wick > (body * 2) and lower_wick < body: return "SHOOTING_STAR"
        return "NONE"

    def analyze_trend(self, candles):
        """Uses 200 EMA to determine global trend. Logs changes."""
        previous_trend = self.trend
        try:
            df = pd.DataFrame(candles)
            ema200 = df['close'].ewm(span=200, adjust=False).mean().iloc[-1]
            current = df['close'].iloc[-1]
            
            new_trend = "NEUTRAL"
            if current > ema200:
                new_trend = "BULLISH_STRONG" if current > (ema200 * 1.001) else "BULLISH_WEAK"
            else:
                new_trend = "BEARISH_STRONG" if current < (ema200 * 0.999) else "BEARISH_WEAK"
            
            self.trend = new_trend
            
            # Log Trend Change
            if self.trend != previous_trend:
                 logger.info(f"🌊 TREND SHIFT: {previous_trend} ➔ {self.trend} | Price: {current:.2f} | EMA200: {ema200:.2f}")
                 
        except: 
            self.trend = "NEUTRAL"

    # --- STRUCTURE / ZONES (KEPT) ---
    def analyze_structure_zones(self, symbol, candles):
        if not candles: return
        ts_candles = candles
        current_price = ts_candles[-1]['close']
        self.zone_tolerance = current_price * 0.0005 

        highs, lows = self._get_fractals(ts_candles)
        all_swings = highs + lows
        zones = self._cluster_levels(all_swings, threshold=self.zone_tolerance)
        
        self.support_zones = []
        self.resistance_zones = []
        for zone in zones:
            if zone['count'] >= self.zone_min_touches:
                if zone['top'] < current_price: self.support_zones.append(zone)
                elif zone['bottom'] > current_price: self.resistance_zones.append(zone)
        self.support_zones.sort(key=lambda x: x['top'], reverse=True)
        self.resistance_zones.sort(key=lambda x: x['bottom'])
        
        if time.time() - self.last_draw_time > 5.0:
            self._draw_zones(symbol); self.last_draw_time = time.time()

    def _draw_zones(self, symbol):
        for i, zone in enumerate(self.support_zones[:3]):
            self.connector.send_draw_command(f"Supp_{i}", zone['top'], zone['bottom'], 100, 0, "0x008000") 
        for i, zone in enumerate(self.resistance_zones[:3]):
            self.connector.send_draw_command(f"Res_{i}", zone['top'], zone['bottom'], 100, 0, "0x000080") 

    def _get_fractals(self, candles, window=2):
        highs = []; lows = []
        if len(candles) < (window * 2 + 1): return [], []
        for i in range(window, len(candles) - window):
            curr = candles[i]
            is_high = all(candles[i-j]['high'] <= curr['high'] and candles[i+j]['high'] <= curr['high'] for j in range(1, window + 1))
            if is_high: highs.append(curr['high'])
            is_low = all(candles[i-j]['low'] >= curr['low'] and candles[i+j]['low'] >= curr['low'] for j in range(1, window + 1))
            if is_low: lows.append(curr['low'])
        return highs, lows

    def _cluster_levels(self, levels, threshold):
        if not levels: return []
        levels.sort()
        zones = []; current_cluster = [levels[0]]
        for i in range(1, len(levels)):
            price = levels[i]
            if price - current_cluster[-1] <= threshold:
                current_cluster.append(price)
            else:
                zones.append(self._make_zone_dict(current_cluster))
                current_cluster = [price]
        if current_cluster: zones.append(self._make_zone_dict(current_cluster))
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