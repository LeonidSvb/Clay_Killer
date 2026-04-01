@echo off
taskkill /F /IM python.exe 2>nul
timeout /t 2 /nobreak >nul
C:\Users\79818\AppData\Local\Programs\Python\Python312\python.exe %~dp0app.py
