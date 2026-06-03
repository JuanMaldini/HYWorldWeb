@echo off
title HYWorld Web
cd /d D:\GitHub\HYWorldWeb

:: Kill any existing processes on ports 5000 and 5173
echo Cleaning up ports...
for /f "tokens=5" %%a in ('netstat -ano ^| findstr :5173 ^| findstr LISTENING') do taskkill /PID %%a /F >nul 2>&1
for /f "tokens=5" %%a in ('netstat -ano ^| findstr :5000 ^| findstr LISTENING') do taskkill /PID %%a /F >nul 2>&1
timeout /t 2 >nul

:: Launch React/Vite dev server with pnpm
echo Starting pnpm dev server on port 5173...
start /b cmd /c "cd frontend && pnpm run dev > vite.log 2>&1"

:: Wait for Vite
echo Waiting for Vite to be ready...
for /L %%i in (1,1,60) do (
    curl -s http://localhost:5173 >nul 2>&1 && goto :ready
    timeout /t 1 >nul
    echo Waiting... %%i/60
)

:ready
echo.
echo ====================================
echo  HYWorld is running!
echo  Web UI:   http://localhost:5173
echo.
echo  Logs: vite.log
echo  Press Ctrl+C here to stop
echo ====================================
echo.

pause