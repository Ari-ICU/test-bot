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
        self.title("MT5 Bot - Confluence Edition")
        self.geometry("1100x700") 
        self.resizable(True, True) 
        
        self.news_engine = news_engine
        self.mt5_connector = mt5_connector
        self.strategy = None
        
        self.last_price_update = time.time()
        self.symbols_loaded = False
        self.known_symbols = set()
        
        # --- UI Variables ---
        self.auto_trade_var = tk.BooleanVar(value=False)
        self.max_pos_var = tk.IntVar(value=1)
        self.lot_size_var = tk.DoubleVar(value=0.01)
        self.cooldown_var = tk.DoubleVar(value=15.0)

        # Strategy Filters
        self.use_trend_filter_var = tk.BooleanVar(value=True) 
        self.use_zone_filter_var = tk.BooleanVar(value=True) 

        # Profit Mgmt
        self.auto_close_sec_var = tk.DoubleVar(value=2.0)
        self.use_profit_mgmt_var = tk.BooleanVar(value=True)
        self.min_profit_var = tk.DoubleVar(value=0.10)
        self.break_even_var = tk.DoubleVar(value=0.50)

        # Indicators (Relevant to Confluence)
        self.rsi_period_var = tk.IntVar(value=14)
        self.macd_fast_var = tk.IntVar(value=12)
        self.macd_slow_var = tk.IntVar(value=26)
        self.macd_signal_var = tk.IntVar(value=9)

        # Dashboard Manual Inputs
        self.symbol_var = tk.StringVar()
        self.tf_var = tk.StringVar(value="5min") 
        self.manual_sl_var = tk.DoubleVar(value=0.0)
        self.manual_tp_var = tk.DoubleVar(value=0.0)
        
        # Time Filter Settings
        self.use_time_filter_var = tk.BooleanVar(value=True)
        self.start_hour_var = tk.IntVar(value=8)
        self.end_hour_var = tk.IntVar(value=20)
        
        self._bind_traces()

        self.mt5_connector.on_tick_received = self._on_tick_received
        self.mt5_connector.on_symbols_received = self._on_symbols_received
        
        self.mt5_connector.request_symbols()
        
        self._setup_logging()
        self._create_widgets()
        self._check_log_queue()
        
        self.after(5000, self._update_news)  
        self._update_header_time()

    def _bind_traces(self):
        vars_to_trace = [
            self.max_pos_var, self.lot_size_var, self.cooldown_var,
            self.use_trend_filter_var, self.use_zone_filter_var,
            self.auto_close_sec_var, self.use_profit_mgmt_var,
            self.min_profit_var, self.break_even_var,
            self.rsi_period_var,
            self.macd_fast_var, self.macd_slow_var, self.macd_signal_var,
            self.use_time_filter_var, self.start_hour_var, self.end_hour_var
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
        """Push UI values to the Strategy object."""
        if self.strategy:
            try:
                # Trading Params
                self.strategy.max_positions = self._safe_get(self.max_pos_var, 1)
                self.strategy.lot_size = self._safe_get(self.lot_size_var, 0.01)
                self.strategy.trade_cooldown = self._safe_get(self.cooldown_var, 15.0)
                
                # Filters
                self.strategy.use_trend_filter = self.use_trend_filter_var.get()
                self.strategy.use_zone_filter = self.use_zone_filter_var.get()

                # Profit
                self.strategy.profit_close_interval = self._safe_get(self.auto_close_sec_var, 2.0)
                self.strategy.use_profit_management = self.use_profit_mgmt_var.get()
                self.strategy.min_profit_target = self._safe_get(self.min_profit_var, 0.10)
                self.strategy.break_even_activation = self._safe_get(self.break_even_var, 0.50)

                # Indicators
                self.strategy.rsi_period = self._safe_get(self.rsi_period_var, 14)
                self.strategy.macd_fast = self._safe_get(self.macd_fast_var, 12)
                self.strategy.macd_slow = self._safe_get(self.macd_slow_var, 26)
                self.strategy.macd_signal = self._safe_get(self.macd_signal_var, 9)

                # Time
                self.strategy.use_time_filter = self.use_time_filter_var.get()
                self.strategy.start_hour = self._safe_get(self.start_hour_var, 8)
                self.strategy.end_hour = self._safe_get(self.end_hour_var, 20)

                logging.info(f"⚙️ Settings Sync: Active={self.strategy.active}")
            except Exception as e: logging.debug(f"Sync error: {e}")
        
    def _on_tick_received(self, symbol, bid, ask, balance, profit, acct_name, positions, buy_count, sell_count, avg_entry, candles):
        self.last_price_update = time.time() 
        self.after(0, lambda: self._update_ui_data(symbol, bid, ask, balance, profit, acct_name, positions, buy_count, sell_count, candles))

    def _on_symbols_received(self, symbols_list):
        if not self.symbols_loaded:
            self.after(0, lambda: self._set_combo_values(symbols_list))
            self.symbols_loaded = True

    def _update_ui_data(self, symbol, bid, ask, balance, profit, acct_name, positions, buy_count, sell_count, candles):
        try:
            # Sync back internal strategy state to UI if changed externally (e.g. by Webhook)
            if self.strategy:
                if self.auto_trade_var.get() != self.strategy.active:
                    self.auto_trade_var.set(self.strategy.active)

            clean_symbol = str(symbol).replace('\x00', '').strip()
            
            # Update Symbol List
            if clean_symbol not in self.known_symbols:
                self.known_symbols.add(clean_symbol)
                current_values = list(self.combo_symbol['values'])
                if clean_symbol not in current_values:
                    current_values.append(clean_symbol)
                    self.combo_symbol['values'] = current_values
            
            if not self.symbol_var.get(): 
                self.symbol_var.set(clean_symbol)

            # Update Labels
            bal_style = "success" if balance > 5000 else "info"
            self.lbl_balance.config(text=f"💰 Balance: ${balance:,.2f}", bootstyle=bal_style)
            
            pl_style = "success" if profit >= 0 else "danger"
            self.lbl_profit.config(text=f"📈 P/L: ${profit:+,.2f}", bootstyle=pl_style)
            
            self.lbl_positions.config(text=f"📦 Positions: {positions}/{self.max_pos_var.get()}")
            
            # --- MT5 Connection Status ---
            if clean_symbol == self.symbol_var.get():
                tf_display = self.tf_var.get()
                self.lbl_mt5.config(text=f"MT5: {clean_symbol} [{tf_display}]", bootstyle="success")
                self.lbl_bid.config(text=f"BID: {bid:.2f}")
                self.lbl_ask.config(text=f"ASK: {ask:.2f}")

                # Sync Status
                min_needed = 200
                count = len(candles)
                if count >= min_needed:
                    self.lbl_sync.config(text="🔄 Sync: READY", foreground="#2ecc71")
                else:
                    self.lbl_sync.config(text=f"🔄 Sync: {count}/{min_needed}", foreground="#f39c12")

                # Strategy Data
                if self.strategy and len(candles) > 50:
                    rsi, macd, signal = self.strategy.calculate_indicators(candles)
                    
                    # Determine Signal Status for UI
                    pred_score, pred_dir = self.strategy.get_prediction_score(symbol, bid, ask, candles)
                    
                    # Overwrite if we are already in a trade
                    is_in_sell = sell_count > 0
                    is_in_buy = buy_count > 0
                    if is_in_sell:
                        pred_dir = "SELL"; pred_score = 100
                    elif is_in_buy:
                        pred_dir = "BUY"; pred_score = 100
                    
                    dir_emoji = "🟢" if pred_dir == "BUY" else "🔴" if pred_dir == "SELL" else "⚪"
                    dir_style = "success" if pred_dir == "BUY" else "danger" if pred_dir == "SELL" else "secondary"
                    self.lbl_current_signal.config(text=f"{dir_emoji} {pred_dir}", bootstyle=dir_style)
                    
                    # RSI Label
                    rsi_color = "secondary"
                    if rsi < 40: rsi_color = "success" # Oversold / Dip
                    elif rsi > 60: rsi_color = "danger" # Overbought / Peak
                    self.lbl_live_rsi.config(text=f"RSI: {rsi:.1f}", bootstyle=rsi_color)
                    
                    # Trend Label
                    trend_txt = self.strategy.trend.replace("BULLISH", "UP").replace("BEARISH", "DOWN").replace("_STRONG", "++").replace("_WEAK", "+")
                    trend_color = "success" if "UP" in trend_txt else "danger" if "DOWN" in trend_txt else "secondary"
                    self.lbl_trend.config(text=f"Trend: {trend_txt}", bootstyle=trend_color)

                    # Zone Info
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
                        self.lbl_detected_zone.config(text="Zone: OFF", bootstyle="secondary")

        except Exception: pass

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
    
    def _on_tf_change(self, event=None):
        symbol = self.symbol_var.get()
        tf = self.tf_var.get()
        if symbol and tf:
            # Map simplified UI TFs to strategy strings
            tf_map = {"M1": "1min", "M5": "5min", "M15": "15min", "M30": "30min", "H1": "H1", "H4": "H4"}
            strat_tf = tf_map.get(tf, "5min")
            
            # Update Strategy directly
            if self.strategy:
                self.strategy.update_timeframe(strat_tf)
                
            logging.info(f"Requested Timeframe change: {symbol} -> {tf}")
    
    def _on_symbol_change(self, event=None):
        symbol = self.symbol_var.get()
        if symbol:
            self.mt5_connector.change_symbol(symbol)
            logging.info(f"Requested Symbol change to: {symbol}")
            # Reset UI Data placeholders
            self.lbl_live_rsi.config(text="RSI: ...", bootstyle="secondary")
            self.lbl_trend.config(text="Trend: ...", bootstyle="secondary")
            
            if self.strategy and hasattr(self.strategy, 'reset_state'):
                self.strategy.reset_state()

    def _set_combo_values(self, symbols_list):
        self.combo_symbol['values'] = symbols_list
        for s in symbols_list:
            self.known_symbols.add(s)
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
            session = getattr(self.strategy, 'active_session_name', 'Unknown')
            market_info = f" | {session} Session"
            
        if hasattr(self, 'lbl_time'): 
            self.lbl_time.config(text=f"🕒 {now}{market_info}")
        
        self.after(1000, self._update_header_time)

    def _create_widgets(self):
        main_frame = ttk.Frame(self)
        main_frame.pack(fill=BOTH, expand=True)
        
        header_frame = ttk.Frame(main_frame, relief="flat")
        header_frame.pack(fill=X, padx=10, pady=5)
        ttk.Label(header_frame, text="🛡️ Confluence Bot", font=("Segoe UI", 14, "bold"), bootstyle="inverse-primary").pack(side=LEFT)
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
        
        # --- Stats ---
        stats_frame = ttk.LabelFrame(left_frame, text="📊 Account", padding=10)
        stats_frame.pack(fill=X, pady=5)
        
        self.lbl_balance = ttk.Label(stats_frame, text="💰 Balance: $0.00", font=("Segoe UI", 14, "bold"), bootstyle="success")
        self.lbl_balance.pack(anchor=W, pady=2)
        
        self.lbl_profit = ttk.Label(stats_frame, text="📈 P/L: $0.00", font=("Segoe UI", 12), bootstyle="info")
        self.lbl_profit.pack(anchor=W, pady=2)
        
        self.lbl_positions = ttk.Label(stats_frame, text="📦 Positions: 0/1", font=("Segoe UI", 10))
        self.lbl_positions.pack(anchor=W, pady=2)

        # --- Analysis ---
        ind_frame = ttk.LabelFrame(left_frame, text="📉 Analysis", padding=10, bootstyle="info")
        ind_frame.pack(fill=X, pady=5)
        
        self.lbl_trend = ttk.Label(ind_frame, text="Trend: Waiting...", font=("Segoe UI", 11, "bold"))
        self.lbl_trend.pack(anchor=W, pady=2)
        
        self.lbl_live_rsi = ttk.Label(ind_frame, text="RSI: --", font=("Segoe UI", 10))
        self.lbl_live_rsi.pack(anchor=W, pady=2)

        self.lbl_detected_zone = ttk.Label(ind_frame, text="Zone: --", font=("Segoe UI", 10), bootstyle="warning")
        self.lbl_detected_zone.pack(anchor=W, pady=2)
        
        self.lbl_sync = ttk.Label(ind_frame, text="🔄 Sync: Waiting...", font=("Segoe UI", 9), foreground="#888")
        self.lbl_sync.pack(anchor=W, pady=2)

        signal_frame = ttk.LabelFrame(left_frame, text="🎯 Current Signal", padding=10, bootstyle="primary")
        signal_frame.pack(fill=X, pady=5)
        self.lbl_current_signal = ttk.Label(signal_frame, text="⚪ NEUTRAL", font=("Segoe UI", 11, "bold"))
        self.lbl_current_signal.pack(anchor=W)

        # --- Right Side ---
        right_frame = ttk.Frame(parent, padding=10)
        right_frame.grid(row=0, column=1, sticky="nsew")
        
        strat_frame = ttk.LabelFrame(right_frame, text="🧠 Confluence Setup", padding=10, bootstyle="primary")
        strat_frame.pack(fill=X, pady=5)
        
        ttk.Label(strat_frame, text="1. Trend (EMA 200)", font=("", 9)).pack(anchor=W)
        ttk.Label(strat_frame, text="2. Zone (Support/Res)", font=("", 9)).pack(anchor=W)
        ttk.Label(strat_frame, text="3. Trigger (Pattern+RSI)", font=("", 9)).pack(anchor=W)
        
        ttk.Checkbutton(strat_frame, text="✅ Auto Trade Enabled", variable=self.auto_trade_var, command=self._on_auto_toggle, bootstyle="success-round-toggle").pack(pady=(10, 0))

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
        self.combo_tf['values'] = ["M1", "M5", "M15", "M30", "H1", "H4"]
        self.combo_tf.pack(side=LEFT, padx=5)
        self.combo_tf.bind("<<ComboboxSelected>>", self._on_tf_change)
        
        prices_frame = ttk.Frame(ctl_box)
        prices_frame.pack(fill=X, pady=10)
        self.lbl_bid = ttk.Label(prices_frame, text="BID: 0.00", bootstyle="info", font=("Segoe UI", 12))
        self.lbl_bid.pack(side=LEFT, padx=10)
        self.lbl_ask = ttk.Label(prices_frame, text="ASK: 0.00", bootstyle="success", font=("Segoe UI", 12))
        self.lbl_ask.pack(side=RIGHT, padx=10)

        btn_grid = ttk.Frame(ctl_box)
        btn_grid.pack(fill=X, pady=5)
        ttk.Button(btn_grid, text="BUY", command=self._on_buy, bootstyle="success").pack(side=LEFT, fill=X, expand=True, padx=2)
        ttk.Button(btn_grid, text="SELL", command=self._on_sell, bootstyle="danger").pack(side=LEFT, fill=X, expand=True, padx=2)
        
        close_grid = ttk.Frame(ctl_box)
        close_grid.pack(fill=X, pady=5)
        ttk.Button(close_grid, text="Close Profit", command=self._on_close_profit, bootstyle="success-outline").pack(side=LEFT, fill=X, expand=True, padx=2)
        ttk.Button(close_grid, text="Close Loss", command=self._on_close_loss, bootstyle="danger-outline").pack(side=LEFT, fill=X, expand=True, padx=2)
        
        ttk.Button(ctl_box, text="CLOSE ALL", command=self._on_close_all, bootstyle="warning-outline").pack(fill=X, pady=5)

    def _build_settings_tab(self, parent):
        scroll_frame = ttk.Frame(parent)
        scroll_frame.pack(fill=BOTH, expand=True, padx=10, pady=10)
        
        scroll_frame.columnconfigure(0, weight=1)
        scroll_frame.columnconfigure(1, weight=1)

        # --- Col 1 ---
        col0 = ttk.Frame(scroll_frame)
        col0.grid(row=0, column=0, sticky="nsew", padx=5)
        
        trade_frame = ttk.LabelFrame(col0, text="📈 Execution", padding=15)
        trade_frame.pack(fill=X, pady=5)
        
        ttk.Label(trade_frame, text="Max Positions:").grid(row=0, column=0, sticky=W, pady=5)
        ttk.Spinbox(trade_frame, from_=1, to=10, textvariable=self.max_pos_var, width=8).grid(row=0, column=1, sticky=W, padx=10)
        
        ttk.Label(trade_frame, text="Lot Size:").grid(row=1, column=0, sticky=W, pady=5)
        ttk.Spinbox(trade_frame, from_=0.01, to=10.0, increment=0.01, textvariable=self.lot_size_var, width=8).grid(row=1, column=1, sticky=W, padx=10)
        
        ttk.Label(trade_frame, text="Cooldown (s):").grid(row=2, column=0, sticky=W, pady=5)
        ttk.Spinbox(trade_frame, from_=5, to=300, textvariable=self.cooldown_var, width=8).grid(row=2, column=1, sticky=W, padx=10)

        filter_frame = ttk.LabelFrame(col0, text="🎯 Filters", padding=15, bootstyle="info")
        filter_frame.pack(fill=X, pady=5)
        
        ttk.Checkbutton(filter_frame, text="Trend (EMA 200)", variable=self.use_trend_filter_var, bootstyle="success-round-toggle").pack(anchor=W, pady=3)
        ttk.Checkbutton(filter_frame, text="Structure (Zones)", variable=self.use_zone_filter_var, bootstyle="success-round-toggle").pack(anchor=W, pady=3)
        ttk.Checkbutton(filter_frame, text="Time Filter", variable=self.use_time_filter_var, bootstyle="success-round-toggle").pack(anchor=W, pady=3)
        
        time_row = ttk.Frame(filter_frame)
        time_row.pack(fill=X, pady=(5, 0))
        ttk.Label(time_row, text="Hour:").pack(side=LEFT)
        ttk.Spinbox(time_row, from_=0, to=23, textvariable=self.start_hour_var, width=4).pack(side=LEFT, padx=5)
        ttk.Label(time_row, text="to").pack(side=LEFT)
        ttk.Spinbox(time_row, from_=0, to=23, textvariable=self.end_hour_var, width=4).pack(side=LEFT, padx=5)

        # --- Col 2 ---
        col1 = ttk.Frame(scroll_frame)
        col1.grid(row=0, column=1, sticky="nsew", padx=5)

        profit_frame = ttk.LabelFrame(col1, text="💰 Profit & Protection", padding=15, bootstyle="warning")
        profit_frame.pack(fill=X, pady=5)
        
        ttk.Checkbutton(profit_frame, text="Auto Profit Close", variable=self.use_profit_mgmt_var, bootstyle="warning-round-toggle").pack(anchor=W, pady=3)
        
        row2 = ttk.Frame(profit_frame)
        row2.pack(fill=X, pady=3)
        ttk.Label(row2, text="Target ($):").pack(side=LEFT)
        ttk.Spinbox(row2, from_=0.05, to=100.0, increment=0.05, textvariable=self.min_profit_var, width=8).pack(side=RIGHT)
        
        row3 = ttk.Frame(profit_frame)
        row3.pack(fill=X, pady=3)
        ttk.Label(row3, text="BreakEven ($):").pack(side=LEFT)
        ttk.Spinbox(row3, from_=0.05, to=50.0, increment=0.05, textvariable=self.break_even_var, width=8).pack(side=RIGHT)

        ind_frame = ttk.LabelFrame(col1, text="📉 Indicators", padding=15, bootstyle="secondary")
        ind_frame.pack(fill=X, pady=5)
        
        ttk.Label(ind_frame, text="RSI Period:").grid(row=0, column=0, sticky=W)
        ttk.Spinbox(ind_frame, from_=2, to=50, textvariable=self.rsi_period_var, width=5).grid(row=0, column=1, sticky=W, padx=5)