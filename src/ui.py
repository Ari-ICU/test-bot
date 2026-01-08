import threading
import time
import logging
import queue
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
        self.title("MT5 Trading Bot - Pro Dashboard v7.7")
        self.geometry("1000x900") 
        self.resizable(True, True) 
        
        self.news_engine = news_engine
        self.mt5_connector = mt5_connector
        self.strategy = None
        
        # State variables
        self.last_price_update = time.time()
        self.symbols_loaded = False
        self.open_positions = []  
        self.profit_history = []  
        
        # Default Config Values
        config_max_pos = 1
        
        if self.news_engine and hasattr(self.news_engine, 'config'):
            auto_config = self.news_engine.config.get('auto_trading', {})
            config_max_pos = auto_config.get('max_positions', 1)
        
        # --- Variables ---
        self.auto_trade_var = tk.BooleanVar(value=False)
        self.max_pos_var = tk.IntVar(value=config_max_pos)
        self.max_duration_var = tk.IntVar(value=0)
        self.min_profit_var = tk.DoubleVar(value=0.50)
        
        # NEW: Auto Risk (System Calculated)
        self.use_auto_risk = tk.BooleanVar(value=True) # Default ON for safety

        # Traces
        self.max_pos_var.trace_add("write", self._on_setting_changed)
        self.use_auto_risk.trace_add("write", self._on_setting_changed)

        # Dashboard Manual Inputs
        self.symbol_var = tk.StringVar()
        self.tf_var = tk.StringVar(value="M1") 
        self.lot_size_var = tk.DoubleVar(value=0.01)
        self.sl_var = tk.DoubleVar(value=0.0)
        self.tp_var = tk.DoubleVar(value=0.0)
        
        self.mt5_connector.on_tick_received = self._on_tick_received
        self.mt5_connector.on_symbols_received = self._on_symbols_received
        
        self._setup_logging()
        self._create_widgets()
        self._check_log_queue()
        
        self.after(5000, self._update_news)  
        self._update_header_time()

    def _setup_styles(self):
        style = tb.Style()
        style.configure("TCheckbutton", font=("Segoe UI", 10))

    def _update_header_time(self):
        now = time.strftime("%Y-%m-%d %H:%M:%S")
        if hasattr(self, 'lbl_time'): self.lbl_time.config(text=now)
        self.after(1000, self._update_header_time)

    def _sync_ui_to_strategy(self):
        if self.strategy:
            try: self.strategy.max_positions = self.max_pos_var.get()
            except: pass
            
            self.strategy.set_active(self.auto_trade_var.get())
            
            # Sync Auto Risk
            try: self.strategy.use_auto_risk = self.use_auto_risk.get()
            except: pass
            
            logging.info(f"UI synced to strategy")

    def _on_tick_received(self, symbol, bid, ask, balance, profit, acct_name, positions, buy_count, sell_count, avg_entry, candles):
        self.last_price_update = time.time() 
        self.after(0, lambda: self._update_ui_data(symbol, bid, ask, balance, profit, acct_name, positions, buy_count, sell_count, avg_entry, candles))
        
        if profit != 0 and (not self.profit_history or self.profit_history[-1][1] != profit):
             self.profit_history.append((time.strftime("%H:%M:%S"), profit))
             if len(self.profit_history) > 50: self.profit_history.pop(0)

    def _on_symbols_received(self, symbols_list):
        if not self.symbols_loaded:
            self.after(0, lambda: self._set_combo_values(symbols_list))
            self.symbols_loaded = True

    def _update_ui_data(self, symbol, bid, ask, balance, profit, acct_name, positions, buy_count, sell_count, avg_entry, candles):
        try:
            clean_symbol = str(symbol).replace('\x00', '').strip()
            if not self.symbol_var.get(): self.symbol_var.set(clean_symbol)

            if clean_symbol == self.symbol_var.get():
                self.lbl_mt5.config(text=f"MT5: Connected ({clean_symbol})", bootstyle="success")
                self.lbl_bid.config(text=f"{bid:.5f}")
                self.lbl_ask.config(text=f"{ask:.5f}")

            self._update_card(self.lbl_balance, f"${balance:,.2f}", "success" if balance > 5000 else "info")
            self._update_card(self.lbl_profit, f"${profit:+,.2f}", "success" if profit >= 0 else "danger")
            self._update_card(self.lbl_positions, f"{positions}/{self.max_pos_var.get()}", "warning" if positions >= self.max_pos_var.get() else "secondary")
            
        except Exception as e:
            logging.error(f"UI Update Error: {e}")

    def _update_card(self, label, text, bootstyle):
        label.config(text=text, bootstyle=bootstyle)

    # --- ACTION HANDLERS ---
    def _on_buy(self):
        s = self.symbol_var.get()
        if s: self.mt5_connector.send_command("BUY", s, self.lot_size_var.get(), self.sl_var.get(), self.tp_var.get(), 0)

    def _on_sell(self):
        s = self.symbol_var.get()
        if s: self.mt5_connector.send_command("SELL", s, self.lot_size_var.get(), self.sl_var.get(), self.tp_var.get(), 0)

    def _on_close_all(self):
        s = self.symbol_var.get()
        if s: self.mt5_connector.close_position(s)

    def _on_auto_toggle(self):
        if self.strategy: self.strategy.set_active(self.auto_trade_var.get())

    def _on_setting_changed(self, *args):
        if self.strategy: 
            try: self.strategy.max_positions = self.max_pos_var.get()
            except: pass
            try: self.strategy.use_auto_risk = self.use_auto_risk.get()
            except: pass

    def _set_combo_values(self, symbols_list):
        self.combo_symbol['values'] = symbols_list
        if symbols_list and not self.symbol_var.get(): 
            self.symbol_var.set(symbols_list[0])

    def _update_news(self):
        if self.news_engine:
            news_str = self.news_engine.get_latest_news(10)
            self.news_text.delete(1.0, tk.END)
            self.news_text.insert(tk.END, news_str)
        self.after(30000, self._update_news)

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

    def _create_widgets(self):
        self._setup_styles()
        main_frame = ttk.Frame(self)
        main_frame.pack(fill=BOTH, expand=True)
        
        # Header
        header_frame = ttk.Frame(main_frame, relief="flat")
        header_frame.pack(fill=X, padx=10, pady=5)
        ttk.Label(header_frame, text="🛡️ MT5 Pro Bot v7.7", font=("Segoe UI", 16, "bold"), bootstyle="inverse-dark").pack(side=LEFT)
        self.lbl_mt5 = ttk.Label(header_frame, text="MT5: Connecting...", bootstyle="warning")
        self.lbl_mt5.pack(side=LEFT, padx=20)
        self.lbl_time = ttk.Label(header_frame, text="")
        self.lbl_time.pack(side=RIGHT)

        # Tabs
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
        self.log_text = scrolledtext.ScrolledText(logs_tab, height=20, font=('Consolas', 9))
        self.log_text.pack(fill=BOTH, expand=True)

        news_tab = ttk.Frame(notebook)
        notebook.add(news_tab, text="📰 News")
        self.news_text = scrolledtext.ScrolledText(news_tab, height=20, font=('Consolas', 9))
        self.news_text.pack(fill=BOTH, expand=True)

    def _build_dashboard_tab(self, parent):
        parent.grid_columnconfigure(0, weight=1)
        parent.grid_columnconfigure(1, weight=1)
        parent.grid_rowconfigure(0, weight=1)

        # Left Column: Financials
        left_frame = ttk.Frame(parent, padding=10)
        left_frame.grid(row=0, column=0, sticky="nsew")
        
        self._create_stat_card(left_frame, "💰 Balance", "$0.00", "success").pack(fill=X, pady=10)
        self.lbl_balance = left_frame.winfo_children()[-1].winfo_children()[0]
        
        self._create_stat_card(left_frame, "📉 Profit", "$0.00", "info").pack(fill=X, pady=10)
        self.lbl_profit = left_frame.winfo_children()[-1].winfo_children()[0]
        
        self._create_stat_card(left_frame, "📊 Open Positions", "0/0", "warning").pack(fill=X, pady=10)
        self.lbl_positions = left_frame.winfo_children()[-1].winfo_children()[0]

        # Right Column: Controls
        right_frame = ttk.Frame(parent, padding=10)
        right_frame.grid(row=0, column=1, sticky="nsew")
        
        ctl_box = ttk.LabelFrame(right_frame, text="Execution", padding=15)
        ctl_box.pack(fill=X, pady=5)
        
        # Symbol
        ttk.Label(ctl_box, text="Symbol:", font=("Segoe UI", 10)).pack(anchor=W)
        self.combo_symbol = ttk.Combobox(ctl_box, textvariable=self.symbol_var, state="readonly")
        self.combo_symbol.pack(fill=X, pady=(0,10))
        
        # Prices
        prices_frame = ttk.Frame(ctl_box)
        prices_frame.pack(fill=X, pady=10)
        self.lbl_bid = ttk.Label(prices_frame, text="0.000", bootstyle="info", font=("Segoe UI", 20))
        self.lbl_bid.pack(side=LEFT, padx=10)
        self.lbl_ask = ttk.Label(prices_frame, text="0.000", bootstyle="success", font=("Segoe UI", 20))
        self.lbl_ask.pack(side=RIGHT, padx=10)

        # Manual Manual Inputs
        grid_params = ttk.Frame(ctl_box)
        grid_params.pack(fill=X)
        ttk.Label(grid_params, text="Lot:").grid(row=0, column=0)
        ttk.Entry(grid_params, textvariable=self.lot_size_var, width=8).grid(row=0, column=1)
        ttk.Label(grid_params, text="SL:").grid(row=0, column=2)
        ttk.Entry(grid_params, textvariable=self.sl_var, width=8).grid(row=0, column=3)
        ttk.Label(grid_params, text="TP:").grid(row=0, column=4)
        ttk.Entry(grid_params, textvariable=self.tp_var, width=8).grid(row=0, column=5)

        # Buttons
        btn_grid = ttk.Frame(ctl_box)
        btn_grid.pack(fill=X, pady=15)
        ttk.Button(btn_grid, text="BUY", command=self._on_buy, bootstyle="success").pack(side=LEFT, fill=X, expand=True, padx=5)
        ttk.Button(btn_grid, text="SELL", command=self._on_sell, bootstyle="danger").pack(side=LEFT, fill=X, expand=True, padx=5)
        
        ttk.Button(ctl_box, text="CLOSE ALL", command=self._on_close_all, bootstyle="warning-outline").pack(fill=X, pady=10)
        
        # Auto Strategy Toggle
        auto_frame = ttk.LabelFrame(right_frame, text="Auto Strategy", padding=15)
        auto_frame.pack(fill=X, pady=20)
        ttk.Checkbutton(auto_frame, text="Enable Auto Trade", variable=self.auto_trade_var, command=self._on_auto_toggle, bootstyle="round-toggle").pack()

    def _create_stat_card(self, parent, title, value, bootstyle):
        f = ttk.LabelFrame(parent, text=title, padding=10, bootstyle=bootstyle)
        l = ttk.Label(f, text=value, font=("Segoe UI", 20, "bold"), bootstyle=bootstyle)
        l.pack()
        return f

    def _build_settings_tab(self, parent):
        ttk.Label(parent, text="Bot Settings", font=("Segoe UI", 12)).pack(pady=10)
        
        sf = ttk.Frame(parent, padding=20)
        sf.pack(fill=BOTH)
        
        ttk.Label(sf, text="Max Auto Positions:").grid(row=0, column=0, sticky=W, pady=5)
        ttk.Spinbox(sf, from_=1, to=20, textvariable=self.max_pos_var, width=10, command=self._on_setting_changed).grid(row=0, column=1, sticky=W)
        
        # --- NEW: Safe System Risk ---
        risk_frame = ttk.LabelFrame(sf, text="Small Balance Protections", padding=10)
        risk_frame.grid(row=2, column=0, columnspan=3, sticky="ew", pady=15)
        
        # No user inputs for distance, just ON/OFF
        ttk.Checkbutton(risk_frame, text="Enable Safe System SL/TP (Auto-Calc)", variable=self.use_auto_risk, command=self._on_setting_changed).pack(anchor=W)
        ttk.Label(risk_frame, text="* Uses Swing High/Low for Stops\n* Targets 1:1.5 Risk-Reward\n* Prevents account blowout", font=("Segoe UI", 8), foreground="gray").pack(anchor=W, pady=5)