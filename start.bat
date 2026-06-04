@echo off
title HYWorld
cd /d D:\GitHub\HYWorldWeb

:: ── 1. Detener todo lo anterior ──────────────────────────
echo [HYWorld] Deteniendo servicios previos...
call stop.bat >nul 2>&1

:: ── 2. Carpetas necesarias ───────────────────────────────
if not exist "logs"     mkdir logs
if not exist "projects" mkdir projects

:: ── 3. Elegir Python (entorno conda, fallback a PATH) ────
set "PYEXE=D:\Apps\miniconda3\envs\hyworld2\python.exe"
if not exist "%PYEXE%" (
    echo [HYWorld] AVISO: no se encontro %PYEXE%, usando 'python' del PATH
    set "PYEXE=python"
)

:: ── 4. Frontend (Vite) en ventana propia ─────────────────
echo [HYWorld] Iniciando frontend (Vite) en http://localhost:5173 ...
start "HYWorld Web" cmd /c "cd /d D:\GitHub\HYWorldWeb\frontend && pnpm run dev > ..\logs\vite.log 2>&1"

:: ── 5. Worker ML en ventana propia (log en vivo) ─────────
echo [HYWorld] Iniciando ML worker (descarga proyectos + reconstruccion 3D)...
start "HYWorld Worker" cmd /k "%PYEXE% -u scripts\worker.py"

:: ── 6. Esperar a que Vite responda ───────────────────────
echo [HYWorld] Esperando a Vite...
for /L %%i in (1,1,60) do (
    curl -s http://localhost:5173 >nul 2>&1 && goto :ready
    timeout /t 1 >nul
)
:ready

start "" http://localhost:5173

echo.
echo ============================================
echo  HYWorld en marcha
echo  Web     : http://localhost:5173
echo  Worker  : ventana "HYWorld Worker" (log en vivo)
echo  Logs    : logs\worker_AAAAMMDD.log  ^|  logs\vite.log
echo ============================================
echo.
echo Cierra esta ventana cuando quieras. Para detener todo usa stop.bat
pause
