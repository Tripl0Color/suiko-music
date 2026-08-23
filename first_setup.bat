@echo off
echo ========================================
echo  YT Music Bot — Первый запуск
echo ========================================
echo.

:: Check Python
python --version >nul 2>&1
if errorlevel 1 (
    echo ❌ Python не найден!
    echo.
    echo Скачай Python с https://python.org/downloads/
    echo При установке ОБЯЗАТЕЛЬНО поставь галочку "Add Python to PATH"
    echo.
    pause
    exit /b 1
)

echo ✅ Python найден:
python --version
echo.

:: Install dependencies
echo Устанавливаю зависимости...
pip install -r requirements.txt
if errorlevel 1 (
    echo.
    echo ❌ Ошибка установки зависимостей
    pause
    exit /b 1
)

echo.
echo ✅ Все зависимости установлены!
echo.

:: Check config.json
python -c "import json; c=json.load(open('config.json','r',encoding='utf-8')); t=c.get('telegram_bot_token',''); print('✅ Токен найден' if t and t!='ВСТАВЬ_СЮДА_ТОКЕН_ОТ_BOTFATHER' else '⚠ Токен не указан — открой config.json и вставь токен')" 2>nul
if errorlevel 1 (
    echo ⚠ Не удалось проверить config.json
)

echo.
echo ========================================
echo  Готово! Теперь:
echo.
echo  1. Открой config.json в текстовом редакторе
echo  2. Вставь токен от @BotFather
echo  3. Запусти: python main.py
echo     (или собери exe: build.bat)
echo ========================================
echo.
pause
