# -*- coding: utf-8 -*-
"""Prueba de extremo a extremo del enlace web, sin Internet ni Cloudflare:

    gateway SIM (hilo) ⇄ ZeroMQ ⇄ puente (asyncio) ⇄ WebSocket ⇄ servidor web (aiohttp) ⇄ navegadores simulados

Comprueba roles, mando exclusivo, preferencia por jerarquía, STOP siempre permitido,
difusión de actividad, auditoría, presencia en el snapshot y rechazo de un puente con clave falsa.
"""
import asyncio
import json
import sys
import threading
import time

import pytest
import zmq

aiohttp = pytest.importorskip("aiohttp")

from core import remoto  # noqa: E402
from gateway.backend_sim import BackendSim  # noqa: E402
from gateway.servidor import Servidor  # noqa: E402


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


class Navegador:
    """Una persona en la web: sesión HTTP + WebSocket /ws/web."""

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
        return await self.esperar(lambda m: m["tipo"] == "resultado" and m["ref"] == ref)

    async def esperar(self, cond, timeout=5.0):
        limite = time.monotonic() + timeout
        while time.monotonic() < limite:
            for m in self.msgs:
                if cond(m):
                    return m
            await asyncio.sleep(0.02)
        raise AssertionError("mensaje no recibido")

    async def esperar_snap(self, cond, timeout=8.0):
        limite = time.monotonic() + timeout
        while time.monotonic() < limite:
            if self.snap is not None and cond(self.snap):
                return self.snap
            await asyncio.sleep(0.02)
        raise AssertionError("snapshot no alcanzado; último: %s" % (self.snap or {}).get("mando"))

    async def cerrar(self):
        if self.ws is not None:
            await self.ws.close()
        if self._tarea:
            self._tarea.cancel()
        await self.sesion.close()


async def _escenario(gw, tmp_path):
    from digital_twin.servidor_web.app import ServidorGemelo
    from puente.enlace import Puente

    clave = remoto.generar_clave()
    srv = ServidorGemelo(str(tmp_path), clave)
    for u, rol in (("ana", "usuario"), ("oscar", "operador"), ("olga", "operador"), ("ines", "ingeniero")):
        srv.almacen.crear_usuario(u, "clave-" + u, rol)
    runner = aiohttp.web.AppRunner(srv.aplicacion())
    await runner.setup()
    sitio = aiohttp.web.TCPSite(runner, "127.0.0.1", 0)
    await sitio.start()
    puerto = sitio._server.sockets[0].getsockname()[1]
    base = "http://127.0.0.1:%d" % puerto

    # Un puente con clave falsa es rechazado
    async with aiohttp.ClientSession() as s:
        with pytest.raises(aiohttp.WSServerHandshakeError):
            await s.ws_connect(base.replace("http", "ws") + "/ws/planta",
                               headers={"Authorization": "Bearer falsa-falsa-falsa-falsa"})

    ctx = zmq.asyncio.Context()
    puente = Puente(base.replace("http", "ws") + "/ws/planta", clave, pub=gw.pub_endpoint,
                    cmd=gw.cmd_endpoint, hz=20, log=lambda *_: None, contexto=ctx)
    tarea_puente = asyncio.ensure_future(puente.correr())
    navs = {u: Navegador(base) for u in ("ana", "oscar", "olga", "ines")}
    try:
        for u, n in navs.items():
            await n.entrar(u, "clave-" + u)
        ana, oscar, olga, ines = navs["ana"], navs["oscar"], navs["olga"], navs["ines"]

        # El snapshot llega a la web y la presencia llega al gateway (y vuelve en el snapshot)
        s = await ana.esperar_snap(lambda s: s["mando"]["enlace_web"] and len(s["mando"]["conectados"]) == 4)
        assert s["modo"] == "SIM" and s["etapa"] == 0

        # Rol usuario: solo ve
        r = await ana.orden(op="pulso", tag="STARTV")
        assert not r["ok"]
        # Operador sin mando: rechazado por el gateway
        r = await oscar.orden(op="pulso", tag="STARTV")
        assert not r["ok"] and "pide el mando" in r["msg"]
        # Operador con mando: START llega al PLC simulado
        r = await oscar.orden(op="mando", accion="pedir")
        assert r["ok"], r
        r = await olga.orden(op="mando", accion="pedir")
        assert not r["ok"] and "oscar" in r["msg"]          # exclusión entre iguales
        r = await oscar.orden(op="pulso", tag="STARTV")
        assert r["ok"], r
        await oscar.esperar_snap(lambda s: s["bits"].get("ACTIVE"))
        # Operador no escribe parámetros (lo filtra el servidor)
        r = await oscar.orden(op="escribir", tag="T_NEUM", valor=300)
        assert not r["ok"] and "ingeniero" in r["msg"]
        # Ingeniero toma el mando por jerarquía y escribe
        r = await ines.orden(op="mando", accion="pedir")
        assert r["ok"] and "jerarquía" in r["msg"]
        r = await ines.orden(op="escribir", tag="T_NEUM", valor=300)
        assert r["ok"], r
        await ines.esperar_snap(lambda s: s["ints"].get("T5_PRE") == 300)
        r = await oscar.orden(op="pulso", tag="RESETV")
        assert not r["ok"]                                    # ya no tiene el mando
        # STOP siempre pasa para un operador
        r = await olga.orden(op="pulso", tag="STOPV")
        assert r["ok"], r
        await olga.esperar_snap(lambda s: not s["bits"].get("ACTIVE"))
        # Órdenes que la web no puede mandar nunca
        r = await ines.orden(op="entrada", tag="SC1", valor=True)
        assert not r["ok"]

        # Todos ven la actividad con usuario, rol y hora
        act = await ana.esperar(lambda m: m["tipo"] == "actividad" and m["usuario"] == "ines"
                                and m["detalle"] == "T_NEUM = 300")
        assert act["ok"] and act["rol"] == "ingeniero" and act["t"] > 0
        filas = srv.almacen.auditoria(100)
        assert any(f["usuario"] == "olga" and f["detalle"] == "pulso STOPV" and f["ok"] for f in filas)
        assert any(f["usuario"] == "ana" and not f["ok"] for f in filas)

        # El HMI local manda sobre la web: una orden local le quita el mando a ines
        gw_titular = gw.snapshot["mando"]["titular"]
        assert gw_titular["usuario"] == "ines"
    finally:
        for n in navs.values():
            await n.cerrar()
        puente.detener()
        await asyncio.wait_for(tarea_puente, 5)
        ctx.term()
        await runner.cleanup()


def test_enlace_web_completo(gateway, tmp_path):
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    import zmq.asyncio  # noqa: F401
    asyncio.run(_escenario(gateway, tmp_path))
