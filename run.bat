@echo off
chcp 65001 >nul
cd /d "%~dp0"

:loop
echo.
echo ================================================
echo  XAUUSD Zone Alert Bot ishga tushmoqda...
echo  %date% %time%
echo ================================================
".venv\Scripts\python.exe" main.py
echo.
echo  Bot toxtadi. 10 soniyadan keyin qayta ishga tushadi.
echo  Butunlay toxtatish uchun bu oynani yoping.
timeout /t 10 /nobreak >nul
goto loop
