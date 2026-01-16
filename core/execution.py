import threading
import logging
import json
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
        
        # FIXED: Internal storage variable initialized
        self._account_data = {
            'name': 'Disconnected',
            'balance': 0.0,
            'equity': 0.0,
            'profit': 0.0,
            'total_count': 0
        }
        
        self.last_candles = []
        self.available_symbols = []
        self.running = False
        self.telegram_bot = None
        self.active_symbol = None 

    @property
    def account_info(self):
        """Thread-safe getter for account data"""
        with self.lock:
            return self._account_data.copy()

    def set_telegram(self, tg_bot):
        self.telegram_bot = tg_bot

    def start(self):
        try:
            MT5RequestHandler.connector = self
            self.server = HTTPServer((self.host, self.port), MT5RequestHandler)
            self.server_thread = threading.Thread(target=self.server.serve_forever, daemon=True)
            self.server_thread.start()
            self.running = True
            logger.info(f"Execution Engine (HTTP) Started on {self.host}:{self.port}")
            return True
        except Exception as e:
            logger.error(f"Failed to start Execution Engine: {e}")
            return False
            
    def stop(self):
        self.running = False
        if self.server:
            self.server.shutdown()
            self.server.server_close()
            logger.info("Execution Engine Stopped")

    def send_order(self, action, symbol, volume, sl, tp):
        cmd = f"{action}|{symbol}|{volume}|{sl}|{tp}|10"
        with self.lock: 
            self.command_queue.append(cmd)
        logger.info(f"Order Queued: {cmd}")
        if self.telegram_bot:
            self.telegram_bot.send_message(f"🚀 <b>Signal Sent:</b> {action} {symbol} {volume}")

    def close_position(self, symbol, mode="ALL"):
        cmd = f"CLOSE_MODE|{symbol}|{mode}"
        with self.lock: 
            self.command_queue.append(cmd)
        logger.info(f"Close Command Queued: {cmd}")

    def change_symbol(self, symbol):
        cmd = f"CHANGE_SYMBOL|{symbol}"
        with self.lock:
            self.command_queue.append(cmd)
        logger.info(f"Symbol Change Queued: {symbol}")

    def get_latest_candles(self):
        return self.last_candles

class MT5RequestHandler(BaseHTTPRequestHandler):
    connector = None

    def log_message(self, format, *args):
        pass

    def do_POST(self):
        if not self.connector: return

        try:
            length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(length).decode('utf-8')
            data = parse_qs(body)
            
            if 'symbol' in data:
                self.connector.active_symbol = data['symbol'][0]

            if 'candles' in data:
                raw_candles = data['candles'][0]
                if raw_candles:
                    parsed = []
                    for c in raw_candles.split('|'):
                        parts = c.split(',')
                        if len(parts) >= 5:
                            parsed.append({
                                'high': float(parts[0]),
                                'low': float(parts[1]),
                                'open': float(parts[2]),
                                'close': float(parts[3]),
                                'time': int(parts[4])
                            })
                    self.connector.last_candles = parsed

            if 'all_symbols' in data:
                self.connector.available_symbols = [s.strip() for s in data['all_symbols'][0].split(',') if s.strip()]

            # 4. FIXED: Updating the internal variable instead of the read-only property
            if 'balance' in data:
                trade_mode = int(data.get('trade_mode', [1])[0])
                b_count = int(data.get('buy_count', [0])[0])
                s_count = int(data.get('sell_count', [0])[0])
                self.connector._account_data = {
                    'name': data.get('acct_name', ["Unknown"])[0], 
                    'is_demo': (trade_mode != 0),
                    'balance': float(data.get('balance', [0])[0]),
                    'equity': float(data.get('acct_equity', [0])[0]),
                    'profit': float(data.get('profit', [0])[0]),
                    'buy_count': b_count,
                    'sell_count': s_count,
                    'total_count': b_count + s_count,
                    'bid': float(data.get('bid', [0.0])[0]),
                    'ask': float(data.get('ask', [0.0])[0])
                }

            resp = "OK"
            with self.connector.lock:
                if self.connector.command_queue:
                    resp = ";".join(self.connector.command_queue)
                    self.connector.command_queue = [] 
            
            self.send_response(200)
            self.end_headers()
            self.wfile.write(resp.encode())
            
        except Exception as e:
            logger.error(f"Sync Error: {e}")
            self.send_error(500)