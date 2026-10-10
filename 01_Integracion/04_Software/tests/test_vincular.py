# -*- coding: utf-8 -*-
"""Vinculación del puente con una cuenta admin (puente/vincular.py ⇄ POST /api/puente/clave).

Sin red externa: el servidor del gemelo (ServidorGemelo real, aiohttp) corre en 127.0.0.1 con un
puerto efímero, en un hilo con su propio bucle asyncio, porque el cliente (urllib) es bloqueante
como lo será en el hilo del HMI. El Almacen (SQLite) se crea y se usa solo dentro de ese hilo.
"""
import asyncio
import os
import socket
import subprocess
import sys
import threading
import time
from collections import deque

import pytest

aiohttp = pytest.importorskip("aiohttp")
from aiohttp import web  # noqa: E402

from core import remoto  # noqa: E402
from puente import vincular  # noqa: E402
from puente.vincular import guardar_clave, obtener_clave, url_https  # noqa: E402

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CLAVE_ADMIN = "admin-clave-123"
CLAVE_OPE = "ope-clave-1234"


class ServidorEnHilo:
    """Arranca una app aiohttp en 127.0.0.1:<efímero> dentro de un hilo con su propio bucle.
    `fabrica()` se llama DENTRO del hilo (así SQLite queda en el hilo que lo usa)."""

    def __init__(self, fabrica):
        self._fabrica = fabrica
        self._listo = threading.Event()
        self._error = None
        self.loop = None
        self.objeto = None
        self.base = None
        self._hilo = threading.Thread(target=self._correr, daemon=True)

    def _correr(self):
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        runner = None
        try:
            self.objeto, app = self._fabrica()
            runner = web.AppRunner(app)
            self.loop.run_until_complete(runner.setup())
            sitio = web.TCPSite(runner, "127.0.0.1", 0)
            self.loop.run_until_complete(sitio.start())
            self.base = "http://127.0.0.1:%d" % sitio._server.sockets[0].getsockname()[1]
        except Exception as e:      # noqa: BLE001 — se reporta en el hilo de la prueba
            self._error = e
            self._listo.set()
            return
        self._listo.set()
        try:
            self.loop.run_forever()
        finally:
            self.loop.run_until_complete(runner.cleanup())
            self.loop.close()

    def arrancar(self):
        self._hilo.start()
        assert self._listo.wait(10.0), "el servidor de prueba no arrancó"
        if self._error is not None:
            raise self._error
        return self

    def en_hilo(self, funcion):
        """Ejecuta `funcion()` en el hilo del servidor y devuelve su resultado."""
        async def _envoltura():
            return funcion()
        return asyncio.run_coroutine_threadsafe(_envoltura(), self.loop).result(5.0)

    def parar(self):
        if self.loop is not None and self.loop.is_running():
            self.loop.call_soon_threadsafe(self.loop.stop)
        self._hilo.join(10.0)


@pytest.fixture
def gemelo(tmp_path):
    from digital_twin.servidor_web.app import ServidorGemelo

    clave = remoto.generar_clave()

    def fabrica():
        srv = ServidorGemelo(str(tmp_path / "servidor"), clave, log=lambda *_: None)
        srv.almacen.crear_usuario("admin", CLAVE_ADMIN, "admin")
        srv.almacen.crear_usuario("ope", CLAVE_OPE, "operador")
        return srv, srv.aplicacion()

    s = ServidorEnHilo(fabrica).arrancar()
    yield s
    s.parar()


def _puerto_libre():
    """Un puerto de 127.0.0.1 donde no escucha nadie (se abre y se cierra al momento)."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


# ---------------------------------------------------------------------------------- url_https
@pytest.mark.parametrize("entrada, esperada", [
    ("wss://digitaltwinscada.smartsensorslab.com/ws/planta", "https://digitaltwinscada.smartsensorslab.com"),
    ("ws://127.0.0.1:3002/ws/planta", "http://127.0.0.1:3002"),
    ("https://digitaltwinscada.smartsensorslab.com/consola?x=1", "https://digitaltwinscada.smartsensorslab.com"),
    ("http://localhost:3002/", "http://localhost:3002"),
    ("digitaltwinscada.smartsensorslab.com", "https://digitaltwinscada.smartsensorslab.com"),
    ("  digitaltwinscada.smartsensorslab.com/ws/planta  ", "https://digitaltwinscada.smartsensorslab.com"),
    ("WSS://Ejemplo.COM:8443/ws/planta", "https://ejemplo.com:8443"),
    ("ws://[::1]:3002/ws/planta", "http://[::1]:3002"),
])
def test_url_https(entrada, esperada):
    assert url_https(entrada) == esperada


@pytest.mark.parametrize("entrada", ["", "   ", None, "ftp://ejemplo.com", "mqtt+wss://broker.ejemplo.com",
                                     "wss:///ws/planta", "https://ejemplo.com:abc", "dos palabras.com"])
def test_url_https_invalida(entrada):
    with pytest.raises(ValueError):
        url_https(entrada)


# ---------------------------------------------------------------------------------- endpoint + cliente
def test_admin_obtiene_y_guarda_la_clave(gemelo, tmp_path):
    srv = gemelo.objeto
    r = obtener_clave(gemelo.base.replace("http://", "ws://") + "/ws/planta", "admin", CLAVE_ADMIN, timeout=5)
    assert r["ok"], r
    assert r["clave"] == srv.clave
    assert r["url"] == gemelo.base
    assert r["planta_en_linea"] is False and r["mqtt"] is None

    ruta = guardar_clave(tmp_path / "hmi" / "datos" / "puente.clave", r["clave"])
    assert os.path.isabs(ruta) and os.path.exists(ruta)
    assert remoto.leer_clave(ruta) == srv.clave
    with open(ruta, "rb") as f:
        assert f.read() == (srv.clave + "\n").encode("utf-8")

    filas = gemelo.en_hilo(lambda: srv.almacen.auditoria(20))
    assert any(f["accion"] == "puente-clave" and f["usuario"] == "admin" and f["detalle"] == "entregada"
               and f["ok"] for f in filas)


def test_respuesta_no_se_cachea(gemelo):
    async def pedir():
        async with aiohttp.ClientSession() as s:
            async with s.post(gemelo.base + "/api/puente/clave",
                              json={"usuario": "admin", "clave": CLAVE_ADMIN}) as r:
                return r.status, r.headers.get("Cache-Control"), await r.json()

    status, cache, datos = asyncio.run(pedir())
    assert status == 200 and cache == "no-store"
    assert datos["ws_planta"] == "/ws/planta" and datos["via"] is None


def test_contrasena_mala(gemelo):
    srv = gemelo.objeto
    r = obtener_clave(gemelo.base, "admin", "no-es-la-clave", timeout=5)
    assert r == {"ok": False, "msg": "usuario o contraseña incorrectos", "status": 401}
    r = obtener_clave(gemelo.base, "nadie", "no-es-la-clave", timeout=5)
    assert not r["ok"] and r["status"] == 401
    filas = gemelo.en_hilo(lambda: srv.almacen.auditoria(20))
    assert any(f["accion"] == "puente-clave" and not f["ok"] and f["msg"] == "credenciales inválidas" for f in filas)


def test_operador_no_puede(gemelo):
    r = obtener_clave(gemelo.base, "ope", CLAVE_OPE, timeout=5)
    assert not r["ok"] and r["status"] == 403
    assert "admin" in r["msg"]
    assert "clave" not in r


def test_demasiados_intentos(gemelo):
    from digital_twin.servidor_web.app import LOGIN_MAX_FALLOS

    srv = gemelo.objeto
    # Se simulan los fallos previos (cada uno costaría un PBKDF2 real) y se comprueba el 429.
    gemelo.en_hilo(lambda: srv._fallos_login.setdefault("127.0.0.1", deque()).extend([time.time()] * LOGIN_MAX_FALLOS))
    r = obtener_clave(gemelo.base, "admin", CLAVE_ADMIN, timeout=5)
    assert not r["ok"] and r["status"] == 429 and "espera" in r["msg"]


def test_origen_ajeno_rechazado(gemelo):
    async def pedir():
        async with aiohttp.ClientSession() as s:
            async with s.post(gemelo.base + "/api/puente/clave", headers={"Origin": "https://malo.example"},
                              json={"usuario": "admin", "clave": CLAVE_ADMIN}) as r:
                return r.status, await r.json()

    status, datos = asyncio.run(pedir())
    assert status == 403 and datos["ok"] is False and "clave" not in datos


def test_sin_servidor_mensaje_de_conexion():
    puerto = _puerto_libre()
    r = obtener_clave("ws://127.0.0.1:%d/ws/planta" % puerto, "admin", CLAVE_ADMIN, timeout=3)
    assert not r["ok"] and r["status"] is None
    assert r["msg"].startswith("no se pudo conectar con http://127.0.0.1:%d" % puerto), r["msg"]


def test_servidor_viejo_sin_endpoint():
    async def salud(_request):
        return web.json_response({"ok": True})

    def fabrica():
        app = web.Application()
        app.router.add_get("/api/salud", salud)
        return None, app

    s = ServidorEnHilo(fabrica).arrancar()
    try:
        r = obtener_clave(s.base, "admin", CLAVE_ADMIN, timeout=5)
    finally:
        s.parar()
    assert not r["ok"] and r["status"] == 404
    assert "actualízalo" in r["msg"] and "/api/puente/clave" in r["msg"]


def test_datos_que_faltan_no_llegan_al_servidor():
    assert obtener_clave("", "admin", "x")["msg"].startswith("falta la dirección")
    assert not obtener_clave("wss://ejemplo.com/ws/planta", "", "x")["ok"]
    assert not obtener_clave("wss://ejemplo.com/ws/planta", "admin", "")["ok"]


# ---------------------------------------------------------------------------------- guardar_clave
def test_guardar_clave_rechaza_claves_malas(tmp_path):
    ruta = tmp_path / "puente.clave"
    with pytest.raises(ValueError, match="corta"):
        guardar_clave(ruta, "corta")
    with pytest.raises(ValueError, match="espacios"):
        guardar_clave(ruta, "abcdefgh ijklmnopqrstu")
    with pytest.raises(ValueError):
        guardar_clave(ruta, None)
    assert not ruta.exists()
    # Los espacios alrededor sí se quitan
    guardar_clave(ruta, "  " + "a" * 20 + "\r\n")
    assert remoto.leer_clave(str(ruta)) == "a" * 20


# ---------------------------------------------------------------------------------- CLI
def test_cli_con_contrasena_stdin(gemelo, tmp_path):
    srv = gemelo.objeto
    archivo = tmp_path / "cli" / "puente.clave"
    entorno = dict(os.environ, PYTHONIOENCODING="utf-8")
    proc = subprocess.run(
        [sys.executable, "-m", "puente.vincular", "--url", gemelo.base.replace("http://", "ws://") + "/ws/planta",
         "--usuario", "admin", "--clave-archivo", str(archivo), "--contrasena-stdin", "--timeout", "5"],
        input=CLAVE_ADMIN + "\n", capture_output=True, text=True, encoding="utf-8", cwd=RAIZ, env=entorno,
        timeout=30)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert remoto.leer_clave(str(archivo)) == srv.clave
    assert srv.clave not in proc.stdout            # nunca se imprime la clave completa
    assert vincular._resumen(srv.clave) in proc.stdout

    mala = subprocess.run(
        [sys.executable, "-m", "puente.vincular", "--url", gemelo.base, "--usuario", "admin",
         "--clave-archivo", str(tmp_path / "otra.clave"), "--contrasena-stdin", "--timeout", "5"],
        input="equivocada\n", capture_output=True, text=True, encoding="utf-8", cwd=RAIZ, env=entorno, timeout=30)
    assert mala.returncode == 1
    assert "usuario o contraseña incorrectos" in mala.stdout
    assert not (tmp_path / "otra.clave").exists()
