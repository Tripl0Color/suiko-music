"""Entry point – starts the Telegram bot and scheduler. Verbose logging."""

import logging
import sys

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

import database as db
from bot import build_app, scheduled_check
from config import CHECK_INTERVAL_MINUTES


def main() -> None:
    # ── Logging setup: everything visible ──────────────────────────
    fmt = "%(asctime)s [%(name)s] %(levelname)s: %(message)s"
    logging.basicConfig(format=fmt, level=logging.INFO, stream=sys.stdout)

    # Quiet down noisy loggers a bit
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("apscheduler").setLevel(logging.INFO)

    # Our loggers: full verbosity
    logging.getLogger("bot").setLevel(logging.DEBUG)
    logging.getLogger("yt_music").setLevel(logging.DEBUG)
    logging.getLogger("database").setLevel(logging.DEBUG)
    logging.getLogger("config").setLevel(logging.DEBUG)

    logger = logging.getLogger(__name__)
    logger.info("=== Starting YT Music Telegram Bot ===")

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
