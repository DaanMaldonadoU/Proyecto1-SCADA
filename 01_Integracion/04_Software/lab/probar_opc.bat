@echo off
rem Diagnostico OPC DA contra RSLinx con el Python de 32 bits del gateway. Sin Qt, sin gateway.
rem Uso: probar_opc.bat --servidores
rem      probar_opc.bat --topics
rem      probar_opc.bat --topic PROYECTO1_TEST --modo REAL --n 30
rem      probar_opc.bat --topic PROYECTO1_TEST --modo REAL --probar-preajustes --confirmar-real
cd /d "%~dp0.."
.venv32\Scripts\python.exe -m gateway.diagnostico_opc %*
pause
