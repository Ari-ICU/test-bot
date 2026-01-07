import threading
import time
import logging
import queue
import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox
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

        self._setup_logging()  # FIXED: Local formatter
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
            self.lbl_mt5.config(text="MT5: Connected", bootstyle="success", font=("Helvetica", 10, "bold"))
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
            self._update_card(self.lbl_balance, f"{balance:,.2f}", "success" if balance > 10000 else "info")
            self._update_card(self.lbl_account, f"{acct_name}", "secondary")
            self._update_card(self.lbl_positions, f"{positions}/100", "warning" if positions > 0 else "secondary")
            self._update_card(self.lbl_buy_count, f"{buy_count}", "success" if buy_count > 0 else "secondary")
            self._update_card(self.lbl_sell_count, f"{sell_count}", "danger" if sell_count > 0 else "secondary")
            
            p_text = f"${profit:+,.2f}"
            boot = "success" if profit > 0 else "danger" if profit < 0 else "secondary"
            self._update_card(self.lbl_profit, f"{p_text}", boot, font=("Helvetica", 14, "bold"))

            if clean_incoming == clean_selected:
                self.lbl_symbol_display.config(text=f"{clean_incoming}")
                self.lbl_bid.config(text=f"BID: {bid:.3f}", bootstyle="info")
                self.lbl_ask.config(text=f"ASK: {ask:.3f}", bootstyle="success")
                
                # Avg Entry
                if avg_entry > 0:
                    self._update_card(self.lbl_avg_entry, f"{avg_entry:.3f}", "info")
                else:
                    self.lbl_avg_entry.config(text="---", bootstyle="secondary")
                
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
                    self.lbl_range_low.config(text=f"< {buy_th:.2f}", bootstyle="success")
                    self.lbl_range_high.config(text=f"> {sell_th:.2f}", bootstyle="danger")
                except:
                    self.lbl_range_low.config(text="---")
                    self.lbl_range_high.config(text="---")

                # Patterns with icons
                if self.strategy:
                    patterns = self.strategy.analyze_patterns(candles) if candles else {}
                    p_text = []
                    if patterns.get('bullish_fvg', False): p_text.append("BULL FVG")
                    if patterns.get('bearish_fvg', False): p_text.append("BEAR FVG")
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
            try:
                value = self.scalp_tp_var.get()
                if value.strip():  # Skip if empty
                    float_value = float(value)
                    if float_value >= 0:  # Basic validation: non-negative
                        self.strategy.scalp_tp_amount = float_value
                        logging.info(f"Scalp TP updated to {float_value}")
                    else:
                        logging.warning(f"Invalid Scalp TP: {value} (must be >= 0)")
                # Else: Silent skip—user is typing
            except ValueError:
                # Handles non-numeric input (e.g., letters, partial decimals)
                pass  # Silent—don't crash on typing
            except Exception as e:
                logging.error(f"Scalp TP update error: {e}")

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
            min_p = self.entry_min_price.get().strip()
            max_p = self.entry_max_price.get().strip()
            if min_p and max_p:  # Only if both non-empty
                min_val = float(min_p)
                max_val = float(max_p)
                if min_val < max_val:  # Basic sanity check
                    if self.strategy:
                        self.strategy.min_price = min_val
                        self.strategy.max_price = max_val
                    logging.info(f"Range updated: {min_val:.2f} - {max_val:.2f}")
                else:
                    logging.warning("Invalid range: Min must be < Max")
            # Else: Skip during typing
        except ValueError:
            pass  # Silent on invalid input
        except Exception as e:
            logging.error(f"Range update error: {e}")

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
                # FIXED: Use integer ms (500 = 0.5s)
                ToolTip(widget, text, bootstyle="dark", delay=500)
            except:
                pass  # Fallback if not available

    def _setup_logging(self):
        # FIXED: Local formatter—no self.attr to trip tk __getattr__
        formatter = logging.Formatter('%(asctime)s: %(message)s', datefmt='%H:%M:%S')
        queue_handler = QueueHandler()
        queue_handler.setFormatter(formatter)
        logging.getLogger().addHandler(queue_handler)

    def _check_log_queue(self):
        try:
            while True:
                record = log_queue.get_nowait()
                msg = self.format(record)
                self.log_text.insert(tk.END, msg + '\n')
                self.log_text.see(tk.END)
        except queue.Empty:
            pass
        self.after(100, self._check_log_queue)

    def format(self, record):
        # FIXED: Local formatter here too
        formatter = logging.Formatter('%(asctime)s: %(message)s', datefmt='%H:%M:%S')
        return formatter.format(record)

    def _create_widgets(self):
        # Main container
        main_container = tb.Frame(self)
        main_container.pack(fill=BOTH, expand=True, padx=10, pady=10)

        # Top header bar
        header = tb.Frame(main_container, bootstyle="primary")
        header.pack(fill=X, pady=(0,10))

        tb.Label(header, text="MT5 Trading Bot v4.0", bootstyle="light", font=("Helvetica", 16, "bold")).pack(side=LEFT, padx=10)
        self.lbl_mt5 = tb.Label(header, text="MT5: Disconnected", bootstyle="danger")
        self.lbl_mt5.pack(side=RIGHT, padx=10)

        # Notebook for tabs
        self.notebook = tb.Notebook(main_container, bootstyle="primary")
        self.notebook.pack(fill=BOTH, expand=True)

        # Tab 1: Main Dashboard
        self.tab_main = tb.Frame(self.notebook)
        self.notebook.add(self.tab_main, text="Dashboard")

        # Tab 2: News
        self.tab_news = tb.Frame(self.notebook)
        self.notebook.add(self.tab_news, text="News")

        # Tab 3: Logs
        self.tab_logs = tb.Frame(self.notebook)
        self.notebook.add(self.tab_logs, text="Logs")

        self._build_main_tab(self.tab_main)
        self._build_news_tab(self.tab_news)
        self._build_log_view(self.tab_logs)

    def _build_main_tab(self, parent):
        # Left panel: Controls
        left_panel = tb.Frame(parent)
        left_panel.pack(side=LEFT, fill=Y, padx=(0,10))

        # Auto Trade Toggle
        tb.Checkbutton(left_panel, text="Auto Trade", variable=self.auto_trade_var, 
                       command=self._on_auto_toggle, bootstyle="success-round-toggle").pack(anchor=W, pady=5)
        self._create_tooltip(left_panel.winfo_children()[-1], "Enable/disable automated trading")

        # Max Positions
        tb.Label(left_panel, text="Max Positions:").pack(anchor=W)
        spin_max = tb.Spinbox(left_panel, from_=1, to=100, textvariable=self.max_pos_var, 
                              command=self._on_max_pos_changed, width=10)
        spin_max.pack(anchor=W, pady=2)

        # Scalp Mode
        tb.Checkbutton(left_panel, text="Scalp Mode", variable=self.scalp_var, 
                       command=self._on_scalp_toggle, bootstyle="warning-round-toggle").pack(anchor=W, pady=5)
        tb.Label(left_panel, text="Scalp TP ($):").pack(anchor=W)
        entry_scalp = tb.Entry(left_panel, textvariable=self.scalp_tp_var, width=10)
        entry_scalp.pack(anchor=W, pady=2)
        entry_scalp.bind('<KeyRelease>', self._on_scalp_param_changed)

        # Profit Close Loop
        tb.Checkbutton(left_panel, text="Auto Close Profit", variable=self.auto_profit_var, 
                       command=self._on_profit_loop_toggle, bootstyle="info-round-toggle").pack(anchor=W, pady=5)
        tb.Label(left_panel, text="Interval (s):").pack(anchor=W)
        spin_profit = tb.Spinbox(left_panel, from_=1, to=60, textvariable=self.profit_sec_var, width=10)
        spin_profit.pack(anchor=W, pady=2)

        # Strategy Filters
        filter_frame = tb.LabelFrame(left_panel, text="Strategy Filters")  # FIXED: No styling to avoid TclError
        filter_frame.pack(fill=X, pady=10)
        # filter_frame.configure(style="secondary.TLabelframe")  # SKIPPED: Bug workaround
        tb.Checkbutton(filter_frame, text="FVG", variable=self.fvg_var).pack(anchor=W)
        tb.Checkbutton(filter_frame, text="OB", variable=self.ob_var).pack(anchor=W)
        tb.Checkbutton(filter_frame, text="Zone Confluence", variable=self.zone_conf_var).pack(anchor=W)
        tb.Checkbutton(filter_frame, text="Trend Filter", variable=self.trend_var).pack(anchor=W)

        # Zone %
        tb.Label(filter_frame, text="Zone %:").pack(anchor=W)
        spin_zone = tb.Spinbox(filter_frame, from_=5, to=50, textvariable=self.zone_var, 
                               command=self._on_zone_changed, width=10)
        spin_zone.pack(anchor=W, pady=2)

        # Auto Range
        tb.Checkbutton(left_panel, text="Auto Range", variable=self.auto_range_var, 
                       command=self._on_auto_range_toggle, bootstyle="light-round-toggle").pack(anchor=W, pady=5)

        # Manual Range
        range_frame = tb.LabelFrame(left_panel, text="Manual Range")  # FIXED: No styling
        range_frame.pack(fill=X, pady=10)
        # range_frame.configure(style="secondary.TLabelframe")  # SKIPPED
        tb.Label(range_frame, text="Min Price:").grid(row=0, column=0, sticky=W)
        self.entry_min_price = tb.Entry(range_frame, width=12)
        self.entry_min_price.grid(row=0, column=1, padx=5)
        self.entry_min_price.bind('<KeyRelease>', self._on_range_changed)
        tb.Label(range_frame, text="Max Price:").grid(row=1, column=0, sticky=W)
        self.entry_max_price = tb.Entry(range_frame, width=12)
        self.entry_max_price.grid(row=1, column=1, padx=5)
        self.entry_max_price.bind('<KeyRelease>', self._on_range_changed)

        # Threshold Labels
        self.lbl_range_low = tb.Label(range_frame, text="---", bootstyle="secondary")
        self.lbl_range_low.grid(row=2, column=0, sticky=W, pady=2)
        self.lbl_range_high = tb.Label(range_frame, text="---", bootstyle="secondary")
        self.lbl_range_high.grid(row=2, column=1, sticky=E, pady=2)

        # Quick Actions
        action_frame = tb.Frame(left_panel)
        action_frame.pack(fill=X, pady=10)
        tb.Button(action_frame, text="Close All", command=self._on_close_all, bootstyle="danger-outline").pack(fill=X, pady=2)
        tb.Button(action_frame, text="Refresh Data", command=self._on_refresh_data, bootstyle="info-outline").pack(fill=X, pady=2)

        # Right panel: Market Data Cards
        right_panel = tb.Frame(parent)
        right_panel.pack(side=RIGHT, fill=BOTH, expand=True)

        # Symbol Selector
        symbol_frame = tb.Frame(right_panel)
        symbol_frame.pack(fill=X, pady=5)
        tb.Label(symbol_frame, text="Symbol:").pack(side=LEFT)
        self.combo_symbol = tb.Combobox(symbol_frame, textvariable=self.symbol_var, state="readonly", width=20)
        self.combo_symbol.pack(side=LEFT, padx=5)
        self.combo_symbol.bind('<<ComboboxSelected>>', lambda e: self._on_symbol_change())

        # Price Display
        price_frame = tb.Frame(right_panel)
        price_frame.pack(fill=X, pady=5)
        self.lbl_symbol_display = tb.Label(price_frame, text="---", bootstyle="secondary", font=("Helvetica", 12))
        self.lbl_symbol_display.pack()
        self.lbl_bid = tb.Label(price_frame, text="BID: ---", bootstyle="secondary")
        self.lbl_bid.pack()
        self.lbl_ask = tb.Label(price_frame, text="ASK: ---", bootstyle="secondary")
        self.lbl_ask.pack()

        # Data Cards Grid
        cards_frame = tb.Frame(right_panel)
        cards_frame.pack(fill=BOTH, expand=True, pady=10)

        # Balance Card
        balance_card = tb.LabelFrame(cards_frame, text="Balance")  # FIXED: No styling
        balance_card.grid(row=0, column=0, sticky=EW, padx=5, pady=5)
        # balance_card.configure(style="success.TLabelframe")  # SKIPPED
        self.lbl_balance = tb.Label(balance_card, text="$0.00", bootstyle="success", font=("Helvetica", 18, "bold"))
        self.lbl_balance.pack(pady=10)

        # Account Card
        account_card = tb.LabelFrame(cards_frame, text="Account")  # FIXED: No styling
        account_card.grid(row=0, column=1, sticky=EW, padx=5, pady=5)
        # account_card.configure(style="secondary.TLabelframe")  # SKIPPED
        self.lbl_account = tb.Label(account_card, text="---", bootstyle="secondary")
        self.lbl_account.pack(pady=10)

        # Positions Card
        pos_card = tb.LabelFrame(cards_frame, text="Positions")  # FIXED: No styling
        pos_card.grid(row=1, column=0, sticky=EW, padx=5, pady=5)
        # pos_card.configure(style="warning.TLabelframe")  # SKIPPED
        self.lbl_positions = tb.Label(pos_card, text="0/100", bootstyle="warning")
        self.lbl_positions.pack(pady=10)

        # Profit Card
        profit_card = tb.LabelFrame(cards_frame, text="P&L")  # FIXED: No styling
        profit_card.grid(row=1, column=1, sticky=EW, padx=5, pady=5)
        # profit_card.configure(style="secondary.TLabelframe")  # SKIPPED
        self.lbl_profit = tb.Label(profit_card, text="$0.00", bootstyle="secondary", font=("Helvetica", 18, "bold"))
        self.lbl_profit.pack(pady=10)

        # Buy Count Card
        buy_card = tb.LabelFrame(cards_frame, text="Buys")  # FIXED: No styling
        buy_card.grid(row=2, column=0, sticky=EW, padx=5, pady=5)
        # buy_card.configure(style="success.TLabelframe")  # SKIPPED
        self.lbl_buy_count = tb.Label(buy_card, text="0", bootstyle="success")
        self.lbl_buy_count.pack(pady=10)

        # Sell Count Card
        sell_card = tb.LabelFrame(cards_frame, text="Sells")  # FIXED: No styling
        sell_card.grid(row=2, column=1, sticky=EW, padx=5, pady=5)
        # sell_card.configure(style="danger.TLabelframe")  # SKIPPED
        self.lbl_sell_count = tb.Label(sell_card, text="0", bootstyle="danger")
        self.lbl_sell_count.pack(pady=10)

        # Avg Entry Card
        avg_card = tb.LabelFrame(cards_frame, text="Avg Entry")  # FIXED: No styling
        avg_card.grid(row=3, column=0, columnspan=2, sticky=EW, padx=5, pady=5)
        # avg_card.configure(style="info.TLabelframe")  # SKIPPED
        self.lbl_avg_entry = tb.Label(avg_card, text="---", bootstyle="info")
        self.lbl_avg_entry.pack(pady=10)

        # Patterns & Debug
        patterns_frame = tb.LabelFrame(right_panel, text="Signals & Debug")  # FIXED: No styling
        patterns_frame.pack(fill=X, pady=10)
        # patterns_frame.configure(style="dark.TLabelframe")  # SKIPPED

        self.lbl_patterns = tb.Label(patterns_frame, text="Scanning...", bootstyle="secondary")
        self.lbl_patterns.pack(anchor=W)

        debug_row = tb.Frame(patterns_frame)
        debug_row.pack(fill=X)
        self.lbl_fvg_price = tb.Label(debug_row, text="---", bootstyle="secondary")
        self.lbl_fvg_price.pack(side=LEFT)
        self.lbl_ob_price = tb.Label(debug_row, text="---", bootstyle="secondary")
        self.lbl_ob_price.pack(side=RIGHT)

        self.lbl_debug_vals = tb.Label(patterns_frame, text="---", bootstyle="secondary", font=("Consolas", 9))
        self.lbl_debug_vals.pack(anchor=W, pady=5)

        # Price Chart Canvas
        chart_frame = tb.LabelFrame(right_panel, text="Price Chart")  # FIXED: No styling
        chart_frame.pack(fill=X, pady=10)
        # chart_frame.configure(style="primary.TLabelframe")  # SKIPPED
        self.canvas_chart = tk.Canvas(chart_frame, bg='black', height=150)
        self.canvas_chart.pack(fill=X)

        cards_frame.grid_columnconfigure(0, weight=1)
        cards_frame.grid_columnconfigure(1, weight=1)

    def _build_news_tab(self, parent):
        # News list
        list_frame = tb.Frame(parent)
        list_frame.pack(fill=BOTH, expand=True, padx=10, pady=10)

        # FIXED: Use tk.Listbox instead of tb.Listbox
        self.news_list = tk.Listbox(list_frame, height=20)
        scrollbar = tb.Scrollbar(list_frame, orient=VERTICAL, command=self.news_list.yview)
        self.news_list.config(yscrollcommand=scrollbar.set)
        self.news_list.pack(side=LEFT, fill=BOTH, expand=True)
        scrollbar.pack(side=RIGHT, fill=Y)

        # Bind double-click to open news
        self.news_list.bind('<Double-1>', self._on_news_double_click)

        # Update button
        tb.Button(parent, text="Refresh News", command=self._refresh_news, bootstyle="info-outline").pack(pady=5)

    def _build_log_view(self, parent):
        # FIXED: lowercase 'w' for Panedwindow
        log_split = tb.Panedwindow(parent, orient=tk.HORIZONTAL)
        log_split.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        # Left: Log Text Widget
        self.log_text = tb.Text(log_split, height=20, wrap=tk.WORD, 
                                font=('Consolas', 9), 
                                bg='black', fg='white',
                                insertbackground='white')
        log_frame = tb.Frame(log_split)
        log_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        
        scrollbar = tb.Scrollbar(log_frame, orient=tk.VERTICAL, command=self.log_text.yview)
        self.log_text.config(yscrollcommand=scrollbar.set)
        
        self.log_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        # Right: Log Controls
        controls_frame = tb.Frame(log_split)
        controls_frame.pack(side=tk.RIGHT, fill=tk.Y, padx=(5,0))
        
        clear_btn = tb.Button(controls_frame, text="Clear Logs", 
                              bootstyle="danger-outline",
                              command=self.clear_logs)
        clear_btn.pack(pady=2)
        
        save_btn = tb.Button(controls_frame, text="Save Logs", 
                             bootstyle="info-outline",
                             command=self.save_logs)
        save_btn.pack(pady=2)
        
        # Add to split
        log_split.add(log_frame, weight=4)
        log_split.add(controls_frame, weight=1)

    # FIXED: Missing methods added here
    def clear_logs(self):
        """Clear the log text widget."""
        self.log_text.delete(1.0, tk.END)
        logging.info("Logs cleared by user.")

    def save_logs(self):
        """Save log content to file with optional dialog."""
        try:
            # Default file
            filename = 'bot_logs.txt'
            # Optional: Use filedialog for choose (uncomment if you import it)
            # from tkinter import filedialog
            # filename = filedialog.asksaveasfilename(defaultextension=".txt", filetypes=[("Text files", "*.txt")])
            # if not filename: return
            
            with open(filename, 'w') as f:
                f.write(self.log_text.get(1.0, tk.END))
            logging.info(f"Logs saved to {filename}")
            messagebox.showinfo("Logs Saved", f"Logs exported to {filename}")
        except Exception as e:
            logging.error(f"Failed to save logs: {e}")
            messagebox.showerror("Save Error", f"Couldn't save logs: {e}")

    def _set_combo_values(self, symbols_list):
        self.combo_symbol['values'] = symbols_list
        if symbols_list:
            self.symbol_var.set(symbols_list[0])
        self.symbols_loaded = True
        logging.info(f"Symbols loaded: {len(symbols_list)} items")

    def _on_symbol_change(self, *args):
        symbol = self.symbol_var.get()
        if symbol and self.strategy:
            self.strategy.symbol = symbol  # Assume strategy has this
            logging.info(f"Symbol changed to {symbol}")

    def _refresh_news(self):
        if self.news_engine:
            self.news_engine.scan_feeds()
            self._update_news_list()

    def _update_news_list(self):
        self.news_list.delete(0, tk.END)
        try:
            # Assume news_engine has get_latest() -> list of (title, url, time)
            for item in self.news_engine.get_latest()[-20:]:  # Last 20
                self.news_list.insert(tk.END, f"{item[2]} - {item[0]}")
        except AttributeError:
            self.news_list.insert(tk.END, "News engine not ready - check logs")

    def _on_news_double_click(self, event):
        selection = self.news_list.curselection()
        if selection:
            idx = selection[0]
            try:
                # Assume open in browser or something
                import webbrowser
                url = self.news_engine.get_latest()[idx][1]  # url
                webbrowser.open(url)
                logging.info(f"Opened news: {url}")
            except:
                logging.warning("Could not open news URL")

if __name__ == "__main__":
    # Test stubxq
    class StubNews: 
        def get_latest(self): return [("Test News", "https://example.com", time.time())]
        def scan_feeds(self): pass
    class StubConnector: 
        def request_symbols(self): pass
    app = TradingBotUI(StubNews(), StubConnector())
    app.mainloop()