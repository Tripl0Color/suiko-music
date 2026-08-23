@echo off
echo ========================================
echo  Building YT Music Bot .exe ...
echo ========================================

cd /d "%~dp0"

:: Install dependencies first
echo Installing dependencies...
pip install -r requirements.txt --quiet

:: Build with PyInstaller
pyinstaller ^
    --noconfirm ^
    --onedir ^
    --name "YTMusicBot" ^
    --add-data "config.json;." ^
    --add-data "browser.json;." ^
    --add-data "songs.db;." ^
    --hidden-import database ^
    --hidden-import config ^
    --hidden-import yt_music ^
    --hidden-import bot ^
    --hidden-import aiohttp ^
    --hidden-import aiosqlite ^
    --hidden-import telegram ^
    --hidden-import ytmusicapi ^
    --hidden-import apscheduler ^
    --hidden-import dotenv ^
    --hidden-import pystray ^
    --hidden-import PIL ^
    --hidden-import imageio_ffmpeg ^
    --collect-all telegram ^
    --collect-all ytmusicapi ^
    --collect-all apscheduler ^
    main.py

:: Copy config files next to the exe
echo Copying config files...
copy /Y "%~dp0config.json" "%~dp0dist\YTMusicBot\config.json"
copy /Y "%~dp0browser.json" "%~dp0dist\YTMusicBot\browser.json"
copy /Y "%~dp0songs.db" "%~dp0dist\YTMusicBot\songs.db"
copy /Y "%~dp0install_autostart.bat" "%~dp0dist\YTMusicBot\install_autostart.bat"
copy /Y "%~dp0start_bot.vbs" "%~dp0dist\YTMusicBot\start_bot.vbs"

echo.
echo ========================================
echo  Build complete!
echo  Exe: dist\YTMusicBot\YTMusicBot.exe
echo.
echo  1. Отредактируй config.json в папке dist\YTMusicBot
echo  2. Запусти YTMusicBot.exe
echo ========================================
pause
