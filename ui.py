import time
import queue
import logging
import threading
import tkinter as tk
import ttkbootstrap as ttk
from ttkbootstrap.constants import *
from ttkbootstrap.widgets.scrolled import ScrolledText
from collections import deque
from datetime import datetime
from filters.news import _manager as news_manager
AUTO_TABS = ["M1", "M5", "M15", "M30", "H1", "H4", "D1", "W1", "MN"]
class QueueHandler(logging.Handler):
    def __init__(self, log_queue):
        super().__init__()
        self.log_queue = log_queue
    def emit(self, record):
        self.log_queue.put(record)
class TradingApp(ttk.Window):
    def __init__(self, bot_loop_callback, connector, risk_manager, telegram_bot=None):
        super().__init__(themename="cyborg")
        self.title("MT5 Advanced AI Terminal")
        self.geometry("980x680") # Better fit for 13.3" (typically 1280-1440 width)
        self.minsize(900, 600)
        self.bot_loop_callback = bot_loop_callback
        self.connector = connector
        self.risk = risk_manager
        self.config = getattr(risk_manager, 'full_config', {})
        self.telegram_bot = telegram_bot
        self.log_queue = queue.Queue(maxsize=1000)
        self.bot_running = True
        self.bot_thread = None
        risk_cfg = self.config.get('risk', {})
        self.lot_var = tk.DoubleVar(value=risk_cfg.get('lot_size', 0.01))
        self.symbol_var = tk.StringVar(value=self.connector.active_symbol)
        self.tf_var = tk.StringVar(value=self.connector.active_tf) 
        self.style_var = tk.StringVar(value="scalp") 
        self.auto_trade_var = tk.BooleanVar(value=False)
        self.max_trades_var = tk.IntVar(value=risk_cfg.get('max_trades', 10))
        self.max_pos_var = tk.IntVar(value=risk_cfg.get('max_open_positions', 10))
        self.cool_off_var = tk.IntVar(value=risk_cfg.get('cool_off_seconds', 300)) 
        self.crt_reclaim_var = tk.DoubleVar(value=0.25)
        self.tg_token_var = tk.StringVar(value=self.telegram_bot.token if self.telegram_bot else "")
        self.tg_chat_var = tk.StringVar(value=self.telegram_bot.chat_id if self.telegram_bot else "")
        self.strat_vars = {
            "AI_Predict": tk.BooleanVar(value=True),
            "Trend": tk.BooleanVar(value=True),
            "Scalp": tk.BooleanVar(value=True),
            "Breakout": tk.BooleanVar(value=True),
            "TBS_Retest": tk.BooleanVar(value=True),
            "ICT_Master": tk.BooleanVar(value=True),
            "TBS_Turtle": tk.BooleanVar(value=True),
            "CRT_TBS": tk.BooleanVar(value=True),
            "PD_Parameter": tk.BooleanVar(value=True),
            "News_Sentiment": tk.BooleanVar(value=True),
            "Force_News": tk.BooleanVar(value=False),
            "Reversal": tk.BooleanVar(value=True),
            "SMC_Master": tk.BooleanVar(value=True),
            "PowerTF": tk.BooleanVar(value=True)
        }
        
        # Position Management Vars
        pm_cfg = self.config.get('position_management', {})
        self.be_enabled_var = tk.BooleanVar(value=pm_cfg.get('breakeven_enabled', True))
        self.be_trigger_var = tk.DoubleVar(value=pm_cfg.get('breakeven_trigger_pct', 50.0))
        self.trail_enabled_var = tk.BooleanVar(value=pm_cfg.get('trailing_stop_enabled', True))
        self.trail_pct_var = tk.DoubleVar(value=pm_cfg.get('trailing_stop_pct', 0.5))
        self.last_avail_syms = []
        self.last_account_info = None
        self.last_active_symbol = None
        self.last_active_tf = None
        self.buy_btn = None
        self.sell_btn = None
        self.toast_label = None
        self.last_logs = deque(maxlen=50)
        self.log_suppress_threshold = 1.0
        self._setup_logging()
        self._build_ui()
        self._start_log_polling()
        self._start_light_refresh()
        self._start_heavy_refresh()
        self.after(100, self._auto_start_bot)
    def _auto_start_bot(self):
        if not self.bot_running:
            return
        self.status_var.set("BOT: RUNNING")
        self.lbl_status.configure(bootstyle="success-inverse")
        if not self.bot_thread or not self.bot_thread.is_alive():
            self.bot_thread = threading.Thread(target=self.bot_loop_callback, args=(self,), daemon=True)
            self.bot_thread.start()
        logging.info("🚀 Bot Auto-Started - Real-Time Scanning Active")
    def _setup_logging(self):
        root_logger = logging.getLogger()
        root_logger.setLevel(logging.INFO)
        if not any(isinstance(h, QueueHandler) for h in root_logger.handlers):
            queue_handler = QueueHandler(self.log_queue)
            formatter = logging.Formatter('%(asctime)s | %(levelname)s | %(message)s', datefmt='%H:%M:%S')
            queue_handler.setFormatter(formatter)
            root_logger.addHandler(queue_handler)
    def _build_ui(self):
        # Premium Header
        header = ttk.Frame(self, bootstyle="dark")
        header.pack(fill=X, padx=0, pady=0)
        
        header_inner = ttk.Frame(header, bootstyle="dark", padding=(20, 12))
        header_inner.pack(fill=X)

        title_frame = ttk.Frame(header_inner, bootstyle="dark")
        title_frame.pack(side=LEFT)
        
        # Premium Logo styling
        logo_f = ttk.Frame(title_frame, bootstyle="dark")
        logo_f.pack(side=LEFT)
        ttk.Label(logo_f, text="MT5", font=("Orbitron", 18, "bold"), bootstyle="info").pack(side=LEFT)
        ttk.Label(logo_f, text=" QUANT", font=("Orbitron", 18, "bold"), bootstyle="light").pack(side=LEFT)
        ttk.Label(logo_f, text=" TERMINAL", font=("Helvetica", 10, "bold"), bootstyle="secondary").pack(side=LEFT, padx=(5, 0), pady=(5, 0))
        
        status_frame = ttk.Frame(header_inner, bootstyle="dark")
        status_frame.pack(side=RIGHT)
        
        self.lbl_server = ttk.Label(status_frame, text="● SERVER: OFF", bootstyle="danger", font=("Helvetica", 9, "bold"))
        self.lbl_server.pack(side=LEFT, padx=10)
        
        self.status_var = tk.StringVar(value="BOT: STOPPED")
        self.lbl_status = ttk.Label(status_frame, textvariable=self.status_var, bootstyle="warning", font=("Helvetica", 9, "bold"))
        self.lbl_status.pack(side=LEFT, padx=10)
        
        self.lbl_health = ttk.Label(status_frame, text="LATENCY: 0.0s", bootstyle="info", font=("Consolas", 9))
        self.lbl_health.pack(side=LEFT, padx=15)

        # Content Area with Notebook
        style = ttk.Style()
        style.configure("TNotebook.Tab", font=("Helvetica", 10, "bold"), padding=[15, 5])
        
        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill=BOTH, expand=YES, padx=10, pady=5)
        
        self.tab_dashboard = ttk.Frame(self.notebook)
        self.tab_console = ttk.Frame(self.notebook)
        self.tab_market = ttk.Frame(self.notebook)
        self.tab_settings = ttk.Frame(self.notebook)
        
        self.notebook.add(self.tab_dashboard, text="📊 DASHBOARD")
        self.notebook.add(self.tab_console, text="💻 CONSOLE")
        self.notebook.add(self.tab_market, text="🌐 MARKET")
        self.notebook.add(self.tab_settings, text="⚙️ SETTINGS")
        
        self._build_dashboard_tab()
        self._build_console_tab()
        self._build_market_tab()
        self._build_settings_tab()
        self.sym_combo.set(self.connector.active_symbol)

        # Startup check: Add a verification signal to ensure the timeline works
        self.after(2000, lambda: self.add_signal_to_log("SYS", "Backbone", "STARTUP", "Intelligence Timeline Verified - Ready for Signals"))
    
    def _build_dashboard_tab(self):
        # Make Dashboard Scrollable for small screens
        canvas = tk.Canvas(self.tab_dashboard, borderwidth=0, highlightthickness=0)
        scrollbar = ttk.Scrollbar(self.tab_dashboard, orient=VERTICAL, command=canvas.yview)
        container = ttk.Frame(canvas, padding=12)

        canvas.create_window((0, 0), window=container, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        
        # Auto-resize canvas width to match scrollable frame
        def on_configure(e):
            canvas.configure(scrollregion=canvas.bbox("all"))
            canvas.itemconfig(canvas_win, width=e.width)

        canvas_win = canvas.create_window((0,0), window=container, anchor="nw")
        canvas.bind("<Configure>", on_configure)

        canvas.pack(side=LEFT, fill=BOTH, expand=YES)
        scrollbar.pack(side=RIGHT, fill=Y)

        # --- Top Section: Account & Performance ---
        top_row = ttk.Frame(container)
        top_row.pack(fill=X, pady=(0, 15))

        # Account Info Card
        acc_frame = ttk.Labelframe(top_row, text=" Wallet & Account ", padding=10)
        acc_frame.pack(side=LEFT, fill=BOTH, expand=YES, padx=(0, 5))
        
        self._create_stat_box(acc_frame, "MODE", "lbl_acc_mode", "info", "CONNECTING...", 0, 0)
        self._create_stat_box(acc_frame, "BALANCE", "lbl_balance", "primary", "$0.00", 0, 1)
        self._create_stat_box(acc_frame, "EQUITY", "lbl_equity", "primary", "$0.00", 1, 0)
        self._create_stat_box(acc_frame, "FLOATING", "lbl_profit", "success", "$0.00", 1, 1)

        # Performance Card
        perf_frame = ttk.Labelframe(top_row, text=" Daily Performance ", padding=10)
        perf_frame.pack(side=LEFT, fill=BOTH, expand=YES, padx=5)
        
        self._create_stat_box(perf_frame, "TRADES", "lbl_daily_trades", "secondary", "0", 0, 0)
        self._create_stat_box(perf_frame, "DAILY P/L", "lbl_prof_today", "success", "$0.00", 0, 1)
        self._create_stat_box(perf_frame, "WEEKLY", "lbl_prof_week", "success", "$0.00", 1, 0)
        self._create_stat_box(perf_frame, "WIN RATE", "lbl_win_rate", "info", "0%", 1, 1)

        # Market Prices Card
        price_frame = ttk.Labelframe(top_row, text=" Live Market ", padding=10)
        price_frame.pack(side=LEFT, fill=BOTH, expand=YES, padx=(5, 0))
        
        self._create_stat_box(price_frame, "BID", "lbl_bid", "warning", "0.00000", 0, 0)
        self._create_stat_box(price_frame, "ASK", "lbl_ask", "warning", "0.00000", 0, 1)
        self._create_stat_box(price_frame, "BUY POS", "lbl_buy_count", "secondary", "0", 1, 0)
        self._create_stat_box(price_frame, "SELL POS", "lbl_sell_count", "secondary", "0", 1, 1)
        self._create_stat_box(price_frame, "TOTAL POS", "lbl_total_count", "info", "0", 2, 0)

        # --- Middle Section: Strategy Monitor ---
        strat_frame = ttk.Labelframe(container, text=" AI Strategy Intelligence Grid ", padding=10)
        strat_frame.pack(fill=X, pady=10)
        
        self.strat_ui_items = {}
        strat_list = [
            ("AI_Predict", "AI Smart Predictor"), ("Trend", "Trend Following"),
            ("Scalp", "M5 Scalper"), ("Breakout", "Breakout Engine"),
            ("ICT_Master", "ICT Master"), ("TBS_Turtle", "TBS Turtle"),
            ("TBS_Retest", "TBS Retest"), ("CRT_TBS", "CRT MT5 Master"),
            ("PD_Parameter", "PD Array Logic"), ("News_Sentiment", "News Sentiment"),
            ("Reversal", "Reversal Engine"), ("SMC_Master", "SMC Master"),
            ("PowerTF", "Power of TF")
        ]
        
        grid_inner = ttk.Frame(strat_frame)
        grid_inner.pack(fill=X)
        
        for i, (key, name) in enumerate(strat_list):
            r, c = divmod(i, 5) # 5 columns
            f = ttk.Frame(grid_inner, padding=5)
            f.grid(row=r, column=c, sticky=NSEW)
            grid_inner.columnconfigure(c, weight=1)
            
            ttk.Label(f, text=name, font=("Helvetica", 8, "bold"), bootstyle="secondary").pack(anchor=W)
            status_lbl = ttk.Label(f, text="SYNCING", font=("Helvetica", 9, "bold"), bootstyle=SECONDARY)
            status_lbl.pack(anchor=W)
            reason_lbl = ttk.Label(f, text="...", font=("Helvetica", 7), bootstyle=LIGHT)
            reason_lbl.pack(anchor=W)
            self.strat_ui_items[key] = {"status": status_lbl, "reason": reason_lbl}

        # --- Bottom Section: Controls & Config ---
        bottom_row = ttk.Frame(container)
        bottom_row.pack(fill=BOTH, expand=YES, pady=(10, 0))

        # Execution
        exec_group = ttk.Labelframe(bottom_row, text=" Terminal Execution ", padding=15)
        exec_group.pack(side=LEFT, fill=BOTH, expand=YES, padx=(0, 10))
        
        btn_grid = ttk.Frame(exec_group)
        btn_grid.pack(fill=X, pady=5)
        
        self.buy_btn = ttk.Button(btn_grid, text="BUY MARKET", bootstyle="success", command=lambda: self.manual_trade("BUY"), width=15)
        self.buy_btn.pack(side=LEFT, padx=5, pady=5, expand=YES, fill=X)
        
        self.sell_btn = ttk.Button(btn_grid, text="SELL MARKET", bootstyle="danger", command=lambda: self.manual_trade("SELL"), width=15)
        self.sell_btn.pack(side=LEFT, padx=5, pady=5, expand=YES, fill=X)
        
        sep = ttk.Separator(exec_group, orient=HORIZONTAL)
        sep.pack(fill=X, pady=10)
        
        close_grid = ttk.Frame(exec_group)
        close_grid.pack(fill=X)
        
        ttk.Button(close_grid, text="CLOSE PROFIT", bootstyle="success-outline", command=lambda: self.manual_close("WIN")).pack(side=LEFT, padx=2, expand=YES, fill=X)
        ttk.Button(close_grid, text="CLOSE LOSS", bootstyle="danger-outline", command=lambda: self.manual_close("LOSS")).pack(side=LEFT, padx=2, expand=YES, fill=X)
        ttk.Button(close_grid, text="CLOSE ALL", bootstyle="warning-outline", command=lambda: self.manual_close("ALL")).pack(side=LEFT, padx=2, expand=YES, fill=X)

        be_row = ttk.Frame(exec_group)
        be_row.pack(fill=X, pady=(10, 0))
        ttk.Button(be_row, text="🛡️ APPLY BREAKEVEN TO ACTIVE", bootstyle="info-outline", command=self.apply_be_manual).pack(fill=X)

        # Quick Config
        quick_cfg = ttk.Labelframe(bottom_row, text=" Quick Configuration ", padding=15)
        quick_cfg.pack(side=RIGHT, fill=BOTH, expand=YES, padx=(10, 0))
        
        cfg_grid = ttk.Frame(quick_cfg)
        cfg_grid.pack(fill=BOTH, expand=YES)
        
        # Row 0: Auto Trade
        ttk.Label(cfg_grid, text="Auto Trading:", font=("Helvetica", 10, "bold")).grid(row=0, column=0, sticky=W, pady=5)
        ttk.Checkbutton(cfg_grid, bootstyle="success-round-toggle", variable=self.auto_trade_var, text="ACTIVE", command=self.on_auto_trade_toggle).grid(row=0, column=1, sticky=E, pady=5)
        
        # Row 1: Symbol & TF
        ttk.Label(cfg_grid, text="Symbol:", font=("Helvetica", 9)).grid(row=1, column=0, sticky=W, pady=2)
        self.sym_combo = ttk.Combobox(cfg_grid, textvariable=self.symbol_var, width=15)
        self.sym_combo.grid(row=1, column=1, sticky=EW, pady=2)
        
        ttk.Label(cfg_grid, text="Timeframe:", font=("Helvetica", 9)).grid(row=2, column=0, sticky=W, pady=2)
        self.tf_combo = ttk.Combobox(cfg_grid, textvariable=self.tf_var, values=AUTO_TABS, width=15)
        self.tf_combo.grid(row=2, column=1, sticky=EW, pady=2)
        
        # Row 2: Lot & Max
        ttk.Label(cfg_grid, text="Lot Size:", font=("Helvetica", 9)).grid(row=3, column=0, sticky=W, pady=2)
        ttk.Spinbox(cfg_grid, from_=0.01, to=50, textvariable=self.lot_var, width=14).grid(row=3, column=1, sticky=EW, pady=2)
        
        cfg_grid.columnconfigure(1, weight=1)

        # --- Footer Section: Signal History ---
        history_frame = ttk.Labelframe(container, text=" Live Signal Intelligence Timeline ", padding=10)
        history_frame.pack(fill=X, pady=(15, 0)) # Don't expand inside canvas if we want fixed height
        
        columns = ("Time", "TF", "Strategy", "Signal", "Reason")
        # Explicit height in pixels for the treeview to prevent squashing
        self.signal_tree = ttk.Treeview(history_frame, columns=columns, show="headings", height=10, bootstyle="primary")
        
        # Tech styling for treeview
        style = ttk.Style()
        style.configure("Treeview", rowheight=28, font=("Helvetica", 9))
        style.configure("Treeview.Heading", font=("Helvetica", 9, "bold"))

        widths = {"Time": 80, "TF": 60, "Strategy": 150, "Signal": 100, "Reason": 400}
        for col in columns:
            self.signal_tree.heading(col, text=col.upper())
            self.signal_tree.column(col, width=widths[col], anchor=W if col=="Reason" else CENTER)
            
        self.signal_tree.tag_configure('BUY', foreground='#1aff1a', font=("Helvetica", 9, "bold"))
        self.signal_tree.tag_configure('SELL', foreground='#ff4d4d', font=("Helvetica", 9, "bold"))
        self.signal_tree.tag_configure('STARTUP', foreground='#00ccff', font=("Helvetica", 9, "italic"))
        
        self.signal_tree.pack(fill=X, side=LEFT, expand=YES)
        
        # Add scrollbar to signal tree
        sig_scroll = ttk.Scrollbar(history_frame, orient=VERTICAL, command=self.signal_tree.yview)
        self.signal_tree.configure(yscrollcommand=sig_scroll.set)
        sig_scroll.pack(side=RIGHT, fill=Y)

    def _create_stat_box(self, parent, label, attr_name, color, initial, row, col):
        # Card-like frame for stats
        frame = ttk.Frame(parent, padding=6, bootstyle="secondary-subtle")
        frame.grid(row=row, column=col, sticky=EW, padx=3, pady=3)
        parent.columnconfigure(col, weight=1)
        
        ttk.Label(frame, text=label, font=("Helvetica", 8, "bold"), bootstyle="secondary").pack(anchor=W)
        val_lbl = ttk.Label(frame, text=initial, font=("Roboto", 12, "bold"), bootstyle=color)
        val_lbl.pack(anchor=W, pady=(1, 0))
        setattr(self, attr_name, val_lbl)
    def _build_console_tab(self):
        console_frame = ttk.Frame(self.tab_console)
        console_frame.pack(fill=BOTH, expand=YES, padx=10, pady=10)
        btn_frame = ttk.Frame(console_frame)
        btn_frame.pack(fill=X, pady=(0, 10))
        ttk.Button(btn_frame, text="🗑️ Clear Console Logs", bootstyle="danger-outline", command=self.clear_logs).pack(side=RIGHT)
        ttk.Label(btn_frame, text="Live System Feed", font=("Helvetica", 12, "bold")).pack(side=LEFT)
        self.log_area = ScrolledText(console_frame, bootstyle="secondary", height=20, width=120, autohide=True, font=("Consolas", 10))
        self.log_area.pack(fill=BOTH, expand=YES)
        self.log_area.tag_config('INFO', foreground='lightgreen')
        self.log_area.tag_config('WARNING', foreground='#feca57') # Vibrant yellow
        self.log_area.tag_config('ERROR', foreground='#ff6b6b')   # Soft red
        self.log_area.tag_config('DEBUG', foreground='#a0a0a0')   # Muted gray
        self.log_area.tag_config('TIMESTAMP', foreground='#5bc0de') # Cyan for time
    def _build_market_tab(self):
        container = ttk.Frame(self.tab_market)
        container.pack(fill=BOTH, expand=YES, padx=15, pady=15)
        top_frame = ttk.Frame(container)
        top_frame.pack(fill=X, pady=(0, 15))
        info_frame = ttk.Frame(top_frame)
        info_frame.pack(side=LEFT)
        self.lbl_news_sent = ttk.Label(info_frame, text="SENTIMENT: LOADING...", font=("Roboto", 14, "bold"), bootstyle="info")
        self.lbl_news_sent.pack(anchor=W)
        self.lbl_news_date = ttk.Label(info_frame, text="DATE: --", font=("Helvetica", 9), bootstyle="secondary")
        self.lbl_news_date.pack(anchor=W)
        self.lbl_news_status = ttk.Label(top_frame, text="MARKET WATCH: INITIALIZING...", font=("Helvetica", 10), bootstyle="secondary")
        self.lbl_news_status.pack(side=BOTTOM, anchor=W, pady=(5, 0))
        ttk.Button(top_frame, text="🔄 Refresh News Now", bootstyle="info-outline", command=self._force_news_refresh).pack(side=RIGHT)
        content_panes = ttk.Panedwindow(container, orient=HORIZONTAL)
        content_panes.pack(fill=BOTH, expand=YES)
        cal_frame = ttk.Labelframe(content_panes, text=" Economic Calendar (Forex Factory) ", padding=10)
        content_panes.add(cal_frame, weight=3)
        columns = ("Time", "Currency", "Impact", "Event", "Actual", "Forecast", "Previous")
        self.news_tree = ttk.Treeview(cal_frame, columns=columns, show="headings", height=15, bootstyle="info")
        widths = {"Time": 60, "Currency": 70, "Impact": 80, "Event": 250, "Actual": 80, "Forecast": 80, "Previous": 80}
        for col in columns:
            self.news_tree.heading(col, text=col)
            self.news_tree.column(col, width=widths[col], anchor=CENTER if col in ["Impact", "Currency"] else W)
        
        self.news_tree.tag_configure('High', foreground='#ff4d4d', font=("Helvetica", 9, "bold"))
        self.news_tree.tag_configure('Medium', foreground='#ffa31a')
        self.news_tree.tag_configure('Low', foreground='#1aff1a')
        self.news_tree.pack(fill=BOTH, expand=YES)
        
        # Style for alternating rows
        style = ttk.Style()
        style.configure("Treeview", rowheight=30)
        head_frame = ttk.Labelframe(content_panes, text=" Global Headlines & Sentiment ", padding=10)
        content_panes.add(head_frame, weight=2)
        self.news_feed = ScrolledText(head_frame, height=15, autohide=True, font=("Helvetica", 9))
        self.news_feed.pack(fill=BOTH, expand=YES)
        self.news_feed.tag_config('positive', foreground='lightgreen')
        self.news_feed.tag_config('negative', foreground='#ff6b6b')
        self.news_feed.tag_config('volatile', foreground='#feca57')
    def _force_news_refresh(self):
        self._last_news_update = 0
        self._heavy_refresh()
        self.show_toast("Refreshing News Data...", "info")
    def _update_news_ui(self):
        try:
            now = time.time()
            if now - self._last_news_update < 60:
                return
            sym = self.symbol_var.get()
            upcoming = news_manager.get_calendar_summary(sym, count=15)
            self.news_tree.delete(*self.news_tree.get_children())
            for ev in upcoming:
                impact = ev.get('impact', 'Low')
                self.news_tree.insert("", tk.END, values=(
                    ev.get('time'),
                    ev.get('currency', 'USD'),
                    impact,
                    ev.get('title'),
                    ev.get('actual', '-'),
                    ev.get('forecast', '-'),
                    ev.get('previous')
                ), tags=(impact,))
            score, summary, risks = news_manager.get_market_sentiment()
            color = "success" if score >= 3 else "danger" if score <= -3 else "info"
            self.lbl_news_sent.configure(text=f"SENTIMENT: {summary.upper()}", bootstyle=color)
            full_date = time.strftime("%A, %B %d, %Y | %H:%M:%S")
            self.lbl_news_date.configure(text=f"LAST UPDATED: {full_date}")
            status = getattr(news_manager, 'fetch_status', 'OFFLINE')
            st_color = "success" if status == "ACTIVE" else "warning" if "RATE" in status else "danger"
            self.lbl_news_status.configure(text=f"MARKET WATCH: {status}", bootstyle=st_color)
            self.news_feed.delete("1.0", tk.END)
            self.news_feed.insert(tk.END, "📢 LATEST GLOBAL THEMES:\n\n")
            for h in news_manager.headlines:
                tag = "neutral"
                h_lower = h.lower()
                if any(w in h_lower for w in ["war", "conflict", "tariff", "attack", "sanction", "tension", "strike", "escalat"]): tag = "negative"
                elif any(w in h_lower for w in ["growth", "deal", "improvement", "surge", "resolution", "bullish", "recovery"]): tag = "positive"
                elif any(w in h_lower for w in ["trump", "fed", "election", "policy"]): tag = "volatile"
                self.news_feed.insert(tk.END, f"• {h}\n\n", tag)
            self._last_news_update = now
        except Exception as e:
            logging.debug(f"News UI update error: {e}")
    def _build_settings_tab(self):
        # Settings is already using a container, let's make it scrollable like dashboard
        canvas = tk.Canvas(self.tab_settings, borderwidth=0, highlightthickness=0)
        scrollbar = ttk.Scrollbar(self.tab_settings, orient=VERTICAL, command=canvas.yview)
        container = ttk.Frame(canvas, padding=15)

        canvas.create_window((0, 0), window=container, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        
        def on_configure(e):
            canvas.configure(scrollregion=canvas.bbox("all"))
            canvas.itemconfig(canvas_win, width=e.width)

        canvas_win = canvas.create_window((0,0), window=container, anchor="nw")
        canvas.bind("<Configure>", on_configure)

        canvas.pack(side=LEFT, fill=BOTH, expand=YES)
        scrollbar.pack(side=RIGHT, fill=Y)

        # 2-Column Layout to eliminate empty space
        left_col = ttk.Frame(container)
        left_col.pack(side=LEFT, fill=BOTH, expand=YES, padx=(0, 10))
        
        right_col = ttk.Frame(container)
        right_col.pack(side=LEFT, fill=BOTH, expand=YES, padx=(10, 0))

        # --- LEFT: Strategy Selection ---
        strat_grp = ttk.Labelframe(left_col, text=" AI Strategy Intelligence Engines ", padding=15)
        strat_grp.pack(fill=BOTH, expand=YES)
        
        strat_desc = ttk.Label(strat_grp, text="Toggle specific logic engines and view recommended timeframes.", font=("Helvetica", 9, "italic"), bootstyle="secondary")
        strat_desc.pack(anchor=W, pady=(0, 15))

        strat_meta = {
            "AI_Predict": {"name": "AI Predictor (SMC)", "rec": "M5/M15"},
            "Trend": {"name": "Trend Following", "rec": "H1/H4/D1"},
            "Scalp": {"name": "Multi-TF Scalper", "rec": "Any"},
            "Breakout": {"name": "Breakout Engine", "rec": "H4/D1"},
            "TBS_Retest": {"name": "TBS Retest", "rec": "M15/M30"},
            "ICT_Master": {"name": "ICT Master", "rec": "M15/H1"},
            "TBS_Turtle": {"name": "TBS Turtle", "rec": "H1"},
            "CRT_TBS": {"name": "CRT Master", "rec": "H1/H4"},
            "PD_Parameter": {"name": "PD Array Logic", "rec": "Daily"},
            "News_Sentiment": {"name": "News Filter", "rec": "Global"},
            "Reversal": {"name": "Reversal Engine", "rec": "M15"},
            "SMC_Master": {"name": "SMC Master", "rec": "M15/H1"},
            "PowerTF": {"name": "Power of TF", "rec": "M15 Focus"}
        }

        # Grid for strategies in left column
        strat_grid = ttk.Frame(strat_grp)
        strat_grid.pack(fill=X)
        
        # Filter out keys that might not be in strat_vars to prevent crash
        active_strats = [k for k in strat_meta.keys() if k in self.strat_vars]
        
        for i, strat_key in enumerate(active_strats):
            var = self.strat_vars[strat_key]
            meta = strat_meta[strat_key]
            r, c = divmod(i, 2) # 2 columns inside the left panel
            cell = ttk.Frame(strat_grid, padding=8)
            cell.grid(row=r, column=c, sticky=NW)
            
            ttk.Checkbutton(cell, text=meta["name"], variable=var, bootstyle="round-toggle").pack(anchor=W)
            ttk.Label(cell, text=f"Best: {meta['rec']}", font=("Helvetica", 8), bootstyle="secondary").pack(anchor=W, padx=25)

        # --- RIGHT: Integration & Risk ---
        # Position Management Card
        pm_grp = ttk.Labelframe(right_col, text=" Advanced Trade Protection ", padding=15)
        pm_grp.pack(fill=X, pady=(0, 20))
        
        # Break-even
        be_frame = ttk.Frame(pm_grp)
        be_frame.pack(fill=X, pady=8)
        ttk.Checkbutton(be_frame, text="Auto Break-Even (BE)", variable=self.be_enabled_var, bootstyle="round-toggle").pack(side=LEFT)
        ttk.Label(be_frame, text="Trigger %:", font=("Helvetica", 9)).pack(side=LEFT, padx=(20, 5))
        ttk.Spinbox(be_frame, from_=10, to=90, textvariable=self.be_trigger_var, width=5).pack(side=LEFT)
        
        # Trailing
        tr_frame = ttk.Frame(pm_grp)
        tr_frame.pack(fill=X, pady=8)
        ttk.Checkbutton(tr_frame, text="Auto Trailing Stop", variable=self.trail_enabled_var, bootstyle="round-toggle").pack(side=LEFT)
        ttk.Label(tr_frame, text="Trail %:", font=("Helvetica", 9)).pack(side=LEFT, padx=(37, 5))
        ttk.Spinbox(tr_frame, from_=0.1, to=10.0, increment=0.1, textvariable=self.trail_pct_var, width=5).pack(side=LEFT)

        ttk.Button(pm_grp, text="SYNC RISK PARAMETERS", bootstyle="info-outline", command=self.update_risk_settings).pack(fill=X, pady=(10, 0))

        # Telegram Card
        tg_grp = ttk.Labelframe(right_col, text=" Secure Telegram Bridge ", padding=15)
        tg_grp.pack(fill=X)
        
        ttk.Label(tg_grp, text="Bot Token API Key:", font=("Helvetica", 8, "bold"), bootstyle="secondary").pack(anchor=W)
        ttk.Entry(tg_grp, textvariable=self.tg_token_var, show="*", width=50).pack(fill=X, pady=(5, 15))
        
        ttk.Label(tg_grp, text="Authorized Chat ID:", font=("Helvetica", 8, "bold"), bootstyle="secondary").pack(anchor=W)
        chat_f = ttk.Frame(tg_grp)
        chat_f.pack(fill=X, pady=5)
        ttk.Entry(chat_f, textvariable=self.tg_chat_var).pack(side=LEFT, fill=X, expand=YES)
        ttk.Button(chat_f, text="Test", bootstyle="info-outline", command=self.test_telegram, width=8).pack(side=LEFT, padx=(10, 0))
        
        ttk.Button(tg_grp, text="SAVE CONFIGURATION", bootstyle="primary", command=self.update_telegram).pack(fill=X, pady=(15, 0))
    def on_auto_trade_toggle(self):
        state = "ENABLED" if self.auto_trade_var.get() else "DISABLED"
        msg = f"🚀 Auto-Trading {state} - Real-Time Analysis Active" if state == "ENABLED"              else f"⏸️ Auto-Trading {state} - Switching to Manual Mode"
        logging.getLogger("Main").info(msg)
    def update_symbol(self, event=None):
        sym = self.symbol_var.get()
        if sym:
            if hasattr(self.connector, 'change_symbol'):
                self.connector.change_symbol(sym)
            if hasattr(self.connector, 'refresh_symbols'):
                self.connector.refresh_symbols()
            logging.info(f"🔄 UI Symbol Changed to {sym} – Queued for MT5, Refreshing...")
    def update_timeframe(self, event=None):
        tf_map = {"M1": 1, "M5": 5, "M15": 15, "M30": 30, "H1": 60, "H4": 240, "D1": 1440, "W1": 10080, "MN": 43200}
        minutes = tf_map.get(self.tf_var.get(), 5)
        if hasattr(self.connector, 'change_timeframe'):
            self.connector.change_timeframe(self.symbol_var.get(), minutes)
    def force_refresh(self):
        if hasattr(self.connector, 'force_sync'):
            self.connector.force_sync()
        if hasattr(self.connector, 'refresh_symbols'):
            self.connector.refresh_symbols()
        if hasattr(self.connector, 'available_symbols'):
            self.sym_combo['values'] = self.connector.available_symbols
        logging.info("🔄 Manual Refresh Triggered – Check Console for EA Response (Symbols/TF)")
    def test_telegram(self):
        if self.telegram_bot:
            self.telegram_bot.send_message("🔔 <b>Test Message</b> from MT5 Bot", self.tg_chat_var.get())
            logging.info("Sent test message to Telegram")
    def update_telegram(self):
        if self.telegram_bot:
            self.telegram_bot.token = self.tg_token_var.get()
            self.telegram_bot.chat_id = self.tg_chat_var.get()
            logging.info("Telegram credentials updated")
    
    def update_risk_settings(self):
        # Sync UI vars back to config for workers to pick up
        if not hasattr(self, 'config'): return
        if 'position_management' not in self.config: self.config['position_management'] = {}
        
        pm = self.config['position_management']
        pm['breakeven_enabled'] = self.be_enabled_var.get()
        pm['breakeven_trigger_pct'] = self.be_trigger_var.get()
        pm['trailing_stop_enabled'] = self.trail_enabled_var.get()
        pm['trailing_stop_pct'] = self.trail_pct_var.get()
        
        self.show_toast("Position Management Settings Applied", "info")
        logging.info("🛡️ Position Management parameters updated in real-time")

    def apply_be_manual(self):
        sym = self.symbol_var.get()
        def do_be():
            try:
                positions = self.connector.positions
                count = 0
                for pos in positions:
                    if pos['symbol'] == sym:
                        ticket = pos['ticket']
                        entry = pos['price']
                        pos_type = pos['type']
                        current_sl = pos['sl']
                        
                        # Apply BE - slightly better than entry to cover spread/fees if possible
                        # For forex/gold, a small offset is good
                        offset = entry * 0.0001
                        new_sl = entry + offset if pos_type == "BUY" else entry - offset
                        
                        # Only modify if it improves the SL
                        should_mod = False
                        if pos_type == "BUY" and (current_sl < entry or current_sl == 0):
                            should_mod = True
                        elif pos_type == "SELL" and (current_sl > entry or current_sl == 0):
                            should_mod = True
                            
                        if should_mod:
                            self.connector.modify_position(ticket, new_sl, pos['tp'])
                            count += 1
                
                msg = f"🛡️ BE applied to {count} positions for {sym}"
                self.after(0, lambda: self.show_toast(msg, "success"))
                logging.info(msg)
            except Exception as e:
                logging.error(f"Manual BE failed: {e}")
                
        threading.Thread(target=do_be, daemon=True).start()

    def toggle_bot(self):
        self.bot_running = not self.bot_running
        if self.bot_running:
            self.status_var.set("BOT: RUNNING")
            self.lbl_status.configure(bootstyle="success")
            if not self.bot_thread or not self.bot_thread.is_alive():
                self.bot_thread = threading.Thread(target=self.bot_loop_callback, args=(self,), daemon=True)
                self.bot_thread.start()
            logging.info("🚀 Bot Started - Real-Time Scanning Active")
        else:
            self.status_var.set("BOT: STOPPED")
            self.lbl_status.configure(bootstyle="warning")
            logging.info("⏹️ Bot Stopped")
    def manual_trade(self, action):
        try:
            vol = float(self.lot_var.get())
        except ValueError:
            vol = 0.01
        sym = self.symbol_var.get()
        btn = self._get_buy_sell_button(action)
        original_text = f"{action} MARKET"
        if btn:
            btn.configure(text=f"{action}ING...", state="disabled", bootstyle="primary")
        def send_in_background():
            try:
                if hasattr(self.connector, 'send_order'):
                    self.connector.send_order(action, sym, vol, 0, 0)
                logging.info(f"Manual {action} ({vol} lots) on {sym} - Executed")
                self.after(0, lambda: self._on_trade_success(btn, original_text, action, vol))
            except Exception as e:
                logging.error(f"Trade failed: {e}")
                self.after(0, lambda: self._on_trade_error(btn, original_text, str(e)))
        threading.Thread(target=send_in_background, daemon=True).start()
    def _get_buy_sell_button(self, action):
        if action == "BUY":
            return self.buy_btn
        elif action == "SELL":
            return self.sell_btn
        return None
    def _on_trade_success(self, btn, original_text, action, vol):
        if btn:
            btn.configure(text=original_text, state="normal", bootstyle="success-outline")
            btn.configure(bootstyle="success")
            self.after(300, lambda: btn.configure(bootstyle="success-outline"))
        self.show_toast(f"{action} Order Sent! ({vol} lots)", "success")
    def _on_trade_error(self, btn, original_text, error_msg):
        if btn:
            btn.configure(text=original_text, state="normal", bootstyle="danger-outline")
        self.show_toast(f"Trade Error: {error_msg}", "error")
    def show_toast(self, message, toast_type="info"):
        if self.toast_label:
            self.toast_label.destroy()
        self.toast_label = ttk.Label(self, text=message, bootstyle=f"{toast_type}-inverse")
        self.toast_label.place(relx=0.5, rely=0.1, anchor="center")
        def fade_out(delay=2000):
            self.after(delay, self.toast_label.destroy)
        fade_out()
    def manual_close(self, mode):
        sym = self.symbol_var.get()
        cmd = f"CLOSE_{mode}|{sym}"
        def do_close():
            try:
                if hasattr(self.connector, 'lock'):
                    with self.connector.lock:
                        self.connector.command_queue.append(cmd)
                logging.info(f"Manual Close ({mode}) request sent for {sym}")
                self.after(0, lambda: self.show_toast(f"Close {mode} Request Sent for {sym}", "info"))
            except Exception as e:
                logging.error(f"Manual close failed: {e}")
        threading.Thread(target=do_close, daemon=True).start()
    def clear_logs(self):
        self.log_area.delete(1.0, tk.END)
        self.last_logs.clear()
    def log_formatter(self, record):
        time_str = time.strftime('%H:%M:%S', time.localtime(record.created))
        # Optional: return a structured tuple to apply different tags to different parts
        return f"[{time_str}] "
    
    def _start_log_polling(self):
        batch = []
        max_batch = 15
        while len(batch) < max_batch and not self.log_queue.empty():
            try:
                record = self.log_queue.get_nowait()
                raw_msg = record.getMessage()
                now = time.time()
                
                # Deduplication logic
                should_log = True
                suppress_threshold = self.log_suppress_threshold
                for ts, prev_raw in list(self.last_logs):
                    if now - ts < suppress_threshold and prev_raw == raw_msg:
                        should_log = False
                        break
                
                if should_log:
                    self.last_logs.append((now, raw_msg))
                    time_str = time.strftime('%H:%M:%S', time.localtime(record.created))
                    batch.append((f"[{time_str}] ", "TIMESTAMP"))
                    batch.append((f"{raw_msg}\n", record.levelname))
            except queue.Empty:
                break
        
        if batch:
            for msg, tag in batch:
                self.log_area.insert(tk.END, msg, tag)
            self.log_area.see(tk.END)
            
            # Keep history manageable
            current_lines = int(self.log_area.index('end-1c').split('.')[0])
            if current_lines > 1000:
                self.log_area.delete('1.0', '200.0')
        
        self.after(100, self._start_log_polling)
    def _start_light_refresh(self):
        self._light_refresh()
        self.after(2000, self._start_light_refresh)
    def _light_refresh(self):
        if hasattr(self.connector, 'server') and self.connector.server:
            self.lbl_server.configure(text="SERVER: ONLINE", bootstyle="success-inverse")
        current_info = getattr(self.connector, 'get_account_info', lambda: self.connector.account_info)()
        if current_info != self.last_account_info:
            info = current_info
            self.lbl_acc_mode.configure(text="DEMO" if info.get('is_demo', True) else "REAL")
            self.lbl_balance.configure(text=f"${info.get('balance', 0):,.2f}")
            self.lbl_equity.configure(text=f"${info.get('equity', 0):,.2f}")
            
            prof = info.get('profit', 0.0)
            p_color = "success" if prof >= 0 else "danger"
            self.lbl_profit.configure(text=f"${prof:,.2f}", bootstyle=p_color)
            
            prof_today = info.get('prof_today', 0.0)
            t_color = "success" if (prof_today + prof) >= 0 else "danger"
            self.lbl_prof_today.configure(text=f"${prof_today:,.2f}", bootstyle=t_color)
            
            prof_week = info.get('prof_week', 0.0)
            w_color = "success" if prof_week >= 0 else "danger"
            self.lbl_prof_week.configure(text=f"${prof_week:,.2f}", bootstyle=w_color)
            
            # Update Win Rate
            win_rate = info.get('win_rate', 0.0)
            self.lbl_win_rate.configure(text=f"{win_rate:.1f}%")

            self.lbl_bid.configure(text=f"{info.get('bid', 0.0):.5f}")
            self.lbl_ask.configure(text=f"{info.get('ask', 0.0):.5f}")
            
            # Sync Server Status with color
            server_online = hasattr(self.connector, 'server') and self.connector.server
            self.lbl_server.configure(
                text="● SERVER: ONLINE" if server_online else "● SERVER: OFFLINE",
                bootstyle="success" if server_online else "danger"
            )
            self.lbl_total_count.configure(text=str(info.get('total_count', 0)))
            self.lbl_buy_count.configure(text=str(info.get('buy_count', 0)))
            self.lbl_sell_count.configure(text=str(info.get('sell_count', 0)))
            
            daily_count = getattr(self.risk, 'daily_trades_count', 0)
            self.lbl_daily_trades.configure(text=str(daily_count))
            
            self.last_account_info = current_info
        if hasattr(self.connector, 'pending_changes'):
            pending = self.connector.pending_changes
            if pending.get('symbol') and pending['symbol'] != self.symbol_var.get():
                logging.warning(f"⚠️ Pending Symbol Sync Lag: UI={self.symbol_var.get()}, Pending={pending['symbol']}")
            if pending.get('tf') and pending['tf'] != self.tf_var.get():
                logging.warning(f"⚠️ Pending TF Sync Lag: UI={self.tf_var.get()}, Pending={pending['tf']}")
    def _start_heavy_refresh(self):
        self._heavy_refresh()
        self.after(5000, self._start_heavy_refresh)
    def _heavy_refresh(self):
        if hasattr(self.connector, 'available_symbols'):
            avail_syms = self.connector.available_symbols
            if avail_syms != self.last_avail_syms:
                current_dropdown = list(self.sym_combo['values']) if self.sym_combo['values'] else []
                if sorted(current_dropdown) != sorted(avail_syms):
                    self.sym_combo['values'] = avail_syms
                    if self.symbol_var.get() not in avail_syms:
                        self.symbol_var.set(avail_syms[0])
                        self.sym_combo.set(avail_syms[0])
                        logging.info(f"🔄 Auto-selected first synced symbol: {avail_syms[0]}")
                    logging.info(f"📋 UI Dropdown Updated: {len(avail_syms)} symbols synced from MT5")
                self.last_avail_syms = avail_syms[:]
        if hasattr(self.connector, 'active_symbol'):
            ea_active = self.connector.active_symbol
            if ea_active != self.last_active_symbol:
                ui_selected = self.symbol_var.get()
                if ui_selected != ea_active:
                    logging.info(f"🤝 Sync: UI updated to MT5 active symbol: {ea_active} (was {ui_selected})")
                    self.symbol_var.set(ea_active)
                    self.sym_combo.set(ea_active)
                self.last_active_symbol = ea_active
        if hasattr(self.connector, 'active_tf'):
            ea_tf = self.connector.active_tf
            if ea_tf != self.last_active_tf:
                ui_tf = self.tf_var.get()
                if ui_tf != ea_tf:
                    logging.info(f"🤝 Sync: Primary TF set to {ea_tf} (Multi-TF AUTO scanning all timeframes)")
                    self.tf_var.set(ea_tf)
                    if hasattr(self, 'tf_combo'):
                        self.tf_combo.set(ea_tf)
                self.last_active_tf = ea_tf
        self._update_news_ui()
    def update_strategy_status(self, strat_key, action, reason):
        if hasattr(self, 'strat_ui_items') and strat_key in self.strat_ui_items:
            item = self.strat_ui_items[strat_key]
            boot_color = "secondary"
            if action == "BUY": boot_color = "success"
            elif action == "SELL": boot_color = "danger"
            elif action == "NEUTRAL": boot_color = "secondary"
            try:
                item['status'].configure(text=action, bootstyle=boot_color)
                clean_reason = str(reason).replace("TBS: ", "").replace("AI_Predict: ", "")
                short_reason = (clean_reason[:25] + '..') if len(clean_reason) > 25 else clean_reason
                item['reason'].configure(text=short_reason)
            except Exception:
                pass
    def add_signal_to_log(self, tf, strategy, action, reason):
        """Thread-safe signal logging for the UI Timeline"""
        try:
            now = datetime.now().strftime("%H:%M:%S")
            self.signal_tree.insert("", 0, values=(now, tf, strategy, action, reason), tags=(action,))
            
            # Keep history light
            if len(self.signal_tree.get_children()) > 100:
                self.signal_tree.delete(self.signal_tree.get_children()[-1])
            
            # Scroll to top to ensure visibility
            self.signal_tree.yview_moveto(0)
        except Exception as e:
            logging.debug(f"Signal Timeline update error: {e}")

    def update_scan_health(self, latency):
        color = "success" if latency < 5 else "warning" if latency < 12 else "danger"
        self.lbl_health.configure(text=f"LATENCY: {latency:.1f}s", bootstyle=color)

    def mainloop(self):
        super().mainloop()
if __name__ == "__main__":
    pass