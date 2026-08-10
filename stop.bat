@echo off
:: ============================================================
::  HYWorld - Stop
::  Lanzador. La logica vive en scripts\stop.ps1
:: ============================================================
setlocal
title HYWorld - Stop
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\stop.ps1" %*
exit /b %errorlevel%
