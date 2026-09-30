@echo off
title Instalador del Asistente
echo Instalando el Asistente de notas y reuniones...
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0instalar.ps1"
echo.
pause
