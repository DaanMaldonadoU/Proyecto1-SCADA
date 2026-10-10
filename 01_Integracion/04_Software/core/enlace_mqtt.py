# -*- coding: utf-8 -*-
"""
core/enlace_mqtt.py — Transporte MQTT del enlace puente ⇄ servidor del gemelo (alternativa a /ws/planta).

Qué hace:
    El puente (puente/) y el servidor web del gemelo (digital_twin/servidor_web) pueden hablar por
    un broker MQTT (p. ej. broker.smartsensorslab.com) en lugar del WebSocket saliente /ws/planta.
    Los MENSAJES son los mismos del contrato de mds/ENLACE_WEB.md (campo "tipo": snap, evt, hola,
    resultado, ping, orden, presencia, pong); cambia solo el camino por el que viajan. Este módulo
    aporta las tres piezas que ambos lados comparten:

    * Topics: ``<prefijo>/<planta>/<nombre>``. El puente publica snap, evt, estado (retenido, con
      last will), resultado y ping; el servidor publica orden, presencia (retenido) y pong.
    * Sobre sellado: el broker es un intermediario en el que no se confía. Cada mensaje se publica
      como ``firma_hex + "\\n" + json`` con HMAC-SHA256 de la misma clave compartida del enlace
      (``puente.clave``). Quien no tenga la clave puede llenar el topic, pero sus mensajes se
      descartan al abrir el sobre. Las órdenes conservan además su firma propia de core.remoto
      (hora, id único): el sobre no sustituye esa protección contra reenvíos.
    * ClienteMqtt: envoltorio de paho-mqtt para un bucle asyncio. La red va en el hilo de paho
      (``loop_start``); lo recibido pasa al bucle con ``call_soon_threadsafe`` ya verificado.

URL del broker (``--mqtt`` en el puente y en el servidor):
    mqtt://usuario:clave@host[:1883]            TCP sin cifrar (solo dentro de la misma máquina)
    mqtts://usuario:clave@host[:8883]           TCP con TLS
    mqtt+ws://usuario:clave@host[:80][/ruta]    MQTT sobre WebSocket
    mqtt+wss://usuario:clave@host[:443][/ruta]  MQTT sobre WebSocket con TLS (pasa por proxies y
                                                por redes que solo dejan salir por 443)
    Parámetros opcionales: ``?ca=ruta.pem`` (CA propia) e ``?inseguro=1`` (no verificar el
    certificado: solo para pruebas con certificados autofirmados).

Compatibilidad: Python 3.12 a 3.13. Dependencia: paho-mqtt >= 2 (pura Python), importada solo al
arrancar el cliente, así el módulo se puede importar sin ella (sellar/abrir y los topics no la usan).
"""
import hashlib
import hmac
import json
import re
import secrets
import ssl
import unicodedata
from urllib.parse import parse_qs, unquote, urlparse

from core import remoto

PREFIJO_DEFECTO = "scada"
PLANTA_DEFECTO = "estacion-electroneumatica"

# esquema -> (tls, transporte paho, puerto por defecto)
ESQUEMAS = {
    "mqtt": (False, "tcp", 1883),
    "mqtts": (True, "tcp", 8883),
    "mqtt+ws": (False, "websockets", 80),
    "mqtt+wss": (True, "websockets", 443),
}

NOMBRES_PUENTE = ("snap", "evt", "estado", "resultado", "ping")      # los publica el puente
NOMBRES_SERVIDOR = ("orden", "presencia", "pong")                    # los publica el servidor
QOS = {"snap": 0, "evt": 1, "estado": 1, "resultado": 1, "ping": 0, "orden": 1, "presencia": 0, "pong": 0}
RETENIDO = {"estado": True, "presencia": True}
# "tipo" del mensaje -> nombre de topic (el resto coincide con su tipo)
TOPIC_DE_TIPO = {"hola": "estado"}
KEEPALIVE_S = 20
LARGO_FIRMA = 64


def es_url_mqtt(url):
    """True si la URL tiene uno de los esquemas MQTT de este módulo."""
    return isinstance(url, str) and url.split("://", 1)[0].lower() in ESQUEMAS


def slug(texto, defecto=PLANTA_DEFECTO):
    """Segmento de topic a partir de un nombre libre: minúsculas sin acentos, letras, dígitos y guiones."""
    t = unicodedata.normalize("NFKD", str(texto or ""))
    t = "".join(c for c in t if not unicodedata.combining(c)).lower()
    t = re.sub(r"[^a-z0-9]+", "-", t).strip("-")
    return t or defecto


def analizar_url(url):
    """Descompone una URL MQTT. Lanza ValueError si el esquema no es de este módulo."""
    u = urlparse(url)
    esquema = u.scheme.lower()
    if esquema not in ESQUEMAS:
        raise ValueError("esquema MQTT desconocido en %r (usa mqtt://, mqtts://, mqtt+ws:// o mqtt+wss://)" % url)
    tls, transporte, puerto = ESQUEMAS[esquema]
    if not u.hostname:
        raise ValueError("la URL MQTT no tiene host: %r" % url)
    q = parse_qs(u.query)
    return {
        "esquema": esquema, "host": u.hostname, "puerto": u.port or puerto, "tls": tls,
        "transporte": transporte, "usuario": unquote(u.username) if u.username else None,
        "clave": unquote(u.password) if u.password else None,
        "ruta": u.path if transporte == "websockets" and u.path else ("/mqtt" if transporte == "websockets" else None),
        "ca": q.get("ca", [None])[0], "inseguro": q.get("inseguro", ["0"])[0] in ("1", "true", "si", "sí"),
    }


def ocultar_clave(url):
    """La URL sin la contraseña, para registros y pantallas."""
    try:
        u = urlparse(url)
        if u.password:
            return url.replace(":" + u.password + "@", ":***@", 1)
    except ValueError:
        pass
    return url


class Topics:
    """Nombres de topic de una planta: ``t.snap``, ``t.orden``… y ``t.nombre(topic)`` para el inverso."""

    def __init__(self, prefijo=PREFIJO_DEFECTO, planta=PLANTA_DEFECTO):
        self.prefijo = slug(prefijo, PREFIJO_DEFECTO)
        self.planta = slug(planta)
        self.base = "%s/%s" % (self.prefijo, self.planta)
        self._por_topic = {}
        for n in NOMBRES_PUENTE + NOMBRES_SERVIDOR:
            topic = "%s/%s" % (self.base, n)
            setattr(self, n, topic)
            self._por_topic[topic] = n

    def nombre(self, topic):
        """'snap', 'orden'… o None si el topic no es de esta planta."""
        return self._por_topic.get(topic)

    def de_tipo(self, tipo):
        """Topic al que va un mensaje según su campo "tipo" (None si no viaja por MQTT)."""
        n = TOPIC_DE_TIPO.get(tipo, tipo)
        return getattr(self, n, None) if n in self._por_topic.values() else None

    def del_puente(self):
        return [(getattr(self, n), QOS[n]) for n in NOMBRES_PUENTE]

    def del_servidor(self):
        return [(getattr(self, n), QOS[n]) for n in NOMBRES_SERVIDOR]


# ---------------------------------------------------------------------------- sobre sellado
def _firma(clave, cuerpo):
    return hmac.new(clave.encode("utf-8"), cuerpo, hashlib.sha256).hexdigest()


def sellar(clave, obj):
    """bytes listos para publicar: ``firma_hex\\njson``."""
    cuerpo = remoto.a_json(obj).encode("utf-8")
    return _firma(clave, cuerpo).encode("ascii") + b"\n" + cuerpo


def abrir(clave, payload):
    """(ok, obj, motivo). Rechaza sobres mal formados o con firma ajena."""
    if not isinstance(payload, (bytes, bytearray)) or len(payload) < LARGO_FIRMA + 2 \
            or payload[LARGO_FIRMA:LARGO_FIRMA + 1] != b"\n":
        return False, None, "sobre mal formado"
    firma = bytes(payload[:LARGO_FIRMA]).decode("ascii", "replace")
    cuerpo = bytes(payload[LARGO_FIRMA + 1:])
    if not hmac.compare_digest(firma, _firma(clave, cuerpo)):
        return False, None, "firma inválida"
    try:
        obj = json.loads(cuerpo.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return False, None, "JSON inválido"
    if not isinstance(obj, dict) or not isinstance(obj.get("tipo"), str):
        return False, None, "mensaje sin tipo"
    return True, obj, ""


# ---------------------------------------------------------------------------- cliente
class ClienteMqtt:
    """paho-mqtt sobre asyncio. Uso:

        c = ClienteMqtt(url, clave, "puente-estacion", log=print)
        c.voluntad(topics.estado, {"tipo": "hola", "en_linea": False, ...})     # antes de arrancar
        c.suscribir(topics.orden, 1)
        c.arrancar(loop, al_recibir=lambda topic, obj: ..., al_conectar=..., al_desconectar=...)
        c.publicar(topics.snap, {"tipo": "snap", "s": snap})                  # desde cualquier hilo
        c.cerrar(despedida=(topics.estado, {...}, 1, True))

    Las devoluciones de llamada se ejecutan en el bucle asyncio dado, con el sobre ya abierto y
    verificado. Reconecta solo (espera creciente de 1 a 30 s) y vuelve a suscribirse al reconectar.
    """

    def __init__(self, url, clave, id_cliente, log=print, keepalive=KEEPALIVE_S):
        self.cfg = analizar_url(url)
        self.url = url
        self.clave = clave
        # Sufijo aleatorio: dos puentes con el mismo id se expulsarían mutuamente del broker sin fin.
        self.id_cliente = "%s-%s" % (id_cliente, secrets.token_hex(3))
        self.log = log
        self.keepalive = int(keepalive)
        self.conectado = False
        self.recibidos = 0
        self.rechazados = 0
        self.enviados = 0
        self.ultimo_error = None
        self._paho = None
        self._loop = None
        self._al_recibir = None
        self._al_conectar = None
        self._al_desconectar = None
        self._suscripciones = []
        self._voluntad = None
        self._avisos_rechazo = 0

    # ------------------------------------------------------------------ configuración previa
    def voluntad(self, topic, obj, qos=1, retain=True):
        """Mensaje que el broker publicará si este cliente desaparece sin despedirse (last will)."""
        self._voluntad = (topic, sellar(self.clave, obj), int(qos), bool(retain))

    def suscribir(self, topic, qos=0):
        self._suscripciones.append((topic, int(qos)))
        if self._paho is not None and self.conectado:
            self._paho.subscribe(topic, int(qos))

    # ------------------------------------------------------------------ arranque y cierre
    def arrancar(self, loop, al_recibir, al_conectar=None, al_desconectar=None):
        import paho.mqtt.client as mqtt

        self._loop = loop
        self._al_recibir = al_recibir
        self._al_conectar = al_conectar
        self._al_desconectar = al_desconectar
        c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=self.id_cliente, clean_session=True,
                        protocol=mqtt.MQTTv311, transport=self.cfg["transporte"])
        if self.cfg["usuario"]:
            c.username_pw_set(self.cfg["usuario"], self.cfg["clave"])
        if self.cfg["tls"]:
            if self.cfg["inseguro"]:
                c.tls_set(cert_reqs=ssl.CERT_NONE)
                c.tls_insecure_set(True)
            else:
                c.tls_set(ca_certs=self.cfg["ca"])
        if self.cfg["transporte"] == "websockets":
            c.ws_set_options(path=self.cfg["ruta"] or "/mqtt")
        if self._voluntad is not None:
            topic, payload, qos, retain = self._voluntad
            c.will_set(topic, payload, qos=qos, retain=retain)
        c.on_connect = self._paho_connect
        c.on_disconnect = self._paho_disconnect
        c.on_message = self._paho_message
        c.reconnect_delay_set(min_delay=1, max_delay=30)
        self._paho = c
        try:
            c.connect_async(self.cfg["host"], self.cfg["puerto"], self.keepalive)
        except (OSError, ValueError) as e:      # p. ej. host mal formado; la red se reintenta sola
            self.ultimo_error = str(e)
            self.log("[mqtt] no se pudo preparar la conexión a %s: %s" % (ocultar_clave(self.url), e))
        c.loop_start()

    def cerrar(self, despedida=None):
        """Publica la despedida (topic, obj, qos, retain) si se da, se desconecta y para el hilo."""
        c, self._paho = self._paho, None
        if c is None:
            return
        try:
            if despedida is not None and self.conectado:
                topic, obj, qos, retain = despedida
                info = c.publish(topic, sellar(self.clave, obj), qos=int(qos), retain=bool(retain))
                try:
                    info.wait_for_publish(2.0)
                except (RuntimeError, ValueError):
                    pass
            c.disconnect()
        except Exception as e:  # pragma: no cover - cierre tolerante
            self.ultimo_error = str(e)
        finally:
            c.loop_stop()
            self.conectado = False

    # ------------------------------------------------------------------ publicación
    def publicar(self, topic, obj, qos=0, retain=False):
        """Sella y publica. Devuelve True si paho lo aceptó (no garantiza la entrega en QoS 0)."""
        c = self._paho
        if c is None:
            return False
        try:
            info = c.publish(topic, sellar(self.clave, obj), qos=int(qos), retain=bool(retain))
        except (ValueError, OSError) as e:
            self.ultimo_error = str(e)
            return False
        ok = info.rc == 0
        if ok:
            self.enviados += 1
        return ok

    # ------------------------------------------------------------------ devoluciones de paho (hilo de red)
    def _en_bucle(self, fn, *args):
        loop = self._loop
        if loop is None or loop.is_closed():
            return
        try:
            loop.call_soon_threadsafe(fn, *args)
        except RuntimeError:       # el bucle se cerró entre la comprobación y la llamada
            pass

    def _paho_connect(self, client, userdata, flags, reason_code, properties=None):
        ok = not getattr(reason_code, "is_failure", False) and getattr(reason_code, "value", reason_code) == 0
        self._en_bucle(self._conectado, ok, str(reason_code))

    def _paho_disconnect(self, client, userdata, flags, reason_code, properties=None):
        self._en_bucle(self._desconectado, str(reason_code))

    def _paho_message(self, client, userdata, msg):
        self._en_bucle(self._mensaje, msg.topic, bytes(msg.payload), bool(msg.retain))

    # ------------------------------------------------------------------ en el bucle asyncio
    def _conectado(self, ok, motivo):
        if not ok:
            self.ultimo_error = motivo
            self.log("[mqtt] el broker rechazó la conexión: %s" % motivo)
            return
        self.conectado = True
        self.ultimo_error = None
        c = self._paho
        if c is not None:
            for topic, qos in self._suscripciones:
                c.subscribe(topic, qos)
        self.log("[mqtt] conectado a %s como %s" % (ocultar_clave(self.url), self.id_cliente))
        if self._al_conectar is not None:
            self._al_conectar()

    def _desconectado(self, motivo):
        estaba = self.conectado
        self.conectado = False
        if estaba:
            self.log("[mqtt] desconectado del broker (%s); reintentando" % motivo)
        if self._al_desconectar is not None and estaba:
            self._al_desconectar(motivo)

    def _mensaje(self, topic, payload, retenido):
        ok, obj, motivo = abrir(self.clave, payload)
        if not ok:
            self.rechazados += 1
            if self._avisos_rechazo < 5:
                self._avisos_rechazo += 1
                self.log("[mqtt] mensaje descartado en %s: %s" % (topic, motivo))
            return
        self.recibidos += 1
        if self._al_recibir is not None:
            self._al_recibir(topic, obj, retenido)
