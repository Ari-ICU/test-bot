# execution.py (Fully Fixed - Enhanced for flexible symbol parsing and auto-sync)
import threading
import logging
import json
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs
from core.asset_detector import detect_asset_type  # For logging

logger = logging.getLogger("Execution")

class MT5RequestHandler(BaseHTTPRequestHandler):
    # execution.py (Fully Fixed do_POST with Priority Response and Async Processing)

    def do_POST(self):
        """
        Optimized POST handler to minimize MT5 latency and resolve 10018 errors.
        """
        try:
            # 1. READ INCOMING DATA
            content_length = int(self.headers['Content-Length'])
            post_data = self.rfile.read(content_length).decode('utf-8')
            data = parse_qs(post_data)

            # 2. PRIORITY: FETCH PENDING COMMANDS IMMEDIATELY
            # We fetch the queue first so we can respond to MT5 as quickly as possible.
            with self.connector.lock:
                if self.connector.command_queue:
                    resp = ";".join(self.connector.command_queue)
                    self.connector.command_queue = [] 
                else:
                    resp = "OK"
            
            # 3. IMMEDIATE RESPONSE TO MT5
            # By sending the 200 OK and commands here, the MT5 WebRequest is released 
            # while Python continues to process the heavy candle/account data below.
            self.send_response(200)
            self.send_header('Content-type', 'text/plain')
            self.end_headers()
            self.wfile.write(resp.encode())

            # 4. BACKGROUND DATA PROCESSING (After Response)
            
            # Handle Symbol and Timeframe Confirmation
            if 'symbol' in data:
                new_symbol = data['symbol'][0]
                with self.connector.lock:
                    self.connector.active_symbol = new_symbol
                    self.connector.pending_changes['symbol'] = None

            if 'tf' in data:
                new_tf = data['tf'][0].upper()
                with self.connector.lock:
                    self.connector.active_tf = new_tf
                    self.connector.pending_changes['tf'] = None

            # Handle Bid/Ask Persistence (Prevents 0.0 values)
            if 'bid' in data and 'ask' in data:
                with self.connector.lock:
                    self.connector._account_data['bid'] = float(data['bid'][0])
                    self.connector._account_data['ask'] = float(data['ask'][0])

            # Handle Account Updates
            if 'balance' in data:
                with self.connector.lock:
                    self.connector._account_data.update({
                        'balance': float(data.get('balance', [0])[0]),
                        'equity': float(data.get('acct_equity', [0])[0]),
                        'profit': float(data.get('profit', [0])[0]),
                        'total_count': int(data.get('buy_count', [0])[0]) + int(data.get('sell_count', [0])[0])
                    })

            # Handle Candle Sync (Heavy Operation)
            raw_candles = data.get('candles', [''])[0]
            if raw_candles:
                tf_key = data.get('tf', ['M5'])[0].upper()
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

        except Exception as e:
            logger.error(f"Critical do_POST Error: {e}")
            # Note: headers might have already been sent, so we handle safely
            try:
                self.send_error(500)
            except:
                pass

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
        
        self.available_symbols = []  # FALLBACK: Initial common symbols
        self.running = False
        self.telegram_bot = None
        self.active_symbol = "XAUUSDm"  # Track active EA symbol
        self.active_tf = "M5"  # NEW: Track active TF

        # FIXED: Add pending_changes for optimistic updates
        self.pending_changes = {'symbol': None, 'tf': None}  # Track pending for optimistic UI

        # ENHANCED: Log fallback on init
        logger.info(f"🔄 Initialized with Fallback Symbols: {len(self.available_symbols)} (e.g., {self.available_symbols[:3]}) – Awaiting MT5 POST")

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

    # FIXED: Update change_symbol with optimistic update
    def change_symbol(self, new_symbol):
        with self.lock:
            # 1. Clear candle data for ALL timeframes so strategies don't use old data
            for tf in self.tf_data:
                self.tf_data[tf] = []  
            
            # 2. Optimistically update internal state (revert on EA failure if needed)
            old_symbol = self.active_symbol
            self.active_symbol = new_symbol
            self.pending_changes['symbol'] = new_symbol
            
            # 3. Queue the command for the EA to pick up on its next poll
            self.command_queue.append(f"SYMBOL_CHANGE|{new_symbol}|{self.active_tf}")
            
            logger.info(f"🔄 UI Request: Change to {new_symbol} (from {old_symbol}). Queued & Optimistically Updated.")

    # FIXED: Update change_timeframe with optimistic update
    def change_timeframe(self, symbol, minutes):
        tf_map = {1: "M1", 5: "M5", 15: "M15", 30: "M30", 60: "H1", 240: "H4", 1440: "D1"}
        new_tf = tf_map.get(minutes, "M5")
        with self.lock:
            # Clear data for the new TF to force a fresh reload from MT5
            self.tf_data[new_tf] = []  
            
            # Optimistically update
            old_tf = self.active_tf
            self.active_tf = new_tf
            self.pending_changes['tf'] = new_tf
            
            self.command_queue.append(f"TF_CHANGE|{new_tf}|{symbol}")
            logger.info(f"🔄 UI Request: Change TF to {new_tf} (from {old_tf}). Queued & Optimistically Updated.")

    # ENHANCED: Update refresh_symbols to queue a request
    def refresh_symbols(self):
        with self.lock:
            self.command_queue.append("GET_SYMBOLS")
        logger.info("🔄 Forcing Symbol List Refresh – Queued GET_SYMBOLS for MT5")

    # NEW: Add force_sync() for manual refresh (callable from UI)
    def force_sync(self):
        """Force a full sync from EA (e.g., re-POLL symbols/TF)."""
        with self.lock:
            self.command_queue.append("SYNC_REQUEST")  # EA-side: Trigger a full POST
            logger.info("🔄 Force Sync Requested – Awaiting EA Response.")

    # Inside MT5Connector in execution.py
    def send_order(self, action, symbol, lot, sl, tp):
        with self.lock:
            # Check for valid prices before allowing the queue
            if self._account_data['bid'] <= 0 or self._account_data['ask'] <= 0:
                logger.error(f"Execution Blocked: Invalid prices for {symbol} (Bid: {self._account_data['bid']})")
                return False
                
            self.command_queue.append(f"{action}|{symbol}|{lot}|{sl}|{tp}")
            logger.info(f"Order Queued: {action}|{symbol}|{lot}|{sl}|{tp}")
        return True

    # ENHANCED: In start(), queue an initial sync request
    def start(self):
        """Starts the HTTP server for MT5 communication"""
        try:
            MT5RequestHandler.connector = self
            self.server = HTTPServer((self.host, self.port), MT5RequestHandler)
            self.server_thread = threading.Thread(target=self.server.serve_forever, daemon=True)
            self.server_thread.start()
            self.running = True
            # NEW: Queue initial sync request for EA
            with self.lock:
                self.command_queue.append("GET_SYMBOLS")  # EA should respond with symbols POST
            logger.info(f"Execution Engine (HTTP) Started on {self.host}:{self.port} – Sent GET_SYMBOLS request")
            return True
        except Exception as e:
            logger.error(f"Failed to start Execution Engine: {e}")
            return False

    def stop(self):
        self.running = False
        if self.server:
            self.server.shutdown()
        logger.info("Execution Engine Stopped")