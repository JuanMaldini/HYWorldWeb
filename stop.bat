@echo off
echo Stopping HYWorld services...

:: Kill Flask (port 5000)
for /f "tokens=5" %%a in ('netstat -ano ^| findstr :5000 ^| findstr LISTENING') do (
    echo Killing Flask (PID %%a)
    taskkill /PID %%a /F >nul 2>&1
)

:: Kill Node (Vite dev server, port 5173)
for /f "tokens=5" %%a in ('netstat -ano ^| findstr :5173 ^| findstr LISTENING') do (
    echo Killing Vite (PID %%a)
    taskkill /PID %%a /F >nul 2>&1
)

echo Done. All services stopped.