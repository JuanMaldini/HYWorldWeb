@echo off
setlocal EnableDelayedExpansion
title HYWorld - Start

:: == Rutas (portable: el repo es la carpeta de este .bat) ==
set "REPO=%~dp0"
if "%REPO:~-1%"=="\" set "REPO=%REPO:~0,-1%"
set "DATA=C:\HyWorldWebData"
set "SCRIPTS=%REPO%\scripts"

:: -- 0. Setup log -------------------------------------------
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

:: -- 1. Docker corriendo? ----------------------------------
%LOG% "Verificando Docker..."
docker info >nul 2>&1
if errorlevel 1 (
    %LOG% "ERROR: Docker no esta corriendo. Abrir Docker Desktop."
    pause
    exit /b 1
)
%LOG% "  Docker: OK"

:: -- 2. Datos en C:\HyWorldWebData (1ra vez: se frena) -----
%LOG% "Verificando carpeta de datos..."
if not exist "%DATA%"           mkdir "%DATA%"
if not exist "%DATA%\models"    mkdir "%DATA%\models"
if not exist "%DATA%\repo"      mkdir "%DATA%\repo"
if not exist "%DATA%\projects"  mkdir "%DATA%\projects"
if not exist "%DATA%\logs"      mkdir "%DATA%\logs"

:: .env.example: regenerado SIEMPRE (refleja la plantilla actual)
(
    echo MODELS_DIR=C:\HyWorldWebData\models
    echo HF_TOKEN=
) > "%DATA%\.env.example"
if not exist "%DATA%\.env" (
    %LOG% "  Primera ejecucion: creando %DATA%\.env ..."
    (
        echo MODELS_DIR=C:\HyWorldWebData\models
        echo HF_TOKEN=
    ) > "%DATA%\.env"
    %LOG% "=============================================="
    %LOG% "ATENCION: Estructura creada en %DATA%"
    %LOG% "Editar %DATA%\.env (MODELS_DIR si queres otro disco)"
    %LOG% "y ejecutar start.bat de nuevo."
    %LOG% "=============================================="
    pause
    exit /b 1
)

:: Cargar variables del .env de datos (MODELS_DIR, HF_TOKEN)
for /f "usebackq eol=# tokens=1,* delims==" %%a in ("%DATA%\.env") do set "%%a=%%b"
if not defined MODELS_DIR set "MODELS_DIR=%DATA%\models"
if not exist "%MODELS_DIR%" mkdir "%MODELS_DIR%"
%LOG% "  Modelos en: %MODELS_DIR%"

:: HF_TOKEN: crear la linea en el .env si no existe (para poder rellenarla)
findstr /b /i "HF_TOKEN=" "%DATA%\.env" >nul 2>&1
if errorlevel 1 (
    echo HF_TOKEN=>> "%DATA%\.env"
    %LOG% "  HF_TOKEN agregado a %DATA%\.env (vacio - rellenalo si queres)"
)

:: Limpiar tokens HF cacheados de sesiones anteriores (pisan/confunden al nuestro)
if exist "%MODELS_DIR%\token"          del /q "%MODELS_DIR%\token" >nul 2>&1
if exist "%MODELS_DIR%\stored_tokens"  del /q "%MODELS_DIR%\stored_tokens" >nul 2>&1
if exist "%USERPROFILE%\.cache\huggingface\token" del /q "%USERPROFILE%\.cache\huggingface\token" >nul 2>&1

:: HF_TOKEN: avisar si esta vacio; validar contra HuggingFace si esta relleno
if "%HF_TOKEN%"=="" (
    %LOG% "  HF_TOKEN vacio - descargas HF sin autenticar (mas lentas, rate limits)."
    %LOG% "  Para quitar el aviso: rellenar HF_TOKEN en %DATA%\.env"
) else (
    %LOG% "  Validando HF_TOKEN contra HuggingFace..."
    curl -s -o nul -w "%%{http_code}" -H "Authorization: Bearer %HF_TOKEN%" https://huggingface.co/api/whoami-v2 > "%TEMP%\hf_check.txt" 2>nul
    set /p HF_HTTP=<"%TEMP%\hf_check.txt"
    del /q "%TEMP%\hf_check.txt" >nul 2>&1
    if "!HF_HTTP!"=="200" (
        %LOG% "  HF_TOKEN: VALIDO"
    ) else (
        %LOG% "ERROR: HF_TOKEN invalido (HTTP !HF_HTTP!). Corregir en %DATA%\.env"
        pause
        exit /b 1
    )
)

:: -- 3. Bajar contenedor previo ----------------------------
%LOG% "Deteniendo contenedor previo..."
docker compose -f "%SCRIPTS%\docker-compose.yml" down >>"%LOGFILE%" 2>&1

:: -- 4. Verificar .env (en el root del repo) ---------------
%LOG% "Verificando configuracion (.env)..."
if not exist "%REPO%\.env" (
    %LOG% "  .env no existe - copiando .env.example..."
    copy "%REPO%\.env.example" "%REPO%\.env" >nul
    %LOG% "=============================================="
    %LOG% "ATENCION: Editar %REPO%\.env"
    %LOG% "Completar PB_URL y PB_ADMIN_TOKEN,"
    %LOG% "luego ejecutar de nuevo."
    %LOG% "=============================================="
    pause
    exit /b 1
)

findstr /i "PB_ADMIN_TOKEN=" "%REPO%\.env" >nul 2>&1
if errorlevel 1 (
    %LOG% "ERROR: .env sin PB_ADMIN_TOKEN"
    pause
    exit /b 1
)
for /f "tokens=2 delims==" %%a in ('findstr /i "PB_ADMIN_TOKEN" "%REPO%\.env"') do (
    if "%%a"=="" (
        %LOG% "ERROR: PB_ADMIN_TOKEN vacio. Editar %REPO%\.env"
        pause
        exit /b 1
    )
)
%LOG% "  Configuracion: OK"

:: -- 5. Sync HY-World-2.0 repo -----------------------------
%LOG% "Sincronizando HY-World-2.0..."
if exist "%DATA%\repo\.git" (
    %LOG% "  git pull..."
    git -C "%DATA%\repo" pull origin main >>"%LOGFILE%" 2>&1
) else (
    %LOG% "  clonando..."
    git clone --depth=1 https://github.com/Tencent-Hunyuan/HY-World-2.0 "%DATA%\repo" >>"%LOGFILE%" 2>&1
)
%LOG% "  Repo OK"

:: -- 5b. Sync Hunyuan3D-2 repo -----------------------------
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

:: -- 6. Detectar cambios en Dockerfile / entrypoint.sh ------
set "BUILD_TRIGGERfile=%DATA%\build_trigger.txt"
set "CURRENT_HASH="
for %%F in ("%SCRIPTS%\Dockerfile" "%SCRIPTS%\entrypoint.sh") do (
    for /f "tokens=*" %%H in ('powershell -NoProfile -Command "(Get-FileHash '%%~fF' -Algorithm MD5).Hash"') do (
        set "CURRENT_HASH=!CURRENT_HASH!%%H"
    )
)
if "!CURRENT_HASH!"=="" (
    %LOG% "  AVISO: no se pudo calcular hash de build - forzando rebuild"
    set "NEED_REBUILD=1"
)
if not exist "%BUILD_TRIGGERfile%" (
    set "NEED_REBUILD=1"
) else (
    for /f "usebackq tokens=*" %%H in ("%BUILD_TRIGGERfile%") do set "PREV_HASH=%%H"
    if "!CURRENT_HASH!" neq "!PREV_HASH!" set "NEED_REBUILD=1"
)

:: -- 7. Imagen Docker --------------------------------------
%LOG% "Verificando imagen Docker..."
docker image inspect hyworld_ml:latest >nul 2>&1
if errorlevel 1 set "NEED_REBUILD=1"
if defined NEED_REBUILD (
    %LOG% "  Construyendo imagen (primera vez puede tardar 20+ min)..."
    docker build -t hyworld_ml:latest -f "%SCRIPTS%\Dockerfile" "%SCRIPTS%" >>"%LOGFILE%" 2>&1
    if errorlevel 1 (
        %LOG% "ERROR: Build fallo. Ver %LOGFILE%"
        pause
        exit /b 1
    )
    powershell -NoProfile -Command "[IO.File]::WriteAllText('%BUILD_TRIGGERfile%', '!CURRENT_HASH!')"
    %LOG% "  Imagen construida OK"
) else (
    %LOG% "  Imagen OK (sin cambios)"
)

:: -- 8. Levantar contenedor --------------------------------
%LOG% "Levantando contenedor..."
docker compose -f "%SCRIPTS%\docker-compose.yml" up -d >>"%LOGFILE%" 2>&1

:: -- 9. Esperar a que arranque -----------------------------
%LOG% "Esperando a que el worker arranque..."
for /L %%i in (1,1,12) do (
    timeout /t 5 >nul
    docker ps --filter "name=hyworld_ml" --format "{{.Status}}" | findstr /i "Up" >nul 2>&1
    if not errorlevel 1 goto :container_up
)
:container_up
docker ps --filter "name=hyworld_ml" --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}" >>"%LOGFILE%" 2>&1

:: -- 9b. Auto-fix dependencias ML del contenedor (idempotente) --
:: onnxruntime lo usa compute_sky_mask (skyseg.onnx) en worldmirror.
:: Debe ser CPU: el wheel -gpu enlaza libcudart de otra CUDA y rompe el import
:: ("libcudart.so.13"). Ya esta en el Dockerfile; esto es red de seguridad por si
:: la imagen viene pre-armada sin la dependencia. Si ya esta, no hace nada.
%LOG% "Verificando dependencias ML del contenedor (onnxruntime)..."
docker exec hyworld_ml python3.11 -c "import onnxruntime" >nul 2>&1
if errorlevel 1 (
    %LOG% "  onnxruntime ausente/roto - instalando CPU 1.20.1..."
    docker exec hyworld_ml pip uninstall -y onnxruntime-gpu onnxruntime >>"%LOGFILE%" 2>&1
    docker exec hyworld_ml pip install --no-cache-dir onnxruntime==1.20.1 >>"%LOGFILE%" 2>&1
    docker exec hyworld_ml python3.11 -c "import onnxruntime as o; print('onnxruntime', o.__version__, 'OK')" >>"%LOGFILE%" 2>&1
    %LOG% "  onnxruntime instalado"
) else (
    %LOG% "  onnxruntime OK"
)

:: -- 10. Iniciar Asset Server (Hunyuan3D-2) en background --
set "ASSET_LOG=%DATA%\logs\asset_server.log"
set "ASSET_SCRIPT=%DATA%\Hunyuan3D-2\api_server.py"
set "ASSET_SAVE_DIR=%DATA%\projects\asset_cache"
if not exist "%ASSET_SAVE_DIR%" mkdir "%ASSET_SAVE_DIR%"

%LOG% "Iniciando Asset Server (Hunyuan3D-2) en puerto 8081..."
start "" /b cmd /c "set HF_HOME=%MODELS_DIR%&&set HUGGINGFACE_HUB_CACHE=%MODELS_DIR%\hub&&set HF_TOKEN=%HF_TOKEN%&&set HUGGING_FACE_HUB_TOKEN=%HF_TOKEN%&&set HY3D_SAVE_DIR=%ASSET_SAVE_DIR%&&python "%ASSET_SCRIPT%" --host 0.0.0.0 --port 8081 --enable_tex >>"%ASSET_LOG%" 2>&1"
%LOG% "  Asset Server iniciado (log: %ASSET_LOG%)"

:: -- 11. Frontend (Vite) -----------------------------------
%LOG% "Verificando frontend..."
if not exist "%REPO%\frontend\node_modules" (
    %LOG% "  Instalando dependencias del frontend..."
    pushd "%REPO%\frontend"
    call pnpm install >>"%LOGFILE%" 2>&1
    popd
)
%LOG% "Iniciando frontend en http://localhost:5173 ..."
start "HYWorld Web" cmd /k "cd /d %REPO%\frontend && pnpm run dev"

%LOG% "Esperando a Vite..."
for /L %%i in (1,1,30) do (
    curl -s http://localhost:5173 >nul 2>&1 && goto :vite_ready
    timeout /t 1 >nul
)
:vite_ready
start "" http://localhost:5173

:: -- 12. Ventana de logs del worker y salir ----------------
%LOG% "=========================================="
%LOG% " TODO INICIADO - abriendo ventana de logs"
%LOG% "=========================================="
start "HYWorld - Logs" cmd /k "docker logs -f hyworld_ml"
exit
