import requests
import logging
import json

logger = logging.getLogger("Telegram")

class TelegramBot:
    def __init__(self, token, authorized_chat_id=None, connector=None):
        self.token = token
        self.chat_id = authorized_chat_id
        self.connector = connector  # Reference to MT5Connector to execute trades
        self.api_url = f"https://api.telegram.org/bot{token}"

    def send_message(self, text, chat_id=None):
        """Sends a text message to Telegram"""
        if not self.token: return
        
        target_chat = chat_id if chat_id else self.chat_id
        if not target_chat: return

        try:
            url = f"{self.api_url}/sendMessage"
            payload = {"chat_id": target_chat, "text": text, "parse_mode": "HTML"}
            requests.post(url, json=payload, timeout=5)
        except Exception as e:
            logger.error(f"Failed to send Telegram message: {e}")

    def process_webhook_update(self, update):
        """Processes incoming JSON update from Telegram Webhook"""
        try:
            if "message" not in update: return
            
            msg = update["message"]
            chat_id = str(msg.get("chat", {}).get("id"))
            text = msg.get("text", "").strip()

            # Security: Only allow authorized chat ID if set
            if self.chat_id and chat_id != str(self.chat_id):
                logger.warning(f"Unauthorized command from ChatID: {chat_id}")
                return

            self._handle_command(text, chat_id)
            
        except Exception as e:
            logger.error(f"Error processing Telegram update: {e}")

    def _handle_command(self, text, chat_id):
        """Parses text commands and triggers bot actions"""
        cmd_parts = text.split()
        command = cmd_parts[0].lower()
        
        response = ""
        
        if command == "/start":
            response = "🤖 <b>MT5 Bot Online</b>\nCommands:\n/buy [lot] - Buy Market\n/sell [lot] - Sell Market\n/close_win - Close Profits\n/close_all - Close All\n/status - Account Info"
            
        elif command == "/status":
            if self.connector and self.connector.account_info:
                info = self.connector.account_info
                response = (f"📊 <b>Account Status</b>\n"
                            f"Balance: ${info.get('balance', 0):.2f}\n"
                            f"Equity: ${info.get('equity', 0):.2f}\n"
                            f"Profit: ${info.get('profit', 0):.2f}")
            else:
                response = "⚠️ No connection to MT5 Terminal."

        elif command in ["/buy", "/sell"]:
            action = "BUY" if command == "/buy" else "SELL"
            lot = 0.01
            if len(cmd_parts) > 1:
                try: lot = float(cmd_parts[1])
                except: pass
            
            if self.connector:
                self.connector.send_order(action, "XAUUSD", lot, 0, 0)
                response = f"✅ <b>Order Sent:</b> {action} {lot} XAUUSD"
            else:
                response = "❌ Connector not ready."

        elif command == "/close_all":
            if self.connector:
                self.connector.close_position("XAUUSD", "ALL")
                response = "⚠️ Closing ALL positions..."
                
        elif command == "/close_win":
            if self.connector:
                self.connector.close_position("XAUUSD", "WIN")
                response = "💰 Closing PROFITABLE positions..."

        if response:
            self.send_message(response, chat_id)