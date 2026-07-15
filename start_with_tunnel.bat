@echo off
title Law AI Chatbot + Tunnel

if not exist "venv\Scripts\activate.bat" (
    echo [ERROR] venv not found. Run setup.bat first.
    pause
    exit /b 1
)

call venv\Scripts\activate.bat

echo Starting FastAPI server...
start "FastAPI Server" cmd /k "uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload"

timeout /t 3 /nobreak > nul

echo Starting Cloudflare Tunnel...
start "Cloudflare Tunnel" cmd /k "cloudflared tunnel --url http://localhost:8000"

echo.
echo Both windows started.
echo Check the Tunnel window for your public URL.
pause