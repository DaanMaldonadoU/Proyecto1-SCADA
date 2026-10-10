# -*- coding: utf-8 -*-
"""Pruebas del servidor en modo SIM por ZeroMQ real (TCP con puertos efímeros)."""
import threading
import time

import pytest
import zmq

from core import protocolo, tags
from core.latencia import percentil
from gateway.backend_sim import BackendSim
from gateway.servidor import Servidor


class Cliente:
    """SUB + REQ mínimos, como los usaría el HMI."""

    def __init__(self, ctx, pub, cmd):
        self.sub = ctx.socket(zmq.SUB)
        self.sub.setsockopt(zmq.LINGER, 0)
        self.sub.setsockopt(zmq.SUBSCRIBE, b"")
        self.sub.connect(pub)
        self.req = ctx.socket(zmq.REQ)
        self.req.setsockopt(zmq.LINGER, 0)
        self.req.setsockopt(zmq.RCVTIMEO, 2000)
        self.req.connect(cmd)
        self.eventos = []

    def orden(self, cmd):
        self.req.send(protocolo.empaquetar(cmd))
        return protocolo.desempaquetar(self.req.recv())

    def snapshots(self, timeout=2.0):
        """Generador de snapshots; guarda los eventos que lleguen por el camino."""
        limite = time.time() + timeout
        while time.time() < limite:
            if self.sub.poll(100):
                topic, datos = self.sub.recv_multipart()
                msg = protocolo.desempaquetar(datos)
                if topic == protocolo.TOPIC_SNAP:
                    yield msg
                else:
                    self.eventos.append(msg)

    def esperar(self, cond, timeout=10.0):
        for s in self.snapshots(timeout):
            if cond(s):
                return s
        raise AssertionError("condición no alcanzada en %.1f s" % timeout)

    def cerrar(self):
        self.sub.close(0)
        self.req.close(0)


@pytest.fixture
def gateway():
    ctx = zmq.Context()
    srv = Servidor(BackendSim(), pub="tcp://127.0.0.1:*", cmd="tcp://127.0.0.1:*",
                   periodo_ms=20, contexto=ctx)
    hilo = threading.Thread(target=srv.bucle, daemon=True)
    hilo.start()
    assert srv.listo.wait(5.0)
    cli = Cliente(ctx, srv.pub_endpoint, srv.cmd_endpoint)
    cli.esperar(lambda s: s["conectado"], 5.0)      # la suscripción ya recibe
    yield srv, cli
    cli.cerrar()
    srv.detener()
    hilo.join(5.0)
    ctx.term()


def test_snapshot_tiene_todas_las_claves(gateway):
    srv, cli = gateway
    s = cli.esperar(lambda s: True)
    assert set(protocolo.snapshot_vacio()) <= set(s)
    assert s["modo"] == "SIM" and s["fuente"] == "sim" and s["conectado"]
    assert s["etapa"] == 0
    assert set(s["palabras"]) == set(tags.PALABRAS)
    assert set(tags.TAGS_BIT) <= set(s["bits"])
    assert set(tags.TAGS_INT) <= set(s["ints"])
    assert s["calidad"]["good"] == s["calidad"]["total"] == len(tags.ITEMS_RAPIDOS) + len(tags.ITEMS_LENTOS)
    assert len(s["pos"]) == 3 and len(s["pos_neum"]) == 2
    assert set(s["lat"]) == set(protocolo.latencia_vacia())
    assert s["bits"]["STOP_1"] is True


def test_ping_estado_y_orden_invalida(gateway):
    srv, cli = gateway
    r = cli.orden(protocolo.cmd_ping())
    assert r["ok"] and r["msg"] == "pong"
    r = cli.orden(protocolo.cmd_estado())
    assert r["ok"] and r["snapshot"]["modo"] == "SIM"
    r = cli.orden({"op": "borrar_todo"})
    assert not r["ok"]
    r = cli.orden(protocolo.cmd_fuente("cache"))
    assert not r["ok"]                               # SIM no tiene fuente OPC


def test_escribir_t_espera_cambia_cinco_pre(gateway):
    srv, cli = gateway
    r = cli.orden(protocolo.cmd_escribir("T_ESPERA", 37))
    assert r["ok"], r
    s = cli.esperar(lambda s: all(s["ints"].get(t) == 37 for t in tags.CONFIRMACION_PARAMETRO["T_ESPERA"]))
    assert s["ints"]["T5_PRE"] == 500
    ult = s["escrituras"]["ultima"]
    assert ult["tag"] == "T_ESPERA" and ult["ok"]
    r = cli.orden(protocolo.cmd_escribir("N_CICLOS", 7))
    assert r["ok"]
    cli.esperar(lambda s: s["ints"].get("C_PRE") == 7)
    r = cli.orden(protocolo.cmd_escribir("T_ESPERA", 99999))
    assert not r["ok"]
    r = cli.orden(protocolo.cmd_escribir("EV_E1", 1))
    assert not r["ok"]


def test_pulso_start_y_secuencia_completa_sin_conflictos(gateway):
    srv, cli = gateway
    assert cli.orden(protocolo.cmd_escribir("T_ESPERA", 10))["ok"]
    assert cli.orden(protocolo.cmd_escribir("T_NEUM", 20))["ok"]
    cli.esperar(lambda s: s["ints"].get("T0_PRE") == 10 and s["ints"].get("T5_PRE") == 20)
    t0 = time.perf_counter()
    r = cli.orden(protocolo.cmd_pulso("STARTV"))
    assert r["ok"], r
    etapas = []
    end_visto = False
    pulso_visto = False
    for s in cli.snapshots(30.0):
        b = s["bits"]
        for e, c, _sc, _se in tags.CILINDROS.values():
            assert not (b[e] and b[c]), "EV_E y EV_C a la vez en %s/%s" % (e, c)
        if b["STARTV"]:
            pulso_visto = True
        if s["etapa"] is not None and (not etapas or etapas[-1] != s["etapa"]):
            etapas.append(s["etapa"])
        if srv.fines > 0:
            end_visto = True
            break
    dur = time.perf_counter() - t0
    assert pulso_visto
    assert end_visto, etapas
    # Tres ciclos completos: X7 aparece tres veces
    assert etapas.count(7) == 3, etapas
    assert etapas.count(1) == 3
    assert dur < 20.0
    # El pulso se retiró solo (300 ms en el gateway)
    s = cli.esperar(lambda s: not s["bits"]["STARTV"])
    assert s["escrituras"]["pendientes"] == 0
    assert any("STARTV" in e["msg"] for e in cli.eventos)
    assert any("END" in e["msg"] for e in cli.eventos)
    assert etapas[-1] in (0, 8)


def test_pulso_dura_300_ms(gateway):
    srv, cli = gateway
    t_envio = time.time()
    assert cli.orden(protocolo.cmd_pulso("STOPV"))["ok"]
    t_alto = t_bajo = None
    for s in cli.snapshots(3.0):
        if s["bits"]["STOPV"] and t_alto is None:
            t_alto = s["t"]
        if t_alto is not None and not s["bits"]["STOPV"]:
            t_bajo = s["t"]
            break
    assert t_alto is not None and t_bajo is not None
    assert 0.25 <= t_bajo - t_envio <= 0.40


def test_entrada_y_fisica_en_sim(gateway):
    srv, cli = gateway
    # En automático los sensores los fija la física
    r = cli.orden(protocolo.cmd_entrada("SC1", False))
    assert not r["ok"]
    assert cli.orden(protocolo.cmd_fisica(False))["ok"]
    r = cli.orden(protocolo.cmd_entrada("SC1", False))
    assert r["ok"], r
    cli.esperar(lambda s: s["bits"]["SC1"] is False)
    # Pulsador físico de paro (NC)
    assert cli.orden(protocolo.cmd_entrada("STOP_1", False))["ok"]
    s = cli.esperar(lambda s: any(a["id"] == "stop_fisico" for a in s["alarmas"]))
    assert s["bits"]["STOP_1"] is False
    assert cli.orden(protocolo.cmd_entrada("STOP_1", True))["ok"]
    cli.esperar(lambda s: not s["alarmas"])
    assert cli.orden(protocolo.cmd_fisica(True))["ok"]
    cli.esperar(lambda s: s["bits"]["SC1"] is True)


def test_periodo_se_mantiene(gateway):
    srv, cli = gateway
    ts = [s["t"] for s in cli.snapshots(2.0)]
    assert len(ts) > 50
    periodos = [(b - a) * 1000.0 for a, b in zip(ts, ts[1:])]
    assert percentil(periodos, 95) < 40.0, periodos
    media = sum(periodos) / len(periodos)
    assert 15.0 <= media <= 25.0
    # También lo que el gateway publica en lat
    s = cli.esperar(lambda s: True)
    assert 15.0 <= s["lat"]["periodo_ms"] <= 30.0


class _BackendReal(BackendSim):
    """Simulador que se presenta como REAL, para probar las reglas del modo."""
    modo = "REAL"


def test_entrada_rechazada_en_real():
    srv = Servidor(_BackendReal(), pub="tcp://127.0.0.1:*", cmd="tcp://127.0.0.1:*",
                   contexto=zmq.Context.instance())
    srv.backend.conectar()
    srv.conectado = True
    r = srv.procesar_orden(protocolo.cmd_entrada("SC1", True))
    assert not r["ok"] and "REAL" in r["msg"]
    assert srv._ultima_escritura["ok"] is False
    assert any(e["nivel"] == "aviso" for e in srv._eventos)
    r = srv.procesar_orden(protocolo.cmd_entrada("STOP_1", False))
    assert not r["ok"]
    r = srv.procesar_orden(protocolo.cmd_fisica(False))
    assert not r["ok"]
    # Los pulsos y parámetros sí se permiten en REAL
    assert srv.procesar_orden(protocolo.cmd_pulso("STARTV"))["ok"]
    assert srv.procesar_orden(protocolo.cmd_escribir("T_ESPERA", 120))["ok"]
    assert srv.backend.ladder.ints["T4_PRE"] == 120


def test_desconexion_y_reconexion():
    """Cinco lecturas fallidas → conectado=False y alarma; luego reconecta."""

    class _Fallon(BackendSim):
        fallar = 0

        def leer_rapido(self):
            if self.fallar > 0:
                self.fallar -= 1
                raise RuntimeError("fallo simulado")
            return BackendSim.leer_rapido(self)

    ctx = zmq.Context()
    b = _Fallon()
    srv = Servidor(b, pub="tcp://127.0.0.1:*", cmd="tcp://127.0.0.1:*", periodo_ms=20, contexto=ctx)
    srv.abrir()
    srv._intentar_conectar()
    srv.ciclo()
    b.fallar = 5
    for _ in range(4):
        s = srv.ciclo()
        assert s["conectado"]
    s = srv.ciclo()
    assert not s["conectado"]
    assert any(a["id"] == "desconexion" for a in s["alarmas"])
    srv._t_reintento = 0.0                           # no esperar 1 s en la prueba
    s = srv.ciclo()
    assert s["conectado"] and not any(a["id"] == "desconexion" for a in s["alarmas"])
    srv.cerrar()
    ctx.term()
