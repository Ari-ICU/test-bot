import threading
import time
import logging
import queue
from datetime import datetime
import tkinter as tk
from tkinter import ttk, scrolledtext
import ttkbootstrap as tb
from ttkbootstrap.constants import *

log_queue = queue.Queue()

class QueueHandler(logging.Handler):
    def emit(self, record):
        log_queue.put(record)

class TradingBotUI(tb.Window):
    def __init__(self, news_engine, mt5_connector):
        super().__init__(themename="darkly")  
        self.title("MT5 Bot - Confluence Edition (Fixed)")
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

        # Filters
        self.use_trend_filter_var = tk.BooleanVar(value=True) 
        self.use_zone_filter_var = tk.BooleanVar(value=True) 

        # Profit Mgmt
        self.auto_close_sec_var = tk.DoubleVar(value=2.0)
        self.use_profit_mgmt_var = tk.BooleanVar(value=True)
        self.min_profit_var = tk.DoubleVar(value=0.10)
        self.break_even_var = tk.DoubleVar(value=0.50)

        # Indicators
        self.rsi_period_var = tk.IntVar(value=14)
        
        # Dashboard Inputs
        self.symbol_var = tk.StringVar()
        self.tf_var = tk.StringVar(value="M5") 
        
        # Time Filter
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
        vars_to_trace = [self.max_pos_var, self.lot_size_var, self.cooldown_var,
                         self.use_trend_filter_var, self.use_zone_filter_var,
                         self.use_profit_mgmt_var, self.min_profit_var, self.break_even_var,
                         self.rsi_period_var, self.use_time_filter_var, 
                         self.start_hour_var, self.end_hour_var]
        for var in vars_to_trace:
            var.trace_add("write", self._on_setting_changed)

    def _sync_ui_to_strategy(self):
        if self.strategy:
            try:
                self.strategy.max_positions = self.max_pos_var.get()
                self.strategy.lot_size = self.lot_size_var.get()
                self.strategy.trade_cooldown = self.cooldown_var.get()
                self.strategy.use_trend_filter = self.use_trend_filter_var.get()
                self.strategy.use_zone_filter = self.use_zone_filter_var.get()
                self.strategy.use_profit_management = self.use_profit_mgmt_var.get()
                self.strategy.min_profit_target = self.min_profit_var.get()
                self.strategy.break_even_activation = self.break_even_var.get()
                self.strategy.rsi_period = self.rsi_period_var.get()
                self.strategy.use_time_filter = self.use_time_filter_var.get()
                self.strategy.start_hour = self.start_hour_var.get()
                self.strategy.end_hour = self.end_hour_var.get()
            except: pass
        
    def _on_tick_received(self, symbol, bid, ask, balance, profit, acct_name, positions, buy_count, sell_count, avg_entry, candles):
        self.after(0, lambda: self._update_ui_data(symbol, bid, ask, balance, profit, acct_name, positions, candles))

    def _on_symbols_received(self, symbols_list):
        if not self.symbols_loaded:
            self.after(0, lambda: self._set_combo_values(symbols_list))
            self.symbols_loaded = True

    def _update_ui_data(self, symbol, bid, ask, balance, profit, acct_name, positions, candles):
        try:
            # Sync Auto-Trade Switch
            if self.strategy and self.auto_trade_var.get() != self.strategy.active:
                self.auto_trade_var.set(self.strategy.active)

            clean_symbol = str(symbol).replace('\x00', '').strip()
            
            # Update Symbol Combo
            if clean_symbol not in self.known_symbols:
                self.known_symbols.add(clean_symbol)
                current_values = list(self.combo_symbol['values'])
                if clean_symbol not in current_values:
                    current_values.append(clean_symbol)
                    self.combo_symbol['values'] = current_values
            
            if not self.symbol_var.get(): self.symbol_var.set(clean_symbol)

            # Update Labels
            self.lbl_balance.config(text=f"💰 Balance: ${balance:,.2f}")
            pl_style = "success" if profit >= 0 else "danger"
            self.lbl_profit.config(text=f"📈 P/L: ${profit:+,.2f}", bootstyle=pl_style)
            self.lbl_positions.config(text=f"📦 Positions: {positions}/{self.max_pos_var.get()}")
            
            if clean_symbol == self.symbol_var.get():
                self.lbl_mt5.config(text=f"MT5: {clean_symbol}", bootstyle="success")
                self.lbl_bid.config(text=f"BID: {bid:.2f}")
                self.lbl_ask.config(text=f"ASK: {ask:.2f}")

                count = len(candles) if candles else 0
                sync_color = "success" if count >= 200 else "warning"
                self.lbl_sync.config(text=f"🔄 Sync: {count} bars", bootstyle=sync_color)

                if self.strategy:
                    # Show Trend/Zone from Strategy
                    trend_txt = self.strategy.trend.replace("BULLISH", "UP").replace("BEARISH", "DOWN")
                    self.lbl_trend.config(text=f"Trend: {trend_txt}")
                    
                    supp = f"{self.strategy.support_zones[0]['top']:.2f}" if self.strategy.support_zones else "None"
                    res = f"{self.strategy.resistance_zones[0]['bottom']:.2f}" if self.strategy.resistance_zones else "None"
                    self.lbl_detected_zone.config(text=f"S: {supp} | R: {res}")

        except Exception: pass

    def _on_auto_toggle(self):
        if self.strategy: self.strategy.set_active(self.auto_trade_var.get())

    def _on_setting_changed(self, *args):
        self._sync_ui_to_strategy()
    
    def _on_tf_change(self, event=None):
        symbol = self.symbol_var.get()
        tf = self.tf_var.get()
        if symbol and tf and self.strategy:
            # FIX: Map UI -> Strategy
            tf_map = {"M1": "1min", "M5": "5min", "M15": "15min", "M30": "30min", "H1": "H1", "H4": "H4"}
            strat_tf = tf_map.get(tf, "5min")
            self.strategy.update_timeframe(strat_tf)
    
    def _on_symbol_change(self, event=None):
        symbol = self.symbol_var.get()
        if symbol:
            self.mt5_connector.change_symbol(symbol)
            if self.strategy: self.strategy.last_candles = None # Reset cache

    def _set_combo_values(self, symbols_list):
        self.combo_symbol['values'] = symbols_list
        for s in symbols_list: self.known_symbols.add(s)
        if symbols_list and not self.symbol_var.get(): self.symbol_var.set(symbols_list[0])

    def _update_news(self):
        if self.news_engine:
            news_str = self.news_engine.get_latest_news(10)
            sync_time = time.strftime("%H:%M:%S")
            self.news_text.delete(1.0, tk.END)
            self.news_text.insert(tk.END, f"Last Sync: {sync_time}\n" + "-"*30 + "\n" + news_str)
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
        self.lbl_time.config(text=f"🕒 {now}")
        self.after(1000, self._update_header_time)

    def _create_widgets(self):
        # HEADER
        header = ttk.Frame(self, padding=10)
        header.pack(fill=X)
        ttk.Label(header, text="🛡️ Confluence Bot", font=("", 14, "bold"), bootstyle="inverse-primary").pack(side=LEFT)
        self.lbl_mt5 = ttk.Label(header, text="MT5: Connecting...", bootstyle="warning")
        self.lbl_mt5.pack(side=LEFT, padx=20)
        self.lbl_time = ttk.Label(header, text="", font=("", 10))
        self.lbl_time.pack(side=RIGHT)

        # NOTEBOOK (TABS)
        notebook = ttk.Notebook(self, padding=5)
        notebook.pack(fill=BOTH, expand=True)

        # TAB 1: DASHBOARD
        dash_tab = ttk.Frame(notebook)
        notebook.add(dash_tab, text="📈 Dashboard")
        self._build_dashboard_tab(dash_tab)

        # TAB 2: SETTINGS
        sets_tab = ttk.Frame(notebook)
        notebook.add(sets_tab, text="⚙️ Settings")
        self._build_settings_tab(sets_tab)

        # TAB 3: LOGS
        logs_tab = ttk.Frame(notebook)
        notebook.add(logs_tab, text="📝 Logs")
        self.log_text = scrolledtext.ScrolledText(logs_tab, height=15, font=('Consolas', 9))
        self.log_text.pack(fill=BOTH, expand=True)

        # TAB 4: NEWS
        news_tab = ttk.Frame(notebook)
        notebook.add(news_tab, text="📰 News")
        self.news_text = scrolledtext.ScrolledText(news_tab, height=15, font=('Consolas', 9))
        self.news_text.pack(fill=BOTH, expand=True)

    def _build_dashboard_tab(self, parent):
        parent.columnconfigure(0, weight=1)
        parent.columnconfigure(1, weight=1)
        
        # LEFT: STATS
        left = ttk.Frame(parent, padding=10)
        left.grid(row=0, column=0, sticky="nsew")
        
        stats = ttk.LabelFrame(left, text="📊 Stats", padding=10)
        stats.pack(fill=X, pady=5)
        self.lbl_balance = ttk.Label(stats, text="💰 Balance: $0.00", font=("", 14), bootstyle="success")
        self.lbl_balance.pack(anchor=W)
        self.lbl_profit = ttk.Label(stats, text="📈 P/L: $0.00", font=("", 12))
        self.lbl_profit.pack(anchor=W)
        self.lbl_positions = ttk.Label(stats, text="📦 Positions: 0")
        self.lbl_positions.pack(anchor=W)

        ana = ttk.LabelFrame(left, text="📉 Analysis", padding=10)
        ana.pack(fill=X, pady=5)
        self.lbl_trend = ttk.Label(ana, text="Trend: --")
        self.lbl_trend.pack(anchor=W)
        self.lbl_detected_zone = ttk.Label(ana, text="Zone: --")
        self.lbl_detected_zone.pack(anchor=W)
        self.lbl_sync = ttk.Label(ana, text="Sync: Waiting...")
        self.lbl_sync.pack(anchor=W)

        # RIGHT: CONTROLS
        right = ttk.Frame(parent, padding=10)
        right.grid(row=0, column=1, sticky="nsew")
        
        ctrl = ttk.LabelFrame(right, text="⚡ Controls", padding=10)
        ctrl.pack(fill=X, pady=5)
        
        # Auto Trade
        ttk.Checkbutton(ctrl, text="✅ Auto Trade", variable=self.auto_trade_var, command=self._on_auto_toggle, bootstyle="success-round-toggle").pack(pady=5)
        
        # Selector
        sel = ttk.Frame(ctrl)
        sel.pack(fill=X, pady=5)
        self.combo_symbol = ttk.Combobox(sel, textvariable=self.symbol_var, state="readonly", width=10)
        self.combo_symbol.pack(side=LEFT, padx=2)
        self.combo_symbol.bind("<<ComboboxSelected>>", self._on_symbol_change)
        
        self.combo_tf = ttk.Combobox(sel, textvariable=self.tf_var, values=["M1", "M5", "M15", "M30", "H1", "H4"], state="readonly", width=5)
        self.combo_tf.pack(side=LEFT, padx=2)
        self.combo_tf.bind("<<ComboboxSelected>>", self._on_tf_change)

        # Prices
        prices = ttk.Frame(ctrl)
        prices.pack(fill=X, pady=5)
        self.lbl_bid = ttk.Label(prices, text="BID: 0.00", bootstyle="info")
        self.lbl_bid.pack(side=LEFT, padx=5)
        self.lbl_ask = ttk.Label(prices, text="ASK: 0.00", bootstyle="warning")
        self.lbl_ask.pack(side=RIGHT, padx=5)

        # Buttons
        btns = ttk.Frame(ctrl)
        btns.pack(fill=X, pady=5)
        ttk.Button(btns, text="BUY", command=lambda: self.mt5_connector.send_command("BUY", self.symbol_var.get(), self.lot_size_var.get()), bootstyle="success").pack(side=LEFT, fill=X, expand=True, padx=2)
        ttk.Button(btns, text="SELL", command=lambda: self.mt5_connector.send_command("SELL", self.symbol_var.get(), self.lot_size_var.get()), bootstyle="danger").pack(side=LEFT, fill=X, expand=True, padx=2)
        
        close_btns = ttk.Frame(ctrl)
        close_btns.pack(fill=X, pady=5)
        ttk.Button(close_btns, text="Close All", command=lambda: self.mt5_connector.close_position(self.symbol_var.get()), bootstyle="secondary").pack(fill=X)

    def _build_settings_tab(self, parent):
        f = ttk.Frame(parent, padding=10)
        f.pack(fill=BOTH, expand=True)
        
        # Exection
        e = ttk.LabelFrame(f, text="Execution", padding=5)
        e.pack(fill=X, pady=5)
        ttk.Label(e, text="Lots:").pack(side=LEFT)
        ttk.Spinbox(e, from_=0.01, to=10, increment=0.01, textvariable=self.lot_size_var, width=5).pack(side=LEFT, padx=5)
        ttk.Label(e, text="Max Pos:").pack(side=LEFT)
        ttk.Spinbox(e, from_=1, to=10, textvariable=self.max_pos_var, width=5).pack(side=LEFT, padx=5)
        
        # Filters
        fi = ttk.LabelFrame(f, text="Filters", padding=5)
        fi.pack(fill=X, pady=5)
        ttk.Checkbutton(fi, text="Trend Filter", variable=self.use_trend_filter_var, bootstyle="round-toggle").pack(anchor=W)
        ttk.Checkbutton(fi, text="Zone Filter", variable=self.use_zone_filter_var, bootstyle="round-toggle").pack(anchor=W)
        
        # Profit
        p = ttk.LabelFrame(f, text="Profit", padding=5)
        p.pack(fill=X, pady=5)
        ttk.Checkbutton(p, text="Auto Close Profit", variable=self.use_profit_mgmt_var, bootstyle="round-toggle").pack(anchor=W)
        r = ttk.Frame(p); r.pack(fill=X)
        ttk.Label(r, text="Target ($):").pack(side=LEFT)
        ttk.Spinbox(r, from_=1, to=1000, textvariable=self.min_profit_var, width=6).pack(side=LEFT)