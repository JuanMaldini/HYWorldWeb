@echo off
title HYWorld Web - Start

set "REPO=%~dp0"
if "%REPO:~-1%"=="\" set "REPO=%REPO:~0,-1%"

cd /d "%REPO%\frontend"

if not exist "node_modules" (
    echo Instalando dependencias del frontend...
    call pnpm install
)

echo Iniciando frontend en http://localhost:5173 ...
start "HYWorld Web" cmd /k "cd /d %REPO%\frontend && pnpm run dev"

for /L %%i in (1,1,30) do (
    curl -s http://localhost:5173 >nul 2>&1 && goto :ready
    timeout /t 1 >nul
)
:ready
start "" http://localhost:5173
exit
