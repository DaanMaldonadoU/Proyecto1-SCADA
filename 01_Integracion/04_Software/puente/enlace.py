# -*- coding: utf-8 -*-
"""
puente/enlace.py — Puente entre el gateway local (ZeroMQ) y el servidor web del gemelo.

Qué hace:
    * Se suscribe al PUB del gateway como un HMI más y reenvía al servidor el último
      snapshot en cuanto llega (a `hz` por segundo como mucho; 20 por defecto, el ritmo del
      gateway en SIM) y todos los eventos. No espera a un temporizador: el retraso añadido es
      el de serializar y enviar.
    * Mide la ida y vuelta hasta el servidor con un `ping` cada PERIODO_PING_S y la publica en
      cada snapshot como `lat_web_ms`, para que el gemelo muestre el retardo real del enlace.
    * En REAL el gateway no da `pos`: el puente la estima con core.estimador usando la
      calibración que mide el HMI (datos/calibracion.json, solo lectura), para que el gemelo
      mueva los vástagos igual que la pantalla local. Marca `pos_estimada: true`.
    * Modo suave (`suave`: "auto" por defecto = cuando el gateway no da `pos`, es decir en REAL o
      con `--simular-enlace`; "si" siempre; "no" nunca): la misma animación prevista del HMI
      (core.suavizado: bobinas, sensores y GRAFCET, carreras repuestas, sin saltos). El snapshot
      sale con `pos`/`pos_neum` animados y un bloque `suave` {v, obj, etapa, t_etapa, acc, repuestas}
      para que el navegador siga moviendo los vástagos entre snapshots sin esperar al siguiente
      (mds/ENLACE_WEB.md §3.3).
    * Recibe órdenes del servidor, verifica firma, hora e id (core.remoto.Verificador) y las
      pasa al REP del gateway con su identidad `quien`. El gateway decide con su árbitro de
      mando (core.mando) y la respuesta vuelve al servidor como `resultado`.
    * Reenvía al gateway la presencia (quién está en línea en la web) cada PERIODO_PRESENCIA_S
      mientras el enlace con el servidor esté vivo: eso le dice al HMI que la web está ahí.

Dos transportes, mismos mensajes (mds/ENLACE_WEB.md §3 y §7):
    * WebSocket saliente a `wss://…/ws/planta` (por defecto). En el laboratorio no hay que abrir
      puertos: basta con salida HTTPS hacia el dominio del servidor.
    * MQTT (`--mqtt mqtts://usuario:clave@broker…`): el puente publica en
      `<prefijo>/<planta>/{snap,evt,estado,resultado,ping}` y escucha `{orden,presencia,pong}`.
      Cada mensaje va sellado con HMAC de la misma clave (core/enlace_mqtt.py): el broker solo
      transporta, no decide. `estado` es retenido y lleva *last will*, así el servidor sabe si el
      puente desapareció. El enlace se considera vivo mientras el servidor conteste a los `ping`.

    Si se cae la conexión, reintenta con espera creciente (1, 2, 4, 8, 15 s; MQTT lo hace paho).

Modos: SIM, EMULATE y REAL (lo que publique el gateway).
Compatibilidad: Python 3.12 a 3.13 (pensado para el Python de 64 bits del HMI).
Dependencias: aiohttp (WebSocket), paho-mqtt (solo con --mqtt), pyzmq, msgpack.
"""
from __future__ import annotations

import asyncio
import json
import time
from collections import deque

import zmq
import zmq.asyncio

from core import enlace_mqtt, protocolo, remoto

try:
    from core.calibracion import Calibracion
    from core.estimador import EstimadorCarrera
except ImportError:  # pragma: no cover
    Calibracion = EstimadorCarrera = None
try:
    from core.suavizado import Suavizador
    from gateway.fisica import CadenaNeumatica
except ImportError:  # pragma: no cover
    Suavizador = CadenaNeumatica = None

ESPERAS_RECONEXION = (1.0, 2.0, 4.0, 8.0, 15.0)
PERIODO_PRESENCIA_S = 5.0
PERIODO_PING_S = 3.0
ENLACE_MQTT_VIVO_S = 10.0       # sin pong del servidor en este tiempo, el enlace MQTT se da por muerto
# Igual que el HMI (2 s desde la sesión 10): una escritura por DF1 en el laboratorio tardó hasta
# 1,2 s. Debe seguir por debajo de TIMEOUT_RESULTADO_S (3 s) del servidor web.
TIMEOUT_ORDEN_S = protocolo.TIMEOUT_CMD_MS / 1000.0
MAX_EVENTOS_COLA = 300
HZ_DEFECTO = 20.0
MODOS_SUAVE = ("auto", "si", "no")


class _CanalWs:
    """Canal hacia el servidor por WebSocket: un mensaje, un `send_str`."""

    via = "ws"

    def __init__(self, ws):
        self.ws = ws

    @property
    def cerrado(self):
        return self.ws.closed

    @property
    def vivo(self):
        return not self.ws.closed

    async def enviar(self, obj):
        await self.ws.send_str(remoto.a_json(obj))


class _CanalMqtt:
    """Canal hacia el servidor por MQTT: cada tipo de mensaje va a su topic con su QoS."""

    via = "mqtt"

    def __init__(self, cliente, topics):
        self.cliente = cliente
        self.topics = topics
        self.t_pong = None          # monotónico del último pong del servidor

    @property
    def cerrado(self):
        return not self.cliente.conectado

    @property
    def vivo(self):
        """El broker puede estar arriba con el servidor caído: solo cuentan los pong recientes."""
        return self.cliente.conectado and self.t_pong is not None \
            and time.monotonic() - self.t_pong < ENLACE_MQTT_VIVO_S

    async def enviar(self, obj):
        nombre = enlace_mqtt.TOPIC_DE_TIPO.get(obj.get("tipo"), obj.get("tipo"))
        topic = self.topics.de_tipo(obj.get("tipo"))
        if topic is None:
            return
        self.cliente.publicar(topic, obj, qos=enlace_mqtt.QOS.get(nombre, 0),
                              retain=enlace_mqtt.RETENIDO.get(nombre, False))


class Puente:
    def __init__(self, url, clave, pub=protocolo.PUB_DEFECTO, cmd=protocolo.CMD_DEFECTO,
                 hz=HZ_DEFECTO, planta="estacion", ruta_calibracion=None, log=print, contexto=None,
                 mqtt=None, prefijo=enlace_mqtt.PREFIJO_DEFECTO, suave="auto"):
        if not url and not mqtt:
            raise ValueError("hace falta la URL del WebSocket (url) o la del broker (mqtt)")
        self.url = url
        self.mqtt_url = mqtt
        self.transporte = "mqtt" if mqtt else "ws"
        self.topics = enlace_mqtt.Topics(prefijo, planta)
        self.clave = clave
        self.pub_dir = pub
        self.cmd_dir = cmd
        self.periodo_s = 1.0 / max(0.5, float(hz))
        self.planta = planta
        self.log = log
        self.ctx = contexto or zmq.asyncio.Context.instance()
        self.verificador = remoto.Verificador(clave)
        self.snapshot = None
        self._nuevo = asyncio.Event()       # hay snapshot o eventos sin enviar
        self._seq_enviado = -1
        self._t_envio = 0.0
        self._modo_anunciado = None
        self.rtt_ms = None                  # ida y vuelta puente ⇄ servidor (ms), None hasta el primer pong
        self._eventos = deque(maxlen=MAX_EVENTOS_COLA)
        self._presencia = []
        self._req = None
        self._lock_req = asyncio.Lock()
        self._parar = asyncio.Event()
        self.ws_conectado = False           # True mientras haya canal abierto (WS o MQTT)
        self.cliente_mqtt = None
        self.ordenes = {"aceptadas": 0, "rechazadas": 0}
        self._estimador = None
        cal = None
        if EstimadorCarrera is not None:
            cal = Calibracion(ruta_calibracion) if ruta_calibracion else Calibracion()
            cal.ruta = None          # solo lectura: la calibración la escribe el HMI
            self._estimador = EstimadorCarrera(cal)
        self.suave = suave if suave in MODOS_SUAVE else "auto"
        self._suavizador = None
        if Suavizador is not None and self.suave != "no":
            self._suavizador = Suavizador(cal, cadena=CadenaNeumatica() if CadenaNeumatica else None)
        self._suave_avisado = None

    # ------------------------------------------------------------------ ZeroMQ
    def _nuevo_req(self):
        if self._req is not None:
            self._req.close(0)
        self._req = self.ctx.socket(zmq.REQ)
        self._req.setsockopt(zmq.LINGER, 0)
        self._req.setsockopt(zmq.REQ_RELAXED, 1)
        self._req.setsockopt(zmq.REQ_CORRELATE, 1)
        self._req.connect(self.cmd_dir)

    async def orden_gateway(self, cmd):
        """Manda una orden al gateway y devuelve su respuesta (o un fallo si no contesta)."""
        async with self._lock_req:
            if self._req is None:
                self._nuevo_req()
            try:
                await self._req.send(protocolo.empaquetar(cmd))
                datos = await asyncio.wait_for(self._req.recv(), TIMEOUT_ORDEN_S)
                return protocolo.desempaquetar(datos)
            except (asyncio.TimeoutError, zmq.ZMQError) as e:
                self._nuevo_req()
                return protocolo.respuesta(False, "el gateway no respondió (%s)" % (e or "timeout"))

    async def _bucle_sub(self):
        sub = self.ctx.socket(zmq.SUB)
        sub.setsockopt(zmq.LINGER, 0)
        sub.setsockopt(zmq.SUBSCRIBE, b"")
        sub.connect(self.pub_dir)
        self.log("[puente] suscrito al gateway en %s" % self.pub_dir)
        try:
            while not self._parar.is_set():
                topic, datos = await sub.recv_multipart()
                msg = protocolo.desempaquetar(datos)
                if topic == protocolo.TOPIC_SNAP:
                    self.snapshot = self._completar(msg)
                elif topic == protocolo.TOPIC_EVT:
                    self._eventos.append(msg)
                self._nuevo.set()
        finally:
            sub.close(0)

    def _completar(self, snap):
        """Añade la posición estimada si el gateway no la da (REAL)."""
        if self._suavizador is not None:
            self._suavizador.actualizar(time.perf_counter(), snap)
        if self._estimador is None:
            return snap
        est = self._estimador.actualizar(time.perf_counter(), snap.get("bits") or {})
        if snap.get("pos") is None and snap.get("conectado"):
            snap["pos"] = [round(float(est[n]["pos"]), 3) for n in (1, 2, 3)]
            snap["pos_estimada"] = True
            snap["carreras"] = {str(n): {"objetivo": est[n]["objetivo"], "duracion_ms": est[n]["duracion_ms"],
                                         "moviendo": est[n]["moviendo"]} for n in (1, 2, 3)}
        else:
            snap["pos_estimada"] = False
        return snap

    def _suave_activo(self, snap):
        if self._suavizador is None or not snap.get("conectado"):
            return False
        return self.suave == "si" or (self.suave == "auto" and snap.get("pos_estimada", snap.get("pos") is None))

    def preparar_envio(self, snap, t=None):
        """Copia del snapshot lista para el servidor: con el modo suave, posición animada y bloque
        `suave`; sin él, tal cual. No toca `self.snapshot` (se reenvía si no llega otro)."""
        activo = self._suave_activo(snap)
        if activo != self._suave_avisado:
            self._suave_avisado = activo
            self.log("[puente] modo suave %s" % ("activo: posición prevista para el gemelo" if activo
                                                 else "inactivo: se manda la posición tal cual"))
        if not activo:
            return snap
        m = self._suavizador.muestrear(time.perf_counter() if t is None else t, dt_max=1.0)
        s = dict(snap)
        s["pos"] = m["pos"]
        s["pos_neum"] = m["pos_neum"]
        s["pos_estimada"] = True
        s["suave"] = {"v": m["velocidad"], "obj": m["objetivo"], "etapa": m["etapa"], "t_etapa": m["t_etapa"],
                      "acc": {str(k): v for k, v in m["acc"].items()}, "repuestas": m["repuestas"],
                      "sin_etapa": m["sin_etapa"]}
        return s

    # ------------------------------------------------------------------ mensajes comunes a los dos transportes
    def _hola(self, en_linea=True):
        return {"tipo": "hola", "v": remoto.VERSION_ENLACE, "planta": self.planta,
                "modo": (self.snapshot or {}).get("modo"), "en_linea": bool(en_linea), "t": time.time()}

    async def _enviar_estado(self, canal):
        """Snapshot en cuanto llega del gateway (respetando `hz` como máximo; y al menos uno por
        segundo aunque no cambie) y todos los eventos pendientes."""
        while not canal.cerrado:
            try:
                await asyncio.wait_for(self._nuevo.wait(), 1.0)
            except asyncio.TimeoutError:
                pass
            self._nuevo.clear()
            while self._eventos:
                await canal.enviar({"tipo": "evt", "e": self._eventos.popleft()})
            s = self.snapshot
            if s is None:
                continue
            ahora = time.monotonic()
            desde_envio = ahora - self._t_envio
            if s.get("seq") == self._seq_enviado and desde_envio < 1.0:
                continue
            if desde_envio < self.periodo_s:
                # Llegó antes de lo que permite `hz`: se espera lo justo y se manda el más nuevo.
                await asyncio.sleep(self.periodo_s - desde_envio)
                s = self.snapshot
                ahora = time.monotonic()
            if self.rtt_ms is not None:
                s["lat_web_ms"] = round(self.rtt_ms, 1)
            await canal.enviar({"tipo": "snap", "s": self.preparar_envio(s)})
            self._seq_enviado = s.get("seq")
            self._t_envio = ahora
            if s.get("modo") != self._modo_anunciado:
                # El servidor muestra el modo que anuncia `hola`; se reanuncia si cambia (o al conocerse).
                self._modo_anunciado = s.get("modo")
                await canal.enviar(self._hola())

    async def _latido_ping(self, canal):
        while not canal.cerrado:
            await canal.enviar({"tipo": "ping", "t": time.monotonic()})
            await asyncio.sleep(PERIODO_PING_S)

    async def _latido_presencia(self, canal):
        while not canal.cerrado:
            if canal.vivo:
                await self.orden_gateway(protocolo.cmd_presencia(self._presencia))
            await asyncio.sleep(PERIODO_PRESENCIA_S)

    async def _atender_orden(self, canal, orden):
        ok, motivo = self.verificador.verificar(orden)
        oid = orden.get("id") if isinstance(orden, dict) else None
        if not ok:
            self.ordenes["rechazadas"] += 1
            self.log("[puente] orden descartada: %s" % motivo)
            await canal.enviar({"tipo": "resultado", "id": oid, "ok": False,
                                "msg": "puente: %s" % motivo, "t": time.time()})
            return
        cmd = dict(orden["cmd"])
        cmd["quien"] = orden["quien"]
        resp = await self.orden_gateway(cmd)
        self.ordenes["aceptadas" if resp.get("ok") else "rechazadas"] += 1
        await canal.enviar({"tipo": "resultado", "id": oid, "ok": bool(resp.get("ok")),
                            "msg": resp.get("msg", ""), "t": time.time(), "mando": resp.get("mando")})

    async def _mensaje_servidor(self, canal, datos):
        """Lo que manda el servidor: orden, presencia o pong (igual por WS que por MQTT)."""
        tipo = datos.get("tipo")
        if tipo == "orden":
            asyncio.ensure_future(self._atender_orden(canal, datos))
        elif tipo == "presencia":
            self._presencia = datos.get("conectados") or []
            if canal.vivo:
                await self.orden_gateway(protocolo.cmd_presencia(self._presencia))
        elif tipo == "pong":
            try:
                self.rtt_ms = (time.monotonic() - float(datos.get("t"))) * 1000.0
            except (TypeError, ValueError):
                pass
            if isinstance(canal, _CanalMqtt):
                primero = canal.t_pong is None
                canal.t_pong = time.monotonic()
                if primero:
                    self.log("[puente] el servidor del gemelo responde por MQTT (%.0f ms)" % self.rtt_ms)
                    await self.orden_gateway(protocolo.cmd_presencia(self._presencia))

    # ------------------------------------------------------------------ WebSocket
    async def _sesion_ws(self, sesion):
        import aiohttp
        cab = {"Authorization": "Bearer %s" % self.clave, "X-Planta": self.planta}
        async with sesion.ws_connect(self.url, headers=cab, heartbeat=20, max_msg_size=4 * 1024 * 1024) as ws:
            canal = _CanalWs(ws)
            self.ws_conectado = True
            self._modo_anunciado = (self.snapshot or {}).get("modo")
            self.log("[puente] conectado a %s" % self.url)
            await canal.enviar(self._hola())
            tareas = [asyncio.ensure_future(self._enviar_estado(canal)),
                      asyncio.ensure_future(self._latido_presencia(canal)),
                      asyncio.ensure_future(self._latido_ping(canal))]
            try:
                async for msg in ws:
                    if msg.type != aiohttp.WSMsgType.TEXT:
                        continue
                    try:
                        datos = json.loads(msg.data)
                    except ValueError:
                        continue
                    await self._mensaje_servidor(canal, datos)
            finally:
                self.ws_conectado = False
                self.rtt_ms = None
                for t in tareas:
                    t.cancel()

    async def _bucle_ws(self):
        import aiohttp
        intento = 0
        async with aiohttp.ClientSession() as sesion:
            while not self._parar.is_set():
                try:
                    await self._sesion_ws(sesion)
                    intento = 0
                except aiohttp.WSServerHandshakeError as e:
                    self.log("[puente] el servidor rechazó la conexión (%s): ¿clave correcta?" % e.status)
                except (aiohttp.ClientError, OSError, asyncio.TimeoutError) as e:
                    self.log("[puente] sin conexión con el servidor: %s" % e)
                espera = ESPERAS_RECONEXION[min(intento, len(ESPERAS_RECONEXION) - 1)]
                intento += 1
                self.log("[puente] reintento en %.0f s" % espera)
                try:
                    await asyncio.wait_for(self._parar.wait(), espera)
                except asyncio.TimeoutError:
                    pass

    # ------------------------------------------------------------------ MQTT
    async def _bucle_mqtt(self):
        loop = asyncio.get_event_loop()
        T = self.topics
        cliente = enlace_mqtt.ClienteMqtt(self.mqtt_url, self.clave, "puente-%s" % T.planta, log=self.log)
        self.cliente_mqtt = cliente
        canal = _CanalMqtt(cliente, T)
        cliente.voluntad(T.estado, self._hola(en_linea=False), qos=enlace_mqtt.QOS["estado"], retain=True)
        for topic, qos in T.del_servidor():
            cliente.suscribir(topic, qos)
        tareas = []

        def al_conectar():
            self.ws_conectado = True
            self._modo_anunciado = (self.snapshot or {}).get("modo")
            cliente.publicar(T.estado, self._hola(), qos=enlace_mqtt.QOS["estado"], retain=True)
            tareas[:] = [asyncio.ensure_future(self._enviar_estado(canal)),
                         asyncio.ensure_future(self._latido_presencia(canal)),
                         asyncio.ensure_future(self._latido_ping(canal))]
            self.log("[puente] publicando en %s/… (planta %s)" % (T.base, self.planta))

        def al_desconectar(motivo):
            self.ws_conectado = False
            self.rtt_ms = None
            canal.t_pong = None
            for t in tareas:
                t.cancel()
            tareas[:] = []

        def al_recibir(topic, obj, retenido):
            if T.nombre(topic) in enlace_mqtt.NOMBRES_SERVIDOR:
                asyncio.ensure_future(self._mensaje_servidor(canal, obj))

        self.log("[puente] conectando al broker %s" % enlace_mqtt.ocultar_clave(self.mqtt_url))
        cliente.arrancar(loop, al_recibir, al_conectar, al_desconectar)
        try:
            await self._parar.wait()
        finally:
            for t in tareas:
                t.cancel()
            self.ws_conectado = False
            # Despedida limpia: el estado retenido queda en "fuera de línea" sin esperar al last will.
            await loop.run_in_executor(None, cliente.cerrar,
                                       (T.estado, self._hola(en_linea=False), enlace_mqtt.QOS["estado"], True))

    # ------------------------------------------------------------------ ciclo de vida
    async def correr(self):
        enlace = self._bucle_mqtt() if self.transporte == "mqtt" else self._bucle_ws()
        tareas = [asyncio.ensure_future(self._bucle_sub()), asyncio.ensure_future(enlace)]
        try:
            await self._parar.wait()
        finally:
            for t in tareas:
                t.cancel()
            await asyncio.gather(*tareas, return_exceptions=True)
            if self._req is not None:
                self._req.close(0)

    def detener(self):
        self._parar.set()
