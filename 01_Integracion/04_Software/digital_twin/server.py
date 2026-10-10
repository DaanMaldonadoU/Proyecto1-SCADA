"""
Puente OPC UA ⇄ Gemelo digital (WebSocket)

    pip install aiohttp asyncua

Uso:
    python server.py                       # http://localhost:8765  (sirve index.html y /ws)
    python server.py --opc opc.tcp://192.168.0.10:4840

Sin --opc arranca en modo demo: recorre la secuencia 1B+ 2B+ 3B+ 1B- 2B- 3B-
para que puedas comprobar el enlace con el gemelo.

Protocolo (JSON):
  servidor → gemelo   {"outputs": {"1B+":1,"1B-":0,"2B+":0,...,"CEV3":0,"EEV3":0,"START":0,"STOP":0,"ESTOP":0,"RESET":0}}
                      {"inputs":  {"E4B":1,"C4B":0,"E5B":0,"C5B":1}}      # sensores físicos (opcional)
                      {"cylinders": {"1B":1}}                              # objetivo directo 0/1 (opcional)
                      {"positions": {"1B":0.42}}                           # posición 0..1 (si tienes encoder)
                      {"pressure": 1, "flow_time": 1.6}
  gemelo → servidor   {"type":"hello", ...}
                      {"type":"sensors","SC1":1,"SE1":0,...}               # solo los que cambian
                      {"type":"button","name":"START","value":1}
"""
import argparse
import asyncio
import json
import pathlib
import time

from aiohttp import web, WSMsgType

HERE = pathlib.Path(__file__).parent

# ------------------------------------------------------------------
# Estado compartido: tu código OPC escribe aquí; el WebSocket lo difunde.
# ------------------------------------------------------------------
OUTPUT_TAGS = ["1B+", "1B-", "2B+", "2B-", "3B+", "3B-",
               "CEV3", "EEV3", "START", "STOP", "ESTOP", "RESET"]
INPUT_TAGS = ["SC1", "SE1", "SC2", "SE2", "SC3N", "SE3N", "C4B", "E4B", "C5B", "E5B"]

state = {
    "outputs": {t: 0 for t in OUTPUT_TAGS},
    "inputs": {},          # sensores físicos leídos del PLC (opcional)
    "pressure": 1,
}
twin_sensors = {}          # último estado de sensores que reporta el gemelo
clients: set[web.WebSocketResponse] = set()
_dirty = asyncio.Event()


def set_output(tag: str, value) -> None:
    """Llama a esto desde tu lectura OPC cada vez que cambie una salida."""
    v = 1 if value else 0
    if state["outputs"].get(tag) != v:
        state["outputs"][tag] = v
        _dirty.set()


def set_input(tag: str, value) -> None:
    v = 1 if value else 0
    if state["inputs"].get(tag) != v:
        state["inputs"][tag] = v
        _dirty.set()


async def broadcaster():
    """Envía el estado a todos los gemelos conectados cuando algo cambia (y un ping cada 5 s)."""
    while True:
        try:
            await asyncio.wait_for(_dirty.wait(), timeout=5.0)
            payload = json.dumps({"outputs": state["outputs"], "inputs": state["inputs"],
                                  "pressure": state["pressure"]})
        except asyncio.TimeoutError:
            payload = json.dumps({"type": "ping", "t": time.time()})
        _dirty.clear()
        dead = []
        for ws in clients:
            try:
                await ws.send_str(payload)
            except Exception:
                dead.append(ws)
        for ws in dead:
            clients.discard(ws)


# ------------------------------------------------------------------
# Lectura OPC UA. Adapta los NodeId a tu proyecto de PLC.
# ------------------------------------------------------------------
# Ejemplo (Siemens S7-1500 / TIA): ns=3;s="Salidas"."1B_mas"
OPC_OUTPUT_NODES = {
    "1B+": 'ns=3;s="Q_1B_mas"', "1B-": 'ns=3;s="Q_1B_menos"',
    "2B+": 'ns=3;s="Q_2B_mas"', "2B-": 'ns=3;s="Q_2B_menos"',
    "3B+": 'ns=3;s="Q_3B_mas"', "3B-": 'ns=3;s="Q_3B_menos"',
}
OPC_INPUT_NODES = {
    # "SC1": 'ns=3;s="I_SC1"', ...
}
OPC_BUTTON_NODES = {           # botones que el gemelo puede escribir en el PLC (opcional)
    # "START": 'ns=3;s="I_Marcha"', "STOP": 'ns=3;s="I_Paro"', "ESTOP": 'ns=3;s="I_Emergencia"',
}


async def opc_loop(url: str, period: float = 0.05):
    from asyncua import Client  # pip install asyncua
    while True:
        try:
            async with Client(url=url) as client:
                print(f"[opc] conectado a {url}")
                out_nodes = {t: client.get_node(n) for t, n in OPC_OUTPUT_NODES.items()}
                in_nodes = {t: client.get_node(n) for t, n in OPC_INPUT_NODES.items()}
                while True:
                    if out_nodes:
                        vals = await client.read_values(list(out_nodes.values()))
                        for tag, v in zip(out_nodes, vals):
                            set_output(tag, v)
                    if in_nodes:
                        vals = await client.read_values(list(in_nodes.values()))
                        for tag, v in zip(in_nodes, vals):
                            set_input(tag, v)
                    await asyncio.sleep(period)
        except Exception as e:  # noqa: BLE001
            print(f"[opc] error: {e!r}; reintento en 3 s")
            await asyncio.sleep(3)


async def write_button_to_plc(name: str, value: int):
    """Escribe pulsadores del gemelo en el PLC si has mapeado OPC_BUTTON_NODES."""
    node_id = OPC_BUTTON_NODES.get(name)
    if not node_id or not app.get("opc_url"):
        return
    try:
        from asyncua import Client
        async with Client(url=app["opc_url"]) as client:
            await client.get_node(node_id).write_value(bool(value))
    except Exception as e:  # noqa: BLE001
        print(f"[opc] no se pudo escribir {name}: {e!r}")


# ------------------------------------------------------------------
# Modo demo (sin PLC): recorre la secuencia del plano.
# ------------------------------------------------------------------
async def demo_loop():
    seq = ["1B+", "2B+", "3B+", "1B-", "2B-", "3B-"]
    await asyncio.sleep(1)
    while True:
        for key in seq:
            set_output(key, 1)
            await asyncio.sleep(0.25)
            set_output(key, 0)
            target = key[:2]
            sensor = {"1B": ("SE1", "SC1"), "2B": ("SE2", "SC2"), "3B": ("SE3N", "SC3N")}[target]
            want = sensor[0] if key.endswith("+") else sensor[1]
            for _ in range(200):               # espera a que el gemelo confirme el sensor
                if twin_sensors.get(want):
                    break
                await asyncio.sleep(0.05)
            await asyncio.sleep(0.4)


# ------------------------------------------------------------------
# Web
# ------------------------------------------------------------------
async def ws_handler(request: web.Request):
    ws = web.WebSocketResponse(heartbeat=20)
    await ws.prepare(request)
    clients.add(ws)
    print(f"[ws] gemelo conectado ({len(clients)} en total)")
    await ws.send_str(json.dumps({"outputs": state["outputs"], "inputs": state["inputs"],
                                  "pressure": state["pressure"]}))
    try:
        async for msg in ws:
            if msg.type != WSMsgType.TEXT:
                continue
            try:
                data = json.loads(msg.data)
            except json.JSONDecodeError:
                continue
            kind = data.get("type")
            if kind == "sensors":
                for k, v in data.items():
                    if k != "type":
                        twin_sensors[k] = v
            elif kind == "button":
                print(f"[ws] botón {data.get('name')} = {data.get('value')}")
                asyncio.create_task(write_button_to_plc(data.get("name"), data.get("value")))
            elif kind == "hello":
                twin_sensors.update(data.get("sensors", {}))
    finally:
        clients.discard(ws)
        print("[ws] gemelo desconectado")
    return ws


async def state_handler(request: web.Request):
    return web.json_response({"state": state, "twin_sensors": twin_sensors, "clients": len(clients)})


async def index(request: web.Request):
    return web.FileResponse(HERE / "index.html")


async def on_startup(app: web.Application):
    app["tasks"] = [asyncio.create_task(broadcaster())]
    if app.get("opc_url"):
        app["tasks"].append(asyncio.create_task(opc_loop(app["opc_url"])))
    else:
        print("[demo] sin --opc: ejecutando secuencia de demostración")
        app["tasks"].append(asyncio.create_task(demo_loop()))


app = web.Application()
app.add_routes([web.get("/", index), web.get("/ws", ws_handler), web.get("/api/state", state_handler)])
app.on_startup.append(on_startup)

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--opc", default=None, help="URL OPC UA, p. ej. opc.tcp://192.168.0.10:4840")
    args = ap.parse_args()
    app["opc_url"] = args.opc
    print(f"Gemelo digital en http://localhost:{args.port}  (WebSocket en /ws)")
    web.run_app(app, host=args.host, port=args.port)
