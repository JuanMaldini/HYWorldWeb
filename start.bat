@echo off
:: ============================================================
::  HYWorld - Start
::
::  Lanzador. Toda la logica vive en scripts\preflight.ps1
::
::  Uso:
::    start.bat              arranque completo + validacion
::    start.bat -Web         solo frontend (no toca contenedores)
::    start.bat -Rebuild     fuerza rebuild de las imagenes
::    start.bat -NoBrowser   no abre el navegador
::    start.bat -SkipPull    no actualiza los repos ML
:: ============================================================
setlocal
title HYWorld - Start
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\preflight.ps1" %*
exit /b %errorlevel%
