@echo off
rem cuentas.bat — gestion de cuentas del gemelo desde la consola de la PC servidor.
rem Uso: cuentas.bat                          (lista las cuentas)
rem      cuentas.bat crear ana ingeniero      (roles: usuario, operador, ingeniero, admin; pide la contrasena sin eco)
rem      cuentas.bat rol ana operador
rem      cuentas.bat clave ana
rem      cuentas.bat borrar ana
rem      cuentas.bat auditoria 100
rem Lo mismo se puede hacer desde la web con una cuenta admin (boton "Cuentas y auditoria").
cd /d "%~dp0..\.."
set PYW=.venv-web\Scripts\python.exe
if not exist %PYW% ( echo [cuentas] falta .venv-web: ejecuta instalar_servidor.bat & pause & exit /b 1 )
if "%1"=="" ( %PYW% -m digital_twin.servidor_web usuarios & goto fin )
if /i "%1"=="crear" ( %PYW% -m digital_twin.servidor_web usuario-crear %2 --rol %3 & goto fin )
if /i "%1"=="rol" ( %PYW% -m digital_twin.servidor_web usuario-rol %2 %3 & goto fin )
if /i "%1"=="clave" ( %PYW% -m digital_twin.servidor_web usuario-clave %2 & goto fin )
if /i "%1"=="borrar" ( %PYW% -m digital_twin.servidor_web usuario-borrar %2 & goto fin )
if /i "%1"=="auditoria" ( %PYW% -m digital_twin.servidor_web auditoria --n %2 & goto fin )
echo [cuentas] orden desconocida: %1
:fin
pause
