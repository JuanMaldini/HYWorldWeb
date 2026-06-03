@echo off
title HYWorld Web
cd /d D:\GitHub\HYWorldWeb

:: Launch Flask in background
echo Starting Flask server on port 5000...
start /b D:\Apps\miniconda3\envs\hyworld2\python.exe server.py > flask.log 2>&1

:: Wait for Flask to be ready
echo Waiting for Flask...
for /L %%i in (1,1,30) do (
    curl -s http://localhost:5000 >nul 2>&1 && goto :flask_ready
    timeout /t 1 >nul
)
echo Flask did not start. Check flask.log
goto :vite_start

:flask_ready
echo Flask ready.

:vite_start
:: Launch Vite dev server in background
echo Starting React dev server on port 5173...
cd frontend
start /b npm run dev > vite.log 2>&1

:: Wait for Vite
echo Waiting for Vite...
for /L %%i in (1,1,30) do (
    curl -s http://localhost:5173 >nul 2>&1 && goto :vite_ready
    timeout /t 1 >nul
)
echo Vite ready.

:vite_ready
echo.
echo ====================================
echo  HYWorld is running!
echo  Web UI:   http://localhost:5173
echo  API:      http://localhost:5000
echo  Logs:     flask.log, vite.log
echo  Press Ctrl+C here to stop all
echo ====================================
echo.

:: Keep this process alive so Ctrl+C stops everything
pause