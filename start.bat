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

:: ── 3b. Limpiar cache HuggingFace corrupta ────────────────
:: Borra descargas interrumpidas (*.incomplete, *.part) y locks stale
:: (*.lock) que bloquean re-descargas de hf_hub.
%LOG% "Limpiando cache HuggingFace incompleta..."
set "HF_HUB=%DATA%\models\hub"
set "HF_CLEANED=0"
if exist "%HF_HUB%" (
    for /f %%C in ('powershell -NoProfile -Command "$f = @(Get-ChildItem -Path '%HF_HUB%' -Recurse -File -Include *.incomplete,*.lock,*.part -ErrorAction SilentlyContinue); $f | Remove-Item -Force -ErrorAction SilentlyContinue; $f.Count"') do set "HF_CLEANED=%%C"
)
if "!HF_CLEANED!"=="0" (
    %LOG% "  Cache OK"
) else (
    %LOG% "  !HF_CLEANED! archivo(s) corrupto(s) eliminado(s)"
)

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

:: ── 5b. Sync Hunyuan3D-2 repo ─────────────────────────────
%LOG% "Sincronizando Hunyuan3D-2..."
if exist "%DATA%\Hunyuan3D-2\.git" (
    %LOG% "  git pull Hunyuan3D-2..."
    git -C "%DATA%\Hunyuan3D-2" pull >>"%LOGFILE%" 2>&1
) else (
    %LOG% "  AVISO: %DATA%\Hunyuan3D-2 no encontrado. Clonando..."
    git clone --depth=1 https://github.com/Tencent-Hunyuan/Hunyuan3D-2 "%DATA%\Hunyuan3D-2" >>"%LOGFILE%" 2>&1
    %LOG% "  Instalando dependencias Hunyuan3D-2..."
    python -m pip install -r "%DATA%\Hunyuan3D-2\requirements.txt" >>"%LOGFILE%" 2>&1
    python -m pip install -e "%DATA%\Hunyuan3D-2" --no-deps >>"%LOGFILE%" 2>&1
)
%LOG% "  Hunyuan3D-2 OK"

:: ── 6. Detectar cambios en Dockerfile / requirements.txt ───────
set "BUILD_TRIGGERfile=%DATA%\build_trigger.txt"
set "CURRENT_HASH="
for %%F in ("%REPO%\Dockerfile" "%REPO%\requirements.txt") do (
    for /f "tokens=*" %%H in ('powershell -NoProfile -Command "(Get-FileHash '%%~fF' -Algorithm MD5).Hash"') do (
        set "CURRENT_HASH=!CURRENT_HASH!%%H"
    )
)
if not exist "%BUILD_TRIGGERfile%" (
    set "NEED_REBUILD=1"
) else (
    for /f "usebackq tokens=*" %%H in ("%BUILD_TRIGGERfile%") do set "PREV_HASH=%%H"
    if "!CURRENT_HASH!" neq "!PREV_HASH!" set "NEED_REBUILD=1"
)
if defined NEED_REBUILD (
    %LOG% "  Archivos de build detectados como nuevos/modificados — forzando rebuild"
    docker rmi hyworld_ml:latest -f >nul 2>&1
    powershell -NoProfile -Command "[IO.File]::WriteAllText('%BUILD_TRIGGERfile%', '!CURRENT_HASH!')"
) else (
    %LOG% "  Build cache: OK"
)

:: ── 7. Imagen Docker ─────────────────────────────────────
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

:: ── 9. Iniciar Asset Server (Hunyuan3D-2) en background ───
set "ASSET_LOG=%DATA%\logs\asset_server.log"
set "ASSET_SCRIPT=%DATA%\Hunyuan3D-2\api_server.py"
set "ASSET_SAVE_DIR=%DATA%\projects\asset_cache"
if not exist "%ASSET_SAVE_DIR%" mkdir "%ASSET_SAVE_DIR%"

%LOG% "Iniciando Asset Server (Hunyuan3D-2) en puerto 8081..."
:: HF_HOME apunta al volumen compartido — misma carpeta que Docker, sin re-descargas
start "" /b cmd /c "set HF_HOME=%DATA%\models&&set HUGGINGFACE_HUB_CACHE=%DATA%\models\hub&&set HY3D_SAVE_DIR=%ASSET_SAVE_DIR%&&python "%ASSET_SCRIPT%" --host 0.0.0.0 --port 8081 --enable_tex >>"%ASSET_LOG%" 2>&1"
%LOG% "  Asset Server iniciado (log: %ASSET_LOG%)"

:: ── 10. Abrir ventana combinada de logs y cerrar esta ──────
start "HYWorld - Logs" cmd /k "docker logs -f hyworld_ml"
exit
