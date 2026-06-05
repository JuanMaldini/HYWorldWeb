@echo off
title HYWorld - Stop

:: ── Rutas (portable) ──────────────────────────────────────
set "REPO=%~dp0"
if "%REPO:~-1%"=="\" set "REPO=%REPO:~0,-1%"
set "DATA=C:\HyWorldWebData"
cd /d "%REPO%"

if not exist "%DATA%\logs" mkdir "%DATA%\logs"
set "STOPLOG=%DATA%\logs\stop.log"

echo [%time%] [HYWorld] Deteniendo contenedor...
echo [%time%] [HYWorld] Deteniendo contenedor...>> "%STOPLOG%"

:: Bajar contenedor via compose
docker compose -f "%REPO%\docker-compose.yml" down >>"%STOPLOG%" 2>&1

:: Por si queda algun contenedor huerfano
docker ps -a --format "{{.Names}}" | findstr /i "hyworld_ml" >nul 2>&1
if not errorlevel 1 (
    echo [%time%] [HYWorld] Forzando detencion...>> "%STOPLOG%"
    docker kill hyworld_ml >>"%STOPLOG%" 2>&1
    docker rm hyworld_ml   >>"%STOPLOG%" 2>&1
)

echo [%time%] [HYWorld] Contenedor detenido.
echo [%time%] [HYWorld] Contenedor detenido.>> "%STOPLOG%"

:: Matar Asset Server (api_server.py en puerto 8081)
echo [%time%] [HYWorld] Deteniendo Asset Server (puerto 8081)...
for /f "tokens=5" %%i in ('netstat -aon ^| findstr ":8081 " ^| findstr "LISTENING"') do (
    echo [%time%] [HYWorld]   Matando PID %%i>> "%STOPLOG%"
    taskkill /PID %%i /F >nul 2>&1
)
echo [%time%] [HYWorld] Asset Server detenido.

echo [HYWorld] Listo. Para reiniciar: "%REPO%\start.bat"
timeout /t 3 >nul
