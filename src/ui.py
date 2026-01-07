import threading
import time
import logging
import queue
import tkinter as tk
from tkinter import ttk, scrolledtext
import ttkbootstrap as tb
from ttkbootstrap.constants import *
try:
    from ttkbootstrap.tooltip import ToolTip  # For tooltips
except ImportError:
    ToolTip = None  # Fallback if not available

log_queue = queue.Queue()

class QueueHandler(logging.Handler):
    def emit(self, record):
        log_queue.put(record)

class TradingBotUI(tb.Window):
    def __init__(self, news_engine, mt5_connector):
        super().__init__(themename="darkly")
        self.title("MT5 Trading Bot Command Center v4.0 - Modern Dashboard") 
        self.geometry("1400x900")  # MODERN: Wider for cards/charts
        
        self.news_engine = news_engine
        self.mt5_connector = mt5_connector
        self.strategy = None
        
        self.mt5_connector.on_tick_received = self._on_tick_received
        self.mt5_connector.on_symbols_received = self._on_symbols_received
        
        # --- UI State Variables (unchanged) ---
        self.auto_trade_var = tk.BooleanVar(value=True)
        self.max_pos_var = tk.IntVar(value=100)
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
        self.price_history = []  # For simple chart

        # MODERN: Periodic pulse animation
        self.pulse_value = 0
        self._animate_pulse()

    # --- UPDATED: Accepts avg_entry ---
    def _on_tick_received(self, symbol, bid, ask, balance, profit, acct_name, positions, buy_count, sell_count, avg_entry, candles):
        self.after(0, lambda: self._update_ui_data(symbol, bid, ask, balance, profit, acct_name, positions, buy_count, sell_count, avg_entry, candles))
        self.after(0, lambda: self._update_status())
        # MODERN: Update price history for chart
        self.price_history.append((time.time(), (bid + ask) / 2))
        if len(self.price_history) > 50:  # Limit for performance
            self.price_history.pop(0)
        self._draw_price_chart()

    def _on_symbols_received(self, symbols_list):
        if not self.symbols_loaded or getattr(self, 'request_symbol_refresh', False):
            self.after(0, lambda: self._set_combo_values(symbols_list))
            self.request_symbol_refresh = False

    def _update_status(self):
        try: 
            self.lbl_mt5.config(text="🟢 MT5: Connected", bootstyle="success", font=("Helvetica", 10, "bold"))
        except: pass

    # --- UPDATED: Uses avg_entry; card-based updates with fade ---
    def _update_ui_data(self, symbol, bid, ask, balance, profit, acct_name, positions, buy_count, sell_count, avg_entry, candles):
        try:
            clean_incoming = str(symbol).replace('\x00', '').strip()
            clean_selected = str(self.combo_symbol.get()).replace('\x00', '').strip()

            if not clean_selected:
                self.symbol_var.set(clean_incoming)
                clean_selected = clean_incoming

            # Update cards with modern styling
            self._update_card(self.lbl_balance, f"💰 {balance:,.2f}", "success" if balance > 10000 else "info")
            self._update_card(self.lbl_account, f"👤 {acct_name}", "secondary")
            self._update_card(self.lbl_positions, f"📊 {positions}/100", "warning" if positions > 0 else "secondary")
            self._update_card(self.lbl_buy_count, f"🟢 {buy_count}", "success" if buy_count > 0 else "secondary")
            self._update_card(self.lbl_sell_count, f"🔴 {sell_count}", "danger" if sell_count > 0 else "secondary")
            
            p_text = f"${profit:+,.2f}"
            boot = "success" if profit > 0 else "danger" if profit < 0 else "secondary"
            self._update_card(self.lbl_profit, f"📈 {p_text}", boot, font=("Helvetica", 14, "bold"))

            if clean_incoming == clean_selected:
                self.lbl_symbol_display.config(text=f"🔄 {clean_incoming}")
                self.lbl_bid.config(text=f"BID: {bid:.3f}", bootstyle="info")
                self.lbl_ask.config(text=f"ASK: {ask:.3f}", bootstyle="success")
                
                # Avg Entry
                if avg_entry > 0:
                    self._update_card(self.lbl_avg_entry, f"🎯 {avg_entry:.3f}", "info")
                else:
                    self.lbl_avg_entry.config(text="🎯 ---", bootstyle="secondary")
                
                self.current_bid = bid
                self.current_ask = ask
                
                # Auto-range sync (unchanged)
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

                # Range thresholds
                try:
                    mn = float(self.entry_min_price.get())
                    mx = float(self.entry_max_price.get())
                    zp = int(self.zone_var.get())
                    span = mx - mn
                    buy_th = mn + (span * zp / 100.0)
                    sell_th = mx - (span * zp / 100.0)
                    self.lbl_range_low.config(text=f"🟢 < {buy_th:.2f}", bootstyle="success")
                    self.lbl_range_high.config(text=f"🔴 > {sell_th:.2f}", bootstyle="danger")
                except:
                    self.lbl_range_low.config(text="🟢 ---")
                    self.lbl_range_high.config(text="🔴 ---")

                # Patterns with icons
                if self.strategy:
                    patterns = self.strategy.analyze_patterns(candles) if candles else {}
                    p_text = []
                    if patterns.get('bullish_fvg', False): p_text.append("🟢 BULL FVG")
                    if patterns.get('bearish_fvg', False): p_text.append("🔴 BEAR FVG")
                    self.lbl_patterns.config(text=" | ".join(p_text) if p_text else "🔍 Scanning...", bootstyle="warning" if p_text else "secondary")

                    fvg = patterns.get('fvg_zone')
                    self.lbl_fvg_price.config(text=f"🟡 {fvg[0]:.4f}-{fvg[1]:.4f}" if fvg else "🟡 ---", bootstyle="warning" if fvg else "secondary")
                    ob = patterns.get('ob_zone')
                    self.lbl_ob_price.config(text=f"🔵 {ob[0]:.4f}-{ob[1]:.4f}" if ob else "🔵 ---", bootstyle="info" if ob else "secondary")

                    c3h = patterns.get('c3_high', 0)
                    c1l = patterns.get('c1_low', 0)
                    self.lbl_debug_vals.config(text=f"📐 C3_H: {c3h:.2f} | C1_L: {c1l:.2f}")
                    if c3h < c1l: self.lbl_debug_vals.config(bootstyle="success") 
                    elif c3h > c1l: self.lbl_debug_vals.config(bootstyle="danger") 

        except Exception as e:
            logging.error(f"UI Update Error: {e}")

    # MODERN: Helper for card updates with fade effect
    def _update_card(self, label, text, bootstyle, font=None):
        if font: label.config(font=font)
        label.config(text=text, bootstyle=bootstyle)
        # Simple fade: Change alpha (ttkbootstrap simulates via color pulse)
        label.after(200, lambda: label.config(bootstyle=bootstyle))  # Re-apply for 'refresh'

    # MODERN: Simple price chart on canvas
    def _draw_price_chart(self):
        if not hasattr(self, 'canvas_chart') or not self.canvas_chart: return
        self.canvas_chart.delete("all")
        if len(self.price_history) < 2: return
        
        w, h = 400, 150
        self.canvas_chart.config(width=w, height=h)
        x_scale = w / len(self.price_history)
        y_min = min(p[1] for p in self.price_history)
        y_max = max(p[1] for p in self.price_history)
        y_range = y_max - y_min if y_max > y_min else 1
        
        # Draw line
        for i in range(1, len(self.price_history)):
            x1 = (i-1) * x_scale
            y1 = h - ((self.price_history[i-1][1] - y_min) / y_range * h)
            x2 = i * x_scale
            y2 = h - ((self.price_history[i][1] - y_min) / y_range * h)
            self.canvas_chart.create_line(x1, y1, x2, y2, fill="cyan", width=2)

    # MODERN: Animate pulse progress bar
    def _animate_pulse(self):
        self.pulse_value = (self.pulse_value + 10) % 100
        if hasattr(self, 'progress_pulse'):
            self.progress_pulse['value'] = self.pulse_value
        self.after(500, self._animate_pulse)  # Heartbeat every 500ms

    # --- Sync & Toggle Methods (unchanged from prior, with tooltips) ---
    def _sync_ui_to_strategy(self):
        if self.strategy:
            self.strategy.max_positions = self.max_pos_var.get()
            self.strategy.set_active(self.auto_trade_var.get())
            self.strategy.zone_percent = self.zone_var.get()
            self.strategy.auto_close_profit = self.auto_profit_var.get()
            self.strategy.profit_close_interval = self.profit_sec_var.get()
            logging.info(f"UI synced: Active={self.auto_trade_var.get()}, Max Pos={self.max_pos_var.get()}, Zone%={self.zone_var.get()}")

    def _on_auto_toggle(self):
        if self.strategy:
            self.strategy.set_active(self.auto_trade_var.get())
            logging.info(f"Auto-Toggle: {self.auto_trade_var.get()}")

    def _on_max_pos_changed(self, *args):
        if self.strategy:
            self.strategy.max_positions = self.max_pos_var.get()
            logging.info(f"Max Positions updated to {self.strategy.max_positions}")

    def _on_scalp_toggle(self):
        if self.strategy:
            self.strategy.scalp_mode = self.scalp_var.get()
            logging.info(f"Scalp Mode: {self.scalp_var.get()}")

    def _on_scalp_param_changed(self, *args):
        if self.strategy:
            self.strategy.scalp_tp_amount = self.scalp_tp_var.get()

    def _on_profit_loop_toggle(self):
        if self.strategy:
            self.strategy.auto_close_profit = self.auto_profit_var.get()
            self.strategy.profit_close_interval = self.profit_sec_var.get()
            logging.info(f"Profit Close: {self.auto_profit_var.get()} every {self.profit_sec_var.get()}s")

    def _on_auto_range_toggle(self):
        if self.strategy:
            self.strategy.use_dynamic_range = self.auto_range_var.get()

    def _on_zone_changed(self, *args):
        if self.strategy:
            self.strategy.zone_percent = self.zone_var.get()

    def _on_range_changed(self, *args):
        try:
            min_p = float(self.entry_min_price.get())
            max_p = float(self.entry_max_price.get())
            if self.strategy:
                self.strategy.min_price = min_p
                self.strategy.max_price = max_p
        except ValueError:
            pass

    # MODERN: Quick actions
    def _on_close_all(self):
        if self.strategy:
            self.strategy.connector.close_position(self.symbol_var.get())
            logging.info("Quick Close All triggered")

    def _on_refresh_data(self):
        self.mt5_connector.request_symbols()
        self.request_symbol_refresh = True
        logging.info("Data refreshed")

    # MODERN: Tooltip creator
    def _create_tooltip(self, widget, text):
        if ToolTip:
            try:
                ToolTip(widget, text, bootstyle="dark", delay=0.5)
            except:
                pass  # Fallback if not available

    def _setup_logging(self):
        queue_handler = QueueHandler()
        queue_handler.setFormatter(logging.Formatter('%(asctime)s: %(message)s', datefmt='%H:%M:%S'))
        logging.getLogger().addHandler(queue_handler)

    def _create_widgets(self):
        # MODERN: Header with title & status
        header = tb.Frame(self, bootstyle="dark")
        header.pack(fill=X, padx=10, pady=5)
        tb.Label(header, text="🚀 MT5 Trading Bot v4.0", font=("Helvetica", 16, "bold"), bootstyle="light").pack(side=LEFT)
        self.lbl_mt5 = tb.Label(header, text="🔴 MT5: Disconnected", bootstyle="danger", font=("Helvetica", 10, "bold"))
        self.lbl_mt5.pack(side=RIGHT)
        self._create_tooltip(self.lbl_mt5, "MT5 connection status")

        self.tabs = ttk.Notebook(self)
        self.tabs.pack(fill=BOTH, expand=YES, padx=10, pady=5)
        self.tab_dashboard = ttk.Frame(self.tabs)
        self.tabs.add(self.tab_dashboard, text="📊 Dashboard")
        self._build_modern_dashboard(self.tab_dashboard)
        self.tab_logs = ttk.Frame(self.tabs)
        self.tabs.add(self.tab_logs, text="📝 Logs & News")
        self._build_log_view(self.tab_logs)

    def _build_modern_dashboard(self, parent):
        # MODERN: Top row - Metric Cards
        cards_row = tb.Frame(parent)
        cards_row.pack(fill=X, pady=10)
        
        # FIX: Pre-define labels as self attributes (no walrus in tuple)
        self.lbl_balance = tb.Label(bootstyle="success", font=("Helvetica", 12, "bold"))
        self.lbl_profit = tb.Label(bootstyle="secondary", font=("Helvetica", 14, "bold"))
        self.lbl_positions = tb.Label(bootstyle="secondary")
        self.lbl_buy_count = tb.Label(bootstyle="secondary")
        self.lbl_sell_count = tb.Label(bootstyle="secondary")
        self.lbl_account = tb.Label(bootstyle="secondary")
        
        metrics = [
            ("Balance", self.lbl_balance),
            ("P/L", self.lbl_profit),
            ("Positions", self.lbl_positions),
            ("Buys", self.lbl_buy_count),
            ("Sells", self.lbl_sell_count)
        ]
        for i, (title, lbl) in enumerate(metrics):
            # FINAL FIX: Use plain ttk.LabelFrame (no bootstyle - theme applies)
            card = ttk.LabelFrame(cards_row, text=title, padding=10)
            card.pack(side=LEFT, padx=5, fill=X, expand=True)
            lbl.pack()
            self._update_card(lbl, "---", "secondary")  # Init

        # MODERN: Middle row - Prices & Patterns
        mid_row = tb.Frame(parent)
        mid_row.pack(fill=X, pady=10)
        
        # Symbol & Prices Card
        # FINAL FIX: Use plain ttk.LabelFrame
        price_card = ttk.LabelFrame(mid_row, text="💱 Live Prices", padding=10)
        price_card.pack(side=LEFT, fill=X, expand=True, padx=5)
        self.lbl_symbol_display = tb.Label(price_card, text="---", font=("Helvetica", 12, "bold"))
        self.lbl_symbol_display.pack()
        price_frame = tb.Frame(price_card)
        price_frame.pack(fill=X)
        self.lbl_bid = tb.Label(price_frame, text="BID: ---", bootstyle="info")
        self.lbl_bid.pack(side=LEFT)
        self.lbl_ask = tb.Label(price_frame, text="ASK: ---", bootstyle="success")
        self.lbl_ask.pack(side=RIGHT)
        self.lbl_avg_entry = tb.Label(price_card, text="AVG ENTRY: ---", bootstyle="secondary")
        self.lbl_avg_entry.pack()

        # Patterns Card
        # FINAL FIX: Use plain ttk.LabelFrame
        patterns_card = ttk.LabelFrame(mid_row, text="🎯 Signals", padding=10)
        patterns_card.pack(side=LEFT, fill=X, expand=True, padx=5)
        self.lbl_patterns = tb.Label(patterns_card, text="Scanning...", bootstyle="secondary")
        self.lbl_patterns.pack()
        self.lbl_fvg_price = tb.Label(patterns_card, text="---", bootstyle="secondary")
        self.lbl_fvg_price.pack()
        self.lbl_ob_price = tb.Label(patterns_card, text="---", bootstyle="secondary")
        self.lbl_ob_price.pack()
        self.lbl_debug_vals = tb.Label(patterns_card, text="---", bootstyle="secondary")
        self.lbl_debug_vals.pack()

        # MODERN: Chart Canvas
        # FINAL FIX: Use plain ttk.LabelFrame
        chart_frame = ttk.LabelFrame(parent, text="📉 Price Chart (Last 50 Ticks)", padding=10)
        chart_frame.pack(fill=X, pady=10)
        self.canvas_chart = tk.Canvas(chart_frame, bg="black", height=150)
        self.canvas_chart.pack(fill=X)

        # MODERN: Config Panels (grid for alignment)
        config_grid = tb.Frame(parent)
        config_grid.pack(fill=BOTH, expand=YES, pady=10)
        
        # Left: Modes
        # FINAL FIX: Use plain ttk.LabelFrame
        modes_panel = ttk.LabelFrame(config_grid, text="⚙️ Operation Modes", padding=10)
        modes_panel.grid(row=0, column=0, sticky="nsew", padx=5)
        f_auto = tb.Frame(modes_panel)
        f_auto.pack(fill=X)
        self.chk_auto = tb.Checkbutton(f_auto, text="Standard Auto", variable=self.auto_trade_var, bootstyle="success-round-toggle", command=self._on_auto_toggle)
        self.chk_auto.pack(side=LEFT)
        self._create_tooltip(self.chk_auto, "Enable automated trading based on FVG signals")
        # Max Pos
        f_auto_sets = tb.Frame(f_auto)
        f_auto_sets.pack(side=RIGHT)
        tb.Label(f_auto_sets, text="Max Pos:").pack(side=LEFT)
        self.spin_max_pos = tb.Spinbox(f_auto_sets, from_=1, to=100, textvariable=self.max_pos_var, width=5)
        self.spin_max_pos.pack(side=LEFT)
        self.max_pos_var.trace("w", self._on_max_pos_changed)

        # Scalp
        f_scalp = tb.Frame(modes_panel)
        f_scalp.pack(fill=X)
        self.chk_scalp = tb.Checkbutton(f_scalp, text="Scalp Mode", variable=self.scalp_var, bootstyle="danger-round-toggle", command=self._on_scalp_toggle)
        self.chk_scalp.pack(side=LEFT)
        self._create_tooltip(self.chk_scalp, "Enable high-frequency scalping with fixed TP")
        tb.Label(f_scalp, text="TP: $").pack(side=RIGHT)
        tb.Spinbox(f_scalp, from_=0.1, to=100.0, increment=0.1, textvariable=self.scalp_tp_var, width=5).pack(side=RIGHT)
        self.scalp_tp_var.trace("w", self._on_scalp_param_changed)

        # Middle: Boundaries
        # FINAL FIX: Use plain ttk.LabelFrame
        bounds_panel = ttk.LabelFrame(config_grid, text="📏 Boundaries", padding=10)
        bounds_panel.grid(row=0, column=1, sticky="nsew", padx=5)
        tb.Checkbutton(bounds_panel, text="Auto Range", variable=self.auto_range_var, bootstyle="info-round-toggle", command=self._on_auto_range_toggle).pack(anchor="w")
        self._create_tooltip(self.auto_range_var, "Dynamically adjust min/max from history")
        
        f_grid = tb.Frame(bounds_panel)
        f_grid.pack(fill=X)
        tb.Label(f_grid, text="Min:").grid(row=0, column=0, sticky="e")
        self.entry_min_price = tb.Entry(f_grid, width=10)
        self.entry_min_price.insert(0, "0")
        self.entry_min_price.grid(row=0, column=1)
        self.entry_min_price.bind("<KeyRelease>", self._on_range_changed)
        
        tb.Label(f_grid, text="Max:").grid(row=1, column=0, sticky="e")
        self.entry_max_price = tb.Entry(f_grid, width=10)
        self.entry_max_price.insert(0, "0")
        self.entry_max_price.grid(row=1, column=1)
        self.entry_max_price.bind("<KeyRelease>", self._on_range_changed)

        tb.Label(f_grid, text="Zone %:").grid(row=2, column=0, sticky="e")
        self.spin_zone = tb.Spinbox(f_grid, from_=1, to=50, textvariable=self.zone_var, width=5)
        self.spin_zone.grid(row=2, column=1)
        self.zone_var.trace("w", self._on_zone_changed)
        
        self.lbl_range_low = tb.Label(bounds_panel, text="---")
        self.lbl_range_low.pack(anchor="w")
        self.lbl_range_high = tb.Label(bounds_panel, text="---")
        self.lbl_range_high.pack(anchor="w")

        # Right: Logic & Quick Actions
        # FINAL FIX: Use plain ttk.LabelFrame
        logic_panel = ttk.LabelFrame(config_grid, text="🔧 Logic & Actions", padding=10)
        logic_panel.grid(row=0, column=2, sticky="nsew", padx=5)
        
        # Pulse Close
        f_pulse = tb.Frame(logic_panel)
        f_pulse.pack(fill=X)
        self.chk_profit = tb.Checkbutton(f_pulse, text="Pulse Close", variable=self.auto_profit_var, bootstyle="info-square-toggle", command=self._on_profit_loop_toggle)
        self.chk_profit.pack(side=LEFT)
        self._create_tooltip(self.chk_profit, "Auto-close profitable positions every X seconds")
        tb.Label(f_pulse, text="Sec:").pack(side=RIGHT)
        self.spin_profit_sec = tb.Spinbox(f_pulse, from_=1, to=60, textvariable=self.profit_sec_var, width=3)
        self.spin_profit_sec.pack(side=RIGHT)
        self.profit_sec_var.trace("w", self._on_profit_loop_toggle)

        # Filters with icons
        tb.Checkbutton(logic_panel, text="🟢 FVG", variable=self.fvg_var, bootstyle="success").pack(anchor="w", pady=2)
        tb.Checkbutton(logic_panel, text="🔵 OB", variable=self.ob_var, bootstyle="info").pack(anchor="w", pady=2)
        tb.Checkbutton(logic_panel, text="🟡 Zone Conf.", variable=self.zone_conf_var, bootstyle="warning").pack(anchor="w", pady=2)
        tb.Checkbutton(logic_panel, text="📊 Trend Filter", variable=self.trend_var, bootstyle="primary").pack(anchor="w", pady=2)

        # Quick Actions Buttons
        actions_frame = tb.Frame(logic_panel)
        actions_frame.pack(fill=X, pady=10)
        tb.Button(actions_frame, text="🚨 Close All", command=self._on_close_all, bootstyle="danger-outline").pack(side=LEFT, padx=5)
        tb.Button(actions_frame, text="🔄 Refresh", command=self._on_refresh_data, bootstyle="info-outline").pack(side=RIGHT, padx=5)

        # Pulse Progress Bar
        self.progress_pulse = tb.Progressbar(logic_panel, bootstyle="success-striped", mode='determinate', length=200)
        self.progress_pulse.pack(fill=X, pady=5)
        self._create_tooltip(self.progress_pulse, "Market heartbeat - bot is alive!")

        # Symbol Selector (bottom)
        bottom_frame = tb.Frame(parent)
        bottom_frame.pack(fill=X, pady=10)
        tb.Label(bottom_frame, text="🔍 Symbol:").pack(side=LEFT)
        self.combo_symbol = ttk.Combobox(bottom_frame, textvariable=self.symbol_var, state="readonly", width=15)
        self.combo_symbol.pack(side=LEFT, padx=5)
        self.combo_symbol.bind("<<ComboboxSelected>>", self._on_symbol_changed)
        self._create_tooltip(self.combo_symbol, "Select trading symbol (e.g., XAUUSDm)")

        config_grid.columnconfigure((0,1,2), weight=1)

    def _build_log_view(self, parent):
        # MODERN: Split logs & news horizontally
        log_split = tb.PanedWindow(parent, orient=HORIZONTAL)
        log_split.pack(fill=BOTH, expand=YES, padx=10, pady=10)
        
        # Logs
        # FINAL FIX: Use plain ttk.LabelFrame
        log_frame = ttk.LabelFrame(log_split, text="📝 Live Logs")
        log_split.add(log_frame, weight=2)
        self.text_log = scrolledtext.ScrolledText(log_frame, height=25, font=("Consolas", 9), bg="black", fg="white", insertbackground="white")
        self.text_log.pack(fill=BOTH, expand=YES, padx=5, pady=5)

        # News with sentiment
        # FINAL FIX: Use plain ttk.LabelFrame
        news_frame = ttk.LabelFrame(log_split, text="📰 News Feed")
        log_split.add(news_frame, weight=1)
        self.text_news = scrolledtext.ScrolledText(news_frame, height=25, font=("Helvetica", 9), state="disabled")
        self.text_news.pack(fill=BOTH, expand=YES, padx=5, pady=5)
        self._update_news_feed()

    def _check_log_queue(self):
        try:
            while True:
                record = log_queue.get_nowait()
                msg = self.format(record)
                self.text_log.insert(tk.END, msg + "\n")
                self.text_log.see(tk.END)
                if record.levelno >= logging.ERROR:
                    self.text_log.tag_add("error", "end-1l", "end")
                    self.text_log.tag_config("error", foreground="red")
        except queue.Empty:
            pass
        self.after(100, self._check_log_queue)

    def format(self, record):
        return logging.Formatter('%(asctime)s [%(levelname)s] %(message)s', datefmt='%H:%M:%S').format(record)

    # MODERN: Enhanced news with sentiment icons
    def _update_news_feed(self):
        if self.news_engine:
            news_items = self.news_engine.get_recent_news(5)
            self.text_news.config(state="normal")
            self.text_news.delete(1.0, tk.END)
            for item in news_items:
                sent_icon = "🟢" if item['sentiment'] == "BULLISH" else "🔴" if item['sentiment'] == "BEARISH" else "🟡"
                self.text_news.insert(tk.END, f"{sent_icon} {item['title']} - {item['time']}\n{item['summary'][:120]}...\nScore: {item['score']}\n\n")
            self.text_news.config(state="disabled")
        self.after(30000, self._update_news_feed)

    # Placeholder methods (unchanged)
    def _set_combo_values(self, symbols_list):
        self.combo_symbol['values'] = symbols_list
        if symbols_list:
            self.symbol_var.set(symbols_list[0])
        self.symbols_loaded = True

    def _on_symbol_changed(self, event=None):
        if self.strategy:
            self.strategy.symbol = self.symbol_var.get()

    def _refresh_symbols(self):
        self.mt5_connector.request_symbols()
        self.request_symbol_refresh = True

    def mainloop(self):
        super().mainloop()