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
    # UPDATED INIT: Accepts webhook
    def __init__(self, connector, news_engine, config, webhook=None):
        self.connector = connector
        self.news_engine = news_engine
        self.active = True
        
        # --- STRATEGY CONFIGURATION ---
        self.risk_reward_ratio = 1.5     
        self.max_positions = 1           
        self.lot_size = config.get('auto_trading', {}).get('lot_size', 0.01)
        self.trade_cooldown = 15.0       
        
        # --- TIMEFRAME STATE (FIX) ---
        self.target_timeframe = "5min" # Remembers your choice
        
        # --- MODES & FILTERS ---
        self.strategy_mode = "U16_STRATEGY"  # Combined strategy
        self.use_trend_filter = True
        self.use_zone_filter = True
        
        # Store config
        self.config = config
        
        # USE THE SHARED WEBHOOK
        self.webhook = webhook

        if self.webhook:
            # Existing hooks...
            self.webhook.on_status_command = self._handle_telegram_status_command
            self.webhook.on_positions_command = self._handle_telegram_positions_command
            self.webhook.on_mode_command = self._handle_telegram_mode_command
            self.webhook.on_trade_command = self._handle_telegram_trade
            self.webhook.on_close_command = self._handle_telegram_close_ticket
            self.webhook.on_news_command = self._handle_telegram_news_command
            self.webhook.on_accounts_command = self._handle_telegram_accounts_command
            self.webhook.on_account_select = self._handle_telegram_select_account
            
            # NEW HOOKS
            self.webhook.on_analysis_command = self._handle_telegram_analysis
            self.webhook.on_strategy_select = self._handle_telegram_strategy_select
            self.webhook.on_lot_change = self._handle_telegram_lot_change
            self.webhook.on_timeframe_select = self.update_timeframe # <--- WIRED UP
        
        # --- UI CALLBACK (for profit/protection updates) ---
        self.ui_callback = None 
        
        # --- MARKET SESSIONS (Local Hours) ---
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
        
        # --- INDICATOR SETTINGS ---
        self.rsi_period = 14
        self.rsi_buy_threshold = 40      
        self.rsi_sell_threshold = 60     
        self.macd_fast = 12
        self.macd_slow = 26
        self.macd_signal = 9
        self.bb_period = 20
        self.bb_dev = 2.0
        self.ema_fast = 9
        self.ema_slow = 21
        self.stoch_k = 14
        self.stoch_d = 3
        self.stoch_overbought = 80
        self.stoch_oversold = 20
        self.ichi_tenkan = 9
        self.ichi_kijun = 26
        self.ichi_senkou_b = 52
        self.adx_period = 14
        self.crt_htf = 240
        self.crt_zone_size = 0.50 
        self.breakout_period = 20
        self.breakout_threshold = 1.5
        self.scalp_atr_mult = 0.5
        self.scalp_tp_mult = 1.0
        self.mr_bb_period = 20
        self.mr_bb_dev = 2.0
        self.mr_rsi_extreme = 70

        # --- State ---
        self.last_trade_time = 0           
        self.last_log_time = 0           
        self.last_status_time = 0        
        self.last_crt_diag_time = 0      
        self.last_crt_draw = 0           
        self.last_crt_summary_time = 0   
        self.last_hist_req = 0           
        self.trend = "NEUTRAL"
        self.active_session_name = "None"
        self.swing_highs = []  
        self.swing_lows = []
        
        # --- S&R Zones ---
        self.support_zones = []     
        self.resistance_zones = []
        self.zone_min_touches = 1   
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
        
        # --- TRADE PROTECTION ---
        self.break_even_activation = 0.50  
        self.break_even_active = False

    def start(self):
        tz_info = f"Zone: {self.time_zone}" if self.time_zone != "Auto" else "Zone: AUTO (Rotation)"
        logger.info(f"Strategy ACTIVE | Mode: {self.strategy_mode} | {tz_info}")

    def stop(self):
        self.active = False
        logger.info("Strategy PAUSED")

    def set_active(self, active):
        self.active = bool(active)
        state = "ACTIVE" if self.active else "PAUSED"
        logging.info(f"Strategy state set to: {state}")

    def reset_state(self):
        self.trend = "NEUTRAL"
        self.support_zones = []
        self.resistance_zones = []
        self.peak_profit = 0.0
        self.last_positions_list = []
        logging.info("Strategy state reset for new symbol/timeframe.")

    def get_session_times(self):
        parts = []
        for city, data in self.SESSIONS.items():
            parts.append(f"{city[:3]}:{data['start']:02d}-{data['end']:02d}")
        return " | ".join(parts)

    # --- NEW METHOD: Force Update Timeframe ---
    def update_timeframe(self, new_tf):
        if self.target_timeframe == new_tf:
            return

        logger.info(f"🔄 Switching Timeframe: {self.target_timeframe} -> {new_tf}")
        self.target_timeframe = new_tf
        
        # 1. Update Connector (Push the change)
        if hasattr(self.connector, 'set_timeframe'):
             self.connector.set_timeframe(new_tf)
        elif hasattr(self.connector, 'timeframe'):
             self.connector.timeframe = new_tf
        
        # 2. Reset internal data
        self.last_candles = None
        self.last_hist_req = 0 
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
        
        # --- FIX: USE TARGET TF IF CANDLES ARE LOADING ---
        if candles and len(candles) > 2:
            diff = (candles[1]['time'] - candles[0]['time']) // 60
            tf_minutes = diff if diff > 0 else 5
        else:
            # Fallback to target so logs are correct while waiting
            tf_map = {"1min": 1, "5min": 5, "15min": 15, "30min": 30, "H1": 60, "H4": 240}
            tf_minutes = tf_map.get(self.target_timeframe, 5)
        
        # Adjust min_needed based on TF
        if tf_minutes <= 1: min_needed = 1440 
        elif tf_minutes <= 5: min_needed = 300
        elif tf_minutes <= 30: min_needed = 150
        elif tf_minutes <= 60: min_needed = 100
        else: min_needed = 50
        
        htf_extra = 0
        if tf_minutes < 60 and self.use_trend_filter:
            htf_extra = 500  
        
        total_needed = min_needed + htf_extra
        
        if not candles or len(candles) < total_needed:
            if current_time - self.last_hist_req > 5:
                # Ensure connector knows the target TF
                self.connector.request_history(symbol, total_needed + 50)
                self.last_hist_req = current_time
                logging.info(f"Requesting {total_needed + 50} candles for {symbol} (Target: {self.target_timeframe})...")
            if candles and len(candles) > 0:
                self._log_skip(f"Gathering data... ({len(candles)}/{total_needed} candles)")
            return

        if candles[0]['time'] > candles[-1]['time']:
            candles = candles[::-1]
        
        self.current_profit = profit 
        self.last_positions_count = positions

        if positions > 0:
            if profit > self.peak_profit: self.peak_profit = profit
        else:
            self.peak_profit = 0.0

        if self.use_zone_filter: 
            self.analyze_structure_zones(symbol, candles)
            
        if self.use_trend_filter: 
            self.analyze_trend(candles)

        actual_positions = max(positions, len(getattr(self.connector, 'open_positions', [])))
        
        if self.active and actual_positions < self.max_positions:
            if (time.time() - self.last_trade_time) > self.trade_cooldown:
                # Always use combined U16 strategy, adaptive to TF
                self.check_signals_u16(symbol, bid, ask, candles, tf_minutes)

        if current_time - self.last_status_time >= 10:
            self.last_status_time = current_time
            conf_score, conf_txt = self.get_prediction_score(symbol, bid, ask, candles)
            near_supp = self._get_nearest_zone(bid, is_support=True)
            s_val = f"{near_supp['top']:.2f}" if near_supp else "None"
            active_txt = "AUTO-ON" if self.active else "AUTO-OFF"
            logger.info(f"📊 [MT5:{server_time_str}] {active_txt} | {symbol} | Mode: {self.strategy_mode} | TF: {tf_minutes}min | S: {s_val} | Conf: {conf_score}% | PnL: {profit:.2f}")

        current_positions_list = getattr(self.connector, 'open_positions', [])
        
        if not hasattr(self, 'last_positions_list'):
            self.last_positions_list = current_positions_list

        if hasattr(self, 'last_balance') and self.last_balance != 0:
             realized_pnl = balance - self.last_balance
             last_tickets = {p['ticket']: p for p in self.last_positions_list}
             curr_tickets = {p['ticket']: p for p in current_positions_list}
             closed_tickets = [t_data for t_id, t_data in last_tickets.items() if t_id not in curr_tickets]
             count_closed = len(closed_tickets)
             
             if count_closed > 0 and self.webhook:
                 if count_closed == 1:
                     t = closed_tickets[0]
                     msg_reason = f"Ticket #{t['ticket']}"
                     self.webhook.notify_close(t['symbol'], realized_pnl, msg_reason)
                 else:
                     msg_reason = f"Batch Close ({count_closed} trades)"
                     self.webhook.notify_close(symbol, realized_pnl, msg_reason)
        
        self.last_positions_list = current_positions_list
        self.last_positions_count = positions
        self.last_balance = balance

        if positions > 0 and self.use_profit_management:
            self.check_and_close_profit(symbol)
            if self.ui_callback:
                self.ui_callback("profit_update", {"profit": self.current_profit, "positions": positions})

    # --- HELPER CALCULATIONS ---
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

    def calculate_stochastic(self, candles):
        try:
            df = pd.DataFrame(candles)
            low_min = df['low'].rolling(window=self.stoch_k).min()
            high_max = df['high'].rolling(window=self.stoch_k).max()
            df['k_percent'] = 100 * ((df['close'] - low_min) / (high_max - low_min))
            df['d_percent'] = df['k_percent'].rolling(window=self.stoch_d).mean()
            return df.iloc[-1]['k_percent'], df.iloc[-1]['d_percent']
        except: return 50, 50

    def calculate_adx(self, candles):
        try:
            df = pd.DataFrame(candles)
            df['up_move'] = df['high'] - df['high'].shift(1)
            df['down_move'] = df['low'].shift(1) - df['low']
            df['plus_dm'] = np.where((df['up_move'] > df['down_move']) & (df['up_move'] > 0), df['up_move'], 0)
            df['minus_dm'] = np.where((df['down_move'] > df['up_move']) & (df['down_move'] > 0), df['down_move'], 0)
            h_l = df['high'] - df['low']
            h_pc = (df['high'] - df['close'].shift(1)).abs()
            l_pc = (df['low'] - df['close'].shift(1)).abs()
            df['tr'] = pd.concat([h_l, h_pc, l_pc], axis=1).max(axis=1)
            window = self.adx_period
            df['tr_smooth'] = df['tr'].rolling(window).sum()
            df['plus_di'] = 100 * (df['plus_dm'].rolling(window).sum() / df['tr_smooth'])
            df['minus_di'] = 100 * (df['minus_dm'].rolling(window).sum() / df['tr_smooth'])
            df['dx'] = 100 * abs(df['plus_di'] - df['minus_di']) / (df['plus_di'] + df['minus_di'])
            df['adx'] = df['dx'].rolling(window).mean()
            return df.iloc[-1]['adx']
        except: return 0

    def calculate_ichimoku(self, candles):
        try:
            df = pd.DataFrame(candles)
            nine_high = df['high'].rolling(window=self.ichi_tenkan).max()
            nine_low = df['low'].rolling(window=self.ichi_tenkan).min()
            df['tenkan'] = (nine_high + nine_low) / 2
            twenty_six_high = df['high'].rolling(window=self.ichi_kijun).max()
            twenty_six_low = df['low'].rolling(window=self.ichi_kijun).min()
            df['kijun'] = (twenty_six_high + twenty_six_low) / 2
            df['span_a'] = ((df['tenkan'] + df['kijun']) / 2).shift(self.ichi_kijun)
            fifty_two_high = df['high'].rolling(window=self.ichi_senkou_b).max()
            fifty_two_low = df['low'].rolling(window=self.ichi_senkou_b).min()
            df['span_b'] = ((fifty_two_high + fifty_two_low) / 2).shift(self.ichi_kijun)
            curr = df.iloc[-1]
            return curr['tenkan'], curr['kijun'], curr['span_a'], curr['span_b'], curr['close']
        except: return 0,0,0,0,0

    def detect_candle_patterns(self, candles):
        if len(candles) < 3: return "NONE"
        c1 = candles[-2]; c2 = candles[-1]
        if c1['close'] < c1['open'] and c2['close'] > c2['open']:
            if c2['close'] > c1['open'] and c2['open'] < c1['close']:
                return "BULLISH_ENGULFING"
        if c1['close'] > c1['open'] and c2['close'] < c2['open']:
            if c2['close'] < c1['open'] and c2['open'] > c1['close']:
                return "BEARISH_ENGULFING"
        body = abs(c2['close'] - c2['open'])
        lower_wick = min(c2['close'], c2['open']) - c2['low']
        upper_wick = c2['high'] - max(c2['close'], c2['open'])
        if lower_wick > (body * 2) and upper_wick < body: return "HAMMER"
        if upper_wick > (body * 2) and lower_wick < body: return "SHOOTING_STAR"
        return "NONE"

    def calculate_bollinger_bands(self, candles, period=20, dev=2.0):
        try:
            df = pd.DataFrame(candles)
            df['sma'] = df['close'].rolling(window=period).mean()
            df['std'] = df['close'].rolling(window=period).std()
            df['upper'] = df['sma'] + (df['std'] * dev)
            df['lower'] = df['sma'] - (df['std'] * dev)
            last = df.iloc[-1]
            bandwidth = (last['upper'] - last['lower']) / last['sma'] * 100
            return last['upper'], last['lower'], last['sma'], bandwidth
        except: return 0, 0, 0, 0

    def get_htf_trend(self, candles, htf_minutes=240):
        """Calculate trend on higher timeframe via resampling."""
        try:
            if len(candles) < 200: return "NEUTRAL"
            df = pd.DataFrame(candles)
            df['dt'] = pd.to_datetime(df['time'], unit='s')
            df.set_index('dt', inplace=True)
            htf_df = df.resample(f"{htf_minutes}T").agg({'open':'first', 'high':'max', 'low':'min', 'close':'last'}).dropna()
            if len(htf_df) < 200: return "NEUTRAL"
            htf_ema200 = htf_df['close'].ewm(span=200, adjust=False).mean().iloc[-1]
            htf_close = htf_df['close'].iloc[-1]
            if htf_close > htf_ema200:
                return "BULLISH_STRONG" if htf_close > (htf_ema200 * 1.001) else "BULLISH_WEAK"
            else:
                return "BEARISH_STRONG" if htf_close < (htf_ema200 * 0.999) else "BEARISH_WEAK"
        except:
            return "NEUTRAL"

    # --- COMBINED U16 STRATEGY (Incorporates all other strategies, multi-TF adaptive) ---
    def check_signals_u16(self, symbol, bid, ask, candles, tf_minutes):
        if len(candles) < 50: return  # Need sufficient data
        buy_score = 0; sell_score = 0; reasons = []
        rsi, macd, macd_sig = self.calculate_indicators(candles)
        k, d = self.calculate_stochastic(candles)
        adx = self.calculate_adx(candles)
        tenkan, kijun, span_a, span_b, price = self.calculate_ichimoku(candles)
        fvg_type, fvg_top, fvg_bot = self._detect_recent_fvg(candles)
        current_close = candles[-1]['close']
        df = pd.DataFrame(candles)
        
        # LTF Core indicators (current TF)
        if rsi < 40: buy_score += 1
        elif rsi > 60: sell_score += 1
        if macd > macd_sig: buy_score += 1
        else: sell_score += 1
        if k < 25 and k > d: buy_score += 1; reasons.append("StochOvS")
        if k > 75 and k < d: sell_score += 1; reasons.append("StochOvB")
        if price > max(span_a, span_b): buy_score += 1
        if price < min(span_a, span_b): sell_score += 1
        
        pattern = self.detect_candle_patterns(candles)
        if "BULLISH" in pattern or pattern == "HAMMER": buy_score += 2; reasons.append(pattern)
        if "BEARISH" in pattern or pattern == "SHOOTING_STAR": sell_score += 2; reasons.append(pattern)
        
        structure = self.detect_market_structure(candles) 
        if structure == "BULLISH": buy_score += 1
        elif structure == "BEARISH": sell_score += 1
        
        if adx > 25:
            if self.trend == "BULLISH_STRONG": buy_score += 1
            if self.trend == "BEARISH_STRONG": sell_score += 1

        nearest_supp = self._get_nearest_zone(bid, is_support=True)
        nearest_res = self._get_nearest_zone(bid, is_support=False)
        atr = self.calculate_atr(candles)
        
        if nearest_supp and (bid - nearest_supp['top']) < atr: buy_score += 2; reasons.append("SuppBounce")
        if nearest_res and (nearest_res['bottom'] - bid) < atr: sell_score += 2; reasons.append("ResReject")
        
        if fvg_type == "BULLISH" and fvg_bot < ask < fvg_top: buy_score += 3; reasons.append("FVG_Retrace")
        elif fvg_type == "BEARISH" and fvg_bot < bid < fvg_top: sell_score += 3; reasons.append("FVG_Retrace")
            
        crt_signal = self._detect_crt_signal(candles, bid, ask)
        if crt_signal == "BUY": buy_score += 3; reasons.append("CRT_Sweep")
        elif crt_signal == "SELL": sell_score += 3; reasons.append("CRT_Sweep")

        # Additional confluence from other strategies (LTF)
        # Bollinger Bands (Mean Reversion & Breakout)
        upper, lower, sma, bandwidth = self.calculate_bollinger_bands(candles, self.bb_period, self.bb_dev)
        if current_close < lower: buy_score += 2; reasons.append("BB_Lower")
        if current_close > upper: sell_score += 2; reasons.append("BB_Upper")
        prev_close = candles[-2]['close']
        squeeze_threshold = sma * 0.005
        if bandwidth < squeeze_threshold:
            if current_close > upper and current_close > prev_close + (atr * self.breakout_threshold):
                buy_score += 2; reasons.append("Breakout_Bull")
            elif current_close < lower and current_close < prev_close - (atr * self.breakout_threshold):
                sell_score += 2; reasons.append("Breakout_Bear")

        # EMA Cross
        df['fast_ema'] = df['close'].ewm(span=self.ema_fast, adjust=False).mean()
        df['slow_ema'] = df['close'].ewm(span=self.ema_slow, adjust=False).mean()
        if df.iloc[-1]['fast_ema'] > df.iloc[-1]['slow_ema']: buy_score += 1
        else: sell_score += 1

        # Mean Reversion (low ADX)
        if adx < 25:
            if current_close <= lower and rsi < (100 - self.mr_rsi_extreme): buy_score += 2; reasons.append("MR_Buy")
            elif current_close >= upper and rsi > self.mr_rsi_extreme: sell_score += 2; reasons.append("MR_Sell")

        # SMC Order Blocks
        bullish_ob, bearish_ob = self.calculate_order_blocks(candles)
        if bullish_ob and bullish_ob['bottom'] <= ask <= bullish_ob['top']: buy_score += 2; reasons.append("Bull_OB")
        if bearish_ob and bearish_ob['bottom'] <= bid <= bearish_ob['top']: sell_score += 2; reasons.append("Bear_OB")

        # Silver Bullet Time Bonus
        if self._is_silver_bullet_time() and fvg_type != "NONE":
            if fvg_type == "BULLISH": buy_score += 1; reasons.append("Silver_Bull")
            elif fvg_type == "BEARISH": sell_score += 1; reasons.append("Silver_Bear")

        # Momentum (MACD Histogram expansion)
        short_ema_val = df['close'].ewm(span=self.macd_fast, adjust=False).mean()
        long_ema_val = df['close'].ewm(span=self.macd_slow, adjust=False).mean()
        df['macd'] = short_ema_val - long_ema_val
        df['macd_signal'] = df['macd'].ewm(span=self.macd_signal, adjust=False).mean()

        prev_macd_hist = (df.iloc[-2]['macd'] - df.iloc[-2]['macd_signal']) if len(df) > 1 else 0
        curr_macd_hist = macd - macd_sig
        if adx > 25 and curr_macd_hist > prev_macd_hist: buy_score += 1
        elif adx > 25 and curr_macd_hist < prev_macd_hist: sell_score += 1

        # HTF Confluence (always check higher TF for alignment, adaptive to current TF)
        target_htf = min(1440, max(60, tf_minutes * 12))  # Adaptive HTF: 12x current or cap at D1
        htf_trend = self.get_htf_trend(candles, target_htf)
        if "BULLISH" in htf_trend:
            buy_score += 2 if "STRONG" in htf_trend else 1
            reasons.append(f"HTF_{htf_trend}")
        elif "BEARISH" in htf_trend:
            sell_score += 2 if "STRONG" in htf_trend else 1
            reasons.append(f"HTF_{htf_trend}")

        # TF-Adaptive Threshold: Lower for LTF (scalping), higher for HTF (swing)
        base_threshold = 7
        if tf_minutes <= 5:  # LTF: Easier entry for quick scalps
            THRESHOLD = base_threshold - 1
        elif tf_minutes >= 240:  # HTF: Stricter for longer holds
            THRESHOLD = base_threshold + 2
        else:
            THRESHOLD = base_threshold

        # TF-Adaptive Risk: Tighter on LTF, wider on HTF
        if tf_minutes <= 5:
            atr_mult = self.scalp_atr_mult * 0.8  # Even tighter SL for LTF
            tp_base = 1.2
        else:
            atr_mult = self.scalp_atr_mult * 1.5  # Wider for HTF
            tp_base = 2.0

        if buy_score >= THRESHOLD and buy_score > sell_score:
            if self._check_filters("BUY", ask):
                sl_dist = atr * atr_mult
                sl = ask - sl_dist
                tp_mult = min(tp_base + (buy_score - THRESHOLD) * 0.2, 3.0)  # Dynamic TP, capped higher for HTF
                tp = ask + (sl_dist * tp_mult)
                reason_str = ",".join(reasons)
                logger.info(f"🌟 BUY (U16) | TF:{tf_minutes}min | Score: {buy_score} | Reasons: {reason_str}")
                self.execute_trade("BUY", symbol, self.lot_size, "U16_STRATEGY", sl, tp)
        elif sell_score >= THRESHOLD and sell_score > buy_score:
            if self._check_filters("SELL", bid):
                sl_dist = atr * atr_mult
                sl = bid + sl_dist
                tp_mult = min(tp_base + (sell_score - THRESHOLD) * 0.2, 3.0)  # Dynamic TP
                tp = bid - (sl_dist * tp_mult)
                reason_str = ",".join(reasons)
                logger.info(f"🌟 SELL (U16) | TF:{tf_minutes}min | Score: {sell_score} | Reasons: {reason_str}")
                self.execute_trade("SELL", symbol, self.lot_size, "U16_STRATEGY", sl, tp)

    # --- STRUCTURE HELPERS ---
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
            name = f"Supp_{i}"
            self.connector.send_draw_command(name, zone['top'], zone['bottom'], 100, 0, "0x008000") 
        for i, zone in enumerate(self.resistance_zones[:3]):
            name = f"Res_{i}"
            self.connector.send_draw_command(name, zone['top'], zone['bottom'], 100, 0, "0x000080") 

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

    def analyze_trend(self, candles):
        try:
            df = pd.DataFrame(candles)
            ema200 = df['close'].ewm(span=200, adjust=False).mean().iloc[-1]
            current = df['close'].iloc[-1]
            if current > ema200:
                self.trend = "BULLISH_STRONG" if current > (ema200 * 1.001) else "BULLISH_WEAK"
            else:
                self.trend = "BEARISH_STRONG" if current < (ema200 * 0.999) else "BEARISH_WEAK"
        except: self.trend = "NEUTRAL"

    def get_htf_structure(self, candles, timeframe_minutes=240):
        if not candles or len(candles) < 20: return None, None, "NO_DATA"
        df = pd.DataFrame(candles)
        df['dt'] = pd.to_datetime(df['time'], unit='s')
        df.set_index('dt', inplace=True)
        htf_candles = df.resample(f"{timeframe_minutes}T").agg({'high':'max','low':'min','close':'last','open':'first'}).dropna()
        if len(htf_candles) < 2: return None, None, "INSUFFICIENT_DATA"
        prev_htf = htf_candles.iloc[-2]
        return prev_htf['high'], prev_htf['low'], "OK"

    def _detect_crt_signal(self, candles, bid, ask):
        if len(candles) < 20: return "NONE"
        ltf_mins = (candles[1]['time'] - candles[0]['time']) // 60 or 5
        needed = (self.crt_htf // ltf_mins) * 2
        if len(candles) < needed: return "NONE"
        crt_high, crt_low, status = self.get_htf_structure(candles, self.crt_htf)
        if status != "OK": return "NONE"
        
        range_width = crt_high - crt_low
        entry_threshold = range_width * self.crt_zone_size
        close_price = candles[-2]['close']
        recent_history = candles[-11:-1]
        recent_lows = [c['low'] for c in recent_history]
        recent_highs = [c['high'] for c in recent_history]
        
        if min(recent_lows) < crt_low:
            if close_price > crt_low and crt_low < ask < (crt_low + entry_threshold): return "BUY"
        elif max(recent_highs) > crt_high:
            if close_price < crt_high and (crt_high - entry_threshold) < bid < crt_high: return "SELL"
        return "NONE"

    def detect_market_structure(self, candles):
        if len(candles) < 50: return "NEUTRAL"
        highs, lows = self._get_fractals(candles, window=3)
        if not highs or not lows: return "NEUTRAL"
        current_close = candles[-1]['close']
        if current_close > highs[-1]: return "BULLISH"
        elif current_close < lows[-1]: return "BEARISH"
        return "NEUTRAL"

    def calculate_order_blocks(self, candles):
        if len(candles) < 20: return None, None
        bullish_ob = None; bearish_ob = None
        for i in range(len(candles) - 3, len(candles) - 30, -1):
            curr = candles[i]
            if curr['close'] < curr['open'] and i + 1 < len(candles) and candles[i+1]['close'] > curr['high']:
                bullish_ob = {'top': curr['high'], 'bottom': curr['low']}; break
        for i in range(len(candles) - 3, len(candles) - 30, -1):
            curr = candles[i]
            if curr['close'] > curr['open'] and i + 1 < len(candles) and candles[i+1]['close'] < curr['low']:
                bearish_ob = {'top': curr['high'], 'bottom': curr['low']}; break
        return bullish_ob, bearish_ob

    def _detect_recent_fvg(self, candles):
        if len(candles) < 5: return "NONE", 0, 0
        for i in range(len(candles) - 1, 2, -1):
            curr = candles[i]; prev2 = candles[i-2]
            if curr['low'] > prev2['high']:
                return "BULLISH", curr['low'], prev2['high']
            if curr['high'] < prev2['low']:
                return "BEARISH", prev2['low'], curr['high']
        return "NONE", 0, 0

    def _is_silver_bullet_time(self):
        try:
            ny_tz = ZoneInfo("America/New_York")
            h = datetime.now(ny_tz).hour
            return h in [10, 14]
        except: return False

    # --- FILTERS & UTILS ---
    def get_prediction_score(self, symbol, bid, ask, candles):
        if not candles or len(candles) < 50: return 0, "NEUTRAL"
        rsi, macd, macd_sig = self.calculate_indicators(candles)
        buy_strength = 0; sell_strength = 0
        if rsi < 50: buy_strength += 20
        else: sell_strength += 20
        if macd > macd_sig: buy_strength += 20
        else: sell_strength += 20
        if "BULLISH" in self.trend: buy_strength += 20
        elif "BEARISH" in self.trend: sell_strength += 20
        if buy_strength > sell_strength: return buy_strength, "BUY"
        elif sell_strength > buy_strength: return sell_strength, "SELL"
        else: return 50, "NEUTRAL"

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
            tz_map = {"London": "Europe/London", "New York": "America/New_York", "Tokyo": "Asia/Tokyo", "Sydney": "Australia/Sydney"}
            if self.time_zone in tz_map: now = datetime.now(ZoneInfo(tz_map[self.time_zone]))
            else: now = datetime.now()
            curr_hour = now.hour
            return (self.start_hour <= curr_hour < self.end_hour) if self.start_hour <= self.end_hour else (curr_hour >= self.start_hour or curr_hour < self.end_hour)
        except: return True

    def _check_filters(self, direction, current_price):
        if self.news_engine and self.news_engine.trading_pause:
            self._log_skip("News Filter: Trading is currently PAUSED due to high-impact news.")
            return False
        if not self._is_trading_time():
            self._log_skip(f"Time Filter: Outside trading hours.")
            return False
        if self.use_zone_filter:
            if direction == "BUY":
                nearest_res = self._get_nearest_zone(current_price, is_support=False)
                if nearest_res and (nearest_res['bottom'] - current_price) < (self.zone_tolerance * 0.5): return False
            if direction == "SELL":
                nearest_supp = self._get_nearest_zone(current_price, is_support=True)
                if nearest_supp and (current_price - nearest_supp['top']) < (self.zone_tolerance * 0.5): return False
        if self.use_trend_filter:
             if direction == "BUY" and "BEARISH" in self.trend: return False
             if direction == "SELL" and "BULLISH" in self.trend: return False
        return True

    def _log_skip(self, message):
        if time.time() - self.last_log_time > 15:
            logger.info(f"❌ {message}")
            self.last_log_time = time.time()

    def calculate_safe_risk(self, direction, entry_price, candles):
        atr = self.calculate_atr(candles)
        if atr == 0: atr = entry_price * 0.001
        sl_dist = atr * 1.5
        if direction == "BUY":
            nearest_supp = self._get_nearest_zone(entry_price, is_support=True)
            if nearest_supp and (entry_price - nearest_supp['bottom']) < (sl_dist * 1.5):
                sl = nearest_supp['bottom'] - (atr * 0.2)
            else: sl = entry_price - sl_dist
            raw_tp = entry_price + ((entry_price - sl) * self.risk_reward_ratio)
            tp = raw_tp - (atr * 0.05)
        elif direction == "SELL":
            nearest_res = self._get_nearest_zone(entry_price, is_support=False)
            if nearest_res and (nearest_res['top'] - entry_price) < (sl_dist * 1.5):
                sl = nearest_res['top'] + (atr * 0.2)
            else: sl = entry_price + sl_dist
            raw_tp = entry_price - ((sl - entry_price) * self.risk_reward_ratio)
            tp = raw_tp + (atr * 0.05)
        return float(sl), float(tp)

    def execute_trade(self, direction, symbol, volume, reason, sl, tp):
        self.last_trade_time = time.time()
        success = self.connector.send_command(direction, symbol, volume, sl, tp, 0)
        if success:
            logger.info(f"🚀 EXECUTED {direction} {symbol} | Vol: {volume} | SL: {sl:.4f} | TP: {tp:.4f} | Reason: {reason}")
            if self.webhook:
                self.webhook.notify_trade(direction, symbol, volume, sl, tp, reason)
        else:
            logger.error(f"❌ FAILED to execute {direction} {symbol}")

    def check_and_close_profit(self, symbol):
        if time.time() - self.last_profit_close_time < self.profit_close_interval: return
        self.last_profit_close_time = time.time()
        try:
            if not self.break_even_active and self.current_profit >= self.break_even_activation:
                msg = f"🛡️ BREAK-EVEN ACTIVATED: Profit ${self.current_profit:.2f}. Locking in position."
                logger.info(msg)
                self.break_even_active = True
                if self.webhook: self.webhook.notify_protection(symbol, msg)
                if self.ui_callback: self.ui_callback("break_even", {"profit": self.current_profit, "msg": msg})
            
            if self.current_profit >= self.min_profit_target:
                logger.info(f"💰 TARGET HIT: ${self.current_profit:.2f}. Closing...")
                close_msg = "Target Profit Hit"
                if self.webhook: self.webhook.notify_close(symbol, self.current_profit, close_msg)
                success = self.connector.close_profit(symbol)
                if success:
                    self.break_even_active = False
                    self.peak_profit = 0.0
                    if self.ui_callback: self.ui_callback("profit_closed", {"profit": self.current_profit, "symbol": symbol})
                else: logger.warning(f"⚠️ Failed to close profit for {symbol}. Retrying next tick...")
        except Exception as e:
            logger.error(f"❌ Error in check_and_close_profit: {e}")
            if self.ui_callback: self.ui_callback("error", {"msg": str(e)})

    # --- TELEGRAM HANDLERS ---
    def _handle_telegram_positions_command(self):
        raw_positions = getattr(self.connector, 'open_positions', [])
        if raw_positions: self.webhook.notify_active_positions(raw_positions)
        else:
            if self.last_positions_count > 0: self.webhook.send_message(f"⚠️ Have {self.last_positions_count} positions, but details are syncing...")
            else: self.webhook.notify_active_positions([])

    def _handle_telegram_mode_command(self):
        self.active = not self.active
        state = "ACTIVE (AUTO-TRADING)" if self.active else "PAUSED"
        self.webhook.send_message(f"🔄 **Strategy Updated**\nNew State: **{state}**")
        logger.info(f"Telegram Request: Strategy set to {state}")

    def _handle_telegram_trade(self, action, symbol=None, volume=None):
        if not symbol:
            self.webhook.send_message("⚠️ Please specify symbol. Example: `/buy XAUUSDm 0.01`")
            return
        if not volume: volume = self.lot_size
        success = self.connector.send_command(action, symbol, volume, 0.0, 0.0, 0)
        if success:
            direction_emoji = "🟢" if action == "BUY" else "🔴"
            self.webhook.send_message(f"{direction_emoji} *Sent {action}* for `{symbol}` (Lot: {volume})")
        else: self.webhook.send_message("❌ Failed to send command to MT5.")

    def _handle_telegram_close_ticket(self, ticket_id):
        self.webhook.send_message(f"⏳ Attempting to close Ticket #{ticket_id}...")
        self.connector.close_ticket(ticket_id)

    def _handle_telegram_news_command(self):
        if self.news_engine:
            self.webhook.send_message("🔎 *Fetching live updates...*")
            self.news_engine.fetch_latest()
            news_str = self.news_engine.get_latest_news(5)
            if news_str: self.webhook.send_message(f"📰 *Latest News*\n{news_str}")
            else: self.webhook.send_message("📭 No relevant news found recently.")
        else: self.webhook.send_message("⚠️ News Engine not active.")

    def _handle_telegram_accounts_command(self):
        acct = self.connector.account_info
        if acct and acct.get('login'):
            msg = (
                f"🔑 *ACTIVE MT5 ACCOUNT*\n\n"
                f"👤 *{acct.get('name', 'Unknown')}*\n"
                f"🆔 Login: `{acct.get('login', 'N/A')}`\n"
                f"🖥️ Server: `{acct.get('server', 'N/A')}`\n"
                f"🏢 Broker: `{acct.get('company', 'N/A')}`\n"
                f"⚖️ Leverage: `1:{acct.get('leverage', 'N/A')}`\n\n"
                f"💰 Balance: `${acct.get('balance', 0):.2f}`\n"
                f"📊 Equity: `${acct.get('equity', 0):.2f}`\n"
                f"📈 Floating P/L: `${acct.get('profit', 0):.2f}`"
            )
            self.webhook.send_message(msg)
        else: self.webhook.send_message("⚠️ No MT5 account connected. Waiting for data...")
    
    def _handle_telegram_select_account(self, account_index):
        import json
        accounts = self.config.get('mt5_accounts', [])
        if 0 <= account_index < len(accounts):
            selected = accounts[account_index]
            self.config['mt5']['active_account'] = account_index
            try:
                with open('config.json', 'w') as f:
                    json.dump(self.config, f, indent=2)
                self.webhook.send_message(
                    f"✅ *Account Switched!*\n\n"
                    f"👤 *{selected['name']}*\n"
                    f"🖥️ Server: `{selected['server']}`\n\n"
                    f"⚠️ *Note:* You must manually switch accounts in MT5 Terminal."
                )
            except Exception as e: self.webhook.send_message(f"❌ Failed to save: {e}")
        else: self.webhook.send_message("❌ Invalid account selection.")
        
    def _handle_telegram_status_command(self):
        pos_count = self.last_positions_count
        bal = self.last_balance 
        self.webhook.notify_account_summary(bal, self.current_profit, pos_count, self.strategy_mode, self.lot_size)

    def _handle_telegram_analysis(self):
        if hasattr(self, 'last_candles') and hasattr(self, 'last_symbol') and self.last_candles:
            tf_min = 5  # Default
            if len(self.last_candles) > 2:
                diff = (self.last_candles[1]['time'] - self.last_candles[0]['time']) // 60
                if diff > 0: tf_min = diff
            rsi, macd, macd_sig = self.calculate_indicators(self.last_candles)
            score, signal = self.get_prediction_score(self.last_symbol, 0, 0, self.last_candles)
            htf_trend = self.get_htf_trend(self.last_candles)
            self.webhook.notify_analysis(self.last_symbol, self.trend, rsi, macd, score, signal, tf_min, htf_trend)
        else: self.webhook.send_message("⚠️ No market data available yet. Wait for a tick.")

    def _handle_telegram_strategy_select(self, mode_name):
        self.webhook.send_message(f"🧠 Strategy locked to combined **U16_STRATEGY**. Change ignored.")
        logger.info(f"Telegram: Attempt to change to {mode_name}, but locked to U16")

    def _handle_telegram_lot_change(self, delta):
        new_lot = round(self.lot_size + delta, 2)
        if new_lot < 0.01: new_lot = 0.01
        self.lot_size = new_lot
        self.webhook.send_message(f"🎲 Lot size updated to: **{self.lot_size}**")
        logger.info(f"Telegram: Lot size changed to {self.lot_size}")