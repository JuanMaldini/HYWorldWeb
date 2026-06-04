@echo off
title HYWorld — Start Frontend
cd /d D:\GitHub\HYWorldWeb

echo [HYWorld] Verificando frontend...
if not exist "frontend" (
    echo [HYWorld] ERROR: carpeta frontend no existe
    pause
    exit /b 1
)

if not exist "frontend\node_modules" (
    echo [HYWorld] Instalando dependencias del frontend...
    cd frontend
    call pnpm install
    cd ..
)

echo [HYWorld] Iniciando frontend (Vite) en http://localhost:5173 ...
start "HYWorld Web" cmd /c "cd /d D:\GitHub\HYWorldWeb\frontend && pnpm run dev > ..\logs\vite.log 2>&1"

echo [HYWorld] Esperando a Vite...
for /L %%i in (1,1,30) do (
    curl -s http://localhost:5173 >nul 2>&1 && goto :ready
    timeout /t 1 >nul
)
:ready

start "" http://localhost:5173

echo.
echo ===========================================================
echo  Frontend iniciado
echo  URL: http://localhost:5173
echo  Para detener: cerrar ventana "HYWorld Web"
echo ===========================================================
echo.
pause