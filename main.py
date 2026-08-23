"""Entry point – starts the Telegram bot, scheduler, and system tray icon."""

import logging
import sys
import threading

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

import database as db
from bot import build_app, scheduled_check
from config import CHECK_INTERVAL_MINUTES


# ── System tray icon (Windows notification area) ────────────────

def _create_tray_icon():
    """Create and run a pystray icon in the Windows system tray."""
    try:
        import pystray
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        logging.getLogger(__name__).warning("pystray/Pillow not installed, no tray icon")
        return None

    # Draw a simple green music note icon
    size = 64
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    # Green circle background
    draw.ellipse([4, 4, 60, 60], fill=(76, 175, 80, 255))
    # White music note ♪
    try:
        font = ImageFont.truetype("segoeui.ttf", 36)
    except OSError:
        font = ImageFont.load_default()
    bbox = draw.textbbox((0, 0), "♪", font=font)
    w, h = bbox[2] - bbox[0], bbox[3] - bbox[1]
    draw.text(((size - w) / 2 - bbox[0], (size - h) / 2 - bbox[1] - 4),
              "♪", fill="white", font=font)

    def on_show_status(icon, item):
        """Show a Windows balloon notification with bot status."""
        icon.notify("YT Music Bot работает!\nАвтопроверка каждые 15 мин.",
                    title="YT Music Bot")

    def on_exit(icon, item):
        icon.stop()
        import os
        os._exit(0)

    menu = pystray.Menu(
        pystray.MenuItem("📊 Статус", on_show_status, default=True),
        pystray.MenuItem("❌ Выход", on_exit),
    )

    icon = pystray.Icon(
        "YTMusicBot",
        img,
        title="YT Music Bot",
        menu=menu,
    )
    return icon


def main() -> None:
    # ── Logging setup: file + console ────────────────────────────
    fmt = "%(asctime)s [%(name)s] %(levelname)s: %(message)s"
    log_file = "bot.log"

    # File handler (always)
    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setFormatter(logging.Formatter(fmt))
    file_handler.setLevel(logging.DEBUG)

    # Console handler (only if running in a terminal)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(logging.Formatter(fmt))
    console_handler.setLevel(logging.INFO)

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)
    root_logger.addHandler(file_handler)
    root_logger.addHandler(console_handler)

    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("apscheduler").setLevel(logging.INFO)

    logger = logging.getLogger(__name__)
    logger.info("=== Starting YT Music Telegram Bot ===")
    logger.info("Log file: %s", log_file)

    # ── Start tray icon in a background thread ────────────────────
    tray_icon = _create_tray_icon()
    if tray_icon:
        tray_thread = threading.Thread(target=tray_icon.run, daemon=True)
        tray_thread.start()
        logger.info("Tray icon started")

    # ── Launch Edge with debug port for auto cookie refresh ──────
    from config import BROWSER
    from yt_music import YTMusicService
    if not YTMusicService._is_chrome_debug_running():
        logger.info("Launching %s with debug port for cookie auto-refresh...", BROWSER)
        ok = YTMusicService._launch_chrome_with_debug()
        if ok:
            logger.info("%s debug port active", BROWSER)
            if tray_icon:
                try:
                    tray_icon.notify(
                        f"{BROWSER.title()} opened for cookie refresh.\n"
                        "Log in to YouTube Music once.",
                        title="YT Music Bot",
                    )
                except Exception:
                    pass
        else:
            logger.warning("Could not launch %s with debug port", BROWSER)
    else:
        logger.info("%s debug port active", BROWSER)

    # ── Telegram bot + scheduler ──────────────────────────────────
    app = build_app()
    scheduler = AsyncIOScheduler()

    async def post_init(application) -> None:
        logger.info("Initializing database…")
        await db.init_db()
        logger.info("Database initialized OK")

        scheduler.add_job(
            scheduled_check,
            trigger=IntervalTrigger(minutes=CHECK_INTERVAL_MINUTES),
            args=[application],
            id="liked_songs_check",
            replace_existing=True,
            name="Check liked songs",
        )
        scheduler.start()
        logger.info("Scheduler started – checking every %d minutes", CHECK_INTERVAL_MINUTES)

        # Update tray tooltip with status
        if tray_icon:
            tray_icon.title = f"YT Music Bot ✅ (check every {CHECK_INTERVAL_MINUTES}m)"

    async def post_shutdown(application) -> None:
        if scheduler.running:
            scheduler.shutdown(wait=False)
        logger.info("Bot shut down.")

    app.post_init = post_init
    app.post_shutdown = post_shutdown

    logger.info("Starting polling…")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
