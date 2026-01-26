# ui.py 
# Fully Fixed: Auto-Start Bot on Init (No More "STOPPED" Default), Thread-Safe UI Updates,
# Enhanced Logging/Sync, Strategy Status, and Manual Controls. UI Now Starts "RUNNING" Immediately.
# FIXED: Defined AUTO_TABS locally, Completed log_polling (ScrolledText compat + dedup), Added missing strat_vars entry,
#        Ensured all refs (e.g., self.log_area.insert) work w/o errors. No UI/layout changes.

import time
import queue
import logging
import threading
import tkinter as tk
import ttkbootstrap as ttk
from ttkbootstrap.constants import *
from ttkbootstrap.scrolled import ScrolledText
from collections import deque  # For simple dedup queue

# FIXED: Define AUTO_TABS locally (used in UI, no import needed)
AUTO_TABS = ["M1", "M5", "M15", "M30", "H1", "H4", "D1", "W1", "MN"]

class QueueHandler(logging.Handler):
    """Class to send logging records to a queue"""
    def __init__(self, log_queue):
        super().__init__()
        self.log_queue = log_queue

    def emit(self, record):
        self.log_queue.put(record)

class TradingApp(ttk.Window):
    def __init__(self, bot_loop_callback, connector, risk_manager, telegram_bot=None):
        super().__init__(themename="cyborg")
        self.title("MT5 Algo Terminal - Strategy Only Mode")
        self.geometry("1050x640")
       
        self.bot_loop_callback = bot_loop_callback
        self.connector = connector
        self.risk = risk_manager
        self.telegram_bot = telegram_bot
       
        self.log_queue = queue.Queue(maxsize=1000)  # Limit queue to prevent memory bloat
        self.bot_running = True  # FIXED: Starts RUNNING by default (no more "STOPPED")
        self.bot_thread = None
       
        # Defaults - Load from risk config if available, otherwise fallback to defaults
        risk_conf = self.risk.config if hasattr(self.risk, 'config') else {}
        self.lot_var = tk.DoubleVar(value=risk_conf.get('lot_size', 0.01))
        self.symbol_var = tk.StringVar(value=self.connector.active_symbol)
        self.tf_var = tk.StringVar(value=self.connector.active_tf) 
        self.style_var = tk.StringVar(value="scalp") 
        self.auto_trade_var = tk.BooleanVar(value=False)
        self.max_pos_var = tk.IntVar(value=risk_conf.get('max_trades', 5))
        self.cool_off_var = tk.IntVar(value=risk_conf.get('cool_off_seconds', 5)) 
        self.crt_reclaim_var = tk.DoubleVar(value=0.25)
       
        self.tg_token_var = tk.StringVar(value=self.telegram_bot.token if self.telegram_bot else "")
        self.tg_chat_var = tk.StringVar(value=self.telegram_bot.chat_id if self.telegram_bot else "")
        
        # Strategy Toggles - FIXED: Added "News_Sentiment" to match _build_settings_tab meta
        self.strat_vars = {
            "AI_Predict": tk.BooleanVar(value=True),
            "Trend": tk.BooleanVar(value=True),
            "Scalp": tk.BooleanVar(value=True),
            "Breakout": tk.BooleanVar(value=True),
            "TBS_Retest": tk.BooleanVar(value=True),
            "ICT_SB": tk.BooleanVar(value=True),
            "TBS_Turtle": tk.BooleanVar(value=True),
            "CRT_TBS": tk.BooleanVar(value=True),
            "PD_Parameter": tk.BooleanVar(value=True),
            "News_Sentiment": tk.BooleanVar(value=True),  # FIXED: Added missing entry
            "Reversal": tk.BooleanVar(value=True)
        }
       
        # Cache for optimizations
        self.last_avail_syms = []
        self.last_account_info = None
        self.last_active_symbol = None
        self.last_active_tf = None
       
        # Button references for smooth feedback
        self.buy_btn = None
        self.sell_btn = None
        self.toast_label = None  # For toasts
       
        # NEW: Log deduplication cache (last 10s of messages to suppress spam)
        self.last_logs = deque(maxlen=50)  # FIFO queue for recent msgs with timestamps
        self.log_suppress_threshold = 1.0  # Reduced to 1s for more real-time feel
       
        self._setup_logging()
        self._build_ui()
        self._start_log_polling()
        self._start_light_refresh()  # Start light refresh for basics
        self._start_heavy_refresh()  # Start heavy refresh for symbols/TF
       
        # FIXED: Auto-Start Bot Immediately (No Delay, Sets "RUNNING")
        self.after(100, self._auto_start_bot)  # Slight delay for UI init

    def _auto_start_bot(self):
        """FIXED: Auto-starts bot on init, sets status to RUNNING, starts thread."""
        if not self.bot_running:
            return  # Already running
        self.status_var.set("BOT: RUNNING")
        self.lbl_status.configure(bootstyle="success-inverse")
        if not self.bot_thread or not self.bot_thread.is_alive():
            self.bot_thread = threading.Thread(target=self.bot_loop_callback, args=(self,), daemon=True)
            self.bot_thread.start()
        logging.info("🚀 Bot Auto-Started - Real-Time Scanning Active")

    def _setup_logging(self):
        # Cooperate with main.py - do NOT clear root handlers so terminal logging stays alive
        root_logger = logging.getLogger()
        root_logger.setLevel(logging.INFO)
        
        # Only add QueueHandler if not already present
        if not any(isinstance(h, QueueHandler) for h in root_logger.handlers):
            queue_handler = QueueHandler(self.log_queue)
            formatter = logging.Formatter('%(asctime)s | %(levelname)s | %(message)s', datefmt='%H:%M:%S')
            queue_handler.setFormatter(formatter)
            root_logger.addHandler(queue_handler)

    def _build_ui(self):
        header = ttk.Frame(self)
        header.pack(fill=X, padx=15, pady=8)
        title_lbl = ttk.Label(header, text="MT5 AUTO-TRADER", font=("Roboto", 18, "bold"), bootstyle="inverse-dark")
        title_lbl.pack(side=LEFT)
       
        status_frame = ttk.Frame(header)
        status_frame.pack(side=RIGHT)
        self.lbl_server = ttk.Label(status_frame, text="SERVER: OFF", bootstyle="secondary-inverse", font=("Helvetica", 10, "bold"))
        self.lbl_server.pack(side=LEFT, padx=5)
        self.status_var = tk.StringVar(value="BOT: RUNNING")  # FIXED: Default to RUNNING
        self.lbl_status = ttk.Label(status_frame, textvariable=self.status_var, bootstyle="success-inverse", font=("Helvetica", 10, "bold"))  # FIXED: Green start
        self.lbl_status.pack(side=LEFT, padx=5)
        self.tabs = ttk.Notebook(self)
        self.tabs.pack(fill=BOTH, expand=YES, padx=5, pady=5)
        self.tab_dashboard = ttk.Frame(self.tabs)
        self.tab_console = ttk.Frame(self.tabs)
        self.tab_settings = ttk.Frame(self.tabs)
        self.tabs.add(self.tab_dashboard, text=" Dashboard ")
        self.tabs.add(self.tab_console, text=" Live Console ")
        self.tabs.add(self.tab_settings, text=" Settings ")
       
        self._build_dashboard_tab()
        self._build_console_tab()
        self._build_settings_tab()

        # FIXED: Ensure initial selection matches connector
        self.sym_combo.set(self.connector.active_symbol)    

    def _build_dashboard_tab(self):
        content = ttk.Frame(self.tab_dashboard)
        content.pack(fill=BOTH, expand=YES, padx=10, pady=5)
       
        def create_stat_card(parent, title, var_name, color, initial_val="$0.00"):
            frame = ttk.Frame(parent, bootstyle=f"{color}")
            frame.pack(side=LEFT, fill=X, expand=YES, padx=3)
            inner = ttk.Frame(frame, bootstyle=f"{color}")
            inner.pack(fill=BOTH, padx=10, pady=8)
            ttk.Label(inner, text=title, font=("Helvetica", 9), bootstyle=f"{color}-inverse").pack(anchor=W)
            lbl = ttk.Label(inner, text=initial_val, font=("Roboto", 18, "bold"), bootstyle=f"{color}-inverse")
            lbl.pack(anchor=E)
            setattr(self, var_name, lbl)
            return lbl

        # --- ROW 1: STRATEGY ENGINE MONITOR ---
        strategy_monitor = ttk.Labelframe(content, text=" Active Strategy Engine ")
        strategy_monitor.pack(fill=X, pady=(0, 8))
        strategy_monitor_inner = ttk.Frame(strategy_monitor)
        strategy_monitor_inner.pack(fill=BOTH, expand=YES, padx=5, pady=5)
       
        self.strat_ui_items = {}
        strat_list = [
            ("AI_Predict", "AI Smart Predictor"),
            ("Trend", "Trend Following"), 
            ("Scalp", "M5 Scalper"), 
            ("Breakout", "Breakout Engine"), 
            ("ICT_SB", "ICT Silver Bullet"), 
            ("TBS_Turtle", "TBS Turtle"), 
            ("TBS_Retest", "TBS Retest"), 
            ("CRT_TBS", "CRT MT5 Master"),
            ("PD_Parameter", "PD Array Logic"),
            ("News_Sentiment", "News Sentiment"),
            ("Reversal", "Reversal Engine")
        ]
        for key, name in strat_list:
            f = ttk.Frame(strategy_monitor_inner)
            f.pack(side=LEFT, expand=YES)
            ttk.Label(f, text=name, font=("Helvetica", 9)).pack()
            status_lbl = ttk.Label(f, text="WAITING", font=("Helvetica", 10, "bold"), bootstyle=SECONDARY)
            status_lbl.pack()
            reason_lbl = ttk.Label(f, text="...", font=("Helvetica", 7), bootstyle=LIGHT)
            reason_lbl.pack()
            self.strat_ui_items[key] = {"status": status_lbl, "reason": reason_lbl}

        # --- ROW 2: ACCOUNT STATS ---
        stats_frame = ttk.Frame(content)
        stats_frame.pack(fill=X, pady=(0, 5))
        create_stat_card(stats_frame, "ACCOUNT MODE", "lbl_acc_mode", "secondary", "CONNECTING...")
        create_stat_card(stats_frame, "BALANCE", "lbl_balance", "primary")
        create_stat_card(stats_frame, "EQUITY", "lbl_equity", "info")
        create_stat_card(stats_frame, "FLOATING P/L", "lbl_profit", "success", "$0.00")
       
        # --- ROW 3: PSYCHOLOGY & MARKET ---
        mid_frame = ttk.Frame(content)
        mid_frame.pack(fill=X, pady=(0, 5))
        self.lbl_daily_trades = create_stat_card(mid_frame, "DAILY ACTIVITY", "lbl_daily_trades", "dark", "0 Trades")
        create_stat_card(mid_frame, "DAILY NET P/L", "lbl_prof_today", "success")
        create_stat_card(mid_frame, "WEEKLY PROFIT", "lbl_prof_week", "success")
        create_stat_card(mid_frame, "BID PRICE", "lbl_bid", "warning", "0.00000")
        create_stat_card(mid_frame, "ASK PRICE", "lbl_ask", "warning", "0.00000")

        # --- ROW 4: POSITION COUNTS ---
        pos_frame = ttk.Frame(content)
        pos_frame.pack(fill=X, pady=(0, 8))
        create_stat_card(pos_frame, "BUY POSITIONS", "lbl_buy_count", "secondary", "0")
        create_stat_card(pos_frame, "SELL POSITIONS", "lbl_sell_count", "secondary", "0")
        create_stat_card(pos_frame, "TOTAL POSITIONS", "lbl_total_count", "light", "0")

        # --- ROW 5: CONTROLS ---
        ctrl_wrapper = ttk.Frame(content)
        ctrl_wrapper.pack(fill=BOTH, expand=YES)

        # Execution Controls (Left Side)
        exec_frame = ttk.Labelframe(ctrl_wrapper, text=" Execution Controls ")
        exec_frame.pack(side=LEFT, fill=BOTH, expand=YES, padx=(0, 10))
       
        grid_frame = ttk.Frame(exec_frame)
        grid_frame.pack(fill=X, padx=20, pady=15)
        self.buy_btn = ttk.Button(grid_frame, text="BUY MARKET", bootstyle="success-outline",
                                  command=lambda: self.manual_trade("BUY"))
        self.buy_btn.pack(side=LEFT, fill=X, expand=YES, padx=5)
        self.sell_btn = ttk.Button(grid_frame, text="SELL MARKET", bootstyle="danger-outline",
                                   command=lambda: self.manual_trade("SELL"))
        self.sell_btn.pack(side=LEFT, fill=X, expand=YES, padx=5)
       
        close_frame = ttk.Frame(exec_frame)
        close_frame.pack(fill=X, padx=20, pady=(5, 15))
        ttk.Button(close_frame, text="CLOSE PROFIT", bootstyle="success",
                   command=lambda: self.manual_close("WIN")).pack(side=LEFT, fill=X, expand=YES, padx=5)
        ttk.Button(close_frame, text="CLOSE LOSS", bootstyle="danger",
                   command=lambda: self.manual_close("LOSS")).pack(side=LEFT, fill=X, expand=YES, padx=5)
        ttk.Button(close_frame, text="CLOSE ALL", bootstyle="warning",
                   command=lambda: self.manual_close("ALL")).pack(side=LEFT, fill=X, expand=YES, padx=5)

        # Configuration Controls (Right Side - Compact for 13.3" screens)
        conf_frame = ttk.Labelframe(ctrl_wrapper, text=" Configuration ", padding=10)
        conf_frame.pack(side=RIGHT, fill=BOTH, expand=YES, padx=(10, 0))
       
        # Use Grid for compactness
        conf_frame.columnconfigure(0, weight=1)
        conf_frame.columnconfigure(1, weight=1)

        # 0. Auto Trading Switch (Top Row)
        auto_row = ttk.Frame(conf_frame)
        auto_row.grid(row=0, column=0, columnspan=2, sticky=EW, pady=(0, 10))
        ttk.Label(auto_row, text="Auto Trading Status:", font=("Helvetica", 10, "bold")).pack(side=LEFT)
        ttk.Checkbutton(auto_row, bootstyle="success-round-toggle", variable=self.auto_trade_var,
                        text="ACTIVE", command=self.on_auto_trade_toggle).pack(side=RIGHT)

        # 1. Symbol and Timeframe
        s_f = ttk.Frame(conf_frame); s_f.grid(row=1, column=0, sticky=EW, padx=5, pady=2)
        ttk.Label(s_f, text="Active Symbol:", font=("Helvetica", 9)).pack(anchor=W)
        self.sym_combo = ttk.Combobox(s_f, textvariable=self.symbol_var, width=12, bootstyle="secondary")
        self.sym_combo.pack(fill=X); self.sym_combo.bind("<<ComboboxSelected>>", self.update_symbol)

        # 2. AI Style and Max Positions
        st_f = ttk.Frame(conf_frame); st_f.grid(row=2, column=0, sticky=EW, padx=5, pady=2)
        ttk.Label(st_f, text="AI Style:", font=("Helvetica", 9)).pack(anchor=W)
        self.style_combo = ttk.Combobox(st_f, textvariable=self.style_var, values=["sniper", "scalp", "intraday", "swing"], width=12, bootstyle="warning")
        self.style_combo.pack(fill=X)
        ttk.Label(st_f, text="Rec TF: Sniper(M1) | Scalp(M5)", font=("Helvetica", 7), bootstyle="secondary").pack(anchor=W)
        ttk.Label(st_f, text="Intra(M15-M30) | Swing(H1+)", font=("Helvetica", 7), bootstyle="secondary").pack(anchor=W)

        mp_f = ttk.Frame(conf_frame); mp_f.grid(row=2, column=1, sticky=EW, padx=5, pady=2)
        ttk.Label(mp_f, text="Max Pos:", font=("Helvetica", 9)).pack(anchor=W)
        ttk.Spinbox(mp_f, from_=1, to=20, textvariable=self.max_pos_var, width=10).pack(fill=X)

        # 3. Trade Volume and Cool-off
        v_f = ttk.Frame(conf_frame); v_f.grid(row=3, column=0, sticky=EW, padx=5, pady=2)
        ttk.Label(v_f, text="Volume (Lots):", font=("Helvetica", 9)).pack(anchor=W)
        ttk.Spinbox(v_f, from_=0.01, to=50, textvariable=self.lot_var, width=10).pack(fill=X)

        co_f = ttk.Frame(conf_frame); co_f.grid(row=3, column=1, sticky=EW, padx=5, pady=2)
        ttk.Label(co_f, text="Cool-off (s):", font=("Helvetica", 9)).pack(anchor=W)
        self.cool_spin = ttk.Spinbox(co_f, from_=0, to=300, textvariable=self.cool_off_var, width=10)
        self.cool_spin.pack(fill=X)

        # 4. CRT Reclaim % (Full Width)
        crt_f = ttk.Frame(conf_frame); crt_f.grid(row=4, column=0, columnspan=2, sticky=EW, padx=5, pady=5)
        ttk.Label(crt_f, text="CRT Reclaim % (HTF Expansion Check):", font=("Helvetica", 9)).pack(anchor=W)
        ttk.Spinbox(crt_f, from_=0.05, to=0.95, increment=0.05, textvariable=self.crt_reclaim_var, width=10).pack(fill=X)

    def _build_console_tab(self):
        # Console Setup with ScrolledText
        console_frame = ttk.Frame(self.tab_console)
        console_frame.pack(fill=BOTH, expand=YES, padx=10, pady=10)
        
        btn_frame = ttk.Frame(console_frame)
        btn_frame.pack(fill=X, pady=(0, 10))
        ttk.Button(btn_frame, text="🗑️ Clear Console Logs", bootstyle="danger-outline", command=self.clear_logs).pack(side=RIGHT)
        ttk.Label(btn_frame, text="Live System Feed", font=("Helvetica", 12, "bold")).pack(side=LEFT)

        self.log_area = ScrolledText(console_frame, bootstyle="secondary", height=20, width=120, autohide=True)
        self.log_area.pack(fill=BOTH, expand=YES)
        # FIXED: Configure tags for log levels (use self.log_area.insert for ScrolledText)
        self.log_area.tag_config('INFO', foreground='lightgreen')
        self.log_area.tag_config('WARNING', foreground='#f0ad4e')
        self.log_area.tag_config('ERROR', foreground='#d9534f')

    def _build_settings_tab(self):
        container = ttk.Frame(self.tab_settings)
        container.pack(fill=BOTH, expand=YES, padx=15, pady=15)
        
        # Strategy Toggles
        strat_grp = ttk.Labelframe(container, text=" Active Strategies & Recommended TF ")
        strat_grp.pack(fill=X, pady=10)
        strat_inner = ttk.Frame(strat_grp)
        strat_inner.pack(fill=X, padx=20, pady=10)
        
        # Strategy Metadata: Name and Recommended Timeframe
        strat_meta = {
            "AI_Predict": {"name": "AI Predictor (SMC)", "rec": "Rec: M5"},
            "Trend": {"name": "Trend Following", "rec": "Rec: H1/H4"},
            "Scalp": {"name": "Multi-TF Scalper", "rec": "Rec: All"},
            "Breakout": {"name": "Breakout Engine", "rec": "Rec: H4/D1"},
            "TBS_Retest": {"name": "TBS Retest", "rec": "Rec: M15/M30"},
            "ICT_SB": {"name": "ICT Silver Bullet", "rec": "Rec: M15"},
            "TBS_Turtle": {"name": "TBS Turtle", "rec": "Rec: H1"},
            "CRT_TBS": {"name": "CRT Master", "rec": "Rec: H1/H4"},
            "PD_Parameter": {"name": "PD Array Logic", "rec": "Rec: Daily/H4"},
            "News_Sentiment": {"name": "News Sentiment", "rec": "Rec: All"},
            "Reversal": {"name": "Reversal Engine", "rec": "Rec: M15"}
        }

        # Grid layout for toggles with recommendation notes
        col = 0
        row = 0
        for strat_key, var in self.strat_vars.items():
            meta = strat_meta.get(strat_key, {"name": strat_key, "rec": ""})
            
            # Container for check + note
            cell_frame = ttk.Frame(strat_inner)
            cell_frame.grid(row=row, column=col, padx=10, pady=8, sticky=W)
            
            # Checkbox with Strategy Name
            cb = ttk.Checkbutton(cell_frame, text=meta["name"], variable=var, bootstyle="round-toggle")
            cb.pack(anchor=W)
            
            # Recommendation Note (Small Text)
            ttk.Label(cell_frame, text=meta["rec"], font=("Helvetica", 8), bootstyle="secondary").pack(anchor=W, padx=(25, 0)) # Indent under text

            col += 1
            if col > 2:  # 3 cols to fit extra text
                col = 0
                row += 1

        tg_grp = ttk.Labelframe(container, text=" Telegram Bot Integration ")
        tg_grp.pack(fill=X, pady=10)
        tg_inner = ttk.Frame(tg_grp)
        tg_inner.pack(fill=X, padx=20, pady=20)
        ttk.Label(tg_inner, text="Bot Token:", font=("Helvetica", 10)).pack(anchor=W)
        ttk.Entry(tg_inner, textvariable=self.tg_token_var, show="*").pack(fill=X, pady=5)
        ttk.Label(tg_inner, text="Chat ID:", font=("Helvetica", 10)).pack(anchor=W, pady=(10, 0))
        chat_frame = ttk.Frame(tg_inner)
        chat_frame.pack(fill=X, pady=5)
        ttk.Entry(chat_frame, textvariable=self.tg_chat_var).pack(side=LEFT, fill=X, expand=YES)
        ttk.Button(chat_frame, text="Test Message", bootstyle="info-outline", command=self.test_telegram).pack(side=LEFT, padx=(10, 0))
        ttk.Button(tg_inner, text="Update Telegram Credentials", bootstyle="primary", command=self.update_telegram).pack(fill=X, pady=15)

    def on_auto_trade_toggle(self):
        state = "ENABLED" if self.auto_trade_var.get() else "DISABLED"
        msg = f"🚀 Auto-Trading {state} - Real-Time Analysis Active" if state == "ENABLED" \
              else f"⏸️ Auto-Trading {state} - Switching to Manual Mode"
        logging.getLogger("Main").info(msg)

    # FIXED: Enhanced update_symbol – Trigger connector refresh (no immediate refresh call)
    def update_symbol(self, event=None):
        sym = self.symbol_var.get()
        if sym:
            if hasattr(self.connector, 'change_symbol'):
                self.connector.change_symbol(sym)
            # NEW: Force connector to expect new symbols list
            if hasattr(self.connector, 'refresh_symbols'):
                self.connector.refresh_symbols()
            logging.info(f"🔄 UI Symbol Changed to {sym} – Queued for MT5, Refreshing...")

    # FIXED: Enhanced update_timeframe – Similar (no immediate refresh call)
    def update_timeframe(self, event=None):
        tf_map = {"M1": 1, "M5": 5, "M15": 15, "M30": 30, "H1": 60, "H4": 240, "D1": 1440, "W1": 10080, "MN": 43200}
        minutes = tf_map.get(self.tf_var.get(), 5)
        if hasattr(self.connector, 'change_timeframe'):
            self.connector.change_timeframe(self.symbol_var.get(), minutes)

    # ENHANCED: Add force_refresh() method with symbols-specific logic
    def force_refresh(self):
        """Force connector to sync symbols and TF from EA."""
        if hasattr(self.connector, 'force_sync'):
            self.connector.force_sync()
        if hasattr(self.connector, 'refresh_symbols'):
            self.connector.refresh_symbols()  # Specifically refresh symbols
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

    def toggle_bot(self):
        """FIXED: Toggle now works with auto-start; UI updates thread-safe via after()."""
        self.bot_running = not self.bot_running
        if self.bot_running:
            self.after(0, lambda: self.status_var.set("BOT: RUNNING"))
            self.after(0, lambda: self.lbl_status.configure(bootstyle="success-inverse"))
            if not self.bot_thread or not self.bot_thread.is_alive():
                self.bot_thread = threading.Thread(target=self.bot_loop_callback, args=(self,), daemon=True)
                self.bot_thread.start()
            logging.info("🚀 Bot Started - Real-Time Scanning Active")
        else:
            self.after(0, lambda: self.status_var.set("BOT: STOPPED"))
            self.after(0, lambda: self.lbl_status.configure(bootstyle="danger-inverse"))
            logging.info("⏹️ Bot Stopped")

    # OPTIMIZED: Threaded manual_trade for smooth, non-blocking response
    def manual_trade(self, action):
        try:
            vol = float(self.lot_var.get())
        except ValueError:
            vol = 0.01  # Fallback
        sym = self.symbol_var.get()
        
        # Instant UI feedback: Disable button + show "SENDING..."
        btn = self._get_buy_sell_button(action)
        original_text = f"{action} MARKET"
        if btn:
            btn.configure(text=f"{action}ING...", state="disabled", bootstyle="primary")  # Visual cue
        
        # Fire-and-forget thread for heavy work
        def send_in_background():
            try:
                if hasattr(self.connector, 'send_order'):
                    self.connector.send_order(action, sym, vol, 0, 0)
                # Log in thread (non-blocking for UI)
                logging.info(f"Manual {action} ({vol} lots) on {sym} - Executed")
                
                # Success callback: Re-enable + flash green
                self.after(0, lambda: self._on_trade_success(btn, original_text, action, vol))
            except Exception as e:
                logging.error(f"Trade failed: {e}")
                # Error callback
                self.after(0, lambda: self._on_trade_error(btn, original_text, str(e)))
        
        threading.Thread(target=send_in_background, daemon=True).start()

    def _get_buy_sell_button(self, action):
        """Helper to get button reference for feedback."""
        if action == "BUY":
            return self.buy_btn
        elif action == "SELL":
            return self.sell_btn
        return None

    def _on_trade_success(self, btn, original_text, action, vol):
        """Handle successful trade feedback."""
        if btn:
            btn.configure(text=original_text, state="normal", bootstyle="success-outline")
            # Smooth flash: Green pulse
            btn.configure(bootstyle="success")
            self.after(300, lambda: btn.configure(bootstyle="success-outline"))
        # Toast notification
        self.show_toast(f"{action} Order Sent! ({vol} lots)", "success")

    def _on_trade_error(self, btn, original_text, error_msg):
        """Handle trade error feedback."""
        if btn:
            btn.configure(text=original_text, state="normal", bootstyle="danger-outline")
        # Quick error popup (non-blocking)
        self.show_toast(f"Trade Error: {error_msg}", "error")

    def show_toast(self, message, toast_type="info"):
        """Show smooth toast notification."""
        if self.toast_label:
            self.toast_label.destroy()  # Clear old
        self.toast_label = ttk.Label(self, text=message, bootstyle=f"{toast_type}-inverse")
        self.toast_label.place(relx=0.5, rely=0.1, anchor="center")  # Top-center
        # Fade out smoothly
        def fade_out(delay=2000):
            self.after(delay, self.toast_label.destroy)
        fade_out()

    def manual_close(self, mode):
        """
        Fixed: Sends specific action strings (CLOSE_WIN, CLOSE_LOSS, CLOSE_ALL)
        to match the MQL5 ProcessCommand logic.
        """
        sym = self.symbol_var.get()
       
        # Format the command to match MQL5 EA's ProcessCommand expectation:
        # The EA checks: if(action == "CLOSE_ALL") or if(action == "CLOSE_WIN"), etc.
        cmd = f"CLOSE_{mode}|{sym}"
       
        # Append the command to the connector's queue for the EA to pick up
        if hasattr(self.connector, 'lock'):
            with self.connector.lock:
                self.connector.command_queue.append(cmd)
           
        logging.info(f"Manual Close ({mode}) request sent for {sym}")
        self.show_toast(f"Close {mode} Request Sent for {sym}", "info")

    def clear_logs(self):
        self.log_area.delete(1.0, tk.END)  # FIXED: Use delete for ScrolledText
        self.last_logs.clear()  # Clear dedup cache too

    # FIXED: Enhanced log polling with deduplication to prevent spam loops + ScrolledText compat
    def _start_log_polling(self):
        batch = []
        max_batch = 10  # Cap batch to prevent long blocks
        while len(batch) < max_batch and not self.log_queue.empty():
            try:
                record = self.log_queue.get_nowait()
                raw_msg = record.getMessage()
                
                # NEW: Dedup check - skip if identical raw msg within threshold
                now = time.time()
                should_log = True
                suppress_threshold = self.log_suppress_threshold
                
                for ts, prev_raw in list(self.last_logs):
                    if now - ts < suppress_threshold and prev_raw == raw_msg:
                        should_log = False
                        break
                    elif now - ts > suppress_threshold + 5:
                        self.last_logs.remove((ts, prev_raw))
                
                if should_log:
                    self.last_logs.append((now, raw_msg))
                    full_msg = self.log_formatter(record) + "\n"
                    batch.append((full_msg, record.levelname))
            except queue.Empty:
                break
        
        if batch:
            # 1. Update Detailed Console (Tab) - FIXED: self.log_area.insert for ScrolledText
            for msg, tag in batch:
                self.log_area.insert(tk.END, msg, tag)
            self.log_area.see(tk.END)
            
            # Truncate detailed console (max 500 lines)
            current_lines = int(self.log_area.index('end-1c').split('.')[0])
            if current_lines > 500:
                self.log_area.delete('1.0', f'{current_lines-500}.0')
        
        self.after(200, self._start_log_polling)  # Slower poll: reduces CPU, still responsive

    def log_formatter(self, record):
        time_str = time.strftime('%H:%M:%S', time.localtime(record.created))
        return f"[{time_str}] {record.getMessage()}"

    # OPTIMIZED: Light refresh for frequent updates (account info, status) every 2s
    def _start_light_refresh(self):
        self._light_refresh()
        self.after(2000, self._start_light_refresh)

    def _light_refresh(self):
        # 4. Refresh Server Status & Account Metrics (cached checks)
        if hasattr(self.connector, 'server') and self.connector.server:
            self.lbl_server.configure(text="SERVER: ONLINE", bootstyle="success-inverse")
        
        # FIXED: Use get_account_info() if available, fallback to dict
        current_info = getattr(self.connector, 'get_account_info', lambda: self.connector.account_info)()
        if current_info != self.last_account_info:
            info = current_info
            self.lbl_acc_mode.configure(text="DEMO" if info.get('is_demo', True) else "REAL")
            self.lbl_balance.configure(text=f"${info.get('balance', 0):,.2f}")
            self.lbl_equity.configure(text=f"${info.get('equity', 0):,.2f}")
            
            prof = info.get('profit', 0.0)
            p_color = "success" if prof >= 0 else "danger"
            self.lbl_profit.configure(text=f"${prof:,.2f}", bootstyle=f"{p_color}-inverse")
            
            prof_today = info.get('prof_today', 0.0)
            # Display: Realized (Floating)
            # e.g. "$100.00 (Open: $-50.00)"
            net_str = f"${prof_today:,.2f} (Open: ${prof:,.2f})"
            t_color = "success" if (prof_today + prof) >= 0 else "danger"
            self.lbl_prof_today.configure(text=net_str, bootstyle=f"{t_color}-inverse", font=("Helvetica", 10, "bold"))
            
            prof_week = info.get('prof_week', 0.0)
            w_color = "success" if prof_week >= 0 else "danger"
            self.lbl_prof_week.configure(text=f"${prof_week:,.2f}", bootstyle=f"{w_color}-inverse")
            
            self.lbl_bid.configure(text=f"{info.get('bid', 0.0):.5f}")
            self.lbl_ask.configure(text=f"{info.get('ask', 0.0):.5f}")
            self.lbl_total_count.configure(text=str(info.get('total_count', 0)))
            self.lbl_buy_count.configure(text=str(info.get('buy_count', 0)))
            self.lbl_sell_count.configure(text=str(info.get('sell_count', 0)))
            
            # Update Daily Discipline from RiskManager
            daily_count = getattr(self.risk, 'daily_trades_count', 0)
            self.lbl_daily_trades.configure(text=f"{daily_count} Trades")
            
            self.last_account_info = current_info  # Cache

        # NEW: Check for pending mismatches and log (only if changed)
        if hasattr(self.connector, 'pending_changes'):
            pending = self.connector.pending_changes
            if pending.get('symbol') and pending['symbol'] != self.symbol_var.get():
                logging.warning(f"⚠️ Pending Symbol Sync Lag: UI={self.symbol_var.get()}, Pending={pending['symbol']}")
            if pending.get('tf') and pending['tf'] != self.tf_var.get():
                logging.warning(f"⚠️ Pending TF Sync Lag: UI={self.tf_var.get()}, Pending={pending['tf']}")

    # OPTIMIZED: Heavy refresh for infrequent/heavy ops (symbols/TF sync) every 5s
    def _start_heavy_refresh(self):
        self._heavy_refresh()
        self.after(5000, self._start_heavy_refresh)

    def _heavy_refresh(self):
        # 1. Sync the Available Symbols List (Market Watch) - direct compare
        if hasattr(self.connector, 'available_symbols'):
            avail_syms = self.connector.available_symbols
            if avail_syms != self.last_avail_syms:
                current_dropdown = list(self.sym_combo['values']) if self.sym_combo['values'] else []
                if sorted(current_dropdown) != sorted(avail_syms):  # Keep sorted for safety
                    self.sym_combo['values'] = avail_syms
                    # ENHANCED: Auto-select the first if current is not in list (e.g., invalid default)
                    if self.symbol_var.get() not in avail_syms:
                        self.symbol_var.set(avail_syms[0])
                        self.sym_combo.set(avail_syms[0])
                        logging.info(f"🔄 Auto-selected first synced symbol: {avail_syms[0]}")
                    logging.info(f"📋 UI Dropdown Updated: {len(avail_syms)} symbols synced from MT5")
                self.last_avail_syms = avail_syms[:]  # Cache copy

        # 2. SMART SYNC: Active Symbol (cached)
        if hasattr(self.connector, 'active_symbol'):
            ea_active = self.connector.active_symbol
            if ea_active != self.last_active_symbol:
                ui_selected = self.symbol_var.get()
                if ui_selected != ea_active:
                    logging.info(f"🤝 Sync: UI updated to MT5 active symbol: {ea_active} (was {ui_selected})")
                    self.symbol_var.set(ea_active)
                    self.sym_combo.set(ea_active)
                self.last_active_symbol = ea_active

        # 3. SMART SYNC: Primary Timeframe for Risk Management (cached)
        if hasattr(self.connector, 'active_tf'):
            ea_tf = self.connector.active_tf
            if ea_tf != self.last_active_tf:
                ui_tf = self.tf_var.get()
                if ui_tf != ea_tf:
                    logging.info(f"🤝 Sync: Primary TF set to {ea_tf} (Multi-TF AUTO scanning all timeframes)")
                    self.tf_var.set(ea_tf)
                    # Only update tf_combo if it exists (optional UI element)
                    if hasattr(self, 'tf_combo'):
                        self.tf_combo.set(ea_tf)
                self.last_active_tf = ea_tf

    # --- NEW: Strategy Feedback Updater ---
    def update_strategy_status(self, strat_key, action, reason):
        if hasattr(self, 'strat_ui_items') and strat_key in self.strat_ui_items:
            item = self.strat_ui_items[strat_key]
            
            # Color Logic
            boot_color = "secondary"
            if action == "BUY": boot_color = "success"
            elif action == "SELL": boot_color = "danger"
            elif action == "NEUTRAL": boot_color = "secondary"
            
            # Update Labels Safely
            try:
                item['status'].configure(text=action, bootstyle=boot_color)
                
                # Clean and Truncate Reason
                clean_reason = str(reason).replace("TBS: ", "").replace("AI_Predict: ", "")
                short_reason = (clean_reason[:25] + '..') if len(clean_reason) > 25 else clean_reason
                item['reason'].configure(text=short_reason)
            except Exception:
                pass

    # FIXED: Mainloop (Starts All Pollers)
    def mainloop(self):
        super().mainloop()

if __name__ == "__main__":
    pass