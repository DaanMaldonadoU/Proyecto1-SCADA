@echo off
rem ============================================================================
rem  Instalacion en la maquina del laboratorio (Windows 10/11). Ejecutar UNA vez
rem  desde cualquier carpeta; trabaja sobre la raiz del repositorio (..\).
rem  Crea dos entornos virtuales:
rem    .venv32  Python 3.12 de 32 bits  -> gateway OPC (RSLinx es COM de 32 bits)
rem    .venv    Python 64 bits (3.13 o 3.12) -> HMI PySide6, puente, gemelo local, pruebas
rem  Requisitos previos: los dos Python instalados con el "py launcher" (ver mds\INSTALACION_LAB.md).
rem ============================================================================
setlocal
cd /d "%~dp0.."
echo.
echo === [1/4] Python de 32 bits para el gateway ===
py -3.12-32 -c "import sys; print('Python', sys.version.split()[0], '32 bits' if sys.maxsize < 2**32 else '64 bits')" 2>nul
if errorlevel 1 (
  echo   NO se encontro Python 3.12 de 32 bits. Instala python-3.12.x.exe ^(Windows installer 32-bit^)
  echo   desde python.org marcando "py launcher" y vuelve a ejecutar este archivo.
  goto :fin
)
if not exist .venv32\Scripts\python.exe py -3.12-32 -m venv .venv32
.venv32\Scripts\python.exe -m pip install --upgrade pip
.venv32\Scripts\python.exe -m pip install -r requirements-gateway.txt
if errorlevel 1 ( echo   Fallo la instalacion del gateway. & goto :fin )

echo.
echo === [2/4] Python de 64 bits para el HMI, el puente y el gemelo ===
set PY64=
py -3.13-64 -c "import sys" >nul 2>nul
if not errorlevel 1 set PY64=-3.13-64
if "%PY64%"=="" (
  py -3.12-64 -c "import sys" >nul 2>nul
  if not errorlevel 1 set PY64=-3.12-64
)
if "%PY64%"=="" (
  echo   NO se encontro Python 3.13 ni 3.12 de 64 bits. Instala python-3.13.x-amd64.exe con "py launcher".
  goto :fin
)
py %PY64% -c "import sys; print('Python', sys.version.split()[0], '64 bits')"
if not exist .venv\Scripts\python.exe py %PY64% -m venv .venv
.venv\Scripts\python.exe -m pip install --upgrade pip
.venv\Scripts\python.exe -m pip install -r requirements-hmi.txt "pytest>=7,<9"
if errorlevel 1 ( echo   Fallo la instalacion del HMI. & goto :fin )

echo.
echo === [3/4] Comprobaciones ===
.venv32\Scripts\python.exe -c "import zmq, msgpack, loguru, win32com, OpenOPC; print('gateway 32 bits: dependencias OK')"
if errorlevel 1 echo   AVISO: falta algo en .venv32 (OpenOPC o pywin32). Revisa mds\INSTALACION_LAB.md seccion 3.
.venv\Scripts\python.exe -c "import zmq, msgpack, loguru, aiohttp, PySide6.QtQuick; print('HMI 64 bits: dependencias OK')"
if errorlevel 1 echo   AVISO: falta algo en .venv (PySide6 o aiohttp).

echo.
echo === [4/4] Pruebas automaticas (sin PLC, ~30 s) ===
.venv\Scripts\python.exe -m pytest tests -q
echo.
echo Listo. Siguiente paso: lab\probar_opc.bat --servidores   (ver mds\INSTALACION_LAB.md)
:fin
endlocal
pause
