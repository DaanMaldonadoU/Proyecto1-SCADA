@echo off
rem Gateway OPC (Python 3.12 de 32 bits, misma maquina que RSLinx). Publica en 5555/5556.
rem En el RSLinx del laboratorio el topic del SLC real es PROYECTO1_TEST (driver AB_ETH-2 -> 1761-NET-ENI 192.168.1.80).
rem Uso: gateway.bat [REAL|EMULATE|SIM] [TOPIC] [argumentos extra]      defecto: REAL PROYECTO1_TEST
rem Ejemplos: gateway.bat REAL PROYECTO1_TEST --fuente dispositivo   (la cache es el defecto)
rem           gateway.bat REAL PROYECTO1_TEST --remoto      (mando web habilitado desde el arranque)
rem           gateway.bat SIM
setlocal
set MODO=%1
if "%MODO%"=="" set MODO=REAL
set TOPIC=%2
if "%TOPIC%"=="" set TOPIC=PROYECTO1_TEST
cd /d "%~dp0.."
echo Gateway %MODO% sobre [%TOPIC%] - Ctrl+C para salir
if /i "%MODO%"=="SIM" (
  .venv32\Scripts\python.exe -m gateway --modo SIM %3 %4 %5 %6 %7 %8
) else (
  .venv32\Scripts\python.exe -m gateway --modo %MODO% --servidor "RSLinx Local OPC Server" --topic %TOPIC% --periodo 100 %3 %4 %5 %6 %7 %8
)
endlocal
pause
