# -*- coding: utf-8 -*-
r"""
digital_twin/servidor_web/__main__.py — Arranque del servidor del gemelo y gestión de cuentas.

Desde la raíz del repositorio (en la PC servidor):
    python -m digital_twin.servidor_web                          # sirve en http://127.0.0.1:3002
    python -m digital_twin.servidor_web --mqtt mqtt://gemelo:CLAVE@127.0.0.1:1883   # además escucha al puente por MQTT
    python -m digital_twin.servidor_web --publico                # sin sesión se ve el gemelo (rol usuario)
    python -m digital_twin.servidor_web usuario-crear daan --rol admin
    python -m digital_twin.servidor_web usuario-rol ana ingeniero
    python -m digital_twin.servidor_web usuario-clave ana
    python -m digital_twin.servidor_web usuario-borrar ana
    python -m digital_twin.servidor_web usuarios
    python -m digital_twin.servidor_web auditoria --n 50
    python -m digital_twin.servidor_web clave                   # muestra la clave del puente
    python -m digital_twin.servidor_web clave-diagnostico       # ¿el servidor en marcha usa esa clave? (y por Internet)
    python -m digital_twin.servidor_web clave-fijar <CLAVE>     # usar esta clave (p. ej. la del HMI); luego reiniciar

La URL del broker MQTT también puede venir de la variable de entorno GEMELO_MQTT_URL o del archivo
<datos>/mqtt.url (una línea), para no escribir la contraseña del broker en la línea de órdenes.

La primera vez crea digital_twin/datos/puente.clave: se copia a la máquina del HMI como
datos/puente.clave. Por defecto escucha solo en 127.0.0.1:3002: el acceso desde Internet lo da el
proxy inverso o el túnel que publica digitaltwinscada.smartsensorslab.com (mds/DESPLIEGUE_SERVIDOR.md).

Compatibilidad: Python 3.12 a 3.13. Dependencias: aiohttp; paho-mqtt con --mqtt.
"""
import argparse
import getpass
import os
import sys
import time

AQUI = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.dirname(os.path.dirname(AQUI))
if RAIZ not in sys.path:
    sys.path.insert(0, RAIZ)

from core import enlace_mqtt, remoto  # noqa: E402
from core.mando import ROLES  # noqa: E402

DATOS_DEFECTO = os.path.join(RAIZ, "digital_twin", "datos")
PUERTO_DEFECTO = 3002
VARIABLE_MQTT = "GEMELO_MQTT_URL"


def _pedir_clave(usuario):
    while True:
        c1 = getpass.getpass("Contraseña para %s: " % usuario)
        c2 = getpass.getpass("Repite la contraseña: ")
        if c1 == c2:
            return c1
        print("No coinciden; otra vez.")


def url_mqtt(args):
    """--mqtt, si no la variable de entorno, si no el archivo <datos>/mqtt.url; None si no hay nada."""
    if args.mqtt:
        return args.mqtt.strip()
    de_entorno = os.environ.get(VARIABLE_MQTT, "").strip()
    if de_entorno:
        return de_entorno
    ruta = os.path.join(args.datos, "mqtt.url")
    if os.path.exists(ruta):
        with open(ruta, "r", encoding="utf-8") as f:
            for linea in f:
                linea = linea.strip()
                if linea and not linea.startswith("#"):
                    return linea
    return None


def main(argv=None):
    for flujo in (sys.stdout, sys.stderr):
        try:
            flujo.reconfigure(encoding="utf-8", errors="replace")   # acentos y "…" en la consola de Windows
        except (AttributeError, ValueError):
            pass
    p = argparse.ArgumentParser(prog="python -m digital_twin.servidor_web")
    p.add_argument("--datos", default=DATOS_DEFECTO, help="carpeta de la base y la clave del puente")
    sub = p.add_subparsers(dest="orden")
    s = sub.add_parser("servir", help="arranca el servidor (orden por defecto)")
    for q in (p, s):
        q.add_argument("--host", default="127.0.0.1")
        q.add_argument("--port", type=int, default=PUERTO_DEFECTO)
        q.add_argument("--publico", action="store_true", help="permite ver el gemelo sin iniciar sesión")
        q.add_argument("--index", default=None, help="HTML del frontend (defecto digital_twin/index.html)")
        q.add_argument("--mqtt", default=None, metavar="URL",
                       help="broker MQTT por el que llega el puente (mqtt://, mqtts://, mqtt+ws://, mqtt+wss://"
                            "usuario:clave@host[:puerto]); también %s o <datos>/mqtt.url" % VARIABLE_MQTT)
        q.add_argument("--planta", default=enlace_mqtt.PLANTA_DEFECTO,
                       help="segmento de planta en los topics MQTT (debe coincidir con --planta del puente)")
        q.add_argument("--prefijo", default=enlace_mqtt.PREFIJO_DEFECTO, help="prefijo de los topics MQTT")
    c = sub.add_parser("usuario-crear")
    c.add_argument("usuario")
    c.add_argument("--rol", default="usuario", choices=list(ROLES))
    c.add_argument("--clave", default=None, help="(mejor omitir: se pide sin eco)")
    r = sub.add_parser("usuario-rol")
    r.add_argument("usuario")
    r.add_argument("rol", choices=list(ROLES))
    k = sub.add_parser("usuario-clave")
    k.add_argument("usuario")
    b = sub.add_parser("usuario-borrar")
    b.add_argument("usuario")
    sub.add_parser("usuarios")
    a = sub.add_parser("auditoria")
    a.add_argument("--n", type=int, default=50)
    sub.add_parser("clave")
    d = sub.add_parser("clave-diagnostico", help="comprueba la clave del puente contra el servidor en marcha")
    d.add_argument("--port", type=int, default=PUERTO_DEFECTO)
    d.add_argument("--url-publica", default="wss://digitaltwinscada.smartsensorslab.com/ws/planta")
    d.add_argument("--sin-internet", action="store_true", help="solo la prueba en el propio servidor")
    f = sub.add_parser("clave-fijar", help="guarda esta clave como la del puente (reiniciar después)")
    f.add_argument("clave_nueva", metavar="CLAVE")
    args = p.parse_args(argv)

    ruta_clave = os.path.join(args.datos, "puente.clave")
    from digital_twin.servidor_web.usuarios import Almacen
    orden = args.orden or "servir"

    if orden == "clave":
        print(remoto.leer_clave(ruta_clave, crear=True))
        return 0
    if orden == "clave-diagnostico":
        from digital_twin.servidor_web.diagnostico_clave import diagnosticar
        r = diagnosticar(args.datos, puerto=args.port, url_publica=args.url_publica, probar_publica=not args.sin_internet)
        return 0 if r in ("ok", "puente_conectado") else 1
    if orden == "clave-fijar":
        from digital_twin.servidor_web.diagnostico_clave import fijar
        try:
            fijar(args.datos, args.clave_nueva)
        except (OSError, ValueError) as e:
            print("Error: %s" % e)
            return 1
        return 0
    if orden != "servir":
        al = Almacen(os.path.join(args.datos, "gemelo.sqlite"))
        try:
            if orden == "usuario-crear":
                al.crear_usuario(args.usuario, args.clave or _pedir_clave(args.usuario), args.rol)
                al.auditar("consola", "admin", "local", "usuarios", "crear %s %s" % (args.usuario, args.rol), True, "")
                print("Creado %s (%s)" % (args.usuario, args.rol))
            elif orden == "usuario-rol":
                print("OK" if al.cambiar_rol(args.usuario, args.rol) else "No existe %s" % args.usuario)
            elif orden == "usuario-clave":
                print("OK" if al.cambiar_clave(args.usuario, _pedir_clave(args.usuario)) else "No existe")
            elif orden == "usuario-borrar":
                print("Borrado" if al.borrar(args.usuario) else "No existe %s" % args.usuario)
            elif orden == "usuarios":
                for u in al.listar():
                    print("%-20s %-10s %s" % (u["usuario"], u["rol"], "activo" if u["activo"] else "INACTIVO"))
            elif orden == "auditoria":
                for f in reversed(al.auditoria(args.n)):
                    print("%s  %-12s %-10s %-8s %-6s %-22s %s" % (
                        time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(f["t"])), f["usuario"], f["rol"] or "",
                        f["accion"], "ok" if f["ok"] else "NO", f["detalle"] or "", f["msg"] or ""))
        except ValueError as e:
            print("Error: %s" % e)
            return 1
        finally:
            al.cerrar()
        return 0

    mqtt = url_mqtt(args)
    if mqtt and not enlace_mqtt.es_url_mqtt(mqtt):
        print("[gemelo] la URL MQTT debe empezar por mqtt://, mqtts://, mqtt+ws:// o mqtt+wss:// (recibido: %s)"
              % enlace_mqtt.ocultar_clave(mqtt))
        return 2
    if mqtt:
        try:
            import paho.mqtt  # noqa: F401
        except ImportError:
            print("[gemelo] falta paho-mqtt: pip install -r digital_twin\\servidor_web\\requirements.txt")
            return 2
    from aiohttp import web
    from digital_twin.servidor_web.app import ServidorGemelo
    nueva = not os.path.exists(ruta_clave)
    clave = remoto.leer_clave(ruta_clave, crear=True)
    srv = ServidorGemelo(args.datos, clave, publico=args.publico, index=args.index, mqtt=mqtt,
                         planta=args.planta, prefijo=args.prefijo)
    if nueva:
        print("[gemelo] Clave del puente creada en %s" % ruta_clave)
        print("[gemelo] Cópiala a la máquina del HMI como datos/puente.clave")
    if not srv.almacen.hay_admin():
        print("[gemelo] AVISO: no hay ninguna cuenta admin. Crea una con:")
        print("         python -m digital_twin.servidor_web usuario-crear <nombre> --rol admin")
    print("[gemelo] http://%s:%d  (frontend /, consola /consola, puente /ws/planta, salud /api/salud)" % (args.host, args.port))
    if mqtt:
        print("[gemelo] MQTT: %s · topics %s/…" % (enlace_mqtt.ocultar_clave(mqtt), srv.topics.base))
    else:
        print("[gemelo] MQTT: desactivado (el puente llega por /ws/planta); activar con --mqtt URL")
    web.run_app(srv.aplicacion(), host=args.host, port=args.port, print=None)
    return 0


if __name__ == "__main__":
    sys.exit(main())
