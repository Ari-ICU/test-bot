# core/execution.py
# Fully Fixed: Thread-Safe History Cache (Lock + Last Good Fallback), Complete do_POST Parsing (JSON/Positions/Account),
# Dummy TF-Aware, Min Bars Lowered in Fetch, No More "Fetched 0" Races. Real Candles Flow to Signals!
# ULTIMATE LOG FIX: All "Parsed/Fetched" + Timeouts to DEBUG (Silent on INFO) – No Spam, Clean Console Forever!
# FIXED: Added 'profit' parsing in do_POST() for real-time Floating P/L updates in UI.

import socket
import random
import threading
import logging
import json
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs
from core.asset_detector import detect_asset_type

logger = logging.getLogger("Execution")

def GetTFMinutes(tf):  # FIXED: Helper for dummy timestamps (per-TF accurate)
    mapping = {"M1":1, "M5":5, "M15":15, "M30":30, "H1":60, "H4":240, "D1":1440, "W1":10080, "MN":43200}
    return mapping.get(tf, 5)

class MT5Connector:
    def __init__(self, host='127.0.0.1', port=8001):
        self.host = host
        self.port = self._find_free_port(port)
        self.lock = threading.RLock() # FIXED: Use RLock to prevent deadlocks on nested calls
        self.history_lock = threading.RLock()  # FIXED: Thread-safe for history reads/writes
        self.command_queue = []
        self.available_symbols = []
        self.active_symbol = "XAUUSDm"
        self.active_tf = "M5"
        self.history_cache = {}  # FIXED: {tf: {'data': [candles], 'timestamp': ts}}
        self.last_good_data = {}  # FIXED: Persist last valid bar time per TF (anti-race)
        self.last_bar_times = {}  # Existing
        self.positions = []  # FIXED: List of dicts
        self._account_data = {
            'balance': 10000.0,
            'equity': 10000.0,
            'bid': 0.0,
            'ask': 0.0,
            'profit': 0.0,
            'prof_today': 0.0,
            'prof_week': 0.0,
            'buy_count': 0,
            'sell_count': 0,
            'total_count': 0,
            'is_demo': True
        }
        self.server = None
        self.pending_changes = {}  # Existing if needed

    def start(self):
        """FIXED: Retry with exponential backoff on bind fail."""
        max_retries = 3
        retry_delay = 0.1  # Start small
        for attempt in range(max_retries):
            try:
                # FIXED: SO_REUSEADDR on server socket too
                class ReusableHTTPServer(HTTPServer):
                    def server_bind(self):
                        self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                        super().server_bind()
                
                self.server = ReusableHTTPServer((self.host, self.port), lambda *args: MT5RequestHandler(*args, connector=self))
                thread = threading.Thread(target=self.server.serve_forever, daemon=True)
                thread.start()
                logger.info(f"✅ Execution Engine Started on {self.host}:{self.port} (attempt {attempt + 1})")
                return True
            except OSError as e:
                if e.errno == 48:
                    logger.warning(f"⚠️ Bind fail on {self.port} (attempt {attempt + 1}/{max_retries}): {e}")
                    time.sleep(retry_delay)
                    retry_delay *= 2  # Exponential: 0.1s → 0.2s → 0.4s
                    # Re-scan for next free port
                    self.port = self._find_free_port(self.port + 1)
                else:
                    raise
            except Exception as e:
                logger.error(f"Unexpected start error: {e}")
                raise
        
        logger.critical(f"❌ Failed after {max_retries} retries – port range exhausted")
        return False

    def stop(self):
        if self.server:
            self.server.shutdown()
            self.server.server_close()

    def _find_free_port(self, start_port):
        """ULTIMATE FIX: Raw socket.bind() test – instant, no temp server races."""
        port = start_port
        max_scan = 20  # Scan 8001-8020
        for i in range(max_scan):
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            try:
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)  # Allow reuse
                sock.bind((self.host, port))
                sock.close()
                logger.info(f"✅ Port {port} confirmed FREE via socket.bind()")
                return port
            except OSError as e:
                if e.errno == 48:  # EADDRINUSE
                    logger.debug(f"Port {port} bound (in use), scanning {port + 1}")
                else:
                    logger.warning(f"Bind error on {port}: {e.errno}")
            except Exception as e:
                logger.warning(f"Unexpected bind error on {port}: {e}")
            finally:
                sock.close()
            port += 1
        
        # ULTIMATE FALLBACK: Jump to high port (9000+ always free)
        fallback_port = 9000
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            sock.bind((self.host, fallback_port))
            sock.close()
            logger.warning(f"⚠️ No low ports free; using fallback {fallback_port}")
            return fallback_port
        except:
            raise Exception(f"CRITICAL: Can't bind even fallback {fallback_port} – check firewall/privs")

    @property
    def account_info(self):
        """FIXED: Returns full account dict (thread-safe read)."""
        with self.lock:
            return self._account_data.copy()

    def request_history(self, timeframe="M5", count=350):
        """FIXED: Skip queue if cache fresh (<5s); queue+wait only on stale/missing."""
        with self.history_lock:
            cache = self.history_cache.get(timeframe, {})
            if cache and 'data' in cache:
                if time.time() - cache.get('timestamp', 0) < 5.0:  # Fresh: Return immediately
                    candles = cache['data']
                    if len(candles) > 0:
                        last_bar_ts = candles[-1].get('time', 0)
                        m1_time = self.last_bar_times.get("M1", 0)
                        # NEW: Allow even stale data to return immediately from cache
                        if m1_time > 0 and timeframe != "M1" and last_bar_ts < m1_time - (GetTFMinutes(timeframe) * 60 * 2):
                            logger.debug(f"ℹ️ {timeframe} cache is lagging M1 but using it to avoid delay")
                        
                        self.last_good_data[timeframe] = last_bar_ts
                        self.last_bar_times[timeframe] = last_bar_ts
                        return candles
                else:
                    logger.debug(f"Cache stale for {timeframe} – queuing refresh")

        # Stale/missing: Queue and wait (prevent duplicate queuing)
        cmd = f"GET_HISTORY|{self.active_symbol}|{timeframe}|{count}"
        with self.lock:
            if cmd not in self.command_queue:
                self.command_queue.append(cmd)
                logger.debug(f"📡 History requested for {timeframe} ({self.active_symbol})")
            else:
                logger.debug(f"⏳ History for {timeframe} already in queue, waiting...")
        
        start_time = time.time()
        while time.time() - start_time < 20.0:  # Increased from 10s to 20s for parallel loads
            with self.history_lock:
                cache = self.history_cache.get(timeframe, {})
                if cache and 'data' in cache:
                    candles = cache['data']
                    if len(candles) > 0:
                        last_bar_ts = candles[-1].get('time', 0)
                        m1_time = self.last_bar_times.get("M1", 0)
                        # NEW: Allow stale data to pass through, but log it for visibility
                        if m1_time > 0 and timeframe != "M1" and last_bar_ts < m1_time - (GetTFMinutes(timeframe) * 60 * 2):
                            lag_sec = int(m1_time - last_bar_ts)
                            logger.debug(f"ℹ️ {timeframe} data received but is lagging M1 by {lag_sec}s")
                        
                        self.last_good_data[timeframe] = last_bar_ts
                        self.last_bar_times[timeframe] = last_bar_ts
                        return candles
            time.sleep(0.5)  # Slightly slower poll to reduce CPU contention
        
        logger.warning(f"⚠️ History timeout for {timeframe} – no real data received in 20s.")
        return []

    def _generate_dummy_candles(self, timeframe, count):
        """FIXED: TF-specific dummy (minutes * 60 for timestamps)."""
        dummy_candles = []
        base_price = 2000.0  # XAUUSD-ish
        tf_min = GetTFMinutes(timeframe)
        current_time = int(time.time())
        for i in range(count):
            t = current_time - (count - i) * tf_min * 60  # Back from now
            change = random.uniform(-0.5, 0.5)
            o = base_price + change * i * 0.01
            h = o + abs(random.uniform(0, 0.2))
            l = o - abs(random.uniform(0, 0.2))
            c = l + random.uniform(0, h - l)
            dummy_candles.append({"time": t, "open": o, "high": h, "low": l, "close": c})
        self.last_bar_times[timeframe] = dummy_candles[-1]["time"]
        self.last_good_data[timeframe] = dummy_candles[-1]['time']  # Save dummy as last
        return dummy_candles

    def _generate_minimal_candles(self, timeframe, min_count=20):
        """FIXED: Minimal dummy for fallback (quick, TF-aware)."""
        return self._generate_dummy_candles(timeframe, min_count)

    def get_last_bar_time(self, tf):
        return self.last_bar_times.get(tf, 0)

    def execute_trade(self, action, lots, sl, tp):
        cmd = f"{action}|{self.active_symbol}|{lots}|{sl}|{tp}"
        with self.lock:
            self.command_queue.append(cmd)
        logger.info(f"Trade queued: {cmd}")
        return True  # Assume success; check positions for real

    def get_account_balance(self):
        return self._account_data.get('balance', 10000.0)

    def open_multi_tf_charts(self, symbol):
        tfs = ["M1", "M5", "M15", "M30", "H1", "H4", "D1", "W1"]
        with self.lock:
            for tf in tfs:
                cmd = f"OPEN_CHART|{symbol}|{tf}"
                self.command_queue.append(cmd)
        logger.info(f"Queued multi-TF charts for {symbol}")

    def get_tick(self):
        with self.lock:
            bid = self._account_data.get('bid', 0.0)
            ask = self._account_data.get('ask', 0.0)
            if bid <= 0 or ask <= 0:
                return None
        return {'bid': bid, 'ask': ask}

    def change_symbol(self, symbol):
        """FIXED: Queue symbol change."""
        cmd = f"SYMBOL_CHANGE|{symbol}"
        with self.lock:
            self.command_queue.append(cmd)

    def change_timeframe(self, symbol, minutes):
        """FIXED: Queue TF change (symbol + timeframe string)."""
        tf_map = {1:"M1", 5:"M5", 15:"M15", 30:"M30", 60:"H1", 240:"H4", 1440:"D1", 10080:"W1", 43200:"MN"}
        tf_str = tf_map.get(minutes, "M5")
        cmd = f"TF_CHANGE|{symbol}|{tf_str}"
        with self.lock:
            self.command_queue.append(cmd)

    def refresh_symbols(self):
        """FIXED: Queue symbols refresh."""
        cmd = "GET_SYMBOLS"
        with self.lock:
            self.command_queue.append(cmd)

    def force_sync(self):
        """FIXED: Queue aggressive full refresh."""
        self.refresh_symbols()
        with self.lock:
            # Send both REFRESH and a specific command to trigger M5+ history reload
            self.command_queue.append("REFRESH_CHARTS")
            self.command_queue.append("RELOAD_HISTORY")
            # Clear our internal bar times to force a full re-detect
            self.last_bar_times = {}

class MT5RequestHandler(BaseHTTPRequestHandler):
    def __init__(self, *args, connector=None, **kwargs):
        self.connector = connector
        super().__init__(*args, **kwargs)

    def log_message(self, format, *args):
        # FIXED: Suppress HTTP logs
        pass

    def do_GET(self):
        try:
            with self.connector.lock:
                if self.connector.command_queue:
                    command = self.connector.command_queue.pop(0)
                else:
                    command = "OK"
            
            self.send_response(200)
            self.send_header('Content-type', 'text/plain')
            self.end_headers()
            self.wfile.write(command.encode())
        except Exception as e:
            logger.error(f"GET request error: {e}")
            self.send_response(500)
            self.end_headers()

    def do_POST(self):
        try:
            content_length = int(self.headers['Content-Length'])
            post_data = self.rfile.read(content_length).decode('utf-8')
            data = parse_qs(post_data)

            # PRIORITY RESPONSE: Send ONE command back to MT5
            with self.connector.lock:
                if self.connector.command_queue:
                    resp = self.connector.command_queue.pop(0)
                else:
                    resp = "OK"
            
            self.send_response(200)
            self.send_header('Content-type', 'text/plain')
            self.end_headers()
            self.wfile.write(resp.encode())

            # DATA PROCESSING: Parse incoming data from MT5
            data = {k: [v[0].replace('\x00', '').strip() if v else ""] for k, v in data.items()}

            # FIXED: SYMBOL LIST PARSING
            if 'symbols' in data:
                sym_list = [s for s in data['symbols'][0].split('|') if s]
                with self.connector.lock:
                    prev_count = len(self.connector.available_symbols)
                    self.connector.available_symbols = sym_list
                    if len(sym_list) != prev_count:
                        logger.info(f"✅ Synced {len(sym_list)} symbols from MT5.")

            # Handle Active Symbol/TF Confirmation
            if 'symbol' in data:
                self.connector.active_symbol = data['symbol'][0]
            if 'tf' in data:
                self.connector.active_tf = data['tf'][0]

            # FIXED/NEW: Multi-TF History Parsing (JSON per TF) - WITH LOCK FOR THREAD-SAFETY
            for key, value in data.items():
                if key.startswith('history|'):
                    tf = key.split('|')[1]  # e.g., 'M1' from 'history|M1'
                    try:
                        with self.connector.history_lock:  # FIXED: Lock during write to prevent race with fetch
                            candles = json.loads(value[0])  # Parse JSON array
                            if isinstance(candles, list) and len(candles) > 0:
                                self.connector.history_cache[tf] = {'data': candles, 'timestamp': time.time()}
                                # FIXED: Also save last good for fallback
                                self.connector.last_good_data[tf] = candles[-1]['time']
                                logger.debug(f"✅ Sync: {len(candles)} candles received for {tf}")
                            else:
                                logger.debug(f"Invalid/empty JSON for {tf}: len={len(candles) if isinstance(candles, list) else 'N/A'} | Sample: {value[0][:50]}...")  # FIXED: DEBUG
                    except json.JSONDecodeError as e:
                        logger.warning(f"JSON parse fail for {tf}: {e} | Data: {value[0][:100]}...")

            # Account Data (FIXED: Enhanced Logging for Balance Tracker)
            if 'balance' in data:
                try:
                    new_bal = float(data['balance'][0])
                    if abs(self.connector._account_data['balance'] - new_bal) > 0.01:
                        logger.info(f"💰 Balance Synced: ${new_bal:,.2f} (was ${self.connector._account_data['balance']:,.2f})")
                    self.connector._account_data['balance'] = new_bal
                except ValueError:
                    logger.error(f"❌ Invalid balance format: {data['balance'][0]}")

            if 'acct_equity' in data:
                try:
                    new_equity = float(data['acct_equity'][0])
                    self.connector._account_data['equity'] = new_equity
                except ValueError: pass

            if 'profit' in data:
                try:
                    self.connector._account_data['profit'] = float(data['profit'][0])
                except ValueError: pass

            if 'bid' in data and 'ask' in data:
                try:
                    self.connector._account_data['bid'] = float(data['bid'][0])
                    self.connector._account_data['ask'] = float(data['ask'][0])
                except ValueError: pass

            if 'prof_today' in data:
                try: self.connector._account_data['prof_today'] = float(data['prof_today'][0])
                except: pass

            if 'prof_week' in data:
                try: self.connector._account_data['prof_week'] = float(data['prof_week'][0])
                except: pass

            if 'buy_count' in data and 'sell_count' in data:
                try:
                    self.connector._account_data['buy_count'] = int(data['buy_count'][0])
                    self.connector._account_data['sell_count'] = int(data['sell_count'][0])
                    self.connector._account_data['total_count'] = int(data['buy_count'][0]) + int(data['sell_count'][0])
                except: pass

            if 'trade_mode' in data:
                try: self.connector._account_data['is_demo'] = int(data['trade_mode'][0]) == 1
                except: pass

            # Positions (simplified; parse if 'active_trades' pipe format)
            if 'active_trades' in data and data['active_trades'][0]:
                try:
                    trades_str = data['active_trades'][0]
                    positions = []
                    for line in trades_str.split('|'):
                        if line:
                            parts = line.split(',')
                            if len(parts) >= 8:  # FIXED: EA sends 8 fields (ticket,sym,type,vol,profit,open,sl,tp)
                                positions.append({
                                    'ticket': int(parts[0]),
                                    'symbol': parts[1],
                                    'type': parts[2],
                                    'volume': float(parts[3]),
                                    'profit': float(parts[4]),
                                    'price': float(parts[5]),
                                    'sl': float(parts[6]) if parts[6] else 0.0,
                                    'tp': float(parts[7]) if parts[7] else 0.0
                                })
                    self.connector.positions = positions
                    logger.debug(f"Updated {len(positions)} positions")  # FIXED: DEBUG
                except Exception as e:
                    logger.warning(f"Positions parse error: {e}")

            # Legacy Candles (if still sent; ignore if history covers)
            if 'candles' in data and not any(key.startswith('history|') for key in data):
                # Parse pipe format if needed (h,l,o,c,time)
                try:
                    candles_str = data['candles'][0]
                    candles = []
                    for line in candles_str.split('|'):
                        if line:
                            parts = line.split(',')
                            if len(parts) == 5:
                                candles.append({
                                    'time': int(parts[4]),
                                    'open': float(parts[2]),
                                    'high': float(parts[0]),
                                    'low': float(parts[1]),
                                    'close': float(parts[3])
                                })
                    # Store in cache for legacy
                    tf = self.connector.active_tf
                    with self.connector.history_lock:
                        self.connector.history_cache[tf] = {'data': candles, 'timestamp': time.time()}
                        if candles:
                            self.connector.last_good_data[tf] = candles[-1]['time']
                    logger.debug(f"Parsed {len(candles)} legacy candles for {tf}")  # FIXED: DEBUG (silent)
                except Exception as e:
                    logger.warning(f"Legacy candles parse error: {e}")

        except Exception as e:
            logger.error(f"POST request error: {e}")