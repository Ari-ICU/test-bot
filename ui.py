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
    def __init__(self, bot_loop_callback, connector, risk_manager):
        super().__init__(themename="cyborg")
        self.title("MT5 Algo Terminal")
        self.geometry("1100x750")
        
        self.bot_loop_callback = bot_loop_callback
        self.connector = connector
        self.risk = risk_manager
        
        self.log_queue = queue.Queue()
        self.bot_running = False
        self.bot_thread = None
        
        # Variable for Manual Lot Size
        self.lot_var = tk.DoubleVar(value=0.01)
        
        self._setup_logging()
        self._build_ui()
        self._start_log_polling()
        self._start_data_refresh()
        
        # --- AUTO START ---
        self.after(1000, self.toggle_bot) 

    def _setup_logging(self):
        queue_handler = QueueHandler(self.log_queue)
        formatter = logging.Formatter('%(asctime)s | %(levelname)s | %(message)s', datefmt='%H:%M:%S')
        queue_handler.setFormatter(formatter)
        logging.getLogger().addHandler(queue_handler)

    def _build_ui(self):
        # --- Top Header Bar ---
        header = ttk.Frame(self)
        header.pack(fill=X, padx=20, pady=15)
        
        # Title
        title_lbl = ttk.Label(header, text="MT5 AUTO-TRADER", font=("Roboto", 20, "bold"), bootstyle="inverse-dark")
        title_lbl.pack(side=LEFT)
        
        # Status Badges
        status_frame = ttk.Frame(header)
        status_frame.pack(side=RIGHT)
        
        self.lbl_server = ttk.Label(status_frame, text="SERVER: OFF", bootstyle="secondary-inverse", font=("Helvetica", 10, "bold"))
        self.lbl_server.pack(side=LEFT, padx=5)

        self.status_var = tk.StringVar(value="BOT: STOPPED")
        self.lbl_status = ttk.Label(status_frame, textvariable=self.status_var, bootstyle="danger-inverse", font=("Helvetica", 10, "bold"))
        self.lbl_status.pack(side=LEFT, padx=5)

        # --- Main Tabs ---
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
        
        # 1. Stats Row
        stats_frame = ttk.Frame(content)
        stats_frame.pack(fill=X, pady=(0, 20))
        
        def create_stat_card(parent, title, var_name, color):
            frame = ttk.Frame(parent, bootstyle=f"{color}")
            frame.pack(side=LEFT, fill=X, expand=YES, padx=5)
            
            inner = ttk.Frame(frame, bootstyle=f"{color}")
            inner.pack(fill=BOTH, padx=15, pady=15)
            
            ttk.Label(inner, text=title, font=("Helvetica", 10), bootstyle=f"{color}-inverse").pack(anchor=W)
            lbl = ttk.Label(inner, text="$0.00", font=("Roboto", 22, "bold"), bootstyle=f"{color}-inverse")
            lbl.pack(anchor=E)
            setattr(self, var_name, lbl)

        create_stat_card(stats_frame, "BALANCE", "lbl_balance", "primary")
        create_stat_card(stats_frame, "EQUITY", "lbl_equity", "info")
        create_stat_card(stats_frame, "PROFIT (SESSION)", "lbl_profit", "success")

        # 2. Controls Section
        ctrl_frame = ttk.Labelframe(content, text=" Execution Controls ")
        ctrl_frame.pack(fill=BOTH, expand=YES, pady=10)
        
        # --- Lot Size Configuration ---
        config_row = ttk.Frame(ctrl_frame)
        config_row.pack(fill=X, padx=20, pady=(15, 5))
        
        ttk.Label(config_row, text="Manual Lot Size:", font=("Helvetica", 10)).pack(side=LEFT)
        
        # Spinbox for Lot Size
        spin_lot = ttk.Spinbox(config_row, from_=0.01, to=50.0, increment=0.01, textvariable=self.lot_var, width=10, bootstyle="secondary")
        spin_lot.pack(side=LEFT, padx=10)
        
        # --- Manual Buttons ---
        grid_frame = ttk.Frame(ctrl_frame)
        grid_frame.pack(fill=X, padx=20, pady=10)
        
        # Buy / Sell Buttons
        btn_buy = ttk.Button(grid_frame, text="BUY MARKET", bootstyle="success-outline", command=lambda: self.manual_trade("BUY"))
        btn_buy.pack(side=LEFT, fill=X, expand=YES, padx=(0, 5))
        
        btn_sell = ttk.Button(grid_frame, text="SELL MARKET", bootstyle="danger-outline", command=lambda: self.manual_trade("SELL"))
        btn_sell.pack(side=LEFT, fill=X, expand=YES, padx=(5, 5))
        
        # --- Closing Buttons Row ---
        close_frame = ttk.Frame(ctrl_frame)
        close_frame.pack(fill=X, padx=20, pady=(5, 15))
        
        btn_close_win = ttk.Button(close_frame, text="CLOSE PROFIT", bootstyle="success", command=lambda: self.manual_close("WIN"))
        btn_close_win.pack(side=LEFT, fill=X, expand=YES, padx=(0, 5))
        
        btn_close_loss = ttk.Button(close_frame, text="CLOSE LOSING", bootstyle="danger", command=lambda: self.manual_close("LOSS"))
        btn_close_loss.pack(side=LEFT, fill=X, expand=YES, padx=(5, 5))
        
        btn_close_all = ttk.Button(close_frame, text="CLOSE ALL", bootstyle="warning", command=lambda: self.manual_close("ALL"))
        btn_close_all.pack(side=LEFT, fill=X, expand=YES, padx=(5, 0))

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
        
        info_grp = ttk.Labelframe(container, text=" Webhook Configuration ")
        info_grp.pack(fill=X, pady=10)
        
        inner_info = ttk.Frame(info_grp)
        inner_info.pack(fill=X, padx=20, pady=20) 
        
        ttk.Label(inner_info, text="Webhook URL (TradingView):", font=("Helvetica", 10)).pack(anchor=W)
        
        url_frame = ttk.Frame(inner_info)
        url_frame.pack(fill=X, pady=5)
        
        url_val = f"http://127.0.0.1:{self.connector.port}/webhook"
        entry = ttk.Entry(url_frame, bootstyle="dark")
        entry.insert(0, url_val)
        entry.configure(state="readonly")
        entry.pack(side=LEFT, fill=X, expand=YES)
        
        ttk.Label(inner_info, text="JSON Payload Format:", font=("Helvetica", 10)).pack(anchor=W, pady=(15, 0))
        
        code_box = ttk.Text(inner_info, height=4, font=("Consolas", 9), foreground="#cccccc", background="#2b2b2b", relief="flat")
        code_box.insert("1.0", '{\n  "action": "BUY",\n  "symbol": "XAUUSD",\n  "volume": 0.01\n}')
        code_box.configure(state="disabled")
        code_box.pack(fill=X, pady=5)

        risk_grp = ttk.Labelframe(container, text=" Risk Management ")
        risk_grp.pack(fill=X, pady=20)
        
        inner_risk = ttk.Frame(risk_grp)
        inner_risk.pack(fill=X, padx=20, pady=20)
        
        ttk.Label(inner_risk, text="Risk settings are loaded from config.json", bootstyle="secondary").pack(anchor=W)

    # --- Logic ---

    def toggle_bot(self):
        if not self.bot_running:
            self.bot_running = True
            self.status_var.set("BOT: RUNNING")
            self.lbl_status.configure(bootstyle="success-inverse")
            
            self.bot_thread = threading.Thread(target=self.bot_loop_callback, args=(self,), daemon=True)
            self.bot_thread.start()
            logging.info("Auto-Trading session started automatically.")
        else:
            self.bot_running = False
            self.status_var.set("BOT: STOPPED")
            self.lbl_status.configure(bootstyle="danger-inverse")
            logging.info("Auto-Trading session stopped.")

    def manual_trade(self, action):
        try:
            # Get volume from spinbox
            vol = float(self.lot_var.get())
        except ValueError:
            vol = 0.01
            
        self.connector.send_order(action, "XAUUSD", vol, 0, 0)
        logging.info(f"Manual {action} ({vol} lots) command sent to Bridge.")

    def manual_close(self, mode):
        # mode can be "ALL", "WIN", or "LOSS"
        self.connector.close_position("XAUUSD", mode)
        logging.info(f"Manual Close ({mode}) command sent.")

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
            
            bal = info.get('balance', 0)
            eq = info.get('equity', 0)
            prof = info.get('profit', 0)
            
            self.lbl_balance.configure(text=f"${bal:,.2f}")
            self.lbl_equity.configure(text=f"${eq:,.2f}")
            
            p_prefix = "+" if prof >= 0 else ""
            self.lbl_profit.configure(text=f"{p_prefix}${prof:,.2f}")
            
        self.after(500, self._start_data_refresh)