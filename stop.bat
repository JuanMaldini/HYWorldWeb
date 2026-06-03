@echo off
echo Stopping HYWorld Web Server...
for /f "tokens=5" %%a in ('netstat -ano ^| findstr :5000 ^| findstr LISTENING') do (
    echo Killing process %%a
    taskkill /PID %%a /F >nul 2>&1
)
echo Done.