# 🎵 YT Music → Telegram Channel Bot

Автоматически пересылает лайкнутые треки из YouTube Music в Telegram-канал с обложками и аудио.

![Python](https://img.shields.io/badge/Python-3.10+-blue) ![License](https://img.shields.io/badge/License-MIT-green) ![Platform](https://img.shields.io/badge/Platform-Windows-lightgrey)

---

## 📸 Как это работает

```
YouTube Music (лайки) → Бот (скрейпит через Edge/Chrome) → Telegram канал
```

1. Бот запускает браузер с debug-портом
2. Навигирует на страницу лайкнутых треков
3. Извлекает информацию о треках из DOM
4. Скачивает аудио через CDP (без yt-dlp)
5. Отправляет обложку + аудио в канал

---

## 🚀 Быстрый старт

### Способ 1: Python (рекомендуется для разработки)

```bash
# 1. Клонируй/скачай проект
git clone https://github.com/YOUR_USERNAME/yt-music-bot.git
cd yt-music-bot

# 2. Запусти первый настройщик
first_setup.bat

# 3. Отредактируй config.json
#    Вставь токен от @BotFather

# 4. Запусти бота
python main.py
```

### Способ 2: EXE (для обычных пользователей)

```bash
# 1. Собери exe
build.bat

# 2. Отредактируй config.json в папке dist\YTMusicBot
# 3. Запусти YTMusicBot.exe
```

---

## ⚙️ Настройка (config.json)

```json
{
    "telegram_bot_token": "123456:ABC-DEF...",
    "allowed_user_ids": [123456789],
    "browser": "edge",
    "check_interval_minutes": 15,
    "db_path": "songs.db",
    "browser_file": "browser.json"
}
```

| Поле | Описание | По умолчанию |
|------|----------|--------------|
| `telegram_bot_token` | Токен от @BotFather | **обязательно** |
| `allowed_user_ids` | ID пользователей (пусто = все) | `[]` |
| `browser` | Браузер: `edge` или `chrome` | `"edge"` |
| `check_interval_minutes` | Интервал проверки лайков | `15` |
| `db_path` | Путь к SQLite базе | `"songs.db"` |
| `browser_file` | Путь к файлу кук | `"browser.json"` |

### Получение Telegram ID

1. Напиши боту [@userinfobot](https://t.me/userinfobot)
2. Скопируй свой ID
3. Вставь в `allowed_user_ids`

### Получение токена бота

1. Открой [@BotFather](https://t.me/BotFather) в Telegram
2. Напиши `/newbot`
3. Следуй инструкциям
4. Скопируй токен

---

## 📂 Структура проекта

```
yt-music-bot/
├── main.py              # Точка входа (tray icon + scheduler)
├── bot.py               # Обработчики команд Telegram
├── yt_music.py          # YouTube Music (CDP + скрейпинг)
├── database.py          # SQLite база
├── config.py            # Загрузка конфигурации
├── config.json          # Настройки (редактируй этот файл!)
├── browser.json         # Куки браузера (создаётся автоматически)
├── songs.db             # База опубликованных треков
├── requirements.txt     # Зависимости Python
├── build.bat            # Сборка EXE
├── first_setup.bat      # Первый запуск
├── install_autostart.bat# Автозапуск с Windows
├── start_bot.vbs        # Тихий запуск (без консоли)
└── README.md
```

---

## 🎯 Команды бота

| Команда | Описание |
|---------|----------|
| `/start` | Запуск и настройка |
| `/status` | Статус бота |
| `/check` | Проверить лайкнутые сейчас |
| `/pause` | Приостановить автопроверку |
| `/resume` | Возобновить автопроверку |
| `/channel` | Указать канал |
| `/scan` | Отметить треки как опубликованные |
| `/history` | Последние опубликованные треки |
| `/clear_history` | Очистить историю |
| `/export` | Извлечь cookies из браузера |
| `/refresh` | Обновить cookies |
| `/auth` | Инструкция по авторизации |
| `/help` | Справка |

---

## 🔐 Авторизация YouTube Music

Бот использует **Chrome DevTools Protocol (CDP)** — куки извлекаются напрямую из браузера.

### Автоматически (рекомендуется)

1. Запусти бота
2. Откроется окно Edge/Chrome
3. **Залогинься** в YouTube Music в этом окне
4. Бот автоматически извлечёт куки

### Ручная вставка кук

1. Открой [music.youtube.com](https://music.youtube.com)
2. F12 → Application → Cookies → скопируй нужные
3. Или используй расширение [Get cookies.txt](https://chromewebstore.google.com/detail/get-cookiestxt-locally/cclelndahbckbenkjhflpdbgdldlbecc)
4. Вставь как сообщение боту

> ⏰ Cookies истекают через ~2-4 недели. Бот автоматически обновляет их через CDP.

---

## 🔄 Автозапуск с Windows

```bash
# Установи автозапуск
install_autostart.bat

# Удали автозапуск
# Удали файл: %APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\YT Music Bot.lnk
```

---

## 🐳 Docker

```bash
docker compose up -d
```

---

## 🛠️ Требования

- **Python** 3.10+
- **Windows** (для CDP и tray icon)
- **Edge** или **Chrome** (для извлечения кук)
- **ffmpeg** (для конвертации аудио — устанавливается автоматически через imageio_ffmpeg)

---

## 📋 FAQ

### Бот не находит треки?

1. Убедись что Edge/Chrome открылся с YouTube Music
2. Проверь что залогинен нужным аккаунтом
3. Напиши `/check` в бот

### Аудио не постится?

- YouTube требует авторизацию для скачивания
- Убедись что браузер залогинен
- Попробуй `/refresh`

### Cookies истекли?

- Напиши `/export` или `/refresh`
- Или вставь свежие куки в чат

---

## 📄 Лицензия

MIT License
