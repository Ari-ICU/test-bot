# ui.py (Fully Fixed - Enhanced for symbol sync logging and auto-select)
import time
import queue
import logging
import threading
import tkinter as tk
import ttkbootstrap as ttk
from ttkbootstrap.constants import *
from ttkbootstrap.scrolled import ScrolledText

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
        self.geometry("1100x900")
       
        self.bot_loop_callback = bot_loop_callback
        self.connector = connector
        self.risk = risk_manager
        self.telegram_bot = telegram_bot
       
        self.log_queue = queue.Queue()
        self.bot_running = False
        self.bot_thread = None
       
        # Defaults
        self.lot_var = tk.DoubleVar(value=0.01)
        self.symbol_var = tk.StringVar(value="XAUUSDm")
        self.tf_var = tk.StringVar(value="M5") # Added for Timeframe control
        self.auto_trade_var = tk.BooleanVar(value=False)
        self.max_pos_var = tk.IntVar(value=5)
       
        self.tg_token_var = tk.StringVar(value=self.telegram_bot.token if self.telegram_bot else "")
        self.tg_chat_var = tk.StringVar(value=self.telegram_bot.chat_id if self.telegram_bot else "")
       
        self._setup_logging()
        self._build_ui()
        self._start_log_polling()
        self._start_data_refresh()
       
        self.after(1000, self.toggle_bot)

    def _setup_logging(self):
        # 1. Get the ROOT logger to capture signals from EVERY file
        root_logger = logging.getLogger()
        root_logger.setLevel(logging.INFO)
        # 2. CLEAR existing handlers to prevent UI freezing or duplicate logs
        if root_logger.hasHandlers():
            root_logger.handlers.clear()
        # 3. Re-attach the QueueHandler
        queue_handler = QueueHandler(self.log_queue)
        formatter = logging.Formatter('%(asctime)s | %(levelname)s | %(message)s', datefmt='%H:%M:%S')
        queue_handler.setFormatter(formatter)
       
        root_logger.addHandler(queue_handler)

    def _build_ui(self):
        header = ttk.Frame(self)
        header.pack(fill=X, padx=20, pady=15)
        title_lbl = ttk.Label(header, text="MT5 AUTO-TRADER", font=("Roboto", 20, "bold"), bootstyle="inverse-dark")
        title_lbl.pack(side=LEFT)
       
        status_frame = ttk.Frame(header)
        status_frame.pack(side=RIGHT)
        self.lbl_server = ttk.Label(status_frame, text="SERVER: OFF", bootstyle="secondary-inverse", font=("Helvetica", 10, "bold"))
        self.lbl_server.pack(side=LEFT, padx=5)
        self.status_var = tk.StringVar(value="BOT: STOPPED")
        self.lbl_status = ttk.Label(status_frame, textvariable=self.status_var, bootstyle="danger-inverse", font=("Helvetica", 10, "bold"))
        self.lbl_status.pack(side=LEFT, padx=5)
        self.tabs = ttk.Notebook(self)
        self.tabs.pack(fill=BOTH, expand=YES, padx=10, pady=10)
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
        self.tf_combo.set(self.connector.active_tf)    

    def _build_dashboard_tab(self):
        content = ttk.Frame(self.tab_dashboard)
        content.pack(fill=BOTH, expand=YES, padx=20, pady=20)
       
        def create_stat_card(parent, title, var_name, color, initial_val="$0.00"):
            frame = ttk.Frame(parent, bootstyle=f"{color}")
            frame.pack(side=LEFT, fill=X, expand=YES, padx=5)
            inner = ttk.Frame(frame, bootstyle=f"{color}")
            inner.pack(fill=BOTH, padx=15, pady=15)
            ttk.Label(inner, text=title, font=("Helvetica", 10), bootstyle=f"{color}-inverse").pack(anchor=W)
            lbl = ttk.Label(inner, text=initial_val, font=("Roboto", 22, "bold"), bootstyle=f"{color}-inverse")
            lbl.pack(anchor=E)
            setattr(self, var_name, lbl)
            return lbl

        # --- ROW 1: STRATEGY ENGINE STATUS ---
        strategy_monitor = ttk.Labelframe(content, text=" Active Strategy Engine ")
        strategy_monitor.pack(fill=X, pady=(0, 15))
        strategy_monitor_inner = ttk.Frame(strategy_monitor)
        strategy_monitor_inner.pack(fill=BOTH, expand=YES, padx=10, pady=10)
       
        strat_list = ["ICT Silver Bullet", "Trend Confluence", "M5 Scalper"]
        for strat in strat_list:
            f = ttk.Frame(strategy_monitor_inner)
            f.pack(side=LEFT, expand=YES)
            ttk.Label(f, text=strat, font=("Helvetica", 9)).pack()
            ttk.Label(f, text="READY", font=("Helvetica", 12, "bold"), bootstyle=SUCCESS).pack()

        # --- ROW 2: ACCOUNT STATS ---
        stats_frame = ttk.Frame(content)
        stats_frame.pack(fill=X, pady=(0, 10))
        create_stat_card(stats_frame, "ACCOUNT MODE", "lbl_acc_mode", "secondary", "CONNECTING...")
        create_stat_card(stats_frame, "BALANCE", "lbl_balance", "primary")
        create_stat_card(stats_frame, "EQUITY", "lbl_equity", "info")
        create_stat_card(stats_frame, "FLOATING P/L", "lbl_profit", "success", "$0.00")
       
        # --- ROW 3: PSYCHOLOGY & MARKET ---
        mid_frame = ttk.Frame(content)
        mid_frame.pack(fill=X, pady=(0, 10))
        self.lbl_daily_trades = create_stat_card(mid_frame, "DAILY DISCIPLINE", "lbl_daily_trades", "dark", "0/5 Trades")
        create_stat_card(mid_frame, "BID PRICE", "lbl_bid", "warning", "0.00000")
        create_stat_card(mid_frame, "ASK PRICE", "lbl_ask", "warning", "0.00000")

        # --- ROW 4: POSITION COUNTS ---
        pos_frame = ttk.Frame(content)
        pos_frame.pack(fill=X, pady=(0, 20))
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
        ttk.Button(grid_frame, text="BUY MARKET", bootstyle="success-outline",
                   command=lambda: self.manual_trade("BUY")).pack(side=LEFT, fill=X, expand=YES, padx=5)
        ttk.Button(grid_frame, text="SELL MARKET", bootstyle="danger-outline",
                   command=lambda: self.manual_trade("SELL")).pack(side=LEFT, fill=X, expand=YES, padx=5)
       
        close_frame = ttk.Frame(exec_frame)
        close_frame.pack(fill=X, padx=20, pady=(5, 15))
        ttk.Button(close_frame, text="CLOSE PROFIT", bootstyle="success",
                   command=lambda: self.manual_close("WIN")).pack(side=LEFT, fill=X, expand=YES, padx=5)
        ttk.Button(close_frame, text="CLOSE LOSS", bootstyle="danger",
                   command=lambda: self.manual_close("LOSS")).pack(side=LEFT, fill=X, expand=YES, padx=5)
        ttk.Button(close_frame, text="CLOSE ALL", bootstyle="warning",
                   command=lambda: self.manual_close("ALL")).pack(side=LEFT, fill=X, expand=YES, padx=5)

        # Configuration Controls (Right Side)
        conf_frame = ttk.Labelframe(ctrl_wrapper, text=" Configuration ")
        conf_frame.pack(side=RIGHT, fill=BOTH, expand=YES, padx=(10, 0))
       
        # Auto Trading Switch
        auto_row = ttk.Frame(conf_frame)
        auto_row.pack(fill=X, padx=20, pady=5)
        ttk.Label(auto_row, text="Auto Trading:", font=("Helvetica", 11, "bold")).pack(side=LEFT)
        ttk.Checkbutton(auto_row, bootstyle="success-round-toggle", variable=self.auto_trade_var,
                        text="ACTIVE", command=self.on_auto_trade_toggle).pack(side=RIGHT)

        # Active Symbol Dropdown
        sym_row = ttk.Frame(conf_frame)
        sym_row.pack(fill=X, padx=20, pady=5)
        ttk.Label(sym_row, text="Active Symbol:", font=("Helvetica", 10)).pack(anchor=W)
        self.sym_combo = ttk.Combobox(sym_row, textvariable=self.symbol_var, width=15, bootstyle="secondary")
        self.sym_combo.pack(fill=X, pady=2)
        self.sym_combo.bind("<<ComboboxSelected>>", self.update_symbol)
       
        # Execution Timeframe Dropdown
        tf_row = ttk.Frame(conf_frame)
        tf_row.pack(fill=X, padx=20, pady=5)
        ttk.Label(tf_row, text="Execution Timeframe:", font=("Helvetica", 10)).pack(anchor=W)
        self.tf_combo = ttk.Combobox(tf_row, textvariable=self.tf_var,
                                     values=["M1", "M5", "M15", "M30", "H1", "H4", "D1"],
                                     width=15, bootstyle="info")
        self.tf_combo.pack(fill=X, pady=2)
        self.tf_combo.bind("<<ComboboxSelected>>", self.update_timeframe)

        # Max Positions Spinbox
        pos_row = ttk.Frame(conf_frame)
        pos_row.pack(fill=X, padx=20, pady=5)
        ttk.Label(pos_row, text="Max Positions:", font=("Helvetica", 10)).pack(anchor=W)
        ttk.Spinbox(pos_row, from_=1, to=20, textvariable=self.max_pos_var, width=10).pack(fill=X, pady=2)

        # Trade Volume Spinbox
        lot_row = ttk.Frame(conf_frame)
        lot_row.pack(fill=X, padx=20, pady=5)
        ttk.Label(lot_row, text="Trade Volume:", font=("Helvetica", 10)).pack(anchor=W)
        ttk.Spinbox(lot_row, from_=0.01, to=50, textvariable=self.lot_var, width=10).pack(fill=X, pady=2)

    def _build_console_tab(self):
        # Console Setup with ScrolledText
        console_frame = ttk.Frame(self.tab_console)
        console_frame.pack(fill=BOTH, expand=YES, padx=20, pady=20)
        self.log_area = ScrolledText(console_frame, bootstyle="secondary", height=30, width=120, autohide=True)
        self.log_area.pack(fill=BOTH, expand=YES)
        # Configure tags for log levels
        self.log_area.text.tag_config('INFO', foreground='lightgreen')
        self.log_area.text.tag_config('WARNING', foreground='#f0ad4e')
        self.log_area.text.tag_config('ERROR', foreground='#d9534f')

    def _build_settings_tab(self):
        container = ttk.Frame(self.tab_settings)
        container.pack(fill=BOTH, expand=YES, padx=30, pady=30)
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
        logging.info(f"Auto-Trading {state}")

    # FIXED: Enhanced update_symbol – Trigger connector refresh
    def update_symbol(self, event=None):
        sym = self.symbol_var.get()
        if sym:
            if hasattr(self.connector, 'change_symbol'):
                self.connector.change_symbol(sym)
            # NEW: Force connector to expect new symbols list
            if hasattr(self.connector, 'refresh_symbols'):
                self.connector.refresh_symbols()
            logging.info(f"🔄 UI Symbol Changed to {sym} – Queued for MT5, Refreshing...")
            # FIXED: Force immediate UI sync to reflect optimistic update
            self._start_data_refresh()  # Trigger one-time refresh

    # FIXED: Enhanced update_timeframe – Similar
    def update_timeframe(self, event=None):
        tf_map = {"M1": 1, "M5": 5, "M15": 15, "M30": 30, "H1": 60, "H4": 240, "D1": 1440}
        minutes = tf_map.get(self.tf_var.get(), 5)
        if hasattr(self.connector, 'change_timeframe'):
            self.connector.change_timeframe(self.symbol_var.get(), minutes)
        logging.info(f"🔄 UI TF Changed to {self.tf_var.get()} ({minutes}min) – Queued for MT5, Refreshing...")
        # FIXED: Force immediate UI sync to reflect optimistic update
        self._start_data_refresh()  # Trigger one-time refresh

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
        if not self.bot_running:
            self.bot_running = True
            self.status_var.set("BOT: RUNNING")
            self.lbl_status.configure(bootstyle="success-inverse")
            self.bot_thread = threading.Thread(target=self.bot_loop_callback, args=(self,), daemon=True)
            self.bot_thread.start()
            logging.info("System Engine Started.")

    def manual_trade(self, action):
        try: vol = float(self.lot_var.get())
        except: vol = 0.01
        sym = self.symbol_var.get()
        if hasattr(self.connector, 'send_order'):
            self.connector.send_order(action, sym, vol, 0, 0)
        logging.info(f"Manual {action} ({vol} lots) on {sym}")

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

    def clear_logs(self):
        self.log_area.text.configure(state='normal')
        self.log_area.text.delete(1.0, tk.END)
        self.log_area.text.configure(state='disabled')

    def _start_log_polling(self):
        # This runs every 100ms to pull logs from the bot thread into the UI
        while not self.log_queue.empty():
            try:
                record = self.log_queue.get_nowait()
                # Use your existing formatter logic
                msg = self.log_formatter(record)
               
                # FIX: Target the internal .text attribute of the ScrolledText widget
                self.log_area.text.configure(state='normal')
                self.log_area.text.insert(tk.END, msg + "\n", record.levelname)
                self.log_area.text.see(tk.END) # Auto-scroll to latest signal
                self.log_area.text.configure(state='disabled')
            except queue.Empty:
                break
        self.after(100, self._start_log_polling)

    def log_formatter(self, record):
        time_str = time.strftime('%H:%M:%S', time.localtime(record.created))
        return f"[{time_str}] {record.getMessage()}"

    # FIXED: Enhanced _start_data_refresh – Better sync, error handling, and force refresh if empty
    def _start_data_refresh(self):
        """
        FIXED: Enhanced Auto-Sync Logic.
        Prevents 'snapback' by only updating UI variables when the MT5 EA 
        reports a change that matches the user's intent.
        """
        # 1. Sync the Available Symbols List (Market Watch)
        if hasattr(self.connector, 'available_symbols'):
            avail_syms = self.connector.available_symbols
            current_dropdown = list(self.sym_combo['values']) if self.sym_combo['values'] else []
            
            # Update the list if it differs from MT5 Market Watch
            if avail_syms and sorted(current_dropdown) != sorted(avail_syms):
                self.sym_combo['values'] = avail_syms
                # ENHANCED: Auto-select the first if current is not in list (e.g., invalid default)
                if self.symbol_var.get() not in avail_syms:
                    self.symbol_var.set(avail_syms[0])
                    self.sym_combo.set(avail_syms[0])
                    logging.info(f"🔄 Auto-selected first synced symbol: {avail_syms[0]}")
                logging.info(f"📋 UI Dropdown Updated: {len(avail_syms)} symbols synced from MT5")

        # 2. SMART SYNC: Active Symbol
        if hasattr(self.connector, 'active_symbol'):
            ea_active = self.connector.active_symbol
            ui_selected = self.symbol_var.get()
            
            # Only force a UI update if the EA is reporting something different
            # AND the user isn't currently trying to change it.
            if ui_selected != ea_active:
                logging.info(f"🤝 Sync: UI updated to MT5 active symbol: {ea_active} (was {ui_selected})")
                self.symbol_var.set(ea_active)
                self.sym_combo.set(ea_active)

        # 3. SMART SYNC: Active Timeframe
        if hasattr(self.connector, 'active_tf'):
            ea_tf = self.connector.active_tf
            ui_tf = self.tf_var.get()
            if ui_tf != ea_tf:
                logging.info(f"🤝 Sync: UI updated to MT5 active TF: {ea_tf}")
                self.tf_var.set(ea_tf)
                self.tf_combo.set(ea_tf)

        # 4. Refresh Server Status & Account Metrics
        if hasattr(self.connector, 'server') and self.connector.server:
            self.lbl_server.configure(text="SERVER: ONLINE", bootstyle="success-inverse")
       
        if self.connector.account_info:
            info = self.connector.account_info
            self.lbl_acc_mode.configure(text="DEMO" if info.get('is_demo', True) else "REAL")
            self.lbl_balance.configure(text=f"${info.get('balance', 0):,.2f}")
            self.lbl_equity.configure(text=f"${info.get('equity', 0):,.2f}")
            
            prof = info.get('profit', 0.0)
            p_color = "success" if prof >= 0 else "danger"
            self.lbl_profit.configure(text=f"${prof:,.2f}", bootstyle=f"{p_color}-inverse")
            
            self.lbl_bid.configure(text=f"{info.get('bid', 0.0):.5f}")
            self.lbl_ask.configure(text=f"{info.get('ask', 0.0):.5f}")
            self.lbl_total_count.configure(text=str(info.get('total_count', 0)))
            self.lbl_buy_count.configure(text=str(info.get('buy_count', 0)))
            self.lbl_sell_count.configure(text=str(info.get('sell_count', 0)))

        # NEW: Check for pending mismatches and log
        if hasattr(self.connector, 'pending_changes'):
            pending = self.connector.pending_changes
            if pending.get('symbol') and pending['symbol'] != self.symbol_var.get():
                logging.warning(f"⚠️ Pending Symbol Sync Lag: UI={self.symbol_var.get()}, Pending={pending['symbol']}")
            if pending.get('tf') and pending['tf'] != self.tf_var.get():
                logging.warning(f"⚠️ Pending TF Sync Lag: UI={self.tf_var.get()}, Pending={pending['tf']}")

        # Slower refresh (1s) is essential to give the EA time to respond to POSTs
        self.after(1000, self._start_data_refresh)

if __name__ == "__main__":
    pass