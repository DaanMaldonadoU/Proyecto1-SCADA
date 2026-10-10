# digital_twin — gemelo digital web

Gemelo digital de la estación electroneumática para una PC servidor aparte (`https://digitaltwinscada.smartsensorslab.com`, servidor local en el puerto 3002) o para la misma máquina, en local. Contexto y decisiones: `../mds/GEMELO_DIGITAL.md`. Contrato de mensajes: `../mds/ENLACE_WEB.md`. Despliegue: `../mds/DESPLIEGUE_SERVIDOR.md`.

## Qué hay aquí

| Ruta | Qué es |
|---|---|
| `index.html` | **Frontend del gemelo** (lo sirve el servidor en `/`): escena 3D del tablero neumático (three.js r128) más el tablero de mando web (sesión, mando, START/STOP/RESET, parámetros, GRAFCET, señales, presencia, actividad, cuentas y auditoría). Un solo archivo, sin proceso de construcción. En pantallas angostas (celular, tableta) el tablero va por **pestañas**, la tira inferior se compacta y la cámara se abre en vertical. |
| `servidor_web/` | Servidor aiohttp: cuentas y roles (SQLite), sesión por cookie, WebSocket `/ws/web` para navegadores y `/ws/planta` para el puente del HMI, **o** el puente por MQTT (`--mqtt URL`, `core/enlace_mqtt.py`), auditoría, `/api/salud`. `python -m digital_twin.servidor_web` (puerto 3002). La consola de prueba está en `/consola` (`servidor_web/estatico/consola.html`). |
| `servidor_web/estatico/` | `three.min.js` (copia local de three.js r128: el gemelo funciona sin internet), `manifest.webmanifest` e `icono.svg` (añadir a la pantalla de inicio del celular), `consola.html`. |
| `local.py` | `python -m digital_twin.local [--gateway SIM]`: servidor + puente en un proceso, cuentas de prueba, sin internet, `http://127.0.0.1:3002`. |
| `despliegue/` | Para la PC servidor Windows: `instalar_servidor.bat`, `servidor.bat`, `cuentas.bat`, `Caddyfile`, `cloudflared-config.yml`, `mosquitto.conf` y `mosquitto_acl.conf`. Ver `despliegue/README.md`. |
| `new_front/` | Material de partida del frontend 3D tal como lo entregó el autor (escena con simulación propia y un `server.py` de OPC UA de demostración). No se usa en ejecución; la escena ya está integrada en `index.html`. |
| `server.py` | Versión anterior del servidor de demostración (OPC UA). Obsoleto; se conserva como referencia. |
| `datos/` | Base `gemelo.sqlite`, `puente.clave` y `mqtt.url` en ejecución (ignorado por git). |

## Cómo llegan los datos del HMI

El puente (`../puente/`) corre junto al HMI del laboratorio y reenvía lo que publica el gateway; manda al PLC solo órdenes firmadas que el gateway vuelve a autorizar. Dos transportes con los mismos mensajes (`../mds/ENLACE_WEB.md` §4 y §7):

```bat
python -m puente --mqtt mqtt+wss://puente:CLAVE@broker.smartsensorslab.com      REM MQTT (broker en la PC servidor)
python -m puente --url wss://digitaltwinscada.smartsensorslab.com/ws/planta     REM WebSocket directo
```
Por MQTT cada mensaje va en un sobre sellado con HMAC de `puente.clave`; el servidor se suscribe con `--mqtt mqtt://gemelo:CLAVE@127.0.0.1:1883` (o `datos/mqtt.url`). Si llegan los dos, manda el WebSocket.

## Qué muestra el frontend

Solo se mueve lo que existe en el PLC de este proyecto (`../docs/TABLA_DE_VARIABLES.md` sección 1):

| Cilindro del tablero | Fuente en el snapshot | Detalle |
|---|---|---|
| 1A, 2A, 3A | `pos[0..2]`, bits `SC/SE`, `EV_E/EV_C` | Bobinas en el manifold izquierdo; los tubos se iluminan según la memoria de la válvula 5/2; en REAL la posición es estimada (`pos_estimada`) y la tira inferior lo indica. |
| 4A, 5A | `pos_neum[0..1]` | Cadena neumática sin sensores en el PLC: posición por modelo de tiempos durante la ventana `T4:5`; rodillos `C4A/E4A/C5A/E5A` por posición. |
| 1B, 2B, 3B, 4B, 5B | — | Están en el tablero real, no en este proyecto: quietos, con etiqueta gris. |

Panel de mando 3D: START/STOP/RESET mandan pulsos `STARTV/STOPV/RESETV` con los mismos permisos que los botones del tablero; se hunden con `START_1`, `STOP_1` (NC) y los pulsos; el piloto verde es `ACTIVE`. Las posiciones recibidas se interpolan con un retraso de ~1,5 periodos de muestreo para que el vástago no dé saltos.

Píldoras de la cabecera: planta (`Planta en línea · REAL · MQTT` o `WS`) y latencias `PLC` (lectura del gateway), `enlace` (ida y vuelta puente ⇄ servidor, `lat_web_ms`) y `web` (ida y vuelta servidor ⇄ navegador). El botón **Panel** deja solo la escena 3D.

## Probar en local (sin internet)

```bat
.venv\Scripts\python.exe -m digital_twin.local --gateway SIM          REM todo en uno: http://127.0.0.1:3002
```
Paso a paso (lo mismo que hace `local.py`):
```bat
.venv\Scripts\python.exe -m gateway --modo SIM --remoto
.venv\Scripts\python.exe -m digital_twin.servidor_web usuario-crear prueba --rol admin
.venv\Scripts\python.exe -m digital_twin.servidor_web
copy digital_twin\datos\puente.clave datos\puente.clave
.venv\Scripts\python.exe -m puente --url ws://127.0.0.1:3002/ws/planta
REM navegador: http://127.0.0.1:3002/
```
Camino MQTT sin Mosquitto: `python -m tests.broker_mqtt_minimo --puerto 1883`, servidor con `--mqtt mqtt://127.0.0.1:1883`, puente con `--mqtt mqtt://127.0.0.1:1883`.

Pruebas automáticas: `pytest tests/test_enlace_web.py tests/test_gemelo_local.py tests/test_enlace_mqtt.py -q`; con navegador real (Playwright): `pytest tests/test_frontend_web.py -q` (requiere `pip install playwright` y `python -m playwright install chromium-headless-shell`; si no están, se omite). Deja capturas en `datos/capturas/` (`gemelo_3d_marcha.png`, `gemelo_3d_admin.png`, `gemelo_3d_movil.png`).
