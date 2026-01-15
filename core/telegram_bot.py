import requests
import logging
import json

# Define a logger specifically for Telegram-related errors
logger = logging.getLogger("Telegram")

class TelegramBot:
    def __init__(self, token, authorized_chat_id=None, connector=None):
        self.token = token
        self.chat_id = authorized_chat_id
        self.connector = connector
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
            # We use print here to avoid infinite recursion with the LogHandler
            print(f"❌ Failed to send Telegram message: {e}")

    def process_webhook_update(self, update):
        """Processes incoming JSON update from Telegram Webhook"""
        try:
            if "message" not in update: return
            
            msg = update["message"]
            chat_id = str(msg.get("chat", {}).get("id"))
            text = msg.get("text", "").strip()

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
            response = "🤖 <b>MT5 Bot Online</b>\n/buy [lot]\n/sell [lot]\n/close_win\n/close_all\n/status"
            
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

# --- NEW: Log Handler for Real-Time Logs ---
class TelegramLogHandler(logging.Handler):
    """Sends log records to Telegram."""
    def __init__(self, bot):
        super().__init__()
        self.bot = bot

    def emit(self, record):
        try:
            msg = self.format(record)
            # Add Emojis based on log level
            emoji = "ℹ️"
            if record.levelno == logging.WARNING: emoji = "⚠️"
            elif record.levelno == logging.ERROR: emoji = "❌"
            elif record.levelno == logging.CRITICAL: emoji = "🚨"
            
            # Send to Telegram
            formatted_msg = f"{emoji} <b>{record.levelname}:</b> {msg}"
            self.bot.send_message(formatted_msg)
        except Exception:
            self.handleError(record)