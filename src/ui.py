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
        self.title("MT5 Trading Bot Command Center v3.6 (Entry Point)") 
        self.geometry("1100x740") 
        
        self.news_engine = news_engine
        self.mt5_connector = mt5_connector
        self.strategy = None
        
        self.mt5_connector.on_tick_received = self._on_tick_received
        self.mt5_connector.on_symbols_received = self._on_symbols_received
        
        # --- UI State Variables ---
        self.auto_trade_var = tk.BooleanVar(value=False)
        self.max_pos_var = tk.IntVar(value=1)
        self.scalp_var = tk.BooleanVar(value=False)
        self.scalp_tp_var = tk.DoubleVar(value=0.50)
        self.auto_profit_var = tk.BooleanVar(value=True)
        self.profit_sec_var = tk.IntVar(value=1)
        
        # Strategy Filters
        self.fvg_var = tk.BooleanVar(value=True)
        self.ob_var = tk.BooleanVar(value=True)
        self.zone_conf_var = tk.BooleanVar(value=True)
        self.zone_var = tk.IntVar(value=20)
        
        # Trend Filter Toggle
        self.trend_var = tk.BooleanVar(value=True) 
        
        self.auto_range_var = tk.BooleanVar(value=True)
        self.tf_var = tk.StringVar(value="M1")
        self.symbol_var = tk.StringVar()
        self.market_prot_var = tk.BooleanVar(value=True)

        self._setup_logging()
        self._create_widgets()
        self._check_log_queue()
        
        self.last_price_update = 0
        self.symbols_loaded = False
        self.current_bid = 0.0
        self.current_ask = 0.0

    # --- UPDATED: Accepts avg_entry ---
    def _on_tick_received(self, symbol, bid, ask, balance, profit, acct_name, positions, buy_count, sell_count, avg_entry, candles):
        self.after(0, lambda: self._update_ui_data(symbol, bid, ask, balance, profit, acct_name, positions, buy_count, sell_count, avg_entry, candles))
        self.after(0, lambda: self._update_status())

    def _on_symbols_received(self, symbols_list):
        if not self.symbols_loaded or getattr(self, 'request_symbol_refresh', False):
            self.after(0, lambda: self._set_combo_values(symbols_list))
            self.request_symbol_refresh = False

    def _update_status(self):
        try: self.lbl_mt5.config(text="MT5: Connected", bootstyle="success")
        except: pass

    # --- UPDATED: Uses avg_entry ---
    def _update_ui_data(self, symbol, bid, ask, balance, profit, acct_name, positions, buy_count, sell_count, avg_entry, candles):
        try:
            clean_incoming = str(symbol).replace('\x00', '').strip()
            clean_selected = str(self.combo_symbol.get()).replace('\x00', '').strip()

            if not clean_selected:
                self.symbol_var.set(clean_incoming)
                clean_selected = clean_incoming

            self.lbl_balance.config(text=f"${balance:,.2f}")
            self.lbl_account.config(text=acct_name)
            self.lbl_positions.config(text=str(positions), bootstyle="warning" if positions > 0 else "secondary")
            self.lbl_buy_count.config(text=str(buy_count), bootstyle="success" if buy_count > 0 else "secondary")
            self.lbl_sell_count.config(text=str(sell_count), bootstyle="danger" if sell_count > 0 else "secondary")
            
            self.lbl_profit.config(text=f"${profit:+,.2f}")
            if profit > 0: self.lbl_profit.config(bootstyle="success")
            elif profit < 0: self.lbl_profit.config(bootstyle="danger")
            else: self.lbl_profit.config(bootstyle="secondary")

            if clean_incoming == clean_selected:
                self.lbl_symbol_display.config(text=clean_incoming)
                self.lbl_bid.config(text=f"{bid:.3f}")
                self.lbl_ask.config(text=f"{ask:.3f}")
                
                # --- NEW: Update Avg Entry Label ---
                if avg_entry > 0:
                    self.lbl_avg_entry.config(text=f"AVG ENTRY: {avg_entry:.3f}", bootstyle="info")
                else:
                    self.lbl_avg_entry.config(text="AVG ENTRY: ---", bootstyle="secondary")
                # -----------------------------------

                self.current_bid = bid
                self.current_ask = ask
                
                if self.strategy and self.auto_range_var.get():
                     s_min = self.strategy.min_price
                     s_max = self.strategy.max_price
                     if s_min > 0 and s_max > 0:
                         try:
                             cur_min = float(self.entry_min_price.get())
                             cur_max = float(self.entry_max_price.get())
                             if abs(cur_min - s_min) > 0.01:
                                 self.entry_min_price.delete(0, tk.END)
                                 self.entry_min_price.insert(0, f"{s_min:.2f}")
                             if abs(cur_max - s_max) > 0.01:
                                 self.entry_max_price.delete(0, tk.END)
                                 self.entry_max_price.insert(0, f"{s_max:.2f}")
                         except: pass

                try:
                    mn = float(self.entry_min_price.get())
                    mx = float(self.entry_max_price.get())
                    zp = int(self.zone_var.get())
                    span = mx - mn
                    buy_th = mn + (span * zp / 100.0)
                    sell_th = mx - (span * zp / 100.0)
                    self.lbl_range_low.config(text=f"< {buy_th:.2f}", bootstyle="success")
                    self.lbl_range_high.config(text=f"> {sell_th:.2f}", bootstyle="danger")
                except:
                    self.lbl_range_low.config(text="---")
                    self.lbl_range_high.config(text="---")

                if self.strategy:
                    patterns = self.strategy.analyze_patterns(candles)
                    p_text = []
                    if patterns.get('bullish_fvg'): p_text.append("BULL FVG")
                    if patterns.get('bearish_fvg'): p_text.append("BEAR FVG")
                    self.lbl_patterns.config(text=" | ".join(p_text) if p_text else "Scanning...", bootstyle="warning" if p_text else "secondary")

                    fvg = patterns.get('fvg_zone')
                    self.lbl_fvg_price.config(text=f"{fvg[0]:.4f}-{fvg[1]:.4f}" if fvg else "---", bootstyle="warning" if fvg else "secondary")
                    ob = patterns.get('ob_zone')
                    self.lbl_ob_price.config(text=f"{ob[0]:.4f}-{ob[1]:.4f}" if ob else "---", bootstyle="info" if ob else "secondary")

                    c3h = patterns.get('c3_high', 0)
                    c1l = patterns.get('c1_low', 0)
                    self.lbl_debug_vals.config(text=f"C3_H: {c3h:.2f} | C1_L: {c1l:.2f}")
                    if c3h < c1l: self.lbl_debug_vals.config(bootstyle="success") 
                    elif c3h > c1l: self.lbl_debug_vals.config(bootstyle="danger") 

        except Exception as e:
            logging.error(f"UI Update Error: {e}")

    def _setup_logging(self):
        queue_handler = QueueHandler()
        queue_handler.setFormatter(logging.Formatter('%(asctime)s: %(message)s', datefmt='%H:%M:%S'))
        logging.getLogger().addHandler(queue_handler)

    def _create_widgets(self):
        self.tabs = ttk.Notebook(self)
        self.tabs.pack(fill=BOTH, expand=YES, padx=5, pady=5)
        self.tab_dashboard = ttk.Frame(self.tabs)
        self.tabs.add(self.tab_dashboard, text="Dashboard")
        self._build_dashboard(self.tab_dashboard)
        self.tab_logs = ttk.Frame(self.tabs)
        self.tabs.add(self.tab_logs, text="Logs & News")
        self._build_log_view(self.tab_logs)

    def _build_dashboard(self, parent):
        config_container = tb.Frame(parent)
        config_container.pack(fill=X, padx=5, pady=2) 

        # === PANEL 1: MODES ===
        col_modes = tb.LabelFrame(config_container, text="1. Operation Mode")
        col_modes.pack(side=LEFT, fill=BOTH, padx=2, expand=True)
        pad_modes = tb.Frame(col_modes)
        pad_modes.pack(fill=BOTH, expand=True, padx=5, pady=5)
        
        self.lbl_mt5 = tb.Label(pad_modes, text="MT5: Waiting...", bootstyle="warning", font=("Helvetica", 9, "bold"))
        self.lbl_mt5.pack(anchor="w", pady=(0, 5))

        f_auto = tb.Frame(pad_modes)
        f_auto.pack(fill=X, pady=2)
        self.chk_auto = tb.Checkbutton(f_auto, text="Standard Auto", variable=self.auto_trade_var, bootstyle="success-round-toggle", command=self._on_auto_toggle)
        self.chk_auto.pack(side=LEFT)
        
        f_auto_sets = tb.Frame(f_auto)
        f_auto_sets.pack(side=RIGHT)
        tb.Label(f_auto_sets, text="Max:", font=("Helvetica", 8)).pack(side=LEFT, padx=(5, 2))
        self.spin_max_pos = tb.Spinbox(f_auto_sets, from_=1, to=50, textvariable=self.max_pos_var, width=3, font=("Helvetica", 8))
        self.spin_max_pos.pack(side=LEFT)
        self.max_pos_var.trace("w", self._on_max_pos_changed)

        tb.Separator(pad_modes, orient="horizontal").pack(fill=X, pady=5)

        f_scalp = tb.Frame(pad_modes)
        f_scalp.pack(fill=X, pady=2)
        self.chk_scalp = tb.Checkbutton(f_scalp, text="Scalp Mode", variable=self.scalp_var, bootstyle="danger-round-toggle", command=self._on_scalp_toggle)
        self.chk_scalp.pack(side=LEFT)
        
        f_scalp_sets = tb.Frame(f_scalp)
        f_scalp_sets.pack(side=RIGHT)
        tb.Label(f_scalp_sets, text="TP($):", font=("Helvetica", 8)).pack(side=LEFT, padx=(5, 2))
        tb.Spinbox(f_scalp_sets, from_=0.1, to=100.0, increment=0.1, textvariable=self.scalp_tp_var, width=4, font=("Helvetica", 8)).pack(side=LEFT)
        self.scalp_tp_var.trace("w", self._on_scalp_param_changed)

        # === PANEL 2: BOUNDARIES ===
        col_bounds = tb.LabelFrame(config_container, text="2. Price Boundaries")
        col_bounds.pack(side=LEFT, fill=BOTH, padx=2, expand=True)
        pad_bounds = tb.Frame(col_bounds)
        pad_bounds.pack(fill=BOTH, expand=True, padx=5, pady=5)
        
        tb.Checkbutton(pad_bounds, text="Auto Range", variable=self.auto_range_var, bootstyle="info-round-toggle", command=self._on_auto_range_toggle).pack(anchor="w", pady=(0, 5))

        f_grid = tb.Frame(pad_bounds)
        f_grid.pack(fill=X, expand=True)
        tb.Label(f_grid, text="Min:", font=("Helvetica", 9)).grid(row=0, column=0, sticky="e", padx=5, pady=5)
        self.entry_min_price = tb.Entry(f_grid, width=10, font=("Helvetica", 9))
        self.entry_min_price.insert(0, "0")
        self.entry_min_price.grid(row=0, column=1, sticky="w", pady=5)
        
        tb.Label(f_grid, text="Max:", font=("Helvetica", 9)).grid(row=1, column=0, sticky="e", padx=5, pady=5)
        self.entry_max_price = tb.Entry(f_grid, width=10, font=("Helvetica", 9))
        self.entry_max_price.insert(0, "0")
        self.entry_max_price.grid(row=1, column=1, sticky="w", pady=5)

        tb.Label(f_grid, text="Zone %:", font=("Helvetica", 9)).grid(row=2, column=0, sticky="e", padx=5, pady=5)
        self.spin_zone = tb.Spinbox(f_grid, from_=1, to=50, textvariable=self.zone_var, width=5, font=("Helvetica", 9))
        self.spin_zone.grid(row=2, column=1, sticky="w", pady=5)
        self.zone_var.trace("w", self._on_zone_changed)

        self.entry_min_price.bind("<KeyRelease>", self._on_range_changed)
        self.entry_max_price.bind("<KeyRelease>", self._on_range_changed)

        # === PANEL 3: LOGIC ===
        col_strat = tb.LabelFrame(config_container, text="3. Strategy Logic")
        col_strat.pack(side=LEFT, fill=BOTH, padx=2, expand=True)
        pad_strat = tb.Frame(col_strat)
        pad_strat.pack(fill=BOTH, expand=True, padx=5, pady=5)

        f_pulse = tb.Frame(pad_strat)
        f_pulse.pack(fill=X, pady=2)
        self.chk_profit = tb.Checkbutton(f_pulse, text="Pulse Close", variable=self.auto_profit_var, bootstyle="info-square-toggle", command=self._on_profit_loop_toggle)
        self.chk_profit.pack(side=LEFT)
        
        f_pulse_sets = tb.Frame(f_pulse)
        f_pulse_sets.pack(side=RIGHT)
        tb.Label(f_pulse_sets, text="Int(s):", font=("Helvetica", 8)).pack(side=LEFT, padx=(5, 2))
        self.spin_profit_sec = tb.Spinbox(f_pulse_sets, from_=1, to=3600, textvariable=self.profit_sec_var, width=4, font=("Helvetica", 8))
        self.spin_profit_sec.pack(side=LEFT)
        self.profit_sec_var.trace("w", self._on_profit_sec_changed)

        tb.Separator(pad_strat, orient="horizontal").pack(fill=X, pady=8)
        
        f_filters = tb.Frame(pad_strat)
        f_filters.pack(fill=X)
        
        tb.Checkbutton(f_filters, text="Trend", variable=self.trend_var, bootstyle="danger", command=self._on_strat_filter_changed).pack(side=LEFT, padx=2)
        tb.Checkbutton(f_filters, text="FVG", variable=self.fvg_var, bootstyle="warning", command=self._on_strat_filter_changed).pack(side=LEFT, padx=2)
        tb.Checkbutton(f_filters, text="OB", variable=self.ob_var, bootstyle="warning", command=self._on_strat_filter_changed).pack(side=LEFT, padx=2)
        tb.Checkbutton(f_filters, text="Zone", variable=self.zone_conf_var, bootstyle="primary", command=self._on_strat_filter_changed).pack(side=LEFT, padx=2)

        # 2. Account
        acct_frame = tb.LabelFrame(parent, text="Account & Positions")
        acct_frame.pack(fill=X, padx=5, pady=2)
        
        self._build_acct_label(acct_frame, "BALANCE", "lbl_balance", "info")
        self._build_acct_label(acct_frame, "P/L", "lbl_profit", "secondary")
        self._build_acct_label(acct_frame, "POS", "lbl_positions", "secondary")
        self._build_acct_label(acct_frame, "BUY", "lbl_buy_count", "secondary")
        self._build_acct_label(acct_frame, "SELL", "lbl_sell_count", "secondary")
        
        f4 = tb.Frame(acct_frame)
        f4.pack(side=LEFT, padx=15, pady=5)
        tb.Label(f4, text="ACCOUNT", font=("Helvetica", 7)).pack()
        self.lbl_account = tb.Label(f4, text="---", font=("Helvetica", 10, "bold"), bootstyle="primary")
        self.lbl_account.pack()

        # 3. Live Market Data
        price_frame = tb.LabelFrame(parent, text="Live Market Data")
        price_frame.pack(fill=X, padx=5, pady=5)
        
        self.lbl_symbol_display = tb.Label(price_frame, text="---", font=("Helvetica", 16, "bold"))
        self.lbl_symbol_display.pack(pady=(5, 2))
        
        split_container = tb.Frame(price_frame)
        split_container.pack(fill=X, padx=5, pady=2, expand=True)

        left_col = tb.Frame(split_container)
        left_col.pack(side=LEFT, fill=Y, expand=True) 
        
        grid_frame = tb.Frame(left_col)
        grid_frame.pack(pady=2)
        tb.Label(grid_frame, text="BID", font=("Helvetica", 9, "bold"), bootstyle="success").grid(row=0, column=0, padx=15)
        tb.Label(grid_frame, text="ASK", font=("Helvetica", 9, "bold"), bootstyle="danger").grid(row=0, column=1, padx=15)
        
        self.lbl_bid = tb.Label(grid_frame, text="0.000", font=("Helvetica", 22, "bold"), bootstyle="success")
        self.lbl_bid.grid(row=1, column=0, padx=15)
        self.lbl_ask = tb.Label(grid_frame, text="0.000", font=("Helvetica", 22, "bold"), bootstyle="danger")
        self.lbl_ask.grid(row=1, column=1, padx=15)
        
        # --- NEW: AVG ENTRY LABEL ---
        self.lbl_avg_entry = tb.Label(grid_frame, text="AVG ENTRY: ---", font=("Helvetica", 10, "bold"), bootstyle="secondary")
        self.lbl_avg_entry.grid(row=2, column=0, columnspan=2, pady=(5,0))
        # ----------------------------

        zone_frame = tb.Frame(left_col)
        zone_frame.pack(pady=5)
        
        f_buy = tb.Frame(zone_frame)
        f_buy.pack(fill=X, pady=1)
        tb.Label(f_buy, text="BUY ZONE (<):", font=("Helvetica", 8, "bold"), bootstyle="success").pack(side=LEFT)
        self.lbl_range_low = tb.Label(f_buy, text="---", font=("Consolas", 10, "bold"), bootstyle="success")
        self.lbl_range_low.pack(side=RIGHT, padx=5)

        f_sell = tb.Frame(zone_frame)
        f_sell.pack(fill=X, pady=1)
        tb.Label(f_sell, text="SELL ZONE (>):", font=("Helvetica", 8, "bold"), bootstyle="danger").pack(side=LEFT)
        self.lbl_range_high = tb.Label(f_sell, text="---", font=("Consolas", 10, "bold"), bootstyle="danger")
        self.lbl_range_high.pack(side=RIGHT, padx=5)

        right_col = tb.Frame(split_container)
        right_col.pack(side=RIGHT, fill=BOTH, expand=True, padx=(15, 0))
        
        tb.Label(right_col, text="MARKET STRUCTURE", font=("Helvetica", 9, "bold"), bootstyle="secondary").pack(anchor="w", pady=(0, 2))

        r1 = tb.Frame(right_col)
        r1.pack(fill=X, pady=1)
        tb.Label(r1, text="STATUS:", font=("Helvetica", 8, "bold"), width=10).pack(side=LEFT)
        self.lbl_patterns = tb.Label(r1, text="Scanning...", font=("Helvetica", 8), bootstyle="secondary")
        self.lbl_patterns.pack(side=LEFT)

        r2 = tb.Frame(right_col)
        r2.pack(fill=X, pady=1)
        tb.Label(r2, text="FVG ZONE:", font=("Helvetica", 8), width=10).pack(side=LEFT)
        self.lbl_fvg_price = tb.Label(r2, text="---", font=("Consolas", 8), bootstyle="warning")
        self.lbl_fvg_price.pack(side=LEFT)

        r3 = tb.Frame(right_col)
        r3.pack(fill=X, pady=1)
        tb.Label(r3, text="OB ZONE:", font=("Helvetica", 8), width=10).pack(side=LEFT)
        self.lbl_ob_price = tb.Label(r3, text="---", font=("Consolas", 8), bootstyle="info")
        self.lbl_ob_price.pack(side=LEFT)

        tb.Separator(right_col, orient="horizontal").pack(fill=X, pady=5)
        r4 = tb.Frame(right_col)
        r4.pack(fill=X, pady=1)
        tb.Label(r4, text="GAP DEBUG:", font=("Helvetica", 7, "bold"), bootstyle="secondary").pack(anchor="w")
        self.lbl_debug_vals = tb.Label(r4, text="C3: --- | C1: ---", font=("Consolas", 8), bootstyle="secondary")
        self.lbl_debug_vals.pack(anchor="w")

        # 4. Order Execution
        trade_frame = tb.LabelFrame(parent, text="Order Execution")
        trade_frame.pack(fill=X, padx=5, pady=5)
        
        row_context = tb.Frame(trade_frame)
        row_context.pack(fill=X, padx=5, pady=2)
        
        tb.Label(row_context, text="Sym:").pack(side=LEFT)
        self.combo_symbol = tb.Combobox(row_context, textvariable=self.symbol_var, width=10)
        self.combo_symbol.pack(side=LEFT, padx=5)
        self.combo_symbol.bind("<<ComboboxSelected>>", self._on_symbol_changed)
        
        tb.Label(row_context, text="TF:").pack(side=LEFT, padx=(5,2))
        self.combo_tf = tb.Combobox(row_context, textvariable=self.tf_var, width=5)
        self.combo_tf['values'] = ("M1", "M5", "M15", "M30", "H1", "H4", "D1")
        self.combo_tf.pack(side=LEFT, padx=2)
        self.combo_tf.bind("<<ComboboxSelected>>", self._on_timeframe_changed)
        
        tb.Button(row_context, text="⟳", bootstyle="outline-secondary", command=self._refresh_symbols, width=2).pack(side=LEFT, padx=5)
        
        tb.Label(row_context, text="Vol:").pack(side=LEFT, padx=(10, 5))
        self.entry_volume = tb.Entry(row_context, width=6)
        self.entry_volume.insert(0, "0.01")
        self.entry_volume.bind("<KeyRelease>", lambda e: [self._on_volume_changed(e), self._update_estimates(e)])
        self.entry_volume.pack(side=LEFT)
        
        lot_frame = tb.Frame(trade_frame)
        lot_frame.pack(fill=X, padx=5, pady=1)
        for lot in [0.01, 0.05, 0.1, 0.5, 1.0]:
            tb.Button(lot_frame, text=f"{lot}", bootstyle="link-secondary", command=lambda l=lot: self._set_volume(l), width=4).pack(side=LEFT, padx=1)
        
        row_prot = tb.Frame(trade_frame)
        row_prot.pack(fill=X, padx=5, pady=2)
        self.entry_sl, self.lbl_sl_est = self._build_prot_group(row_prot, "SL:")
        self.entry_tp, self.lbl_tp_est = self._build_prot_group(row_prot, "TP:")
        
        exec_notebook = ttk.Notebook(trade_frame, bootstyle="secondary")
        exec_notebook.pack(fill=X, padx=2, pady=2, expand=True)
        tab_market = tb.Frame(exec_notebook)
        exec_notebook.add(tab_market, text="Instant")
        tb.Checkbutton(tab_market, text="Use SL/TP", variable=self.market_prot_var, bootstyle="info-square-toggle").pack(pady=2)
        tb.Button(tab_market, text="BUY", bootstyle="success", width=12, command=lambda: self._send_trade("BUY")).pack(side=LEFT, padx=10, pady=2, expand=True)
        tb.Button(tab_market, text="SELL", bootstyle="danger", width=12, command=lambda: self._send_trade("SELL")).pack(side=RIGHT, padx=10, pady=2, expand=True)
        
        tab_pending = tb.Frame(exec_notebook)
        exec_notebook.add(tab_pending, text="Pending")
        row_limit = tb.Frame(tab_pending)
        row_limit.pack(fill=X, pady=5)
        tb.Label(row_limit, text="Price:").pack(side=LEFT, padx=(10, 5))
        self.entry_price = tb.Entry(row_limit, width=10)
        self.entry_price.insert(0, "0")
        self.entry_price.pack(side=LEFT, padx=5)
        tb.Button(row_limit, text="📍", bootstyle="link", width=3, command=self._fill_limit_price).pack(side=LEFT)
        row_btns = tb.Frame(tab_pending)
        row_btns.pack(fill=X)
        tb.Button(row_btns, text="BUY LIMIT", bootstyle="success-outline", width=12, command=lambda: self._send_trade("BUY_LIMIT")).pack(side=LEFT, padx=10, expand=True)
        tb.Button(row_btns, text="SELL LIMIT", bootstyle="danger-outline", width=12, command=lambda: self._send_trade("SELL_LIMIT")).pack(side=RIGHT, padx=10, expand=True)
        
        tab_manage = tb.Frame(exec_notebook)
        exec_notebook.add(tab_manage, text="Close")
        tb.Button(tab_manage, text="CLOSE ALL", bootstyle="warning", width=15, command=self._close_position).pack(fill=X, padx=20, pady=5)
        r_m = tb.Frame(tab_manage)
        r_m.pack(fill=X)
        tb.Button(r_m, text="WINNERS", bootstyle="success-outline", width=10, command=self._close_profit).pack(side=LEFT, padx=10, expand=True)
        tb.Button(r_m, text="LOSERS", bootstyle="danger-outline", width=10, command=self._close_loss).pack(side=RIGHT, padx=10, expand=True)

    def _build_acct_label(self, parent, text, attr_name, style):
        f = tb.Frame(parent)
        f.pack(side=LEFT, padx=10, pady=5)
        tb.Label(f, text=text, font=("Helvetica", 7)).pack()
        lbl = tb.Label(f, text="0", font=("Helvetica", 11, "bold"), bootstyle=style)
        lbl.pack()
        setattr(self, attr_name, lbl)

    def _build_prot_group(self, parent, label):
        grp = tb.Frame(parent)
        grp.pack(side=LEFT, fill=X, expand=True, padx=2)
        tb.Label(grp, text=label, width=3, font=("Helvetica", 8)).pack(side=LEFT)
        entry = tb.Entry(grp, width=6, font=("Helvetica", 9))
        entry.insert(0, "0")
        entry.bind("<KeyRelease>", self._update_estimates)
        tb.Button(grp, text="-", bootstyle="outline-secondary", width=2, command=lambda: self._adjust_entry(entry, -1)).pack(side=LEFT)
        entry.pack(side=LEFT, padx=1)
        tb.Button(grp, text="+", bootstyle="outline-secondary", width=2, command=lambda: self._adjust_entry(entry, 1)).pack(side=LEFT)
        tb.Button(grp, text="📍", bootstyle="link-secondary", width=2, command=lambda: self._fill_price(entry)).pack(side=LEFT)
        lbl_est = tb.Label(grp, text="(-)", font=("Helvetica", 7), bootstyle="secondary")
        lbl_est.pack(side=LEFT)
        return entry, lbl_est

    def _on_auto_toggle(self):
        is_on = self.auto_trade_var.get()
        limit = self.max_pos_var.get()
        status_text = "ON" if is_on else "OFF"
        self.chk_auto.config(text=f"Standard Auto: {status_text}")
        
        if is_on:
            self.scalp_var.set(False)
            self.chk_scalp.config(text="Scalp Mode", state="disabled", bootstyle="secondary-round-toggle")
            self.spin_max_pos.configure(state='disabled')
            if self.strategy: 
                self.strategy.scalping_active = False 
                self.strategy.max_positions = limit
                self.strategy.auto_close_profit = self.auto_profit_var.get()
                self.strategy.profit_close_interval = self.profit_sec_var.get()
                self._update_strategy_params_safe()
                self.strategy.start()
        else:
            self.chk_scalp.config(state="normal", bootstyle="danger-round-toggle")
            self.spin_max_pos.configure(state='normal')
            if self.strategy: self.strategy.stop()
            
    def _on_scalp_toggle(self):
        is_scalp = self.scalp_var.get()
        if is_scalp:
             self.chk_scalp.config(text="⚡ Scalping: ON")
             self.auto_trade_var.set(False)
             self.chk_auto.config(text="Standard Auto", state="disabled", bootstyle="secondary-round-toggle")
             if self.strategy:
                 self.strategy.scalping_active = True
                 self.strategy.auto_close_profit = self.auto_profit_var.get()
                 self.strategy.max_positions = self.max_pos_var.get()
                 self.strategy.lot_size = float(self.entry_volume.get())
                 self.strategy.start()
        else:
             self.chk_scalp.config(text="Scalp Mode")
             self.chk_auto.config(state="normal", bootstyle="success-round-toggle")
             if self.strategy:
                 self.strategy.scalping_active = False
                 self.strategy.stop()

    def _on_auto_range_toggle(self):
        if self.strategy:
            self.strategy.use_dynamic_range = self.auto_range_var.get()

    def _on_scalp_param_changed(self, *args):
        if self.strategy:
            try: self.strategy.scalp_tp_amount = float(self.scalp_tp_var.get())
            except: pass

    def _update_strategy_params_safe(self):
        if not self.strategy: return
        try:
            self.strategy.min_price = float(self.entry_min_price.get())
            self.strategy.max_price = float(self.entry_max_price.get())
            self.strategy.zone_percent = int(self.spin_zone.get())
            self.strategy.use_fvg = self.fvg_var.get()
            self.strategy.use_ob = self.ob_var.get()
            self.strategy.use_zone_confluence = self.zone_conf_var.get()
            self.strategy.use_dynamic_range = self.auto_range_var.get()
            self.strategy.use_trend_filter = self.trend_var.get()
        except: pass

    def _on_strat_filter_changed(self):
        if not self.strategy: return
        self._update_strategy_params_safe()

    def _refresh_symbols(self):
        self.request_symbol_refresh = True
        
    def _set_combo_values(self, symbols):
        current = self.combo_symbol.get()
        self.combo_symbol['values'] = tuple(symbols)
        if current not in symbols and symbols:
            self.symbol_var.set(symbols[0])
        if not self.symbols_loaded:
            self.symbols_loaded = True
            
    def _on_symbol_changed(self, event):
        symbol = self.combo_symbol.get()
        if not symbol: return
        self.lbl_symbol_display.config(text=f"Loading {symbol}...")
        self.lbl_bid.config(text="...")
        self.lbl_ask.config(text="...")
        try: self.mt5_connector.change_symbol(symbol)
        except AttributeError: pass

    def _on_timeframe_changed(self, event):
        symbol = self.combo_symbol.get()
        tf = self.combo_tf.get()
        if symbol and tf:
            logging.info(f"Changing timeframe to {tf}...")
            self.mt5_connector.change_timeframe(symbol, tf)

    def _send_trade(self, action):
        symbol = self.combo_symbol.get()
        if not symbol: return
        try: vol = float(self.entry_volume.get())
        except: return
        try: sl = float(self.entry_sl.get())
        except: sl = 0.0
        try: tp = float(self.entry_tp.get())
        except: tp = 0.0
        if action in ["BUY", "SELL"] and not self.market_prot_var.get():
            sl = 0.0; tp = 0.0
        try: price = float(self.entry_price.get())
        except: price = 0.0
        self.mt5_connector.send_command(action, symbol, vol, sl, tp, price)

    def _on_volume_changed(self, event):
        try:
            vol = float(self.entry_volume.get())
            if self.strategy: self.strategy.lot_size = vol
        except ValueError: pass

    def _close_position(self):
        symbol = self.combo_symbol.get()
        if symbol: self.mt5_connector.close_position(symbol)

    def _close_profit(self):
        symbol = self.combo_symbol.get()
        if symbol: self.mt5_connector.close_profit(symbol)

    def _close_loss(self):
        symbol = self.combo_symbol.get()
        if symbol: self.mt5_connector.close_loss(symbol)

    def _on_range_changed(self, event):
        if not self.strategy: return
        try:
            self.strategy.min_price = float(self.entry_min_price.get())
            self.strategy.max_price = float(self.entry_max_price.get())
        except ValueError: pass

    def _on_max_pos_changed(self, *args):
        if not self.strategy: return
        try: self.strategy.max_positions = self.max_pos_var.get()
        except: pass

    def _on_profit_loop_toggle(self):
        if not self.strategy: return
        self.strategy.auto_close_profit = self.auto_profit_var.get()

    def _on_profit_sec_changed(self, *args):
        if not self.strategy: return
        try: self.strategy.profit_close_interval = self.profit_sec_var.get()
        except: pass

    def _on_zone_changed(self, *args):
        if not self.strategy: return
        try: self.strategy.zone_percent = self.zone_var.get()
        except: pass

    def _update_estimates(self, event=None):
        try:
            current_price = self.current_bid
            if current_price <= 0: return
            vol = float(self.entry_volume.get())
            multiplier = 1.0
            symbol = self.combo_symbol.get().upper()
            if "XAU" in symbol or "GOLD" in symbol: multiplier = 100.0
            def update_lbl(entry, lbl):
                try:
                    val = float(entry.get())
                    if val > 0:
                        diff = val - current_price
                        est_pl = diff * vol * multiplier
                        lbl.config(text=f"(${abs(est_pl):,.2f})", bootstyle="info")
                    else: lbl.config(text="($0.00)", bootstyle="secondary")
                except: lbl.config(text="(--)", bootstyle="secondary")
            update_lbl(self.entry_sl, self.lbl_sl_est)
            update_lbl(self.entry_tp, self.lbl_tp_est)
        except: pass

    def _fill_price(self, entry_widget):
        if self.current_bid > 0:
            entry_widget.delete(0, tk.END)
            entry_widget.insert(0, f"{self.current_bid}")
            self._update_estimates()

    def _fill_limit_price(self):
        if self.current_bid > 0:
            self.entry_price.delete(0, tk.END)
            self.entry_price.insert(0, f"{self.current_bid}")

    def _set_volume(self, val):
        self.entry_volume.delete(0, tk.END)
        self.entry_volume.insert(0, str(val))
        self._on_volume_changed(None)
        self._update_estimates()

    def _adjust_entry(self, entry_widget, delta):
        try:
            val = float(entry_widget.get())
            new_val = val + delta
            entry_widget.delete(0, tk.END)
            entry_widget.insert(0, f"{new_val:.3f}")
            self._update_estimates()
        except: pass

    def _build_log_view(self, parent):
        self.log_area = scrolledtext.ScrolledText(parent, state='disabled', height=10, bg="#1e1e1e", fg="#00ff00", font=("Consolas", 8)) 
        self.log_area.pack(fill=BOTH, expand=YES)
        self.log_area.tag_config('INFO', foreground='white')
        self.log_area.tag_config('WARNING', foreground='yellow')
        self.log_area.tag_config('ERROR', foreground='red')

    def _check_log_queue(self):
        while not log_queue.empty():
            record = log_queue.get()
            msg = self.format_log_record(record)
            self.log_area.configure(state='normal')
            tag = 'INFO'
            if record.levelno == logging.WARNING: tag = 'WARNING'
            if record.levelno == logging.ERROR: tag = 'ERROR'
            self.log_area.insert(tk.END, msg + "\n", tag)
            self.log_area.see(tk.END)
            self.log_area.configure(state='disabled')
            if "Connected" in msg or "Pulse" in msg: self._update_status()
        self.after(100, self._check_log_queue)

    def format_log_record(self, record):
        return f"{time.strftime('%H:%M:%S', time.localtime(record.created))} | {record.getMessage()}"

if __name__ == "__main__":
    app = TradingBotUI(None, None)
    app.mainloop()