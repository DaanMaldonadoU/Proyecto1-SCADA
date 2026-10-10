@echo off
rem Pruebas automaticas (pytest, sin PLC ni Qt). Deben pasar todas antes de ir al PLC.
cd /d "%~dp0.."
.venv\Scripts\python.exe -m pytest tests -q
pause
