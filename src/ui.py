import threading
import time
import logging
import queue
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
        self.title("MT5 Bot - MACD & RSI Strategy Edition")
        self.geometry("1100x950") 
        self.resizable(True, True) 
        
        self.news_engine = news_engine
        self.mt5_connector = mt5_connector
        self.strategy = None
        
        # State variables
        self.last_price_update = time.time()
        self.symbols_loaded = False
        self.open_positions = []  
        self.profit_history = []  
        
        # --- Config Defaults ---
        config_max_pos = 1
        
        # --- UI Variables (Linked to Strategy) ---
        self.auto_trade_var = tk.BooleanVar(value=False)
        self.max_pos_var = tk.IntVar(value=1)
        self.lot_size_var = tk.DoubleVar(value=0.01)
        
        # Strategy Specifics (MACD/RSI)
        self.rsi_period_var = tk.IntVar(value=14)
        self.rsi_buy_var = tk.IntVar(value=40)
        self.rsi_sell_var = tk.IntVar(value=60)
        
        self.macd_fast_var = tk.IntVar(value=12)
        self.macd_slow_var = tk.IntVar(value=26)
        self.macd_signal_var = tk.IntVar(value=9)
        
        self.rr_ratio_var = tk.DoubleVar(value=2.0)
        self.cooldown_var = tk.DoubleVar(value=15.0)

        # Dashboard Manual Inputs
        self.symbol_var = tk.StringVar()
        self.tf_var = tk.StringVar(value="M1") 
        self.manual_sl_var = tk.DoubleVar(value=0.0)
        self.manual_tp_var = tk.DoubleVar(value=0.0)
        
        # Add Traces to auto-update strategy when UI changes
        self._bind_traces()

        # Connect Events
        self.mt5_connector.on_tick_received = self._on_tick_received
        self.mt5_connector.on_symbols_received = self._on_symbols_received
        
        self._setup_logging()
        self._create_widgets()
        self._check_log_queue()
        
        # Initial Logic Text Update
        self._update_strategy_logic_text()
        
        self.after(5000, self._update_news)  
        self._update_header_time()

    def _bind_traces(self):
        """Syncs UI changes to Strategy instantly"""
        for var in [self.max_pos_var, self.rsi_period_var, self.rsi_buy_var, 
                    self.rsi_sell_var, self.macd_fast_var, self.macd_slow_var, 
                    self.macd_signal_var, self.rr_ratio_var, self.cooldown_var]:
            var.trace_add("write", self._on_setting_changed)

    def _sync_ui_to_strategy(self):
        """Pushes all UI values to the Strategy object."""
        if self.strategy:
            try:
                self.strategy.set_active(self.auto_trade_var.get())
                self.strategy.max_positions = self.max_pos_var.get()
                self.strategy.lot_size = self.lot_size_var.get()
                
                # RSI Settings
                self.strategy.rsi_period = self.rsi_period_var.get()
                self.strategy.rsi_buy_threshold = self.rsi_buy_var.get()
                self.strategy.rsi_sell_threshold = self.rsi_sell_var.get()
                
                # MACD Settings
                self.strategy.macd_fast = self.macd_fast_var.get()
                self.strategy.macd_slow = self.macd_slow_var.get()
                self.strategy.macd_signal = self.macd_signal_var.get()
                
                # Risk Settings
                self.strategy.risk_reward_ratio = self.rr_ratio_var.get()
                self.strategy.trade_cooldown = self.cooldown_var.get()
                
                logging.info("Strategy updated with UI settings.")
            except Exception as e:
                logging.error(f"Sync Error: {e}")

    def _update_strategy_logic_text(self):
        """Updates the dashboard text explaining WHEN the bot will buy/sell."""
        if not hasattr(self, 'lbl_buy_logic'): return
        
        b_rsi = self.rsi_buy_var.get()
        s_rsi = self.rsi_sell_var.get()
        
        self.lbl_buy_logic.config(text=f"🟢 BUY WHEN:  RSI < {b_rsi}  AND  MACD > Signal")
        self.lbl_sell_logic.config(text=f"🔴 SELL WHEN:  RSI > {s_rsi}  AND  MACD < Signal")

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
                self.lbl_mt5.config(text=f"MT5: Connected ({clean_symbol})", bootstyle="success")
                self.lbl_bid.config(text=f"{bid:.5f}")
                self.lbl_ask.config(text=f"{ask:.5f}")

            self._update_card(self.lbl_balance, f"${balance:,.2f}", "success" if balance > 5000 else "info")
            self._update_card(self.lbl_profit, f"${profit:+,.2f}", "success" if profit >= 0 else "danger")
            self._update_card(self.lbl_positions, f"{positions}/{self.max_pos_var.get()}", "warning" if positions >= self.max_pos_var.get() else "secondary")
            
            # --- LIVE STRATEGY FEEDBACK ---
            if self.strategy and len(candles) > 50:
                rsi, macd, signal = self.strategy.calculate_indicators(candles)
                
                # Update RSI Label
                rsi_color = "success" if rsi < self.rsi_buy_var.get() else "danger" if rsi > self.rsi_sell_var.get() else "secondary"
                self.lbl_live_rsi.config(text=f"RSI (14): {rsi:.2f}", bootstyle=rsi_color)
                
                # Update MACD Label
                macd_color = "success" if macd > signal else "danger"
                self.lbl_live_macd.config(text=f"MACD: {macd:.5f} | Sig: {signal:.5f}", bootstyle=macd_color)

        except Exception as e:
            pass

    def _update_card(self, label, text, bootstyle):
        label.config(text=text, bootstyle=bootstyle)

    # --- ACTION HANDLERS ---
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
    
    def _update_header_time(self):
        now = time.strftime("%Y-%m-%d %H:%M:%S")
        if hasattr(self, 'lbl_time'): self.lbl_time.config(text=now)
        self.after(1000, self._update_header_time)

    # --- WIDGET CREATION ---
    def _create_widgets(self):
        main_frame = ttk.Frame(self)
        main_frame.pack(fill=BOTH, expand=True)
        
        # Header
        header_frame = ttk.Frame(main_frame, relief="flat")
        header_frame.pack(fill=X, padx=10, pady=5)
        ttk.Label(header_frame, text="🛡️ MACD+RSI Auto Bot", font=("Segoe UI", 16, "bold"), bootstyle="inverse-primary").pack(side=LEFT)
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
        notebook.add(settings_tab, text="⚙️ Strategy Settings")
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
        
        self._create_stat_card(left_frame, "📊 Positions", "0/0", "warning").pack(fill=X, pady=10)
        self.lbl_positions = left_frame.winfo_children()[-1].winfo_children()[0]

        # Right Column: Controls & Indicators
        right_frame = ttk.Frame(parent, padding=10)
        right_frame.grid(row=0, column=1, sticky="nsew")
        
        # --- Live Indicators Panel ---
        ind_frame = ttk.LabelFrame(right_frame, text="Live Indicators", padding=15, bootstyle="info")
        ind_frame.pack(fill=X, pady=(0, 10))
        
        self.lbl_live_rsi = ttk.Label(ind_frame, text="RSI (14): Waiting...", font=("Segoe UI", 14, "bold"), bootstyle="secondary")
        self.lbl_live_rsi.pack(fill=X, pady=5)
        
        self.lbl_live_macd = ttk.Label(ind_frame, text="MACD: Waiting...", font=("Segoe UI", 12), bootstyle="secondary")
        self.lbl_live_macd.pack(fill=X, pady=5)

        # --- Active Strategy Logic Display (NEW) ---
        logic_frame = ttk.LabelFrame(right_frame, text="Active Strategy Logic", padding=10)
        logic_frame.pack(fill=X, pady=10)
        
        self.lbl_buy_logic = ttk.Label(logic_frame, text="", font=("Segoe UI", 10, "bold"), foreground="#2ecc71") # Green
        self.lbl_buy_logic.pack(anchor=W, pady=2)
        
        self.lbl_sell_logic = ttk.Label(logic_frame, text="", font=("Segoe UI", 10, "bold"), foreground="#e74c3c") # Red
        self.lbl_sell_logic.pack(anchor=W, pady=2)

        # --- Manual Execution ---
        ctl_box = ttk.LabelFrame(right_frame, text="Manual Execution", padding=15)
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

        # Buttons
        btn_grid = ttk.Frame(ctl_box)
        btn_grid.pack(fill=X, pady=15)
        ttk.Button(btn_grid, text="BUY NOW", command=self._on_buy, bootstyle="success").pack(side=LEFT, fill=X, expand=True, padx=5)
        ttk.Button(btn_grid, text="SELL NOW", command=self._on_sell, bootstyle="danger").pack(side=LEFT, fill=X, expand=True, padx=5)
        
        ttk.Button(ctl_box, text="CLOSE ALL POSITIONS", command=self._on_close_all, bootstyle="warning-outline").pack(fill=X, pady=10)
        
        # Auto Strategy Toggle
        auto_frame = ttk.LabelFrame(right_frame, text="Auto Strategy", padding=15)
        auto_frame.pack(fill=X, pady=20)
        ttk.Checkbutton(auto_frame, text="Enable Auto Trade (MACD+RSI)", variable=self.auto_trade_var, command=self._on_auto_toggle, bootstyle="round-toggle").pack()

    def _create_stat_card(self, parent, title, value, bootstyle):
        f = ttk.LabelFrame(parent, text=title, padding=10, bootstyle=bootstyle)
        l = ttk.Label(f, text=value, font=("Segoe UI", 20, "bold"), bootstyle=bootstyle)
        l.pack()
        return f

    def _build_settings_tab(self, parent):
        scroll = ttk.Frame(parent)
        scroll.pack(fill=BOTH, expand=True)
        
        # -- General --
        gen_frame = ttk.LabelFrame(scroll, text="General Settings", padding=15)
        gen_frame.pack(fill=X, padx=10, pady=10)
        
        self._add_setting(gen_frame, "Max Open Positions:", self.max_pos_var, 1, 10, 0)
        self._add_setting(gen_frame, "Lot Size:", self.lot_size_var, 0.01, 10.0, 1)
        self._add_setting(gen_frame, "Trade Cooldown (sec):", self.cooldown_var, 5.0, 300.0, 2)

        # -- RSI Settings --
        rsi_frame = ttk.LabelFrame(scroll, text="RSI Settings", padding=15, bootstyle="info")
        rsi_frame.pack(fill=X, padx=10, pady=10)
        
        self._add_setting(rsi_frame, "RSI Period:", self.rsi_period_var, 2, 50, 0)
        self._add_setting(rsi_frame, "Oversold (Buy if <):", self.rsi_buy_var, 10, 50, 1)
        self._add_setting(rsi_frame, "Overbought (Sell if >):", self.rsi_sell_var, 50, 90, 2)

        # -- MACD Settings --
        macd_frame = ttk.LabelFrame(scroll, text="MACD Settings", padding=15, bootstyle="primary")
        macd_frame.pack(fill=X, padx=10, pady=10)
        
        self._add_setting(macd_frame, "Fast EMA:", self.macd_fast_var, 5, 50, 0)
        self._add_setting(macd_frame, "Slow EMA:", self.macd_slow_var, 10, 100, 1)
        self._add_setting(macd_frame, "Signal SMA:", self.macd_signal_var, 2, 50, 2)

        # -- Risk Management --
        risk_frame = ttk.LabelFrame(scroll, text="Risk Management", padding=15, bootstyle="success")
        risk_frame.pack(fill=X, padx=10, pady=10)
        
        self._add_setting(risk_frame, "Risk/Reward Ratio (1:x):", self.rr_ratio_var, 1.0, 10.0, 0)
        ttk.Label(risk_frame, text="* 2.0 means if Risk $10, Target is $20", font=("Segoe UI", 8), foreground="gray").grid(row=1, column=0, columnspan=3, sticky=W)

    def _add_setting(self, parent, label_text, variable, min_val, max_val, row_idx):
        ttk.Label(parent, text=label_text).grid(row=row_idx, column=0, sticky=W, padx=5, pady=5)
        if isinstance(variable, tk.IntVar) or isinstance(variable, tk.DoubleVar):
            step = 1 if isinstance(variable, tk.IntVar) else 0.1
            ttk.Spinbox(parent, from_=min_val, to=max_val, increment=step, textvariable=variable, width=10).grid(row=row_idx, column=1, sticky=W, padx=5)