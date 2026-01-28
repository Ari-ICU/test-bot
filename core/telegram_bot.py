import requests
import logging
import json
import threading
import time

# Define a logger specifically for Telegram-related errors
logger = logging.getLogger("Telegram")

import queue

class TelegramBot:
    def __init__(self, token, authorized_chat_id=None, connector=None):
        self.token = token
        self.chat_id = authorized_chat_id
        self.connector = connector
        self.risk_manager = None
        self.api_url = f"https://api.telegram.org/bot{token}"
        self.last_update_id = 0
        self.is_polling = False
        self.message_queue = queue.Queue()
        self.last_analysis = {
            "prediction": "NEUTRAL",
            "patterns": "Scanning...",
            "sentiment": "NEUTRAL"
        }
        # Start the message worker thread
        threading.Thread(target=self._message_worker, daemon=True).start()

    def start_polling(self):
        """Starts a background thread to poll for commands"""
        if not self.token or self.is_polling: return
        self.is_polling = True
        threading.Thread(target=self._polling_loop, daemon=True).start()
        logger.info("📡 Telegram Command Polling Started.")

    def stop_polling(self):
        """Stops the telegram polling loop"""
        self.is_polling = False
        logger.info("🛑 Telegram Command Polling Stopped.")

    def _polling_loop(self):
        while self.is_polling:
            try:
                url = f"{self.api_url}/getUpdates"
                params = {"offset": self.last_update_id + 1, "timeout": 30}
                resp = requests.get(url, params=params, timeout=35).json()
                
                if resp.get("ok"):
                    for update in resp.get("result", []):
                        self.last_update_id = update["update_id"]
                        logger.info(f"📩 Telegram Update Received: ID {self.last_update_id}")
                        self.process_webhook_update(update)
                else:
                    logger.error(f"❌ Telegram API Error (getUpdates): {resp}")
            except Exception as e:
                logger.debug(f"❌ Telegram Polling Loop Error (Quiet): {e}")
                time.sleep(5) # Error backoff
            if self.is_polling: time.sleep(1)

    def set_risk_manager(self, risk_manager):
        self.risk_manager = risk_manager

    def track_analysis(self, prediction, patterns, sentiment):
        """Updates the internal cache for the /analysis command"""
        self.last_analysis = {
            "prediction": prediction,
            "patterns": patterns if patterns else "None detected",
            "sentiment": sentiment
        }

    def _message_worker(self):
        """Worker thread that processes the message queue with rate limiting"""
        while True:
            try:
                text, chat_id = self.message_queue.get()
                if not text: continue
                
                target_chat = chat_id if chat_id else self.chat_id
                if not target_chat: continue

                url = f"{self.api_url}/sendMessage"
                payload = {
                    "chat_id": target_chat, 
                    "text": text, 
                    "parse_mode": "HTML",
                    "disable_web_page_preview": True,
                    "disable_notification": "Heartbeat" in text or "Scanning" in text
                }
                
                resp = requests.post(url, json=payload, timeout=15).json()
                if not resp.get("ok"):
                    desc = resp.get('description', '')
                    if "Too Many Requests" in desc:
                        # Extract wait time or default to 10s
                        retry_after = 10
                        try:
                            import re
                            match = re.search(r"after (\d+)", desc)
                            if match: retry_after = int(match.group(1))
                        except: pass
                        logger.warning(f"⏳ Telegram Rate Limit: Waiting {retry_after}s...")
                        time.sleep(retry_after)
                        self.message_queue.put((text, chat_id)) # Re-queue
                    else:
                        logger.error(f"❌ Telegram SendMessage Failed: {desc} | Chat ID: {target_chat}")
                else:
                    logger.debug(f"📤 Telegram Message Sent to {target_chat}")
                
                # Minimum delay between messages to stay safe (30 msgs/sec limit, but let's be conservative)
                time.sleep(0.5) 
            except Exception as e:
                logger.error(f"❌ Telegram Worker Error: {e}")
                time.sleep(1)
            finally:
                self.message_queue.task_done()

    def send_message(self, text, chat_id=None):
        """Adds a message to the queue to be sent asynchronously and rate-limited"""
        if not self.token: 
            logger.warning("⚠️ Telegram: No bot token provided.")
            return
        self.message_queue.put((text, chat_id))

    def process_webhook_update(self, update):
        """Processes incoming JSON update from Telegram Webhook"""
        try:
            if "message" not in update: return
            msg = update["message"]
            chat_id = str(msg.get("chat", {}).get("id"))
            text = msg.get("text", "").strip()

            if self.chat_id and chat_id != str(self.chat_id):
                logger.warning(f"⚠️ Telegram: Unauthorized access attempt from ID {chat_id}")
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
                pos_list = self.connector.get_open_positions() 
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
            is_blocked, headline, link = is_high_impact_news_near(sym)
            news_str = headline if headline else "No major news"
            if link: news_str += f"\n<a href='{link}'>🔗 Read More</a>"
            
            la = self.last_analysis
            response = (
                f"🔍 <b>Market Analysis: {sym} ({tf})</b>\n\n"
                f"🤖 <b>AI Prediction:</b> {la['prediction']}\n"
                f"📰 <b>News:</b> {news_str}\n"
                f"📊 <b>Pattern:</b> {la['patterns']}\n"
                f"⚡ <b>Sentiment:</b> {la['sentiment']}\n\n"
                "<i>Use Dashboard for deep confluence logs.</i>"
            )

        # 4b. /NEWS - Real-Time Feed & Calendar
        elif command == "/news":
            sym = self.connector.active_symbol if self.connector else "XAUUSDm"
            from filters.news import is_high_impact_news_near, analyze_sentiment, _manager as nm
            
            is_blocked, headline, link = is_high_impact_news_near(sym)
            upcoming = nm.get_calendar_summary(sym, count=3)
            sent_type, sent_text = analyze_sentiment(sym)
            
            status = "🔴 BLOCKED" if is_blocked else "🟢 CLEAR"
            
            response = (
                f"📰 <b>REAL-TIME NEWS & CALENDAR</b>\n"
                f"📦 Asset: <b>{sym}</b> | 🚦 Status: <b>{status}</b>\n\n"
                f"📡 <b>Sentiment:</b> {sent_type}\n"
                f"<i>{sent_text}</i>\n\n"
                f"🗓 <b>Upcoming Calendar:</b>\n"
            )
            
            for ev in upcoming:
                impact_icon = "🔥" if ev['impact'] == "High" else "⚠️" if ev['impact'] == "Medium" else "ℹ️"
                # Calculate deviation if actual exists
                dev_str = ""
                if ev['actual'] != '-' and ev['forecast'] != '-':
                    try:
                        # Simple calculation: if Actual > Forecast for USD, it's usually bullish
                        response += f"{impact_icon} {ev['time']} | {ev['title']}\n"
                        response += f"   └ Act: <b>{ev['actual']}</b> | For: {ev['forecast']} | Prev: {ev['previous']}\n"
                    except: 
                        response += f"{impact_icon} {ev['time']} | {ev['title']}\n"
                        response += f"   └ Act: {ev['actual']} | For: {ev['forecast']}\n"
                else:
                    response += f"{impact_icon} {ev['time']} | {ev['title']}\n"
                    response += f"   └ For: <b>{ev['forecast']}</b> | Prev: {ev['previous']}\n"
            
            response += f"\n🔗 <a href='https://www.forexfactory.com/calendar'>Forex Factory Calendar</a>"

        # 5. /SETTINGS 
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

            # 1. Define Emojis & Styles based on content keywords (Case-insensitive check)
            msg_u = msg.upper()
            if "TP HIT" in msg_u or "PROFIT" in msg_u: emoji, header = "💰", "TAKE PROFIT"
            elif "SL HIT" in msg_u or "LOSS" in msg_u: emoji, header = "🛑", "STOP LOSS"
            elif "SIGNAL DETECTED" in msg_u: emoji, header = "🎯", "SIGNAL DETECTED"
            elif "TF SUMMARY" in msg_u: emoji, header = "📊", "TF SUMMARY"
            elif "HEARTBEAT" in msg_u: emoji, header = "💓", "HEARTBEAT"
            elif "EXECUTED" in msg_u or "TRADE OPENED" in msg_u: emoji, header = "🚀", "TRADE OPENED"
            elif "ENGINE TRANSITION" in msg_u: emoji, header = "⚡", "ENGINE STATUS"
            elif record.levelno >= logging.ERROR: emoji, header = "🚨", "ERROR"
            elif record.levelno >= logging.WARNING: emoji, header = "⚠️", "WARNING"
            else: emoji, header = "ℹ️", "INFO"

            # 2. Format the Message
            import html
            clean_msg = html.escape(msg.replace("EXECUTING:", "").strip())
            formatted_text = f"{emoji} <b>{header}</b>\n{clean_msg}"

            # 3. Send in BACKGROUND THREAD (Non-blocking)
            threading.Thread(target=self.bot.send_message, args=(formatted_text,), daemon=True).start()
            
        except Exception:
            self.handleError(record)