@echo off
rem Gemelo digital EN LOCAL (sin internet): servidor web + puente contra el gateway que ya corre.
rem Uso: gemelo_local.bat                 (gateway ya arrancado con gateway.bat; habilita "Web" en el HMI)
rem      gemelo_local.bat --gateway SIM   (arranca ademas un gateway SIM con el mando web habilitado)
rem      gemelo_local.bat --host 0.0.0.0  (para abrirlo desde el celular u otra PC de la misma red)
rem Cuentas: admin/admin1234  ingeniero/ingeniero1234  operador/operador1234  usuario/usuario1234
cd /d "%~dp0.."
.venv\Scripts\python.exe -m digital_twin.local %*
pause
