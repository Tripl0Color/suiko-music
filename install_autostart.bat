@echo off
:: Creates a shortcut to start_bot.vbs in the Windows Startup folder
:: so the bot starts automatically with Windows.

set "SCRIPT_DIR=%~dp0"
set "STARTUP=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"

:: Create shortcut via PowerShell
powershell -Command "$s=(New-Object -COM WScript.Shell).CreateShortcut('%STARTUP%\YT Music Bot.lnk'); $s.TargetPath='%SCRIPT_DIR%start_bot.vbs'; $s.WorkingDirectory='%SCRIPT_DIR%'; $s.Description='YouTube Music Telegram Bot'; $s.Save()"

echo.
echo ============================================
echo  Bot will now start with Windows!
echo  Shortcut created in: %STARTUP%
echo.
echo  To remove autostart, delete:
echo  %STARTUP%\YT Music Bot.lnk
echo ============================================
echo.
pause
