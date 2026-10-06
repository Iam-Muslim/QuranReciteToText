@echo off
title Quran Recite2Text
cd /d "%~dp0"
echo ========================================================
echo   Quran Recite2Text - Interactive Alignment Workstation
echo ========================================================
echo.
echo Launching native desktop window...
python app/run_studio.py
if errorlevel 1 (
    echo.
    echo [!] Could not launch desktop window. Falling back to browser mode:
    start http://127.0.0.1:8000
    python -m app.engine.server
)
pause
