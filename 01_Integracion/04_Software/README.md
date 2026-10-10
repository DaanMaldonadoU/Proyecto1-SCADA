# HMI de la estación electroneumática · SLC 5/04 · OPC DA

Control y Supervisión de Sistema Secuencial Electroneumático. HMI en Python (PySide6 + QML) que habla con un PLC Allen‑Bradley SLC 5/04 por OPC DA (RSLinx Classic), con gateway de 32 bits, simulador integrado y gemelo digital web opcional.

Universidad Nacional Autónoma de México · Facultad de Ingeniería · Control Distribuido e Integración SCADA · Daan Yael Maldonado Uriostigue.

## Para instalarlo y probarlo con el PLC

**Lee la guía paso a paso:** [`docs/GUIA_INSTALACION_HMI.md`](docs/GUIA_INSTALACION_HMI.md) · [versión en PDF](docs/GUIA_INSTALACION_HMI.pdf). Cubre los dos Python (32 y 64 bits), `lab\instalar.bat`, RSLinx y OPC, el diagnóstico y la conexión en modo REAL desde la ventana de conexión del HMI. Las guías generales de instalación de Python, Qt y OPC y de réplica del proyecto, y la DLL de OPC (`gbda_aut.dll`), están en [`instalacion_python/`](../../instalacion_python/) en la raíz del repositorio.

Resumen, desde esta carpeta (`01_Integracion\04_Software`):

```bat
lab\instalar.bat          REM crea .venv32 (Python 3.12 de 32 bits) y .venv (64 bits), instala y corre las pruebas
lab\hmi_sim.bat           REM primera prueba sin PLC (gateway simulado)
lab\probar_opc.bat --servidores
lab\hmi.bat               REM con el PLC: ventana de conexión → REAL → Conectar
lab\gemelo_local.bat      REM gemelo digital en esta misma PC, sin internet
```

## Carpetas

| Carpeta | Contenido |
|---|---|
| `ui/` | HMI (PySide6 o PyQt5, mismos QML): sinóptico, GRAFCET, mandos, parámetros, cronograma, monitor E/S, registro, latencia, ventana de conexión, visor de historial. `ui/qml/HMI.qmlproject` abre la pantalla en Qt Design Studio. |
| `gateway/` | Gateway OPC DA / simulador (`python -m gateway --modo SIM|EMULATE|REAL`) y diagnóstico OPC. |
| `core/` | Tabla de variables, protocolo ZeroMQ, calibración, estimador, modo suave, alarmas, historial, mando. |
| `lab/` | Lanzadores `.bat` para instalar y arrancar en la PC del laboratorio. |
| `digital_twin/`, `puente/` | Gemelo digital web (aiohttp, three.js), lanzadores de la PC servidor (`digital_twin/despliegue/`) y enlace saliente desde el HMI. |
| `assets/` | Sistema de diseño: cilindros por capas (ISO 15552 e ISO 6432), botones, LEDs, iconos, tipografía Inter. |
| `docs/` | Guías de instalación y uso, diagnóstico de la conexión con el PLC, tabla de variables y documentación técnica. |
| `mds/data.md` | Datos institucionales que usan el HMI y el gemelo en títulos y créditos. |
| `tests/` | Pruebas pytest (sin PLC ni ventana). |
| `old/` | HMI v6.1 (Tkinter), prototipo de la presentación preliminar. |

## Documentación técnica

- [`docs/documentacion_tecnica/documentacion_tecnica.pdf`](docs/documentacion_tecnica/documentacion_tecnica.pdf): documento completo del código (arquitectura, protocolos, bibliotecas, física y modelos, interfaz QML, sistema de diseño, Qt Design Studio, normas, gemelo digital, pruebas y latencia).
- [`docs/TABLA_DE_VARIABLES.md`](docs/TABLA_DE_VARIABLES.md): tabla de variables del PLC, secuencia del GRAFCET y mapa del Ladder; es la referencia de `core/tags.py`.
- [`docs/DIAGNOSTICO_CONEXION_PLC.md`](docs/DIAGNOSTICO_CONEXION_PLC.md): prueba con el PLC del 3 de octubre de 2026 y mediciones de latencia.
- [`docs/GUIA_MODO_SUAVE_Y_GEMELO.md`](docs/GUIA_MODO_SUAVE_Y_GEMELO.md): animación suave y envío al gemelo digital.

Algunos comentarios del código citan documentos de desarrollo de `mds/` (arquitectura, enlace web, despliegue) que no se publican; su contenido está en la documentación técnica.
