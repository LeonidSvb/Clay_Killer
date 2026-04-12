@echo off
setlocal
cd /d "%~dp0"
set "PID_FILE=%~dp0voicetype.pid"

if "%~1"=="__start_internal" goto __start_internal
if "%~1"=="__stop_internal" goto __stop_internal

:menu
cls
echo VoiceType
echo.
echo 1. Start
echo 2. Stop
echo 3. Restart
echo 4. Status
echo 5. Debug
echo 6. Reset
echo 0. Exit
echo.
set /p VT_CHOICE=Choose mode: 

if "%VT_CHOICE%"=="1" goto start
if "%VT_CHOICE%"=="2" goto stop
if "%VT_CHOICE%"=="3" goto restart
if "%VT_CHOICE%"=="4" goto status
if "%VT_CHOICE%"=="5" goto debug
if "%VT_CHOICE%"=="6" goto reset
if "%VT_CHOICE%"=="0" exit /b 0

echo Invalid choice.
timeout /t 1 /nobreak >nul
goto menu

:start
if exist "%PID_FILE%" (
  set /p VTPID=<"%PID_FILE%"
  if not "%VTPID%"=="" (
    powershell -NoProfile -ExecutionPolicy Bypass -Command ^
      "if (Get-Process -Id %VTPID% -ErrorAction SilentlyContinue) { Write-Host 'VoiceType is already running with PID %VTPID%.'; exit 0 }"
    if not errorlevel 1 goto end
  )
)
start "" /B pythonw.exe "%~dp0voicetype.py"
echo VoiceType start requested.
goto end

:stop
if not exist "%PID_FILE%" (
  echo VoiceType is not running.
  goto end
)

set /p VTPID=<"%PID_FILE%"
if "%VTPID%"=="" (
  echo VoiceType pid file is empty.
  del "%PID_FILE%" >nul 2>nul
  goto end
)

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$p = Get-Process -Id %VTPID% -ErrorAction SilentlyContinue; if (-not $p) { Write-Host 'VoiceType pid %VTPID% is stale. Cleaning pid file.'; exit 2 }; Write-Host 'Stopping PID %VTPID%'; Stop-Process -Id %VTPID% -Force"

if errorlevel 2 (
  del "%PID_FILE%" >nul 2>nul
  goto end
)

del "%PID_FILE%" >nul 2>nul
goto end

:restart
call "%~f0" __stop_internal
timeout /t 1 /nobreak >nul
call "%~f0" __start_internal
goto end

:status
if not exist "%PID_FILE%" (
  echo VoiceType is not running.
  echo.
  pause
  goto menu
)

set /p VTPID=<"%PID_FILE%"
if "%VTPID%"=="" (
  echo VoiceType pid file is empty.
  echo.
  pause
  goto menu
)

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$p = Get-Process -Id %VTPID% -ErrorAction SilentlyContinue; if (-not $p) { Write-Host 'VoiceType pid %VTPID% is stale.'; exit 2 }; $p | Select-Object Id, ProcessName, Path | Format-Table -AutoSize"
echo.
pause
goto menu

:debug
python "%~dp0voicetype.py"
echo.
pause
goto end

:reset
echo This will force-stop all python.exe and pythonw.exe processes for the current user.
echo Use this only when old VoiceType copies are still hanging around and causing duplicates.
echo.
choice /C YN /M "Continue"
if errorlevel 2 goto menu

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$targets = Get-Process -Name python,pythonw -ErrorAction SilentlyContinue | Where-Object { try { $_.Path } catch { $null } }; " ^
  "foreach ($p in $targets) { try { if ($p.Path -like '*Python*\\python.exe' -or $p.Path -like '*Python*\\pythonw.exe') { Write-Host ('Stopping PID ' + $p.Id + ' ' + $p.ProcessName); Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue } } catch {} }"

del "%PID_FILE%" >nul 2>nul
echo.
echo Reset finished. Start VoiceType again with option 1.
pause
goto menu

:__start_internal
if exist "%PID_FILE%" (
  set /p VTPID=<"%PID_FILE%"
  if not "%VTPID%"=="" (
    powershell -NoProfile -ExecutionPolicy Bypass -Command ^
      "if (Get-Process -Id %VTPID% -ErrorAction SilentlyContinue) { exit 0 }"
    if not errorlevel 1 exit /b 0
  )
)
start "" /B pythonw.exe "%~dp0voicetype.py"
exit /b 0

:__stop_internal
if not exist "%PID_FILE%" exit /b 0
set /p VTPID=<"%PID_FILE%"
if "%VTPID%"=="" (
  del "%PID_FILE%" >nul 2>nul
  exit /b 0
)
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$p = Get-Process -Id %VTPID% -ErrorAction SilentlyContinue; if ($p) { Stop-Process -Id %VTPID% -Force }"
del "%PID_FILE%" >nul 2>nul
exit /b 0

:end
