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
    def __init__(self, bot_loop_callback, connector, risk_manager):
        super().__init__(themename="darkly")
        self.title("MT5 Python Bot & Webhook Manager")
        self.geometry("1100x750")
        
        self.bot_loop_callback = bot_loop_callback
        self.connector = connector
        self.risk = risk_manager
        
        self.log_queue = queue.Queue()
        self.bot_running = False
        self.bot_thread = None
        
        self._setup_logging()
        self._create_layout()
        self._start_log_polling()
        self._start_data_refresh()

    def _setup_logging(self):
        # Add queue handler to root logger
        queue_handler = QueueHandler(self.log_queue)
        # Format: Time - Level - Message
        formatter = logging.Formatter('%(asctime)s %(levelname)s: %(message)s', datefmt='%H:%M:%S')
        queue_handler.setFormatter(formatter)
        logging.getLogger().addHandler(queue_handler)

    def _create_layout(self):
        # --- Header ---
        header = ttk.Frame(self, padding=10)
        header.pack(fill=X)
        
        ttk.Label(header, text="MT5 Algo Trading & Webhook Bridge", font=("Helvetica", 18, "bold"), bootstyle="primary").pack(side=LEFT)
        
        # Status indicators
        status_frame = ttk.Frame(header)
        status_frame.pack(side=RIGHT)

        self.lbl_server = ttk.Label(status_frame, text="HTTP Server: OFF", bootstyle="secondary")
        self.lbl_server.pack(side=RIGHT, padx=10)
        
        self.status_var = tk.StringVar(value="BOT STOPPED")
        self.lbl_status = ttk.Label(status_frame, textvariable=self.status_var, font=("Helvetica", 12, "bold"), bootstyle="danger")
        self.lbl_status.pack(side=RIGHT)
        
        # --- Main Content (Panedwindow) ---
        pane = ttk.Panedwindow(self, orient=HORIZONTAL)
        pane.pack(fill=BOTH, expand=YES, padx=10, pady=10)
        
        # Left Side: Controls & Data
        left_frame = ttk.Frame(pane, padding=10)
        pane.add(left_frame, weight=1)
        
        # 1. Account Info Card
        info_frame = ttk.LabelFrame(left_frame, text="Account Info") 
        info_frame.pack(fill=X, pady=5)
        
        self.lbl_balance = ttk.Label(info_frame, text="Balance: $0.00", font=("Consolas", 12))
        self.lbl_balance.pack(anchor=W, padx=10, pady=(10, 2))
        self.lbl_equity = ttk.Label(info_frame, text="Equity:  $0.00", font=("Consolas", 12))
        self.lbl_equity.pack(anchor=W, padx=10, pady=2)
        self.lbl_profit = ttk.Label(info_frame, text="Profit:  $0.00", font=("Consolas", 12), bootstyle="success")
        self.lbl_profit.pack(anchor=W, padx=10, pady=(2, 10))

        # 2. Controls Card
        ctrl_frame = ttk.LabelFrame(left_frame, text="Bot Controls")
        ctrl_frame.pack(fill=X, pady=10)
        
        self.btn_start = ttk.Button(ctrl_frame, text="START BOT", bootstyle="success", command=self.toggle_bot)
        self.btn_start.pack(fill=X, padx=10, pady=(15, 5))
        
        ttk.Separator(ctrl_frame).pack(fill=X, pady=10, padx=5)
        
        ttk.Label(ctrl_frame, text="Manual Execution", font=("Helvetica", 10, "bold")).pack(anchor=W, padx=10)
        
        btn_grid = ttk.Frame(ctrl_frame)
        btn_grid.pack(fill=X, pady=5, padx=10)
        
        ttk.Button(btn_grid, text="BUY", bootstyle="success-outline", command=lambda: self.manual_trade("BUY")).pack(side=LEFT, fill=X, expand=YES, padx=2)
        ttk.Button(btn_grid, text="SELL", bootstyle="danger-outline", command=lambda: self.manual_trade("SELL")).pack(side=LEFT, fill=X, expand=YES, padx=2)
        
        ttk.Button(ctrl_frame, text="CLOSE ALL POSITIONS", bootstyle="warning", command=lambda: self.manual_close("ALL")).pack(fill=X, padx=10, pady=(5, 15))

        # 3. Webhook Info
        web_frame = ttk.LabelFrame(left_frame, text="Webhook Config")
        web_frame.pack(fill=X, pady=10)
        
        url_text = f"http://127.0.0.1:{self.connector.port}/webhook"
        
        url_ent = ttk.Entry(web_frame, bootstyle="secondary")
        url_ent.insert(0, url_text)
        url_ent.configure(state="readonly")
        url_ent.pack(fill=X, padx=10, pady=(10, 5))
        
        ttk.Label(web_frame, text='Payload: {"action": "BUY", "symbol": "XAUUSD"}', font=("Consolas", 8), bootstyle="secondary").pack(anchor=W, padx=10, pady=(0, 10))

        # Right Side: Logs
        log_container = ttk.Frame(pane) 
        pane.add(log_container, weight=3)
        
        log_header = ttk.Frame(log_container)
        log_header.pack(fill=X, pady=(0, 5))
        
        ttk.Label(log_header, text="System Logs", font=("Helvetica", 10, "bold")).pack(side=LEFT)
        ttk.Button(log_header, text="Clear Logs", bootstyle="secondary-outline", command=self.clear_logs, width=10).pack(side=RIGHT)
        
        log_frame = ttk.LabelFrame(log_container, text="") 
        log_frame.pack(fill=BOTH, expand=YES)

        self.log_area = ScrolledText(log_frame, state='disabled', font=("Consolas", 9), height=30)
        self.log_area.pack(fill=BOTH, expand=YES, padx=2, pady=2)
        
        # FIX: Added .text here
        self.log_area.text.tag_config('INFO', foreground='#ffffff')        
        self.log_area.text.tag_config('WARNING', foreground='#f0ad4e')     
        self.log_area.text.tag_config('ERROR', foreground='#d9534f')       
        self.log_area.text.tag_config('DEBUG', foreground='#5bc0de')       

    def toggle_bot(self):
        if not self.bot_running:
            self.bot_running = True
            self.status_var.set("BOT RUNNING")
            self.lbl_status.configure(bootstyle="success")
            self.btn_start.configure(text="STOP BOT", bootstyle="danger")
            
            self.bot_thread = threading.Thread(target=self.bot_loop_callback, args=(self,), daemon=True)
            self.bot_thread.start()
            logging.info("Bot logic thread started.")
        else:
            self.bot_running = False
            self.status_var.set("BOT STOPPED")
            self.lbl_status.configure(bootstyle="danger")
            self.btn_start.configure(text="START BOT", bootstyle="success")
            logging.info("Stopping bot logic...")

    def manual_trade(self, action):
        vol = self.risk.get_lot_size(1000)
        self.connector.send_order(action, "XAUUSD", vol, 0, 0)
        logging.info(f"Manual {action} command sent.")

    def manual_close(self, mode):
        self.connector.close_position("XAUUSD", mode)
        logging.info("Manual Close All command sent.")
        
    def clear_logs(self):
        # FIX: Added .text here
        self.log_area.text.configure(state='normal')
        self.log_area.text.delete(1.0, tk.END)
        self.log_area.text.configure(state='disabled')

    def _start_log_polling(self):
        while not self.log_queue.empty():
            try:
                record = self.log_queue.get_nowait()
                msg = self.log_formatter(record)
                
                # FIX: Added .text here for all operations
                self.log_area.text.configure(state='normal')
                self.log_area.text.insert(tk.END, msg + "\n", record.levelname) 
                self.log_area.text.see(tk.END)
                self.log_area.text.configure(state='disabled')
            except queue.Empty:
                break
        self.after(100, self._start_log_polling)

    def log_formatter(self, record):
        time_str = time.strftime('%H:%M:%S', time.localtime(record.created))
        return f"[{time_str}] [{record.levelname}] {record.getMessage()}"

    def _start_data_refresh(self):
        if self.connector.server:
            self.lbl_server.configure(text="HTTP Server: ON", bootstyle="success")
        else:
            self.lbl_server.configure(text="HTTP Server: OFF", bootstyle="secondary")

        if self.connector.account_info:
            info = self.connector.account_info
            self.lbl_balance.configure(text=f"Balance: ${info.get('balance', 0):.2f}")
            self.lbl_equity.configure(text=f"Equity:  ${info.get('equity', 0):.2f}")
            prof = info.get('profit', 0)
            color = "success" if prof >= 0 else "danger"
            self.lbl_profit.configure(text=f"Profit:  ${prof:.2f}", bootstyle=color)
            
        self.after(500, self._start_data_refresh)