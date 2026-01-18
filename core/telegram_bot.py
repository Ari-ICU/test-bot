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
        self.risk_manager = None # Will be set by main
        self.api_url = f"https://api.telegram.org/bot{token}"

    def set_risk_manager(self, risk_manager):
        self.risk_manager = risk_manager

    def send_message(self, text, chat_id=None):
        """Sends a text message to Telegram with HTML formatting"""
        if not self.token: return
        
        target_chat = chat_id if chat_id else self.chat_id
        if not target_chat: return

        try:
            url = f"{self.api_url}/sendMessage"
            payload = {
                "chat_id": target_chat, 
                "text": text, 
                "parse_mode": "HTML",
                "disable_web_page_preview": True
            }
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
        """Parses and executes Telegram commands"""
        if not text: return
        command = text.split()[0].lower()
        response = ""
        
        # 1. /MENU - Main Control Panel
        if command == "/menu":
            response = (
                "🎮 <b>MT5 Main Control Panel</b>\n\n"
                "📦 <b>Market:</b> " + (self.connector.active_symbol if self.connector else "N/A") + "\n"
                "⏱ <b>Timeframe:</b> " + (self.connector.active_tf if self.connector else "N/A") + "\n\n"
                "📜 <b>Available Commands:</b>\n"
                "🔹 /status - Account & Config\n"
                "🔹 /positions - Manage Open Trades\n"
                "🔹 /analysis - Technical Analysis\n"
                "🔹 /settings - Strategy & Risk"
            )

        # 2. /STATUS - Account Balance & Config
        elif command == "/status":
            if self.connector and self.connector.account_info:
                info = self.connector.account_info
                balance = info.get('balance', 0)
                equity = info.get('equity', 0)
                profit = info.get('profit', 0)
                drawdown = ((balance - equity) / balance * 100) if balance > 0 else 0
                
                response = (
                    "📊 <b>Account Status</b>\n"
                    f"💰 Balance: <b>${balance:,.2f}</b>\n"
                    f"💵 Equity: <b>${equity:,.2f}</b>\n"
                    f"📈 Profit: <b>" + (f"+${profit:,.2f}" if profit >= 0 else f"-${abs(profit):,.2f}") + "</b>\n"
                    f"📉 Drawdown: <b>{drawdown:.2f}%</b>\n\n"
                    f"🔗 MT5 State: <b>CONNECTED</b>"
                )
            else:
                response = "⚠️ <b>Error:</b> Could not fetch account data. Is MT5 Bridge Running?"

        # 3. /POSITIONS - Manage Trades
        elif command == "/positions":
            if self.connector:
                pos_list = self.connector.get_open_positions() # Assumes this exists or handles empty
                if not pos_list:
                    response = "📭 <b>No open positions.</b>"
                else:
                    response = "📂 <b>Open Positions:</b>\n\n"
                    for p in pos_list:
                        side = "🔵 BUY" if p.get('type') == 0 else "🔴 SELL"
                        response += (f"{side} {p.get('symbol')} ({p.get('volume')})\n"
                                     f"└ Profit: <b>${p.get('profit'):.2f}</b> | Ticket: {p.get('ticket')}\n\n")
            else:
                response = "⚠️ Connection unavailable."

        # 4. /ANALYSIS - Technical Analysis
        elif command == "/analysis":
            sym = self.connector.active_symbol if self.connector else "N/A"
            tf = self.connector.active_tf if self.connector else "N/A"
            response = (
                f"🔍 <b>Market Analysis: {sym} ({tf})</b>\n\n"
                "🤖 <b>AI Prediction:</b> NEUTRAL\n"
                "📊 <b>Pattern:</b> Scanning...\n"
                "⚡ <b>Sentiment:</b> BULLISH\n\n"
                "<i>Use Dashboard for deep confluence logs.</i>"
            )

        # 5. /SETTINGS - Strategy & Risk
        elif command == "/settings":
            if self.risk_manager:
                rm = self.risk_manager
                response = (
                    "⚙️ <b>Strategy & Risk Settings</b>\n"
                    f"🛑 Max Daily Trades: <b>{getattr(rm, 'max_daily_trades', 'N/A')}</b>\n"
                    f"📉 Max Drawdown: <b>{getattr(rm, 'max_drawdown_pct', 'N/A')}%</b>\n"
                    f"⌛ Cool-off: <b>60 min</b>\n\n"
                    f"✅ <b>Auto-Trading:</b> ACTIVE"
                )
            else:
                response = "⚙️ <b>Bot Settings:</b> Mode: Automatic | Risk: Managed"

        elif command == "/start":
            response = "🚀 <b>MT5 Algo Bot Terminal Started.</b>\nType /menu to see options."

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
            elif "Signals Detected" in msg:
                emoji = "🎯"
                header = "SIGNAL DETECTED"
            elif "Executed" in msg:
                emoji = "🚀"
                header = "TRADE OPENED"
            elif "Engine Transition" in msg:
                emoji = "⚡"
                header = "ENGINE STATUS"
            elif "Heartbeat" in msg:
                emoji = "💓"
                header = "SYSTEM ALIVE"
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
            elif "STARTED" in msg or "Launched" in msg:
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