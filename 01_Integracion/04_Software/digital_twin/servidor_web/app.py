# -*- coding: utf-8 -*-
"""
digital_twin/servidor_web/app.py — Servidor web del gemelo digital (aiohttp).

Corre en la PC servidor (Windows) en 127.0.0.1:3002, detrás de un proxy inverso o de un túnel que
publica https://digitaltwinscada.smartsensorslab.com:
    navegador ──HTTPS/WSS──▶ proxy / túnel ──HTTP──▶ este servidor (127.0.0.1:3002)
    puente del HMI ──WSS──▶ proxy / túnel ──▶ este servidor (/ws/planta)          (transporte por defecto)
    puente del HMI ──MQTT──▶ broker.smartsensorslab.com ◀──MQTT── este servidor   (con --mqtt)

Qué hace:
    * Sirve el frontend del gemelo (digital_twin/index.html) y una consola de prueba (/consola).
    * Autentica personas (usuario + contraseña, cookie de sesión HttpOnly) y aplica roles
      (core.mando.ROLES): usuario solo ve; operador START/STOP/RESET; ingeniero además
      parámetros; admin además cuentas.
    * Recibe el estado de la planta del puente, por /ws/planta (autenticado con la clave
      compartida) o por MQTT (mensajes sellados con esa misma clave, core/enlace_mqtt.py), y lo
      difunde a todos los navegadores (/ws/web). Un solo puente a la vez: el último que llega manda.
    * Recibe órdenes de los navegadores, las filtra por rol, las FIRMA (core.remoto) y las
      manda al puente. La decisión final (mando, concurrencia con el HMI local) la toma el
      gateway con core.mando.Arbitro; la respuesta vuelve al navegador y a la auditoría.
    * Anuncia a todos quién hizo qué y cuándo (mensaje "actividad") y quién está en línea.
    * Cada navegador tiene su propia cola de salida (clase Salida): los snapshots se sustituyen por
      el más nuevo y nunca se acumulan, así un navegador lento no retrasa a los demás.
    * Responde `pong` a los `ping` del puente y de los navegadores: cada tramo mide su ida y vuelta.

Contrato completo de mensajes: mds/ENLACE_WEB.md.
Compatibilidad: Python 3.12 a 3.13. Dependencias: aiohttp; paho-mqtt solo con MQTT.
"""
import asyncio
import hmac
import json
import os
import time
import unicodedata
from collections import deque

from aiohttp import WSMsgType, web

from core import enlace_mqtt, mando, remoto
from digital_twin.servidor_web.usuarios import Almacen, hash_clave

AQUI = os.path.dirname(os.path.abspath(__file__))
GEMELO = os.path.dirname(AQUI)
RAIZ = os.path.dirname(GEMELO)

COOKIE = "gemelo_sesion"
PUERTO_DEFECTO = 3002
TIMEOUT_RESULTADO_S = 3.0
MAX_ORDENES_POR_SEG = 4
LOGIN_MAX_FALLOS = 5
LOGIN_VENTANA_S = 300
PERIODO_PRESENCIA_S = 5.0
PLANTA_SIN_SNAP_S = 10.0        # MQTT: sin snapshots en este tiempo, la planta se da por fuera de línea
TOLERANCIA_SNAP_VIEJO_S = 2.0   # MQTT: se descartan snapshots más viejos que el último (reenvíos)
HOLA_RETENIDO_MAX_S = 30.0      # MQTT: un `hola` retenido más viejo que esto no pone la planta en línea

TAGS_PULSO = ("STARTV", "STOPV", "RESETV")
TAGS_PARAMETRO = ("T_ESPERA", "T_NEUM", "N_CICLOS")
RUTA_DATA = os.path.join(RAIZ, "mds", "data.md")


def leer_institucion(ruta=RUTA_DATA):
    """`Clave: valor` por línea de mds/data.md -> {"universidad", "facultad", "division", "departamento",
    "materia", "proyecto", "nombre"} (claves sin acentos ni mayúsculas, valores sin punto final)."""
    datos = {}
    try:
        with open(ruta, "r", encoding="utf-8") as f:
            for linea in f:
                if ":" not in linea:
                    continue
                clave, valor = linea.split(":", 1)
                clave = unicodedata.normalize("NFKD", clave.strip())
                clave = "".join(c for c in clave if not unicodedata.combining(c)).lower().replace(" ", "_")
                datos[clave] = valor.strip().rstrip(".").strip()
    except OSError:
        pass
    return datos


class Salida:
    """Cola de salida de un navegador. Los snapshots se SUSTITUYEN (solo importa el último) y los
    demás mensajes se conservan en orden. Cada navegador tiene su propia tarea de envío: uno lento
    (móvil con mala señal) recibe menos snapshots, pero no frena a los demás ni acumula retraso."""

    def __init__(self, ws):
        self.ws = ws
        self.cola = deque()
        self.snap = None
        self.aviso = asyncio.Event()
        self.descartados = 0
        self.tarea = None

    def poner(self, tipo, texto):
        if tipo == "snap":
            if self.snap is not None:
                self.descartados += 1
            self.snap = texto
        else:
            self.cola.append(texto)
        self.aviso.set()

    async def bombear(self):
        try:
            while not self.ws.closed:
                await self.aviso.wait()
                self.aviso.clear()
                while self.cola:
                    await self.ws.send_str(self.cola.popleft())
                if self.snap is not None:
                    texto, self.snap = self.snap, None
                    await self.ws.send_str(texto)
        except (ConnectionResetError, RuntimeError, asyncio.CancelledError):
            pass

    def arrancar(self):
        self.tarea = asyncio.ensure_future(self.bombear())

    def parar(self):
        if self.tarea is not None:
            self.tarea.cancel()


class _PlantaWs:
    """El puente conectado por WebSocket (/ws/planta)."""

    via = "ws"

    def __init__(self, ws):
        self.ws = ws
        self.t_snap = None

    async def enviar(self, obj):
        try:
            await self.ws.send_str(remoto.a_json(obj))
        except (ConnectionResetError, RuntimeError):
            pass

    async def cerrar(self, motivo):
        await self.ws.close(code=4000, message=motivo.encode("utf-8"))


class _PlantaMqtt:
    """El puente visto a través del broker MQTT: se publica en los topics del servidor."""

    via = "mqtt"

    def __init__(self, cliente, topics):
        self.cliente = cliente
        self.topics = topics
        self.t_snap = None          # `t` del último snapshot aceptado (reloj del gateway)
        self.t_ultimo = time.time()  # hora local del último mensaje del puente

    async def enviar(self, obj):
        tipo = obj.get("tipo")
        topic = self.topics.de_tipo(tipo)
        if topic is not None:
            self.cliente.publicar(topic, obj, qos=enlace_mqtt.QOS.get(tipo, 0),
                                  retain=enlace_mqtt.RETENIDO.get(tipo, False))

    async def cerrar(self, motivo):
        pass    # no hay conexión propia que cerrar: el puente seguirá publicando y se ignorará


def permisos(rol):
    """Qué puede hacer un rol (para que el frontend muestre u oculte controles)."""
    n = mando.ROLES.get(rol, -1)
    return {"ver": n >= 0, "mandos": n >= mando.ROLES["operador"],
            "parametros": n >= mando.ROLES["ingeniero"], "admin": n >= mando.ROLES["admin"],
            "auditoria": n >= mando.ROLES["ingeniero"]}


def limpiar_orden(cmd):
    """Reconstruye la orden con solo los campos permitidos desde la web. (cmd|None, motivo)."""
    if not isinstance(cmd, dict):
        return None, "orden mal formada"
    op = cmd.get("op")
    if op == "pulso":
        if cmd.get("tag") not in TAGS_PULSO:
            return None, "pulso no permitido"
        return {"op": "pulso", "tag": cmd["tag"], "ms": 300}, ""
    if op == "escribir":
        if cmd.get("tag") not in TAGS_PARAMETRO:
            return None, "parámetro no permitido"
        try:
            v = int(cmd.get("valor"))
        except (TypeError, ValueError):
            return None, "valor no entero"
        return {"op": "escribir", "tag": cmd["tag"], "valor": v}, ""
    if op == "mando":
        if cmd.get("accion") not in ("pedir", "liberar"):
            return None, "acción de mando no permitida"
        return {"op": "mando", "accion": cmd["accion"]}, ""
    return None, "orden no permitida desde la web"


def describir(cmd):
    if cmd["op"] == "pulso":
        return "pulso %s" % cmd["tag"]
    if cmd["op"] == "escribir":
        return "%s = %s" % (cmd["tag"], cmd["valor"])
    return "mando %s" % cmd["accion"]


class ServidorGemelo:
    def __init__(self, datos, clave, publico=False, index=None, mqtt=None,
                 planta=enlace_mqtt.PLANTA_DEFECTO, prefijo=enlace_mqtt.PREFIJO_DEFECTO, log=print):
        self.almacen = Almacen(os.path.join(datos, "gemelo.sqlite"))
        self.clave = clave
        self.publico = publico
        self.index = index or os.path.join(GEMELO, "index.html")
        self.log = log
        self.planta = None              # canal del puente (_PlantaWs | _PlantaMqtt) o None
        self.planta_info = {}
        self.snapshot = None
        self.eventos = deque(maxlen=200)
        self.web = {}                   # ws -> {"usuario", "rol", "desde", "ip"}
        self.pendientes = {}            # id de orden -> Future
        self._fallos_login = {}         # ip -> deque de tiempos
        self._ordenes_usuario = {}      # usuario -> deque de tiempos
        # MQTT (opcional)
        self.mqtt_url = mqtt
        self.topics = enlace_mqtt.Topics(prefijo, planta)
        self.mqtt = None
        self._planta_mqtt = None        # canal MQTT preparado (activo solo cuando self.planta es él)
        self._vigilante = None
        self._avisado_mqtt_ignorado = False

    # ================================================================== utilidades HTTP
    @staticmethod
    def ip(request):
        reenviada = request.headers.get("X-Forwarded-For", "")
        return request.headers.get("CF-Connecting-IP") or reenviada.split(",")[0].strip() or request.remote or "?"

    @staticmethod
    def es_https(request):
        return request.secure or request.headers.get("X-Forwarded-Proto") == "https"

    @staticmethod
    def origen_valido(request):
        """Protección CSRF / secuestro de WebSocket: el Origin debe ser este mismo sitio."""
        origen = request.headers.get("Origin")
        if not origen:
            return True
        host = request.headers.get("X-Forwarded-Host") or request.host
        return origen.split("://", 1)[-1].rstrip("/") == host

    def cuenta(self, request):
        c = self.almacen.sesion(request.cookies.get(COOKIE))
        if c is None and self.publico:
            return {"usuario": "invitado", "rol": "usuario", "invitado": True}
        return c

    def _limitar_login(self, ip):
        ahora = time.time()
        d = self._fallos_login.setdefault(ip, deque())
        while d and ahora - d[0] > LOGIN_VENTANA_S:
            d.popleft()
        return len(d) >= LOGIN_MAX_FALLOS

    # ================================================================== páginas
    async def pag_index(self, request):
        if not os.path.exists(self.index):
            raise web.HTTPFound("/consola")
        return web.FileResponse(self.index, headers={"Cache-Control": "no-cache"})

    async def pag_consola(self, request):
        return web.FileResponse(os.path.join(AQUI, "estatico", "consola.html"),
                                headers={"Cache-Control": "no-cache"})

    # ================================================================== API
    async def api_login(self, request):
        if not self.origen_valido(request):
            raise web.HTTPForbidden(text="origen no permitido")
        ip = self.ip(request)
        if self._limitar_login(ip):
            return web.json_response({"ok": False, "msg": "demasiados intentos; espera unos minutos"}, status=429)
        try:
            datos = await request.json()
        except ValueError:
            return web.json_response({"ok": False, "msg": "JSON inválido"}, status=400)
        usuario, clave = str(datos.get("usuario", "")), str(datos.get("clave", ""))
        u = self.almacen.usuario(usuario)
        sal, esperado = (u["sal"], u["hash"]) if u else ("00" * 16, "")
        calculado = await asyncio.get_event_loop().run_in_executor(None, hash_clave, clave, sal)
        if not u or not u["activo"] or not hmac.compare_digest(calculado, esperado):
            self._fallos_login.setdefault(ip, deque()).append(time.time())
            self.almacen.auditar(usuario[:32], None, ip, "login", "", False, "credenciales inválidas")
            return web.json_response({"ok": False, "msg": "usuario o contraseña incorrectos"}, status=401)
        token = self.almacen.crear_sesion(u["usuario"], ip)
        self.almacen.auditar(u["usuario"], u["rol"], ip, "login", "", True, "")
        resp = web.json_response({"ok": True, "usuario": u["usuario"], "rol": u["rol"],
                                  "permisos": permisos(u["rol"])})
        resp.set_cookie(COOKIE, token, httponly=True, samesite="Strict", secure=self.es_https(request),
                        max_age=12 * 3600, path="/")
        return resp

    async def api_logout(self, request):
        if not self.origen_valido(request):
            raise web.HTTPForbidden(text="origen no permitido")
        self.almacen.cerrar_sesion(request.cookies.get(COOKIE))
        resp = web.json_response({"ok": True})
        resp.del_cookie(COOKIE, path="/")
        return resp

    async def api_yo(self, request):
        c = self.cuenta(request)
        if c is None:
            return web.json_response({"ok": False, "msg": "sin sesión"}, status=401)
        return web.json_response({"ok": True, "usuario": c["usuario"], "rol": c["rol"],
                                  "invitado": bool(c.get("invitado")), "permisos": permisos(c["rol"])})

    async def api_estado(self, request):
        if self.cuenta(request) is None:
            return web.json_response({"ok": False, "msg": "sin sesión"}, status=401)
        return web.json_response({"ok": True, "planta_en_linea": self.planta is not None,
                                  "planta": self.planta_info, "snap": self.snapshot,
                                  "conectados": self.conectados()}, dumps=remoto.a_json)

    async def api_institucion(self, request):
        """Datos de mds/data.md para títulos y créditos del frontend (no requiere sesión)."""
        return web.json_response({"ok": True, "institucion": leer_institucion()})

    async def api_salud(self, request):
        """Para el proxy, el monitor o un `curl`: sin sesión, sin datos sensibles."""
        return web.json_response({"ok": True, "planta_en_linea": self.planta is not None,
                                  "via": self.planta.via if self.planta else None,
                                  "mqtt": None if self.mqtt is None else bool(self.mqtt.conectado),
                                  "navegadores": len(self.web), "t": time.time()})

    async def api_puente_clave(self, request):
        """Entrega la clave compartida del puente (datos/puente.clave) a una cuenta admin.

        Sirve para vincular el HMI del laboratorio sin copiar el archivo a mano: el HMI
        (puente/vincular.py) manda usuario y contraseña en el cuerpo JSON, sin cookie porque no es
        un navegador, y guarda la clave que recibe. Esa clave da acceso de «planta» (abre
        /ws/planta y firma las órdenes), por eso solo la obtiene un admin y en producción solo
        debe pedirse por HTTPS. Mismo limitador de intentos y misma verificación que /api/login."""
        sin_cache = {"Cache-Control": "no-store"}
        if not self.origen_valido(request):
            return web.json_response({"ok": False, "msg": "origen no permitido"}, status=403, headers=sin_cache)
        ip = self.ip(request)
        if self._limitar_login(ip):
            return web.json_response({"ok": False, "msg": "demasiados intentos; espera unos minutos"},
                                     status=429, headers=sin_cache)
        try:
            datos = await request.json()
        except ValueError:
            datos = None
        if not isinstance(datos, dict):
            return web.json_response({"ok": False, "msg": "JSON inválido"}, status=400, headers=sin_cache)
        usuario, clave = str(datos.get("usuario", "")), str(datos.get("clave", ""))
        u = self.almacen.usuario(usuario)
        sal, esperado = (u["sal"], u["hash"]) if u else ("00" * 16, "")
        calculado = await asyncio.get_event_loop().run_in_executor(None, hash_clave, clave, sal)
        if not u or not u["activo"] or not hmac.compare_digest(calculado, esperado):
            self._fallos_login.setdefault(ip, deque()).append(time.time())
            self.almacen.auditar(usuario[:32], None, ip, "puente-clave", "", False, "credenciales inválidas")
            return web.json_response({"ok": False, "msg": "usuario o contraseña incorrectos"},
                                     status=401, headers=sin_cache)
        if mando.ROLES.get(u["rol"], -1) < mando.ROLES["admin"]:
            self.almacen.auditar(u["usuario"], u["rol"], ip, "puente-clave", "", False, "se requiere rol admin")
            return web.json_response({"ok": False, "msg": "solo una cuenta admin puede vincular el puente"},
                                     status=403, headers=sin_cache)
        self.almacen.auditar(u["usuario"], u["rol"], ip, "puente-clave", "entregada", True, "")
        return web.json_response({"ok": True, "clave": self.clave, "planta_en_linea": self.planta is not None,
                                  "via": self.planta.via if self.planta else None,
                                  "mqtt": None if self.mqtt is None else bool(self.mqtt.conectado),
                                  "ws_planta": "/ws/planta"}, headers=sin_cache)

    def _exigir(self, request, minimo):
        c = self.cuenta(request)
        if c is None or c.get("invitado"):
            raise web.HTTPUnauthorized(text="sin sesión")
        if mando.ROLES.get(c["rol"], -1) < mando.ROLES[minimo]:
            raise web.HTTPForbidden(text="se requiere rol %s" % minimo)
        return c

    async def api_auditoria(self, request):
        self._exigir(request, "ingeniero")
        n = min(1000, int(request.query.get("n", 200)))
        return web.json_response({"ok": True, "filas": self.almacen.auditoria(n)})

    async def api_usuarios(self, request):
        c = self._exigir(request, "admin")
        if request.method == "GET":
            return web.json_response({"ok": True, "usuarios": self.almacen.listar(), "roles": list(mando.ROLES)})
        if not self.origen_valido(request):
            raise web.HTTPForbidden(text="origen no permitido")
        datos = await request.json()
        accion, usuario = datos.get("accion"), str(datos.get("usuario", ""))
        try:
            if accion == "crear":
                self.almacen.crear_usuario(usuario, str(datos.get("clave", "")), str(datos.get("rol", "usuario")))
            elif accion == "rol":
                if usuario == c["usuario"]:
                    raise ValueError("no puedes cambiar tu propio rol")
                self.almacen.cambiar_rol(usuario, str(datos.get("rol")))
            elif accion == "clave":
                self.almacen.cambiar_clave(usuario, str(datos.get("clave", "")))
            elif accion == "activo":
                if usuario == c["usuario"]:
                    raise ValueError("no puedes desactivarte a ti mismo")
                self.almacen.activar(usuario, bool(datos.get("activo")))
            elif accion == "borrar":
                if usuario == c["usuario"]:
                    raise ValueError("no puedes borrarte a ti mismo")
                self.almacen.borrar(usuario)
            else:
                raise ValueError("acción desconocida")
        except ValueError as e:
            return web.json_response({"ok": False, "msg": str(e)}, status=400)
        detalle = "%s %s %s" % (accion, usuario, datos.get("rol", ""))
        self.almacen.auditar(c["usuario"], c["rol"], self.ip(request), "usuarios", detalle.strip(), True, "")
        # Las sesiones abiertas del afectado se reevalúan: se cierra su WebSocket si ya no vale.
        await self._reevaluar_sesiones()
        return web.json_response({"ok": True, "usuarios": self.almacen.listar()})

    async def _reevaluar_sesiones(self):
        for ws, info in list(self.web.items()):
            if info.get("invitado"):
                continue
            actual = self.almacen.sesion(info.get("token"))
            if actual is None:
                await ws.close(code=4001, message=b"sesion cerrada")
            elif actual["rol"] != info["rol"]:
                info["rol"] = actual["rol"]
                await self._enviar(ws, {"tipo": "yo", "usuario": info["usuario"], "rol": info["rol"],
                                        "permisos": permisos(info["rol"])})
        await self._anunciar_presencia()

    # ================================================================== difusión
    async def _enviar(self, ws, obj):
        """A un navegador por su cola (conserva el orden con la difusión)."""
        info = self.web.get(ws)
        if info is not None:
            info["salida"].poner(obj.get("tipo"), remoto.a_json(obj))
            return
        try:
            await ws.send_str(remoto.a_json(obj))
        except (ConnectionResetError, RuntimeError):
            pass

    async def difundir(self, obj):
        """A todos los navegadores sin esperar a ninguno (cada uno tiene su cola)."""
        texto = remoto.a_json(obj)
        tipo = obj.get("tipo")
        for info in list(self.web.values()):
            info["salida"].poner(tipo, texto)

    def conectados(self):
        """Personas en línea (una fila por usuario, con su rol y desde cuándo)."""
        vistos = {}
        for info in self.web.values():
            u = vistos.get(info["usuario"])
            if u is None or info["desde"] < u["desde"]:
                vistos[info["usuario"]] = {"usuario": info["usuario"], "rol": info["rol"], "desde": info["desde"]}
        return sorted(vistos.values(), key=lambda u: (-mando.ROLES.get(u["rol"], -1), u["usuario"]))

    async def _anunciar_presencia(self):
        lista = self.conectados()
        await self.difundir({"tipo": "presencia", "conectados": lista})
        if self.planta is not None:
            await self.planta.enviar({"tipo": "presencia", "conectados": lista})

    # ================================================================== WebSocket de navegadores
    async def ws_web(self, request):
        if not self.origen_valido(request):
            raise web.HTTPForbidden(text="origen no permitido")
        c = self.cuenta(request)
        if c is None:
            raise web.HTTPUnauthorized(text="inicia sesión")
        ws = web.WebSocketResponse(heartbeat=25, max_msg_size=64 * 1024)
        await ws.prepare(request)
        salida = Salida(ws)
        info = {"usuario": c["usuario"], "rol": c["rol"], "desde": time.time(), "ip": self.ip(request),
                "invitado": bool(c.get("invitado")), "token": request.cookies.get(COOKIE), "salida": salida}
        self.web[ws] = info
        salida.arrancar()
        await self._enviar(ws, {"tipo": "bienvenida", "yo": {"usuario": c["usuario"], "rol": c["rol"],
                                                             "invitado": info["invitado"], "permisos": permisos(c["rol"])},
                                "planta_en_linea": self.planta is not None, "planta": self.planta_info,
                                "snap": self.snapshot, "eventos": list(self.eventos)[-50:],
                                "roles": list(mando.ROLES)})
        await self._anunciar_presencia()
        try:
            async for msg in ws:
                if msg.type != WSMsgType.TEXT:
                    continue
                try:
                    datos = json.loads(msg.data)
                except ValueError:
                    continue
                if datos.get("tipo") == "orden":
                    asyncio.ensure_future(self._orden_web(ws, info, datos))
                elif datos.get("tipo") == "ping":
                    # El navegador mide su ida y vuelta con `t` (su reloj); `t_srv` es la hora del servidor.
                    await self._enviar(ws, {"tipo": "pong", "t": datos.get("t"), "t_srv": time.time()})
        finally:
            self.web.pop(ws, None)
            salida.parar()
            await self._anunciar_presencia()
        return ws

    async def _orden_web(self, ws, info, datos):
        ref = datos.get("ref")

        async def responder(ok, msg, mando_estado=None, auditar=True, detalle=""):
            if auditar:
                act = self.almacen.auditar(info["usuario"], info["rol"], info["ip"], "orden", detalle, ok, msg)
                await self.difundir(dict(act, tipo="actividad"))
            await self._enviar(ws, {"tipo": "resultado", "ref": ref, "ok": ok, "msg": msg, "mando": mando_estado})

        cmd, motivo = limpiar_orden(datos.get("cmd"))
        if cmd is None:
            return await responder(False, motivo, auditar=False)
        detalle = describir(cmd)
        # Frescura del rol: se relee de la base por si el admin lo cambió.
        if not info.get("invitado"):
            actual = self.almacen.sesion(info.get("token"))
            if actual is None:
                return await responder(False, "sesión vencida", detalle=detalle)
            info["rol"] = actual["rol"]
        ok, motivo = mando.permiso_por_rol(info["rol"], cmd)
        if not ok or info.get("invitado"):
            return await responder(False, motivo or "inicia sesión para mandar", detalle=detalle)
        ahora = time.time()
        d = self._ordenes_usuario.setdefault(info["usuario"], deque())
        while d and ahora - d[0] > 1.0:
            d.popleft()
        if len(d) >= MAX_ORDENES_POR_SEG:
            return await responder(False, "demasiadas órdenes por segundo", auditar=False)
        d.append(ahora)
        planta = self.planta
        if planta is None:
            return await responder(False, "la planta no está en línea (puente desconectado)", detalle=detalle)
        orden = remoto.nueva_orden(self.clave, cmd, {"usuario": info["usuario"], "rol": info["rol"]})
        fut = asyncio.get_event_loop().create_future()
        self.pendientes[orden["id"]] = fut
        try:
            await planta.enviar(orden)
            res = await asyncio.wait_for(fut, TIMEOUT_RESULTADO_S)
        except asyncio.TimeoutError:
            return await responder(False, "la planta no respondió a tiempo", detalle=detalle)
        finally:
            self.pendientes.pop(orden["id"], None)
        await responder(bool(res.get("ok")), res.get("msg", ""), res.get("mando"), detalle=detalle)

    # ================================================================== la planta (común a WS y MQTT)
    async def _planta_llega(self, canal, info):
        """Un puente nuevo (por WS o por MQTT) pasa a ser LA planta; el anterior se despide."""
        if self.planta is not None and self.planta is not canal:
            await self.planta.cerrar("reemplazado por otro puente")
        self.planta = canal
        self.planta_info = dict(info, via=canal.via, desde=time.time())
        self.almacen.auditar("puente", None, self.planta_info.get("ip"), "puente", "conectado (%s)" % canal.via, True, "")
        await self.difundir({"tipo": "planta", "en_linea": True, "planta": self.planta_info})
        await canal.enviar({"tipo": "presencia", "conectados": self.conectados()})

    async def _planta_perdida(self, canal, motivo):
        if self.planta is not canal:
            return
        self.planta = None
        self.almacen.auditar("puente", None, self.planta_info.get("ip"), "puente", "%s (%s)" % (motivo, canal.via), True, "")
        await self.difundir({"tipo": "planta", "en_linea": False})
        for fut in self.pendientes.values():
            if not fut.done():
                fut.set_result({"ok": False, "msg": "se perdió la conexión con la planta"})

    async def _mensaje_planta(self, canal, datos):
        """Lo que manda el puente: snap, evt, resultado, hola o ping (igual por WS que por MQTT)."""
        tipo = datos.get("tipo")
        if tipo == "snap":
            s = datos.get("s")
            if not isinstance(s, dict):
                return
            t = s.get("t")
            if canal.via == "mqtt" and isinstance(t, (int, float)) and canal.t_snap is not None \
                    and t < canal.t_snap - TOLERANCIA_SNAP_VIEJO_S:
                return                      # reenvío o desorden del broker: se ignora el viejo
            if isinstance(t, (int, float)):
                canal.t_snap = t
            self.snapshot = s
            await self.difundir({"tipo": "snap", "s": self.snapshot})
        elif tipo == "evt":
            self.eventos.append(datos.get("e"))
            await self.difundir({"tipo": "evt", "e": datos.get("e")})
        elif tipo == "resultado":
            fut = self.pendientes.get(datos.get("id"))
            if fut is not None and not fut.done():
                fut.set_result(datos)
        elif tipo == "hola":
            self.planta_info.update({"modo": datos.get("modo"), "planta": datos.get("planta")})
            await self.difundir({"tipo": "planta", "en_linea": True, "planta": self.planta_info})
        elif tipo == "ping":
            # El puente mide la ida y vuelta hasta aquí y la publica como `lat_web_ms` en el snapshot.
            await canal.enviar({"tipo": "pong", "t": datos.get("t"), "t_srv": time.time()})

    # ================================================================== WebSocket del puente
    async def ws_planta(self, request):
        autorizacion = request.headers.get("Authorization", "")
        if not hmac.compare_digest(autorizacion, "Bearer %s" % self.clave):
            self.almacen.auditar("puente", None, self.ip(request), "puente", "", False, "clave inválida")
            raise web.HTTPUnauthorized(text="clave inválida")
        ws = web.WebSocketResponse(heartbeat=20, max_msg_size=4 * 1024 * 1024)
        await ws.prepare(request)
        canal = _PlantaWs(ws)
        await self._planta_llega(canal, {"planta": request.headers.get("X-Planta", "?"), "ip": self.ip(request)})
        try:
            async for msg in ws:
                if msg.type != WSMsgType.TEXT:
                    continue
                try:
                    datos = json.loads(msg.data)
                except ValueError:
                    continue
                if self.planta is canal:
                    await self._mensaje_planta(canal, datos)
        finally:
            await self._planta_perdida(canal, "desconectado")
        return ws

    # ================================================================== MQTT del puente
    def _mqtt_arrancar(self, loop):
        if not self.mqtt_url:
            return
        T = self.topics
        self.mqtt = enlace_mqtt.ClienteMqtt(self.mqtt_url, self.clave, "gemelo-%s" % T.planta, log=self.log)
        self._planta_mqtt = _PlantaMqtt(self.mqtt, T)
        for topic, qos in T.del_puente():
            self.mqtt.suscribir(topic, qos)
        self.mqtt.arrancar(loop, self._mqtt_recibir, al_conectar=self._mqtt_conectado)
        self._vigilante = asyncio.ensure_future(self._vigilar_mqtt())
        self.log("[gemelo] MQTT: escuchando al puente en %s/{%s} vía %s" % (
            T.base, ",".join(enlace_mqtt.NOMBRES_PUENTE), enlace_mqtt.ocultar_clave(self.mqtt_url)))

    def _mqtt_conectado(self):
        # Al (re)conectar, el puente recibe la presencia actual aunque no haya cambiado (topic retenido).
        if self.planta is self._planta_mqtt:
            asyncio.ensure_future(self.planta.enviar({"tipo": "presencia", "conectados": self.conectados()}))

    def _mqtt_recibir(self, topic, obj, retenido):
        asyncio.ensure_future(self._mqtt_mensaje(topic, obj, retenido))

    async def _mqtt_mensaje(self, topic, obj, retenido):
        nombre = self.topics.nombre(topic)
        if nombre not in enlace_mqtt.NOMBRES_PUENTE:
            return
        canal = self._planta_mqtt
        tipo = obj.get("tipo")
        if nombre == "estado":
            fresco = not retenido or (isinstance(obj.get("t"), (int, float)) and time.time() - obj["t"] < HOLA_RETENIDO_MAX_S)
            if obj.get("en_linea", True) is False:
                if self.planta is canal and not retenido:
                    await self._planta_perdida(canal, "desconectado")
                return
            if self.planta is None and fresco:
                canal.t_ultimo = time.time()
                await self._planta_llega(canal, {"planta": obj.get("planta"), "modo": obj.get("modo"),
                                                 "ip": self.mqtt.cfg["host"]})
            if self.planta is canal:
                await self._mensaje_planta(canal, obj)
            return
        if self.planta is None and nombre == "snap":
            canal.t_ultimo = time.time()
            s = obj.get("s") or {}
            await self._planta_llega(canal, {"planta": self.topics.planta, "modo": s.get("modo"),
                                             "ip": self.mqtt.cfg["host"]})
        if self.planta is not canal:
            if self.planta is not None and not self._avisado_mqtt_ignorado:
                self._avisado_mqtt_ignorado = True
                self.log("[gemelo] MQTT: llegan mensajes del puente por el broker, pero hay un puente por WebSocket; se ignoran")
            if nombre == "resultado":      # una respuesta tardía a una orden sigue valiendo
                await self._mensaje_planta(canal, obj)
            return
        self._avisado_mqtt_ignorado = False
        canal.t_ultimo = time.time()
        await self._mensaje_planta(canal, obj)

    async def _vigilar_mqtt(self):
        """Sin snapshots del puente durante PLANTA_SIN_SNAP_S (el puente manda al menos uno por
        segundo), la planta se da por fuera de línea aunque el last will no haya llegado."""
        try:
            while True:
                await asyncio.sleep(2.0)
                canal = self._planta_mqtt
                if self.planta is canal and canal is not None and time.time() - canal.t_ultimo > PLANTA_SIN_SNAP_S:
                    await self._planta_perdida(canal, "sin noticias %.0f s" % PLANTA_SIN_SNAP_S)
        except asyncio.CancelledError:
            pass

    # ================================================================== aplicación
    @web.middleware
    async def cabeceras(self, request, handler):
        resp = await handler(request)
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("Referrer-Policy", "same-origin")
        resp.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
        return resp

    def aplicacion(self):
        app = web.Application(middlewares=[self.cabeceras])
        app.add_routes([
            web.get("/", self.pag_index),
            web.get("/consola", self.pag_consola),
            web.post("/api/login", self.api_login),
            web.post("/api/logout", self.api_logout),
            web.get("/api/yo", self.api_yo),
            web.get("/api/estado", self.api_estado),
            web.get("/api/institucion", self.api_institucion),
            web.get("/api/salud", self.api_salud),
            web.post("/api/puente/clave", self.api_puente_clave),
            web.get("/api/auditoria", self.api_auditoria),
            web.get("/api/usuarios", self.api_usuarios),
            web.post("/api/usuarios", self.api_usuarios),
            web.get("/ws/web", self.ws_web),
            web.get("/ws/planta", self.ws_planta),
            web.static("/estatico", os.path.join(AQUI, "estatico")),
        ])
        assets = os.path.join(RAIZ, "assets", "assets_cilindros")
        if os.path.isdir(assets):
            app.router.add_static("/assets", assets)

        async def al_arrancar(_app):
            self._mqtt_arrancar(asyncio.get_event_loop())

        async def al_cerrar(_app):
            if self._vigilante is not None:
                self._vigilante.cancel()
            for ws in list(self.web):
                await ws.close(code=1001, message=b"servidor detenido")
            if self.planta is not None:
                await self.planta.cerrar("servidor detenido")
            if self.mqtt is not None:
                # Se borra la presencia retenida para que el puente no vea una lista vieja al volver.
                await asyncio.get_event_loop().run_in_executor(
                    None, self.mqtt.cerrar, (self.topics.presencia, {"tipo": "presencia", "conectados": []}, 0, True))
            self.almacen.cerrar()
        app.on_startup.append(al_arrancar)
        app.on_shutdown.append(al_cerrar)
        return app
