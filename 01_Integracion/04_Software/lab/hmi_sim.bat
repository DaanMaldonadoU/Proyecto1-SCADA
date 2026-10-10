@echo off
rem HMI + gateway SIM en un solo comando (sin PLC, sin RSLinx): la primera prueba en la maquina nueva.
cd /d "%~dp0.."
.venv\Scripts\python.exe ui\app.py --lanzar-gateway SIM %*
pause
