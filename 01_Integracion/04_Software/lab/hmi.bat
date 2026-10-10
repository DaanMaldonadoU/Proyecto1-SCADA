@echo off
rem HMI PySide6 (Python de 64 bits) contra el gateway que ya corre en 5555/5556.
rem Uso: hmi.bat [argumentos extra de ui\app.py]   p. ej.  hmi.bat --pantalla-completa
cd /d "%~dp0.."
.venv\Scripts\python.exe ui\app.py %*
pause
