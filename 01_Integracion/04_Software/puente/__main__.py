# -*- coding: utf-8 -*-
r"""
puente/__main__.py — Arranque del puente HMI ⇄ servidor web del gemelo.

    .venv\Scripts\python.exe -m puente --url wss://digitaltwinscada.smartsensorslab.com/ws/planta
    .venv\Scripts\python.exe -m puente --url ws://127.0.0.1:3002/ws/planta             (prueba local)
    .venv\Scripts\python.exe -m puente --mqtt mqtt+wss://puente:CLAVE@broker.smartsensorslab.com
    .venv\Scripts\python.exe -m puente --mqtt mqtts://puente:CLAVE@broker.smartsensorslab.com:8883

Transporte: con `--url` el puente abre un WebSocket saliente hacia el servidor (/ws/planta); con
`--mqtt` publica y escucha en un broker MQTT (topics `<prefijo>/<planta>/…`, mensajes sellados con la
clave). Se usa uno u otro; si se dan los dos, manda `--mqtt`. Contrato: mds/ENLACE_WEB.md §3, §4 y §7.

La clave compartida con el servidor se lee de datos/puente.clave (la genera el servidor
la primera vez que arranca). Para traerla sin copiar archivos: `python -m puente.vincular
--usuario <admin>` (o «Vincular» en la ventana de conexión del HMI), que la pide al servidor con
una cuenta admin del gemelo.

Modo suave (`--suave auto|si|no`, defecto auto): con lecturas lentas del PLC el gemelo recibe la
misma animación prevista que el HMI (core/suavizado.py) y un bloque `suave` para seguir el
movimiento entre snapshots.

Compatibilidad: Python 3.12 a 3.13. Dependencias: aiohttp, pyzmq, msgpack; paho-mqtt con --mqtt.
"""
import argparse
import asyncio
import os
import sys

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if RAIZ not in sys.path:
    sys.path.insert(0, RAIZ)

from core import enlace_mqtt, protocolo, remoto  # noqa: E402
from puente.enlace import Puente  # noqa: E402


def _argumentos(argv=None):
    p = argparse.ArgumentParser(prog="python -m puente", description=__doc__.split("\n\n")[0])
    p.add_argument("--url", default=None, help="WebSocket del servidor: wss://…/ws/planta")
    p.add_argument("--mqtt", default=None, metavar="URL",
                   help="broker MQTT en vez del WebSocket: mqtt://, mqtts://, mqtt+ws:// o mqtt+wss://usuario:clave@host[:puerto][/ruta]")
    p.add_argument("--prefijo", default=enlace_mqtt.PREFIJO_DEFECTO,
                   help="prefijo de los topics MQTT (defecto %s)" % enlace_mqtt.PREFIJO_DEFECTO)
    p.add_argument("--clave", default=os.path.join(RAIZ, "datos", "puente.clave"),
                   help="archivo con la clave compartida (defecto datos/puente.clave)")
    p.add_argument("--pub", default=protocolo.PUB_DEFECTO, help="PUB del gateway")
    p.add_argument("--cmd", default=protocolo.CMD_DEFECTO, help="REP del gateway")
    p.add_argument("--hz", type=float, default=20.0, help="snapshots por segundo hacia la web como máximo (defecto 20)")
    p.add_argument("--planta", default=enlace_mqtt.PLANTA_DEFECTO,
                   help="nombre de la planta; con --mqtt es también el segmento del topic (defecto %s)" % enlace_mqtt.PLANTA_DEFECTO)
    p.add_argument("--calibracion", default=os.path.join(RAIZ, "datos", "calibracion.json"),
                   help="calibración de carreras del HMI (solo lectura) para estimar pos en REAL")
    p.add_argument("--suave", choices=("auto", "si", "no"), default="auto",
                   help="modo suave hacia el gemelo (core.suavizado): auto = cuando el gateway no da pos "
                        "(REAL, --simular-enlace); si = siempre; no = nunca (defecto auto)")
    a = p.parse_args(argv)
    if not a.url and not a.mqtt:
        p.error("indica --url wss://…/ws/planta o --mqtt mqtts://usuario:clave@broker")
    if a.mqtt and not enlace_mqtt.es_url_mqtt(a.mqtt):
        p.error("--mqtt debe empezar por mqtt://, mqtts://, mqtt+ws:// o mqtt+wss://")
    return a


def main(argv=None):
    for flujo in (sys.stdout, sys.stderr):
        try:
            flujo.reconfigure(encoding="utf-8", errors="replace")   # la consola de Windows no imprime "⇄" ni "…"
        except (AttributeError, ValueError):
            pass
    a = _argumentos(argv)
    try:
        clave = remoto.leer_clave(a.clave)
    except (OSError, ValueError) as e:
        print("[puente] %s" % e)
        print("[puente] tráela con «Vincular» en la ventana de conexión del HMI, con "
              "`python -m puente.vincular --usuario <admin>`, o copia aquí el datos/puente.clave del servidor web.")
        return 2
    local = ("127.0.0.1", "localhost")
    if a.url and a.url.startswith("ws://") and not any(h in a.url for h in local):
        print("[puente] AVISO: %s no va cifrado; por Internet usa wss://." % a.url)
    if a.mqtt and a.mqtt.split("://", 1)[0] in ("mqtt", "mqtt+ws") and not any(h in a.mqtt for h in local):
        print("[puente] AVISO: %s no va cifrado (la clave del broker viaja en claro); por Internet usa mqtts:// o mqtt+wss://."
              % enlace_mqtt.ocultar_clave(a.mqtt))
    if sys.platform == "win32" and sys.version_info >= (3, 8):
        # zmq.asyncio necesita el bucle con selector en Windows
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    puente = Puente(a.url, clave, pub=a.pub, cmd=a.cmd, hz=a.hz, planta=a.planta,
                    ruta_calibracion=a.calibracion if os.path.exists(a.calibracion) else None,
                    mqtt=a.mqtt, prefijo=a.prefijo, suave=a.suave)
    try:
        asyncio.run(puente.correr())
    except KeyboardInterrupt:
        print("[puente] detenido")
    return 0


if __name__ == "__main__":
    sys.exit(main())
