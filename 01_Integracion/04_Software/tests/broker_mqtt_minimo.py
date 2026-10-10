# -*- coding: utf-8 -*-
"""
tests/broker_mqtt_minimo.py — Broker MQTT 3.1.1 mínimo en Python puro (asyncio, solo biblioteca estándar).

Qué hace:
    Acepta clientes MQTT por TCP y reparte sus PUBLISH entre los suscriptores cuyos filtros coincidan.
    Implementa el subconjunto de la especificación OASIS MQTT 3.1.1 que usa el transporte MQTT del
    enlace puente ⇄ servidor del gemelo (core/enlace_mqtt.py): CONNECT con usuario/clave y last will,
    PUBLISH con QoS 0 y 1 (PUBACK), bandera retain, SUBSCRIBE/UNSUBSCRIBE con comodines ``+`` y ``#``,
    PINGREQ/PINGRESP y DISCONNECT. Lleva contadores (``publicados``, ``conexiones``) y una cola
    ``ultimos`` con los últimos 200 mensajes para que las pruebas hagan aserciones sin otro cliente.

Para qué se usa:
    Para que las pruebas pytest del proyecto comprueben el transporte MQTT sin instalar Mosquitto ni
    depender de un broker en internet. También se puede arrancar a mano para probar el puente y el
    servidor del gemelo en una sola PC::

        python -m tests.broker_mqtt_minimo --puerto 1883
        python -m tests.broker_mqtt_minimo --puerto 1883 --usuario puente --clave secreto

    No es un broker de producción: no hay TLS, ni WebSocket, ni persistencia, ni límites de clientes.

Qué NO cubre (a propósito):
    * QoS 2: un PUBLISH con QoS 2 se descarta y se cierra la conexión con un aviso en el log (se trata
      como desconexión anormal, así que se publica su will). El enlace del proyecto no usa QoS 2.
    * Sesiones persistentes (clean session = 0): se trata igual que clean session = 1; el CONNACK
      siempre dice "session present = 0" y las suscripciones mueren con la conexión.
    * Reintentos de entrega QoS 1 a los suscriptores: se envía una vez y se ignoran sus PUBACK.
    * Keepalive del lado del broker: no se cierra a un cliente que deja de enviar PINGREQ; la
      desconexión se detecta solo cuando el socket se cierra o falla una escritura.
    * Validación estricta de UTF-8 de los topics más allá de que decodifiquen.

Compatibilidad: Python 3.12 a 3.13.
En Windows, las pruebas fijan ``asyncio.WindowsSelectorEventLoopPolicy()`` antes de ``asyncio.run``;
el broker funciona con cualquiera de los dos bucles.
"""
from __future__ import annotations

import argparse
import asyncio
import collections
import struct
import sys
import uuid
from typing import Callable, Deque, Dict, Optional, Tuple

# ----------------------------------------------------------------------------------------------
# Constantes del protocolo (sección 2.2.1 de la especificación: tipo de paquete en los 4 bits altos)
# ----------------------------------------------------------------------------------------------
CONNECT = 1
CONNACK = 2
PUBLISH = 3
PUBACK = 4
PUBREC = 5
PUBREL = 6
PUBCOMP = 7
SUBSCRIBE = 8
SUBACK = 9
UNSUBSCRIBE = 10
UNSUBACK = 11
PINGREQ = 12
PINGRESP = 13
DISCONNECT = 14

NOMBRES_PAQUETE = {
    CONNECT: "CONNECT", CONNACK: "CONNACK", PUBLISH: "PUBLISH", PUBACK: "PUBACK", PUBREC: "PUBREC",
    PUBREL: "PUBREL", PUBCOMP: "PUBCOMP", SUBSCRIBE: "SUBSCRIBE", SUBACK: "SUBACK",
    UNSUBSCRIBE: "UNSUBSCRIBE", UNSUBACK: "UNSUBACK", PINGREQ: "PINGREQ", PINGRESP: "PINGRESP",
    DISCONNECT: "DISCONNECT",
}

# Códigos de retorno del CONNACK (sección 3.2.2.3)
CONNACK_ACEPTADA = 0
CONNACK_PROTOCOLO = 1          # versión de protocolo no aceptable
CONNACK_ID_RECHAZADO = 2
CONNACK_SERVIDOR_NO_DISPONIBLE = 3
CONNACK_CREDENCIALES = 4       # usuario o clave incorrectos
CONNACK_NO_AUTORIZADO = 5

MAX_PAQUETE = 8 * 1024 * 1024  # 8 MB; por encima se cierra la conexión
MAX_ULTIMOS = 200

Will = Tuple[str, bytes, int, bool]  # (topic, payload, qos, retain)


class ErrorProtocolo(Exception):
    """Paquete malformado o fuera de lugar: el broker cierra la conexión (sección 4.8)."""


# ----------------------------------------------------------------------------------------------
# Codificación / decodificación de los tipos básicos (sección 1.5)
# ----------------------------------------------------------------------------------------------
def codificar_longitud(n: int) -> bytes:
    """Entero de longitud variable (1 a 4 bytes, 7 bits útiles por byte) de la cabecera fija."""
    if n < 0 or n > 268435455:
        raise ErrorProtocolo("longitud restante fuera de rango: %d" % n)
    salida = bytearray()
    while True:
        byte, n = n % 128, n // 128
        if n > 0:
            byte |= 0x80
        salida.append(byte)
        if n == 0:
            return bytes(salida)


def codificar_cadena(texto: str) -> bytes:
    """Cadena UTF-8 con prefijo de longitud de 2 bytes (big-endian)."""
    datos = texto.encode("utf-8")
    if len(datos) > 65535:
        raise ErrorProtocolo("cadena demasiado larga")
    return struct.pack("!H", len(datos)) + datos


def leer_binario(buf: bytes, pos: int) -> Tuple[bytes, int]:
    """Campo con prefijo de longitud de 2 bytes. Devuelve (bytes, nueva posición)."""
    if pos + 2 > len(buf):
        raise ErrorProtocolo("campo truncado (falta la longitud)")
    (n,) = struct.unpack_from("!H", buf, pos)
    pos += 2
    if pos + n > len(buf):
        raise ErrorProtocolo("campo truncado (faltan %d bytes)" % (pos + n - len(buf)))
    return bytes(buf[pos:pos + n]), pos + n


def leer_cadena(buf: bytes, pos: int) -> Tuple[str, int]:
    """Cadena UTF-8 con prefijo de longitud. Un UTF-8 inválido es error de protocolo (sección 1.5.3)."""
    datos, pos = leer_binario(buf, pos)
    try:
        return datos.decode("utf-8"), pos
    except UnicodeDecodeError:
        raise ErrorProtocolo("cadena con UTF-8 inválido")


def leer_u16(buf: bytes, pos: int) -> Tuple[int, int]:
    if pos + 2 > len(buf):
        raise ErrorProtocolo("entero de 16 bits truncado")
    return struct.unpack_from("!H", buf, pos)[0], pos + 2


# ----------------------------------------------------------------------------------------------
# Topics y filtros (sección 4.7)
# ----------------------------------------------------------------------------------------------
def filtro_valido(filtro: str) -> bool:
    """``+`` debe ocupar un nivel completo; ``#`` solo puede ir al final y ocupando su nivel."""
    if not filtro:
        return False
    niveles = filtro.split("/")
    for i, nivel in enumerate(niveles):
        if "#" in nivel and (nivel != "#" or i != len(niveles) - 1):
            return False
        if "+" in nivel and nivel != "+":
            return False
    return True


def topic_valido(topic: str) -> bool:
    """Un topic de PUBLISH no lleva comodines ni puede estar vacío."""
    return bool(topic) and "+" not in topic and "#" not in topic


def coincide(filtro: str, topic: str) -> bool:
    """¿El filtro (con ``+``/``#``) casa con el topic?

    Regla 4.7.2: los topics que empiezan por ``$`` no casan con filtros que empiezan por comodín
    (``#`` o ``+/...``); hay que suscribirse a ``$SYS/...`` explícitamente.
    """
    if topic.startswith("$") and (filtro.startswith("#") or filtro.startswith("+")):
        return False
    nf = filtro.split("/")
    nt = topic.split("/")
    for i, f in enumerate(nf):
        if f == "#":
            return True  # cubre el resto, incluido el nivel padre: "a/#" casa con "a" y con "a/b/c"
        if i >= len(nt):
            return False
        if f != "+" and f != nt[i]:
            return False
    return len(nf) == len(nt)


# ----------------------------------------------------------------------------------------------
# Estado de cada cliente conectado
# ----------------------------------------------------------------------------------------------
class _Cliente(object):
    """Una conexión TCP: su tarea de lectura, su writer y lo que el broker recuerda de ella."""

    def __init__(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        self.reader = reader
        self.writer = writer
        self.id = ""                                   # client id (se rellena en el CONNECT)
        self.suscripciones = {}                        # type: Dict[str, int]  filtro -> QoS concedido
        self.will = None                               # type: Optional[Will]
        self.tarea = None                              # type: Optional[asyncio.Task]
        self.candado = None                            # type: Optional[asyncio.Lock]  serializa write+drain
        self.siguiente_pid = 1                         # packet id creciente para PUBLISH QoS 1 salientes
        self.cerrado = False
        # Por qué terminó la conexión: "limpio" (DISCONNECT), "reemplazado" (otro CONNECT con el
        # mismo id), "parada" (parar() del broker) o "anormal" (EOF, error de protocolo, fallo de red).
        self.motivo = "anormal"
        self.conectado = False                         # ya pasó el CONNECT con éxito

    def pid(self) -> int:
        """Siguiente packet id (1..65535, nunca 0)."""
        p = self.siguiente_pid
        self.siguiente_pid = p + 1 if p < 65535 else 1
        return p

    def direccion(self) -> str:
        try:
            par = self.writer.get_extra_info("peername")
            return "%s:%s" % (par[0], par[1]) if par else "?"
        except Exception:
            return "?"


# ----------------------------------------------------------------------------------------------
# El broker
# ----------------------------------------------------------------------------------------------
class BrokerMinimo(object):
    """Broker MQTT 3.1.1 mínimo para pruebas.

    Parámetros:
        host, puerto: dónde escuchar. ``puerto=0`` pide un puerto efímero; el real queda en ``puerto``
            tras ``arrancar()``.
        usuarios: dict usuario -> clave. ``None`` acepta cualquier CONNECT (con o sin credenciales).
        log: callable que recibe una cadena, o ``None`` para callar.

    Atributos para aserciones:
        retenidos: dict topic -> payload (bytes) de los mensajes retenidos vigentes.
        publicados: número de paquetes PUBLISH recibidos de los clientes (no cuenta los wills).
        conexiones: número de CONNECT aceptados.
        pings: número de PINGREQ atendidos.
        ultimos: deque con los últimos 200 (topic, payload) repartidos, wills incluidos.
    """

    def __init__(self, host: str = "127.0.0.1", puerto: int = 0,
                 usuarios: Optional[Dict[str, str]] = None,
                 log: Optional[Callable[[str], None]] = None) -> None:
        self.host = host
        self._puerto_pedido = int(puerto)
        self._puerto = 0
        self.usuarios = dict(usuarios) if usuarios is not None else None
        self._log = log
        self.retenidos = {}                            # type: Dict[str, bytes]
        self._qos_retenidos = {}                       # type: Dict[str, int]
        self.publicados = 0
        self.conexiones = 0
        self.pings = 0
        self.ultimos = collections.deque(maxlen=MAX_ULTIMOS)  # type: Deque[Tuple[str, bytes]]
        self._clientes = {}                            # type: Dict[str, _Cliente]  client id -> cliente
        self._tareas = set()                           # type: set
        self._servidor = None                          # type: Optional[asyncio.AbstractServer]
        self._parando = False

    # -- ciclo de vida --------------------------------------------------------------------------

    @property
    def puerto(self) -> int:
        """Puerto real en el que escucha (0 antes de ``arrancar()``)."""
        return self._puerto

    async def arrancar(self) -> int:
        """Abre el servidor TCP y devuelve el puerto real."""
        self._parando = False
        self._servidor = await asyncio.start_server(self._atender, self.host, self._puerto_pedido)
        self._puerto = self._servidor.sockets[0].getsockname()[1]
        self.log("[broker] escuchando en %s:%d" % (self.host, self._puerto))
        return self._puerto

    async def parar(self) -> None:
        """Cierra el servidor y todos los clientes; espera a que terminen sus tareas."""
        self._parando = True
        if self._servidor is not None:
            self._servidor.close()
        for c in list(self._clientes.values()):
            c.motivo = "parada"
            self._cerrar(c)
        tareas = [t for t in self._tareas if not t.done()]
        for t in tareas:
            t.cancel()
        if tareas:
            await asyncio.gather(*tareas, return_exceptions=True)
        self._tareas.clear()
        self._clientes.clear()
        if self._servidor is not None:
            try:
                await self._servidor.wait_closed()
            except Exception:
                pass
            self._servidor = None
        self.log("[broker] parado")

    def log(self, texto: str) -> None:
        if self._log is not None:
            try:
                self._log(texto)
            except Exception:
                pass

    # -- una conexión ---------------------------------------------------------------------------

    async def _atender(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        """Tarea de un cliente: CONNECT, bucle de paquetes y limpieza (will incluido)."""
        c = _Cliente(reader, writer)
        c.tarea = asyncio.current_task()
        c.candado = asyncio.Lock()
        self._tareas.add(c.tarea)
        cancelado = False
        try:
            await self._bucle(c)  # sale sin excepción solo con DISCONNECT (motivo "limpio") o tras un rechazo
        except asyncio.CancelledError:
            # Cancelado por parar(), por un reemplazo o por un fallo de escritura desde otra tarea:
            # el motivo ya está puesto ("parada", "reemplazado" o "anormal"). Se limpia en el finally
            # y se vuelve a lanzar para que la tarea quede cancelada, como espera quien la canceló.
            cancelado = True
        except ErrorProtocolo as e:
            self.log("[broker] %s (%s): error de protocolo, se cierra: %s" % (c.id or "?", c.direccion(), e))
        except (asyncio.IncompleteReadError, ConnectionError, OSError) as e:
            if c.motivo == "anormal":
                self.log("[broker] %s (%s): conexión perdida (%s)" % (c.id or "?", c.direccion(),
                                                                       type(e).__name__))
        except Exception as e:  # cualquier otra cosa también cuenta como desconexión anormal
            self.log("[broker] %s (%s): excepción inesperada: %r" % (c.id or "?", c.direccion(), e))
        finally:
            await self._despedir(c)
            self._tareas.discard(c.tarea)
        if cancelado:
            raise asyncio.CancelledError()

    async def _despedir(self, c: _Cliente) -> None:
        """Da de baja al cliente, cierra su socket y publica su will si la desconexión fue anormal."""
        if self._clientes.get(c.id) is c:
            del self._clientes[c.id]
        will = c.will
        c.will = None
        publicar_will = (will is not None and c.conectado and not self._parando
                         and c.motivo == "anormal")
        self._cerrar(c)
        try:
            await asyncio.wait_for(c.writer.wait_closed(), 1.0)
        except Exception:
            pass
        if publicar_will:
            topic, payload, qos, retain = will
            self.log("[broker] %s: desconexión anormal, se publica su will en %s" % (c.id, topic))
            await self._distribuir(topic, payload, qos, retain)
        elif c.conectado and c.motivo == "limpio":
            self.log("[broker] %s: DISCONNECT" % c.id)

    def _cerrar(self, c: _Cliente) -> None:
        """Marca al cliente como cerrado, cierra su transporte y cancela su tarea (si no es la actual)."""
        if c.cerrado:
            return
        c.cerrado = True
        try:
            c.writer.close()
        except Exception:
            pass
        if c.tarea is not None and not c.tarea.done() and c.tarea is not asyncio.current_task():
            c.tarea.cancel()

    async def _leer_paquete(self, reader: asyncio.StreamReader) -> Tuple[int, int, bytes]:
        """Lee un paquete completo: (tipo, banderas, resto). Lanza IncompleteReadError al cerrarse el socket."""
        (b0,) = await reader.readexactly(1)
        tipo, banderas = b0 >> 4, b0 & 0x0F
        longitud, factor = 0, 1
        for _ in range(4):
            (b,) = await reader.readexactly(1)
            longitud += (b & 0x7F) * factor
            factor *= 128
            if not (b & 0x80):
                break
        else:
            raise ErrorProtocolo("longitud restante malformada (más de 4 bytes)")
        if longitud > MAX_PAQUETE:
            raise ErrorProtocolo("paquete de %d bytes supera el máximo de %d" % (longitud, MAX_PAQUETE))
        resto = await reader.readexactly(longitud) if longitud else b""
        return tipo, banderas, resto

    async def _enviar(self, c: _Cliente, datos: bytes) -> bool:
        """Escribe y hace drain bajo el candado del cliente. Un fallo cierra solo a ese cliente."""
        if c.cerrado:
            return False
        try:
            async with c.candado:
                if c.cerrado:
                    return False
                c.writer.write(datos)
                await c.writer.drain()
            return True
        except (ConnectionError, OSError, RuntimeError) as e:
            # RuntimeError: "unable to perform operation on closed transport" en algunas versiones
            self.log("[broker] %s: fallo al escribir (%s), se cierra" % (c.id or "?", type(e).__name__))
            self._cerrar(c)
            return False

    async def _bucle(self, c: _Cliente) -> None:
        """Primero un CONNECT; después paquetes hasta DISCONNECT, EOF o error."""
        tipo, banderas, resto = await self._leer_paquete(c.reader)
        if tipo != CONNECT:
            raise ErrorProtocolo("el primer paquete debe ser CONNECT, llegó %s" % NOMBRES_PAQUETE.get(tipo, tipo))
        if not await self._procesar_connect(c, resto):
            return  # CONNACK de rechazo ya enviado; cerrar sin will (nunca estuvo conectado)

        while not c.cerrado:
            tipo, banderas, resto = await self._leer_paquete(c.reader)
            if tipo == PUBLISH:
                await self._procesar_publish(c, banderas, resto)
            elif tipo == PUBACK:
                pass  # confirmación de un QoS 1 que entregamos; sin reintentos, se ignora
            elif tipo == SUBSCRIBE:
                if banderas != 0x02:
                    raise ErrorProtocolo("SUBSCRIBE con banderas %#x" % banderas)
                await self._procesar_subscribe(c, resto)
            elif tipo == UNSUBSCRIBE:
                if banderas != 0x02:
                    raise ErrorProtocolo("UNSUBSCRIBE con banderas %#x" % banderas)
                await self._procesar_unsubscribe(c, resto)
            elif tipo == PINGREQ:
                self.pings += 1
                await self._enviar(c, bytes([PINGRESP << 4, 0]))
            elif tipo == DISCONNECT:
                c.motivo = "limpio"
                return
            elif tipo == CONNECT:
                raise ErrorProtocolo("segundo CONNECT en la misma conexión")
            elif tipo in (PUBREC, PUBREL, PUBCOMP):
                pass  # restos de QoS 2; no se soporta, se ignoran
            else:
                raise ErrorProtocolo("tipo de paquete desconocido %d" % tipo)

    # -- CONNECT ---------------------------------------------------------------------------------

    async def _procesar_connect(self, c: _Cliente, resto: bytes) -> bool:
        """Valida el CONNECT, autentica y registra al cliente. Devuelve False si se rechazó."""
        pos = 0
        nombre, pos = leer_cadena(resto, pos)
        if pos >= len(resto):
            raise ErrorProtocolo("CONNECT truncado")
        nivel = resto[pos]
        pos += 1
        if nombre != "MQTT" or nivel != 4:
            self.log("[broker] CONNECT rechazado: protocolo %r nivel %d (solo MQTT 3.1.1)" % (nombre, nivel))
            await self._enviar(c, bytes([CONNACK << 4, 2, 0, CONNACK_PROTOCOLO]))
            return False
        if pos >= len(resto):
            raise ErrorProtocolo("CONNECT sin banderas")
        banderas = resto[pos]
        pos += 1
        if banderas & 0x01:
            raise ErrorProtocolo("bit reservado del CONNECT distinto de 0")
        # clean_session = bool(banderas & 0x02): solo se soporta sesión limpia; se trata igual
        con_will = bool(banderas & 0x04)
        will_qos = (banderas >> 3) & 0x03
        will_retain = bool(banderas & 0x20)
        con_clave = bool(banderas & 0x40)
        con_usuario = bool(banderas & 0x80)
        if not con_will and (will_qos or will_retain):
            raise ErrorProtocolo("banderas de will sin will flag")
        if will_qos == 3:
            raise ErrorProtocolo("will QoS 3")
        if con_clave and not con_usuario:
            raise ErrorProtocolo("password flag sin username flag")
        _keepalive, pos = leer_u16(resto, pos)

        # Carga útil: client id, [will topic, will message], [usuario], [clave]
        client_id, pos = leer_cadena(resto, pos)
        will = None  # type: Optional[Will]
        if con_will:
            will_topic, pos = leer_cadena(resto, pos)
            will_msg, pos = leer_binario(resto, pos)
            if not topic_valido(will_topic):
                raise ErrorProtocolo("will topic inválido %r" % will_topic)
            will = (will_topic, will_msg, min(will_qos, 1), will_retain)
        usuario = None  # type: Optional[str]
        clave = None    # type: Optional[bytes]
        if con_usuario:
            usuario, pos = leer_cadena(resto, pos)
        if con_clave:
            clave, pos = leer_binario(resto, pos)
        if pos != len(resto):
            raise ErrorProtocolo("CONNECT con %d bytes sobrantes" % (len(resto) - pos))

        if self.usuarios is not None:
            esperada = self.usuarios.get(usuario) if usuario is not None else None
            if esperada is None or clave is None or clave != esperada.encode("utf-8"):
                self.log("[broker] CONNECT de %r rechazado: usuario o clave incorrectos" % (client_id or usuario))
                await self._enviar(c, bytes([CONNACK << 4, 2, 0, CONNACK_CREDENCIALES]))
                return False

        if not client_id:
            client_id = "auto-" + uuid.uuid4().hex[:12]
        viejo = self._clientes.get(client_id)
        if viejo is not None and viejo is not c:
            # Sección 3.1.4: el servidor desconecta al cliente existente con el mismo id. Su will no
            # se publica (no fue una pérdida de red sino una sustitución).
            self.log("[broker] %s: CONNECT repetido, se cierra la conexión anterior" % client_id)
            viejo.motivo = "reemplazado"
            self._cerrar(viejo)
        c.id = client_id
        c.will = will
        self._clientes[client_id] = c
        if not await self._enviar(c, bytes([CONNACK << 4, 2, 0, CONNACK_ACEPTADA])):
            return False
        c.conectado = True
        self.conexiones += 1
        self.log("[broker] %s conectado desde %s%s" % (client_id, c.direccion(),
                                                       " con will en %s" % will[0] if will else ""))
        return True

    # -- PUBLISH ---------------------------------------------------------------------------------

    async def _procesar_publish(self, c: _Cliente, banderas: int, resto: bytes) -> None:
        qos = (banderas >> 1) & 0x03
        retain = bool(banderas & 0x01)
        if qos == 3:
            raise ErrorProtocolo("PUBLISH con QoS 3")
        pos = 0
        topic, pos = leer_cadena(resto, pos)
        if not topic_valido(topic):
            raise ErrorProtocolo("topic de PUBLISH inválido %r" % topic)
        pid = None
        if qos > 0:
            pid, pos = leer_u16(resto, pos)
            if pid == 0:
                raise ErrorProtocolo("PUBLISH QoS %d con packet id 0" % qos)
        payload = bytes(resto[pos:])
        if qos == 2:
            # Documentado en la cabecera: QoS 2 no se soporta. Se descarta sin repartir (el cliente
            # lo reenviaría con DUP al reconectar) y se cierra la conexión como desconexión anormal.
            self.log("[broker] %s: PUBLISH QoS 2 en %s no soportado, se cierra la conexión" % (c.id, topic))
            raise ErrorProtocolo("QoS 2 no soportado")
        self.publicados += 1
        await self._distribuir(topic, payload, qos, retain)
        if qos == 1:
            await self._enviar(c, bytes([PUBACK << 4, 2]) + struct.pack("!H", pid))

    async def _distribuir(self, topic: str, payload: bytes, qos: int, retain: bool) -> None:
        """Guarda/borra el retenido si procede y reenvía a cada suscriptor con QoS = min(suscripción, mensaje)."""
        self.ultimos.append((topic, payload))
        if retain:
            if payload:
                self.retenidos[topic] = payload
                self._qos_retenidos[topic] = qos
            else:
                # Sección 3.3.1.3: retain con payload vacío borra el retenido y no se guarda
                self.retenidos.pop(topic, None)
                self._qos_retenidos.pop(topic, None)
        for destino in list(self._clientes.values()):
            if destino.cerrado or not destino.conectado:
                continue
            qos_sus = -1
            for filtro, q in destino.suscripciones.items():
                if q > qos_sus and coincide(filtro, topic):
                    qos_sus = q
            if qos_sus < 0:
                continue
            # Al reenviar, la bandera retain va a 0 (solo va a 1 al entregar retenidos a una suscripción nueva)
            await self._enviar_publish(destino, topic, payload, min(qos_sus, qos), retain=False)

    async def _enviar_publish(self, c: _Cliente, topic: str, payload: bytes, qos: int, retain: bool) -> bool:
        b0 = (PUBLISH << 4) | (qos << 1) | (1 if retain else 0)
        variable = codificar_cadena(topic)
        if qos > 0:
            variable += struct.pack("!H", c.pid())
        cuerpo = variable + payload
        return await self._enviar(c, bytes([b0]) + codificar_longitud(len(cuerpo)) + cuerpo)

    # -- SUBSCRIBE / UNSUBSCRIBE -----------------------------------------------------------------

    async def _procesar_subscribe(self, c: _Cliente, resto: bytes) -> None:
        pos = 0
        pid, pos = leer_u16(resto, pos)
        if pid == 0:
            raise ErrorProtocolo("SUBSCRIBE con packet id 0")
        pedidos = []  # type: list
        while pos < len(resto):
            filtro, pos = leer_cadena(resto, pos)
            if pos >= len(resto):
                raise ErrorProtocolo("SUBSCRIBE sin QoS para %r" % filtro)
            qos_byte = resto[pos]
            pos += 1
            if qos_byte & 0xFC:
                raise ErrorProtocolo("SUBSCRIBE con byte de QoS %#x" % qos_byte)
            if qos_byte == 3:
                raise ErrorProtocolo("SUBSCRIBE con QoS 3")
            pedidos.append((filtro, qos_byte))
        if not pedidos:
            raise ErrorProtocolo("SUBSCRIBE sin filtros")

        codigos = bytearray()
        nuevos = []  # type: list
        for filtro, qos_pedido in pedidos:
            if not filtro_valido(filtro):
                codigos.append(0x80)  # fallo para ese filtro (sección 3.9.3)
                self.log("[broker] %s: filtro inválido %r" % (c.id, filtro))
                continue
            concedido = min(qos_pedido, 1)
            c.suscripciones[filtro] = concedido
            codigos.append(concedido)
            nuevos.append((filtro, concedido))
        cuerpo = struct.pack("!H", pid) + bytes(codigos)
        if not await self._enviar(c, bytes([SUBACK << 4]) + codificar_longitud(len(cuerpo)) + cuerpo):
            return
        self.log("[broker] %s: SUBSCRIBE %s" % (c.id, ", ".join("%s (QoS %d)" % n for n in nuevos) or "ninguno válido"))

        # Entrega de retenidos a la suscripción nueva (sección 3.3.1.3), con retain = 1
        for filtro, concedido in nuevos:
            for topic in list(self.retenidos.keys()):
                if coincide(filtro, topic):
                    payload = self.retenidos.get(topic)
                    if payload is None:
                        continue
                    qos = min(concedido, self._qos_retenidos.get(topic, 0))
                    if not await self._enviar_publish(c, topic, payload, qos, retain=True):
                        return

    async def _procesar_unsubscribe(self, c: _Cliente, resto: bytes) -> None:
        pos = 0
        pid, pos = leer_u16(resto, pos)
        if pid == 0:
            raise ErrorProtocolo("UNSUBSCRIBE con packet id 0")
        filtros = []  # type: list
        while pos < len(resto):
            filtro, pos = leer_cadena(resto, pos)
            filtros.append(filtro)
        if not filtros:
            raise ErrorProtocolo("UNSUBSCRIBE sin filtros")
        for filtro in filtros:
            c.suscripciones.pop(filtro, None)
        await self._enviar(c, bytes([UNSUBACK << 4, 2]) + struct.pack("!H", pid))
        self.log("[broker] %s: UNSUBSCRIBE %s" % (c.id, ", ".join(filtros)))


# ----------------------------------------------------------------------------------------------
# Uso a mano
# ----------------------------------------------------------------------------------------------
async def servir(puerto: int, usuarios: Optional[Dict[str, str]] = None, host: str = "127.0.0.1") -> None:
    """Arranca el broker y lo deja corriendo hasta que se cancele (Ctrl+C en consola)."""
    broker = BrokerMinimo(host=host, puerto=puerto, usuarios=usuarios, log=print)
    await broker.arrancar()
    try:
        await asyncio.Event().wait()
    finally:
        await broker.parar()


def _main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Broker MQTT 3.1.1 mínimo para pruebas (solo biblioteca estándar).")
    ap.add_argument("--host", default="127.0.0.1", help="interfaz en la que escuchar (por defecto 127.0.0.1)")
    ap.add_argument("--puerto", type=int, default=1883, help="puerto TCP (por defecto 1883)")
    ap.add_argument("--usuario", default=None, help="si se da, solo se acepta este usuario")
    ap.add_argument("--clave", default=None, help="clave del usuario anterior")
    args = ap.parse_args(argv)
    usuarios = None
    if args.usuario is not None:
        usuarios = {args.usuario: args.clave or ""}
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    try:
        asyncio.run(servir(args.puerto, usuarios, args.host))
    except KeyboardInterrupt:
        print("[broker] interrumpido")
    return 0


if __name__ == "__main__":
    sys.exit(_main())
