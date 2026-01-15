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
            print(f"❌ Failed to send Telegram message: {e}")

    def process_webhook_update(self, update):
        """Processes incoming JSON update from Telegram Webhook"""
        try:
            if "message" not in update: return
            msg = update["message"]
            chat_id = str(msg.get("chat", {}).get("id"))
            text = msg.get("text", "").strip()

            if self.chat_id and chat_id != str(self.chat_id):
                return

            self._handle_command(text, chat_id)
        except Exception as e:
            logger.error(f"Error processing Telegram update: {e}")

    def _handle_command(self, text, chat_id):
        """Parses text commands"""
        cmd_parts = text.split()
        command = cmd_parts[0].lower()
        response = ""
        
        if command == "/start":
            response = "🤖 <b>Bot Online</b>"
        elif command == "/status":
            if self.connector and self.connector.account_info:
                info = self.connector.account_info
                response = (f"📊 <b>Status</b>\n"
                            f"💵 Bal: <b>${info.get('balance', 0):.2f}</b>\n"
                            f"📈 PnL: <b>${info.get('profit', 0):.2f}</b>")
            else:
                response = "⚠️ No connection."

        if response:
            self.send_message(response, chat_id)

# --- IMPROVED: Clean & Visual Log Handler ---
class TelegramLogHandler(logging.Handler):
    """Formats logs with emojis and HTML for Telegram"""
    def __init__(self, bot):
        super().__init__()
        self.bot = bot

    def emit(self, record):
        try:
            msg = record.getMessage()

            # 1. Define Emojis & Styles based on content keywords
            if "TP Hit" in msg or "Profit" in msg:
                emoji = "💰"
                header = "TAKE PROFIT"
            elif "SL Hit" in msg or "Loss" in msg:
                emoji = "🛑"
                header = "STOP LOSS"
            elif "EXECUTING" in msg or "Order Sent" in msg:
                emoji = "🚀"
                header = "NEW TRADE"
            elif "News Signal" in msg:
                emoji = "📰"
                header = "NEWS ALERT"
            elif record.levelno == logging.ERROR:
                emoji = "🚨"
                header = "ERROR"
            elif record.levelno == logging.WARNING:
                emoji = "⚠️"
                header = "WARNING"
            elif "Bot logic initialized" in msg or "Connector started" in msg:
                emoji = "✅"
                header = "SYSTEM"
            else:
                emoji = "ℹ️"
                header = "INFO"

            # 2. Format the Message (Clean HTML)
            clean_msg = msg.replace("EXECUTING:", "").replace("TP Hit:", "").replace("SL Hit:", "").strip()
            formatted_text = f"{emoji} <b>{header}</b>\n{clean_msg}"

            # 3. Send
            self.bot.send_message(formatted_text)
            
        except Exception:
            self.handleError(record)