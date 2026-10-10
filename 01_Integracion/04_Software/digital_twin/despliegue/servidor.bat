@echo off
rem servidor.bat — arranca el servidor del gemelo digital en http://127.0.0.1:3002 (PC servidor).
rem Uso: servidor.bat                     (MQTT segun digital_twin\datos\mqtt.url o GEMELO_MQTT_URL, si existen)
rem      servidor.bat --mqtt mqtt://gemelo:CLAVE@127.0.0.1:1883
rem      servidor.bat --publico           (el gemelo se ve sin iniciar sesion, con rol usuario)
rem Internet llega por el proxy inverso o el tunel (mds\DESPLIEGUE_SERVIDOR.md); este proceso no abre puertos publicos.
cd /d "%~dp0..\.."
if not exist .venv-web\Scripts\python.exe (
  echo [servidor] falta .venv-web: ejecuta primero digital_twin\despliegue\instalar_servidor.bat
  pause
  exit /b 1
)
.venv-web\Scripts\python.exe -m digital_twin.servidor_web --host 127.0.0.1 --port 3002 %*
pause
