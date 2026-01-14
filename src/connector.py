import threading
import logging
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs

logger = logging.getLogger("MT5Connector")

class MT5Connector:
    def __init__(self, host='127.0.0.1', port=8001):
        self.host = host
        self.port = port
        self.server = None
        self.server_thread = None
        self.is_running = False
        self.lock = threading.Lock()
        self.command_queue = []
        self.on_tick_received = None 
        self.on_symbols_received = None
        # --- FIX: Callback for timeframe changes ---
        self.on_timeframe_changed = None 
        self.open_positions = [] 
        self.account_info = {}   

    def start(self):
        try:
            MT5RequestHandler.connector = self
            self.server = HTTPServer((self.host, self.port), MT5RequestHandler)
            self.is_running = True
            logger.info(f"MT5 HTTP Server listening on {self.host}:{self.port}")
            self.server_thread = threading.Thread(target=self.server.serve_forever, daemon=True)
            self.server_thread.start()
            return True
        except Exception as e:
            logger.error(f"Failed to start MT5 Server: {e}")
            return False

    def stop(self):
        self.is_running = False
        if self.server:
            self.server.shutdown()
            self.server.server_close()

    def send_command(self, action, symbol, volume=0.01, sl=0, tp=0, price=0):
        command = f"{action}|{symbol}|{volume}|{sl}|{tp}|{price}"
        self._queue_simple(command)
        return True
    
    def send_draw_command(self, name, price1, price2, start_index, end_index, color_code):
        command = f"DRAW_RECT|{name}|{price1}|{price2}|{start_index}|{end_index}|{color_code}"
        self._queue_simple(command)
        return True

    def send_text_command(self, name, bar_index, price, color_code, text):
        command = f"DRAW_TEXT|{name}|{bar_index}|{price}|{color_code}|{text}"
        self._queue_simple(command)
        return True

    def send_trend_command(self, name, b1, p1, b2, p2, color_code, width=1):
        command = f"DRAW_TREND|{name}|{b1}|{p1}|{b2}|{p2}|{color_code}|{width}"
        self._queue_simple(command)

    def send_hline_command(self, name, price, color_code, style=0):
        command = f"DRAW_LINE|{name}|{price}|{color_code}|{style}"
        self._queue_simple(command)

    def send_label_command(self, name, text, color_code, y_pos):
        command = f"DRAW_LABEL|{name}|{text}|{color_code}|{y_pos}"
        self._queue_simple(command)

    def close_position(self, symbol):
        self._queue_simple(f"CLOSE_ALL|{symbol}")
        return True

    def close_profit(self, symbol):
        self._queue_simple(f"CLOSE_WIN|{symbol}")
        return True

    def close_loss(self, symbol):
        self._queue_simple(f"CLOSE_LOSS|{symbol}")
        return True
    
    def change_symbol(self, symbol):
        self._queue_simple(f"CHANGE_SYMBOL|{symbol}")
        return True
    
    def close_ticket(self, ticket_id):
        self._queue_simple(f"CLOSE_TICKET|{ticket_id}")
        return True
    
    def request_symbols(self):
        self._queue_simple("GET_SYMBOLS|ALL")

    def change_timeframe(self, symbol, tf_str):
        tf_map = {"M1": 1, "M5": 5, "M15": 15, "M30": 30, "H1": 60, "H4": 240, "D1": 1440}
        minutes = tf_map.get(tf_str, 1) 
        self._queue_simple(f"CHANGE_TF|{symbol}|{minutes}")
        
        # --- FIX: Notify the strategy via main.py wiring ---
        if self.on_timeframe_changed:
            self.on_timeframe_changed(tf_str)

    def request_history(self, symbol, count):
        self._queue_simple(f"GET_HISTORY|{symbol}|{count}")

    def _queue_simple(self, cmd):
        with self.lock: self.command_queue.append(cmd)

class MT5RequestHandler(BaseHTTPRequestHandler):
    connector = None
    last_log_time = 0

    def do_POST(self):
        if not self.connector:
            self.send_error(500, "Connector not linked")
            return

        try:
            content_length = int(self.headers.get('Content-Length', 0))
            post_data = self.rfile.read(content_length).decode('utf-8')
            data = {k: v[0] for k, v in parse_qs(post_data).items()}
            
            # Pulse Log
            current_time = time.time()
            if current_time - MT5RequestHandler.last_log_time > 5:
                MT5RequestHandler.last_log_time = current_time

            # Symbols
            if 'all_symbols' in data and self.connector.on_symbols_received:
                self.connector.on_symbols_received([s.strip() for s in data['all_symbols'].split(',') if s.strip()])

            # Tick Data
            if 'symbol' in data and 'bid' in data:
                if self.connector.on_tick_received:
                    clean_symbol = data['symbol'].replace('\x00', '').strip()
                    
                    def clean_float(val):
                        if not val: return 0.0
                        if isinstance(val, str):
                            val = val.replace('\x00', '').strip()
                            if val == "": return 0.0
                            try:
                                return float(val)
                            except:
                                return 0.0
                        return float(val)

                    try:
                        bid = clean_float(data.get('bid', 0))
                        ask = clean_float(data.get('ask', 0))
                        balance = clean_float(data.get('balance', 0))
                        profit = clean_float(data.get('profit', 0))
                        avg_entry = clean_float(data.get('avg_entry', 0))
                    except ValueError as e:
                        logger.error(f"Float Parse Error: {e}")
                        return

                    acct_name = data.get('acct_name', 'Unknown').replace('\x00', '').strip()
                    positions = int(data.get('positions', 0))
                    buy_count = int(data.get('buy_count', 0)) 
                    sell_count = int(data.get('sell_count', 0))
                    
                    self.connector.account_info = {
                        'name': acct_name,
                        'login': data.get('acct_login', '').replace('\x00', '').strip(),
                        'server': data.get('acct_server', '').replace('\x00', '').strip(),
                        'company': data.get('acct_company', '').replace('\x00', '').strip(),
                        'leverage': data.get('acct_leverage', '0').replace('\x00', '').strip(),
                        'equity': clean_float(data.get('acct_equity', 0)),
                        'balance': balance,
                        'profit': profit
                    }

                    candles = []
                    raw_candles = data.get('candles', '')
                    if raw_candles:
                        for c_str in raw_candles.split('|'):
                            parts = c_str.split(',')
                            if len(parts) >= 5: 
                                try:
                                    candles.append({
                                        'high': float(parts[0]), 
                                        'low': float(parts[1]),
                                        'open': float(parts[2]), 
                                        'close': float(parts[3]),
                                        'time': int(parts[4])
                                    })
                                except ValueError: pass

                    if 'active_trades' in data:
                        raw_trades = data['active_trades']
                        parsed_trades = []
                        if raw_trades:
                            raw_trades = raw_trades.replace('\x00', '').strip()
                            if raw_trades:
                                for t_str in raw_trades.split('|'):
                                    p = t_str.split(',')
                                    if len(p) >= 5:
                                        try:
                                            parsed_trades.append({
                                                'ticket': p[0].strip(),
                                                'symbol': p[1].strip(),
                                                'type': p[2].strip(), 
                                                'volume': float(p[3].strip()),
                                                'profit': float(p[4].strip())
                                            })
                                        except ValueError: pass
                        self.connector.open_positions = parsed_trades

                    self.connector.on_tick_received(
                        clean_symbol, bid, ask, balance, profit, acct_name, positions, buy_count, sell_count, avg_entry, candles
                    )

            self.send_response(200)
            self.send_header('Content-type', 'text/plain')
            self.end_headers()
            
            response_text = "OK"
            with self.connector.lock:
                if self.connector.command_queue:
                    response_text = ";".join(self.connector.command_queue)
                    self.connector.command_queue = []
            
            self.wfile.write(response_text.encode('utf-8'))

        except Exception as e:
            logger.error(f"HTTP Request Error: {e}")
            self.send_error(500)
    
    def log_message(self, format, *args): return