# 🎵 YT Music → Telegram Channel Bot

Бот автоматически пересылает лайкнутые песни из YouTube Music в твой Telegram-канал с обложками.

## ⚠ Важно

**OAuth авторизация в YouTube Music сломана на стороне сервера с сентября 2025** ([issue #813](https://github.com/sigma67/ytmusicapi/issues/813)).
Этот бот использует **browser-based auth** — куки из браузера.

## 📂 Структура проекта

```
├── main.py              # Точка входа
├── bot.py               # Все обработчики Telegram-бота
├── yt_music.py          # YouTube Music API (browser auth + лайки)
├── database.py          # SQLite (треки, настройки)
├── config.py            # Конфигурация из .env
├── requirements.txt
├── Dockerfile
├── docker-compose.yml
├── .env.example
└── README.md
```

## 🚀 Установка

```bash
# Клонируй/скопируй проект
cd yt-music-telegram-bot

# Создай виртуальное окружение
python -m venv venv
venv\Scripts\activate  # Windows
# source venv/bin/activate  # Linux/Mac

# Установи зависимости
pip install -r requirements.txt

# Создай .env
cp .env.example .env
# Отредактируй .env — вставь токен бота и ID пользователя
```

## 🔐 Авторизация YouTube Music

Бот использует куки из браузера (browser-based auth).

### Способ 1: Автоматический экспорт (`/export`)

Напиши боту `/export` — он попробует извлечь cookies из Chrome или Edge.

⚠ **На Windows** бот должен быть запущен от администратора (иначе Chrome блокирует чтение cookies).

### Способ 2: DevTools (ручной)

1. Открой [music.youtube.com](https://music.youtube.com) в Chrome/Firefox
2. Войди в Google-аккаунт
3. Нажми **F12** → вкладка **Network**
4. Найди любой запрос к `music.youtube.com`
5. Нажми правой → **Copy → Copy as cURL (bash)**
6. Отправь скопированный текст боту (`/auth` → вставить)

### Способ 3: JSON заголовки

1. В DevTools → **Network** → выбери запрос
2. Вкладка **Headers** → скопируй `cookie`, `authorization`, `x-goog-authuser`
3. Собери JSON:
```json
{
  "cookie": "SOCS=...; __Secure-3PAPISID=...",
  "authorization": "SAPISIDHASH ...",
  "x-goog-authuser": "0"
}
```
4. Отправь боту

### Способ 4: ytmusicapi CLI

```bash
ytmusicapi browser
```
Следуй инструкциям, получи `browser.json`. Отправь файл боту.

**⏰ Cookies истекают через ~2-4 недели.** Когда бот перестанет работать — повтори /auth.

## 🎯 Использование

```
/start   → Начать настройку
/auth    → Инструкция по авторизации
/export  → Автоизвлечение cookies из Chrome/Edge
/check   → Проверить и опубликовать лайкнутые
/channel → Указать канал (@username или ID или пересылка)
/pause   → Приостановить автопроверку
/resume  → Возобновить автопроверку
/status  → Статус бота
/help    → Справка
```

### Флоу:
1. `/start` → `/auth` → отправить headers/JSON/файл
2. `/channel` → указать канал
3. `/check` → бот опубликует лайкнутые песни с обложками
4. Автопроверка каждые 15 минут

## 🐳 Docker

```bash
docker compose up -d
```

## ⚙ Настройка (.env)

| Переменная | Описание | По умолчанию |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | Токен бота от @BotFather | — |
| `ALLOWED_USER_IDS` | ID пользователей через запятую | все |
| `YTMUSIC_BROWSER_FILE` | Путь к файлу с headers | `browser.json` |
| `CHECK_INTERVAL_MINUTES` | Интервал проверки | `15` |
| `DB_PATH` | Путь к SQLite базе | `songs.db` |
