import threading
import time
import datetime # Ensure this is at the top of your file
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
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
from matplotlib.figure import Figure
from matplotlib.dates import DateFormatter
import matplotlib.dates as mdates
from PIL import Image, ImageTk  
import csv
import io

log_queue = queue.Queue()

class QueueHandler(logging.Handler):
    def emit(self, record):
        log_queue.put(record)

class TradingBotUI(tb.Window):
    def __init__(self, news_engine, mt5_connector):
        super().__init__(themename="darkly")  
        self.title("MT5 Trading Bot Command Center v6.0 - Professional Dashboard")
        self.geometry("1400x900")
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
        self.price_history = []  
        self.candles_data = []   
        self.tick_count = 0  
        self.open_positions = []  
        self.profit_history = []  
        
        self.auto_trade_var = tk.BooleanVar(value=True)
        self.max_pos_var = tk.IntVar(value=100)
        self.scalp_var = tk.BooleanVar(value=False)
        self.scalp_tp_var = tk.DoubleVar(value=0.50)
        self.auto_profit_var = tk.BooleanVar(value=True)
        self.profit_sec_var = tk.IntVar(value=1)
        self.fvg_var = tk.BooleanVar(value=True)
        self.ob_var = tk.BooleanVar(value=True)
        self.zone_conf_var = tk.BooleanVar(value=True)
        self.zone_var = tk.IntVar(value=20)
        self.trend_var = tk.BooleanVar(value=True)
        self.auto_range_var = tk.BooleanVar(value=True)
        self.tf_var = tk.StringVar(value="M1")
        self.symbol_var = tk.StringVar()
        self.market_prot_var = tk.BooleanVar(value=True)
        self.lot_size_var = tk.DoubleVar(value=0.01)
        self.sl_var = tk.DoubleVar(value=0.0)
        self.tp_var = tk.DoubleVar(value=0.0)
        
        self.mt5_connector.on_tick_received = self._on_tick_received
        self.mt5_connector.on_symbols_received = self._on_symbols_received
        
        self._setup_logging()
        self._create_widgets()
        self._check_log_queue()
        
        self.bind('<Control-r>', lambda e: self._on_refresh_data())
        self.bind('<Control-t>', lambda e: self._toggle_theme())
        self.bind('<Control-e>', lambda e: self._export_logs())
        
        self.pulse_value = 0
        self._animate_pulse()
        self.after(30000, self._update_news)  
        self._update_header_time()

    def _setup_styles(self):
        """Centralized font management for ttk widgets"""
        style = tb.Style()
        style.configure("TCheckbutton", font=("Segoe UI", 10))
        style.configure("TSpinbox", font=("Segoe UI", 9))
        style.configure("TEntry", font=("Segoe UI", 9))
        style.configure("Treeview", font=("Segoe UI", 9))
        style.configure("Treeview.Heading", font=("Segoe UI", 10, "bold"))

    def _update_header_time(self):
        now = time.strftime("%Y-%m-%d %H:%M:%S")
        if hasattr(self, 'lbl_time'):
            self.lbl_time.config(text=now)
        self.after(1000, self._update_header_time)

    def _on_tick_received(self, symbol, bid, ask, balance, profit, acct_name, positions, buy_count, sell_count, avg_entry, candles):
        self.after(0, lambda: self._update_ui_data(symbol, bid, ask, balance, profit, acct_name, positions, buy_count, sell_count, avg_entry, candles))
        self.after(0, lambda: self._update_status())
        
        mid = (bid + ask) / 2
        self.price_history.append((time.time(), mid))
        if len(self.price_history) > 50: self.price_history.pop(0)
        if candles:  
            last = candles[-1]
            self.candles_data.append([last['time'], last['open'], last['high'], last['low'], last['close']])
            if len(self.candles_data) > 100: self.candles_data.pop(0)
        
        self.tick_count += 1
        self.profit_history.append(profit)
        if len(self.profit_history) > 20: self.profit_history.pop(0)
        
        self.open_positions = [{'symbol': symbol, 'type': 'BUY' if buy_count > 0 else 'SELL', 'size': buy_count + sell_count, 'pnl': profit / max(1, positions)} for _ in range(min(positions, 5))]
        if self.tick_count % 5 == 0:
            self.after(0, self._draw_price_chart)

    def _on_symbols_received(self, symbols_list):
        if not self.symbols_loaded or getattr(self, 'request_symbol_refresh', False):
            self.after(0, lambda: self._set_combo_values(symbols_list))
            self.symbols_loaded = True
            self.request_symbol_refresh = False

    def _update_status(self):
        try: self.lbl_mt5.config(text="MT5: Connected", bootstyle="success")
        except: pass

    def _update_ui_data(self, symbol, bid, ask, balance, profit, acct_name, positions, buy_count, sell_count, avg_entry, candles):
        try:
            clean_symbol = str(symbol).replace('\x00', '').strip()
            clean_selected = str(self.combo_symbol.get()).replace('\x00', '').strip()
            if not clean_selected:
                self.symbol_var.set(clean_symbol)
                clean_selected = clean_symbol

            if clean_symbol == clean_selected:
                self.lbl_symbol_display.config(text=clean_symbol)
                self.lbl_bid.config(text=f"{bid:.3f}")
                self.lbl_ask.config(text=f"{ask:.3f}")
                self.current_bid, self.current_ask = bid, ask

            self._update_card(self.lbl_balance, f"${balance:,.2f}", "success" if balance > 10000 else "info")
            self._update_card(self.lbl_account, acct_name, "secondary")
            self._update_card(self.lbl_positions, f"{positions}/100", "warning" if positions > 50 else "secondary")
            self._update_card(self.lbl_buy_count, f"🟢 Buys: {buy_count}", "success")
            self._update_card(self.lbl_sell_count, f"🔴 Sells: {sell_count}", "danger")
            
            p_text = f"${profit:+,.2f}"
            boot = "success" if profit > 0 else "danger" if profit < 0 else "secondary"
            self._update_card(self.lbl_profit, p_text, boot, font=("Segoe UI", 18, "bold"))
            
            self.lbl_avg_entry.config(text=f"{avg_entry:.3f}" if avg_entry > 0 else "---", bootstyle="info" if avg_entry > 0 else "secondary")

            equity = balance + profit
            self.lbl_equity.config(text=f"${equity:,.2f}", bootstyle="success" if equity > balance else "danger")
            self.lbl_pnl_state.config(text=f"${profit:+,.2f}", bootstyle="success" if profit > 0 else "danger" if profit < 0 else "secondary")
            self.lbl_free_margin.config(text=f"${balance * 0.1:,.2f}", bootstyle="info")
            
            self._update_positions_table()
            self._draw_profit_sparkline()
        except Exception as e:
            logging.error(f"UI Update Error: {e}")

    def _update_card(self, label, text, bootstyle, font=None):
        if font: label.config(font=font)
        label.config(text=text, bootstyle=bootstyle)

    def _draw_price_chart(self):
        if not hasattr(self, 'fig') or len(self.candles_data) < 1: return
        self.ax.clear()
        data = self.candles_data[-50:]
        times = [mdates.date2num(datetime.datetime.fromtimestamp(t)) for t, _, _, _, _ in data]
        opens = [o for _, o, _, _, _ in data]
        highs = [h for _, _, h, _, _ in data]
        lows = [l for _, _, _, l, _ in data]
        closes = [c for _, _, _, _, c in data]
        
        for i in range(len(data)):
            color = 'green' if closes[i] >= opens[i] else 'red'
            self.ax.plot([times[i], times[i]], [lows[i], highs[i]], color=color, linewidth=1)
            self.ax.add_patch(plt.Rectangle((times[i]-0.0001, min(opens[i], closes[i])), 0.0002, abs(closes[i]-opens[i]), color=color, alpha=0.7))
        
        self.ax.xaxis.set_major_formatter(DateFormatter('%H:%M'))
        bg_color = 'black' if 'dark' in self.current_theme else 'white'
        fg_color = 'white' if 'dark' in self.current_theme else 'black'
        self.fig.patch.set_facecolor(bg_color)
        self.ax.set_facecolor(bg_color)
        self.ax.tick_params(colors=fg_color)
        self.canvas.draw()

    def _draw_profit_sparkline(self):
        if hasattr(self, 'profit_canvas') and len(self.profit_history) > 1:
            self.profit_canvas.delete("all")
            max_pnl = max(abs(x) for x in self.profit_history) or 1
            for i in range(1, len(self.profit_history)):
                y1 = 10 - (self.profit_history[i-1] / max_pnl * 10)
                y2 = 10 - (self.profit_history[i] / max_pnl * 10)
                self.profit_canvas.create_line((i-1)*5, y1, i*5, y2, fill='lime' if self.profit_history[i] > 0 else 'red', width=2)

    def _update_positions_table(self):
        if hasattr(self, 'positions_tree'):
            for item in self.positions_tree.get_children(): self.positions_tree.delete(item)
            for pos in self.open_positions:
                self.positions_tree.insert('', 'end', values=(pos['symbol'], pos['type'], f"{pos['size']:.2f}", f"${pos['pnl']:+.2f}"))

    def _animate_pulse(self):
        self.pulse_value = (self.pulse_value + 10) % 100
        if hasattr(self, 'progress_pulse'): self.progress_pulse['value'] = self.pulse_value
        self.after(500, self._animate_pulse)

    def _sync_ui_to_strategy(self):
        if self.strategy:
            self.strategy.max_positions = self.max_pos_var.get()
            self.strategy.set_active(self.auto_trade_var.get())
            self.strategy.scalp_mode = self.scalp_var.get()
            logging.info("UI synced to strategy")

    def _on_auto_toggle(self): self._sync_ui_to_strategy()
    def _on_max_pos_changed(self, *args): self._sync_ui_to_strategy()
    def _on_scalp_toggle(self): self._sync_ui_to_strategy()
    def _on_scalp_param_changed(self, *args): self._sync_ui_to_strategy()
    def _on_profit_loop_toggle(self): self._sync_ui_to_strategy()
    def _on_auto_range_toggle(self): self._sync_ui_to_strategy()
    def _on_zone_changed(self, *args): self._sync_ui_to_strategy()
    def _on_range_changed(self, *args): pass
    def _on_symbol_change(self, *args): 
        if self.strategy: self.strategy.set_symbol(self.symbol_var.get())

    def _on_close_all(self): pass
    def _on_close_profit(self): pass
    def _on_close_loss(self): pass
    def _on_buy(self): pass
    def _on_sell(self): pass

    def _on_refresh_data(self):
        self.mt5_connector.request_symbols()
        self.request_symbol_refresh = True

    def _set_combo_values(self, symbols_list):
        self.combo_symbol['values'] = symbols_list
        if symbols_list: self.symbol_var.set(symbols_list[0])

    def _toggle_theme(self):
        self.current_theme = "cosmo" if self.current_theme == "darkly" else "darkly"
        self.style.theme_use(self.current_theme)
        self._setup_styles() # Re-apply after theme swap
        self._draw_price_chart()

    def _toggle_account_panel(self):
        if self.account_frame.winfo_ismapped(): self.account_frame.pack_forget()
        else: self.account_frame.pack(fill=X, pady=5)

    def show_notification(self, title, message, level="info"):
        if level == "error": Messagebox.show_error(title, message)
        else: Messagebox.show_info(title, message)

    def _filter_logs(self, event=None): pass
    def _export_logs(self): self.show_notification("Export", "Logs saved to logs.csv")

    def _update_news(self):
        news_str = self.news_engine.get_latest_news(5)
        self.news_text.delete(1.0, tk.END)
        self.news_text.insert(tk.END, news_str)
        self.after(30000, self._update_news)

    def _create_tooltip(self, widget, text):
        if ToolTip: ToolTip(widget, text, bootstyle="dark", delay=500)

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
                self.log_text.insert(tk.END, self.format(record) + '\n')
                self.log_text.see(tk.END)
        except queue.Empty: pass
        self.after(100, self._check_log_queue)

    def format(self, record):
        return logging.Formatter('%(asctime)s: %(message)s', datefmt='%H:%M:%S').format(record)

    def _create_widgets(self):
        self._setup_styles()
        main_frame = ttk.Frame(self, padding=0)
        main_frame.pack(fill=BOTH, expand=True)
        
        header_frame = ttk.Frame(main_frame, relief="solid", borderwidth=1)
        header_frame.pack(fill=X, padx=10, pady=(10, 5))
        ttk.Label(header_frame, text="🛡️ MT5 Pro Trading Bot v6.0", font=("Segoe UI", 14, "bold")).pack(side=LEFT)
        self.lbl_time = ttk.Label(header_frame, text="", font=("Segoe UI", 10))
        self.lbl_time.pack(side=RIGHT)
        
        status_frame = ttk.Frame(main_frame, relief="sunken", borderwidth=1)
        status_frame.pack(fill=X, padx=10, pady=5)
        self.lbl_mt5 = ttk.Label(status_frame, text="MT5: Disconnected", bootstyle="danger", font=("Segoe UI", 10))
        self.lbl_mt5.pack(side=LEFT, padx=10)
        ttk.Button(status_frame, text="🎨 Theme", command=self._toggle_theme, bootstyle="outline-primary").pack(side=RIGHT, padx=5)

        notebook = ttk.Notebook(main_frame, padding=5)
        notebook.pack(fill=BOTH, expand=True, padx=10, pady=5)

        dashboard_tab = ttk.Frame(notebook)
        notebook.add(dashboard_tab, text="📈 Dashboard")
        self._build_dashboard_tab(dashboard_tab)

        settings_tab = ttk.Frame(notebook)
        notebook.add(settings_tab, text="⚙️ Settings")
        self._build_settings_tab(settings_tab)

        logs_tab = ttk.Frame(notebook)
        notebook.add(logs_tab, text="📝 Logs")
        self._build_logs_tab(logs_tab)

        news_tab = ttk.Frame(notebook)
        notebook.add(news_tab, text="📰 News")
        self.news_text = scrolledtext.ScrolledText(news_tab, height=20, font=('Consolas', 9))
        self.news_text.pack(fill=BOTH, expand=True, padx=10, pady=10)

    def _build_dashboard_tab(self, parent):
        cards_frame = ttk.Frame(parent, padding=10)
        cards_frame.pack(fill=X)
        for i in range(4): cards_frame.grid_columnconfigure(i, weight=1)

        # Balance & Profit Cards
        b_card = ttk.LabelFrame(cards_frame, text="💰 Balance", padding=15, relief="raised", borderwidth=2)
        b_card.grid(row=0, column=0, sticky="nsew", padx=5, pady=5)
        self.lbl_balance = ttk.Label(b_card, text="$0.00", font=("Segoe UI", 20, "bold"))
        self.lbl_balance.pack()
        self._create_tooltip(b_card, "Current account balance")

        p_card = ttk.LabelFrame(cards_frame, text="📉 P&L", padding=15, relief="raised", borderwidth=2)
        p_card.grid(row=0, column=1, sticky="nsew", padx=5, pady=5)
        self.lbl_profit = ttk.Label(p_card, text="$0.00", font=("Segoe UI", 20, "bold"))
        self.lbl_profit.pack()
        self.profit_canvas = tk.Canvas(p_card, width=100, height=20, bg='black', highlightthickness=0)
        self.profit_canvas.pack(pady=5)
        self._create_tooltip(p_card, "Profit and Loss with sparkline")

        # Bid & Ask Cards
        bid_card = ttk.LabelFrame(cards_frame, text="📊 Bid", padding=15, relief="raised", borderwidth=2)
        bid_card.grid(row=0, column=2, sticky="nsew", padx=5, pady=5)
        self.lbl_bid = ttk.Label(bid_card, text="---", font=("Segoe UI", 20, "bold"), bootstyle="info")
        self.lbl_bid.pack()
        self._create_tooltip(bid_card, "Current bid price")

        ask_card = ttk.LabelFrame(cards_frame, text="📈 Ask", padding=15, relief="raised", borderwidth=2)
        ask_card.grid(row=0, column=3, sticky="nsew", padx=5, pady=5)
        self.lbl_ask = ttk.Label(ask_card, text="---", font=("Segoe UI", 20, "bold"), bootstyle="success")
        self.lbl_ask.pack()
        self._create_tooltip(ask_card, "Current ask price")

        # Stats Cards
        s_card = ttk.LabelFrame(cards_frame, text="📊 Stats", padding=15, relief="raised", borderwidth=2)
        s_card.grid(row=1, column=0, columnspan=4, sticky="nsew", padx=5, pady=5)
        self.lbl_account = ttk.Label(s_card, text="---", font=("Segoe UI", 12))
        self.lbl_account.pack(side=LEFT, padx=15)
        self.lbl_positions = ttk.Label(s_card, text="0/100", font=("Segoe UI", 12))
        self.lbl_positions.pack(side=LEFT, padx=15)
        self.lbl_buy_count = ttk.Label(s_card, text="🟢 Buys: 0", font=("Segoe UI", 12))
        self.lbl_buy_count.pack(side=LEFT, padx=15)
        self.lbl_sell_count = ttk.Label(s_card, text="🔴 Sells: 0", font=("Segoe UI", 12))
        self.lbl_sell_count.pack(side=LEFT, padx=15)
        self._create_tooltip(s_card, "Trading statistics")

        ttk.Separator(parent, orient='horizontal').pack(fill=X, pady=10)

        # Treeview (FIXED: No font arg)
        table_frame = ttk.LabelFrame(parent, text="📋 Open Positions", padding=15, relief="raised", borderwidth=2)
        table_frame.pack(fill=BOTH, expand=True, pady=10)
        self.positions_tree = ttk.Treeview(table_frame, columns=('Symbol', 'Type', 'Size', 'P&L'), show='headings', height=6)
        for col in ('Symbol', 'Type', 'Size', 'P&L'): 
            self.positions_tree.heading(col, text=col)
            self.positions_tree.column(col, anchor='center', width=120)
        self.positions_tree.pack(fill=BOTH, expand=True)
        self._create_tooltip(table_frame, "Current open trading positions")

        ttk.Separator(parent, orient='horizontal').pack(fill=X, pady=10)

        # Bottom Controls
        ctl_frame = ttk.Frame(parent, padding=10)
        ctl_frame.pack(fill=X)
        self.combo_symbol = ttk.Combobox(ctl_frame, textvariable=self.symbol_var, state="readonly", width=18, font=("Segoe UI", 10))
        self.combo_symbol.pack(side=LEFT, padx=10)
        self.lbl_symbol_display = ttk.Label(ctl_frame, text="---", font=("Segoe UI", 14, "bold"))
        self.lbl_symbol_display.pack(side=LEFT, padx=10)
        
        ttk.Label(ctl_frame, text="Lot:", font=("Segoe UI", 10)).pack(side=LEFT, padx=5)
        self.entry_lot = ttk.Entry(ctl_frame, textvariable=self.lot_size_var, width=10, font=("Segoe UI", 9))
        self.entry_lot.pack(side=LEFT, padx=5)
        self._create_tooltip(self.entry_lot, "Lot size for trades")
        ttk.Label(ctl_frame, text="SL:", font=("Segoe UI", 10)).pack(side=LEFT, padx=5)
        self.entry_sl = ttk.Entry(ctl_frame, textvariable=self.sl_var, width=10, font=("Segoe UI", 9))
        self.entry_sl.pack(side=LEFT, padx=5)
        self._create_tooltip(self.entry_sl, "Stop Loss in pips")
        ttk.Label(ctl_frame, text="TP:", font=("Segoe UI", 10)).pack(side=LEFT, padx=5)
        self.entry_tp = ttk.Entry(ctl_frame, textvariable=self.tp_var, width=10, font=("Segoe UI", 9))
        self.entry_tp.pack(side=LEFT, padx=5)
        self._create_tooltip(self.entry_tp, "Take Profit in pips")
        
        button_frame = ttk.Frame(ctl_frame)
        button_frame.pack(side=RIGHT, padx=10)
        buy_btn = ttk.Button(button_frame, text="🛒 Buy", command=self._on_buy, bootstyle="success")
        buy_btn.pack(side=LEFT, padx=5)
        self._create_tooltip(buy_btn, "Open Buy position")
        sell_btn = ttk.Button(button_frame, text="📈 Sell", command=self._on_sell, bootstyle="danger")
        sell_btn.pack(side=LEFT, padx=5)
        self._create_tooltip(sell_btn, "Open Sell position")
        close_all_btn = ttk.Button(button_frame, text="❌ Close All", command=self._on_close_all, bootstyle="danger-outline")
        close_all_btn.pack(side=LEFT, padx=5)
        self._create_tooltip(close_all_btn, "Close all positions")
        close_profit_btn = ttk.Button(button_frame, text="💰 Close Profit", command=self._on_close_profit, bootstyle="success-outline")
        close_profit_btn.pack(side=LEFT, padx=5)
        self._create_tooltip(close_profit_btn, "Close profitable positions")
        close_loss_btn = ttk.Button(button_frame, text="⚠️ Close Loss", command=self._on_close_loss, bootstyle="warning-outline")
        close_loss_btn.pack(side=LEFT, padx=5)
        self._create_tooltip(close_loss_btn, "Close losing positions")
        
        self.lbl_avg_entry = ttk.Label(ctl_frame, text="---", font=("Segoe UI", 10))
        self.lbl_avg_entry.pack(side=RIGHT, padx=10)

        ttk.Separator(parent, orient='horizontal').pack(fill=X, pady=10)

        # Account Details (Always Visible)
        self.account_frame = ttk.LabelFrame(parent, text="💼 Account Details", padding=15, relief="raised", borderwidth=2)
        self.account_frame.pack(fill=X, pady=10)
        self.lbl_equity = ttk.Label(self.account_frame, text="$0.00", font=("Segoe UI", 12))
        self.lbl_equity.pack(side=LEFT, padx=15)
        self.lbl_pnl_state = ttk.Label(self.account_frame, text="$0.00", font=("Segoe UI", 12))
        self.lbl_pnl_state.pack(side=LEFT, padx=15)
        self.lbl_free_margin = ttk.Label(self.account_frame, text="$0.00", font=("Segoe UI", 12))
        self.lbl_free_margin.pack(side=LEFT, padx=15)
        self.lbl_margin_level = ttk.Label(self.account_frame, text="0%", font=("Segoe UI", 12))
        self.lbl_margin_level.pack(side=LEFT, padx=15)
        self.lbl_leverage = ttk.Label(self.account_frame, text="1:500", font=("Segoe UI", 12))
        self.lbl_leverage.pack(side=LEFT, padx=15)
        self.lbl_account_num = ttk.Label(self.account_frame, text="---", font=("Segoe UI", 12))
        self.lbl_account_num.pack(side=LEFT, padx=15)
        self._create_tooltip(self.account_frame, "Detailed account information")

    def _build_settings_tab(self, parent):
        parent.configure(padding=10)
        t_frame = ttk.LabelFrame(parent, text="Trading Controls", padding=10)
        t_frame.pack(fill=X, padx=10, pady=5)
        
        # FIXED: Removed font args from ttk.Checkbutton and ttk.Spinbox
        ttk.Checkbutton(t_frame, text="Auto Trade", variable=self.auto_trade_var, command=self._on_auto_toggle).pack(anchor=W)
        ttk.Label(t_frame, text="Max Positions:").pack(anchor=W)
        ttk.Spinbox(t_frame, from_=1, to=100, textvariable=self.max_pos_var, command=self._on_max_pos_changed).pack(anchor=W)
        
        ttk.Checkbutton(t_frame, text="Scalp Mode", variable=self.scalp_var, command=self._on_scalp_toggle).pack(anchor=W)
        ttk.Entry(t_frame, textvariable=self.scalp_tp_var).pack(anchor=W)

        ttk.Label(t_frame, text="Lot Size:").pack(anchor=W)
        ttk.Entry(t_frame, textvariable=self.lot_size_var).pack(anchor=W)
        ttk.Label(t_frame, text="Stop Loss (pips):").pack(anchor=W)
        ttk.Entry(t_frame, textvariable=self.sl_var).pack(anchor=W)
        ttk.Label(t_frame, text="Take Profit (pips):").pack(anchor=W)
        ttk.Entry(t_frame, textvariable=self.tp_var).pack(anchor=W)

        f_frame = ttk.LabelFrame(parent, text="Filters", padding=10)
        f_frame.pack(fill=X, padx=10, pady=5)
        for text, var in [("FVG", self.fvg_var), ("OB", self.ob_var), ("Trend", self.trend_var)]:
            ttk.Checkbutton(f_frame, text=text, variable=var).pack(anchor=W)

    def _build_logs_tab(self, parent):
        self.log_text = scrolledtext.ScrolledText(parent, height=20, font=('Consolas', 9))
        self.log_text.pack(fill=BOTH, expand=True, padx=10, pady=5)