"""SQLite database for tracking posted songs."""

from __future__ import annotations

import aiosqlite

from config import DB_PATH


async def init_db() -> None:
    """Create tables if they don't exist."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS posted_songs (
                video_id   TEXT PRIMARY KEY,
                title      TEXT NOT NULL,
                artists    TEXT NOT NULL,
                album      TEXT DEFAULT '',
                duration   TEXT DEFAULT '',
                posted_at  TEXT DEFAULT (datetime('now'))
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS user_settings (
                user_id    INTEGER PRIMARY KEY,
                channel_id TEXT,
                is_active  INTEGER DEFAULT 1
            )
        """)
        await db.commit()


async def is_posted(video_id: str) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "SELECT 1 FROM posted_songs WHERE video_id = ?", (video_id,)
        )
        return await cursor.fetchone() is not None


async def mark_posted(
    video_id: str, title: str, artists: str, album: str = "", duration: str = ""
) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR IGNORE INTO posted_songs (video_id, title, artists, album, duration) "
            "VALUES (?, ?, ?, ?, ?)",
            (video_id, title, artists, album, duration),
        )
        await db.commit()


async def get_all_posted_ids() -> set[str]:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT video_id FROM posted_songs")
        return {row[0] for row in await cursor.fetchall()}


async def save_channel(user_id: int, channel_id: str) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO user_settings (user_id, channel_id, is_active) VALUES (?, ?, 1) "
            "ON CONFLICT(user_id) DO UPDATE SET channel_id=excluded.channel_id, is_active=1",
            (user_id, channel_id),
        )
        await db.commit()


async def get_channel(user_id: int) -> str | None:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "SELECT channel_id FROM user_settings WHERE user_id = ? AND is_active = 1",
            (user_id,),
        )
        row = await cursor.fetchone()
        return row[0] if row else None


async def set_active(user_id: int, active: bool) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE user_settings SET is_active = ? WHERE user_id = ?",
            (int(active), user_id),
        )
        await db.commit()


async def get_all_active_users() -> list[dict]:
    """Return all users with an active channel set."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT user_id, channel_id FROM user_settings WHERE is_active = 1 AND channel_id IS NOT NULL"
        )
        return [dict(row) for row in await cursor.fetchall()]
