# Proyecto 1 · Control y supervisión de sistema secuencial electroneumático

Estación electroneumática de cinco cilindros gobernada por un PLC Allen‑Bradley SLC 5/04 (Ladder IEC 61131‑3 derivado de un GRAFCET), supervisada desde un HMI en Python (PySide6 + QML) comunicado por OPC DA con RSLinx Classic, y con un gemelo digital web.

Universidad Nacional Autónoma de México · Facultad de Ingeniería · División de Ingeniería Eléctrica · Control Distribuido e Integración SCADA (clave 1095), semestre 2027‑1.
Autor: Daan Yael Maldonado Uriostigue · Profesor: Ing. David Quintanar Villalba.

| | |
|---|---|
| Entregables del proyecto (documentos PMI, informe, planos, evidencias) | [Carpeta ENTREGABLES en Google Drive](https://drive.google.com/drive/folders/1-GG7s85rkc2Q7_lxWhho26UZA0iYyy8G?usp=sharing) |
| Gemelo digital (requiere cuenta) | <https://digitaltwinscada.smartsensorslab.com> |
| Código | este repositorio |

## Qué contiene

```
01_Integracion/
├─ 03_Ingenieria/
│  ├─ ladder/                 programa del SLC 5/04 (RSLogix 500): PROYECTO1_TEST.RSS y su base de documentación
│  └─ simulacion_simulink/    modelo P1_secuencia.slx (MATLAB R2025a, Simulink + Stateflow), scripts y figuras
│                             documentacion_tecnica/documentacion_tecnica_simulink.pdf
└─ 04_Software/               gateway OPC DA, HMI (PySide6 + QML), puente, gemelo digital, pruebas y lanzadores .bat
                              docs/documentacion_tecnica/documentacion_tecnica.pdf
instalacion_python/           guías de instalación y réplica del proyecto, y gbda_aut.dll (OPC DA Automation)
```

## Arquitectura

```
SLC 5/04 ──DF1──► 1761-NET-ENI ──Ethernet──► RSLinx Classic (OPC DA) ──COM──► gateway (Python 3.12, 32 bits)
                                                                                   │ ZeroMQ + msgpack
                                                                                   ▼
                                    HMI (Python 3.13, 64 bits, PySide6 + QML)   puente ──MQTT/WSS──► servidor del gemelo
                                                                                              (aiohttp + three.js, Cloudflare Tunnel)
```

El gateway corre en un Python de 32 bits porque OPC DA es una interfaz COM de 32 bits; el HMI corre en 64 bits y los dos se comunican por ZeroMQ. El mismo software trabaja en tres modos: **SIM** (Ladder simulado en Python, sin PLC), **EMULATE** (RSLogix Emulate 500) y **REAL** (SLC 5/04).

## Instalación y réplica

Requisitos: Windows 10/11, Python 3.12 de 32 bits y Python 3.13 de 64 bits (con el *py launcher*), y RSLinx Classic con servidor OPC sólo para el modo REAL.

1. Lee las guías de [`instalacion_python/`](instalacion_python/):
   - `guia_instalacion_python_qt_opc.pdf` — Python de 32 y 64 bits, PySide6/Qt, OPC Core Components, registro de `gbda_aut.dll` y configuración de RSLinx.
   - `guia_replicar_proyecto_github.pdf` — descarga del repositorio, lanzadores `.bat` y pruebas de aceptación.
2. Registra la DLL de OPC (consola como administrador, con el `regsvr32` de 32 bits):
   ```bat
   copy instalacion_python\gbda_aut.dll C:\Windows\SysWOW64\
   C:\Windows\SysWOW64\regsvr32.exe C:\Windows\SysWOW64\gbda_aut.dll
   ```
3. Instala y prueba el software:
   ```bat
   cd 01_Integracion\04_Software
   lab\instalar.bat          REM crea .venv32 (32 bits) y .venv (64 bits), instala dependencias y corre las pruebas
   lab\hmi_sim.bat           REM HMI con el gateway simulado, sin PLC
   lab\probar_opc.bat --servidores
   lab\hmi.bat               REM con el PLC: ventana de conexión → REAL → Conectar
   lab\gemelo_local.bat      REM gemelo digital en la misma PC, sin internet
   ```

La guía detallada del software está en [`01_Integracion/04_Software/docs/GUIA_INSTALACION_HMI.md`](01_Integracion/04_Software/docs/GUIA_INSTALACION_HMI.md).

## Programa del PLC y simulación

- `01_Integracion/03_Ingenieria/ladder/PROYECTO1_TEST.RSS`: rutina Ladder (LAD 2, 26 escalones) para el SLC 5/04 1747‑L541C con módulos 1746‑IB16 y 1746‑OB16. La tabla de variables está en [`01_Integracion/04_Software/docs/TABLA_DE_VARIABLES.md`](01_Integracion/04_Software/docs/TABLA_DE_VARIABLES.md).
- `01_Integracion/03_Ingenieria/simulacion_simulink/`: simulación de la secuencia completa (PLC en Stateflow, cilindros 1A–3A y cadena neumática 4A/5A). Abre `P1_secuencia.slx` en MATLAB R2025a y pulsa *Run*; `graficar_tiempos_p1.m` regenera las gráficas de tiempos.

## Componentes de terceros

`gbda_aut.dll` (Graybox OPC DA Automation Wrapper, distribuida con OpenOPC), la tipografía Inter (SIL Open Font License) y three.js (licencia MIT) conservan sus licencias originales.
