import threading
import logging
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs

logger = logging.getLogger("Execution")

class MT5Connector:
    def __init__(self, host='127.0.0.1', port=8001):
        self.host = host
        self.port = port
        self.server = None
        self.command_queue = []
        self.lock = threading.Lock()
        self.data_callback = None
        self.account_info = {}
        self.open_positions = []

    def start(self):
        try:
            MT5RequestHandler.connector = self
            self.server = HTTPServer((self.host, self.port), MT5RequestHandler)
            threading.Thread(target=self.server.serve_forever, daemon=True).start()
            logger.info("Execution Engine (HTTP) Started")
            return True
        except Exception as e:
            logger.error(f"Failed to start Execution Engine: {e}")
            return False

    def send_order(self, action, symbol, volume, sl, tp):
        cmd = f"{action}|{symbol}|{volume}|{sl}|{tp}|0"
        with self.lock: self.command_queue.append(cmd)
        logger.info(f"Order Queued: {cmd}")

    def close_position(self, symbol):
        with self.lock: self.command_queue.append(f"CLOSE_ALL|{symbol}")

    def get_latest_candles(self):
        # Logic to return stored candles (handled in RequestHandler)
        return getattr(self, 'last_candles', [])

class MT5RequestHandler(BaseHTTPRequestHandler):
    connector = None
    def do_POST(self):
        if not self.connector: return
        try:
            length = int(self.headers.get('Content-Length', 0))
            data = parse_qs(self.rfile.read(length).decode('utf-8'))
            
            # Process incoming tick data here (simplified for brevity)
            # In real implementation, parse 'bid', 'ask', 'candles'
            # and update connector.last_candles / connector.account_info
            
            # Send commands back to MT5
            resp = "OK"
            with self.connector.lock:
                if self.connector.command_queue:
                    resp = ";".join(self.connector.command_queue)
                    self.connector.command_queue = []
            
            self.send_response(200)
            self.end_headers()
            self.wfile.write(resp.encode())
        except: self.send_error(500)
    
    def log_message(self, format, *args): return