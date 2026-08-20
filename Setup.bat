@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion
title Faster-Whisper Transcriber - Setup

echo ============================================================
echo  Faster-Whisper Transcriber - First-time Setup
echo  This downloads a private, portable copy of Python for this
echo  app only. It will NOT touch any Python you already have
echo  installed, and needs an internet connection.
echo ============================================================
echo.

set "ROOT=%~dp0"
set "PYDIR=%ROOT%python"
set "PYEXE=%PYDIR%\python.exe"
set "PYVER=3.11.9"
set "PYZIP=python-%PYVER%-embed-amd64.zip"
set "PYURL=https://www.python.org/ftp/python/%PYVER%/%PYZIP%"
set "GETPIPURL=https://bootstrap.pypa.io/get-pip.py"

if exist "%PYEXE%" (
    echo [1/6] Portable Python already present, skipping download.
    goto :pth
)

echo [1/6] Downloading portable Python %PYVER% ...
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "try { Invoke-WebRequest -Uri '%PYURL%' -OutFile '%ROOT%%PYZIP%' -UseBasicParsing } catch { Write-Host $_.Exception.Message; exit 1 }"
if not exist "%ROOT%%PYZIP%" (
    echo.
    echo ERROR: Download failed. Check your internet connection and try
    echo again, or download %PYZIP% manually from:
    echo   %PYURL%
    echo and place it next to this script, then re-run Setup.bat.
    pause
    exit /b 1
)

echo       Extracting ...
mkdir "%PYDIR%" >nul 2>&1
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "Expand-Archive -Path '%ROOT%%PYZIP%' -DestinationPath '%PYDIR%' -Force"
del "%ROOT%%PYZIP%" >nul 2>&1

:pth
echo [2/6] Configuring portable Python ...
REM The embeddable distribution ships with 'import site' commented out
REM and no site-packages on its search path by default. Both are
REM required for pip and any installed package to work at all.
set "PTHFILE=%PYDIR%\python311._pth"
if exist "%PTHFILE%" (
    powershell -NoProfile -ExecutionPolicy Bypass -Command ^
      "(Get-Content '%PTHFILE%') -replace '^#import site$','import site' | Set-Content '%PTHFILE%'; Add-Content '%PTHFILE%' 'Lib\site-packages'"
)

if exist "%PYDIR%\Scripts\pip.exe" (
    echo [3/6] pip already installed, skipping.
    goto :deps
)

echo [3/6] Installing pip ...
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "Invoke-WebRequest -Uri '%GETPIPURL%' -OutFile '%ROOT%get-pip.py' -UseBasicParsing"
"%PYEXE%" "%ROOT%get-pip.py" --no-warn-script-location
del "%ROOT%get-pip.py" >nul 2>&1

:deps
echo [4/6] Installing required packages (this takes a few minutes) ...
"%PYEXE%" -m pip install --no-warn-script-location -r "%ROOT%requirements.txt"
if errorlevel 1 (
    echo.
    echo ERROR: Package installation failed. See the messages above.
    pause
    exit /b 1
)

echo [5/6] Installing NVIDIA CUDA libraries (needed for GPU transcription) ...
"%PYEXE%" -m pip install --no-warn-script-location nvidia-cublas-cu12 nvidia-cudnn-cu12

echo [6/6] Linking CUDA libraries so Windows can find them ...
REM pip installs these DLLs deep inside site-packages, where Windows
REM DLL search order never looks. Copying them next to python.exe
REM IS on the search path is the simplest reliable fix.
for /d %%D in ("%PYDIR%\Lib\site-packages\nvidia\*") do (
    if exist "%%D\bin" (
        copy /y "%%D\bin\*.dll" "%PYDIR%\" >nul 2>&1
    )
)

echo.
echo ============================================================
echo  Setup complete! Double-click Run.bat to start the app.
echo ============================================================
pause