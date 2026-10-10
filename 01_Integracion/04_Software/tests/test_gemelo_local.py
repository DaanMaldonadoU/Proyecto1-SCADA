# -*- coding: utf-8 -*-
"""Gemelo digital en local (digital_twin/local.py): servidor + puente en un proceso contra un gateway SIM.

Comprueba lo que la sesión 04 dejó sin prueba: el `pong` con eco de `t` (navegador y puente), la
latencia del tramo puente ⇄ servidor publicada como `lat_web_ms`, las cuentas de prueba, el frontend 3D
servido en `/` con three.js local y `/api/institucion`.
"""
import asyncio
import json
import sys
import threading
import time

import pytest
import zmq

aiohttp = pytest.importorskip("aiohttp")

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


async def _escenario(gw, tmp_path):
    import zmq.asyncio
    from digital_twin.local import GemeloLocal, CUENTAS_PRUEBA

    ctx = zmq.asyncio.Context()
    try:
        gemelo = GemeloLocal(datos=str(tmp_path), host="127.0.0.1", puerto=0, pub=gw.pub_endpoint,
                             cmd=gw.cmd_endpoint, log=lambda *_: None)
        # el puente del gemelo usa el contexto global; se le da uno propio para poder cerrarlo
        url = await gemelo.arrancar()
        gemelo.puente.ctx = ctx
        try:
            assert (tmp_path / "puente.clave").exists()
            assert sorted(u["usuario"] for u in gemelo.servidor.almacen.listar()) == sorted(c[0] for c in CUENTAS_PRUEBA)

            async with aiohttp.ClientSession(cookie_jar=aiohttp.CookieJar(unsafe=True)) as s:
                # Frontend 3D, three.js local e institución sin sesión
                r = await s.get(url + "/")
                assert r.status == 200 and "gemelo" in (await r.text()).lower()
                r = await s.get(url + "/estatico/three.min.js")
                assert r.status == 200 and "three" in (await r.text(errors="ignore"))[:2000].lower()
                r = await s.get(url + "/api/institucion")
                j = await r.json()
                assert j["ok"] and "electroneum" in j["institucion"]["proyecto"].lower()
                r = await s.get(url + "/api/yo")
                assert r.status == 401

                # Cuenta de prueba y WebSocket
                r = await s.post(url + "/api/login", json={"usuario": "operador", "clave": "operador1234"})
                assert r.status == 200, await r.text()
                ws = await s.ws_connect(url.replace("http", "ws") + "/ws/web")
                bienvenida = json.loads((await ws.receive()).data)
                assert bienvenida["tipo"] == "bienvenida" and bienvenida["yo"]["rol"] == "operador"

                await ws.send_str(json.dumps({"tipo": "ping", "t": 123.5}))
                snap, pong, resultado = None, None, None
                limite = time.monotonic() + 10.0
                ref = 1
                pedido = False
                while time.monotonic() < limite:
                    m = await asyncio.wait_for(ws.receive(), 5.0)
                    d = json.loads(m.data)
                    if d["tipo"] == "pong":
                        pong = d
                    elif d["tipo"] == "snap":
                        snap = d["s"]
                        if not pedido and snap.get("mando", {}).get("enlace_web"):
                            await ws.send_str(json.dumps({"tipo": "orden", "ref": ref,
                                                          "cmd": {"op": "mando", "accion": "pedir"}}))
                            pedido = True
                    elif d["tipo"] == "resultado" and d.get("ref") == ref:
                        resultado = d
                    if pong and resultado and snap and isinstance(snap.get("lat_web_ms"), (int, float)):
                        break
                assert pong and pong["t"] == 123.5 and pong["t_srv"] > 0
                assert snap is not None and snap["modo"] == "SIM"
                assert isinstance(snap.get("lat_web_ms"), (int, float)) and 0 <= snap["lat_web_ms"] < 1000
                assert resultado and resultado["ok"], resultado
                await ws.close()
        finally:
            await gemelo.parar()
    finally:
        ctx.term()


def test_gemelo_local(gateway, tmp_path):
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(_escenario(gateway, tmp_path))
