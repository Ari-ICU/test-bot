import threading
import logging
import json
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs
from core.asset_detector import detect_asset_type  # For logging

logger = logging.getLogger("Execution")

class MT5RequestHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        try:
            content_length = int(self.headers['Content-Length'])
            post_data = self.rfile.read(content_length).decode('utf-8')
            data = parse_qs(post_data)

            # 1. Handle Commands (e.g., POLL, ORDER)
            if 'command' in data:
                cmd = data['command'][0].upper()
                if cmd == 'POLL':
                    # Send account/candle snapshot
                    resp = self._build_poll_response(data)
                    self.send_response(200)
                    self.end_headers()
                    self.wfile.write(resp.encode())
                    return

            # 2. Handle Order Execution
            if 'action' in data:
                action = data['action'][0]
                symbol = data.get('symbol', ['XAUUSD'])[0]
                lot = float(data.get('lot', [0.01])[0])
                sl = float(data.get('sl', [0.0])[0])
                tp = float(data.get('tp', [0.0])[0])
                
                # Simulate/Queue Order (in real: Send to MT5 via ZeroMQ or file)
                logger.info(f"Order Received: {action} {symbol} Lot:{lot} SL:{sl} TP:{tp}")
                
                # Queue for processing (thread-safe)
                with self.connector.lock:
                    self.connector.command_queue.append(f"EXEC:{action}|{symbol}|{lot}|{sl}|{tp}")
                
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"ORDER_QUEUED")

            # 3. Handle Data Sync (Candles, Account)
            raw_candles = data.get('candles', [''])[0]
            if raw_candles:
                # Route data to correct TF slot based on EA parameter
                tf_key = data.get('tf', ['M5'])[0].upper()
                
                if raw_candles:
                    parsed = []
                    for c in raw_candles.split('|'):
                        parts = c.split(',')
                        if len(parts) >= 5:
                            parsed.append({
                                'high': float(parts[0]), 'low': float(parts[1]),
                                'open': float(parts[2]), 'close': float(parts[3]),
                                'time': int(parts[4])
                            })
                    with self.connector.lock:
                        self.connector.tf_data[tf_key] = parsed
                        logger.debug(f"Updated {len(parsed)} candles for {tf_key}")

            # 4. Handle Account Updates
            if 'balance' in data:
                trade_mode = int(data.get('trade_mode', [1])[0])
                b_count = int(data.get('buy_count', [0])[0])
                s_count = int(data.get('sell_count', [0])[0])
                
                with self.connector.lock:
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

            # NEW: Update Active Symbol from EA
            if 'symbol' in data:
                new_symbol = data['symbol'][0]
                with self.connector.lock:
                    if self.connector.active_symbol != new_symbol:
                        self.connector.active_symbol = new_symbol
                        logger.info(f"EA Active Symbol Updated: {new_symbol} ({detect_asset_type(new_symbol)})")

            # Prepare response for MT5 (Sends any pending commands)
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

    def _build_poll_response(self, data):
        """Build response with current state for EA poll."""
        with self.connector.lock:
            acc = self.connector.account_info
            tf = data.get('tf', ['M5'])[0]
            candles = self.connector.get_tf_candles(tf)
            
            # Format candles as | separated string
            candle_str = '|'.join([f"{c['high']},{c['low']},{c['open']},{c['close']},{c['time']}" for c in candles[-100:]]) if candles else ''
            
            return f"POLLOK|balance:{acc['balance']}|equity:{acc['equity']}|profit:{acc['profit']}|bid:{acc['bid']}|ask:{acc['ask']}|buy_count:{acc['buy_count']}|sell_count:{acc['sell_count']}|candles:{candle_str}|symbol:{self.connector.active_symbol}"

    def log_message(self, format, *args):
        # Suppress default HTTP logs
        pass

class MT5Connector:
    def __init__(self, host='127.0.0.1', port=8001):
        self.host = host
        self.port = port
        self.server = None
        self.command_queue = []
        self.lock = threading.Lock()
        
        # Internal storage for account data
        self._account_data = {
            'name': 'Disconnected',
            'balance': 0.0,
            'equity': 0.0,
            'profit': 0.0,
            'total_count': 0,
            'bid': 0.0,
            'ask': 0.0,
            'buy_count': 0,
            'sell_count': 0
        }

        # FULL TIMEFRAME SUPPORT: Expanded to hold data for all required strategy timeframes
        self.tf_data = {
            "M1": [], "M5": [], "M15": [], "M30": [],
            "H1": [], "H4": [], "D1": [], "W1": []
        }
        
        self.available_symbols = [] # Stores the dropdown list for the UI
        self.running = False
        self.telegram_bot = None
        self.active_symbol = "XAUUSDm"  # NEW: Track active EA symbol

    @property
    def account_info(self):
        """Thread-safe getter for account data"""
        with self.lock:
            return self._account_data.copy()

    def get_tf_candles(self, timeframe_str, count=300):
        """Thread-safe access to candle data received from MT5 Bridge"""
        with self.lock:
            data = self.tf_data.get(timeframe_str.upper(), [])
            if len(data) > count:
                return data[-count:]
            return data

    def set_telegram(self, tg_bot):
        self.telegram_bot = tg_bot

    def send_order(self, action, symbol, lot, sl, tp):
        """Send order to queue for EA execution."""
        if not self.running:
            logger.error("Connector not running – Cannot send order")
            return False
        
        # Format for EA: POST to /order endpoint (handled in do_POST)
        order_data = {
            'command': 'ORDER',
            'action': action,
            'symbol': symbol,
            'lot': str(lot),
            'sl': str(sl),
            'tp': str(tp)
        }
        # In real impl: Use requests.post(self.host, self.port, order_data) or ZeroMQ
        # For now, queue internally
        with self.lock:
            self.command_queue.append(f"{action}|{symbol}|{lot}|{sl}|{tp}")
            logger.info(f"Order Queued: {action}|{symbol}|{lot}|{sl}|{tp}")
        
        if self.telegram_bot:
            self.telegram_bot.send_message(f"📈 Order Sent: {action} {symbol} Lot:{lot}")
        return True

    def start(self):
        """Starts the HTTP server for MT5 communication"""
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
        logger.info("Execution Engine Stopped")