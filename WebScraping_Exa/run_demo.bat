@echo off
cd /d "%~dp0"

for /f "tokens=5" %%a in ('netstat -ano 2^>nul ^| findstr ":8502 " ^| findstr LISTENING') do (
    taskkill /F /PID %%a >nul 2>&1
)

echo Starting UI demo on http://localhost:8502
start "" http://localhost:8502
py -m streamlit run ui_demo.py --server.port 8502
