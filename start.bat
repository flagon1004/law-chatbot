@echo off
chcp 65001 > nul
title Law AI Chatbot Server

echo ============================================
echo   Law AI Chatbot Server Starting...
echo ============================================
echo.

if not exist ".env" (
    echo [ERROR] .env file not found.
    echo Copy .env.example to .env and enter your API keys.
    pause
    exit /b 1
)

if not exist "venv\Scripts\activate.bat" (
    echo [ERROR] venv not found. Run this first:
    echo   python -m venv venv
    pause
    exit /b 1
)

echo [1/3] Activating venv...
call venv\Scripts\activate.bat

echo [2/3] Checking packages...
pip install -r requirements.txt -q

for /f "tokens=2 delims=:" %%a in ('ipconfig ^| findstr /i "IPv4"') do (
    set IP=%%a
    goto :found_ip
)
:found_ip
set IP=%IP: =%

echo [3/3] Starting server...
echo.
echo Local   : http://localhost:8000
echo Network : http://%IP%:8000
echo.
echo Press Ctrl+C to stop.
echo ============================================
echo.

uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

pause