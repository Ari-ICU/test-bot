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
        self.title("MT5 Algo Terminal")
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
        self.symbol_var = tk.StringVar(value="XAUUSD") # Default, will be overwritten by EA
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
        queue_handler = QueueHandler(self.log_queue)
        formatter = logging.Formatter('%(asctime)s | %(levelname)s | %(message)s', datefmt='%H:%M:%S')
        queue_handler.setFormatter(formatter)
        logging.getLogger().addHandler(queue_handler)

    def _build_ui(self):
        # (Same as before, abbreviated for clarity)
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
        self.tabs.add(self.tab_dashboard, text="  Dashboard  ")
        self.tabs.add(self.tab_console, text="  Live Console  ")
        self.tabs.add(self.tab_settings, text="  Settings  ")
        
        self._build_dashboard_tab()
        self._build_console_tab()
        self._build_settings_tab()

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

        stats_frame = ttk.Frame(content)
        stats_frame.pack(fill=X, pady=(0, 10))
        create_stat_card(stats_frame, "ACCOUNT MODE", "lbl_acc_mode", "secondary", "CONNECTING...")
        create_stat_card(stats_frame, "BALANCE", "lbl_balance", "primary")
        create_stat_card(stats_frame, "EQUITY", "lbl_equity", "info")
        create_stat_card(stats_frame, "FLOATING P/L", "lbl_profit", "success")

        market_frame = ttk.Frame(content)
        market_frame.pack(fill=X, pady=(0, 10))
        create_stat_card(market_frame, "BID PRICE", "lbl_bid", "warning", "0.00000")
        create_stat_card(market_frame, "ASK PRICE", "lbl_ask", "warning", "0.00000")

        pos_frame = ttk.Frame(content)
        pos_frame.pack(fill=X, pady=(0, 20))
        create_stat_card(pos_frame, "BUY POSITIONS", "lbl_buy_count", "secondary", "0")
        create_stat_card(pos_frame, "SELL POSITIONS", "lbl_sell_count", "secondary", "0")
        create_stat_card(pos_frame, "TOTAL POSITIONS", "lbl_total_count", "light", "0")

        ctrl_wrapper = ttk.Frame(content)
        ctrl_wrapper.pack(fill=BOTH, expand=YES)

        exec_frame = ttk.Labelframe(ctrl_wrapper, text=" Execution Controls ")
        exec_frame.pack(side=LEFT, fill=BOTH, expand=YES, padx=(0, 10))
        grid_frame = ttk.Frame(exec_frame)
        grid_frame.pack(fill=X, padx=20, pady=15)
        ttk.Button(grid_frame, text="BUY MARKET", bootstyle="success-outline", command=lambda: self.manual_trade("BUY")).pack(side=LEFT, fill=X, expand=YES, padx=5)
        ttk.Button(grid_frame, text="SELL MARKET", bootstyle="danger-outline", command=lambda: self.manual_trade("SELL")).pack(side=LEFT, fill=X, expand=YES, padx=5)
        close_frame = ttk.Frame(exec_frame)
        close_frame.pack(fill=X, padx=20, pady=(5, 15))
        ttk.Button(close_frame, text="CLOSE PROFIT", bootstyle="success", command=lambda: self.manual_close("WIN")).pack(side=LEFT, fill=X, expand=YES, padx=5)
        ttk.Button(close_frame, text="CLOSE LOSS", bootstyle="danger", command=lambda: self.manual_close("LOSS")).pack(side=LEFT, fill=X, expand=YES, padx=5)
        ttk.Button(close_frame, text="CLOSE ALL", bootstyle="warning", command=lambda: self.manual_close("ALL")).pack(side=LEFT, fill=X, expand=YES, padx=5)

        conf_frame = ttk.Labelframe(ctrl_wrapper, text=" Configuration ")
        conf_frame.pack(side=RIGHT, fill=BOTH, expand=YES, padx=(10, 0))
        
        auto_row = ttk.Frame(conf_frame)
        auto_row.pack(fill=X, padx=20, pady=10)
        ttk.Label(auto_row, text="Auto Trading:", font=("Helvetica", 11, "bold")).pack(side=LEFT)
        ttk.Checkbutton(auto_row, bootstyle="success-round-toggle", variable=self.auto_trade_var, text="ACTIVE", command=self.on_auto_trade_toggle).pack(side=RIGHT)

        sym_row = ttk.Frame(conf_frame)
        sym_row.pack(fill=X, padx=20, pady=5)
        ttk.Label(sym_row, text="Active Symbol:", font=("Helvetica", 10)).pack(anchor=W)
        sym_input_frame = ttk.Frame(sym_row)
        sym_input_frame.pack(fill=X, pady=2)
        self.sym_combo = ttk.Combobox(sym_input_frame, textvariable=self.symbol_var, width=15, bootstyle="secondary")
        self.sym_combo.pack(side=LEFT, fill=X, expand=YES)
        self.sym_combo.bind("<<ComboboxSelected>>", self.update_symbol)
        
        lot_row = ttk.Frame(conf_frame)
        lot_row.pack(fill=X, padx=20, pady=5)
        ttk.Label(lot_row, text="Trade Volume:", font=("Helvetica", 10)).pack(anchor=W)
        ttk.Spinbox(lot_row, from_=0.01, to=50.0, increment=0.01, textvariable=self.lot_var, width=10).pack(fill=X, pady=2)

        pos_row = ttk.Frame(conf_frame)
        pos_row.pack(fill=X, padx=20, pady=5)
        ttk.Label(pos_row, text="Max Positions:", font=("Helvetica", 10)).pack(anchor=W)
        ttk.Spinbox(pos_row, from_=1, to=100, increment=1, textvariable=self.max_pos_var, width=10).pack(fill=X, pady=2)

    def _build_console_tab(self):
        toolbar = ttk.Frame(self.tab_console)
        toolbar.pack(fill=X, padx=10, pady=10)
        ttk.Label(toolbar, text="System Logs", font=("Helvetica", 12, "bold")).pack(side=LEFT)
        ttk.Button(toolbar, text="Clear Console", bootstyle="secondary", command=self.clear_logs).pack(side=RIGHT)
        self.log_area = ScrolledText(self.tab_console, state='disabled', font=("Consolas", 10))
        self.log_area.pack(fill=BOTH, expand=YES, padx=10, pady=(0, 10))
        self.log_area.text.tag_config('INFO', foreground='#ffffff')
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
        info_grp = ttk.Labelframe(container, text=" Webhook Info ")
        info_grp.pack(fill=X, pady=10)
        ttk.Label(info_grp, text=f"Local URL: http://127.0.0.1:{self.connector.port}/telegram", font=("Consolas", 10), padding=20).pack(anchor=W)

    def on_auto_trade_toggle(self):
        state = "ENABLED" if self.auto_trade_var.get() else "DISABLED"
        logging.info(f"Auto-Trading {state}")

    def update_symbol(self, event=None):
        sym = self.symbol_var.get()
        if sym:
            self.connector.change_symbol(sym)
            logging.info(f"Changing active symbol to {sym}...")

    def test_telegram(self):
        if self.telegram_bot:
            self.telegram_bot.send_message("🔔 <b>Test Message</b> from MT5 Bot", self.tg_chat_var.get())
            logging.info("Sent test message to Telegram")

    def update_telegram(self):
        if self.telegram_bot:
            self.telegram_bot.token = self.tg_token_var.get()
            self.telegram_bot.chat_id = self.tg_chat_var.get()
            self.telegram_bot.api_url = f"https://api.telegram.org/bot{self.telegram_bot.token}"
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
        self.connector.send_order(action, sym, vol, 0, 0)
        logging.info(f"Manual {action} ({vol} lots) on {sym}")

    def manual_close(self, mode):
        sym = self.symbol_var.get()
        self.connector.close_position(sym, mode)
        logging.info(f"Manual Close ({mode}) on {sym}")

    def clear_logs(self):
        self.log_area.text.configure(state='normal')
        self.log_area.text.delete(1.0, tk.END)
        self.log_area.text.configure(state='disabled')

    def _start_log_polling(self):
        while not self.log_queue.empty():
            try:
                record = self.log_queue.get_nowait()
                msg = self.log_formatter(record)
                self.log_area.text.configure(state='normal')
                self.log_area.text.insert(tk.END, msg + "\n", record.levelname) 
                self.log_area.text.see(tk.END)
                self.log_area.text.configure(state='disabled')
            except queue.Empty:
                break
        self.after(100, self._start_log_polling)

    def log_formatter(self, record):
        time_str = time.strftime('%H:%M:%S', time.localtime(record.created))
        return f"[{time_str}] {record.getMessage()}"

    def _start_data_refresh(self):
        if self.connector.server:
            self.lbl_server.configure(text="SERVER: LISTENING", bootstyle="success-inverse")
        else:
            self.lbl_server.configure(text="SERVER: OFF", bootstyle="secondary-inverse")

        if self.connector.account_info:
            info = self.connector.account_info
            # Pull 'name' from the dict returned by the connector
            is_demo = info.get('is_demo', True)
            mode_text = "DEMO ACCOUNT" if is_demo else "REAL ACCOUNT"
            acc_name = info.get('name', "Unknown Account")
            self.lbl_acc_mode.configure(text=mode_text, bootstyle=f"secondary-inverse")
            self.lbl_balance.configure(text=f"${info.get('balance', 0):,.2f}")
            self.lbl_equity.configure(text=f"${info.get('equity', 0):,.2f}")
            prof = info.get('profit', 0)
            p_prefix = "+" if prof >= 0 else ""
            self.lbl_profit.configure(text=f"{p_prefix}${prof:,.2f}")
            
            self.lbl_bid.configure(text=f"{info.get('bid', 0.0):.5f}")
            self.lbl_ask.configure(text=f"{info.get('ask', 0.0):.5f}")
            
            self.lbl_buy_count.configure(text=str(info.get('buy_count', 0)))
            self.lbl_sell_count.configure(text=str(info.get('sell_count', 0)))
            self.lbl_total_count.configure(text=str(info.get('total_count', 0)))
            
        # --- NEW: AUTO-SYNC UI SYMBOL WITH EA ---
        if self.connector.active_symbol:
            current_ui_sym = self.symbol_var.get()
            real_ea_sym = self.connector.active_symbol
            
            # If UI is on XAUUSD (default) but EA says BTC, update UI immediately
            if current_ui_sym == "XAUUSD" and real_ea_sym != "XAUUSD":
                self.symbol_var.set(real_ea_sym)
                logging.info(f"Auto-Sync: UI updated to match EA symbol ({real_ea_sym})")

        # --- NEW: CLEAN SYMBOL LIST UPDATE ---
        if self.connector.available_symbols:
            current_values = self.sym_combo['values']
            new_values = tuple(self.connector.available_symbols)
            
            if current_values != new_values:
                self.sym_combo['values'] = new_values
                # Ensure current selection is valid
                if self.symbol_var.get() not in new_values and new_values:
                    self.symbol_var.set(new_values[0])
            
        self.after(500, self._start_data_refresh)