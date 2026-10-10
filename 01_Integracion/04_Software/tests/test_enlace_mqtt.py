# -*- coding: utf-8 -*-
"""Transporte MQTT del enlace puente ⇄ servidor del gemelo (core/enlace_mqtt.py), sin broker externo:

    gateway SIM (hilo) ⇄ ZeroMQ ⇄ puente (--mqtt) ⇄ broker mínimo (tests/broker_mqtt_minimo.py) ⇄ servidor web ⇄ navegador

Comprueba: URLs y topics; el sobre sellado (firma válida, ajena, mal formada); que el servidor pone la
planta en línea al recibir snapshots por el broker (via "mqtt"), que las órdenes firmadas van y vuelven
por MQTT (pedir mando, START → ACTIVE), que `lat_web_ms` se mide a través del broker, que un publicador
con la clave equivocada se ignora, que la despedida limpia del puente pone la planta fuera de línea y que
un puente por WebSocket tiene preferencia sobre el de MQTT.
"""
import asyncio
import json
import sys
import threading
import time

import pytest
import zmq

aiohttp = pytest.importorskip("aiohttp")
pytest.importorskip("paho.mqtt")

from core import enlace_mqtt, remoto  # noqa: E402
from gateway.backend_sim import BackendSim  # noqa: E402
from gateway.servidor import Servidor  # noqa: E402


# ---------------------------------------------------------------------------- unidades sin red
def test_urls_y_topics():
    c = enlace_mqtt.analizar_url("mqtts://puente:se%40creto@broker.smartsensorslab.com")
    assert c["host"] == "broker.smartsensorslab.com" and c["puerto"] == 8883 and c["tls"]
    assert c["transporte"] == "tcp" and c["usuario"] == "puente" and c["clave"] == "se@creto"
    c = enlace_mqtt.analizar_url("mqtt+wss://u:p@broker.smartsensorslab.com/mqtt?ca=mi.pem")
    assert c["puerto"] == 443 and c["transporte"] == "websockets" and c["ruta"] == "/mqtt" and c["ca"] == "mi.pem"
    c = enlace_mqtt.analizar_url("mqtt://127.0.0.1:1884")
    assert c["puerto"] == 1884 and not c["tls"] and c["usuario"] is None
    assert enlace_mqtt.analizar_url("mqtt+ws://h")["ruta"] == "/mqtt"
    assert enlace_mqtt.analizar_url("mqtts://h?inseguro=1")["inseguro"]
    with pytest.raises(ValueError):
        enlace_mqtt.analizar_url("wss://servidor/ws/planta")
    assert enlace_mqtt.es_url_mqtt("mqtt+wss://x") and not enlace_mqtt.es_url_mqtt("ws://x")
    assert enlace_mqtt.ocultar_clave("mqtts://u:secreto@h:8883") == "mqtts://u:***@h:8883"

    t = enlace_mqtt.Topics("scada", "Estación Electroneumática")
    assert t.base == "scada/estacion-electroneumatica"
    assert t.snap == "scada/estacion-electroneumatica/snap" and t.orden.endswith("/orden")
    assert t.nombre(t.estado) == "estado" and t.nombre("otra/cosa") is None
    assert t.de_tipo("hola") == t.estado and t.de_tipo("snap") == t.snap and t.de_tipo("bienvenida") is None
    assert [n for n, _ in t.del_puente()] == [t.snap, t.evt, t.estado, t.resultado, t.ping]
    assert enlace_mqtt.Topics(planta="").planta == enlace_mqtt.PLANTA_DEFECTO


def test_sobre_sellado():
    clave = remoto.generar_clave()
    payload = enlace_mqtt.sellar(clave, {"tipo": "snap", "s": {"etapa": 3, "pos": [0.5, 0, 1]}})
    assert payload[64:65] == b"\n"
    ok, obj, motivo = enlace_mqtt.abrir(clave, payload)
    assert ok and obj["s"]["etapa"] == 3 and motivo == ""
    ok, obj, motivo = enlace_mqtt.abrir("otra-clave-otra-clave", payload)
    assert not ok and obj is None and motivo == "firma inválida"
    ok, _, motivo = enlace_mqtt.abrir(clave, payload.replace(b'"etapa":3', b'"etapa":4'))   # cuerpo alterado
    assert not ok and motivo == "firma inválida"
    ok, _, motivo = enlace_mqtt.abrir(clave, b"hola")
    assert not ok and motivo == "sobre mal formado"
    ok, _, motivo = enlace_mqtt.abrir(clave, enlace_mqtt.sellar(clave, {"sin": "tipo"}))
    assert not ok and motivo == "mensaje sin tipo"


# ---------------------------------------------------------------------------- extremo a extremo
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


async def _esperar(cond, timeout=10.0, que="condición"):
    limite = time.monotonic() + timeout
    while time.monotonic() < limite:
        if cond():
            return True
        await asyncio.sleep(0.02)
    raise AssertionError("no se alcanzó: %s" % que)


class Navegador:
    def __init__(self, base):
        self.base = base
        self.sesion = aiohttp.ClientSession(cookie_jar=aiohttp.CookieJar(unsafe=True))
        self.ws = None
        self.msgs = []
        self.snap = None
        self._ref = 0
        self._tarea = None

    async def entrar(self, usuario, clave):
        r = await self.sesion.post(self.base + "/api/login", json={"usuario": usuario, "clave": clave})
        assert r.status == 200, await r.text()
        self.ws = await self.sesion.ws_connect(self.base.replace("http", "ws") + "/ws/web")
        self._tarea = asyncio.ensure_future(self._leer())

    async def _leer(self):
        async for m in self.ws:
            d = json.loads(m.data)
            if d["tipo"] == "snap":
                self.snap = d["s"]
            else:
                self.msgs.append(d)

    async def orden(self, **cmd):
        self._ref += 1
        ref = self._ref
        await self.ws.send_str(json.dumps({"tipo": "orden", "ref": ref, "cmd": cmd}))
        await _esperar(lambda: any(m["tipo"] == "resultado" and m["ref"] == ref for m in self.msgs), 8, "resultado")
        return [m for m in self.msgs if m["tipo"] == "resultado" and m["ref"] == ref][0]

    async def cerrar(self):
        if self.ws is not None:
            await self.ws.close()
        if self._tarea:
            self._tarea.cancel()
        await self.sesion.close()


async def _escenario(gw, tmp_path):
    import zmq.asyncio
    from digital_twin.servidor_web.app import ServidorGemelo
    from puente.enlace import Puente
    from tests.broker_mqtt_minimo import BrokerMinimo

    broker = BrokerMinimo(usuarios={"puente": "clave-puente", "gemelo": "clave-gemelo"})
    puerto_broker = await broker.arrancar()
    clave = remoto.generar_clave()
    srv = ServidorGemelo(str(tmp_path), clave, mqtt="mqtt://gemelo:clave-gemelo@127.0.0.1:%d" % puerto_broker,
                         planta="Estación de prueba", log=lambda *_: None)
    srv.almacen.crear_usuario("oscar", "clave-oscar", "operador")
    runner = aiohttp.web.AppRunner(srv.aplicacion())
    await runner.setup()
    sitio = aiohttp.web.TCPSite(runner, "127.0.0.1", 0)
    await sitio.start()
    puerto_web = sitio._server.sockets[0].getsockname()[1]
    base = "http://127.0.0.1:%d" % puerto_web
    ctx = zmq.asyncio.Context()
    registro = []
    puente = Puente(None, clave, pub=gw.pub_endpoint, cmd=gw.cmd_endpoint, hz=20, planta="Estación de prueba",
                    log=registro.append, contexto=ctx,
                    mqtt="mqtt://puente:clave-puente@127.0.0.1:%d" % puerto_broker)
    assert puente.transporte == "mqtt" and puente.topics.base == "scada/estacion-de-prueba"
    tarea_puente = asyncio.ensure_future(puente.correr())
    nav = Navegador(base)
    try:
        # 1) La planta se pone en línea por el broker y el navegador recibe snapshots vivos
        await _esperar(lambda: srv.planta is not None and srv.planta.via == "mqtt", 10, "planta por MQTT")
        assert srv.planta_info["via"] == "mqtt" and srv.planta_info["planta"] == "Estación de prueba"
        assert broker.retenidos.get(puente.topics.estado) is not None       # `hola` retenido con last will
        await nav.entrar("oscar", "clave-oscar")
        await _esperar(lambda: nav.snap is not None and nav.snap["modo"] == "SIM", 10, "snapshot en el navegador")
        bienvenida = [m for m in nav.msgs if m["tipo"] == "bienvenida"][0]
        assert bienvenida["planta_en_linea"] and bienvenida["planta"]["via"] == "mqtt"
        # 2) La latencia del tramo puente ⇄ servidor se mide a través del broker
        await _esperar(lambda: isinstance((nav.snap or {}).get("lat_web_ms"), (int, float)), 10, "lat_web_ms")
        assert 0 <= nav.snap["lat_web_ms"] < 2000
        # 3) La presencia llega al gateway por el puente (enlace web vivo) y las órdenes van y vuelven por MQTT
        await _esperar(lambda: (nav.snap or {}).get("mando", {}).get("enlace_web"), 15, "enlace_web en el gateway")
        r = await nav.orden(op="mando", accion="pedir")
        assert r["ok"], r
        r = await nav.orden(op="pulso", tag="STARTV")
        assert r["ok"], r
        await _esperar(lambda: (nav.snap or {}).get("bits", {}).get("ACTIVE"), 10, "ACTIVE tras START")
        assert puente.ordenes["aceptadas"] >= 2
        act = [m for m in nav.msgs if m["tipo"] == "actividad" and m["detalle"] == "pulso STARTV"]
        assert act and act[0]["ok"] and act[0]["usuario"] == "oscar"
        filas = srv.almacen.auditoria(50)
        assert any(f["accion"] == "puente" and "conectado (mqtt)" in (f["detalle"] or "") for f in filas)
        # 4) Un intruso con acceso al broker pero sin la clave del enlace no cambia nada
        import paho.mqtt.client as mqtt
        intruso = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="intruso")
        intruso.username_pw_set("puente", "clave-puente")
        intruso.connect("127.0.0.1", puerto_broker, 10)
        intruso.loop_start()
        falso = {"tipo": "snap", "s": {"modo": "REAL", "etapa": 8, "bits": {}, "t": time.time() + 100}}
        rechazados_antes = srv.mqtt.rechazados
        info = intruso.publish(puente.topics.snap, enlace_mqtt.sellar("clave-falsa-clave-falsa", falso), qos=1)
        info.wait_for_publish(3)
        intruso.publish(puente.topics.snap, b"basura sin sobre", qos=1).wait_for_publish(3)
        await _esperar(lambda: srv.mqtt.rechazados >= rechazados_antes + 2, 5, "sobres rechazados")
        await asyncio.sleep(0.3)
        assert srv.snapshot["modo"] == "SIM" and srv.snapshot["etapa"] != 8
        intruso.loop_stop()
        intruso.disconnect()
        # 5) Un puente por WebSocket tiene preferencia: reemplaza al de MQTT mientras viva
        puente_ws = Puente(base.replace("http", "ws") + "/ws/planta", clave, pub=gw.pub_endpoint,
                           cmd=gw.cmd_endpoint, hz=20, log=lambda *_: None, contexto=ctx)
        tarea_ws = asyncio.ensure_future(puente_ws.correr())
        await _esperar(lambda: srv.planta is not None and srv.planta.via == "ws", 10, "planta por WS")
        plantas = [m for m in nav.msgs if m["tipo"] == "planta"]
        assert plantas[-1]["en_linea"] and plantas[-1]["planta"]["via"] == "ws"
        puente_ws.detener()
        await asyncio.wait_for(tarea_ws, 5)
        # al caer el WS, el puente MQTT sigue publicando y vuelve a ser la planta
        await _esperar(lambda: srv.planta is not None and srv.planta.via == "mqtt", 10, "vuelta a MQTT")
        # 6) Despedida limpia del puente: estado retenido fuera de línea y planta fuera de línea en la web
        puente.detener()
        await asyncio.wait_for(tarea_puente, 10)
        await _esperar(lambda: srv.planta is None, 10, "planta fuera de línea")
        ok, estado, _ = enlace_mqtt.abrir(clave, broker.retenidos[puente.topics.estado])
        assert ok and estado["en_linea"] is False
        await _esperar(lambda: any(m["tipo"] == "planta" and not m["en_linea"] for m in nav.msgs), 5, "aviso al navegador")
        r = await nav.orden(op="pulso", tag="STOPV")
        assert not r["ok"] and "no está en línea" in r["msg"]
    finally:
        await nav.cerrar()
        if not tarea_puente.done():
            puente.detener()
            await asyncio.wait_for(tarea_puente, 10)
        await runner.cleanup()
        ctx.term()
        await broker.parar()


def test_enlace_mqtt_completo(gateway, tmp_path):
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    import zmq.asyncio  # noqa: F401
    asyncio.run(_escenario(gateway, tmp_path))
