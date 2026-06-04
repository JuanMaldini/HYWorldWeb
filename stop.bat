@echo off
title HYWorld — Stop
cd /d D:\GitHub\HYWorldWeb

:: ── Logging ───────────────────────────────────────────────
for /f "tokens=1-4 delims=/ " %%a in ('date /t') do set y=%%a&set m=%%b&set d=%%c
for /f "tokens=1-2 delims=: " %%a in ('time /t') do set hh=%%a&set mm=%%b
set LOGFILE=C:\HyWorldWebData\logs\start_%y%%m%%d%_%hh%%mm%.log

echo [%time%] [HYWorld] Deteniendo contenedor...
if exist "C:\HyWorldWebData\logs" (
    echo [%time%] [HYWorld] Deteniendo contenedor... >> "C:\HyWorldWebData\logs\stop.log"
)

:: Bajar contenedor si existe
docker compose down >>"C:\HyWorldWebData\logs\stop.log" 2>&1

:: Por si queda algun proceso hurfano
docker ps -a | findstr "hyworld_ml" >nul 2>&1
if not errorlevel 1 (
    echo [%time%] [HYWorld] Forzando detencion... >> "C:\HyWorldWebData\logs\stop.log" 2>&1
    docker kill hyworld_ml >>"C:\HyWorldWebData\logs\stop.log" 2>&1
    docker rm hyworld_ml >>"C:\HyWorldWebData\logs\stop.log" 2>&1
)

:: Limpiar procesos sueltos (python worker.py)
for /f "tokens=1" %%a in (
    'wmic process where "name='"'"'python.exe'"'"' and commandline like '"'"'%%worker.py%%'"'"'" get processid 2^>nul ^| findstr /r "[0-9]"'
) do (
    echo [%time%] [HYWorld] Matando proceso python残余: %%a >> "C:\HyWorldWebData\logs\stop.log" 2>&1
    taskkill /F /PID %%a >nul 2>&1
)

echo [%time%] [HYWorld] Contenedor detenido.
echo [%time%] [HYWorld] Contenedor detenido. >> "C:\HyWorldWebData\logs\stop.log" 2>&1
echo [HYWorld] Listo.
echo Para reiniciar: D:\GitHub\HYWorldWeb\start.bat