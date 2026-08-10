@echo off
title HYWorld Web - Start

set "REPO=%~dp0"
if "%REPO:~-1%"=="\" set "REPO=%REPO:~0,-1%"

set "PB_URL="
for /f "usebackq tokens=1,2 delims==" %%a in ("%REPO%\.env") do (
    if "%%a"=="PB_URL" set "PB_URL=%%b"
)
if "%PB_URL%"=="" set "PB_URL=http://localhost:8092"

echo VITE_PB_URL=%PB_URL%>"%REPO%\frontend\.env.local"

cd /d "%REPO%\frontend"

if not exist "node_modules" (
    echo Instalando dependencias del frontend...
    call pnpm install
)

echo Iniciando frontend en %PB_URL% ...
start "HYWorld Web" cmd /k "cd /d %REPO%\frontend && pnpm run dev"

for /L %%i in (1,1,30) do (
    curl -s http://localhost:5173 >nul 2>&1 && goto :ready
    timeout /t 1 >nul
)
:ready
start "" http://localhost:5173
exit
