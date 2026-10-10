@echo off
rem clave_puente.bat - PC SERVIDOR: el puente del laboratorio no entra ("401 clave invalida")?
rem Uso: clave_puente.bat                 diagnostico: que carpeta usa el servidor en marcha, si acepta su clave
rem                                       (dentro y por Internet) y, si vale, la muestra para copiarla al laboratorio
rem      clave_puente.bat fijar CLAVE     el servidor usara CLAVE (p. ej. la que ya tiene el HMI); luego REINICIAR
rem                                       servidor.bat. La anterior queda como puente.clave.anterior-FECHA
rem Detalle: docs\GUIA_MODO_SUAVE_Y_GEMELO.md seccion 3 y mds\DESPLIEGUE_SERVIDOR.md seccion 7.
cd /d "%~dp0..\.."
set PYW=.venv-web\Scripts\python.exe
if not exist %PYW% ( echo [clave] falta .venv-web: ejecuta instalar_servidor.bat & pause & exit /b 1 )
if /i "%1"=="fijar" (
  %PYW% -m digital_twin.servidor_web clave-fijar %2
) else (
  %PYW% -m digital_twin.servidor_web clave-diagnostico %*
)
pause
