@echo off
:: ============================================================
::  HYWorld - Start
::
::  Lanzador. Toda la logica vive en scripts\preflight.ps1
::
::  Uso:
::    start.bat              arranque completo + validacion + log en vivo
::    start.bat -Web         solo frontend (no toca contenedores)
::    start.bat -Rebuild     fuerza rebuild de las imagenes
::    start.bat -NoBrowser   no abre el navegador
::    start.bat -SkipPull    no actualiza los repos ML
::    start.bat -NoLogs      no engancha el log del worker al terminar
:: ============================================================
setlocal enabledelayedexpansion
title HYWorld - Start

:: -NoLogs es un flag propio de este lanzador: se filtra para no pasarselo a
:: preflight.ps1, que no lo conoce.
set "ARGS="
set "TAILLOGS=1"
for %%A in (%*) do (
    if /i "%%~A"=="-NoLogs" (set "TAILLOGS=0") else (set "ARGS=!ARGS! %%A")
)

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\preflight.ps1"%ARGS%
set "RC=%errorlevel%"

echo(
if not "%RC%"=="0" (
    echo [ERROR] Fallo con codigo %RC%.
    goto :hold
)
echo [OK] HYWorld iniciado.

:: -Web no levanta contenedores: no hay log de worker que seguir.
echo %ARGS% | find /i "-Web" >nul && goto :hold
if "%TAILLOGS%"=="0" goto :hold

echo(
echo ============================================================
echo  Log del worker EN VIVO  (contenedor hyworld_ml)
echo(
echo  Es el mismo stream que muestra Docker Desktop: el entrypoint
echo  hace tee del stdout, asi que este texto y .data\logs\worker_*.log
echo  son el mismo contenido.
echo(
echo  Ctrl+C corta el seguimiento del log. NO detiene los
echo  contenedores: para eso, stop.bat
echo ============================================================
echo(
docker logs -f --tail 50 hyworld_ml

:hold
:: Al hacer doble clic, cmd se lanza con /c y cierra la ventana al terminar:
:: el resultado desaparecia antes de poder leerlo. Se pausa solo en ese caso;
:: si se invoca desde una terminal ya abierta, no molesta.
echo %cmdcmdline% | find /i "/c" >nul && (
    echo(
    echo Pulsa una tecla para cerrar esta ventana...
    pause >nul
)
exit /b %RC%
