@echo off
title HYWorld — Start

:: ── 0. Setup log directorio y archivo ───────────────────
if not exist "C:\HyWorldWebData\logs" mkdir "C:\HyWorldWebData\logs"
set LOGFILE=C:\HyWorldWebData\logs\start_log.txt
echo. > "%LOGFILE%"
echo ========================================= >> "%LOGFILE%"
echo HYWorld Start.bat — iniciado %date% %time% >> "%LOGFILE%"
echo ========================================= >> "%LOGFILE%"

:: ── 0b. Funcion para loggear sin drama ──────────────────
set "LOG=call :log"
goto :main

:log
echo [%time%] %~1
echo [%time%] %~1 >> "%LOGFILE%"
exit /b 0

:main
%LOG% "Verificando Docker Engine..."
docker info >nul 2>&1
if errorlevel 1 (
    %LOG% "ERROR: Docker no esta corriendo."
    %LOG% "Abre Docker Desktop y espera. Luego ejecuta de nuevo."
    pause
    exit /b 1
)
%LOG% "Docker: OK"

%LOG% "Deteniendo servicios previos..."
call stop.bat >>"%LOGFILE%" 2>&1

%LOG% "Verificando carpeta de datos..."
if not exist "C:\HyWorldWebData" (
    %LOG% "Creando C:\HyWorldWebData..."
    mkdir "C:\HyWorldWebData"
)
if not exist "C:\HyWorldWebData\models"    mkdir "C:\HyWorldWebData\models"    2>nul
if not exist "C:\HyWorldWebData\repo"      mkdir "C:\HyWorldWebData\repo"      2>nul
if not exist "C:\HyWorldWebData\projects"  mkdir "C:\HyWorldWebData\projects"  2>nul
if not exist "C:\HyWorldWebData\logs"     mkdir "C:\HyWorldWebData\logs"     2>nul

%LOG% "Verificando configuracion..."
if not exist "C:\HyWorldWebData\.env" (
    %LOG% "=============================================="
    %LOG% ".env no encontrado — creando plantilla..."
    %LOG% "=============================================="
    (
        echo # PocketBase Configuration
        echo PB_URL=https://pocketbase.vmoliver.cloud
        echo PB_ADMIN_TOKEN=
        *** POLL_INTERVAL=10
    ) > "C:\HyWorldWebData\.env"
    %LOG% "AVISO: EDITAR C:\HyWorldWebData\.env ANTES de continuar."
    %LOG% "Agregar PB_ADMIN_TOKEN y volver a ejecutar."
    %LOG% "=============================================="
    pause
    exit /b 1
)

findstr /i "PB_ADMIN_TOKEN=" "C:\HyWorldWebData\.env" >nul 2>&1
if errorlevel 1 (
    %LOG% "ERROR: .env sin PB_ADMIN_TOKEN."
    pause
    exit /b 1
)

for /f "tokens=2 delims==" %%a in ('findstr /i "PB_ADMIN_TOKEN" "C:\HyWorldWebData\.env"') do (
    if "%%a"=="" (
        %LOG% "ERROR: PB_ADMIN_TOKEN esta vacio."
        pause
        exit /b 1
    )
)
%LOG% "Configuracion: OK"

%LOG% "Sincronizando repo HY-World-2.0..."
if exist "C:\HyWorldWebData\repo\.git" (
    %LOG% "Repo existe — git pull..."
    git -C "C:\HyWorldWebData\repo" pull origin main >>"%LOGFILE%" 2>&1
) else (
    %LOG% "Clonando HY-World-2.0..."
    git clone --depth=1 https://github.com/Tencent-Hunyuan/HY-World-2.0 "C:\HyWorldWebData\repo" >>"%LOGFILE%" 2>&1
)
%LOG% "Repo sincronizado."

%LOG% "Verificando imagen Docker..."
docker image inspect hyworld_ml:latest >nul 2>&1
if errorlevel 1 (
    %LOG% "Construyendo imagen Docker (primera vez)..."
    %LOG% "Puede tardar 10-20 minutos."
    docker compose build --no-cache >>"%LOGFILE%" 2>&1
    if errorlevel 1 (
        %LOG% "ERROR: Fallo el build. Ver %LOGFILE%"
        pause
        exit /b 1
    )
    %LOG% "Imagen construida OK."
) else (
    %LOG% "Imagen: OK"
)

%LOG% "Iniciando contenedor..."
docker compose up -d >>"%LOGFILE%" 2>&1
%LOG% "Contenedor iniciado."

%LOG% "=========================================================="
%LOG% " HYWorld iniciado OK"
%LOG% " Log: %LOGFILE%"
%LOG% " Ver worker: docker logs hyworld_ml -f"
%LOG% "=========================================================="

echo.
echo ===========================================================
echo  Ver log en: %LOGFILE%
echo ===========================================================
pause