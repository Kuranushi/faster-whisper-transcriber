@echo off
title Faster-Whisper Transcriber

set "ROOT=%~dp0"
set "PYWEXE=%ROOT%python\pythonw.exe"
set "PYEXE=%ROOT%python\python.exe"

if not exist "%PYEXE%" (
    echo.
    echo Portable Python not found yet.
    echo Please run Setup.bat first ^(just once^) before using Run.bat.
    echo.
    pause
    exit /b 1
)

REM Use pythonw.exe to launch the GUI without a visible console window.
REM If pythonw.exe is missing for any reason, fall back to python.exe.
if exist "%PYWEXE%" (
    start "" "%PYWEXE%" "%ROOT%transcribe_ui.py"
) else (
    start "" "%PYEXE%" "%ROOT%transcribe_ui.py"
)
