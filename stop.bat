@echo off
echo [HYWorld] Deteniendo servicios...

:: Vite dev server (puerto 5173)
for /f "tokens=5" %%a in ('netstat -ano ^| findstr :5173 ^| findstr LISTENING') do (
    taskkill /PID %%a /F >nul 2>&1
)

:: Ventanas por titulo
taskkill /F /FI "WINDOWTITLE eq HYWorld Worker*" >nul 2>&1
taskkill /F /FI "WINDOWTITLE eq HYWorld Web*"    >nul 2>&1

:: Cualquier python suelto corriendo worker.py
for /f "tokens=1" %%a in ('wmic process where "name='python.exe' and commandline like '%%worker.py%%'" get processid 2^>nul ^| findstr /r "[0-9]"') do (
    taskkill /F /PID %%a >nul 2>&1
)

echo [HYWorld] Listo.
