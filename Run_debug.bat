@echo off
title Faster-Whisper Transcriber [DEBUG]

set "ROOT=%~dp0"
set "PYEXE=%ROOT%python\python.exe"

if not exist "%PYEXE%" (
    echo.
    echo Portable Python not found yet.
    echo Please run Setup.bat first ^(just once^) before using Run.bat.
    echo.
    pause
    exit /b 1
)

REM Debug mode: keeps the console window open so you can see error messages.
"%PYEXE%" "%ROOT%transcribe_ui.py"

if errorlevel 1 (
    echo.
    echo The app closed with an error - see the messages above.
    pause
)
