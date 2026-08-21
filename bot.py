"""Telegram bot – all commands, no inline buttons. Verbose logging.

Browser-based auth (OAuth broken server-side since Sep 2025).
"""

from __future__ import annotations

import asyncio
import json
import logging
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


HELP_TEXT = """🎵 <b>Music Channel Bot</b>

Команды:
/start — Начать настройку
/status — Текущий статус
/auth — Инструкция по авторизации YouTube Music
/export — Автоизвлечение cookies из браузера
/check — Проверить лайкнутые сейчас
/pause — Приостановить автопроверку
/resume — Возобновить автопроверку
/help — Показать эту справку
"""


AUTH_INSTRUCTIONS = """🔐 <b>Авторизация YouTube Music</b>

⚠ OAuth сломан на стороне YouTube (с сент. 2025).
Используем <b>browser-based auth</b> — куки из браузера.

<b>Способ 1: Автоматически</b>
Просто напиши <code>/export</code> — извлеку cookies из Chrome/Edge.
⚠ На Windows нужен запуск от администратора.

<b>Способ 2: Netscape Cookie File</b>
Отправь файл <code>cookies.txt</code> (формат из yt-dlp, CurlExporter и т.д.)
<b>Или</b> вставь содержимое как сообщение.

<b>Способ 3: DevTools</b>
1. Открой <a href="https://music.youtube.com">music.youtube.com</a>
2. F12 → вкладка <b>Network</b>
3. Найди запрос к music.youtube.com
4. ПКМ → <b>Copy → Copy as cURL</b>
5. Вставь мне как сообщение

<b>Способ 4: JSON</b>
Отправь:
<code>{"cookie": "...", "authorization": "SAPISIDHASH ...", "x-goog-authuser": "0"}</code>

<b>Способ 5: Файл</b>
Загрузи <code>browser.json</code> (созданный через ytmusicapi)

⏰ Cookies истекают через 2-4 недели — потом /auth заново.
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
            f"✅ Бот активен!\n\n"
            f"📺 Канал: {channel}\n"
            f"🔄 Автопроверка: каждые {CHECK_INTERVAL_MINUTES} мин.\n\n"
            f"Команды:\n"
            f"/check — проверить сейчас\n"
            f"/pause — приостановить\n"
            f"/status — подробный статус"
        )
        return

    lines = ["🎵 Привет! Я пересылаю лайкнутые песни из YouTube Music в канал.\n"]
    if not yt_service.is_authorized:
        lines.append("Шаг 1: Напиши /auth чтобы получить инструкцию по авторизации.")
    else:
        lines.append("✅ YouTube Music уже авторизован.")
    if not channel:
        lines.append("Шаг 2: Напиши /channel чтобы указать канал.")
    await update.message.reply_text("\n".join(lines))


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

    await update.message.reply_text(
        f"📊 Статус бота\n\n"
        f"🎵 YouTube Music: {yt_status}\n"
        f"📺 Канал: {ch_status}\n"
        f"🎵 Опубликовано треков: {len(posted_ids)}\n"
        f"🔄 Автопроверка: каждые {CHECK_INTERVAL_MINUTES} мин."
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
        await update.message.reply_text("⚠ Бот не настроен. Используй /start")
        return

    await update.message.reply_text("🔍 Проверяю лайкнутые песни…")
    count = await check_and_post(ctx.bot, user.id, channel)
    logger.info("[CHECK] user=%s posted_count=%d", user.id, count)

    if count == 0:
        await update.message.reply_text("🎵 Новых лайкнутых песен нет.")
    else:
        await update.message.reply_text(f"✅ Опубликовано {count} новых песен!")


# ╔══════════════════════════════════════════════════════════════════╗
# ║  /channel — set target channel                                  ║
# ╚══════════════════════════════════════════════════════════════════╝


async def cmd_channel(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    _log_update(update)
    user = update.effective_user
    if not user or not is_allowed(user.id):
        return

    if not yt_service.is_authorized:
        await update.message.reply_text("⚠ Сначала авторизуй YouTube Music: /auth")
        return

    await update.message.reply_text(
        "📡 Укажи канал для постинга.\n\n"
        "Отправь одно из:\n"
        "• @username канала (например @my_music)\n"
        "• Числовой ID (например -1001234567890)\n"
        "• Пересланное сообщение из канала\n\n"
        "💡 Бот должен быть администратором канала с правом публикации!"
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
    await update.message.reply_text("⏸ Автопроверка приостановлена.\nВозобновить: /resume")


async def cmd_resume(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    _log_update(update)
    user = update.effective_user
    if not user or not is_allowed(user.id):
        return
    logger.info("[RESUME] user=%s", user.id)
    await db.set_active(user.id, True)
    await update.message.reply_text(
        f"▶️ Автопроверка возобновлена (каждые {CHECK_INTERVAL_MINUTES} мин)."
    )


# ╔══════════════════════════════════════════════════════════════════╗
# ║  /help                                                          ║
# ╚══════════════════════════════════════════════════════════════════╝


async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    _log_update(update)
    await update.message.reply_text(HELP_TEXT, parse_mode="HTML")


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
            f"✅ Канал подключён: {channel_id}\n\n"
            f"🔄 Автопроверка: каждые {CHECK_INTERVAL_MINUTES} мин.\n"
            f"Напиши /check чтобы проверить прямо сейчас."
        )
        return

    # ── Channel setup: @username or numeric ID ──────────────────────
    if text.startswith("@") or (text.lstrip("-").isdigit() and len(text) > 3):
        channel_id = text
        logger.info("[TEXT] user=%s text_input=%r → channel_id=%s", user.id, text, channel_id)

        if not yt_service.is_authorized:
            await update.message.reply_text("⚠ Сначала авторизуй YouTube Music: /auth")
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
                f"❌ Не могу отправить сообщение в канал {channel_id}.\n\n"
                f"Убедись, что:\n"
                f"1. Бот добавлен как администратор канала\n"
                f"2. У бота есть право публикации сообщений\n\n"
                f"Ошибка: {e}"
            )
            return

        await db.save_channel(user.id, channel_id)
        await update.message.reply_text(
            f"✅ Канал подключён: {channel_id}\n\n"
            f"🔄 Автопроверка: каждые {CHECK_INTERVAL_MINUTES} мин.\n"
            f"Напиши /check чтобы проверить прямо сейчас."
        )
        return

    # ── Unknown text ────────────────────────────────────────────────
    if yt_service.is_authorized:
        await update.message.reply_text(
            "🤔 Не понял команду.\n\n"
            "Используй /help для списка команд."
        )
    else:
        await update.message.reply_text(
            "⚠ Сначала авторизуй YouTube Music: /auth"
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
    try:
        caption = _format_caption(track)
        thumb_url = _best_thumb_url(track.get("thumbnails", []))
        video_id = track["video_id"]

        import aiohttp

        # ── Message 1: cover art + description ─────────────────────
        if thumb_url:
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(thumb_url) as resp:
                        if resp.status == 200:
                            photo_bytes = await resp.read()
                            await bot.send_photo(
                                chat_id=channel_id,
                                photo=photo_bytes,
                                caption=caption,
                                parse_mode="HTML",
                            )
                            logger.info(
                                "[POST] cover=%s(%s) → %s",
                                track["title"], video_id, channel_id,
                            )
            except Exception:
                logger.warning("[POST] Failed to send cover for %s", video_id)
        else:
            await bot.send_message(
                chat_id=channel_id, text=caption, parse_mode="HTML"
            )

        # ── Message 2: audio file ──────────────────────────────────
        audio_path = await asyncio.to_thread(yt_service.download_audio, video_id)

        if audio_path:
            # Download thumbnail for audio cover art
            thumbnail_bytes = None
            if thumb_url:
                try:
                    async with aiohttp.ClientSession() as session:
                        async with session.get(thumb_url) as resp:
                            if resp.status == 200:
                                thumbnail_bytes = await resp.read()
                except Exception:
                    pass

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

            logger.info(
                "[POST] audio=%s(%s) → %s",
                track["title"], video_id, channel_id,
            )
            return True

        logger.warning("[POST] Audio download failed for %s", video_id)
        return True  # cover message was sent successfully
        return True

    except Exception:
        logger.exception(
            "[POST] FAILED song=%s → %s", track["video_id"], channel_id
        )
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
    app.add_handler(CommandHandler("export", cmd_export))
    app.add_handler(CommandHandler("check", cmd_check))
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
