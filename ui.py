import time
import queue
import logging
import threading
import tkinter as tk
import ttkbootstrap as ttk
from ttkbootstrap.constants import *
from ttkbootstrap.scrolled import ScrolledText
from tkinter.font import Font

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
        self.geometry("1100x850")
        
        self.bot_loop_callback = bot_loop_callback
        self.connector = connector
        self.risk = risk_manager
        self.telegram_bot = telegram_bot
        
        self.log_queue = queue.Queue()
        self.bot_running = False
        self.bot_thread = None
        
        # UI Variables
        self.lot_var = tk.DoubleVar(value=0.01)
        self.symbol_var = tk.StringVar(value="XAUUSD")
        self.auto_trade_var = tk.BooleanVar(value=False)
        
        # Telegram Vars
        self.tg_token_var = tk.StringVar(value=self.telegram_bot.token if self.telegram_bot else "")
        self.tg_chat_var = tk.StringVar(value=self.telegram_bot.chat_id if self.telegram_bot else "")
        
        self._setup_logging()
        self._build_ui()
        self._start_log_polling()
        self._start_data_refresh()
        
        # Auto-start connection (but not trading logic until toggled)
        self.after(1000, self.toggle_bot) 

    def _setup_logging(self):
        queue_handler = QueueHandler(self.log_queue)
        formatter = logging.Formatter('%(asctime)s | %(levelname)s | %(message)s', datefmt='%H:%M:%S')
        queue_handler.setFormatter(formatter)
        logging.getLogger().addHandler(queue_handler)

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
        
        self.tabs.add(self.tab_dashboard, text="  Dashboard  ")
        self.tabs.add(self.tab_console, text="  Live Console  ")
        self.tabs.add(self.tab_settings, text="  Settings  ")
        
        self._build_dashboard_tab()
        self._build_console_tab()
        self._build_settings_tab()

    def _build_dashboard_tab(self):
        content = ttk.Frame(self.tab_dashboard)
        content.pack(fill=BOTH, expand=YES, padx=20, pady=20)
        
        # 1. Financial Stats
        stats_frame = ttk.Frame(content)
        stats_frame.pack(fill=X, pady=(0, 10))
        
        def create_stat_card(parent, title, var_name, color, initial_val="$0.00"):
            frame = ttk.Frame(parent, bootstyle=f"{color}")
            frame.pack(side=LEFT, fill=X, expand=YES, padx=5)
            inner = ttk.Frame(frame, bootstyle=f"{color}")
            inner.pack(fill=BOTH, padx=15, pady=15)
            ttk.Label(inner, text=title, font=("Helvetica", 10), bootstyle=f"{color}-inverse").pack(anchor=W)
            lbl = ttk.Label(inner, text=initial_val, font=("Roboto", 22, "bold"), bootstyle=f"{color}-inverse")
            lbl.pack(anchor=E)
            setattr(self, var_name, lbl)

        create_stat_card(stats_frame, "BALANCE", "lbl_balance", "primary")
        create_stat_card(stats_frame, "EQUITY", "lbl_equity", "info")
        create_stat_card(stats_frame, "FLOATING P/L", "lbl_profit", "success")

        # 2. Position Counts
        pos_frame = ttk.Frame(content)
        pos_frame.pack(fill=X, pady=(0, 20))
        create_stat_card(pos_frame, "BUY POSITIONS", "lbl_buy_count", "secondary", "0")
        create_stat_card(pos_frame, "SELL POSITIONS", "lbl_sell_count", "secondary", "0")
        create_stat_card(pos_frame, "TOTAL POSITIONS", "lbl_total_count", "warning", "0")

        # 3. Controls & Config Wrapper
        ctrl_wrapper = ttk.Frame(content)
        ctrl_wrapper.pack(fill=BOTH, expand=YES)

        # -- Left: Execution Controls --
        exec_frame = ttk.Labelframe(ctrl_wrapper, text=" Execution Controls ")
        exec_frame.pack(side=LEFT, fill=BOTH, expand=YES, padx=(0, 10))
        
        # Manual Buttons
        grid_frame = ttk.Frame(exec_frame)
        grid_frame.pack(fill=X, padx=20, pady=15)
        
        btn_buy = ttk.Button(grid_frame, text="BUY MARKET", bootstyle="success-outline", command=lambda: self.manual_trade("BUY"))
        btn_buy.pack(side=LEFT, fill=X, expand=YES, padx=(0, 5))
        
        btn_sell = ttk.Button(grid_frame, text="SELL MARKET", bootstyle="danger-outline", command=lambda: self.manual_trade("SELL"))
        btn_sell.pack(side=LEFT, fill=X, expand=YES, padx=(5, 5))
        
        close_frame = ttk.Frame(exec_frame)
        close_frame.pack(fill=X, padx=20, pady=(5, 15))
        
        btn_close_win = ttk.Button(close_frame, text="CLOSE PROFIT", bootstyle="success", command=lambda: self.manual_close("WIN"))
        btn_close_win.pack(side=LEFT, fill=X, expand=YES, padx=(0, 5))
        
        btn_close_loss = ttk.Button(close_frame, text="CLOSE LOSS", bootstyle="danger", command=lambda: self.manual_close("LOSS"))
        btn_close_loss.pack(side=LEFT, fill=X, expand=YES, padx=(5, 5))
        
        btn_close_all = ttk.Button(close_frame, text="CLOSE ALL", bootstyle="warning", command=lambda: self.manual_close("ALL"))
        btn_close_all.pack(side=LEFT, fill=X, expand=YES, padx=(5, 0))

        # -- Right: Configuration --
        conf_frame = ttk.Labelframe(ctrl_wrapper, text=" Configuration ")
        conf_frame.pack(side=RIGHT, fill=BOTH, expand=YES, padx=(10, 0))
        
        # Auto Trade Toggle
        auto_row = ttk.Frame(conf_frame)
        auto_row.pack(fill=X, padx=20, pady=15)
        ttk.Label(auto_row, text="Auto Trading:", font=("Helvetica", 11, "bold")).pack(side=LEFT)
        
        # Round Toggle Switch
        chk_auto = ttk.Checkbutton(auto_row, bootstyle="success-round-toggle", variable=self.auto_trade_var, text="ACTIVE", command=self.on_auto_trade_toggle)
        chk_auto.pack(side=RIGHT)

        # Symbol Changer
        sym_row = ttk.Frame(conf_frame)
        sym_row.pack(fill=X, padx=20, pady=10)
        ttk.Label(sym_row, text="Active Symbol:", font=("Helvetica", 10)).pack(anchor=W)
        
        sym_input_frame = ttk.Frame(sym_row)
        sym_input_frame.pack(fill=X, pady=5)
        
        ent_sym = ttk.Entry(sym_input_frame, textvariable=self.symbol_var, width=15)
        ent_sym.pack(side=LEFT, padx=(0, 5))
        
        btn_sym = ttk.Button(sym_input_frame, text="Set", bootstyle="info-outline", command=self.update_symbol, width=6)
        btn_sym.pack(side=LEFT)

        # Lot Size
        lot_row = ttk.Frame(conf_frame)
        lot_row.pack(fill=X, padx=20, pady=10)
        ttk.Label(lot_row, text="Trade Volume (Lot):", font=("Helvetica", 10)).pack(anchor=W)
        spin_lot = ttk.Spinbox(lot_row, from_=0.01, to=50.0, increment=0.01, textvariable=self.lot_var, width=10)
        spin_lot.pack(fill=X, pady=5)

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
        inner_info = ttk.Frame(info_grp)
        inner_info.pack(fill=X, padx=20, pady=20) 
        ttk.Label(inner_info, text=f"Local URL: http://127.0.0.1:{self.connector.port}/telegram", font=("Consolas", 10)).pack(anchor=W)

    def on_auto_trade_toggle(self):
        state = "ENABLED" if self.auto_trade_var.get() else "DISABLED"
        logging.info(f"Auto-Trading {state}")

    def update_symbol(self):
        sym = self.symbol_var.get()
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
        else:
            # We don't stop the thread, just visually indicate status
            # In a real app, you might want a graceful shutdown flag
            pass

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
            self.lbl_balance.configure(text=f"${info.get('balance', 0):,.2f}")
            self.lbl_equity.configure(text=f"${info.get('equity', 0):,.2f}")
            
            prof = info.get('profit', 0)
            p_prefix = "+" if prof >= 0 else ""
            self.lbl_profit.configure(text=f"{p_prefix}${prof:,.2f}")
            
            self.lbl_buy_count.configure(text=str(info.get('buy_count', 0)))
            self.lbl_sell_count.configure(text=str(info.get('sell_count', 0)))
            self.lbl_total_count.configure(text=str(info.get('total_count', 0)))
            
        self.after(500, self._start_data_refresh)