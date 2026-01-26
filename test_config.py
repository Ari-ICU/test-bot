from bot_settings import Config
import os
from dotenv import load_dotenv

load_dotenv()
conf = Config()
print(f"TELEGRAM_BOT_TOKEN from env: {os.getenv('TELEGRAM_BOT_TOKEN')}")
print(f"telegram.bot_token from config: {conf.get('telegram.bot_token')}")
print(f"telegram.chat_id from config: {conf.get('telegram.chat_id')}")
