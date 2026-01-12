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
        self.strategy_mode_var = tk.StringVar(value="MACD_RSI")
        self.use_trend_filter_var = tk.BooleanVar(value=True) 
        self.use_zone_filter_var = tk.BooleanVar(value=True) 

        # Profit Settings
        self.auto_close_sec_var = tk.DoubleVar(value=2.0)
        self.use_profit_mgmt_var = tk.BooleanVar(value=True)
        self.rr_ratio_var = tk.DoubleVar(value=2.0)

        # Indicator Settings (Optimized for M5)
        self.rsi_period_var = tk.IntVar(value=9)
        self.rsi_buy_var = tk.IntVar(value=35)
        self.rsi_sell_var = tk.IntVar(value=65)
        
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
            self.rsi_period_var, self.rsi_buy_var, self.rsi_sell_var,
            self.macd_fast_var, self.macd_slow_var, self.macd_signal_var,
            self.bb_period_var, self.bb_dev_var, self.ema_fast_var, self.ema_slow_var,
            self.use_time_filter_var, self.time_zone_var, self.start_hour_var, self.end_hour_var,
            self.crt_htf_var, self.crt_lookback_var, self.crt_zone_var
        ]
        for var in vars_to_trace:
            var.trace_add("write", self._on_setting_changed)

    def _safe_get(self, var, default=0):
        """Safely get a value from a Tkinter variable, returning default if empty."""
        try:
            val = var.get()
            return val if val != "" else default
        except:
            return default

    def _sync_ui_to_strategy(self):
        if self.strategy:
            try:
                # Basic Settings
                self.strategy.set_active(self.auto_trade_var.get())
                self.strategy.max_positions = self._safe_get(self.max_pos_var, 1)
                self.strategy.lot_size = self._safe_get(self.lot_size_var, 0.01)
                self.strategy.trade_cooldown = self._safe_get(self.cooldown_var, 15.0)
                
                # Logic & Filters
                self.strategy.strategy_mode = self.strategy_mode_var.get()
                self.strategy.use_trend_filter = self.use_trend_filter_var.get()
                self.strategy.use_zone_filter = self.use_zone_filter_var.get()

                # Profit
                self.strategy.profit_close_interval = self._safe_get(self.auto_close_sec_var, 2.0)
                self.strategy.use_profit_management = self.use_profit_mgmt_var.get()
                self.strategy.risk_reward_ratio = self._safe_get(self.rr_ratio_var, 2.0)

                # Indicators
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

                # Time Filter Sync
                self.strategy.use_time_filter = self.use_time_filter_var.get()
                self.strategy.time_zone = self.time_zone_var.get()
                self.strategy.start_hour = self._safe_get(self.start_hour_var, 8)
                self.strategy.end_hour = self._safe_get(self.end_hour_var, 20)

                # CRT Sync
                self.strategy.crt_htf = self._safe_get(self.crt_htf_var, 240)
                self.strategy.crt_lookback = self._safe_get(self.crt_lookback_var, 10)
                self.strategy.crt_zone_size = self._safe_get(self.crt_zone_var, 0.25)

                logging.info(f"Settings Updated: Mode={self.strategy.strategy_mode} | Trend={self.strategy.use_trend_filter} | Zone={self.strategy.use_zone_filter}")
            except (tk.TclError, ValueError, TypeError):
                # Silently catch errors while user is typing in boxes
                pass
            except Exception as e:
                logging.debug(f"Sync error: {e}")

    def _update_strategy_logic_text(self):
        if not hasattr(self, 'lbl_buy_logic'): return
        
        mode = self.strategy_mode_var.get()
        rsi_b = self._safe_get(self.rsi_buy_var, 30)
        rsi_s = self._safe_get(self.rsi_sell_var, 70)
        
        if mode == "MACD_RSI":
            self.lbl_buy_logic.config(text=f"🟢 BUY: RSI < {rsi_b} & MACD > Sig")
            self.lbl_sell_logic.config(text=f"🔴 SELL: RSI > {rsi_s} & MACD < Sig")
        elif mode == "BOLLINGER":
            self.lbl_buy_logic.config(text=f"🟢 BUY: Price < Lower BB & RSI < {rsi_b}")
            self.lbl_sell_logic.config(text=f"🔴 SELL: Price > Upper BB & RSI > {rsi_s}")
        elif mode == "EMA_CROSS":
            ema_f = self._safe_get(self.ema_fast_var, 9)
            ema_s = self._safe_get(self.ema_slow_var, 21)
            self.lbl_buy_logic.config(text=f"🟢 BUY: EMA {ema_f} Crosses Above {ema_s}")
            self.lbl_sell_logic.config(text=f"🔴 SELL: EMA {ema_f} Crosses Below {ema_s}")
        elif mode == "SMC":
            self.lbl_buy_logic.config(text=f"🟢 BUY: Retrace into Bullish FVG (Gap)")
            self.lbl_sell_logic.config(text=f"🔴 SELL: Retrace into Bearish FVG (Gap)")
        elif mode == "CRT":
            htf = self._safe_get(self.crt_htf_var, 240)
            h_label = f"{htf//60}H" if htf % 60 == 0 else f"{htf}m"
            self.lbl_buy_logic.config(text=f"🟢 BUY: {h_label} Low Sweep & M5/M15 Reclaim")
            self.lbl_sell_logic.config(text=f"🔴 SELL: {h_label} High Sweep & M5/M15 Reclaim")

    def _on_tick_received(self, symbol, bid, ask, balance, profit, acct_name, positions, buy_count, sell_count, avg_entry, candles):
        self.last_price_update = time.time() 
        self.after(0, lambda: self._update_ui_data(symbol, bid, ask, balance, profit, acct_name, positions, candles))
        
        if profit != 0 and (not self.profit_history or self.profit_history[-1][1] != profit):
             self.profit_history.append((time.strftime("%H:%M:%S"), profit))
             if len(self.profit_history) > 50: self.profit_history.pop(0)

    def _on_symbols_received(self, symbols_list):
        if not self.symbols_loaded:
            self.after(0, lambda: self._set_combo_values(symbols_list))
            self.symbols_loaded = True

    def _update_ui_data(self, symbol, bid, ask, balance, profit, acct_name, positions, candles):
        try:
            clean_symbol = str(symbol).replace('\x00', '').strip()
            if not self.symbol_var.get(): self.symbol_var.set(clean_symbol)

            if clean_symbol == self.symbol_var.get():
                tf_display = self.tf_var.get()
                mode_display = self.strategy_mode_var.get()
                self.lbl_mt5.config(text=f"MT5: {clean_symbol} [{tf_display}] ({mode_display})", bootstyle="success")
                self.lbl_bid.config(text=f"{bid:.5f}")
                self.lbl_ask.config(text=f"{ask:.5f}")

            self._update_card(self.lbl_balance, f"${balance:,.2f}", "success" if balance > 5000 else "info")
            self._update_card(self.lbl_profit, f"${profit:+,.2f}", "success" if profit >= 0 else "danger")
            self._update_card(self.lbl_positions, f"{positions}/{self.max_pos_var.get()}", "warning" if positions >= self.max_pos_var.get() else "secondary")
            
            # --- Sync Status Calculation ---
            min_needed = 200
            if self.strategy_mode_var.get() == "CRT":
                min_needed = (self.crt_htf_var.get() // 5) * 3 
            
            count = len(candles)
            if count >= min_needed:
                self._update_card(self.lbl_sync, "READY", "success")
            else:
                self._update_card(self.lbl_sync, f"{count}/{min_needed}", "warning")

            # --- Server Time Update ---
            if count > 0:
                last_time = candles[-1]['time']
                st_str = datetime.fromtimestamp(last_time).strftime('%H:%M:%S')
                self._update_card(self.lbl_server_time, st_str, "primary")

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

                # --- Zone Display (UPDATED for Tradeciety Zones) ---
                if self.use_zone_filter_var.get():
                    # Support Zone Display
                    supp_txt = "None"
                    if hasattr(self.strategy, 'support_zones') and self.strategy.support_zones:
                        # zones sorted by proximity, index 0 is nearest
                        zone = self.strategy.support_zones[0]
                        supp_txt = f"{zone['top']:.2f}"
                    
                    # Resistance Zone Display
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
    
    def _on_mode_change(self, event=None):
        self._on_setting_changed()

    def _on_symbol_change(self, event=None):
        symbol = self.symbol_var.get()
        if symbol:
            self.mt5_connector.change_symbol(symbol)
            logging.info(f"Requested Symbol change to: {symbol}")
            # Reset UI labels to show we're waiting for new data
            self.lbl_live_rsi.config(text="RSI: Waiting...", bootstyle="secondary")
            self.lbl_live_macd.config(text="MACD: Waiting...", bootstyle="secondary")
            self.lbl_detected_zone.config(text="Zone: Detecting...", bootstyle="secondary")
            
            if self.strategy and hasattr(self.strategy, 'reset_state'):
                self.strategy.reset_state()

    def _on_tz_change(self, event=None):
        tz = self.time_zone_var.get()
        # Official Session Hours (Local Time)
        session_hours = {
            "London": (8, 17),
            "New York": (8, 17),
            "Tokyo": (9, 18),
            "Sydney": (7, 16),
            "Auto": (0, 23) # Open wide for auto-rotation
        }
        if tz in session_hours:
            start, end = session_hours[tz]
            self.start_hour_var.set(start)
            self.end_hour_var.set(end)
            logging.info(f"Market Hours synced for {tz}: {start:02d}:00 - {end:02d}:00")

    def _on_crt_htf_change(self, event=None):
        selection = self.crt_htf_combo.get()
        mapping = {"15 Min": 15, "30 Min": 30, "1 Hour (60m)": 60, "4 Hours (240m)": 240, "1 Day (1440m)": 1440}
        minutes = mapping.get(selection, 60)
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

        # Left Column
        left_frame = ttk.Frame(parent, padding=10)
        left_frame.grid(row=0, column=0, sticky="nsew")
        
        self._create_stat_card(left_frame, "💰 Balance", "$0.00", "success").pack(fill=X, pady=5)
        self.lbl_balance = left_frame.winfo_children()[-1].winfo_children()[0]
        
        self._create_stat_card(left_frame, "📉 Profit", "$0.00", "info").pack(fill=X, pady=5)
        self.lbl_profit = left_frame.winfo_children()[-1].winfo_children()[0]
        
        self._create_stat_card(left_frame, "📊 Positions", "0/0", "warning").pack(fill=X, pady=5)
        self.lbl_positions = left_frame.winfo_children()[-1].winfo_children()[0]

        # Sync Card
        self._create_stat_card(left_frame, "🕒 Server Time", "Waiting...", "primary").pack(fill=X, pady=5)
        self.lbl_server_time = left_frame.winfo_children()[-1].winfo_children()[0]

        self._create_stat_card(left_frame, "🔄 Data Sync", "Scanning...", "info").pack(fill=X, pady=5)
        self.lbl_sync = left_frame.winfo_children()[-1].winfo_children()[0]

        # Right Column
        right_frame = ttk.Frame(parent, padding=10)
        right_frame.grid(row=0, column=1, sticky="nsew")
        
        ind_frame = ttk.LabelFrame(right_frame, text="Live Indicators & Zone", padding=10, bootstyle="info")
        ind_frame.pack(fill=X, pady=(0, 5))
        
        self.lbl_live_rsi = ttk.Label(ind_frame, text="RSI: Waiting...", font=("Segoe UI", 12, "bold"), bootstyle="secondary")
        self.lbl_live_rsi.pack(fill=X, pady=2)
        
        self.lbl_live_macd = ttk.Label(ind_frame, text="MACD: Waiting...", font=("Segoe UI", 10), bootstyle="secondary")
        self.lbl_live_macd.pack(fill=X, pady=2)

        # Detected Zone Label
        self.lbl_detected_zone = ttk.Label(ind_frame, text="Zone: Detecting...", font=("Segoe UI", 11, "bold"), bootstyle="secondary")
        self.lbl_detected_zone.pack(fill=X, pady=5)

        logic_frame = ttk.LabelFrame(right_frame, text="Active Strategy Logic", padding=5)
        logic_frame.pack(fill=X, pady=5)
        
        self.lbl_buy_logic = ttk.Label(logic_frame, text="", font=("Segoe UI", 9, "bold"), foreground="#2ecc71")
        self.lbl_buy_logic.pack(anchor=W)
        self.lbl_sell_logic = ttk.Label(logic_frame, text="", font=("Segoe UI", 9, "bold"), foreground="#e74c3c")
        self.lbl_sell_logic.pack(anchor=W)

        ctl_box = ttk.LabelFrame(right_frame, text="Execution", padding=10)
        ctl_box.pack(fill=X, pady=5)
        
        # --- Symbol + Timeframe + Strategy Row ---
        sel_frame = ttk.Frame(ctl_box)
        sel_frame.pack(fill=X, pady=(0, 5))

        # Symbol
        sym_frame = ttk.Frame(sel_frame)
        sym_frame.pack(side=LEFT, fill=X, expand=True)
        ttk.Label(sym_frame, text="Symbol:", font=("Segoe UI", 9)).pack(anchor=W)
        self.combo_symbol = ttk.Combobox(sym_frame, textvariable=self.symbol_var, state="readonly", width=10)
        self.combo_symbol.pack(fill=X)
        self.combo_symbol.bind("<<ComboboxSelected>>", self._on_symbol_change)

        # Timeframe
        tf_frame = ttk.Frame(sel_frame)
        tf_frame.pack(side=LEFT, padx=5)
        ttk.Label(tf_frame, text="TF:", font=("Segoe UI", 9)).pack(anchor=W)
        self.combo_tf = ttk.Combobox(tf_frame, textvariable=self.tf_var, state="readonly", width=5)
        self.combo_tf['values'] = ["M1", "M5", "M15", "M30", "H1", "H4", "D1"]
        self.combo_tf.pack(fill=X)
        self.combo_tf.bind("<<ComboboxSelected>>", self._on_tf_change)

        # Strategy
        strat_frame = ttk.Frame(sel_frame)
        strat_frame.pack(side=LEFT, padx=5, fill=X, expand=True)
        ttk.Label(strat_frame, text="Active Strategy:", font=("Segoe UI", 9)).pack(anchor=W)
        self.combo_strat = ttk.Combobox(strat_frame, textvariable=self.strategy_mode_var, state="readonly", width=15)
        self.combo_strat['values'] = ["MACD_RSI", "BOLLINGER", "EMA_CROSS", "SMC", "CRT"]
        self.combo_strat.pack(fill=X)
        self.combo_strat.bind("<<ComboboxSelected>>", self._on_mode_change)
        
        prices_frame = ttk.Frame(ctl_box)
        prices_frame.pack(fill=X, pady=5)
        self.lbl_bid = ttk.Label(prices_frame, text="0.000", bootstyle="info", font=("Segoe UI", 16))
        self.lbl_bid.pack(side=LEFT, padx=10)
        self.lbl_ask = ttk.Label(prices_frame, text="0.000", bootstyle="success", font=("Segoe UI", 16))
        self.lbl_ask.pack(side=RIGHT, padx=10)

        btn_grid = ttk.Frame(ctl_box)
        btn_grid.pack(fill=X, pady=10)
        ttk.Button(btn_grid, text="BUY", command=self._on_buy, bootstyle="success").pack(side=LEFT, fill=X, expand=True, padx=2)
        ttk.Button(btn_grid, text="SELL", command=self._on_sell, bootstyle="danger").pack(side=LEFT, fill=X, expand=True, padx=2)
        
        ttk.Button(ctl_box, text="CLOSE ALL", command=self._on_close_all, bootstyle="warning-outline").pack(fill=X, pady=5)
        
        auto_frame = ttk.LabelFrame(right_frame, text="Auto Strategy", padding=10)
        auto_frame.pack(fill=X, pady=10)
        ttk.Checkbutton(auto_frame, text="Enable Auto Trade", variable=self.auto_trade_var, command=self._on_auto_toggle, bootstyle="round-toggle").pack()

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
        scroll_frame.columnconfigure(2, weight=1)

        # --- Column 0: General & Filters ---
        col0_frame = ttk.Frame(scroll_frame)
        col0_frame.grid(row=0, column=0, sticky="nsew", padx=5, pady=5)
        
        gen_frame = ttk.LabelFrame(col0_frame, text="General Settings", padding=10)
        gen_frame.pack(fill=X, pady=5)
        self._add_setting(gen_frame, "Max Open Positions:", self.max_pos_var, 1, 10, 0)
        self._add_setting(gen_frame, "Lot Size:", self.lot_size_var, 0.01, 10.0, 1)
        self._add_setting(gen_frame, "Trade Cooldown (sec):", self.cooldown_var, 5.0, 300.0, 2)

        # NEW: Filters
        filter_frame = ttk.LabelFrame(col0_frame, text="Strategy Filters", padding=10, bootstyle="secondary")
        filter_frame.pack(fill=X, pady=5)
        ttk.Checkbutton(filter_frame, text="Use Trend Filter (200 EMA)", variable=self.use_trend_filter_var, bootstyle="round-toggle").pack(anchor=W, pady=2)
        ttk.Checkbutton(filter_frame, text="Use Zone Filter (Supp/Res)", variable=self.use_zone_filter_var, bootstyle="round-toggle").pack(anchor=W, pady=2)

        risk_frame = ttk.LabelFrame(col0_frame, text="Risk Management", padding=10, bootstyle="success")
        risk_frame.pack(fill=X, pady=5)
        self._add_setting(risk_frame, "Risk/Reward Ratio (1:x):", self.rr_ratio_var, 1.0, 10.0, 0)

        # NEW: Time Filter
        time_frame = ttk.LabelFrame(col0_frame, text="Time Filter", padding=10, bootstyle="info")
        time_frame.pack(fill=X, pady=5)
        ttk.Checkbutton(time_frame, text="Use Time Filter", variable=self.use_time_filter_var, bootstyle="round-toggle").pack(anchor=W, pady=2)
        
        ttk.Label(time_frame, text="Time Zone (Session):").pack(anchor=W, pady=(5,0))
        self.combo_tz = ttk.Combobox(time_frame, textvariable=self.time_zone_var, state="readonly")
        self.combo_tz['values'] = ["Local", "London", "New York", "Tokyo", "Sydney", "Auto"]
        self.combo_tz.pack(fill=X, pady=2)
        self.combo_tz.bind("<<ComboboxSelected>>", self._on_tz_change)
        
        # Grid frame for the spinboxes
        time_grid = ttk.Frame(time_frame)
        time_grid.pack(fill=X, pady=5)
        self._add_setting(time_grid, "Start Hour:", self.start_hour_var, 0, 23, 0)
        self._add_setting(time_grid, "End Hour:", self.end_hour_var, 0, 23, 1)

        # --- Column 1: Profit ---
        col1_frame = ttk.Frame(scroll_frame)
        col1_frame.grid(row=0, column=1, sticky="nsew", padx=5, pady=5)

        prof_frame = ttk.LabelFrame(col1_frame, text="Profit & Trailing Settings", padding=10, bootstyle="warning")
        prof_frame.pack(fill=X, pady=5)
        ttk.Checkbutton(prof_frame, text="Active", variable=self.use_profit_mgmt_var, bootstyle="round-toggle").pack(anchor=W, pady=(0, 5))
        
        # Container for settings to easily add logic
        prof_settings = ttk.Frame(prof_frame)
        prof_settings.pack(fill=X)
        self._add_setting(prof_settings, "Auto Close (sec):", self.auto_close_sec_var, 1.0, 60.0, 0)
        
        # --- Column 2: Indicators ---
        col2_frame = ttk.Frame(scroll_frame)
        col2_frame.grid(row=0, column=2, sticky="nsew", padx=5, pady=5)

        rsi_frame = ttk.LabelFrame(col2_frame, text="RSI Settings", padding=10, bootstyle="info")
        rsi_frame.pack(fill=X, pady=5)
        self._add_setting(rsi_frame, "RSI Period:", self.rsi_period_var, 2, 50, 0)
        self._add_setting(rsi_frame, "Oversold (Buy if <):", self.rsi_buy_var, 10, 50, 1)
        self._add_setting(rsi_frame, "Overbought (Sell if >):", self.rsi_sell_var, 50, 90, 2)

        macd_frame = ttk.LabelFrame(col2_frame, text="MACD Settings", padding=10, bootstyle="primary")
        macd_frame.pack(fill=X, pady=5)
        self._add_setting(macd_frame, "Fast EMA:", self.macd_fast_var, 5, 50, 0)
        self._add_setting(macd_frame, "Slow EMA:", self.macd_slow_var, 10, 100, 1)
        self._add_setting(macd_frame, "Signal SMA:", self.macd_signal_var, 2, 50, 2)

        # NEW: Bollinger & EMA
        other_ind_frame = ttk.LabelFrame(col2_frame, text="Bollinger & EMA Settings", padding=10, bootstyle="light")
        other_ind_frame.pack(fill=X, pady=5)
        self._add_setting(other_ind_frame, "BB Period:", self.bb_period_var, 10, 50, 0)
        self._add_setting(other_ind_frame, "BB Deviation:", self.bb_dev_var, 0.5, 4.0, 1)
        self._add_setting(other_ind_frame, "EMA Fast:", self.ema_fast_var, 2, 50, 2)
        self._add_setting(other_ind_frame, "EMA Slow:", self.ema_slow_var, 5, 200, 3)

        # NEW: CRT Settings
        crt_frame = ttk.LabelFrame(col2_frame, text="CRT Strategy Settings", padding=10, bootstyle="danger")
        crt_frame.pack(fill=X, pady=5)
        
        # 1. Big TF Dropdown
        ttk.Label(crt_frame, text="Big TF (Range):").grid(row=0, column=0, sticky=W, padx=5, pady=2)
        self.crt_htf_combo = ttk.Combobox(crt_frame, values=["15 Min", "30 Min", "1 Hour (60m)", "4 Hours (240m)", "1 Day (1440m)"], state="readonly", width=15)
        self.crt_htf_combo.grid(row=0, column=1, sticky=W, padx=5)
        self.crt_htf_combo.bind("<<ComboboxSelected>>", self._on_crt_htf_change)
        
        # Set initial value based on current var
        mapping_inv = {15: "15 Min", 30: "30 Min", 60: "1 Hour (60m)", 240: "4 Hours (240m)", 1440: "1 Day (1440m)"}
        self.crt_htf_combo.set(mapping_inv.get(self.crt_htf_var.get(), "4 Hours (240m)"))

        # 2. Sweep Lookback
        self._add_setting(crt_frame, "Sweep Lookback:", self.crt_lookback_var, 1, 50, 1)
        
        # 3. Entry Zone
        self._add_setting(crt_frame, "Entry Zone (%):", self.crt_zone_var, 0.05, 0.50, 2)
        
        # 4. Progress Label (Dynamic Update)
        self.crt_progress_lbl = ttk.Label(crt_frame, text="Range Progress: Waiting...", font=("", 8, "italic"), foreground="#3498db")
        self.crt_progress_lbl.grid(row=3, column=0, columnspan=2, sticky=W, padx=5, pady=(5,0))
        
        # Guide Frame for Time Conversion
        g_frame = ttk.Frame(crt_frame)
        g_frame.grid(row=4, column=0, columnspan=2, sticky=W, pady=5)
        
        ttk.Label(g_frame, text="Formula: Lookback × Chart TF = Search Time", font=("", 8, "bold"), foreground="#e67e22").pack(anchor=W)
        guide_text = (
            "• M5 Chart  + 1 Lookback  = 5 Mins\n"
            "• M5 Chart  + 12 Lookback = 60 Mins (1H)\n"
            "• M15 Chart + 4 Lookback  = 60 Mins (1H)\n"
            "• M1 Chart  + 10 Lookback = 10 Mins"
        )
        ttk.Label(g_frame, text=guide_text, font=("", 8), foreground="#bdc3c7", justify=LEFT).pack(anchor=W, padx=5)
        
        ttk.Label(crt_frame, text="Ensures Sweep & Reclaim logic is precise for\ndual-timeframe reversal confirmations.", font=("", 8), foreground="#00bc8c", justify=LEFT).grid(row=5, column=0, columnspan=2, sticky=W, pady=(5,0))

    def _add_setting(self, parent, label_text, variable, min_val, max_val, row_idx):
        ttk.Label(parent, text=label_text).grid(row=row_idx, column=0, sticky=W, padx=5, pady=2)
        if isinstance(variable, tk.IntVar) or isinstance(variable, tk.DoubleVar):
            step = 1 if isinstance(variable, tk.IntVar) else 0.1
            ttk.Spinbox(parent, from_=min_val, to=max_val, increment=step, textvariable=variable, width=10).grid(row=row_idx, column=1, sticky=W, padx=5)