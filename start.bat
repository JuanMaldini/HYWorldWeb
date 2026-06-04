@echo off
setlocal EnableDelayedExpansion
title HYWorld - Start

:: ── Rutas (portable: el repo es la carpeta de este .bat) ──
set "REPO=%~dp0"
if "%REPO:~-1%"=="\" set "REPO=%REPO:~0,-1%"
set "DATA=C:\HyWorldWebData"

:: ── 0. Setup log ──────────────────────────────────────────
if not exist "%DATA%\logs" mkdir "%DATA%\logs"
set "LOGFILE=%DATA%\logs\start_log.txt"
set "LOG=call :log"

goto :main

:log
echo [%time%] %~1
echo [%time%] %~1>> "%LOGFILE%"
exit /b 0

:main
%LOG% "=========================================="
%LOG% " HYWorld Start - %date% %time%"
%LOG% " Repo: %REPO%"
%LOG% "=========================================="

:: ── 1. Docker corriendo? ─────────────────────────────────
%LOG% "Verificando Docker..."
docker info >nul 2>&1
if errorlevel 1 (
    %LOG% "ERROR: Docker no esta corriendo. Abrir Docker Desktop."
    pause
    exit /b 1
)
%LOG% "  Docker: OK"

:: ── 2. Bajar contenedor previo ───────────────────────────
%LOG% "Deteniendo contenedor previo..."
docker compose -f "%REPO%\docker-compose.yml" down >>"%LOGFILE%" 2>&1

:: ── 3. Crear estructura de datos ─────────────────────────
%LOG% "Verificando carpeta de datos..."
if not exist "%DATA%"           mkdir "%DATA%"
if not exist "%DATA%\models"    mkdir "%DATA%\models"
if not exist "%DATA%\repo"      mkdir "%DATA%\repo"
if not exist "%DATA%\projects"  mkdir "%DATA%\projects"
if not exist "%DATA%\logs"      mkdir "%DATA%\logs"

:: ── 4. Verificar .env ───────────────────────────────────
%LOG% "Verificando configuracion (.env)..."
if not exist "%DATA%\.env" (
    %LOG% "  .env no existe - creando plantilla..."
    (
        echo PB_URL=https://pocketbase.vmoliver.cloud
        echo PB_ADMIN_TOKEN=
        echo POLL_INTERVAL=10
    ) > "%DATA%\.env"
    %LOG% "=============================================="
    %LOG% "ATENCION: Editar %DATA%\.env"
    %LOG% "Agregar PB_ADMIN_TOKEN, luego ejecutar de nuevo."
    %LOG% "=============================================="
    pause
    exit /b 1
)

findstr /i "PB_ADMIN_TOKEN=" "%DATA%\.env" >nul 2>&1
if errorlevel 1 (
    %LOG% "ERROR: .env sin PB_ADMIN_TOKEN"
    pause
    exit /b 1
)
for /f "tokens=2 delims==" %%a in ('findstr /i "PB_ADMIN_TOKEN" "%DATA%\.env"') do (
    if "%%a"=="" (
        %LOG% "ERROR: PB_ADMIN_TOKEN vacio. Editar .env"
        pause
        exit /b 1
    )
)
%LOG% "  Configuracion: OK"

:: ── 5. Sync HY-World-2.0 repo ────────────────────────────
%LOG% "Sincronizando HY-World-2.0..."
if exist "%DATA%\repo\.git" (
    %LOG% "  git pull..."
    git -C "%DATA%\repo" pull origin main >>"%LOGFILE%" 2>&1
) else (
    %LOG% "  clonando..."
    git clone --depth=1 https://github.com/Tencent-Hunyuan/HY-World-2.0 "%DATA%\repo" >>"%LOGFILE%" 2>&1
)
%LOG% "  Repo OK"

:: ── 6. Imagen Docker ─────────────────────────────────────
%LOG% "Verificando imagen Docker..."
docker image inspect hyworld_ml:latest >nul 2>&1
if errorlevel 1 (
    %LOG% "  Construyendo imagen (primera vez puede tardar 20+ min)..."
    docker build -t hyworld_ml:latest -f "%REPO%\Dockerfile" "%REPO%" >>"%LOGFILE%" 2>&1
    if errorlevel 1 (
        %LOG% "ERROR: Build fallo. Ver %LOGFILE%"
        pause
        exit /b 1
    )
    %LOG% "  Imagen construida OK"
) else (
    %LOG% "  Imagen OK (existe)"
)

:: ── 7. Levantar contenedor ────────────────────────────────
%LOG% "Levantando contenedor..."
docker compose -f "%REPO%\docker-compose.yml" up -d >>"%LOGFILE%" 2>&1

:: ── 8. Esperar a que arranque ────────────────────────────
%LOG% "Esperando a que el worker arranque..."
for /L %%i in (1,1,12) do (
    timeout /t 5 >nul
    docker ps --filter "name=hyworld_ml" --format "{{.Status}}" | findstr /i "Up" >nul 2>&1
    if not errorlevel 1 goto :container_up
)
:container_up
docker ps --filter "name=hyworld_ml" --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}" >>"%LOGFILE%" 2>&1

%LOG% "=========================================="
%LOG% " CONTENEDOR INICIADO - abriendo ventana de logs"
%LOG% "=========================================="

:: ── 9. Abrir SOLO la ventana de logs y cerrar esta ────────
start "HYWorld - Logs" cmd /k "docker logs -f hyworld_ml"
exit
