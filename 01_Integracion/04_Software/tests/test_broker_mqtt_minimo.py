# -*- coding: utf-8 -*-
"""Pruebas del broker MQTT mínimo (tests/broker_mqtt_minimo.py) con clientes paho-mqtt 2.x reales.

El broker corre en el bucle asyncio de la prueba (misma forma que tests/test_gemelo_local.py:
``asyncio.run`` con la política de selector en Windows). Los clientes paho van en sus propios hilos
(``loop_start``), así que la espera de sus callbacks se hace con ``run_in_executor`` para no bloquear
el bucle donde vive el broker. Lo que paho no deja controlar (cerrar el socket sin DISCONNECT para
disparar el will, CONNECT malformados) se hace con sockets TCP crudos construyendo los paquetes a mano.
"""
import asyncio
import queue
import socket
import struct
import sys
import threading
import time

import pytest

mqtt = pytest.importorskip("paho.mqtt.client")

from tests.broker_mqtt_minimo import (  # noqa: E402
    BrokerMinimo, coincide, codificar_cadena, codificar_longitud, filtro_valido,
)

HOST = "127.0.0.1"
ESPERA = 5.0  # segundos máximos para cada callback de paho


# ----------------------------------------------------------------------------------------------
# Utilidades
# ----------------------------------------------------------------------------------------------
async def en_hilo(fn, *args):
    """Ejecuta una función bloqueante fuera del bucle (el broker vive en el bucle y debe seguir girando)."""
    return await asyncio.get_running_loop().run_in_executor(None, fn, *args)


class Paho(object):
    """Cliente paho 2.x con eventos para esperar sus callbacks desde una corrutina."""

    def __init__(self, puerto, client_id="", usuario=None, clave=None, keepalive=60, will=None):
        self.c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=client_id, protocol=mqtt.MQTTv311)
        self.conectado = threading.Event()
        self.desconectado = threading.Event()
        self.suscrito = threading.Event()
        self.codigo = None                   # ReasonCode del último CONNACK
        self.codigo_desconexion = None
        self.mensajes = queue.Queue()        # (topic, payload, qos, retain)
        self.c.on_connect = self._on_connect
        self.c.on_disconnect = self._on_disconnect
        self.c.on_subscribe = self._on_subscribe
        self.c.on_message = self._on_message
        if usuario is not None:
            self.c.username_pw_set(usuario, clave)
        if will is not None:
            topic, payload, qos, retain = will
            self.c.will_set(topic, payload, qos=qos, retain=retain)
        self.c.connect_async(HOST, puerto, keepalive)
        self.c.loop_start()

    # callbacks (hilo de paho)
    def _on_connect(self, client, userdata, flags, reason_code, properties):
        self.codigo = reason_code
        self.conectado.set()

    def _on_disconnect(self, client, userdata, flags, reason_code, properties):
        self.codigo_desconexion = reason_code
        self.desconectado.set()

    def _on_subscribe(self, client, userdata, mid, reason_codes, properties):
        self.codigos_suback = [rc.value for rc in reason_codes]
        self.suscrito.set()

    def _on_message(self, client, userdata, msg):
        self.mensajes.put((msg.topic, bytes(msg.payload), msg.qos, bool(msg.retain)))

    # ayudas (corrutinas)
    async def esperar_conexion(self, timeout=ESPERA):
        assert await en_hilo(self.conectado.wait, timeout), "paho no recibió CONNACK"
        return self.codigo

    async def suscribir(self, filtro, qos=0):
        self.suscrito.clear()
        self.c.subscribe(filtro, qos)
        assert await en_hilo(self.suscrito.wait, ESPERA), "sin SUBACK para %s" % filtro
        return self.codigos_suback

    async def recibir(self, timeout=ESPERA):
        """Siguiente mensaje o None si no llega nada en `timeout` segundos."""
        def tomar():
            try:
                return self.mensajes.get(timeout=timeout)
            except queue.Empty:
                return None
        return await en_hilo(tomar)

    async def publicar(self, topic, payload, qos=0, retain=False):
        info = self.c.publish(topic, payload, qos=qos, retain=retain)
        await en_hilo(info.wait_for_publish, 2.0)
        assert info.is_published(), "PUBLISH QoS %d sin confirmar (%s)" % (qos, topic)
        return info

    def cerrar(self, despedida=True):
        if despedida:
            self.c.disconnect()
        self.c.loop_stop()


def connect_crudo(client_id, will=None, keepalive=60, protocolo="MQTT", nivel=4):
    """Paquete CONNECT a mano. will = (topic, payload, qos, retain) o None."""
    banderas = 0x02  # clean session
    carga = codificar_cadena(client_id)
    if will is not None:
        topic, payload, qos, retain = will
        banderas |= 0x04 | (qos << 3) | (0x20 if retain else 0)
        carga += codificar_cadena(topic) + struct.pack("!H", len(payload)) + payload
    variable = codificar_cadena(protocolo) + bytes([nivel, banderas]) + struct.pack("!H", keepalive)
    resto = variable + carga
    return bytes([0x10]) + codificar_longitud(len(resto)) + resto


def abrir_socket(puerto):
    s = socket.create_connection((HOST, puerto), timeout=ESPERA)
    return s


def recibir_todo(s, n, timeout=ESPERA):
    """Lee hasta n bytes o hasta que el otro lado cierre; devuelve lo leído (b"" si cerró de inmediato)."""
    s.settimeout(timeout)
    datos = b""
    try:
        while len(datos) < n:
            trozo = s.recv(n - len(datos))
            if not trozo:
                break
            datos += trozo
    except socket.timeout:
        pass
    return datos


def correr(escenario, **kw):
    """Arranca un broker en un bucle nuevo, ejecuta `escenario(broker, puerto)` y lo para siempre."""
    registro = []

    async def _con_broker():
        broker = BrokerMinimo(host=HOST, puerto=0, log=registro.append, **kw)
        puerto = await broker.arrancar()
        assert puerto > 0 and broker.puerto == puerto
        try:
            await escenario(broker, puerto)
        finally:
            await broker.parar()
            # parar() no debe dejar tareas colgadas en el bucle
            pendientes = [t for t in asyncio.all_tasks() if t is not asyncio.current_task() and not t.done()]
            assert not pendientes, pendientes
        return broker

    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    broker = asyncio.run(_con_broker())
    return broker, registro


# ----------------------------------------------------------------------------------------------
# Funciones puras
# ----------------------------------------------------------------------------------------------
def test_coincidencia_de_filtros():
    assert coincide("scada/+/snap", "scada/estacion/snap")
    assert not coincide("scada/+/snap", "scada/estacion/otra/snap")
    assert coincide("scada/#", "scada/estacion/snap")
    assert coincide("scada/#", "scada")                 # '#' cubre también el nivel padre
    assert coincide("#", "a/b/c")
    assert coincide("+/+", "a/b") and not coincide("+/+", "a")
    assert coincide("a/b", "a/b") and not coincide("a/b", "a/B")
    # topics que empiezan por '$' no casan con comodines iniciales
    assert not coincide("#", "$SYS/broker/uptime")
    assert not coincide("+/broker/uptime", "$SYS/broker/uptime")
    assert coincide("$SYS/#", "$SYS/broker/uptime")
    # validez de filtros
    assert filtro_valido("a/+/b") and filtro_valido("a/#") and filtro_valido("#") and filtro_valido("+")
    assert not filtro_valido("a/#/b") and not filtro_valido("a#") and not filtro_valido("a+/b") and not filtro_valido("")


def test_longitud_variable():
    assert codificar_longitud(0) == b"\x00"
    assert codificar_longitud(127) == b"\x7f"
    assert codificar_longitud(128) == b"\x80\x01"
    assert codificar_longitud(16383) == b"\xff\x7f"
    assert codificar_longitud(268435455) == b"\xff\xff\xff\x7f"


# ----------------------------------------------------------------------------------------------
# 1. Publicar y suscribir con comodín, QoS 0 y QoS 1
# ----------------------------------------------------------------------------------------------
def test_publicar_y_suscribir():
    async def escenario(broker, puerto):
        sub = Paho(puerto, "sub-1")
        pub = Paho(puerto, "pub-1")
        try:
            assert not (await sub.esperar_conexion()).is_failure
            assert not (await pub.esperar_conexion()).is_failure
            assert broker.conexiones == 2
            assert await sub.suscribir("scada/+/snap", qos=1) == [1]

            await pub.publicar("scada/estacion/snap", b"hola", qos=0)
            assert await sub.recibir() == ("scada/estacion/snap", b"hola", 0, False)

            # QoS 1: el publicador recibe su PUBACK (wait_for_publish) y el suscriptor lo recibe con QoS 1
            info = await pub.publicar("scada/estacion/snap", b"hola-1", qos=1)
            assert info.rc == mqtt.MQTT_ERR_SUCCESS
            assert await sub.recibir() == ("scada/estacion/snap", b"hola-1", 1, False)

            # un topic que no casa con el filtro no llega
            await pub.publicar("scada/estacion/evt", b"no", qos=0)
            assert await sub.recibir(timeout=0.5) is None

            # QoS de entrega = min(suscripción, mensaje): suscripción QoS 0 recibe el QoS 1 como QoS 0
            assert await sub.suscribir("scada/estacion/evt", qos=0) == [0]
            await pub.publicar("scada/estacion/evt", b"evt", qos=1)
            assert await sub.recibir() == ("scada/estacion/evt", b"evt", 0, False)

            assert broker.publicados == 4
            assert list(broker.ultimos)[-1] == ("scada/estacion/evt", b"evt")
        finally:
            sub.cerrar()
            pub.cerrar()

    correr(escenario)


# ----------------------------------------------------------------------------------------------
# 2. Retenidos
# ----------------------------------------------------------------------------------------------
def test_retenidos():
    async def escenario(broker, puerto):
        pub = Paho(puerto, "pub-ret")
        clientes = [pub]
        try:
            await pub.esperar_conexion()
            await pub.publicar("scada/estacion/estado", b"en-linea", qos=1, retain=True)
            assert broker.retenidos == {"scada/estacion/estado": b"en-linea"}

            # quien se suscribe DESPUÉS lo recibe con retain = True
            sub1 = Paho(puerto, "sub-ret-1")
            clientes.append(sub1)
            await sub1.esperar_conexion()
            await sub1.suscribir("scada/estacion/#", qos=1)
            assert await sub1.recibir() == ("scada/estacion/estado", b"en-linea", 1, True)

            # retain con payload vacío borra el retenido (y se reparte a los suscriptores vivos sin retain)
            await pub.publicar("scada/estacion/estado", b"", qos=1, retain=True)
            assert "scada/estacion/estado" not in broker.retenidos
            assert await sub1.recibir() == ("scada/estacion/estado", b"", 1, False)

            sub2 = Paho(puerto, "sub-ret-2")
            clientes.append(sub2)
            await sub2.esperar_conexion()
            await sub2.suscribir("scada/estacion/estado", qos=1)
            assert await sub2.recibir(timeout=0.7) is None
        finally:
            for c in clientes:
                c.cerrar()

    correr(escenario)


# ----------------------------------------------------------------------------------------------
# 3. Will: cierre brusco lo publica; DISCONNECT lo descarta; reemplazo de client id no lo publica
# ----------------------------------------------------------------------------------------------
def test_will_en_desconexion_brusca():
    async def escenario(broker, puerto):
        sub = Paho(puerto, "sub-will")
        try:
            await sub.esperar_conexion()
            await sub.suscribir("scada/estacion/estado", qos=1)

            will = ("scada/estacion/estado", b"adios", 1, True)
            s = await en_hilo(abrir_socket, puerto)
            await en_hilo(s.sendall, connect_crudo("crudo-will", will=will))
            assert await en_hilo(recibir_todo, s, 4) == b"\x20\x02\x00\x00"
            # cierre sin DISCONNECT -> desconexión anormal -> will
            await en_hilo(s.close)
            assert await sub.recibir() == ("scada/estacion/estado", b"adios", 1, False)
            assert broker.retenidos.get("scada/estacion/estado") == b"adios"
            assert ("scada/estacion/estado", b"adios") in broker.ultimos

            # DISCONNECT limpio: el will se descarta
            s2 = await en_hilo(abrir_socket, puerto)
            await en_hilo(s2.sendall, connect_crudo("crudo-limpio", will=("scada/estacion/estado", b"nunca", 0, False)))
            assert await en_hilo(recibir_todo, s2, 4) == b"\x20\x02\x00\x00"
            await en_hilo(s2.sendall, b"\xe0\x00")
            await en_hilo(s2.close)
            assert await sub.recibir(timeout=0.7) is None

            # Un segundo CONNECT con el mismo client id cierra al anterior sin publicar su will
            a = await en_hilo(abrir_socket, puerto)
            await en_hilo(a.sendall, connect_crudo("repetido", will=("scada/estacion/estado", b"nunca", 0, False)))
            assert await en_hilo(recibir_todo, a, 4) == b"\x20\x02\x00\x00"
            b = await en_hilo(abrir_socket, puerto)
            await en_hilo(b.sendall, connect_crudo("repetido"))
            assert await en_hilo(recibir_todo, b, 4) == b"\x20\x02\x00\x00"
            assert await en_hilo(recibir_todo, a, 1, 2.0) == b""     # el broker cerró la conexión vieja
            assert await sub.recibir(timeout=0.7) is None
            await en_hilo(a.close)
            await en_hilo(b.close)
        finally:
            sub.cerrar()

    broker, registro = correr(escenario)
    assert any("se publica su will" in r for r in registro)
    assert any("CONNECT repetido" in r for r in registro)


# ----------------------------------------------------------------------------------------------
# 4. Autenticación
# ----------------------------------------------------------------------------------------------
def test_autenticacion():
    async def escenario(broker, puerto):
        malo = Paho(puerto, "puente-malo", usuario="puente", clave="incorrecta")
        try:
            rc = await malo.esperar_conexion()
            # paho 2.x traduce el código 4 del CONNACK 3.1.1 a ReasonCode 134 "Bad user name or password"
            assert rc.is_failure
            assert "Bad user name or password" in str(rc)
        finally:
            malo.cerrar(despedida=False)  # paho reintenta solo tras un CONNACK de rechazo; se para el hilo
        sin_credenciales = Paho(puerto, "anonimo")
        try:
            assert (await sin_credenciales.esperar_conexion()).is_failure
        finally:
            sin_credenciales.cerrar(despedida=False)
        assert broker.conexiones == 0

        bueno = Paho(puerto, "puente", usuario="puente", clave="secreto")
        try:
            rc = await bueno.esperar_conexion()
            assert not rc.is_failure and rc.value == 0
            assert broker.conexiones == 1
            await bueno.publicar("scada/estacion/ping", b"1", qos=1)
        finally:
            bueno.cerrar()

    broker, registro = correr(escenario, usuarios={"puente": "secreto"})
    assert sum("usuario o clave incorrectos" in r for r in registro) >= 2


# ----------------------------------------------------------------------------------------------
# 5. PINGREQ / PINGRESP con keepalive de 1 s
# ----------------------------------------------------------------------------------------------
def test_pingreq_mantiene_la_conexion():
    async def escenario(broker, puerto):
        c = Paho(puerto, "ping-1", keepalive=1)
        try:
            await c.esperar_conexion()
            t0 = time.monotonic()
            while time.monotonic() - t0 < 3.5:
                await asyncio.sleep(0.25)
                assert not c.desconectado.is_set(), "paho se desconectó: el broker no contestó el PINGREQ"
            assert c.c.is_connected()
            assert broker.pings >= 1
            # y sigue funcionando después
            await c.suscribir("x/y", qos=0)
            await c.publicar("x/y", b"vivo", qos=1)
            assert await c.recibir() == ("x/y", b"vivo", 0, False)
        finally:
            c.cerrar()

    correr(escenario)


# ----------------------------------------------------------------------------------------------
# 6. parar() con clientes conectados; contadores y últimos mensajes
# ----------------------------------------------------------------------------------------------
def test_parar_y_contadores():
    clientes = []

    async def escenario(broker, puerto):
        a = Paho(puerto, "a")
        b = Paho(puerto, "b")
        clientes.extend([a, b])
        await a.esperar_conexion()
        await b.esperar_conexion()
        await b.suscribir("scada/#", qos=1)
        for i in range(3):
            await a.publicar("scada/estacion/snap", ("snap-%d" % i).encode(), qos=i % 2)
        for i in range(3):
            m = await b.recibir()
            assert m[0] == "scada/estacion/snap" and m[1] == ("snap-%d" % i).encode()
        assert broker.publicados == 3
        assert broker.conexiones == 2
        assert list(broker.ultimos) == [("scada/estacion/snap", ("snap-%d" % i).encode()) for i in range(3)]
        # se sale sin desconectar a los clientes: parar() debe cerrarlos él mismo

    broker, registro = correr(escenario)
    try:
        # los paho notaron el cierre del broker
        for c in clientes:
            assert c.desconectado.wait(ESPERA), "paho %s no vio el cierre del broker" % c
        assert registro[-1] == "[broker] parado"
        assert broker.publicados == 3 and broker.conexiones == 2
    finally:
        for c in clientes:
            c.cerrar(despedida=False)


# ----------------------------------------------------------------------------------------------
# 7. Rechazos de protocolo con sockets crudos
# ----------------------------------------------------------------------------------------------
def test_rechazos_de_protocolo():
    async def escenario(broker, puerto):
        # Protocolo distinto de MQTT nivel 4 -> CONNACK código 1 y cierre
        s = await en_hilo(abrir_socket, puerto)
        await en_hilo(s.sendall, connect_crudo("viejo", protocolo="MQIsdp", nivel=3))
        assert await en_hilo(recibir_todo, s, 4) == b"\x20\x02\x00\x01"
        assert await en_hilo(recibir_todo, s, 1, 2.0) == b""
        await en_hilo(s.close)

        # Paquete que anuncia más de 8 MB -> cierre sin respuesta
        s = await en_hilo(abrir_socket, puerto)
        await en_hilo(s.sendall, bytes([0x10]) + codificar_longitud(9 * 1024 * 1024))
        assert await en_hilo(recibir_todo, s, 1, 2.0) == b""
        await en_hilo(s.close)

        # El primer paquete debe ser CONNECT: un PINGREQ suelto cierra la conexión
        s = await en_hilo(abrir_socket, puerto)
        await en_hilo(s.sendall, b"\xc0\x00")
        assert await en_hilo(recibir_todo, s, 1, 2.0) == b""
        await en_hilo(s.close)

        # PUBLISH QoS 2 no soportado: se cierra la conexión y se publica el will (desconexión anormal)
        sub = Paho(puerto, "sub-q2")
        try:
            await sub.esperar_conexion()
            await sub.suscribir("scada/estacion/estado", qos=1)
            s = await en_hilo(abrir_socket, puerto)
            await en_hilo(s.sendall, connect_crudo("q2", will=("scada/estacion/estado", b"caido", 0, False)))
            assert await en_hilo(recibir_todo, s, 4) == b"\x20\x02\x00\x00"
            topic = codificar_cadena("scada/estacion/snap")
            cuerpo = topic + struct.pack("!H", 7) + b"x"
            await en_hilo(s.sendall, bytes([0x34]) + codificar_longitud(len(cuerpo)) + cuerpo)  # QoS 2
            assert await en_hilo(recibir_todo, s, 1, 2.0) == b""
            await en_hilo(s.close)
            assert await sub.recibir() == ("scada/estacion/estado", b"caido", 0, False)
            assert broker.publicados == 0
        finally:
            sub.cerrar()

        assert broker.conexiones == 2  # sub-q2 y q2

    broker, registro = correr(escenario)
    assert any("QoS 2" in r for r in registro)
    assert any("supera el máximo" in r for r in registro)
