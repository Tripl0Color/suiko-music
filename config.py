"""Configuration loaded from environment variables."""

import os
from dotenv import load_dotenv

load_dotenv()

# Telegram
TELEGRAM_BOT_TOKEN: str = os.environ["TELEGRAM_BOT_TOKEN"]
ALLOWED_USER_IDS: list[int] = [
    int(uid.strip()) for uid in os.environ.get("ALLOWED_USER_IDS", "").split(",") if uid.strip()
]

# YouTube Music
YTMUSIC_BROWSER_FILE: str = os.environ.get("YTMUSIC_BROWSER_FILE", "browser.json")

# Scheduler
CHECK_INTERVAL_MINUTES: int = int(os.environ.get("CHECK_INTERVAL_MINUTES", "15"))

# Database
DB_PATH: str = os.environ.get("DB_PATH", "songs.db")
