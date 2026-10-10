# -*- coding: utf-8 -*-
"""Prueba del frontend 3D del gemelo (digital_twin/index.html) con un navegador real.

    gateway SIM (hilo) ⇄ ZeroMQ ⇄ puente ⇄ WebSocket ⇄ servidor web ⇄ Chromium sin ventana (Playwright)

Comprueba lo que ve y hace una persona en la web: inicio de sesión, planta en línea, GRAFCET en X0,
pedir el mando, START (la etapa avanza y el vástago de 1A se mueve), STOP, escritura de un parámetro
por un admin (relectura en pantalla), un rol `usuario` con los mandos deshabilitados, la actividad
compartida y que la página no lanza excepciones de JavaScript. Deja una captura en datos/capturas/.

Una segunda prueba abre la página como un TELÉFONO (390×844, táctil): el tablero de mando va por pestañas
(una tarjeta a la vez), la tira inferior se compacta, no hay desplazamiento horizontal, STOP sigue disponible
y la escena 3D carga; deja la captura `gemelo_3d_movil.png`.

Requiere `pip install playwright` y `python -m playwright install chromium-headless-shell`; si no
están, la prueba se omite. El servidor y el puente corren en un hilo con su propio bucle asyncio
(selector, como exige zmq.asyncio en Windows); Playwright usa el hilo principal.
"""
import asyncio
import os
import sys
import threading
import time

import pytest
import zmq

aiohttp = pytest.importorskip("aiohttp")
sync_api = pytest.importorskip("playwright.sync_api")

from core import remoto  # noqa: E402
from gateway.backend_sim import BackendSim  # noqa: E402
from gateway.servidor import Servidor  # noqa: E402

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CAPTURAS = os.path.join(RAIZ, "datos", "capturas")


@pytest.fixture
def gateway():
    ctx = zmq.Context()
    srv = Servidor(BackendSim(), pub="tcp://127.0.0.1:*", cmd="tcp://127.0.0.1:*",
                   periodo_ms=20, contexto=ctx, remoto_habilitado=True)
    hilo = threading.Thread(target=srv.bucle, daemon=True)
    hilo.start()
    assert srv.listo.wait(5.0)
    yield srv
    srv.detener()
    hilo.join(5.0)
    ctx.term()


class ServicioWeb:
    """Servidor del gemelo + puente en un hilo aparte con bucle selector."""

    def __init__(self, gw, datos):
        self.gw = gw
        self.datos = datos
        self.base = None
        self.error = None
        self._listo = threading.Event()
        self._parar = None
        self._hilo = None
        self.srv = None

    async def _correr(self):
        import zmq.asyncio
        from digital_twin.servidor_web.app import ServidorGemelo
        from puente.enlace import Puente

        clave = remoto.generar_clave()
        self.srv = ServidorGemelo(str(self.datos), clave)
        for u, rol in (("dana", "admin"), ("oscar", "operador"), ("ana", "usuario")):
            self.srv.almacen.crear_usuario(u, "clave-" + u, rol)
        runner = aiohttp.web.AppRunner(self.srv.aplicacion())
        await runner.setup()
        sitio = aiohttp.web.TCPSite(runner, "127.0.0.1", 0)
        await sitio.start()
        puerto = sitio._server.sockets[0].getsockname()[1]
        self.base = "http://127.0.0.1:%d" % puerto
        ctx = zmq.asyncio.Context()
        puente = Puente(self.base.replace("http", "ws") + "/ws/planta", clave, pub=self.gw.pub_endpoint,
                        cmd=self.gw.cmd_endpoint, hz=20, log=lambda *_: None, contexto=ctx)
        tarea = asyncio.ensure_future(puente.correr())
        self._parar = asyncio.Event()
        try:
            for _ in range(200):
                if self.srv.planta is not None and self.srv.snapshot is not None:
                    break
                await asyncio.sleep(0.05)
            self._listo.set()
            await self._parar.wait()
        finally:
            puente.detener()
            await asyncio.wait_for(tarea, 5)
            ctx.term()
            await runner.cleanup()

    def _hilo_main(self):
        loop = asyncio.SelectorEventLoop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self._correr())
        except Exception as e:  # pragma: no cover - se informa en la prueba
            self.error = e
            self._listo.set()
        finally:
            loop.close()

    def arrancar(self):
        self._hilo = threading.Thread(target=self._hilo_main, daemon=True)
        self._hilo.start()
        assert self._listo.wait(15.0), "el servidor web no arrancó"
        assert self.error is None, self.error
        assert self.srv.planta is not None, "el puente no se conectó al servidor"

    def parar(self):
        if self._parar is not None and self._parar._loop is not None:
            self._parar._loop.call_soon_threadsafe(self._parar.set)   # el Event vive en el otro bucle
        self._hilo.join(10.0)


def _entrar(navegador, base, usuario, clave, errores_js, consola=None, movil=False):
    """Una persona = un contexto de navegador (cookies propias) con una página ya autenticada.
    Con movil=True el contexto imita un teléfono en vertical (pantalla angosta, táctil, 2x)."""
    if movil:
        contexto = navegador.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=2,
                                         is_mobile=True, has_touch=True)
    else:
        contexto = navegador.new_context(viewport={"width": 1600, "height": 900})
    page = contexto.new_page()
    page.on("pageerror", lambda e: errores_js.append("%s: %s" % (usuario, e)))
    if consola is not None:
        page.on("console", lambda m: consola.append("%s: %s" % (m.type, m.text)))
    page.goto(base + "/")
    page.wait_for_selector("#login:not([hidden])", timeout=10000)
    page.fill("#lu", usuario)
    page.fill("#lc", clave)
    page.click("#lb")
    page.wait_for_selector("#login[hidden]", state="attached", timeout=10000)
    page.wait_for_function("document.getElementById('txtYo').textContent.indexOf(%r) === 0" % usuario, timeout=10000)
    page.wait_for_function("document.getElementById('txtPlanta').textContent.indexOf('Planta en línea') === 0", timeout=10000)
    return page


def test_frontend_3d_con_navegador(gateway, tmp_path):
    # Playwright lanza Chromium como subproceso asyncio: en Windows eso exige el bucle proactor. Otras
    # pruebas (test_enlace_web) dejan fijada la política selector; aquí se fija la proactor mientras dura
    # la prueba (el hilo del servidor crea su propio SelectorEventLoop y no depende de la política).
    politica_previa = asyncio.get_event_loop_policy()
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    servicio = ServicioWeb(gateway, tmp_path)
    servicio.arrancar()
    errores_js = []
    consola = []
    try:
        with sync_api.sync_playwright() as p:
            try:
                navegador = p.chromium.launch()
            except sync_api.Error as e:  # navegador no instalado
                pytest.skip("Chromium de Playwright no disponible: %s" % e)
            oscar = _entrar(navegador, servicio.base, "oscar", "clave-oscar", errores_js, consola)

            # La escena 3D cargó (three.js local) y el GRAFCET está en X0 con el mando libre
            assert oscar.evaluate("!!window.THREE")
            oscar.wait_for_selector("[data-etapa='0'].on", timeout=10000)
            assert oscar.is_disabled("#btnStart")          # sin mando todavía
            assert not oscar.is_disabled("#btnStop")       # STOP nunca necesita el mando
            assert not oscar.is_disabled("#btnPedir")
            oscar.click("#btnPedir")
            oscar.wait_for_function("document.getElementById('mandoEstado').textContent.indexOf('eres tú') >= 0", timeout=10000)
            oscar.wait_for_function("!document.getElementById('btnStart').disabled", timeout=5000)
            assert oscar.is_disabled("#wTneum")            # operador: sin parámetros

            # START: la secuencia arranca, la etapa avanza y el vástago de 1A se mueve en la barra
            oscar.click("#btnStart")
            oscar.wait_for_function("document.getElementById('grafcetSub').textContent === 'en marcha'", timeout=10000)
            oscar.wait_for_function("!document.querySelector(\"[data-etapa='0']\").classList.contains('on')", timeout=10000)
            oscar.wait_for_function("parseFloat(document.querySelector(\"[data-fill='1A']\").style.width) > 20", timeout=10000)
            oscar.wait_for_function("document.getElementById('mandoRes').textContent.indexOf('Pulso STARTV: aceptada') >= 0", timeout=5000)
            time.sleep(0.6)
            os.makedirs(CAPTURAS, exist_ok=True)
            oscar.screenshot(path=os.path.join(CAPTURAS, "gemelo_3d_marcha.png"))

            # Un rol `usuario` solo ve, pero recibe la actividad de los demás
            ana = _entrar(navegador, servicio.base, "ana", "clave-ana", errores_js)
            assert ana.is_disabled("#btnStart") and ana.is_disabled("#btnStop") and ana.is_disabled("#btnPedir")
            assert ana.is_hidden("#btnCuentas")
            ana.wait_for_function("document.getElementById('conectados').textContent.indexOf('oscar') >= 0", timeout=10000)
            # Al entrar recibe los últimos eventos de la planta (bienvenida), entre ellos el pulso de oscar
            ana.wait_for_function("document.getElementById('eventos').textContent.indexOf('Pulso STARTV') >= 0", timeout=5000)

            # STOP desde oscar: la secuencia se detiene y ana ve la actividad en vivo (quién, qué, resultado)
            oscar.click("#btnStop")
            oscar.wait_for_function("document.getElementById('grafcetSub').textContent === 'detenida'", timeout=10000)
            ana.wait_for_function("(function(t){ return t.indexOf('oscar') >= 0 && t.indexOf('pulso STOPV') >= 0 && t.indexOf('aceptada') >= 0; })"
                                  "(document.getElementById('actividad').textContent)", timeout=10000)

            # Un admin toma el mando por jerarquía y escribe T_NEUM = 3,00 s; la pantalla relee 300 centésimas
            dana = _entrar(navegador, servicio.base, "dana", "clave-dana", errores_js)
            assert dana.is_visible("#btnCuentas")
            dana.click("#btnPedir")
            dana.wait_for_function("document.getElementById('mandoEstado').textContent.indexOf('eres tú') >= 0", timeout=10000)
            dana.wait_for_function("!document.getElementById('wTneum').disabled", timeout=5000)
            dana.fill("#pTneum", "3")
            dana.click("#wTneum")
            dana.wait_for_function("document.getElementById('vTneum').textContent.indexOf('3.00 s') >= 0", timeout=10000)
            dana.click("#btnCuentas")
            dana.wait_for_function("document.getElementById('tusuarios').textContent.indexOf('oscar') >= 0", timeout=10000)
            dana.wait_for_function("document.getElementById('auditoriaLog').textContent.indexOf('T_NEUM = 300') >= 0", timeout=10000)
            # oscar perdió el mando: su START vuelve a estar deshabilitado
            oscar.wait_for_function("document.getElementById('btnStart').disabled", timeout=10000)
            assert "dana" in oscar.evaluate("document.getElementById('mandoEstado').textContent")
            dana.screenshot(path=os.path.join(CAPTURAS, "gemelo_3d_admin.png"))
            navegador.close()
    finally:
        servicio.parar()
        asyncio.set_event_loop_policy(politica_previa)
    assert not errores_js, "errores de JavaScript en la página: %s\nconsola: %s" % (errores_js, consola[-20:])
    # Se toleran recursos que no existen en todos los servidores (favicon, /api/institucion en versiones
    # viejas, el 401 de /api/yo antes de iniciar sesión) y los avisos de WebGL del navegador sin GPU.
    graves = [c for c in consola if c.startswith("error:") and "Failed to load resource" not in c
              and "WebGL" not in c and "GPU" not in c]
    assert not graves, "errores en la consola del navegador: %s" % graves


def test_frontend_3d_en_movil(gateway, tmp_path):
    """La misma página vista desde un teléfono: pestañas, tira compacta, sin desplazamiento horizontal."""
    politica_previa = asyncio.get_event_loop_policy()
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    servicio = ServicioWeb(gateway, tmp_path)
    servicio.arrancar()
    errores_js = []
    consola = []
    try:
        with sync_api.sync_playwright() as p:
            try:
                navegador = p.chromium.launch()
            except sync_api.Error as e:  # navegador no instalado
                pytest.skip("Chromium de Playwright no disponible: %s" % e)
            oscar = _entrar(navegador, servicio.base, "oscar", "clave-oscar", errores_js, consola, movil=True)
            assert oscar.evaluate("!!window.THREE")
            # Sin desplazamiento horizontal de la página y con el transporte en la píldora de la planta
            assert oscar.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
            oscar.wait_for_function("document.getElementById('txtPlanta').textContent.indexOf('WS') >= 0", timeout=5000)
            # Pestañas visibles: solo la tarjeta de mando se ve; GRAFCET aparece al tocar su pestaña
            assert oscar.is_visible("#tabs")
            assert oscar.is_visible("#cardMando") and oscar.is_hidden("#cardGrafcet")
            assert not oscar.is_disabled("#btnStop")       # STOP nunca necesita el mando
            oscar.click("#tabs [data-tab='cardGrafcet']")
            oscar.wait_for_selector("#cardGrafcet.activa", timeout=3000)
            assert oscar.is_visible("#cardGrafcet") and oscar.is_hidden("#cardMando")
            oscar.wait_for_selector("[data-etapa='0'].on", timeout=10000)
            # La tira inferior cabe en el ancho del teléfono y esconde los nombres de los sensores
            assert oscar.evaluate("document.getElementById('strip').getBoundingClientRect().right <= window.innerWidth + 1")
            assert oscar.is_hidden("[data-fill='1A'] ~ .ends, .bar .ends")
            # El tablero (pestañas + tarjeta) y la tira no se solapan
            assert oscar.evaluate("document.getElementById('dock').getBoundingClientRect().bottom <= "
                                  "document.getElementById('strip').getBoundingClientRect().top + 1")
            # Volver a Mando, pedir el mando y arrancar desde el teléfono
            oscar.click("#tabs [data-tab='cardMando']")
            oscar.wait_for_selector("#cardMando.activa", timeout=3000)
            oscar.click("#btnPedir")
            oscar.wait_for_function("!document.getElementById('btnStart').disabled", timeout=10000)
            oscar.click("#btnStart")
            oscar.wait_for_function("document.getElementById('grafcetSub').textContent === 'en marcha'", timeout=10000)
            time.sleep(0.8)
            os.makedirs(CAPTURAS, exist_ok=True)
            oscar.screenshot(path=os.path.join(CAPTURAS, "gemelo_3d_movil.png"))
            # Modo "solo 3D": el botón Panel esconde tablero y tira
            oscar.click("#btnPanel")
            assert oscar.is_hidden("#dock") and oscar.is_hidden("#strip")
            oscar.click("#btnPanel")
            assert oscar.is_visible("#dock")
            oscar.click("#btnStop")
            oscar.wait_for_function("document.getElementById('grafcetSub').textContent === 'detenida'", timeout=10000)
            navegador.close()
    finally:
        servicio.parar()
        asyncio.set_event_loop_policy(politica_previa)
    assert not errores_js, "errores de JavaScript en la página: %s\nconsola: %s" % (errores_js, consola[-20:])
    graves = [c for c in consola if c.startswith("error:") and "Failed to load resource" not in c
              and "WebGL" not in c and "GPU" not in c]
    assert not graves, "errores en la consola del navegador: %s" % graves
