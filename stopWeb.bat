@echo off
title HYWorld Web - Stop

echo Deteniendo frontend (puerto 5173)...
for /f "tokens=5" %%i in ('netstat -aon ^| findstr ":5173 " ^| findstr "LISTENING"') do (
    taskkill /PID %%i /F >nul 2>&1
)
taskkill /FI "WINDOWTITLE eq HYWorld Web*" /T /F >nul 2>&1
echo Frontend detenido.
timeout /t 2 >nul
