"""Configuration loaded from environment variables."""

import os
import sys
from pathlib import Path
from dotenv import load_dotenv

# ── Resolve paths relative to the EXE / script directory ────────
# When running as a PyInstaller bundle, __file__ points inside the
# temp extraction folder, so we use sys.executable instead.
if getattr(sys, "frozen", False):
    _BASE_DIR = Path(sys.executable).parent
else:
    _BASE_DIR = Path(__file__).resolve().parent

# Load .env from the same folder as the exe / script
load_dotenv(_BASE_DIR / ".env")

# Telegram
TELEGRAM_BOT_TOKEN: str = os.environ["TELEGRAM_BOT_TOKEN"]
ALLOWED_USER_IDS: list[int] = [
    int(uid.strip()) for uid in os.environ.get("ALLOWED_USER_IDS", "").split(",") if uid.strip()
]

# YouTube Music
YTMUSIC_BROWSER_FILE: str = os.environ.get("YTMUSIC_BROWSER_FILE", str(_BASE_DIR / "browser.json"))

# Scheduler
CHECK_INTERVAL_MINUTES: int = int(os.environ.get("CHECK_INTERVAL_MINUTES", "15"))

# Database
DB_PATH: str = os.environ.get("DB_PATH", str(_BASE_DIR / "songs.db"))
