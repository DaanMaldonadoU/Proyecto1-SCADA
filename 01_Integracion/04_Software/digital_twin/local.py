# -*- coding: utf-8 -*-
r"""
digital_twin/local.py — Gemelo digital EN LOCAL: servidor web + puente en un solo proceso, sin internet.

Para probar el gemelo en la misma máquina que el gateway (laboratorio o desarrollo) sin Cloudflare,
sin copiar claves entre máquinas y sin crear cuentas a mano:

    .venv\Scripts\python.exe -m digital_twin.local                  # usa el gateway que ya corre en 5555/5556
    .venv\Scripts\python.exe -m digital_twin.local --gateway SIM    # arranca además un gateway SIM (--remoto)
    .venv\Scripts\python.exe -m digital_twin.local --host 0.0.0.0   # visible en la LAN: http://<IP de esta PC>:3002
    .venv\Scripts\python.exe -m digital_twin.local --publico        # se ve sin iniciar sesión (rol usuario)
    .venv\Scripts\python.exe -m digital_twin.local --sin-navegador --puerto 3010

Qué hace:
    * Levanta digital_twin/servidor_web (aiohttp) en http://127.0.0.1:3002 con su base y su clave en
      datos/gemelo_local/ (ignorado por git), separadas de las del servidor "de verdad".
    * Crea, si no existen, cuatro cuentas de prueba, una por rol:
          admin / admin1234 · ingeniero / ingeniero1234 · operador / operador1234 · usuario / usuario1234
    * Arranca el puente (puente/enlace.py) en el MISMO proceso, apuntando a ws://127.0.0.1:<puerto>/ws/planta
      con la misma clave: el tramo gateway → servidor pasa por loopback y su latencia (lat_web_ms) es la
      del propio código, no la de la red. Con --gateway SIM también arranca el gateway como subproceso.
    * Abre el navegador en el gemelo. Para probar roles y concurrencia, abre otra ventana de incógnito
      (la cookie de sesión es por navegador) y entra con otra cuenta.

Para EMULATE o REAL el gateway se arranca aparte con el Python de 32 bits (ver mds/INSTALACION_LAB.md)
y este módulo se conecta a él por ZeroMQ como lo hace el HMI. El mando remoto debe estar habilitado
(interruptor Web del HMI o `--remoto` en el gateway) para que la web pueda mandar; STOP pasa siempre.

Compatibilidad: Python 3.12 a 3.13 (64 bits, el del HMI). Dependencias: aiohttp, pyzmq, msgpack.
"""
import argparse
import asyncio
import os
import subprocess
import sys
import webbrowser

AQUI = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.dirname(AQUI)
if RAIZ not in sys.path:
    sys.path.insert(0, RAIZ)

from core import protocolo, remoto  # noqa: E402

DATOS_DEFECTO = os.path.join(RAIZ, "datos", "gemelo_local")
PUERTO_DEFECTO = 3002
CUENTAS_PRUEBA = (("admin", "admin1234", "admin"), ("ingeniero", "ingeniero1234", "ingeniero"),
                  ("operador", "operador1234", "operador"), ("usuario", "usuario1234", "usuario"))


class GemeloLocal:
    """Servidor web del gemelo + puente al gateway, en el bucle asyncio actual."""

    def __init__(self, datos=DATOS_DEFECTO, host="127.0.0.1", puerto=PUERTO_DEFECTO, publico=False,
                 pub=protocolo.PUB_DEFECTO, cmd=protocolo.CMD_DEFECTO, hz=20.0,
                 planta="estacion-electroneumatica (local)", index=None, log=print, suave="auto"):
        self.datos = datos
        self.host = host
        self.puerto = puerto
        self.publico = publico
        self.pub = pub
        self.cmd = cmd
        self.hz = hz
        self.suave = suave
        self.planta = planta
        self.index = index
        self.log = log
        self.servidor = None
        self.puente = None
        self._runner = None
        self._tarea_puente = None
        self.puerto_real = None

    @property
    def url(self):
        host = "127.0.0.1" if self.host in ("0.0.0.0", "") else self.host
        return "http://%s:%d" % (host, self.puerto_real or self.puerto)

    def _crear_cuentas(self):
        creadas = []
        for usuario, clave, rol in CUENTAS_PRUEBA:
            if self.servidor.almacen.usuario(usuario) is None:
                self.servidor.almacen.crear_usuario(usuario, clave, rol)
                creadas.append(usuario)
        return creadas

    async def arrancar(self):
        from aiohttp import web
        from digital_twin.servidor_web.app import ServidorGemelo
        from puente.enlace import Puente

        os.makedirs(self.datos, exist_ok=True)
        clave = remoto.leer_clave(os.path.join(self.datos, "puente.clave"), crear=True)
        self.servidor = ServidorGemelo(self.datos, clave, publico=self.publico, index=self.index)
        creadas = self._crear_cuentas()
        self._runner = web.AppRunner(self.servidor.aplicacion())
        await self._runner.setup()
        sitio = web.TCPSite(self._runner, self.host, self.puerto)
        await sitio.start()
        self.puerto_real = sitio._server.sockets[0].getsockname()[1]
        calibracion = os.path.join(RAIZ, "datos", "calibracion.json")
        self.puente = Puente("ws://127.0.0.1:%d/ws/planta" % self.puerto_real, clave, pub=self.pub, cmd=self.cmd,
                             hz=self.hz, planta=self.planta, log=self.log, suave=self.suave,
                             ruta_calibracion=calibracion if os.path.exists(calibracion) else None)
        self._tarea_puente = asyncio.ensure_future(self.puente.correr())
        self.log("[gemelo local] servidor en %s (datos en %s)" % (self.url, self.datos))
        if creadas:
            self.log("[gemelo local] cuentas de prueba creadas: %s" % ", ".join(creadas))
        self.log("[gemelo local] cuentas: " + " · ".join("%s / %s (%s)" % c for c in CUENTAS_PRUEBA))
        self.log("[gemelo local] puente hacia el gateway: SUB %s · REQ %s" % (self.pub, self.cmd))
        return self.url

    async def parar(self):
        if self.puente is not None:
            self.puente.detener()
        if self._tarea_puente is not None:
            try:
                await asyncio.wait_for(self._tarea_puente, 5)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                self._tarea_puente.cancel()
        if self._runner is not None:
            await self._runner.cleanup()


def _argumentos(argv=None):
    p = argparse.ArgumentParser(prog="python -m digital_twin.local",
                                description="Gemelo digital en local: servidor web + puente, sin internet.")
    p.add_argument("--host", default="127.0.0.1", help="127.0.0.1 (solo esta PC) o 0.0.0.0 (toda la LAN)")
    p.add_argument("--puerto", type=int, default=PUERTO_DEFECTO)
    p.add_argument("--datos", default=DATOS_DEFECTO, help="carpeta de la base, la clave y la auditoría")
    p.add_argument("--publico", action="store_true", help="ver el gemelo sin iniciar sesión (rol usuario)")
    p.add_argument("--gateway", choices=("SIM",), default=None,
                   help="arranca también un gateway SIM con --remoto (EMULATE/REAL van aparte, en 32 bits)")
    p.add_argument("--pub", default=protocolo.PUB_DEFECTO, help="PUB del gateway")
    p.add_argument("--cmd", default=protocolo.CMD_DEFECTO, help="REP del gateway")
    p.add_argument("--hz", type=float, default=20.0, help="snapshots por segundo hacia el navegador (máx.)")
    p.add_argument("--index", default=None, help="otro HTML de frontend (defecto digital_twin/index.html)")
    p.add_argument("--sin-navegador", action="store_true", help="no abrir el navegador")
    p.add_argument("--suave", choices=("auto", "si", "no"), default="auto",
                   help="modo suave del puente (core.suavizado): auto = cuando el gateway no da pos (defecto)")
    return p.parse_args(argv)


async def _correr(a, hijo):
    gemelo = GemeloLocal(datos=a.datos, host=a.host, puerto=a.puerto, publico=a.publico, pub=a.pub, cmd=a.cmd,
                         hz=a.hz, index=a.index, suave=a.suave)
    url = await gemelo.arrancar()
    if a.host == "0.0.0.0":
        print("[gemelo local] desde otro dispositivo de la LAN: http://<IP de esta PC>:%d" % gemelo.puerto_real)
    if not a.sin_navegador:
        webbrowser.open(url)
    print("[gemelo local] Ctrl+C para salir")
    try:
        while True:
            await asyncio.sleep(1.0)
            if hijo is not None and hijo.poll() is not None:
                print("[gemelo local] el gateway terminó (código %s)" % hijo.returncode)
                hijo = None
    finally:
        await gemelo.parar()


def main(argv=None):
    a = _argumentos(argv)
    for flujo in (sys.stdout, sys.stderr):
        try:
            flujo.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())   # zmq.asyncio lo necesita
    hijo = None
    if a.gateway:
        orden = [sys.executable, "-m", "gateway", "--modo", a.gateway, "--remoto", "--pub", a.pub, "--cmd", a.cmd]
        hijo = subprocess.Popen(orden, cwd=RAIZ)
        print("[gemelo local] gateway %s arrancado (pid %d) con el mando remoto habilitado" % (a.gateway, hijo.pid))
    try:
        asyncio.run(_correr(a, hijo))
    except KeyboardInterrupt:
        print("[gemelo local] detenido")
    finally:
        if hijo is not None and hijo.poll() is None:
            hijo.terminate()
            try:
                hijo.wait(timeout=3)
            except subprocess.TimeoutExpired:
                hijo.kill()
    return 0


if __name__ == "__main__":
    sys.exit(main())
