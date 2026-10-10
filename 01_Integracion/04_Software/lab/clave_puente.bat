@echo off
rem clave_puente.bat - PC DEL LABORATORIO: guarda la clave del puente y comprueba que el servidor la acepta.
rem Uso: clave_puente.bat CLAVE        guarda CLAVE en datos\puente.clave y la prueba contra el servidor
rem      clave_puente.bat              prueba la que ya esta en datos\puente.clave
rem La clave correcta la da la PC servidor con digital_twin\despliegue\clave_puente.bat.
rem Despues: HMI -> Conexion... -> Envio de datos = Servidor web -> Conectar.
cd /d "%~dp0.."
set PYH=.venv\Scripts\python.exe
if not exist %PYH% ( echo [clave] falta .venv: ejecuta lab\instalar.bat & pause & exit /b 1 )
if "%1"=="" (
  %PYH% -m puente.vincular --probar
) else (
  %PYH% -m puente.vincular --guardar %1
)
pause
