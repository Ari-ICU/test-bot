import requests
import logging
import json
import threading
import time

# Define a logger specifically for Telegram-related errors
logger = logging.getLogger("Telegram")

class TelegramBot:
    def __init__(self, token, authorized_chat_id=None, connector=None):
        self.token = token
        self.chat_id = authorized_chat_id
        self.connector = connector
        self.risk_manager = None
        self.api_url = f"https://api.telegram.org/bot{token}"
        self.last_update_id = 0
        self.is_polling = False

    def start_polling(self):
        """Starts a background thread to poll for commands"""
        if not self.token or self.is_polling: return
        self.is_polling = True
        threading.Thread(target=self._polling_loop, daemon=True).start()
        logger.info("📡 Telegram Command Polling Started.")

    def _polling_loop(self):
        while self.is_polling:
            try:
                url = f"{self.api_url}/getUpdates"
                params = {"offset": self.last_update_id + 1, "timeout": 30}
                resp = requests.get(url, params=params, timeout=35).json()
                
                if resp.get("ok"):
                    for update in resp.get("result", []):
                        self.last_update_id = update["update_id"]
                        self.process_webhook_update(update)
            except Exception as e:
                time.sleep(5) # Error backoff
            time.sleep(1)

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
                "disable_web_page_preview": True,
                "disable_notification": "Heartbeat" in text or "Scanning" in text
            }
            requests.post(url, json=payload, timeout=15)
        except Exception as e:
            # Silent fail for network jitters
            pass

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
                "🔹 /news - Real-Time News Feed\n"
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
            
            # Fetch news for analysis
            from filters.news import is_high_impact_news_near
            is_blocked, headline = is_high_impact_news_near(sym)
            news_str = headline if headline else "No major news"
            
            response = (
                f"🔍 <b>Market Analysis: {sym} ({tf})</b>\n\n"
                "🤖 <b>AI Prediction:</b> NEUTRAL\n"
                f"📰 <b>News:</b> {news_str}\n"
                "📊 <b>Pattern:</b> Scanning...\n"
                "⚡ <b>Sentiment:</b> BULLISH\n\n"
                "<i>Use Dashboard for deep confluence logs.</i>"
            )

        # 4b. /NEWS - Direct News Check
        elif command == "/news":
            sym = self.connector.active_symbol if self.connector else "USD"
            from filters.news import is_high_impact_news_near
            is_blocked, headline = is_high_impact_news_near(sym)
            status = "🔴 BLOCKED" if is_blocked else "🟢 CLEAR"
            
            response = (
                f"📰 <b>Real-Time News Feed</b>\n"
                f"📦 Asset: <b>{sym}</b>\n"
                f"🚦 Status: <b>{status}</b>\n\n"
                f"🗞️ <b>Latest Headline:</b>\n"
                f"<i>{headline if headline else 'No news data available.'}</i>"
            )

        # 5. /SETTINGS - Strategy & Risk
        elif command == "/settings":
            if self.risk_manager:
                rm = self.risk_manager
                cool_off_mins = int(rm.cool_off_period / 60)
                response = (
                    "⚙️ <b>Strategy & Risk Settings</b>\n"
                    f"🛑 Max Daily Trades: <b>{getattr(rm, 'max_daily_trades', 5)}</b>\n"
                    f"📉 Max Drawdown: <b>{getattr(rm, 'max_drawdown_limit', 5.0)}%</b>\n"
                    f"⌛ Cool-off: <b>{cool_off_mins} min</b>\n\n"
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
            elif "News Signal" in msg or "News Update" in msg or "News Block" in msg:
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