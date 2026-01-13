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
        self.chat_id = str(chat_id) if chat_id else None
        self.enabled = bool(bot_token and chat_id)
        
        # --- Hooks for Strategy (External Logic) ---
        self.on_status_command = None
        self.on_positions_command = None
        self.on_mode_command = None         # Toggle Active/Pause
        self.on_trade_command = None        # Manual Trade
        self.on_close_command = None        # Close Ticket
        self.on_news_command = None         
        self.on_accounts_command = None     
        self.on_account_select = None       
        # -- New Hooks --
        self.on_analysis_command = None     # Request Technical Analysis
        self.on_strategy_select = None      # Change Strategy Mode (name)
        self.on_lot_change = None           # Change Lot Size (delta)

        if self.enabled:
            logger.info("Telegram Webhook Alert initialized.")
            
            # --- FIX: Ensure no webhook is blocking polling ---
            self._delete_webhook() 

            self.stop_event = threading.Event()
            self.poll_thread = threading.Thread(target=self._poll_updates, daemon=True)
            self.poll_thread.start()
            self._register_commands()
            self.send_message("🤖 **Trading Bot Online**\nSystem initialized and ready.")
        else:
            logger.warning("Telegram Webhook Alert: Missing bot_token or chat_id. Alerts disabled.")

    def _delete_webhook(self):
        """Removes any existing webhook to allow getUpdates polling."""
        try:
            url = f"https://api.telegram.org/bot{self.bot_token}/deleteWebhook"
            with urllib.request.urlopen(url, timeout=5):
                pass
            logger.info("Existing webhook deleted (if any) to enable polling.")
        except Exception as e:
            logger.warning(f"Warning: Could not delete webhook: {e}")

    # ---------------------------------------------------------
    # SENDING METHODS
    # ---------------------------------------------------------

    def send_message(self, message):
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
            with urllib.request.urlopen(req, timeout=10): pass
        except Exception as e:
            logger.error(f"Failed to send Telegram alert: {e}")

    def send_keyboard(self, message, buttons):
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
        if not positions_list:
            self.send_message("📭 *No Active Positions*")
            return

        msg = "📋 *SELECT POSITION TO CLOSE*"
        buttons = []
        
        for p in positions_list:
            emoji = "🟢" if p['type'] == 'BUY' else "🔴"
            pl_emoji = "💵" if p['profit'] >= 0 else "🔻"
            btn_text = f"❌ Close {p['type']} {p['symbol']} ({pl_emoji}{p['profit']:.2f})"
            callback_data = f"close_ticket_{p['ticket']}"
            buttons.append([{"text": btn_text, "callback_data": callback_data}])
            
            msg += (
                f"\n\n{emoji} *{p['type']}* `{p['symbol']}`\n"
                f"   └ Vol: `{p['volume']}` | {pl_emoji} `${p['profit']:.2f}`\n"
                f"   └ Ticket: `{p['ticket']}`"
            )
            
        buttons.append([{"text": "🔄 Refresh List", "callback_data": "cmd_positions"}])
        self.send_keyboard(msg, buttons)

    def notify_account_summary(self, balance, floating_pnl, position_count, active_mode, lot_size=0.01):
        emoji = "📈" if floating_pnl >= 0 else "📉"
        msg = (
            f"📊 *ACCOUNT SUMMARY*\n\n"
            f"🏦 Balance: `${balance:.2f}`\n"
            f"{emoji} Floating P/L: `${floating_pnl:.2f}`\n"
            f"📦 Active Positions: `{position_count}`\n"
            f"⚙️ Mode: `{active_mode}`\n"
            f"🎲 Lot Size: `{lot_size}`\n"
            f"🕒 Time: `{time.strftime('%H:%M:%S')}`"
        )
        self.send_message(msg)

    def notify_analysis(self, symbol, trend, rsi, macd, score, signal):
        """Displays technical analysis summary."""
        msg = (
            f"🔬 *MARKET ANALYSIS* ({symbol})\n\n"
            f"📈 Trend: `{trend}`\n"
            f"📊 RSI: `{rsi:.1f}`\n"
            f"📉 MACD: `{macd:.5f}`\n"
            f"🎯 Signal Score: `{score}`\n"
            f"🤖 Recommendation: *{signal}*"
        )
        self.send_message(msg)

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
        msg = f"🛡️ *TRADE PROTECTION*\n\n📦 `{symbol}`\n📝 {message}\n🕒 Time: `{time.strftime('%H:%M:%S')}`"
        self.send_message(msg)

    # ---------------------------------------------------------
    # INTERACTION & COMMANDS
    # ---------------------------------------------------------

    def _register_commands(self):
        try:
            url = f"https://api.telegram.org/bot{self.bot_token}/setMyCommands"
            commands = [
                {"command": "menu", "description": "Main Control Panel"},
                {"command": "status", "description": "Account Balance & Config"},
                {"command": "positions", "description": "Manage Trades"},
                {"command": "analysis", "description": "Technical Analysis"},
                {"command": "settings", "description": "Strategy & Risk"},
            ]
            data = json.dumps({"commands": commands}).encode('utf-8')
            req = urllib.request.Request(url, data=data, headers={'Content-Type': 'application/json'})
            with urllib.request.urlopen(req, timeout=10): pass
        except Exception as e:
            logger.warning(f"Failed to register Telegram commands: {e}")

    def _show_main_menu(self):
        buttons = [
            [{"text": "📊 Status", "callback_data": "cmd_status"}, {"text": "🔬 Analysis", "callback_data": "cmd_analysis"}],
            [{"text": "📋 Positions", "callback_data": "cmd_positions"}, {"text": "⚙️ Settings", "callback_data": "menu_settings"}],
            [{"text": "🟢 Buy XAU", "callback_data": "trade_buy_xau"}, {"text": "🔴 Sell XAU", "callback_data": "trade_sell_xau"}],
            [{"text": "📰 News", "callback_data": "cmd_news"}, {"text": "⏯️ Pause/Resume", "callback_data": "cmd_mode"}],
            [{"text": "❌ CLOSE ALL TRADES", "callback_data": "trade_close_all"}]
        ]
        self.send_keyboard("🎮 *Control Panel*", buttons)

    def _show_settings_menu(self):
        buttons = [
            [{"text": "🧠 Change Strategy", "callback_data": "menu_strategies"}],
            [{"text": "🎲 Lot Size -0.01", "callback_data": "lot_dec"}, {"text": "🎲 Lot Size +0.01", "callback_data": "lot_inc"}],
            [{"text": "🔑 Switch Accounts", "callback_data": "cmd_accounts"}],
            [{"text": "⬅️ Back to Menu", "callback_data": "cmd_menu"}]
        ]
        self.send_keyboard("⚙️ *Bot Settings*", buttons)

    def _show_strategy_menu(self):
        # Common strategies list
        strategies = ["MASTER_CONFLUENCE", "U16_STRATEGY", "SCALPING", "BREAKOUT", "ZONE_BOUNCE", "ICT_FVG"]
        buttons = []
        # Create rows of 2
        for i in range(0, len(strategies), 2):
            row = []
            row.append({"text": strategies[i], "callback_data": f"set_strat_{strategies[i]}"})
            if i+1 < len(strategies):
                row.append({"text": strategies[i+1], "callback_data": f"set_strat_{strategies[i+1]}"})
            buttons.append(row)
        
        buttons.append([{"text": "⬅️ Back to Settings", "callback_data": "menu_settings"}])
        self.send_keyboard("🧠 *Select Strategy Mode*", buttons)

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
                            
                            # Simple Auth Check
                            if chat_id == self.chat_id:
                                cmd = text.strip().lower()
                                
                                if cmd in ["/menu", "/start"]:
                                    self._show_main_menu()
                                elif cmd == "/settings":
                                    self._show_settings_menu()
                                elif cmd == "/status":
                                    logger.info("Received /status command")
                                    if self.on_status_command: self.on_status_command()
                                elif cmd == "/positions":
                                    if self.on_positions_command: self.on_positions_command()
                                elif cmd == "/analysis":
                                    self.send_message("🔍 Analyzing market...")
                                    if self.on_analysis_command: self.on_analysis_command()
                                elif cmd.startswith("/buy") or cmd.startswith("/sell"):
                                    self._handle_text_trade(text)
            except Exception as e:
                logger.error(f"Poll Error: {e}")
                time.sleep(5)
            time.sleep(1)

    def _handle_callback(self, callback):
        try:
            callback_id = callback['id']
            data = callback.get('data', '')
            chat_id = str(callback.get('from', {}).get('id'))
            
            if chat_id != self.chat_id: return
            self._answer_callback(callback_id)
            
            # --- Navigation ---
            if data == "cmd_menu": self._show_main_menu()
            elif data == "menu_settings": self._show_settings_menu()
            elif data == "menu_strategies": self._show_strategy_menu()
            
            # --- Commands ---
            elif data == "cmd_status":
                if self.on_status_command: self.on_status_command()
            elif data == "cmd_positions":
                if self.on_positions_command: self.on_positions_command()
            elif data == "cmd_analysis":
                if self.on_analysis_command: self.on_analysis_command()
            elif data == "cmd_news":
                if self.on_news_command: self.on_news_command()
            elif data == "cmd_accounts":
                if self.on_accounts_command: self.on_accounts_command()
            elif data == "cmd_mode":
                if self.on_mode_command: self.on_mode_command()

            # --- Settings Changes ---
            elif data.startswith("set_strat_"):
                strat_name = data.replace("set_strat_", "")
                if self.on_strategy_select: self.on_strategy_select(strat_name)
            
            elif data == "lot_inc":
                if self.on_lot_change: self.on_lot_change(0.01)
            elif data == "lot_dec":
                if self.on_lot_change: self.on_lot_change(-0.01)

            # --- Trading ---
            elif data.startswith("close_ticket_"):
                ticket_id = data.split("_")[2]
                if self.on_close_command: self.on_close_command(ticket_id)
            elif data.startswith("account_select_"):
                try:
                    idx = int(data.split("_")[2])
                    if self.on_account_select: self.on_account_select(idx)
                except: pass
            
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
         volume = 0
         if len(parts) > 1: symbol = parts[1].upper()
         if len(parts) > 2: 
             try: volume = float(parts[2])
             except: pass
         if self.on_trade_command:
             self.on_trade_command(action, symbol, volume)