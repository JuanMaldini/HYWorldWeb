@echo off
:: ============================================================
::  HYWorld - Stop
::  Lanzador. La logica vive en scripts\stop.ps1
:: ============================================================
setlocal
title HYWorld - Stop
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\stop.ps1" %*
set "RC=%errorlevel%"

:: Igual que start.bat: al hacer doble clic la ventana se cerraba sola y no
:: daba tiempo a leer el resultado.
echo(
if %RC%==0 (echo [OK] HYWorld detenido.) else (echo [ERROR] Fallo con codigo %RC%.)
echo %cmdcmdline% | find /i "/c" >nul && (
    echo(
    echo Pulsa una tecla para cerrar esta ventana...
    pause >nul
)
exit /b %RC%
