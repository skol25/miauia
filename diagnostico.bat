@echo off
title Diagnostico del Asistente
cd /d "%~dp0"
echo Revisando el asistente... (deja esta ventana abierta)
echo ==== %date% %time% ==== > datos\diagnostico.txt
echo --- puertos >> datos\diagnostico.txt
netstat -ano | findstr "47831 47832" >> datos\diagnostico.txt
echo --- procesos >> datos\diagnostico.txt
powershell -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*asistente.py*' -or $_.CommandLine -like '*notas_app.py*' } | Select-Object ProcessId,Name,CommandLine | Format-List" >> datos\diagnostico.txt
echo --- python >> datos\diagnostico.txt
".venv\Scripts\python.exe" --version >> datos\diagnostico.txt 2>&1
echo --- arrancando el asistente >> datos\diagnostico.txt
".venv\Scripts\python.exe" -X faulthandler asistente.py >> datos\diagnostico.txt 2>&1
echo --- el asistente termino >> datos\diagnostico.txt
echo.
echo El asistente se cerro. Ya puedes cerrar esta ventana.
pause
