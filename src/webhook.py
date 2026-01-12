import urllib.request
import urllib.parse
import urllib.error
import json
import logging
import threading
import time

logger = logging.getLogger("WebhookAlert")

class WebhookAlert:
    def __init__(self, bot_token=None, chat_id=None):
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.enabled = bool(bot_token and chat_id)
        
        if self.enabled:
            logger.info("Telegram Webhook Alert initialized.")
            # Start Polling for commands (e.g. /status)
            self.stop_event = threading.Event()
            self.poll_thread = threading.Thread(target=self._poll_updates, daemon=True)
            self.poll_thread.start()
            
            # Register Commands with Telegram for Auto-complete
            self._register_commands()
        else:
            logger.warning("Telegram Webhook Alert: Missing bot_token or chat_id. Alerts disabled.")

    def send_message(self, message):
        """Sends a message to Telegram in a non-blocking thread."""
        if not self.enabled:
            return

        thread = threading.Thread(target=self._send_sync, args=(message,), daemon=True)
        thread.start()

    def _send_sync(self, message):
        """Synchronous sender called from thread."""
        try:
            url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
            data = urllib.parse.urlencode({
                'chat_id': self.chat_id,
                'text': message,
                'parse_mode': 'Markdown'
            }).encode('utf-8')
            
            req = urllib.request.Request(url, data=data)
            with urllib.request.urlopen(req, timeout=10) as response:
                result = response.read().decode('utf-8')
                # logger.debug(f"Telegram response: {result}")
        except urllib.error.HTTPError as e:
            error_msg = e.read().decode('utf-8')
            logger.error(f"Telegram API Error (HTTP {e.code}): {error_msg}")
        except Exception as e:
            logger.error(f"Failed to send Telegram alert: {e}")

    def _register_commands(self):
        """Tells Telegram to show these commands in the menu."""
        try:
            url = f"https://api.telegram.org/bot{self.bot_token}/setMyCommands"
            commands = [
                {"command": "status", "description": "Show account balance & P/L"},
                {"command": "positions", "description": "Show detailed open trades"},
                {"command": "menu", "description": "Show interactive control panel"},
                {"command": "help", "description": "Show available commands"}
            ]
            data = json.dumps({"commands": commands}).encode('utf-8')
            req = urllib.request.Request(url, data=data, headers={'Content-Type': 'application/json'})
            with urllib.request.urlopen(req, timeout=10) as response:
                pass # Success
        except Exception as e:
            logger.warning(f"Failed to register Telegram commands: {e}")

    def notify_trade(self, action, symbol, volume, sl, tp, reason):
        """Specifically formatted notification for trades."""
        direction_emoji = "🟢" if "BUY" in action.upper() else "🔴"
        t_str = time.strftime('%H:%M:%S')
        
        msg = (
            f"{direction_emoji} *TRADE EXECUTED*\n\n"
            f"📍 *{action}* `{symbol}`\n"
            f"💰 Lot: `{volume}`\n"
            f"🛡️ SL: `{sl:.5f}`\n"
            f"🎯 TP: `{tp:.5f}`\n"
            f"💡 Reason: `{reason}`\n"
            f"🕒 Time: `{t_str}`"
        )
        self.send_message(msg)

    def notify_news(self, title, sentiment, score):
        """Specifically formatted notification for news."""
        emoji = "🔥" if sentiment == "BEARISH" else "🚀" if sentiment == "BULLISH" else "ℹ️"
        msg = (
            f"{emoji} *NEWS ALERT*\n\n"
            f"📰 *{title}*\n"
            f"📊 Sentiment: {sentiment} ({score})\n"
            f"⚠️ Trading paused if high impact."
        )
        self.send_message(msg)

    def notify_active_positions(self, positions_list):
        """Sends a detailed list of all open positions."""
        if not positions_list:
            self.send_message("📭 *No Active Positions*")
            return

        msg = "📋 *OPEN POSITIONS*\n"
        for p in positions_list:
            # Assuming p is a dict: {'symbol': 'XAUUSD', 'type': 'BUY', 'volume': 0.01, 'profit': 1.23}
            # Adjust keys based on what Strategy provides
            emoji = "🟢" if p['type'] == 'BUY' else "🔴"
            pl_emoji = "💵" if p['profit'] >= 0 else "🔻"
            msg += (
                f"\n{emoji} *{p['type']}* `{p['symbol']}`\n"
                f"   └ Vol: `{p['volume']}` | {pl_emoji} `${p['profit']:.2f}`\n"
            )
        self.send_message(msg)

    def notify_account_summary(self, balance, floating_pnl, position_count, active_mode):
        """Sends a periodic summary of the account and active positions."""
        emoji = "📈" if floating_pnl >= 0 else "📉"
        msg = (
            f"📊 *ACCOUNT SUMMARY*\n\n"
            f"🏦 Balance: `${balance:.2f}`\n"
            f"{emoji} Floating P/L: `${floating_pnl:.2f}`\n"
            f"📦 Active Positions: `{position_count}`\n"
            f"🤖 Mode: `{active_mode}`\n"
            f"🕒 Time: `{time.strftime('%H:%M:%S')}`"
        )
        self.send_message(msg)

    def notify_close(self, symbol, profit, reason):
        """Notification for closing a position."""
        emoji = "💰" if profit >= 0 else "❌"
        status = "PROFIT" if profit >= 0 else "LOSS"
        msg = (
            f"{emoji} *POSITION CLOSED*\n\n"
            f"📦 `{symbol}`\n"
            f"📈 Result: *{status}*\n"
            f"💵 P/L: `${profit:.2f}`\n"
            f"💡 Reason: `{reason}`\n"
            f"🕒 Time: `{time.strftime('%H:%M:%S')}`"
        )
        self.send_message(msg)

    def _poll_updates(self):
        """Polls Telegram for incoming commands and callback queries."""
        last_update_id = 0
        while not self.stop_event.is_set():
            try:
                url = f"https://api.telegram.org/bot{self.bot_token}/getUpdates?offset={last_update_id + 1}&timeout=30"
                req = urllib.request.Request(url)
                with urllib.request.urlopen(req, timeout=35) as response:
                    data = json.loads(response.read().decode('utf-8'))
                    if data.get('ok'):
                        for result in data['result']:
                            last_update_id = result['update_id']
                            
                            # Handle Callback Queries (Buttons)
                            if 'callback_query' in result:
                                self._handle_callback(result['callback_query'])
                                continue

                            # Handle Text Messages
                            message = result.get('message', {})
                            text = message.get('text', '')
                            chat_id = str(message.get('chat', {}).get('id'))
                            
                            # Security: Only respond to the owner
                            if chat_id == self.chat_id:
                                cmd = text.strip().lower()
                                
                                # Use /menu to show buttons
                                if cmd == "/menu" or cmd == "/start":
                                    self._show_main_menu()
                                elif cmd == "/status":
                                    self.send_message("🤖 Fetching Account Summary...")
                                    if self.on_status_command: self.on_status_command()
                                elif cmd in ["/positions", "/position"]:
                                    self.send_message("🤖 Fetching Open Positions...")
                                    if self.on_positions_command: self.on_positions_command()
                                elif cmd.startswith("/buy") or cmd.startswith("/sell"):
                                    # ... (existing text logic) ...
                                    # Simplified for brevity, logic remains same but truncated in this replace block
                                    self._handle_text_trade(text)

            except Exception as e:
                # logger.error(f"Polling Error: {e}")
                time.sleep(5)
            time.sleep(1)

    def _show_main_menu(self):
        """Displays the main interactive menu."""
        buttons = [
            [{"text": "📊 Status", "callback_data": "cmd_status"}, {"text": "📋 Positions", "callback_data": "cmd_positions"}],
            [{"text": "🟢 Buy XAU", "callback_data": "trade_buy_xau"}, {"text": "🔴 Sell XAU", "callback_data": "trade_sell_xau"}],
            [{"text": "🔄 Active Mode", "callback_data": "cmd_mode"}, {"text": "❌ Close All", "callback_data": "trade_close_all"}]
        ]
        self.send_keyboard("🎮 *Control Panel*", buttons)

    def _handle_callback(self, callback):
        """Processes button clicks."""
        try:
            callback_id = callback['id']
            data = callback.get('data', '')
            chat_id = str(callback.get('from', {}).get('id'))
            
            if chat_id != self.chat_id: return

            # Answer callback to stop loading animation
            self._answer_callback(callback_id)
            
            if data == "cmd_status":
                if self.on_status_command: self.on_status_command()
            elif data == "cmd_positions":
                if self.on_positions_command: self.on_positions_command()
            elif data == "trade_buy_xau":
                if self.on_trade_command: self.on_trade_command("BUY", "XAUUSDm", 0.01)
            elif data == "trade_sell_xau":
                if self.on_trade_command: self.on_trade_command("SELL", "XAUUSDm", 0.01)
            elif data == "trade_close_all":
                # Close all for XAUUSDm example
                if self.on_trade_command: self.on_trade_command("CLOSE_ALL", "XAUUSDm", 0)

        except Exception as e:
            logger.error(f"Callback Error: {e}")

    def _answer_callback(self, callback_id):
        try:
            url = f"https://api.telegram.org/bot{self.bot_token}/answerCallbackQuery?callback_query_id={callback_id}"
            urllib.request.urlopen(url)
        except: pass

    def _handle_text_trade(self, text):
         # Logic from previous step moved here
         parts = text.strip().split()
         action = "BUY" if "buy" in parts[0].lower() else "SELL"
         symbol = None
         volume = None
         if len(parts) > 1: symbol = parts[1].upper()
         if len(parts) > 2: 
             try: volume = float(parts[2])
             except: pass
         if self.on_trade_command:
             self.on_trade_command(action, symbol, volume)
         else:
             self.send_message("⚠️ Strategy not linked.")

    # Hook for Strategy to attach its status reporter
    on_status_command = None
    on_positions_command = None
    on_trade_command = None # lambda action, symbol, volume: ...

    def notify_protection(self, symbol, message):
        """Notification for trailing stop or break-even updates."""
        msg = (
            f"🛡️ *TRADE PROTECTION*\n\n"
            f"📦 `{symbol}`\n"
            f"📝 {message}\n"
            f"🕒 Time: `{time.strftime('%H:%M:%S')}`"
        )
        self.send_message(msg)
