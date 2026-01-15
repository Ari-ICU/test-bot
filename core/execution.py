import threading
import logging
import time
import json
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
        self.last_candles = []
        self.running = False

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
        # MT5 Format: ACTION|SYMBOL|VOLUME|SL|TP|DEVIATION
        cmd = f"{action}|{symbol}|{volume}|{sl}|{tp}|10"
        with self.lock: 
            self.command_queue.append(cmd)
        logger.info(f"Order Queued via Bridge: {cmd}")

    def close_position(self, symbol, mode="ALL"):
        # Modes: ALL, WIN, LOSS
        cmd = f"CLOSE_{mode}|{symbol}"
        with self.lock: 
            self.command_queue.append(cmd)
        logger.info(f"Close Command Queued: {cmd}")

    def get_latest_candles(self):
        return self.last_candles

class MT5RequestHandler(BaseHTTPRequestHandler):
    connector = None

    def log_message(self, format, *args):
        # Suppress default HTTP logging to keep console clean
        pass

    def do_POST(self):
        if not self.connector: return

        try:
            length = int(self.headers.get('Content-Length', 0))
            
            # --- WEBHOOK HANDLING (JSON) ---
            if self.path == '/webhook':
                try:
                    body = self.rfile.read(length).decode('utf-8')
                    data = json.loads(body)
                    
                    # Expected JSON: {"action": "BUY", "symbol": "XAUUSD", "volume": 0.01, "sl": 0, "tp": 0}
                    action = data.get('action', '').upper()
                    symbol = data.get('symbol', 'XAUUSD')
                    volume = float(data.get('volume', 0.01))
                    sl = float(data.get('sl', 0.0))
                    tp = float(data.get('tp', 0.0))
                    
                    if action in ['BUY', 'SELL']:
                        self.connector.send_order(action, symbol, volume, sl, tp)
                        response = {"status": "success", "message": f"Order {action} queued"}
                    elif action.startswith('CLOSE'):
                        self.connector.close_position(symbol, action.replace('CLOSE_', ''))
                        response = {"status": "success", "message": f"Close {action} queued"}
                    else:
                        response = {"status": "error", "message": "Invalid action"}
                        
                    self.send_response(200)
                    self.send_header('Content-type', 'application/json')
                    self.end_headers()
                    self.wfile.write(json.dumps(response).encode())
                    logger.info(f"Webhook received: {data}")
                    
                except Exception as e:
                    logger.error(f"Webhook error: {e}")
                    self.send_error(400, "Invalid JSON")
                return

            # --- MT5 DATA SYNC (Form Data) ---
            body = self.rfile.read(length).decode('utf-8')
            data = parse_qs(body)
            
            # Extract Candle Data if available
            if 'candles' in data:
                # Format: Open,High,Low,Close,Time|...
                raw_candles = data['candles'][0]
                if raw_candles:
                    parsed_candles = []
                    for c in raw_candles.split('|'):
                        parts = c.split(',')
                        if len(parts) >= 5:
                            parsed_candles.append({
                                'high': float(parts[0]),
                                'low': float(parts[1]),
                                'open': float(parts[2]),
                                'close': float(parts[3]),
                                'time': int(parts[4])
                            })
                    self.connector.last_candles = parsed_candles

            # Update Account Info
            if 'balance' in data:
                self.connector.account_info = {
                    'balance': float(data.get('balance', [0])[0]),
                    'equity': float(data.get('acct_equity', [0])[0]),
                    'profit': float(data.get('profit', [0])[0])
                }

            # Send Commands Back to MT5
            resp = "OK"
            with self.connector.lock:
                if self.connector.command_queue:
                    resp = ";".join(self.connector.command_queue)
                    self.connector.command_queue = [] # Clear queue after sending
            
            self.send_response(200)
            self.end_headers()
            self.wfile.write(resp.encode())
            
        except Exception as e:
            # logger.error(f"HTTP Request Error: {e}")
            self.send_error(500)