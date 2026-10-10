@echo off
rem instalar_servidor.bat — prepara el servidor del gemelo digital en la PC servidor (Windows, 64 bits).
rem Crea .venv-web con Python 3.13 o 3.12, instala aiohttp y paho-mqtt, genera la clave del puente,
rem pide la URL del broker MQTT (opcional) y crea la primera cuenta admin si no hay ninguna.
rem Guía completa: mds\DESPLIEGUE_SERVIDOR.md
rem (Sin bloques "( ... )" con variables leídas dentro: cmd las expande antes de ejecutar el bloque.)
setlocal
cd /d "%~dp0..\.."
echo [instalar] carpeta del repositorio: %CD%

set PY=
py -3.13-64 -c "import sys" >nul 2>&1
if not errorlevel 1 set PY=py -3.13-64
if not "%PY%"=="" goto tengo_python
py -3.12-64 -c "import sys" >nul 2>&1
if not errorlevel 1 set PY=py -3.12-64
if not "%PY%"=="" goto tengo_python
echo [instalar] ERROR: no hay Python 3.13 ni 3.12 de 64 bits. Instala python-3.13.x-amd64.exe con el "py launcher".
pause
exit /b 1

:tengo_python
echo [instalar] usando %PY%
if exist .venv-web\Scripts\python.exe goto tengo_venv
%PY% -m venv .venv-web
if errorlevel 1 goto error_venv

:tengo_venv
.venv-web\Scripts\python.exe -m pip install --upgrade pip >nul
.venv-web\Scripts\python.exe -m pip install -r digital_twin\servidor_web\requirements.txt
if errorlevel 1 goto error_pip
.venv-web\Scripts\python.exe -c "import aiohttp, paho.mqtt; print('[instalar] aiohttp', aiohttp.__version__, '- paho-mqtt', paho.mqtt.__version__)"
if errorlevel 1 goto error_pip

if not exist digital_twin\datos mkdir digital_twin\datos
echo.
echo [instalar] Clave compartida con el puente (copiala a la PC del laboratorio como datos\puente.clave):
.venv-web\Scripts\python.exe -m digital_twin.servidor_web clave

echo.
if exist digital_twin\datos\mqtt.url goto tengo_mqtt
echo [instalar] URL del broker MQTT para el servidor, p. ej.  mqtt://gemelo:CLAVE@127.0.0.1:1883
echo [instalar] Deja vacio si el puente llegara por WebSocket (/ws/planta) y no por MQTT.
set MQTTURL=
set /p MQTTURL=[instalar] URL MQTT:
if "%MQTTURL%"=="" goto sin_mqtt
> digital_twin\datos\mqtt.url echo %MQTTURL%
echo [instalar] guardada en digital_twin\datos\mqtt.url (carpeta ignorada por git)
goto cuentas
:tengo_mqtt
echo [instalar] Ya existe digital_twin\datos\mqtt.url (URL del broker MQTT). Borralo para cambiarla.
goto cuentas
:sin_mqtt
echo [instalar] sin MQTT: el puente debera conectarse por wss://digitaltwinscada.smartsensorslab.com/ws/planta

:cuentas
echo.
echo [instalar] Cuentas existentes:
.venv-web\Scripts\python.exe -m digital_twin.servidor_web usuarios
echo [instalar] Si no hay ninguna cuenta admin, crea una ahora (deja vacio para omitir):
set ADMIN=
set /p ADMIN=[instalar] nombre de la cuenta admin:
if "%ADMIN%"=="" goto fin
.venv-web\Scripts\python.exe -m digital_twin.servidor_web usuario-crear %ADMIN% --rol admin

:fin
echo.
echo [instalar] Listo. Arranca el servidor con digital_twin\despliegue\servidor.bat
echo [instalar] y publica https://digitaltwinscada.smartsensorslab.com con Caddy o cloudflared (mds\DESPLIEGUE_SERVIDOR.md).
pause
endlocal
exit /b 0

:error_venv
echo [instalar] ERROR al crear .venv-web
pause
exit /b 1
:error_pip
echo [instalar] ERROR instalando dependencias (aiohttp, paho-mqtt). Revisa la conexion a internet.
pause
exit /b 1
