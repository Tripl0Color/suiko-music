"""Telegram bot – all commands, no inline buttons. Verbose logging.

Browser-based auth (OAuth broken server-side since Sep 2025).
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any

from telegram import Bot, MessageOriginChannel, Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

import database as db
from config import ALLOWED_USER_IDS, CHECK_INTERVAL_MINUTES, TELEGRAM_BOT_TOKEN
from yt_music import YTMusicService

logger = logging.getLogger(__name__)

# ── Global service instance (created once) ─────────────────────────
yt_service = YTMusicService()


def _log_update(update: Update) -> None:
    """Log every incoming update for debugging."""
    u = update.effective_user
    msg = update.message
    cb = update.callback_query
    if u:
        logger.info(
            "[UPDATE] user=%s(%s) chat=%s text=%r callback=%r fwd_origin=%r",
            u.id, u.username, update.effective_chat.id if update.effective_chat else None,
            msg.text if msg else None,
            cb.data if cb else None,
            type(msg.forward_origin).__name__ if msg and msg.forward_origin else None,
        )
    else:
        logger.info("[UPDATE] no effective_user: %s", update)


def is_allowed(user_id: int) -> bool:
    if not ALLOWED_USER_IDS:
        return True
    return user_id in ALLOWED_USER_IDS


HELP_TEXT = """🎶 <b>YouTube Music → Telegram Bot</b>
<i>Автоматически пересылает лайкнутые треки в канал</i>

┌──────────────── <b>Управление</b> ────────────────┐
│                                                     │
│  📋 <b>Основные</b>                                  │
│  /start — Запуск и настройка                        │
│  /status — Статус бота                              │
│  /help — Эта справка                                │
│                                                     │
│  🎵 <b>Музыка</b>                                   │
│  /check — Проверить лайкнутые сейчас                │
│  /scan — Отметить треки как опубликованные          │
│  /history — Последние опубликованные треки           │
│  /clear_history — Очистить историю                  │
│                                                     │
│  🔐 <b>Авторизация</b>                               │
│  /auth — Инструкция по авторизации                   │
│  /export — Автоизвлечение cookies                    │
│  /refresh — Обновить cookies из браузера             │
│                                                     │
│  ⚙️ <b>Настройка</b>                                │
│  /channel — Указать канал                           │
│  /pause — Приостановить автопроверку                 │
│  /resume — Возобновить автопроверку                  │
│                                                     │
└─────────────────────────────────────────────────────┘
"""


AUTH_INSTRUCTIONS = """🔐 <b>Авторизация YouTube Music</b>

Бот использует браузер Edge для доступа к YouTube Music.
Авторизация работает автоматически — Edge открывается при запуске.

┌─────────── <b>Если бот не находит треки</b> ───────────┐
│                                                      │
│  1. Убедись что Edge открыт с YouTube Music          │
│  2. Проверь что залогинен нужным аккаунтом            │
│  3. Напиши /check для ручной проверки               │
│                                                      │
└──────────────────────────────────────────────────────┘

<b>Ручная авторизация (если Edge не помогает):</b>

🔹 <b>Вставь куки прямо в чат</b>
Скопируй cookies из браузера (F12 → Application → Cookies)
и вставь как сообщение.

🔹 <b>Загрузи файл</b>
Отправь <code>browser.json</code> или <code>cookies.txt</code> боту.

⏰ Cookies истекают через 2-4 недели.
"""


# ╔══════════════════════════════════════════════════════════════════╗
# ║  /start                                                         ║
# ╚══════════════════════════════════════════════════════════════════╝


async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    _log_update(update)
    user = update.effective_user
    if not user or not is_allowed(user.id):
        logger.warning("[START] user=%s denied access", user.id if user else "?")
        await update.message.reply_text("⛔ У вас нет доступа к этому боту.")
        return

    channel = await db.get_channel(user.id)
    logger.info(
        "[START] user=%s yt_authorized=%s channel=%s",
        user.id, yt_service.is_authorized, channel,
    )

    if yt_service.is_authorized and channel:
        await update.message.reply_text(
            "🎶 <b>YouTube Music Bot</b>\n"
            "<i>Работаю и слушаю твои лайки!</i>\n\n"
            "┌────────────────────────────────┐\n"
            f"│  📺 Канал: <b>{channel}</b>\n"
            f"│  🔄 Автопроверка: каждые {CHECK_INTERVAL_MINUTES} мин.\n"
            "│  🌐 Браузер: Edge (CDP)\n"
            "└────────────────────────────────┘\n\n"
            "📋 <b>Быстрые команды:</b>\n"
            "  /check — проверить сейчас\n"
            "  /status — подробный статус\n"
            "  /pause — приостановить\n"
            "  /help — все команды",
            parse_mode="HTML",
        )
        return

    await update.message.reply_text(
        "🎶 <b>YouTube Music → Telegram Bot</b>\n"
        "<i>Автоматически пересылает лайкнутые треки в канал</i>\n\n"
        "┌────────────────────────────────┐\n"
        "│  <b>Первый запуск</b>               │\n"
        "│                                │\n"
        f"│  {'' if yt_service.is_authorized else '1️⃣ '}/auth — авторизация\n"
        f"│  {'' if channel else '2️⃣ '}/channel — выбрать канал\n"
        "│                                │\n"
        "│  После настройки бот будет\n"
        "│  автоматически проверять\n"
        "│  лайкнутые треки каждые\n"
        f"│  {CHECK_INTERVAL_MINUTES} минут! 🎉               │\n"
        "└────────────────────────────────┘",
        parse_mode="HTML",
    )


# ╔══════════════════════════════════════════════════════════════════╗
# ║  /status                                                        ║
# ╚══════════════════════════════════════════════════════════════════╝


async def cmd_status(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    _log_update(update)
    user = update.effective_user
    if not user or not is_allowed(user.id):
        return

    channel = await db.get_channel(user.id)
    yt_status = "✅ Авторизован" if yt_service.is_authorized else "❌ Не авторизован"
    ch_status = channel if channel else "❌ Не указан"
    posted_ids = await db.get_all_posted_ids()
    logger.info(
        "[STATUS] user=%s yt=%s channel=%s posted=%d",
        user.id, yt_service.is_authorized, channel, len(posted_ids),
    )

    yt_icon = "🟢" if yt_service.is_authorized else "🔴"
    ch_icon = "🟢" if channel else "🔴"
    await update.message.reply_text(
        "📊 <b>Статус бота</b>\n\n"
        "┌────────────────────────────────┐\n"
        f"│  {yt_icon} YouTube Music: {yt_status}\n"
        f"│  {ch_icon} Канал: {ch_status}\n"
        f"│  🎵 Опубликовано: <b>{len(posted_ids)}</b> треков\n"
        f"│  🔄 Автопроверка: каждые {CHECK_INTERVAL_MINUTES} мин.\n"
        "└────────────────────────────────┘",
        parse_mode="HTML",
    )


# ╔══════════════════════════════════════════════════════════════════╗
# ║  /auth — Browser-based auth instructions                        ║
# ╚══════════════════════════════════════════════════════════════════╝


async def cmd_auth(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    _log_update(update)
    user = update.effective_user
    if not user or not is_allowed(user.id):
        return

    logger.info("[AUTH] user=%s requesting auth instructions", user.id)
    # Set state so we know this user is in auth flow
    ctx.user_data["awaiting_auth"] = True
    await update.message.reply_text(AUTH_INSTRUCTIONS, parse_mode="HTML")


# ╔══════════════════════════════════════════════════════════════════╗
# ║  /export — auto-extract cookies from Chrome/Edge                ║
# ╚══════════════════════════════════════════════════════════════════╝


async def cmd_export(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    _log_update(update)
    user = update.effective_user
    if not user or not is_allowed(user.id):
        return

    logger.info("[EXPORT] user=%s starting browser cookie export", user.id)
    await update.message.reply_text("🔄 Извлекаю cookies из браузера…")

    # Try Chrome first, then Edge
    headers = None
    errors = []
    for browser in ("chrome", "edge"):
        try:
            logger.info("[EXPORT] user=%s trying %s…", user.id, browser)
            headers = await asyncio.to_thread(yt_service.extract_browser_cookies, browser)
            if headers:
                logger.info("[EXPORT] user=%s cookies extracted from %s", user.id, browser)
                break
        except Exception as e:
            errors.append(f"{browser}: {e}")
            logger.warning("[EXPORT] user=%s %s failed: %s", user.id, browser, e)

    if not headers:
        error_detail = "\n".join(errors) if errors else "No cookies found"
        logger.error("[EXPORT] user=%s all browsers failed: %s", user.id, error_detail)
        await update.message.reply_text(
            "❌ Не удалось извлечь cookies из браузера.\n\n"
            "Причины могут быть:\n"
            "• Ты не logged in на music.youtube.com\n"
            "• На Windows бот запущен без прав администратора\n"
            "  (browser_cookie3 требует admin для чтения Chrome)\n"
            "• Браузер не установлен или cookies пусты\n\n"
            "Решения:\n"
            "• Запусти бота от администратора (Windows)\n"
            "• Или используй /auth для ручной авторизации\n"
            "• Или загрузи browser.json файл"
        )
        return

    # Save and test
    ok = yt_service._save_browser_dict(headers)
    if not ok:
        await update.message.reply_text("❌ Ошибка сохранения cookies.")
        return

    yt_service.reload_token()
    if not yt_service.is_authorized:
        await update.message.reply_text("❌ Cookies распознаны, но YTMusic не создался.")
        return

    # Test with a small request
    try:
        tracks = await asyncio.to_thread(yt_service.get_liked_songs, 1)
        count = len(tracks)
        await update.message.reply_text(
            f"✅ Cookies извлечены и работают!\n"
            f"Найдено {count} лайкнутых треков.\n\n"
            f"Теперь напиши /channel чтобы указать канал для постинга."
        )
    except Exception as e:
        logger.exception("[EXPORT] user=%s auth test FAILED", user.id)
        await update.message.reply_text(
            f"⚠ Cookies сохранены, но ошибка проверки:\n<code>{e}</code>\n\n"
            f"Возможно, ты не залогинен на music.youtube.com.\n"
            f"Попробуй /auth для ручной авторизации.",
            parse_mode="HTML",
        )


# ╔══════════════════════════════════════════════════════════════════╗
# ║  /check — manual check                                          ║
# ╚══════════════════════════════════════════════════════════════════╝


async def cmd_check(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    _log_update(update)
    user = update.effective_user
    if not user or not is_allowed(user.id):
        return

    channel = await db.get_channel(user.id)
    logger.info(
        "[CHECK] user=%s yt_authorized=%s channel=%s",
        user.id, yt_service.is_authorized, channel,
    )

    if not yt_service.is_authorized or not channel:
        await update.message.reply_text(
            "⚠️ <b>Бот не настроен</b>\n\n"
            "Напиши /start для настройки.",
            parse_mode="HTML",
        )
        return

    await update.message.reply_text(
        "🔍 <b>Проверяю лайкнутые песни…</b>\n"
        "<i>Скачиваю и отправляю треки в канал</i>",
        parse_mode="HTML",
    )
    count = await check_and_post(ctx.bot, user.id, channel)
    logger.info("[CHECK] user=%s posted_count=%d", user.id, count)

    if count == 0:
        await update.message.reply_text(
            "🎵 <b>Новых лайкнутых песен нет</b>\n"
            "<i>Все треки уже опубликованы или лайки не обновлены</i>",
            parse_mode="HTML",
        )
    else:
        await update.message.reply_text(
            f"✅ <b>Опубликовано {count} новых песен!</b>\n"
            f"<i>Треки уже в канале 🎉</i>",
            parse_mode="HTML",
        )


# ╔══════════════════════════════════════════════════════════════════╗
# ║  /channel — set target channel                                  ║
# ╚══════════════════════════════════════════════════════════════════╝


async def cmd_channel(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    _log_update(update)
    user = update.effective_user
    if not user or not is_allowed(user.id):
        return

    if not yt_service.is_authorized:
        await update.message.reply_text(
            "⚠️ <b>Сначала авторизуй YouTube Music</b>\n"
            "Напиши /auth",
            parse_mode="HTML",
        )
        return

    await update.message.reply_text(
        "📡 <b>Настройка канала</b>\n\n"
        "Отправь одно из:\n\n"
        "🔹 <code>@username</code> канала (напр. @my_music)\n"
        "🔹 Числовой ID (напр. -1001234567890)\n"
        "🔹 Пересланное сообщение из канала\n\n"
        "💡 <i>Бот должен быть администратором канала</i>",
        parse_mode="HTML",
    )


# ╔══════════════════════════════════════════════════════════════════╗
# ║  /pause & /resume                                               ║
# ╚══════════════════════════════════════════════════════════════════╝


async def cmd_pause(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    _log_update(update)
    user = update.effective_user
    if not user or not is_allowed(user.id):
        return
    logger.info("[PAUSE] user=%s", user.id)
    await db.set_active(user.id, False)
    await update.message.reply_text(
        "⏸ <b>Автопроверка приостановлена</b>\n\n"
        "Треки больше не будут поститься.\n"
        "Возобновить: /resume",
        parse_mode="HTML",
    )


async def cmd_resume(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    _log_update(update)
    user = update.effective_user
    if not user or not is_allowed(user.id):
        return
    logger.info("[RESUME] user=%s", user.id)
    await db.set_active(user.id, True)
    await update.message.reply_text(
        f"▶️ <b>Автопроверка возобновлена</b>\n\n"
        f"Каждые {CHECK_INTERVAL_MINUTES} минут бот будет проверять\n"
        "лайкнутые треки и постить новые.",
        parse_mode="HTML",
    )


# ╔══════════════════════════════════════════════════════════════════╗
# ║  /oauth — Google OAuth device flow                              ║
# ╚══════════════════════════════════════════════════════════════════╝


async def cmd_oauth(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Start OAuth device flow for YouTube Music."""
    _log_update(update)
    user = update.effective_user
    if not user or not is_allowed(user.id):
        return

    # Check if user is confirming the OAuth flow
    text = update.message.text.strip() if update.message and update.message.text else ""
    parts = text.split(None, 1)

    if ctx.user_data.get("oauth_pending"):
        # User is confirming — finish OAuth
        ctx.user_data.pop("oauth_pending", None)
        device_code = ctx.user_data.pop("oauth_device_code", None)
        if not device_code:
            await update.message.reply_text("❌ Ошибка: device code потерян. Попробуй /oauth заново.")
            return

        await update.message.reply_text("🔄 Завершаю авторизацию…")
        ok = await asyncio.to_thread(yt_service.oauth_finish, device_code)
        if ok:
            try:
                tracks = await asyncio.to_thread(yt_service.get_liked_songs, 1)
                await update.message.reply_text(
                    f"✅ OAuth авторизация успешна!\n"
                    f"Найдено {len(tracks)} лайкнутых треков.\n\n"
                    f"Теперь укажи канал: /channel"
                )
            except Exception as e:
                await update.message.reply_text(
                    f"⚠ OAuth токен сохранён, но ошибка:\n<code>{e}</code>",
                    parse_mode="HTML",
                )
        else:
            await update.message.reply_text(
                "❌ Не удалось завершить OAuth.\n"
                "Убедись что ты подтвердил на странице. Попробуй /oauth заново."
            )
        return

    # Start new OAuth flow
    await update.message.reply_text("🔄 Получаю код авторизации…")
    result = await asyncio.to_thread(yt_service.oauth_start)
    if not result:
        await update.message.reply_text(
            "❌ Не удалось начать OAuth.\n"
            "Возможно, проблема с сетью. Попробуй позже."
        )
        return

    ctx.user_data["oauth_pending"] = True
    ctx.user_data["oauth_device_code"] = result["device_code"]

    await update.message.reply_text(
        f"🔐 <b>Google OAuth авторизация</b>\n\n"
        f"1. Открой ссылку:\n{result['url']}\n\n"
        f"2. Войди в Google и подтверди доступ\n\n"
        f"3. После подтверждения напиши <code>/oauth</code> ещё раз\n\n"
        f"Код: <code>{result['user_code']}</code>",
        parse_mode="HTML",
    )


# ╔══════════════════════════════════════════════════════════════════╗
# ║  /help                                                          ║
# ╚══════════════════════════════════════════════════════════════════╝


async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    _log_update(update)
    await update.message.reply_text(HELP_TEXT, parse_mode="HTML")


# ╔══════════════════════════════════════════════════════════════════╗
# ║  /scan — mark video IDs as already posted                       ║
# ╚══════════════════════════════════════════════════════════════════╝

# Regex to extract YouTube video IDs from various URL formats
_YT_URL_RE = re.compile(r"(?:music\.)?youtube\.com/watch\?v=([A-Za-z0-9_-]{11})")
_YT_SHORT_RE = re.compile(r"youtu\.be/([A-Za-z0-9_-]{11})")
_YT_ID_RE = re.compile(r"\b([A-Za-z0-9_-]{11})\b")


async def cmd_scan(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Mark video IDs as already posted so the bot won't re-post them.

    Usage:
      /scan — mark all liked songs as posted (skip current queue)
      /scan dQw4w9WgXcQ — mark one video ID
      /scan https://music.youtube.com/watch?v=dQw4w9WgXcQ — mark from URL
      /scan id1 id2 id3 — mark multiple IDs
    """
    _log_update(update)
    user = update.effective_user
    if not user or not is_allowed(user.id):
        return

    # Parse arguments after /scan
    text = update.message.text.strip() if update.message and update.message.text else ""
    parts = text.split(None, 1)  # split /scan from the rest
    arg = parts[1].strip() if len(parts) > 1 else ""

    if arg:
        # Extract video IDs from the argument
        found_ids: set[str] = set()

        # Try URL patterns first
        for regex in (_YT_URL_RE, _YT_SHORT_RE):
            for match in regex.finditer(arg):
                found_ids.add(match.group(1))

        # If no URL found, try to extract bare video IDs (11-char strings)
        if not found_ids:
            # Split by whitespace/newlines and filter 11-char IDs
            for token in re.split(r"[\s,;]+", arg):
                token = token.strip()
                if len(token) == 11 and _YT_ID_RE.fullmatch(token):
                    found_ids.add(token)

        if not found_ids:
            await update.message.reply_text(
                "❌ Не удалось извлечь video ID.\n\n"
                "Форматы:\n"
                "• <code>/scan dQw4w9WgXcQ</code>\n"
                "• <code>/scan https://music.youtube.com/watch?v=dQw4w9WgXcQ</code>\n"
                "• <code>/scan id1 id2 id3</code>",
                parse_mode="HTML",
            )
            return

        added = await db.mark_video_ids(list(found_ids))
        total = await db.get_posted_count()
        logger.info(
            "[SCAN] user=%s manually marked %d IDs, added=%d, total=%d",
            user.id, len(found_ids), added, total,
        )
        await update.message.reply_text(
            f"✅ Отмечено {len(found_ids)} video ID как уже опубликованных.\n"
            f"➕ Добавлено: {added} | 📊 Всего в базе: {total}\n\n"
            f"Эти треки больше не будут поститься."
        )
    else:
        # No argument: mark all current liked songs as posted
        if not yt_service.is_authorized:
            await update.message.reply_text("⚠ Бот не авторизован. Используй /auth")
            return

        await update.message.reply_text("🔍 Получаю список лайкнутых треков…")
        try:
            tracks = await asyncio.to_thread(yt_service.get_liked_songs, 200)
        except Exception as e:
            logger.exception("[SCAN] user=%s failed to fetch liked songs", user.id)
            await update.message.reply_text(f"❌ Ошибка: {e}")
            return

        video_ids = [t["video_id"] for t in tracks]
        added = await db.mark_video_ids(video_ids)
        total = await db.get_posted_count()
        logger.info(
            "[SCAN] user=%s marked all liked (%d), added=%d, total=%d",
            user.id, len(video_ids), added, total,
        )
        await update.message.reply_text(
            f"✅ Отмечено {len(video_ids)} лайкнутых треков как уже опубликованных.\n"
            f"➕ Добавлено: {added} | 📊 Всего в базе: {total}\n\n"
            f"Бот не будет повторять эти треки.\n"
            f"Чтобы сбросить: /clear_history"
        )


# ╔══════════════════════════════════════════════════════════════════╗
# ║  /history — show recently posted tracks                         ║
# ╚══════════════════════════════════════════════════════════════════╝


async def cmd_history(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    _log_update(update)
    user = update.effective_user
    if not user or not is_allowed(user.id):
        return

    tracks = await db.get_recent_posted(limit=15)
    total = await db.get_posted_count()

    if not tracks:
        await update.message.reply_text("📭 Пока нет опубликованных треков.")
        return

    lines = [f"📜 <b>Последние опубликованные треков</b> (всего: {total}):\n"]
    for i, t in enumerate(tracks, 1):
        posted_at = t.get("posted_at", "?")
        title = t["title"]
        artists = t["artists"]
        vid = t["video_id"]
        if title == "[scanned]":
            lines.append(f"  {i}. <code>{vid}</code> (сканирован)")
        else:
            lines.append(f"  {i}. 🎵 {title} — {artists}")

    await update.message.reply_text("\n".join(lines), parse_mode="HTML")


# ╔══════════════════════════════════════════════════════════════════╗
# ║  /clear_history — reset tracking database                       ║
# ╚══════════════════════════════════════════════════════════════════╝


async def cmd_clear_history(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    _log_update(update)
    user = update.effective_user
    if not user or not is_allowed(user.id):
        return

    count = await db.clear_posted_history()
    logger.info("[CLEAR] user=%s cleared %d records", user.id, count)
    await update.message.reply_text(
        f"🗑 Очищено {count} записей из базы опубликованных треков.\n\n"
        f"⚠ Теперь бот заново опубликует все лайкнутые треки!\n"
        f"Используй /scan чтобы заново сканировать канал."
    )


# ╔══════════════════════════════════════════════════════════════════╗
# ║  /refresh — try to auto-refresh cookies from browser            ║
# ╚══════════════════════════════════════════════════════════════════╝


async def cmd_refresh(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    _log_update(update)
    user = update.effective_user
    if not user or not is_allowed(user.id):
        return

    await update.message.reply_text("🔄 Пробую извлечь свежие куки из браузера…")

    refreshed = await asyncio.to_thread(yt_service.try_auto_refresh)
    if refreshed:
        try:
            tracks = await asyncio.to_thread(yt_service.get_liked_songs, 1)
            await update.message.reply_text(
                f"✅ Куки обновлены! Работает.\n"
                f"Найдено {len(tracks)} лайкнутых треков."
            )
        except Exception as e:
            await update.message.reply_text(
                f"⚠ Куки сохранены, но проверка не прошла:\n<code>{e}</code>\n\n"
                f"Возможно, ты не залогинен в браузере на music.youtube.com.",
                parse_mode="HTML",
            )
    else:
        await update.message.reply_text(
            "❌ Не удалось извлечь куки из браузера.\n\n"
            "Возможные причины:\n"
            "• Ты не залогинен на music.youtube.com в браузере\n"
            "• Нужны права администратора (для Chrome)\n\n"
            "Решения:\n"
            "• Вставь куки из расширения cookies.txt в чат\n"
            "• Или напиши /export (нужен запуск от админа)"
        )


# ╔══════════════════════════════════════════════════════════════════╗
# ║  Catch plain text → auth headers or channel setup               ║
# ╚══════════════════════════════════════════════════════════════════╝


async def msg_handle_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle plain text: auth headers, forwarded channel message, or @username."""
    _log_update(update)
    user = update.effective_user
    if not user or not is_allowed(user.id):
        return

    text = update.message.text.strip() if update.message and update.message.text else ""

    # ── Auto-detect Netscape cookies pasted directly ───────────────
    # (no /auth required — user can just paste cookies)
    if (
        text.strip().startswith("# Netscape")
        or text.strip().startswith("# HttpOnly")
    ):
        logger.info("[TEXT] user=%s auto-detected Netscape cookies", user.id)
        headers = yt_service.parse_netscape_cookies(text)
        if headers:
            ok = yt_service._save_browser_dict(headers)
            if not ok:
                await update.message.reply_text("❌ Ошибка сохранения cookies.")
                return
        else:
            await update.message.reply_text(
                "❌ Не удалось распознать Netscape cookies.\n"
                "Убедись что есть __Secure-3PAPISID."
            )
            return

        # Reload and test
        yt_service.reload_token()
        if yt_service.is_authorized:
            try:
                tracks = await asyncio.to_thread(yt_service.get_liked_songs, 1)
                count = len(tracks)
                await update.message.reply_text(
                    f"✅ Cookies из сообщения приняты!\n"
                    f"Найдено {count} лайкнутых треков.\n\n"
                    f"Если канал уже настроен — бот готов к работе!\n"
                    f"Иначе: /channel"
                )
            except Exception as e:
                logger.exception("[TEXT] user=%s cookie auth test FAILED", user.id)
                await update.message.reply_text(
                    f"⚠ Cookies сохранены, но ошибка проверки:\n<code>{e}</code>\n\n"
                    f"Возможно, cookies истекли.",
                    parse_mode="HTML",
                )
        else:
            await update.message.reply_text(
                "❌ Cookies распознаны, но авторизация не создалась."
            )
        return

    # ── Auto-detect JSON cookie header pasted directly ──────────────
    if text.strip().startswith("{") and "cookie" in text.lower() and "authorization" in text.lower():
        logger.info("[TEXT] user=%s auto-detected JSON cookies", user.id)
        try:
            headers = json.loads(text)
        except json.JSONDecodeError:
            # Not valid JSON, fall through
            headers = None

        if headers and "cookie" in headers and "authorization" in headers:
            ok = yt_service._save_browser_dict(headers)
            if not ok:
                await update.message.reply_text("❌ Ошибка сохранения cookies.")
                return

            yt_service.reload_token()
            if yt_service.is_authorized:
                try:
                    tracks = await asyncio.to_thread(yt_service.get_liked_songs, 1)
                    count = len(tracks)
                    await update.message.reply_text(
                        f"✅ JSON cookies приняты!\n"
                        f"Найдено {count} лайкнутых треков.\n\n"
                        f"Если канал уже настроен — бот готов к работе!\n"
                        f"Иначе: /channel"
                    )
                except Exception as e:
                    logger.exception("[TEXT] user=%s json auth test FAILED", user.id)
                    await update.message.reply_text(
                        f"⚠ Cookies сохранены, но ошибка проверки:\n<code>{e}</code>\n\n"
                        f"Возможно, cookies истекли.",
                        parse_mode="HTML",
                    )
            else:
                await update.message.reply_text(
                    "❌ Cookies распознаны, но авторизация не создалась."
                )
            return

    # ── Auth flow: user is sending browser headers ──────────────────
    if ctx.user_data.get("awaiting_auth"):
        logger.info("[TEXT] user=%s in auth flow, processing headers…", user.id)
        ctx.user_data.pop("awaiting_auth", None)

        # Try Netscape Cookie File format
        if text.strip().startswith("# Netscape") or text.strip().startswith("# HttpOnly"):
            logger.info("[TEXT] user=%s detected Netscape cookie format", user.id)
            headers = yt_service.parse_netscape_cookies(text)
            if headers:
                ok = yt_service._save_browser_dict(headers)
                if not ok:
                    await update.message.reply_text("❌ Ошибка сохранения. Попробуй ещё раз: /auth")
                    return
            else:
                await update.message.reply_text(
                    "❌ Не удалось распознать Netscape cookies.\n"
                    "Убедись что есть __Secure-3PAPISID. Повтори: /auth"
                )
                return
        # Try parsing as JSON first
        elif text.strip().startswith("{"):
            try:
                headers = json.loads(text)
                if "cookie" not in headers or "authorization" not in headers:
                    await update.message.reply_text(
                        "❌ JSON должен содержать как минимум 'cookie' и 'authorization'.\n"
                        "Попробуй ещё раз: /auth"
                    )
                    return
                ok = yt_service._save_browser_dict(headers)
                if not ok:
                    await update.message.reply_text("❌ Ошибка сохранения. Попробуй ещё раз: /auth")
                    return
            except json.JSONDecodeError:
                await update.message.reply_text(
                    "❌ Невалидный JSON. Попробуй ещё раз: /auth"
                )
                return
        else:
            # Try parsing as raw headers (curl format)
            ok = yt_service._save_browser_auth(text)
            if not ok:
                await update.message.reply_text(
                    "❌ Не удалось распознать заголовки.\n\n"
                    "Попробуй:\n"
                    "• Отправь JSON: {\"cookie\": \"...\", \"authorization\": \"Bearer ...\", \"x-goog-authuser\": \"0\"}\n"
                    "• Или загрузи файл browser.json\n"
                    "• Повтори: /auth"
                )
                return

        # Reload and test
        yt_service.reload_token()
        if yt_service.is_authorized:
            # Test with a small request
            try:
                tracks = await asyncio.to_thread(yt_service.get_liked_songs, 1)
                count = len(tracks)
                await update.message.reply_text(
                    f"✅ Авторизация успешна!\n"
                    f"Найдено {count} лайкнутых треков.\n\n"
                    f"Теперь напиши /channel чтобы указать канал для постинга."
                )
            except Exception as e:
                logger.exception("[AUTH] user=%s auth test FAILED", user.id)
                await update.message.reply_text(
                    f"⚠ Авторизация сохранена, но при проверке ошибка:\n<code>{e}</code>\n\n"
                    f"Возможно, cookies уже истекли. Попробуй /auth заново.",
                    parse_mode="HTML",
                )
        else:
            await update.message.reply_text(
                "❌ Авторизация не распознана. Проверь формат.\nПопробуй: /auth"
            )
        return

    # ── Channel setup: forwarded message from channel ───────────────
    if (
        update.message
        and update.message.forward_origin
        and isinstance(update.message.forward_origin, MessageOriginChannel)
    ):
        chat = update.message.forward_origin.chat
        channel_id = str(chat.id)
        logger.info("[TEXT] user=%s forwarded from channel: %s", user.id, channel_id)

        bot: Bot = ctx.bot
        try:
            test_msg = await bot.send_message(
                chat_id=channel_id,
                text="🤖 Бот подключён! Сообщение будет удалено.",
            )
            await test_msg.delete()
            logger.info("[TEXT] user=%s channel %s verified OK", user.id, channel_id)
        except Exception as e:
            logger.exception("[TEXT] user=%s channel %s verify FAILED", user.id, channel_id)
            await update.message.reply_text(
                f"❌ Не могу отправить сообщение в канал {channel_id}.\n\n"
                f"Убедись, что:\n"
                f"1. Бот добавлен как администратор канала\n"
                f"2. У бота есть право публикации сообщений\n\n"
                f"Ошибка: {e}"
            )
            return

        await db.save_channel(user.id, channel_id)
        await update.message.reply_text(
            "✅ <b>Канал подключён!</b>\n\n"
            f"📺 Канал: <code>{channel_id}</code>\n"
            f"🔄 Автопроверка: каждые {CHECK_INTERVAL_MINUTES} мин.\n\n"
            "Напиши /check чтобы проверить прямо сейчас.",
            parse_mode="HTML",
        )
        return

    # ── Channel setup: @username or numeric ID ──────────────────────
    if text.startswith("@") or (text.lstrip("-").isdigit() and len(text) > 3):
        channel_id = text
        logger.info("[TEXT] user=%s text_input=%r → channel_id=%s", user.id, text, channel_id)

        if not yt_service.is_authorized:
            await update.message.reply_text(
                "⚠️ <b>Сначала авторизуй YouTube Music</b>\n"
                "Напиши /auth",
                parse_mode="HTML",
            )
            return

        bot: Bot = ctx.bot
        try:
            test_msg = await bot.send_message(
                chat_id=channel_id,
                text="🤖 Бот подключён! Сообщение будет удалено.",
            )
            await test_msg.delete()
            logger.info("[TEXT] user=%s channel %s verified OK", user.id, channel_id)
        except Exception as e:
            logger.exception("[TEXT] user=%s channel %s verify FAILED", user.id, channel_id)
            await update.message.reply_text(
                f"❌ <b>Не могу подключиться к каналу</b>\n\n"
                f"<code>{channel_id}</code>\n\n"
                f"Убедись, что:\n"
                f"1. Бот добавлен как администратор\n"
                f"2. У бота есть право публикации\n\n"
                f"Ошибка: <code>{e}</code>",
                parse_mode="HTML",
            )
            return

        await db.save_channel(user.id, channel_id)
        await update.message.reply_text(
            "✅ <b>Канал подключён!</b>\n\n"
            f"📺 Канал: <code>{channel_id}</code>\n"
            f"🔄 Автопроверка: каждые {CHECK_INTERVAL_MINUTES} мин.\n\n"
            "Напиши /check чтобы проверить прямо сейчас.",
            parse_mode="HTML",
        )
        return

    # ── Unknown text ────────────────────────────────────────────────
    if yt_service.is_authorized:
        await update.message.reply_text(
            "🤔 <b>Не понял команду</b>\n\n"
            "Используй /help для списка команд.",
            parse_mode="HTML",
        )
    else:
        await update.message.reply_text(
            "⚠️ <b>Сначала авторизуй YouTube Music</b>\n"
            "Напиши /auth",
            parse_mode="HTML",
        )


# ╔══════════════════════════════════════════════════════════════════╗
# ║  Handle uploaded files (browser.json)                           ║
# ╚══════════════════════════════════════════════════════════════════╝


async def msg_handle_document(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle uploaded document (e.g. browser.json)."""
    _log_update(update)
    user = update.effective_user
    if not user or not is_allowed(user.id):
        return

    doc = update.message.document
    if not doc:
        return

    logger.info("[DOC] user=%s file=%s size=%d", user.id, doc.file_name, doc.file_size)

    if doc.file_size > 1_000_000:  # 1MB limit
        await update.message.reply_text("❌ Файл слишком большой (макс 1MB).")
        return

    allowed_ext = (".json", ".txt", ".cookies")
    if not any(doc.file_name.endswith(ext) for ext in allowed_ext):
        await update.message.reply_text(
            "❌ Нужен файл .json, .txt или .cookies\n"
            "• browser.json — формат ytmusicapi\n"
            "• cookies.txt — формат Netscape (из yt-dlp)"
        )
        return

    # Download the file
    try:
        file = await ctx.bot.get_file(doc.file_id)
        content = await file.download_as_bytearray()
        text_content = content.decode("utf-8")
    except Exception as e:
        logger.exception("[DOC] user=%s download failed", user.id)
        await update.message.reply_text(f"❌ Ошибка чтения файла: {e}")
        return

    # Try Netscape format first (txt/cookies files)
    if text_content.strip().startswith("# Netscape") or text_content.strip().startswith("# HttpOnly"):
        logger.info("[DOC] user=%s detected Netscape cookie format", user.id)
        headers = yt_service.parse_netscape_cookies(text_content)
        if not headers:
            await update.message.reply_text(
                "❌ Не удалось распознать Netscape cookies.\n"
                "Убедись что файл содержит __Secure-3PAPISID."
            )
            return
    else:
        # Try JSON format
        try:
            headers = json.loads(text_content)
        except json.JSONDecodeError:
            await update.message.reply_text(
                "❌ Файл не распознан.\n"
                "Нужен .json (browser.json) или .txt (Netscape cookies)."
            )
            return

    # Validate required keys
    if "cookie" not in headers or "authorization" not in headers:
        await update.message.reply_text(
            "❌ Файл не содержит нужных заголовков.\n"
            "Нужны как минимум 'cookie' и 'authorization'.\n"
            "Используй /auth для инструкций."
        )
        return

    # Save
    ok = yt_service._save_browser_dict(headers)
    if not ok:
        await update.message.reply_text("❌ Ошибка сохранения. Попробуй ещё раз.")
        return

    yt_service.reload_token()
    if yt_service.is_authorized:
        try:
            tracks = await asyncio.to_thread(yt_service.get_liked_songs, 1)
            count = len(tracks)
            await update.message.reply_text(
                f"✅ Авторизация из файла успешна!\n"
                f"Найдено {count} лайкнутых треков.\n\n"
                f"Напиши /channel чтобы указать канал."
            )
        except Exception as e:
            logger.exception("[DOC] user=%s auth test FAILED", user.id)
            await update.message.reply_text(
                f"⚠ Файл сохранён, но ошибка проверки:\n<code>{e}</code>\n\n"
                f"Возможно, cookies истекли. Попробуй /auth.",
                parse_mode="HTML",
            )
    else:
        await update.message.reply_text("❌ Авторизация не распознана в файле.")


# ╔══════════════════════════════════════════════════════════════════╗
# ║  Core: check liked songs & post to channel                      ║
# ╚══════════════════════════════════════════════════════════════════╝


def _format_caption(track: dict[str, Any]) -> str:
    title = track["title"]
    artists = track["artists"]
    album = track.get("album", "")
    video_id = track["video_id"]

    lines = [f"🎵 <b>{title}</b>", f"👤 {artists}"]
    if album:
        lines.append(f"💿 {album}")
    lines.append(f"\n🔗 https://music.youtube.com/watch?v={video_id}")
    return "\n".join(lines)


def _best_thumb_url(thumbnails: list[dict]) -> str | None:
    if not thumbnails:
        return None
    best = max(thumbnails, key=lambda t: t.get("width", 0) * t.get("height", 0))
    return best.get("url")


async def post_song_to_channel(
    bot: Bot, channel_id: str, track: dict[str, Any]
) -> bool:
    """Post a track to the channel: download audio first, then send cover + audio together."""
    try:
        import aiohttp

        video_id = track["video_id"]
        thumb_url = _best_thumb_url(track.get("thumbnails", []))

        # ── Step 1: Download audio FIRST (this is the slow part) ──
        audio_path = await asyncio.to_thread(yt_service.download_audio, video_id)

        # ── Step 2: Send cover + audio immediately after ──────────
        # Download thumbnail once for both messages
        thumbnail_bytes = None
        if thumb_url:
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(thumb_url) as resp:
                        if resp.status == 200:
                            thumbnail_bytes = await resp.read()
            except Exception:
                pass

        # Send cover art with caption
        if thumbnail_bytes:
            await bot.send_photo(
                chat_id=channel_id,
                photo=thumbnail_bytes,
                caption=_format_caption(track),
                parse_mode="HTML",
            )
        else:
            await bot.send_message(
                chat_id=channel_id,
                text=_format_caption(track),
                parse_mode="HTML",
            )
        logger.info("[POST] cover=%s(%s) → %s", track["title"], video_id, channel_id)

        # Send audio file right after cover (no long delay)
        if audio_path:
            with open(audio_path, "rb") as audio_file:
                send_kwargs = {
                    "chat_id": channel_id,
                    "audio": audio_file,
                    "title": track["title"],
                    "performer": track["artists"],
                }
                if thumbnail_bytes:
                    send_kwargs["thumbnail"] = thumbnail_bytes
                await bot.send_audio(**send_kwargs)
            logger.info("[POST] audio=%s(%s) → %s", track["title"], video_id, channel_id)
            return True

        logger.warning("[POST] Audio download failed for %s", video_id)
        return True  # cover was sent

    except Exception:
        logger.exception("[POST] FAILED song=%s → %s", track["video_id"], channel_id)
        return False


async def check_and_post(bot: Bot, user_id: int, channel_id: str) -> int:
    if not yt_service.is_authorized:
        logger.warning("[CHECK] user=%s not authorized, skipping", user_id)
        return 0

    logger.info("[CHECK] user=%s fetching liked songs…", user_id)
    try:
        tracks = await asyncio.to_thread(yt_service.get_liked_songs, 200)
    except Exception:
        logger.exception("[CHECK] user=%s FAILED to fetch liked songs", user_id)
        return 0

    posted_ids = await db.get_all_posted_ids()
    new_tracks = [t for t in tracks if t["video_id"] not in posted_ids]

    logger.info(
        "[CHECK] user=%s total_liked=%d already_posted=%d new=%d",
        user_id, len(tracks), len(posted_ids), len(new_tracks),
    )

    count = 0
    for track in reversed(new_tracks):
        logger.info(
            "[CHECK] posting %d/%d: %s — %s",
            count + 1, len(new_tracks), track["title"], track["artists"],
        )
        if await post_song_to_channel(bot, channel_id, track):
            await db.mark_posted(
                track["video_id"],
                track["title"],
                track["artists"],
                track.get("album", ""),
                track.get("duration", ""),
            )
            count += 1
            # Cleanup audio file after posting
            await asyncio.to_thread(yt_service.cleanup_audio, track["video_id"])
            await asyncio.sleep(1)

    logger.info("[CHECK] user=%s posted_count=%d total_in_db=%d", user_id, count, len(posted_ids) + count)
    return count


# ╔══════════════════════════════════════════════════════════════════╗
# ║  Scheduled job                                                  ║
# ╚══════════════════════════════════════════════════════════════════╝


async def scheduled_check(app: Application) -> None:
    logger.info("[SCHEDULED] Running scheduled check…")
    users = await db.get_all_active_users()
    logger.info("[SCHEDULED] Active users: %d", len(users))
    bot = app.bot

    # ── Ensure Edge is running (once per cycle) ─────────────────
    if not yt_service.is_authorized:
        logger.info("[SCHEDULED] Edge not running, trying to launch…")
        refreshed = await asyncio.to_thread(yt_service.try_auto_refresh)
        if not refreshed:
            logger.error("[SCHEDULED] Edge launch FAILED — notifying users")
            for user in users:
                try:
                    await bot.send_message(
                        chat_id=user["user_id"],
                        text=(
                            "⚠️ <b>Браузер не запущен!</b>\n\n"
                            "Автопроверка не работает.\n\n"
                            "Запусти YTMusicBot.exe заново."
                        ),
                        parse_mode="HTML",
                    )
                except Exception:
                    logger.exception("[SCHEDULED] Failed to notify user=%s", user["user_id"])
            return
        else:
            logger.info("[SCHEDULED] Edge launched successfully")

    for user in users:
        uid = user["user_id"]
        ch = user["channel_id"]
        try:
            logger.info("[SCHEDULED] Checking user=%s channel=%s", uid, ch)
            await check_and_post(bot, uid, ch)
        except Exception:
            logger.exception("[SCHEDULED] FAILED for user=%s", uid)


# ╔══════════════════════════════════════════════════════════════════╗
# ║  Build application                                              ║
# ╚══════════════════════════════════════════════════════════════════╝


def build_app() -> Application:
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    # All commands
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("auth", cmd_auth))
    app.add_handler(CommandHandler("oauth", cmd_oauth))
    app.add_handler(CommandHandler("export", cmd_export))
    app.add_handler(CommandHandler("check", cmd_check))
    app.add_handler(CommandHandler("scan", cmd_scan))
    app.add_handler(CommandHandler("history", cmd_history))
    app.add_handler(CommandHandler("clear_history", cmd_clear_history))
    app.add_handler(CommandHandler("refresh", cmd_refresh))
    app.add_handler(CommandHandler("channel", cmd_channel))
    app.add_handler(CommandHandler("pause", cmd_pause))
    app.add_handler(CommandHandler("resume", cmd_resume))
    app.add_handler(CommandHandler("help", cmd_help))

    # Document uploads (browser.json)
    app.add_handler(
        MessageHandler(
            filters.Document.ALL & filters.ChatType.PRIVATE,
            msg_handle_document,
        )
    )

    # Plain text → auth headers or channel setup
    app.add_handler(
        MessageHandler(
            filters.ALL
            & ~filters.COMMAND
            & ~filters.Regex(r"^/")
            & ~filters.Document.ALL
            & filters.ChatType.PRIVATE,
            msg_handle_text,
        )
    )

    return app
