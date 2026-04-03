@echo off
cd /d "%~dp0"

:: Kill whatever is on port 8501
for /f "tokens=5" %%a in ('netstat -ano 2^>nul ^| findstr ":8501 " ^| findstr LISTENING') do (
    taskkill /F /PID %%a >nul 2>&1
)

:: SSH tunnel for Postgres (local 5433 -> VPS 5432)
echo Opening SSH tunnel to Postgres...
start /B ssh -i "%USERPROFILE%\.ssh\id_ed25519_hostinger" -o StrictHostKeyChecking=no -L 5433:localhost:5432 -N root@72.61.143.225

:: Wait for tunnel to establish
timeout /t 2 /nobreak >nul

:: Start worker in background
echo Starting enrichment worker...
start /B py worker.py

:: Start app
echo Starting Lead Enrichment on http://localhost:8501
start "" http://localhost:8501
py -m streamlit run app/main.py
