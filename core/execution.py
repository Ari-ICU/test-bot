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
        self.account_info = {}
        self.last_candles = []
        self.available_symbols = []
        self.running = False
        self.telegram_bot = None
        
        # New: Track the actual symbol reporting from MT5
        self.active_symbol = None 

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
        cmd = f"CLOSE_{mode}|{symbol}"
        with self.lock: 
            self.command_queue.append(cmd)
        logger.info(f"Close Command Queued: {cmd}")
        if self.telegram_bot:
            self.telegram_bot.send_message(f"🔄 <b>Close Command:</b> {mode} {symbol}")

    def change_symbol(self, symbol):
        cmd = f"CHANGE_SYMBOL|{symbol}"
        with self.lock:
            self.command_queue.append(cmd)
        logger.info(f"Symbol Change Queued: {symbol}")
        if self.telegram_bot:
            self.telegram_bot.send_message(f"🔀 <b>Symbol Changed:</b> Now trading {symbol}")

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
            
            # --- TELEGRAM WEBHOOK ---
            if self.path == '/telegram':
                body = self.rfile.read(length).decode('utf-8')
                try:
                    data = json.loads(body)
                    if self.connector.telegram_bot:
                        self.connector.telegram_bot.process_webhook_update(data)
                    self.send_response(200)
                    self.end_headers()
                    self.wfile.write(b"OK")
                except Exception as e:
                    logger.error(f"Telegram processing error: {e}")
                    self.send_error(400)
                return

            # --- TRADINGVIEW WEBHOOK ---
            if self.path == '/webhook':
                try:
                    body = self.rfile.read(length).decode('utf-8')
                    data = json.loads(body)
                    action = data.get('action', '').upper()
                    symbol = data.get('symbol', 'XAUUSD')
                    volume = float(data.get('volume', 0.01))
                    if action in ['BUY', 'SELL']:
                        self.connector.send_order(action, symbol, volume, 0, 0)
                    self.send_response(200)
                    self.end_headers()
                    self.wfile.write(json.dumps({"status": "queued"}).encode())
                except:
                    self.send_error(400)
                return

            # --- MT5 DATA SYNC ---
            body = self.rfile.read(length).decode('utf-8')
            data = parse_qs(body)
            
            # 1. Capture Symbol from EA (This fixes the mismatch)
            if 'symbol' in data:
                ea_symbol = data['symbol'][0]
                if ea_symbol:
                    self.connector.active_symbol = ea_symbol

            # 2. Candle Data
            if 'candles' in data:
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

            # 3. Available Symbols
            if 'all_symbols' in data:
                raw_syms = data['all_symbols'][0]
                if raw_syms:
                    clean_syms = [s.strip() for s in raw_syms.split(',') if s.strip()]
                    self.connector.available_symbols = clean_syms

            # 4. Account Info
            if 'balance' in data:
                b_count = int(data.get('buy_count', [0])[0])
                s_count = int(data.get('sell_count', [0])[0])
                self.connector.account_info = {
                    'balance': float(data.get('balance', [0])[0]),
                    'equity': float(data.get('acct_equity', [0])[0]),
                    'profit': float(data.get('profit', [0])[0]),
                    'buy_count': b_count,
                    'sell_count': s_count,
                    'total_count': b_count + s_count,
                    'bid': float(data.get('bid', [0.0])[0]),
                    'ask': float(data.get('ask', [0.0])[0])
                }

            # 5. Send Queued Commands
            resp = "OK"
            with self.connector.lock:
                if self.connector.command_queue:
                    resp = ";".join(self.connector.command_queue)
                    self.connector.command_queue = [] 
            
            self.send_response(200)
            self.end_headers()
            self.wfile.write(resp.encode())
            
        except Exception as e:
            self.send_error(500)