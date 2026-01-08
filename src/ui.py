import threading
import time
import datetime
import logging
import queue
import tkinter as tk
from tkinter import ttk, scrolledtext
import ttkbootstrap as tb
from ttkbootstrap.constants import *
from ttkbootstrap.dialogs import Messagebox
try:
    from ttkbootstrap.tooltip import ToolTip
except ImportError:
    ToolTip = None

log_queue = queue.Queue()

class QueueHandler(logging.Handler):
    def emit(self, record):
        log_queue.put(record)

class TradingBotUI(tb.Window):
    def __init__(self, news_engine, mt5_connector):
        super().__init__(themename="darkly")  
        self.title("MT5 Trading Bot - Pro Dashboard v7.0")
        self.geometry("1000x850") 
        self.resizable(True, True) 
        
        self.news_engine = news_engine
        self.mt5_connector = mt5_connector
        self.strategy = None
        self.current_theme = "darkly"
        
        # State variables
        self.last_price_update = 0
        self.symbols_loaded = False
        self.current_bid = 0.0
        self.current_ask = 0.0
        self.tick_count = 0  
        self.open_positions = []  
        self.profit_history = []  
        
        # Variables
        self.auto_trade_var = tk.BooleanVar(value=False)
        self.max_pos_var = tk.IntVar(value=5)
        self.scalp_var = tk.BooleanVar(value=False)
        self.scalp_tp_var = tk.DoubleVar(value=0.50)
        self.fvg_var = tk.BooleanVar(value=True)
        self.ob_var = tk.BooleanVar(value=True)
        self.trend_var = tk.BooleanVar(value=True)
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
        
        # Bindings
        self.bind('<Control-r>', lambda e: self._on_refresh_data())
        self.bind('<Control-t>', lambda e: self._toggle_theme())
        self.bind('<Control-e>', lambda e: self._export_logs())
        
        self.pulse_value = 0
        self._animate_pulse()
        self.after(5000, self._update_news)  
        self._update_header_time()

    def _setup_styles(self):
        style = tb.Style()
        style.configure("TCheckbutton", font=("Segoe UI", 10))
        style.configure("Treeview.Heading", font=("Segoe UI", 10, "bold"))

    def _update_header_time(self):
        now = time.strftime("%Y-%m-%d %H:%M:%S")
        if hasattr(self, 'lbl_time'):
            self.lbl_time.config(text=now)
        self.after(1000, self._update_header_time)

    def _sync_ui_to_strategy(self):
        if self.strategy:
            self.strategy.max_positions = self.max_pos_var.get()
            self.strategy.set_active(self.auto_trade_var.get())
            self.strategy.scalp_mode = self.scalp_var.get()
            logging.info("UI synced to strategy")

    def _on_tick_received(self, symbol, bid, ask, balance, profit, acct_name, positions, buy_count, sell_count, avg_entry, candles):
        self.after(0, lambda: self._update_ui_data(symbol, bid, ask, balance, profit, acct_name, positions, buy_count, sell_count, avg_entry, candles))
        
        self.tick_count += 1
        
        if profit != 0 and (not self.profit_history or self.profit_history[-1][1] != profit):
             self.profit_history.append((time.strftime("%H:%M:%S"), profit))
             if len(self.profit_history) > 50: self.profit_history.pop(0)
             self.after(0, self._update_history_table)
        
        direction = "BUY" if buy_count > 0 else ("SELL" if sell_count > 0 else "---")
        size = buy_count + sell_count
        if size > 0:
            self.open_positions = [{'symbol': symbol, 'type': direction, 'size': f"{size:.2f} lots", 'pnl': profit}]
        else:
            self.open_positions = []
            
        self.after(0, self._update_positions_table)

    def _on_symbols_received(self, symbols_list):
        if not self.symbols_loaded:
            self.after(0, lambda: self._set_combo_values(symbols_list))
            self.symbols_loaded = True

    def _update_ui_data(self, symbol, bid, ask, balance, profit, acct_name, positions, buy_count, sell_count, avg_entry, candles):
        try:
            clean_symbol = str(symbol).replace('\x00', '').strip()
            current_selection = self.combo_symbol.get()
            
            if not current_selection:
                self.symbol_var.set(clean_symbol)
                current_selection = clean_symbol

            if clean_symbol == current_selection:
                self.lbl_mt5.config(text=f"MT5: Connected ({clean_symbol})", bootstyle="success")
                self.lbl_symbol_display.config(text=clean_symbol)
                self.lbl_bid.config(text=f"{bid:.5f}")
                self.lbl_ask.config(text=f"{ask:.5f}")
                self.current_bid, self.current_ask = bid, ask
            
            self._update_card(self.lbl_balance, f"${balance:,.2f}", "success" if balance > 5000 else "info")
            self._update_card(self.lbl_profit, f"${profit:+,.2f}", "success" if profit >= 0 else "danger")
            self._update_card(self.lbl_positions, f"{positions}/{self.max_pos_var.get()}", "warning" if positions >= self.max_pos_var.get() else "secondary")
            
            equity = balance + profit
            self.lbl_equity.config(text=f"Eq: ${equity:,.2f}", bootstyle="success" if equity >= balance else "warning")
            self.lbl_buy_count.config(text=f"Buys: {buy_count}")
            self.lbl_sell_count.config(text=f"Sells: {sell_count}")

            self._draw_profit_sparkline()

            # --- UPDATE MARKET STRUCTURE INFO ---
            if self.strategy:
                # 1. Trend
                trend = self.strategy.trend
                t_color = "success" if trend == "UPTREND" else "danger" if trend == "DOWNTREND" else "secondary"
                self.lbl_trend.config(text=f"TREND: {trend}", bootstyle=t_color)

                # 2. Range Zones (Swing High/Low)
                high_price = "Waiting..."
                low_price = "Waiting..."
                
                # Retrieve from strategy memory
                if self.strategy.swing_highs:
                    # [-1] is the most recent swing
                    high_price = f"{self.strategy.swing_highs[-1]['price']:.5f}"
                if self.strategy.swing_lows:
                    low_price = f"{self.strategy.swing_lows[-1]['price']:.5f}"

                self.lbl_sell_zone.config(text=f"R-High (Sell): {high_price}")
                self.lbl_buy_zone.config(text=f"R-Low (Buy): {low_price}")

                # 3. Active FVG Signal
                pat = self.strategy.analyze_patterns(candles)
                if pat['bullish_fvg']:
                    self.lbl_signal.config(text=f"Scan: BUY FVG @ {pat['fvg_zone'][1]:.5f}", bootstyle="success")
                elif pat['bearish_fvg']:
                    self.lbl_signal.config(text=f"Scan: SELL FVG @ {pat['fvg_zone'][0]:.5f}", bootstyle="danger")
                else:
                    self.lbl_signal.config(text="Scan: No Pattern", bootstyle="secondary")

        except Exception as e:
            logging.error(f"UI Update Error: {e}")

    def _update_card(self, label, text, bootstyle):
        label.config(text=text, bootstyle=bootstyle)

    def _draw_profit_sparkline(self):
        if hasattr(self, 'profit_canvas') and len(self.profit_history) > 1:
            self.profit_canvas.delete("all")
            w = self.profit_canvas.winfo_width()
            h = self.profit_canvas.winfo_height()
            if w < 10: return 
            
            pnl_values = [p[1] for p in self.profit_history]
            max_pnl = max([abs(x) for x in pnl_values] + [1])
            step = w / len(pnl_values)
            
            self.profit_canvas.create_line(0, h/2, w, h/2, fill="#333333", dash=(2,2))
            
            for i in range(1, len(pnl_values)):
                val1 = pnl_values[i-1]
                val2 = pnl_values[i]
                y1 = (h/2) - (val1 / max_pnl * (h/2 * 0.9))
                y2 = (h/2) - (val2 / max_pnl * (h/2 * 0.9))
                x1 = (i-1) * step
                x2 = i * step
                color = 'lime' if val2 >= 0 else 'red'
                self.profit_canvas.create_line(x1, y1, x2, y2, fill=color, width=2)

    def _update_positions_table(self):
        if hasattr(self, 'positions_tree'):
            for item in self.positions_tree.get_children():
                self.positions_tree.delete(item)
            for pos in self.open_positions:
                tag = 'profit' if pos['pnl'] >= 0 else 'loss'
                self.positions_tree.insert('', 'end', values=(pos['symbol'], pos['type'], pos['size'], f"${pos['pnl']:+.2f}"), tags=(tag,))

    def _update_history_table(self):
        if hasattr(self, 'history_tree'):
            for item in self.history_tree.get_children():
                self.history_tree.delete(item)
            for rec in reversed(self.profit_history[-20:]):
                tag = 'profit' if rec[1] >= 0 else 'loss'
                self.history_tree.insert('', 'end', values=(rec[0], f"${rec[1]:+.2f}"), tags=(tag,))

    def _animate_pulse(self):
        self.pulse_value = (self.pulse_value + 5) % 100
        if hasattr(self, 'progress_pulse'): 
            self.progress_pulse['value'] = self.pulse_value
        self.after(100, self._animate_pulse)

    # --- ACTION HANDLERS ---
    def _on_tf_change(self, event=None):
        s = self.symbol_var.get()
        tf = self.tf_var.get()
        if s and tf:
            logging.info(f"Changing TF to {tf} for {s}")
            self.mt5_connector.change_timeframe(s, tf)

    def _on_buy(self):
        s = self.symbol_var.get()
        if s: self.mt5_connector.send_command("BUY", s, self.lot_size_var.get(), self.sl_var.get(), self.tp_var.get(), 0)

    def _on_sell(self):
        s = self.symbol_var.get()
        if s: self.mt5_connector.send_command("SELL", s, self.lot_size_var.get(), self.sl_var.get(), self.tp_var.get(), 0)

    def _on_close_all(self):
        s = self.symbol_var.get()
        if s: self.mt5_connector.close_position(s)

    def _on_close_profit(self):
        s = self.symbol_var.get()
        if s: self.mt5_connector.close_profit(s)

    def _on_close_loss(self):
        s = self.symbol_var.get()
        if s: self.mt5_connector.close_loss(s)

    # --- UI Interactions ---
    def _on_auto_toggle(self):
        if self.strategy: self.strategy.set_active(self.auto_trade_var.get())
        state = "Enabled" if self.auto_trade_var.get() else "Disabled"
        self.show_notification("Auto Trade", f"Strategy {state}", "success" if self.auto_trade_var.get() else "info")

    def _on_max_pos_changed(self, *args):
        if self.strategy: self.strategy.max_positions = self.max_pos_var.get()
        
    def _on_scalp_toggle(self):
        if self.strategy: self.strategy.scalp_mode = self.scalp_var.get()

    def _on_refresh_data(self):
        self.mt5_connector.request_symbols()
        self.show_notification("System", "Refreshing Symbols...")

    def _set_combo_values(self, symbols_list):
        self.combo_symbol['values'] = symbols_list
        if symbols_list and not self.symbol_var.get(): 
            self.symbol_var.set(symbols_list[0])

    def _toggle_theme(self):
        if self.current_theme == "darkly":
            self.style.theme_use("cosmo")
            self.current_theme = "cosmo"
        else:
            self.style.theme_use("darkly")
            self.current_theme = "darkly"
        self._setup_styles()

    def show_notification(self, title, message, level="info"):
        logging.info(f"{title}: {message}")

    def _export_logs(self):
        try:
            with open("logs_export.csv", "w") as f:
                f.write(self.log_text.get(1.0, tk.END))
            Messagebox.show_info("Export", "Logs saved to logs_export.csv")
        except Exception as e:
            logging.error(f"Export failed: {e}")

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
                msg = self.format(record)
                self.log_text.insert(tk.END, msg + '\n')
                self.log_text.see(tk.END)
        except queue.Empty: pass
        self.after(100, self._check_log_queue)

    def format(self, record):
        return logging.Formatter('%(asctime)s: %(message)s', datefmt='%H:%M:%S').format(record)

    def _create_widgets(self):
        self._setup_styles()
        main_frame = ttk.Frame(self)
        main_frame.pack(fill=BOTH, expand=True)
        
        # Header
        header_frame = ttk.Frame(main_frame, relief="flat")
        header_frame.pack(fill=X, padx=10, pady=5)
        ttk.Label(header_frame, text="🛡️ MT5 Pro Bot v7.0", font=("Segoe UI", 16, "bold"), bootstyle="inverse-dark").pack(side=LEFT)
        self.lbl_mt5 = ttk.Label(header_frame, text="MT5: Connecting...", bootstyle="warning", font=("Segoe UI", 10))
        self.lbl_mt5.pack(side=LEFT, padx=20)
        self.lbl_time = ttk.Label(header_frame, text="", font=("Segoe UI", 10))
        self.lbl_time.pack(side=RIGHT)
        self.progress_pulse = ttk.Progressbar(header_frame, length=100, mode='determinate', bootstyle="success-striped")
        self.progress_pulse.pack(side=RIGHT, padx=10)

        # Tabs
        notebook = ttk.Notebook(main_frame, padding=5)
        notebook.pack(fill=BOTH, expand=True, padx=5, pady=5)

        dashboard_tab = ttk.Frame(notebook)
        notebook.add(dashboard_tab, text="📈 Dashboard")
        self._build_dashboard_tab(dashboard_tab)

        trades_tab = ttk.Frame(notebook)
        notebook.add(trades_tab, text="💱 Trades")
        self._build_trades_tab(trades_tab)

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
        
        self.profit_canvas = tk.Canvas(left_frame.winfo_children()[-1], height=40, bg='#333333', highlightthickness=0)
        self.profit_canvas.pack(fill=X, padx=5, pady=5)

        self._create_stat_card(left_frame, "📊 Open Positions", "0/0", "warning").pack(fill=X, pady=10)
        self.lbl_positions = left_frame.winfo_children()[-1].winfo_children()[0]

        det_frame = ttk.LabelFrame(left_frame, text="Account Snapshot", padding=10)
        det_frame.pack(fill=X, pady=10)
        self.lbl_equity = ttk.Label(det_frame, text="Eq: $0.00", font=("Segoe UI", 11))
        self.lbl_equity.pack(anchor=W, pady=2)
        self.lbl_buy_count = ttk.Label(det_frame, text="Buys: 0", font=("Segoe UI", 11), foreground="lime")
        self.lbl_buy_count.pack(anchor=W, pady=2)
        self.lbl_sell_count = ttk.Label(det_frame, text="Sells: 0", font=("Segoe UI", 11), foreground="red")
        self.lbl_sell_count.pack(anchor=W, pady=2)

        # Right Column: Controls
        right_frame = ttk.Frame(parent, padding=10)
        right_frame.grid(row=0, column=1, sticky="nsew")
        
        ctl_box = ttk.LabelFrame(right_frame, text="Execution", padding=15)
        ctl_box.pack(fill=X, pady=5)
        
        # Symbol & Timeframe
        sym_tf_frame = ttk.Frame(ctl_box)
        sym_tf_frame.pack(fill=X, pady=5)
        
        s_frame = ttk.Frame(sym_tf_frame)
        s_frame.pack(side=LEFT, fill=X, expand=True, padx=(0, 5))
        ttk.Label(s_frame, text="Symbol:", font=("Segoe UI", 10)).pack(anchor=W)
        self.combo_symbol = ttk.Combobox(s_frame, textvariable=self.symbol_var, state="readonly", font=("Segoe UI", 10))
        self.combo_symbol.pack(fill=X)
        
        t_frame = ttk.Frame(sym_tf_frame)
        t_frame.pack(side=RIGHT, fill=X, padx=(5, 0))
        ttk.Label(t_frame, text="Timeframe:", font=("Segoe UI", 10)).pack(anchor=W)
        self.combo_tf = ttk.Combobox(t_frame, textvariable=self.tf_var, values=["M1", "M5", "M15", "M30", "H1", "H4", "D1"], state="readonly", width=6, font=("Segoe UI", 10))
        self.combo_tf.pack(fill=X)
        self.combo_tf.bind("<<ComboboxSelected>>", self._on_tf_change)
        
        self.lbl_symbol_display = ttk.Label(ctl_box, text="---", font=("Segoe UI", 14, "bold"), anchor="center")
        self.lbl_symbol_display.pack(fill=X, pady=5)
        
        prices_frame = ttk.Frame(ctl_box)
        prices_frame.pack(fill=X, pady=10)
        
        bid_col = ttk.Frame(prices_frame)
        bid_col.pack(side=LEFT, padx=10)
        ttk.Label(bid_col, text="BID", font=("Segoe UI", 10), bootstyle="info").pack()
        self.lbl_bid = ttk.Label(bid_col, text="0.000", bootstyle="info", font=("Segoe UI", 25, "bold"))
        self.lbl_bid.pack()

        ask_col = ttk.Frame(prices_frame)
        ask_col.pack(side=RIGHT, padx=10)
        ttk.Label(ask_col, text="ASK", font=("Segoe UI", 10), bootstyle="success").pack()
        self.lbl_ask = ttk.Label(ask_col, text="0.000", bootstyle="success", font=("Segoe UI", 25, "bold"))
        self.lbl_ask.pack()

        # --- NEW: Market Structure Zone ---
        zone_frame = ttk.Frame(ctl_box, relief="solid", borderwidth=1)
        zone_frame.pack(fill=X, pady=10, padx=5)
        
        ttk.Label(zone_frame, text="Detected Range & Signals", font=("Segoe UI", 10, "bold"), bootstyle="inverse-secondary").pack(fill=X)
        
        self.lbl_trend = ttk.Label(zone_frame, text="TREND: ---", font=("Segoe UI", 11, "bold"))
        self.lbl_trend.pack(pady=2)
        
        grid_z = ttk.Frame(zone_frame)
        grid_z.pack(fill=X, pady=2)
        
        self.lbl_sell_zone = ttk.Label(grid_z, text="R-High (Sell): ---", foreground="#ff6b6b")
        self.lbl_sell_zone.pack(side=LEFT, padx=10)
        
        self.lbl_buy_zone = ttk.Label(grid_z, text="R-Low (Buy): ---", foreground="#51cf66")
        self.lbl_buy_zone.pack(side=RIGHT, padx=10)
        
        self.lbl_signal = ttk.Label(zone_frame, text="Scan: Waiting...", font=("Segoe UI", 10))
        self.lbl_signal.pack(pady=5)
        # ----------------------------------

        ttk.Separator(ctl_box, orient='horizontal').pack(fill=X, pady=10)

        grid_params = ttk.Frame(ctl_box)
        grid_params.pack(fill=X)
        
        ttk.Label(grid_params, text="Lot:").grid(row=0, column=0, padx=2)
        ttk.Entry(grid_params, textvariable=self.lot_size_var, width=8).grid(row=0, column=1, padx=2)
        
        ttk.Label(grid_params, text="SL:").grid(row=0, column=2, padx=2)
        ttk.Entry(grid_params, textvariable=self.sl_var, width=8).grid(row=0, column=3, padx=2)
        
        ttk.Label(grid_params, text="TP:").grid(row=0, column=4, padx=2)
        ttk.Entry(grid_params, textvariable=self.tp_var, width=8).grid(row=0, column=5, padx=2)

        btn_grid = ttk.Frame(ctl_box)
        btn_grid.pack(fill=X, pady=15)
        
        ttk.Button(btn_grid, text="BUY", command=self._on_buy, bootstyle="success").pack(side=LEFT, fill=X, expand=True, padx=5)
        ttk.Button(btn_grid, text="SELL", command=self._on_sell, bootstyle="danger").pack(side=LEFT, fill=X, expand=True, padx=5)
        
        close_grid = ttk.Frame(ctl_box)
        close_grid.pack(fill=X, pady=5)
        ttk.Button(close_grid, text="CLOSE PROFIT", command=self._on_close_profit, bootstyle="success-outline").pack(side=LEFT, fill=X, expand=True, padx=2)
        ttk.Button(close_grid, text="CLOSE LOSS", command=self._on_close_loss, bootstyle="danger-outline").pack(side=LEFT, fill=X, expand=True, padx=2)

        ttk.Button(ctl_box, text="CLOSE ALL POSITIONS", command=self._on_close_all, bootstyle="warning-outline").pack(fill=X, pady=10)
        
        auto_frame = ttk.LabelFrame(right_frame, text="Auto Strategy", padding=15)
        auto_frame.pack(fill=X, pady=20)
        ttk.Checkbutton(auto_frame, text="Enable Auto Trade", variable=self.auto_trade_var, command=self._on_auto_toggle, bootstyle="round-toggle").pack()

    def _build_trades_tab(self, parent):
        parent.grid_columnconfigure(0, weight=1)
        parent.grid_rowconfigure(0, weight=1)
        parent.grid_rowconfigure(1, weight=1)
        
        # Active Positions
        active_frame = ttk.LabelFrame(parent, text="Active Positions", padding=10)
        active_frame.grid(row=0, column=0, sticky="nsew", padx=10, pady=5)
        
        cols = ('Sym', 'Type', 'Size', 'PnL')
        self.positions_tree = ttk.Treeview(active_frame, columns=cols, show='headings', height=8)
        for col in cols:
            self.positions_tree.heading(col, text=col)
            self.positions_tree.column(col, width=100)
        
        self.positions_tree.tag_configure('profit', foreground='lime')
        self.positions_tree.tag_configure('loss', foreground='red')
        self.positions_tree.pack(fill=BOTH, expand=True)
        
        # History
        history_frame = ttk.LabelFrame(parent, text="Session History (Last 20 Closed PnL)", padding=10)
        history_frame.grid(row=1, column=0, sticky="nsew", padx=10, pady=5)
        
        h_cols = ('Time', 'Profit')
        self.history_tree = ttk.Treeview(history_frame, columns=h_cols, show='headings', height=8)
        self.history_tree.heading('Time', text='Time')
        self.history_tree.heading('Profit', text='Profit')
        self.history_tree.column('Time', width=150)
        self.history_tree.column('Profit', width=150)
        
        self.history_tree.tag_configure('profit', foreground='lime')
        self.history_tree.tag_configure('loss', foreground='red')
        self.history_tree.pack(fill=BOTH, expand=True)

    def _create_stat_card(self, parent, title, value, bootstyle):
        f = ttk.LabelFrame(parent, text=title, padding=10, bootstyle=bootstyle)
        l = ttk.Label(f, text=value, font=("Segoe UI", 20, "bold"), bootstyle=bootstyle)
        l.pack()
        return f

    def _build_settings_tab(self, parent):
        ttk.Label(parent, text="Bot Settings (Requires Restart for some)", font=("Segoe UI", 12)).pack(pady=10)
        
        sf = ttk.Frame(parent, padding=20)
        sf.pack(fill=BOTH)
        
        ttk.Label(sf, text="Max Auto Positions:").grid(row=0, column=0, sticky=W, pady=5)
        ttk.Spinbox(sf, from_=1, to=20, textvariable=self.max_pos_var, width=10, command=self._on_max_pos_changed).grid(row=0, column=1, sticky=W)
        
        ttk.Checkbutton(sf, text="Scalp Mode", variable=self.scalp_var, command=self._on_scalp_toggle).grid(row=1, column=0, sticky=W, pady=5)
        ttk.Checkbutton(sf, text="Show FVG Zones", variable=self.fvg_var).grid(row=2, column=0, sticky=W, pady=5)
        ttk.Checkbutton(sf, text="Show Order Blocks", variable=self.ob_var).grid(row=3, column=0, sticky=W, pady=5)