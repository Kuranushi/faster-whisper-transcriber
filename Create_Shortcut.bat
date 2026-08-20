@echo off
setlocal
title Faster-Whisper Transcriber - Create Shortcut

set "ROOT=%~dp0"

powershell -NoProfile -ExecutionPolicy Bypass -File "%ROOT%create_shortcuts.ps1" -Root "%ROOT:~0,-1%"

if errorlevel 1 (
    echo.
    echo Shortcut creation failed - see the message above.
    echo.
    pause
    exit /b 1
)

echo.
echo ============================================================
echo  Done. "Launch Faster-Whisper Transcriber.lnk" was created
echo  right here in the project folder. It has NOT been added to
echo  your Desktop or Start Menu - that part is entirely up to you.
echo.
echo  If you want it somewhere else, it's a normal shortcut file:
echo    - Copy/move it to your Desktop, or into
echo      %%APPDATA%%\Microsoft\Windows\Start Menu\Programs
echo      to make it show up in Start.
echo    - Or right-click it -^> "Pin to Start" / "Pin to taskbar"
echo      directly from wherever it sits.
echo ============================================================
echo.
pause
