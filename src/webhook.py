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
        
        # --- Hooks for Strategy (External Logic) ---
        self.on_status_command = None
        self.on_positions_command = None
        self.on_mode_command = None
        self.on_trade_command = None    # lambda action, symbol, volume: ...
        self.on_close_command = None    # lambda ticket_id: ...
        self.on_news_command = None     # lambda: ... (New Hook)

        if self.enabled:
            logger.info("Telegram Webhook Alert initialized.")
            # Start Polling for commands
            self.stop_event = threading.Event()
            self.poll_thread = threading.Thread(target=self._poll_updates, daemon=True)
            self.poll_thread.start()
            
            # Register Commands
            self._register_commands()
        else:
            logger.warning("Telegram Webhook Alert: Missing bot_token or chat_id. Alerts disabled.")

    # ---------------------------------------------------------
    # SENDING METHODS
    # ---------------------------------------------------------

    def send_message(self, message):
        """Sends a message to Telegram in a non-blocking thread."""
        if not self.enabled: return
        threading.Thread(target=self._send_sync, args=(message,), daemon=True).start()

    def _send_sync(self, message):
        try:
            url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
            data = urllib.parse.urlencode({
                'chat_id': self.chat_id,
                'text': message,
                'parse_mode': 'Markdown'
            }).encode('utf-8')
            
            req = urllib.request.Request(url, data=data)
            with urllib.request.urlopen(req, timeout=10) as response:
                pass
        except Exception as e:
            logger.error(f"Failed to send Telegram alert: {e}")

    def send_keyboard(self, message, buttons):
        """Sends a message with an inline keyboard."""
        if not self.enabled: return
        threading.Thread(target=self._send_keyboard_sync, args=(message, buttons), daemon=True).start()

    def _send_keyboard_sync(self, message, buttons):
        try:
            url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
            payload = {
                'chat_id': self.chat_id,
                'text': message,
                'parse_mode': 'Markdown',
                'reply_markup': json.dumps({"inline_keyboard": buttons})
            }
            data = urllib.parse.urlencode(payload).encode('utf-8')
            req = urllib.request.Request(url, data=data)
            with urllib.request.urlopen(req, timeout=10): pass 
        except Exception as e:
            logger.error(f"Failed to send Telegram keyboard: {e}")

    # ---------------------------------------------------------
    # NOTIFICATION FORMATTERS
    # ---------------------------------------------------------

    def notify_trade(self, action, symbol, volume, sl, tp, reason):
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

    def notify_active_positions(self, positions_list):
        """
        Sends a detailed list of all open positions.
        Each position gets a specific 'Close' button for single selection closing.
        """
        if not positions_list:
            self.send_message("📭 *No Active Positions*")
            return

        msg = "📋 *SELECT POSITION TO CLOSE*"
        buttons = []
        
        for p in positions_list:
            emoji = "🟢" if p['type'] == 'BUY' else "🔴"
            pl_emoji = "💵" if p['profit'] >= 0 else "🔻"
            
            # Button Text: "❌ Close BUY XAUUSD (+$10.50)"
            btn_text = f"❌ Close {p['type']} {p['symbol']} ({pl_emoji}{p['profit']:.2f})"
            # Data: close_ticket_12345678
            callback_data = f"close_ticket_{p['ticket']}"
            
            buttons.append([{"text": btn_text, "callback_data": callback_data}])
            
            msg += (
                f"\n\n{emoji} *{p['type']}* `{p['symbol']}`\n"
                f"   └ Vol: `{p['volume']}` | {pl_emoji} `${p['profit']:.2f}`\n"
                f"   └ Ticket: `{p['ticket']}`"
            )
            
        # Add a "Refresh" button at the bottom
        buttons.append([{"text": "🔄 Refresh List", "callback_data": "cmd_positions"}])
        
        self.send_keyboard(msg, buttons)

    def notify_news(self, title, sentiment, score, impact="Medium"):
        """Specifically formatted notification for news."""
        emoji = "🔥" if sentiment == "BEARISH" else "🚀" if sentiment == "BULLISH" else "ℹ️"
        msg = (
            f"{emoji} *NEWS UPDATE*\n\n"
            f"📰 *{title}*\n"
            f"📊 Sentiment: {sentiment} ({score})\n"
            f"💥 Impact: {impact}\n"
            f"🕒 Time: `{time.strftime('%H:%M:%S')}`"
        )
        self.send_message(msg)

    def notify_account_summary(self, balance, floating_pnl, position_count, active_mode):
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

    def notify_protection(self, symbol, message):
        msg = (
            f"🛡️ *TRADE PROTECTION*\n\n"
            f"📦 `{symbol}`\n"
            f"📝 {message}\n"
            f"🕒 Time: `{time.strftime('%H:%M:%S')}`"
        )
        self.send_message(msg)

    # ---------------------------------------------------------
    # INTERACTION & COMMANDS
    # ---------------------------------------------------------

    def _register_commands(self):
        try:
            url = f"https://api.telegram.org/bot{self.bot_token}/setMyCommands"
            commands = [
                {"command": "menu", "description": "Show Main Control Panel"},
                {"command": "status", "description": "Account Balance & P/L"},
                {"command": "positions", "description": "Manage Open Trades"},
                {"command": "news", "description": "Check Market News"},
                {"command": "help", "description": "Show available commands"}
            ]
            data = json.dumps({"commands": commands}).encode('utf-8')
            req = urllib.request.Request(url, data=data, headers={'Content-Type': 'application/json'})
            with urllib.request.urlopen(req, timeout=10): pass
        except Exception as e:
            logger.warning(f"Failed to register Telegram commands: {e}")

    def _show_main_menu(self):
        """Displays the main interactive menu with Close Single and News options."""
        buttons = [
            # Row 1: Info
            [{"text": "📊 Status", "callback_data": "cmd_status"}, {"text": "📋 Positions / Close", "callback_data": "cmd_positions"}],
            # Row 2: Manual Trade
            [{"text": "🟢 Buy XAU", "callback_data": "trade_buy_xau"}, {"text": "🔴 Sell XAU", "callback_data": "trade_sell_xau"}],
            # Row 3: Tools
            [{"text": "🔄 Active Mode", "callback_data": "cmd_mode"}, {"text": "📰 Market News", "callback_data": "cmd_news"}],
            # Row 4: Emergency
            [{"text": "❌ CLOSE ALL TRADES", "callback_data": "trade_close_all"}]
        ]
        self.send_keyboard("🎮 *Control Panel*", buttons)

    def _poll_updates(self):
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
                            
                            if 'callback_query' in result:
                                self._handle_callback(result['callback_query'])
                                continue

                            message = result.get('message', {})
                            text = message.get('text', '')
                            chat_id = str(message.get('chat', {}).get('id'))
                            
                            if chat_id == self.chat_id:
                                cmd = text.strip().lower()
                                
                                if cmd in ["/menu", "/start"]:
                                    self._show_main_menu()
                                elif cmd == "/status":
                                    self.send_message("🤖 Fetching Account Summary...")
                                    if self.on_status_command: self.on_status_command()
                                elif cmd in ["/positions", "/position"]:
                                    self.send_message("🤖 Fetching Open Positions...")
                                    if self.on_positions_command: self.on_positions_command()
                                elif cmd == "/news":
                                    self.send_message("🤖 Checking Market News...")
                                    if self.on_news_command: self.on_news_command()
                                elif cmd.startswith("/buy") or cmd.startswith("/sell"):
                                    self._handle_text_trade(text)

            except Exception as e:
                time.sleep(5)
            time.sleep(1)

    def _handle_callback(self, callback):
        try:
            callback_id = callback['id']
            data = callback.get('data', '')
            chat_id = str(callback.get('from', {}).get('id'))
            
            if chat_id != self.chat_id: return
            self._answer_callback(callback_id)
            
            # --- Status & Info ---
            if data == "cmd_status":
                if self.on_status_command: self.on_status_command()
            elif data == "cmd_positions":
                # Triggers notify_active_positions logic in strategy
                if self.on_positions_command: self.on_positions_command()
            elif data == "cmd_news":
                if self.on_news_command: self.on_news_command()
            elif data == "cmd_mode":
                if self.on_mode_command: self.on_mode_command()
            
            # --- Trading ---
            elif data.startswith("close_ticket_"):
                # Handle single position close
                ticket_id = data.split("_")[2]
                if self.on_close_command: self.on_close_command(ticket_id)
            
            elif data == "trade_buy_xau":
                if self.on_trade_command: self.on_trade_command("BUY", "XAUUSDm", 0.01)
            elif data == "trade_sell_xau":
                if self.on_trade_command: self.on_trade_command("SELL", "XAUUSDm", 0.01)
            elif data == "trade_close_all":
                if self.on_trade_command: self.on_trade_command("CLOSE_ALL", "XAUUSDm", 0)

        except Exception as e:
            logger.error(f"Callback Error: {e}")

    def _answer_callback(self, callback_id):
        try:
            url = f"https://api.telegram.org/bot{self.bot_token}/answerCallbackQuery?callback_query_id={callback_id}"
            urllib.request.urlopen(url)
        except: pass

    def _handle_text_trade(self, text):
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