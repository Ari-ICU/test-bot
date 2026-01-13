import threading
import time
import logging
import queue
from datetime import datetime
import tkinter as tk
from tkinter import ttk, scrolledtext
import ttkbootstrap as tb
from ttkbootstrap.constants import *
from ttkbootstrap.dialogs import Messagebox

log_queue = queue.Queue()

class QueueHandler(logging.Handler):
    def emit(self, record):
        log_queue.put(record)

class TradingBotUI(tb.Window):
    def __init__(self, news_engine, mt5_connector):
        super().__init__(themename="darkly")  
        self.title("MT5 Bot - Laptop Edition")
        self.geometry("1150x750") 
        self.resizable(True, True) 
        
        self.news_engine = news_engine
        self.mt5_connector = mt5_connector
        self.strategy = None
        
        self.last_price_update = time.time()
        self.symbols_loaded = False
        self.open_positions = []  
        self.profit_history = []  
        
        # --- UI Variables ---
        self.auto_trade_var = tk.BooleanVar(value=False)
        self.max_pos_var = tk.IntVar(value=1)
        self.lot_size_var = tk.DoubleVar(value=0.01)
        self.cooldown_var = tk.DoubleVar(value=15.0)

        # Strategies & Toggles
        self.strategy_mode_var = tk.StringVar(value="U16_STRATEGY")
        self.use_trend_filter_var = tk.BooleanVar(value=True) 
        self.use_zone_filter_var = tk.BooleanVar(value=True) 

        # Profit Settings
        self.auto_close_sec_var = tk.DoubleVar(value=2.0)
        self.use_profit_mgmt_var = tk.BooleanVar(value=True)
        self.rr_ratio_var = tk.DoubleVar(value=1.5)
        self.min_profit_var = tk.DoubleVar(value=0.10)

        # Indicators
        self.rsi_period_var = tk.IntVar(value=9)
        self.rsi_buy_var = tk.IntVar(value=35)
        self.rsi_sell_var = tk.IntVar(value=65)
        
        self.stoch_k_var = tk.IntVar(value=14)
        self.stoch_d_var = tk.IntVar(value=3)
        self.stoch_ob_var = tk.IntVar(value=80)
        self.stoch_os_var = tk.IntVar(value=20)

        self.adx_period_var = tk.IntVar(value=14)
        self.adx_threshold_var = tk.IntVar(value=25)

        self.ichi_tenkan_var = tk.IntVar(value=9)
        self.ichi_kijun_var = tk.IntVar(value=26)
        self.ichi_senkou_var = tk.IntVar(value=52)

        self.macd_fast_var = tk.IntVar(value=8)
        self.macd_slow_var = tk.IntVar(value=21)
        self.macd_signal_var = tk.IntVar(value=5)

        self.bb_period_var = tk.IntVar(value=20)
        self.bb_dev_var = tk.DoubleVar(value=2.0)

        self.ema_fast_var = tk.IntVar(value=9)
        self.ema_slow_var = tk.IntVar(value=21)

        # Dashboard Manual Inputs
        self.symbol_var = tk.StringVar()
        self.tf_var = tk.StringVar(value="M1") 
        self.manual_sl_var = tk.DoubleVar(value=0.0)
        self.manual_tp_var = tk.DoubleVar(value=0.0)
        
        # Time Filter Settings
        self.use_time_filter_var = tk.BooleanVar(value=True)
        self.time_zone_var = tk.StringVar(value="Auto")
        self.start_hour_var = tk.IntVar(value=8)
        self.end_hour_var = tk.IntVar(value=20)
        
        # CRT Settings
        self.crt_htf_var = tk.IntVar(value=240)       # Big Timeframe (e.g. 4H)
        self.crt_lookback_var = tk.IntVar(value=10)   # Small Timeframe Lookback (Candles)
        self.crt_zone_var = tk.DoubleVar(value=0.50)  # Entry Zone % of Range (e.g. 0.50 = 50%)
        
        self._bind_traces()

        self.mt5_connector.on_tick_received = self._on_tick_received
        self.mt5_connector.on_symbols_received = self._on_symbols_received
        
        # Request symbol list from MT5 immediately
        self.mt5_connector.request_symbols()
        
        self._setup_logging()
        self._create_widgets()
        self._check_log_queue()
        self._update_strategy_logic_text()
        
        self.after(5000, self._update_news)  
        self._update_header_time()

    def _bind_traces(self):
        """Syncs UI changes to Strategy instantly"""
        vars_to_trace = [
            self.max_pos_var, self.lot_size_var, self.cooldown_var,
            self.strategy_mode_var, self.use_trend_filter_var, self.use_zone_filter_var,
            self.auto_close_sec_var, self.use_profit_mgmt_var, self.rr_ratio_var,
            self.min_profit_var,
            self.rsi_period_var, self.rsi_buy_var, self.rsi_sell_var,
            self.macd_fast_var, self.macd_slow_var, self.macd_signal_var,
            self.bb_period_var, self.bb_dev_var, self.ema_fast_var, self.ema_slow_var,
            self.stoch_k_var, self.stoch_d_var, self.stoch_ob_var, self.stoch_os_var,
            self.adx_period_var, self.adx_threshold_var,
            self.ichi_tenkan_var, self.ichi_kijun_var, self.ichi_senkou_var,
            self.use_time_filter_var, self.time_zone_var, self.start_hour_var, self.end_hour_var,
            self.crt_htf_var, self.crt_lookback_var, self.crt_zone_var
        ]
        for var in vars_to_trace:
            var.trace_add("write", self._on_setting_changed)

    def _safe_get(self, var, default=0):
        try:
            val = var.get()
            return val if val != "" else default
        except:
            return default

    def _sync_ui_to_strategy(self):
        if self.strategy:
            try:
                self.strategy.max_positions = self._safe_get(self.max_pos_var, 1)
                self.strategy.lot_size = self._safe_get(self.lot_size_var, 0.01)
                self.strategy.trade_cooldown = self._safe_get(self.cooldown_var, 15.0)
                
                self.strategy.strategy_mode = self.strategy_mode_var.get()
                self.strategy.use_trend_filter = self.use_trend_filter_var.get()
                self.strategy.use_zone_filter = self.use_zone_filter_var.get()

                self.strategy.profit_close_interval = self._safe_get(self.auto_close_sec_var, 2.0)
                self.strategy.use_profit_management = self.use_profit_mgmt_var.get()
                self.strategy.risk_reward_ratio = self._safe_get(self.rr_ratio_var, 1.5)
                self.strategy.min_profit_target = self._safe_get(self.min_profit_var, 0.10)

                self.strategy.rsi_period = self._safe_get(self.rsi_period_var, 14)
                self.strategy.rsi_buy_threshold = self._safe_get(self.rsi_buy_var, 30)
                self.strategy.rsi_sell_threshold = self._safe_get(self.rsi_sell_var, 70)
                
                self.strategy.macd_fast = self._safe_get(self.macd_fast_var, 12)
                self.strategy.macd_slow = self._safe_get(self.macd_slow_var, 26)
                self.strategy.macd_signal = self._safe_get(self.macd_signal_var, 9)

                self.strategy.bb_period = self._safe_get(self.bb_period_var, 20)
                self.strategy.bb_dev = self._safe_get(self.bb_dev_var, 2.0)

                self.strategy.ema_fast = self._safe_get(self.ema_fast_var, 9)
                self.strategy.ema_slow = self._safe_get(self.ema_slow_var, 21)

                self.strategy.stoch_k = self._safe_get(self.stoch_k_var, 14)
                self.strategy.stoch_d = self._safe_get(self.stoch_d_var, 3)
                self.strategy.stoch_overbought = self._safe_get(self.stoch_ob_var, 80)
                self.strategy.stoch_oversold = self._safe_get(self.stoch_os_var, 20)
                
                self.strategy.adx_period = self._safe_get(self.adx_period_var, 14)
                self.strategy.adx_threshold = self._safe_get(self.adx_threshold_var, 25)

                self.strategy.ichi_tenkan = self._safe_get(self.ichi_tenkan_var, 9)
                self.strategy.ichi_kijun = self._safe_get(self.ichi_kijun_var, 26)
                self.strategy.ichi_senkou_b = self._safe_get(self.ichi_senkou_var, 52)

                self.strategy.use_time_filter = self.use_time_filter_var.get()
                self.strategy.time_zone = self.time_zone_var.get()
                self.strategy.start_hour = self._safe_get(self.start_hour_var, 8)
                self.strategy.end_hour = self._safe_get(self.end_hour_var, 20)

                self.strategy.crt_htf = self._safe_get(self.crt_htf_var, 240)
                self.strategy.crt_lookback = self._safe_get(self.crt_lookback_var, 10)
                self.strategy.crt_zone_size = self._safe_get(self.crt_zone_var, 0.25)

                logging.info(f"Settings Updated: Mode={self.strategy.strategy_mode} | Trend={self.strategy.use_trend_filter} | Zone={self.strategy.use_zone_filter}")
            except (tk.TclError, ValueError, TypeError):
                pass
            except Exception as e:
                logging.debug(f"Sync error: {e}")

    def _update_strategy_logic_text(self):
        if not hasattr(self, 'lbl_buy_logic'): return
        
        mode = self.strategy_mode_var.get()
        if mode == "U16_STRATEGY":
            self.lbl_buy_logic.config(text=f"🟢 BUY: Score ≥ 4 (Indics + PA + SMC/ICT + CRT)")
            self.lbl_sell_logic.config(text=f"🔴 SELL: Score ≥ 4 (Indics + PA + SMC/ICT + CRT)")
        else:
             self.lbl_buy_logic.config(text=f"🟢 BUY: Logic for {mode}")
             self.lbl_sell_logic.config(text=f"🔴 SELL: Logic for {mode}")

    def _on_tick_received(self, symbol, bid, ask, balance, profit, acct_name, positions, buy_count, sell_count, avg_entry, candles):
        self.last_price_update = time.time() 
        self.after(0, lambda: self._update_ui_data(symbol, bid, ask, balance, profit, acct_name, positions, buy_count, sell_count, candles))
        
        if profit != 0 and (not self.profit_history or self.profit_history[-1][1] != profit):
             self.profit_history.append((time.strftime("%H:%M:%S"), profit))
             if len(self.profit_history) > 50: self.profit_history.pop(0)

    def _on_symbols_received(self, symbols_list):
        if not self.symbols_loaded:
            self.after(0, lambda: self._set_combo_values(symbols_list))
            self.symbols_loaded = True

    def _update_ui_data(self, symbol, bid, ask, balance, profit, acct_name, positions, buy_count, sell_count, candles):
        try:
            # Sync UI Checkbox with Strategy State
            if self.strategy and self.auto_trade_var.get() != self.strategy.active:
                self.auto_trade_var.set(self.strategy.active)

            clean_symbol = str(symbol).replace('\x00', '').strip()
            if not self.symbol_var.get(): self.symbol_var.set(clean_symbol)

            if clean_symbol == self.symbol_var.get():
                tf_display = self.tf_var.get()
                mode_display = self.strategy_mode_var.get()
                self.lbl_mt5.config(text=f"MT5: {clean_symbol} [{tf_display}] ({mode_display})", bootstyle="success")
                self.lbl_bid.config(text=f"BID: {bid:.2f}")
                self.lbl_ask.config(text=f"ASK: {ask:.2f}")

            # Update labels with new format
            bal_style = "success" if balance > 5000 else "info"
            self.lbl_balance.config(text=f"💰 Balance: ${balance:,.2f}", bootstyle=bal_style)
            
            pl_style = "success" if profit >= 0 else "danger"
            self.lbl_profit.config(text=f"📈 P/L: ${profit:+,.2f}", bootstyle=pl_style)
            
            self.lbl_positions.config(text=f"📦 Positions: {positions}/{self.max_pos_var.get()}")
            self.lbl_buysell.config(text=f"🟢 {buy_count} | 🔴 {sell_count}")

            # [FIX START] ========================================================
            # Retrieve profit stats from connector
            info = self.mt5_connector.account_info
            
            p_today = info.get('today', 0.0)
            p_week = info.get('week', 0.0)
            p_month = info.get('month', 0.0)
            
            self.lbl_prof_today.config(text=f"Today: ${p_today:+,.2f}", bootstyle="success" if p_today >= 0 else "danger")
            self.lbl_prof_week.config(text=f"Week: ${p_week:+,.2f}", bootstyle="success" if p_week >= 0 else "danger")
            self.lbl_prof_month.config(text=f"Month: ${p_month:+,.2f}", bootstyle="success" if p_month >= 0 else "danger")
            # [FIX END] ==========================================================

            # --- Sync Status ---
            min_needed = 200
            count = len(candles)
            if count >= min_needed:
                self.lbl_sync.config(text="🔄 Sync: READY", foreground="#2ecc71")
            else:
                self.lbl_sync.config(text=f"🔄 Sync: {count}/{min_needed}", foreground="#f39c12")

            # --- Server Time ---
            if count > 0:
                last_time = candles[-1]['time']
                st_str = datetime.fromtimestamp(last_time).strftime('%H:%M:%S')
                self.lbl_server_time.config(text=f"🕒 MT5: {st_str}")

            if self.strategy and len(candles) > 20:
                rsi, macd, signal = self.strategy.calculate_indicators(candles)
                
                rsi_color = "success" if rsi < self.rsi_buy_var.get() else "danger" if rsi > self.rsi_sell_var.get() else "secondary"
                self.lbl_live_rsi.config(text=f"RSI: {rsi:.2f}", bootstyle=rsi_color)
                
                macd_color = "success" if macd > signal else "danger"
                self.lbl_live_macd.config(text=f"MACD: {macd:.5f}", bootstyle=macd_color)

                # --- CRT Progress Update ---
                htf_mins = self.crt_htf_var.get()
                if htf_mins > 0:
                    last_time = candles[-1]['time']
                    elapsed = (last_time % (htf_mins * 60)) // 60
                    remaining = htf_mins - elapsed
                    self.crt_progress_lbl.config(text=f"Range Age: {int(elapsed)}m / {htf_mins}m (Renew in {int(remaining)}m)")

                # --- Zone Display ---
                if self.use_zone_filter_var.get():
                    supp_txt = "None"
                    if hasattr(self.strategy, 'support_zones') and self.strategy.support_zones:
                        zone = self.strategy.support_zones[0]
                        supp_txt = f"{zone['top']:.2f}"
                    
                    res_txt = "None"
                    if hasattr(self.strategy, 'resistance_zones') and self.strategy.resistance_zones:
                        zone = self.strategy.resistance_zones[0]
                        res_txt = f"{zone['bottom']:.2f}"
                        
                    self.lbl_detected_zone.config(text=f"S: {supp_txt} | R: {res_txt}", bootstyle="primary")
                else:
                    self.lbl_detected_zone.config(text="Zone: DISABLED", bootstyle="secondary")

        except Exception as e:
            pass

    def _update_card(self, label, text, bootstyle):
        label.config(text=text, bootstyle=bootstyle)

    def _create_stat_card(self, parent, title, value, bootstyle):
        f = ttk.LabelFrame(parent, text=title, padding=10, bootstyle=bootstyle)
        l = ttk.Label(f, text=value, font=("Segoe UI", 20, "bold"), bootstyle=bootstyle)
        l.pack()
        return f

    def _on_buy(self):
        s = self.symbol_var.get()
        if s: self.mt5_connector.send_command("BUY", s, self.lot_size_var.get(), self.manual_sl_var.get(), self.manual_tp_var.get(), 0)

    def _on_sell(self):
        s = self.symbol_var.get()
        if s: self.mt5_connector.send_command("SELL", s, self.lot_size_var.get(), self.manual_sl_var.get(), self.manual_tp_var.get(), 0)

    def _on_close_all(self):
        s = self.symbol_var.get()
        if s: self.mt5_connector.close_position(s)

    def _on_close_profit(self):
        self.mt5_connector.close_profit(self.symbol_var.get())
    
    def _on_close_loss(self):
        self.mt5_connector.close_loss(self.symbol_var.get())

    def _on_auto_toggle(self):
        if self.strategy: self.strategy.set_active(self.auto_trade_var.get())

    def _on_setting_changed(self, *args):
        self._sync_ui_to_strategy()
        self._update_strategy_logic_text()
    
    def _on_tf_change(self, event=None):
        symbol = self.symbol_var.get()
        tf = self.tf_var.get()
        if symbol and tf:
            self.mt5_connector.change_timeframe(symbol, tf)
            logging.info(f"Requested Timeframe change: {symbol} -> {tf}")
    
    def _on_symbol_change(self, event=None):
        symbol = self.symbol_var.get()
        if symbol:
            self.mt5_connector.change_symbol(symbol)
            logging.info(f"Requested Symbol change to: {symbol}")
            self.lbl_live_rsi.config(text="RSI: Waiting...", bootstyle="secondary")
            self.lbl_live_macd.config(text="MACD: Waiting...", bootstyle="secondary")
            self.lbl_detected_zone.config(text="Zone: Detecting...", bootstyle="secondary")
            
            if self.strategy and hasattr(self.strategy, 'reset_state'):
                self.strategy.reset_state()

    def _on_tz_change(self, event=None):
        tz = self.time_zone_var.get()
        session_hours = {
            "London": (8, 17),
            "New York": (8, 17),
            "Tokyo": (9, 18),
            "Sydney": (7, 16),
            "Auto": (0, 23)
        }
        if tz in session_hours:
            start, end = session_hours[tz]
            self.start_hour_var.set(start)
            self.end_hour_var.set(end)
            logging.info(f"Market Hours synced for {tz}: {start:02d}:00 - {end:02d}:00")

    def _on_crt_htf_change(self, event=None):
        selection = self.crt_htf_combo.get()
        mapping = {"15m": 15, "30m": 30, "1H": 60, "4H": 240, "D1": 1440}
        minutes = mapping.get(selection, 240)
        self.crt_htf_var.set(minutes)
        self._on_setting_changed()

    def _set_combo_values(self, symbols_list):
        self.combo_symbol['values'] = symbols_list
        if symbols_list and not self.symbol_var.get(): 
            self.symbol_var.set(symbols_list[0])

    def _update_news(self):
        if self.news_engine:
            news_str = self.news_engine.get_latest_news(10)
            sync_time = time.strftime("%H:%M:%S")
            self.news_text.delete(1.0, tk.END)
            self.news_text.insert(tk.END, f"🛰️ Last News Sync: {sync_time}\n" + "-"*40 + "\n" + news_str)
        self.after(5000, self._update_news)

    def _setup_logging(self):
        formatter = logging.Formatter('%(asctime)s: %(message)s', datefmt='%H:%M:%S')
        queue_handler = QueueHandler()
        queue_handler.setFormatter(formatter)
        logging.getLogger().addHandler(queue_handler)
        logging.getLogger().setLevel(logging.INFO)

    def _check_log_queue(self):
        try:
            while True:
                record = log_queue.get_nowait()
                msg = logging.Formatter('%(asctime)s: %(message)s', datefmt='%H:%M:%S').format(record)
                self.log_text.insert(tk.END, msg + '\n')
                self.log_text.see(tk.END)
        except queue.Empty: pass
        self.after(100, self._check_log_queue)
    
    def _update_header_time(self):
        now = time.strftime("%H:%M:%S")
        market_info = ""
        if self.strategy:
            session = self.strategy.active_session_name
            all_times = self.strategy.get_session_times()
            market_info = f" | {session} Session | {all_times}"
            
        if hasattr(self, 'lbl_time'): 
            self.lbl_time.config(text=f"🕒 {now}{market_info}")
        
        self.after(1000, self._update_header_time)

    def _create_widgets(self):
        main_frame = ttk.Frame(self)
        main_frame.pack(fill=BOTH, expand=True)
        
        header_frame = ttk.Frame(main_frame, relief="flat")
        header_frame.pack(fill=X, padx=10, pady=5)
        ttk.Label(header_frame, text="🛡️ MT5 Multi-Strategy Bot", font=("Segoe UI", 14, "bold"), bootstyle="inverse-primary").pack(side=LEFT)
        self.lbl_mt5 = ttk.Label(header_frame, text="MT5: Connecting...", bootstyle="warning")
        self.lbl_mt5.pack(side=LEFT, padx=20)
        self.lbl_time = ttk.Label(header_frame, text="", font=("Segoe UI", 9))
        self.lbl_time.pack(side=RIGHT)

        notebook = ttk.Notebook(main_frame, padding=5)
        notebook.pack(fill=BOTH, expand=True, padx=5, pady=5)

        dashboard_tab = ttk.Frame(notebook)
        notebook.add(dashboard_tab, text="📈 Dashboard")
        self._build_dashboard_tab(dashboard_tab)

        settings_tab = ttk.Frame(notebook)
        notebook.add(settings_tab, text="⚙️ Settings")
        self._build_settings_tab(settings_tab)

        logs_tab = ttk.Frame(notebook)
        notebook.add(logs_tab, text="📝 Logs")
        self.log_text = scrolledtext.ScrolledText(logs_tab, height=15, font=('Consolas', 9))
        self.log_text.pack(fill=BOTH, expand=True)

        news_tab = ttk.Frame(notebook)
        notebook.add(news_tab, text="📰 News")
        self.news_text = scrolledtext.ScrolledText(news_tab, height=15, font=('Consolas', 9))
        self.news_text.pack(fill=BOTH, expand=True)

    def _build_dashboard_tab(self, parent):
        parent.grid_columnconfigure(0, weight=1)
        parent.grid_columnconfigure(1, weight=1)
        parent.grid_rowconfigure(0, weight=1)

        left_frame = ttk.Frame(parent, padding=10)
        left_frame.grid(row=0, column=0, sticky="nsew")
        
        stats_frame = ttk.LabelFrame(left_frame, text="📊 Account", padding=10)
        stats_frame.pack(fill=X, pady=5)
        
        self.lbl_balance = ttk.Label(stats_frame, text="💰 Balance: $0.00", font=("Segoe UI", 14, "bold"), bootstyle="success")
        self.lbl_balance.pack(anchor=W, pady=2)
        
        self.lbl_profit = ttk.Label(stats_frame, text="📈 P/L: $0.00", font=("Segoe UI", 12), bootstyle="info")
        self.lbl_profit.pack(anchor=W, pady=2)
        
        pos_row = ttk.Frame(stats_frame)
        pos_row.pack(fill=X, pady=2)
        self.lbl_positions = ttk.Label(pos_row, text="📦 Positions: 0/1", font=("Segoe UI", 10))
        self.lbl_positions.pack(side=LEFT)
        self.lbl_buysell = ttk.Label(pos_row, text="🟢 0 | 🔴 0", font=("Segoe UI", 10), foreground="#888")
        self.lbl_buysell.pack(side=RIGHT)
        
        self.lbl_server_time = ttk.Label(stats_frame, text="🕒 MT5: --:--:--", font=("Segoe UI", 9), foreground="#888")
        self.lbl_server_time.pack(anchor=W, pady=2)

        perf_frame = ttk.LabelFrame(left_frame, text="📈 Performance", padding=10, bootstyle="secondary")
        perf_frame.pack(fill=X, pady=5)

        self.lbl_prof_today = ttk.Label(perf_frame, text="Today: $0.00", font=("Segoe UI", 10, "bold"))
        self.lbl_prof_today.pack(anchor=W, pady=2)

        self.lbl_prof_week = ttk.Label(perf_frame, text="Week: $0.00", font=("Segoe UI", 10))
        self.lbl_prof_week.pack(anchor=W, pady=2)

        self.lbl_prof_month = ttk.Label(perf_frame, text="Month: $0.00", font=("Segoe UI", 10))
        self.lbl_prof_month.pack(anchor=W, pady=2)

        ind_frame = ttk.LabelFrame(left_frame, text="📉 Indicators", padding=10, bootstyle="info")
        ind_frame.pack(fill=X, pady=5)
        
        self.lbl_live_rsi = ttk.Label(ind_frame, text="RSI: --", font=("Segoe UI", 11, "bold"))
        self.lbl_live_rsi.pack(anchor=W, pady=2)
        
        self.lbl_live_macd = ttk.Label(ind_frame, text="MACD: --", font=("Segoe UI", 10))
        self.lbl_live_macd.pack(anchor=W, pady=2)

        self.lbl_detected_zone = ttk.Label(ind_frame, text="Zone: --", font=("Segoe UI", 10), bootstyle="warning")
        self.lbl_detected_zone.pack(anchor=W, pady=2)
        
        self.lbl_sync = ttk.Label(ind_frame, text="🔄 Sync: Waiting...", font=("Segoe UI", 9), foreground="#888")
        self.lbl_sync.pack(anchor=W, pady=2)

        right_frame = ttk.Frame(parent, padding=10)
        right_frame.grid(row=0, column=1, sticky="nsew")
        
        strat_frame = ttk.LabelFrame(right_frame, text="🎯 U16 Strategy", padding=10, bootstyle="primary")
        strat_frame.pack(fill=X, pady=5)
        
        self.lbl_buy_logic = ttk.Label(strat_frame, text="🟢 BUY: Score ≥ 4", font=("Segoe UI", 10, "bold"), foreground="#2ecc71")
        self.lbl_buy_logic.pack(anchor=W)
        self.lbl_sell_logic = ttk.Label(strat_frame, text="🔴 SELL: Score ≥ 4", font=("Segoe UI", 10, "bold"), foreground="#e74c3c")
        self.lbl_sell_logic.pack(anchor=W)
        
        ttk.Checkbutton(strat_frame, text="Auto Trade", variable=self.auto_trade_var, command=self._on_auto_toggle, bootstyle="success-round-toggle").pack(pady=(10, 0))

        ctl_box = ttk.LabelFrame(right_frame, text="⚡ Quick Trade", padding=10)
        ctl_box.pack(fill=X, pady=5)
        
        sel_frame = ttk.Frame(ctl_box)
        sel_frame.pack(fill=X, pady=5)

        ttk.Label(sel_frame, text="Symbol:").pack(side=LEFT)
        self.combo_symbol = ttk.Combobox(sel_frame, textvariable=self.symbol_var, state="readonly", width=12)
        self.combo_symbol.pack(side=LEFT, padx=5)
        self.combo_symbol.bind("<<ComboboxSelected>>", self._on_symbol_change)

        ttk.Label(sel_frame, text="TF:").pack(side=LEFT, padx=(10, 0))
        self.combo_tf = ttk.Combobox(sel_frame, textvariable=self.tf_var, state="readonly", width=5)
        self.combo_tf['values'] = ["M1", "M5", "M15", "M30", "H1", "H4", "D1"]
        self.combo_tf.pack(side=LEFT, padx=5)
        self.combo_tf.bind("<<ComboboxSelected>>", self._on_tf_change)
        
        self.strategy_mode_var.set("U16_STRATEGY")
        
        prices_frame = ttk.Frame(ctl_box)
        prices_frame.pack(fill=X, pady=10)
        self.lbl_bid = ttk.Label(prices_frame, text="BID: 0.00", bootstyle="info", font=("Segoe UI", 14))
        self.lbl_bid.pack(side=LEFT, padx=10)
        self.lbl_ask = ttk.Label(prices_frame, text="ASK: 0.00", bootstyle="success", font=("Segoe UI", 14))
        self.lbl_ask.pack(side=RIGHT, padx=10)

        btn_grid = ttk.Frame(ctl_box)
        btn_grid.pack(fill=X, pady=5)
        ttk.Button(btn_grid, text="🟢 BUY", command=self._on_buy, bootstyle="success").pack(side=LEFT, fill=X, expand=True, padx=2)
        ttk.Button(btn_grid, text="🔴 SELL", command=self._on_sell, bootstyle="danger").pack(side=LEFT, fill=X, expand=True, padx=2)
        
        close_grid = ttk.Frame(ctl_box)
        close_grid.pack(fill=X, pady=5)
        ttk.Button(close_grid, text="💰 Close Profit", command=self._on_close_profit, bootstyle="success-outline").pack(side=LEFT, fill=X, expand=True, padx=2)
        ttk.Button(close_grid, text="📉 Close Loss", command=self._on_close_loss, bootstyle="danger-outline").pack(side=LEFT, fill=X, expand=True, padx=2)
        
        ttk.Button(ctl_box, text="❌ CLOSE ALL", command=self._on_close_all, bootstyle="warning-outline").pack(fill=X, pady=5)

    def _build_settings_tab(self, parent):
        canvas = tk.Canvas(parent, highlightthickness=0)
        scrollbar = ttk.Scrollbar(parent, orient="vertical", command=canvas.yview)
        scroll_frame = ttk.Frame(canvas)

        scroll_frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=scroll_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        
        scroll_frame.columnconfigure(0, weight=1)
        scroll_frame.columnconfigure(1, weight=1)

        col0 = ttk.Frame(scroll_frame)
        col0.grid(row=0, column=0, sticky="nsew", padx=10, pady=10)
        
        trade_frame = ttk.LabelFrame(col0, text="📈 Trade Settings", padding=15)
        trade_frame.pack(fill=X, pady=5)
        
        ttk.Label(trade_frame, text="Max Positions:").grid(row=0, column=0, sticky=W, pady=5)
        ttk.Spinbox(trade_frame, from_=1, to=10, textvariable=self.max_pos_var, width=8).grid(row=0, column=1, sticky=W, padx=10)
        
        ttk.Label(trade_frame, text="Lot Size:").grid(row=1, column=0, sticky=W, pady=5)
        ttk.Spinbox(trade_frame, from_=0.01, to=10.0, increment=0.01, textvariable=self.lot_size_var, width=8).grid(row=1, column=1, sticky=W, padx=10)
        
        ttk.Label(trade_frame, text="Cooldown (sec):").grid(row=2, column=0, sticky=W, pady=5)
        ttk.Spinbox(trade_frame, from_=5, to=300, textvariable=self.cooldown_var, width=8).grid(row=2, column=1, sticky=W, padx=10)

        filter_frame = ttk.LabelFrame(col0, text="🎯 Filters", padding=15, bootstyle="info")
        filter_frame.pack(fill=X, pady=5)
        
        ttk.Checkbutton(filter_frame, text="Trend Filter (EMA 200)", variable=self.use_trend_filter_var, bootstyle="success-round-toggle").pack(anchor=W, pady=3)
        ttk.Checkbutton(filter_frame, text="Zone Filter (S/R)", variable=self.use_zone_filter_var, bootstyle="success-round-toggle").pack(anchor=W, pady=3)
        ttk.Checkbutton(filter_frame, text="Time Filter", variable=self.use_time_filter_var, bootstyle="success-round-toggle").pack(anchor=W, pady=3)
        
        time_row = ttk.Frame(filter_frame)
        time_row.pack(fill=X, pady=(5, 0))
        ttk.Label(time_row, text="Hours:").pack(side=LEFT)
        ttk.Spinbox(time_row, from_=0, to=23, textvariable=self.start_hour_var, width=4).pack(side=LEFT, padx=5)
        ttk.Label(time_row, text="to").pack(side=LEFT)
        ttk.Spinbox(time_row, from_=0, to=23, textvariable=self.end_hour_var, width=4).pack(side=LEFT, padx=5)

        risk_frame = ttk.LabelFrame(col0, text="🛡️ Risk", padding=15, bootstyle="success")
        risk_frame.pack(fill=X, pady=5)
        
        ttk.Label(risk_frame, text="R:R Ratio (1:X):").grid(row=0, column=0, sticky=W, pady=5)
        ttk.Spinbox(risk_frame, from_=1.0, to=10.0, increment=0.5, textvariable=self.rr_ratio_var, width=8).grid(row=0, column=1, sticky=W, padx=10)

        col1 = ttk.Frame(scroll_frame)
        col1.grid(row=0, column=1, sticky="nsew", padx=10, pady=10)

        profit_frame = ttk.LabelFrame(col1, text="💰 Profit Management", padding=15, bootstyle="warning")
        profit_frame.pack(fill=X, pady=5)
        
        ttk.Checkbutton(profit_frame, text="Enable Auto Profit Close", variable=self.use_profit_mgmt_var, bootstyle="warning-round-toggle").pack(anchor=W, pady=3)
        
        row1 = ttk.Frame(profit_frame)
        row1.pack(fill=X, pady=3)
        ttk.Label(row1, text="Check Every (sec):").pack(side=LEFT)
        ttk.Spinbox(row1, from_=1, to=60, textvariable=self.auto_close_sec_var, width=8).pack(side=RIGHT)
        
        row2 = ttk.Frame(profit_frame)
        row2.pack(fill=X, pady=3)
        ttk.Label(row2, text="Min Profit ($):").pack(side=LEFT)
        ttk.Spinbox(row2, from_=0.05, to=10.0, increment=0.05, textvariable=self.min_profit_var, width=8).pack(side=RIGHT)

        crt_frame = ttk.LabelFrame(col1, text="📊 CRT Range Settings", padding=15, bootstyle="danger")
        crt_frame.pack(fill=X, pady=5)
        
        ttk.Label(crt_frame, text="Big Timeframe:").grid(row=0, column=0, sticky=W, pady=5)
        self.crt_htf_combo = ttk.Combobox(crt_frame, values=["15m", "30m", "1H", "4H", "D1"], state="readonly", width=8)
        self.crt_htf_combo.grid(row=0, column=1, sticky=W, padx=10)
        self.crt_htf_combo.set("4H")
        self.crt_htf_combo.bind("<<ComboboxSelected>>", self._on_crt_htf_change)
        
        ttk.Label(crt_frame, text="Sweep Lookback:").grid(row=1, column=0, sticky=W, pady=5)
        ttk.Spinbox(crt_frame, from_=1, to=50, textvariable=self.crt_lookback_var, width=8).grid(row=1, column=1, sticky=W, padx=10)
        
        self.crt_progress_lbl = ttk.Label(crt_frame, text="Range: Waiting...", font=("", 9), foreground="#3498db")
        self.crt_progress_lbl.grid(row=2, column=0, columnspan=2, sticky=W, pady=(10, 0))

        info_frame = ttk.LabelFrame(col1, text="ℹ️ U16 Strategy", padding=15, bootstyle="primary")
        info_frame.pack(fill=X, pady=5)
        
        signals = [
            "✓ RSI + MACD + Stochastic",
            "✓ Ichimoku Cloud",
            "✓ Price Action Patterns",
            "✓ ICT Fair Value Gaps",
            "✓ CRT Sweep & Reclaim",
            "✓ Support/Resistance Zones"
        ]
        for sig in signals:
            ttk.Label(info_frame, text=sig, font=("", 9), foreground="#00bc8c").pack(anchor=W, pady=1)
        
        ttk.Label(info_frame, text="\n🎯 Trade when Score ≥ 4", font=("", 10, "bold"), foreground="#f39c12").pack(anchor=W, pady=5)

    def _add_setting(self, parent, label_text, variable, min_val, max_val, row_idx):
        ttk.Label(parent, text=label_text).grid(row=row_idx, column=0, sticky=W, padx=5, pady=2)
        if isinstance(variable, tk.IntVar) or isinstance(variable, tk.DoubleVar):
            step = 1 if isinstance(variable, tk.IntVar) else 0.1
            ttk.Spinbox(parent, from_=min_val, to=max_val, increment=step, textvariable=variable, width=10).grid(row=row_idx, column=1, sticky=W, padx=5)