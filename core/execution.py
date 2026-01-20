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
    def do_POST(self):
        try:
            content_length = int(self.headers['Content-Length'])
            post_data = self.rfile.read(content_length).decode('utf-8')
            data = parse_qs(post_data)

            # 1. PRIORITY RESPONSE: Send commands back to MT5 immediately
            with self.connector.lock:
                resp = ";".join(self.connector.command_queue) if self.connector.command_queue else "OK"
                self.connector.command_queue = [] 
            
            self.send_response(200)
            self.send_header('Content-type', 'text/plain')
            self.end_headers()
            self.wfile.write(resp.encode())

            # 2. DATA PROCESSING: Parse incoming data from MT5
            
            # --- SANITIZE DATA (Strip null bits from strings) ---
            data = {k: [v[0].replace('\x00', '').strip() if v else ""] for k, v in data.items()}

            # --- FIXED: SYMBOL LIST PARSING ---
            if 'symbols' in data:
                # MQL5 sends symbols as a pipe-separated string (e.g., "XAUUSD|EURUSD")
                sym_list = [s for s in data['symbols'][0].split('|') if s]
                with self.connector.lock:
                    prev_count = len(self.connector.available_symbols)
                    self.connector.available_symbols = sym_list
                    if len(sym_list) != prev_count:
                        logger.info(f"✅ Synced {len(sym_list)} symbols from MT5.")

            # Handle Active Symbol/TF Confirmation
            if 'symbol' in data:
                with self.connector.lock:
                    self.connector.active_symbol = data['symbol'][0]
                    self.connector.pending_changes['symbol'] = None

            if 'tf' in data:
                with self.connector.lock:
                    self.connector.active_tf = data['tf'][0].upper()
                    self.connector.pending_changes['tf'] = None

            # Handle Bid/Ask/Account
            if 'bid' in data and 'ask' in data:
                with self.connector.lock:
                    self.connector._account_data['bid'] = float(data['bid'][0])
                    self.connector._account_data['ask'] = float(data['ask'][0])

            if 'balance' in data:
                with self.connector.lock:
                    self.connector._account_data.update({
                        'balance': float(data.get('balance', [0])[0]),
                        'equity': float(data.get('acct_equity', [0])[0]),
                        'profit': float(data.get('profit', [0])[0]),
                        'prof_today': float(data.get('prof_today', [0])[0]),
                        'prof_week': float(data.get('prof_week', [0])[0]),
                        'total_count': int(data.get('buy_count', [0])[0]) + int(data.get('sell_count', [0])[0]),
                        'buy_count': int(data.get('buy_count', [0])[0]),
                        'sell_count': int(data.get('sell_count', [0])[0])
                    })

            # Handle Candle Sync
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

            # Handle M1 Specific Candles (always sent for profit protection)
            # Only update if the main chart is NOT M1 (to avoid wiping history)
            m1_raw = data.get('m1_candles', [''])[0]
            if m1_raw and tf_key != "M1":
                parsed_m1 = []
                for c in m1_raw.split('|'):
                    parts = c.split(',')
                    if len(parts) >= 5:
                        parsed_m1.append({
                            'high': float(parts[0]), 'low': float(parts[1]),
                            'open': float(parts[2]), 'close': float(parts[3]),
                            'time': int(parts[4])
                        })
                with self.connector.lock:
                    self.connector.tf_data["M1"] = parsed_m1

            # Handle HTF Specific Candles (H1/H4/D1)
            for h_tf in ["H1", "H4", "D1"]:
                if h_tf == tf_key: continue # Don't overwrite main candles if they are on HTF
                h_raw = data.get(f"htf_{h_tf}", [""])[0]
                if h_raw:
                    parsed_h = []
                    for c in h_raw.split('|'):
                        parts = c.split(',')
                        if len(parts) >= 5:
                            parsed_h.append({
                                'high': float(parts[0]), 'low': float(parts[1]),
                                'open': float(parts[2]), 'close': float(parts[3]),
                                'time': int(parts[4])
                            })
                    with self.connector.lock:
                        self.connector.tf_data[h_tf] = parsed_h

            if 'active_trades' in data:
                raw_trades = data['active_trades'][0]
                parsed_trades = []
                if raw_trades:
                    for t in raw_trades.split('|'):
                        parts = t.split(',')
                        if len(parts) >= 5:
                            parsed_trades.append({
                                'ticket': parts[0],
                                'symbol': parts[1],
                                'type': 0 if parts[2] == "BUY" else 1,
                                'volume': float(parts[3]),
                                'profit': float(parts[4]),
                                'open_price': float(parts[5]) if len(parts) >= 6 else 0.0,
                                'sl': float(parts[6]) if len(parts) >= 7 else 0.0,
                                'tp': float(parts[7]) if len(parts) >= 8 else 0.0
                            })
                with self.connector.lock:
                    self.connector._open_positions = parsed_trades

        except Exception as e:
            logger.error(f"Critical do_POST Error: {e} | Raw Data Sample: {str(data)[:100]}")

    def log_message(self, format, *args): pass

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
            'prof_today': 0.0,
            'prof_week': 0.0,
            'total_count': 0,
            'bid': 0.0,
            'ask': 0.0,
            'buy_count': 0,
            'sell_count': 0
        }
        self._open_positions = [] # Store parsed trades

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

    def get_open_positions(self):
        """Thread-safe getter for current active trades"""
        with self.lock:
            return self._open_positions.copy()

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

    def request_history(self, count):
        """Tell the EA to send more historical bars."""
        with self.lock:
            self.command_queue.append(f"GET_HISTORY|{self.active_symbol}|{count}")
            logger.info(f"📥 Requested {count} bars of history from EA.")

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

    # FIXED: Update modify_order to include Symbol for EA parser stability
    def modify_order(self, ticket, sl, tp, symbol=None):
        with self.lock:
            # 1. If symbol not provided, look it up in active positions
            if not symbol:
                for pos in self._open_positions:
                    if str(pos['ticket']) == str(ticket):
                        symbol = pos['symbol']
                        break
            
            # 2. Validation
            if not symbol:
                logger.error(f"❌ Modify Fail: Symbol lookup failed for Ticket {ticket}")
                return False

            # 3. Queue with correct structure: CMD|SYMBOL|TICKET|SL|TP
            self.command_queue.append(f"ORDER_MODIFY|{symbol}|{ticket}|{sl}|{tp}")
            logger.debug(f"Modify Queued: {symbol} #{ticket} -> SL: {sl}, TP: {tp}")
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