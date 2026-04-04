@echo off
echo.
echo  Streamlit Apps
echo  ==============
echo  [1] Lead Enrichment       http://localhost:8501
echo  [2] AI Lead Processing    http://localhost:8502
echo  [3] YouTube Transcript    http://localhost:8503
echo  [4] SaaS LM Recruit       http://localhost:8504
echo  [5] LinkedIn Content OS   http://localhost:8505
echo  [6] LLM Testing Lab       http://localhost:7860
echo  [7] Campaign Manager PV   http://localhost:8506
echo.
set /p choice="Enter number (or Enter to cancel): "

if "%choice%"=="1" (
    cd /d "%~dp0WebScraping_Exa"
    call run.bat
    goto end
)
if "%choice%"=="2" (
    cd /d "%~dp0ai_lead_processing"
    for /f "tokens=5" %%a in ('netstat -ano 2^>nul ^| findstr ":8502 " ^| findstr LISTENING') do taskkill /F /PID %%a >nul 2>&1
    start "" http://localhost:8502
    py -m streamlit run streamlit_app.py
    goto end
)
if "%choice%"=="3" (
    cd /d "%~dp0youtube_transcript"
    for /f "tokens=5" %%a in ('netstat -ano 2^>nul ^| findstr ":8503 " ^| findstr LISTENING') do taskkill /F /PID %%a >nul 2>&1
    start "" http://localhost:8503
    py -m streamlit run app.py
    goto end
)
if "%choice%"=="4" (
    cd /d "%~dp0SaaS-LM-recruit"
    for /f "tokens=5" %%a in ('netstat -ano 2^>nul ^| findstr ":8504 " ^| findstr LISTENING') do taskkill /F /PID %%a >nul 2>&1
    start "" http://localhost:8504
    py -m streamlit run ui/streamlit_app.py
    goto end
)
if "%choice%"=="5" (
    cd /d "%~dp0linkedin-content-S"
    for /f "tokens=5" %%a in ('netstat -ano 2^>nul ^| findstr ":8505 " ^| findstr LISTENING') do taskkill /F /PID %%a >nul 2>&1
    start "" http://localhost:8505
    py -m streamlit run app.py
    goto end
)

if "%choice%"=="6" (
    for /f "tokens=5" %%a in ('netstat -ano 2^>nul ^| findstr ":7860 " ^| findstr LISTENING') do taskkill /F /PID %%a >nul 2>&1
    start "" http://localhost:7860
    C:\Users\79818\AppData\Local\Programs\Python\Python312\python.exe "%~dp0gradio\app.py"
    goto end
)

if "%choice%"=="7" (
    cd /d "%~dp0WebScraping_Exa\campaign_manager_PV"
    for /f "tokens=5" %%a in ('netstat -ano 2^>nul ^| findstr ":8506 " ^| findstr LISTENING') do taskkill /F /PID %%a >nul 2>&1
    start "" http://localhost:8506
    py -m streamlit run app.py --server.port 8506
    goto end
)

:end
