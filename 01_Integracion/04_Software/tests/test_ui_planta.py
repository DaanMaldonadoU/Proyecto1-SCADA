# -*- coding: utf-8 -*-
"""
tests/test_ui_planta.py — Pruebas del cliente ZeroMQ del HMI (`ui.cliente.Planta`) sin ventana.

Qué prueba (mds/ARQUITECTURA.md 6.6): la clase `Planta(QObject)` contra un gateway SIM REAL
(`gateway.servidor.Servidor` + `gateway.backend_sim.BackendSim`) que corre en un hilo del mismo
proceso con puertos TCP efímeros, igual que `tests/test_servidor_sim.py`. No hay QML ni ventana:
    * `QT_QPA_PLATFORM=offscreen` antes de importar Qt.
    * Un `QCoreApplication` compartido por el proceso de pytest: otros módulos de prueba de ui/
      pueden haberlo creado antes (o crear un QGuiApplication), por eso siempre se consulta
      `instance()` y nunca se destruye.
    * El bucle de eventos se avanza con `processEvents()` dentro de un lazo con plazo (`esperar`),
      nunca con `exec()`. Así el QTimer de 15 ms de `Planta` dispara y las respuestas del hilo
      REQ llegan por la cola de señales igual que en el HMI real.
    * Cada prueba levanta su propio gateway y su propia `Planta` (fixtures de función) para que
      ningún caso dependa del estado que dejó otro. La calibración se redirige a `tmp_path` para
      que las mediciones del simulador no ensucien `datos/calibracion.json` del repositorio.

Los plazos son generosos (5 s; 6 s para la caída del gateway, que tarda SIN_SNAPSHOT_S = 2 s):
las pruebas miden comportamiento, no tiempos exactos. Salta si no hay binding de Qt.

Requiere: Python 3.12+ con PySide6 o PyQt5, pyzmq y msgpack.
"""
import os
import threading
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
qt_compat = pytest.importorskip("ui.qt_compat")

import zmq  # noqa: E402  (después del importorskip a propósito)

from core import protocolo, tags  # noqa: E402
from gateway.backend_sim import BackendSim  # noqa: E402
from gateway.servidor import Servidor  # noqa: E402
from ui import cliente  # noqa: E402
from ui.cliente import ModeloEventos, Planta  # noqa: E402

QCoreApplication = qt_compat.QtCore.QCoreApplication

PLAZO_S = 5.0            # plazo normal de espera
PLAZO_CAIDA_S = 6.0      # SIN_SNAPSHOT_S (2 s) + margen
PERIODO_GATEWAY_MS = 20


# ============================================================================
# Utilidades
# ============================================================================
def esperar(cond, timeout=PLAZO_S):
    """Avanza el bucle de Qt hasta que `cond()` sea verdadera o venza el plazo. Devuelve bool."""
    app = QCoreApplication.instance()
    limite = time.perf_counter() + timeout
    while True:
        app.processEvents()
        if cond():
            return True
        if time.perf_counter() >= limite:
            return False
        time.sleep(0.005)


def avanzar(segundos):
    """Deja correr el bucle de Qt un tiempo fijo (para comprobar que algo NO ocurre)."""
    esperar(lambda: False, segundos)


def filas(modelo):
    """Filas visibles del ModeloEventos (la más reciente primero) leídas por la API pública del modelo."""
    salida = []
    for i in range(modelo.rowCount()):
        idx = modelo.index(i, 0)
        salida.append({"hora": modelo.data(idx, ModeloEventos.ROL_HORA),
                       "nivel": modelo.data(idx, ModeloEventos.ROL_NIVEL),
                       "msg": modelo.data(idx, ModeloEventos.ROL_MSG),
                       "origen": modelo.data(idx, ModeloEventos.ROL_ORIGEN)})
    return salida


def buscar(modelo, texto, nivel=None, origen=None):
    """Filas visibles cuyo mensaje contiene `texto` y, si se piden, con ese nivel y origen."""
    return [f for f in filas(modelo)
            if texto in f["msg"]
            and (nivel is None or f["nivel"] == nivel)
            and (origen is None or f["origen"] == origen)]


# ============================================================================
# Fixtures
# ============================================================================
@pytest.fixture(scope="module")
def app():
    """QCoreApplication compartido: se reutiliza el que exista (otro módulo pudo crearlo) y no se destruye."""
    return QCoreApplication.instance() or QCoreApplication([])


@pytest.fixture
def gateway():
    """Servidor SIM real en un hilo, puertos efímeros, contexto ZeroMQ propio (como test_servidor_sim)."""
    ctx = zmq.Context()
    srv = Servidor(BackendSim(), pub="tcp://127.0.0.1:*", cmd="tcp://127.0.0.1:*",
                   periodo_ms=PERIODO_GATEWAY_MS, contexto=ctx)
    hilo = threading.Thread(target=srv.bucle, name="gateway-prueba", daemon=True)
    hilo.start()
    assert srv.listo.wait(5.0), "el gateway no abrió sus sockets"
    yield srv, hilo
    srv.detener()
    hilo.join(5.0)
    assert not hilo.is_alive(), "el hilo del gateway no terminó"
    ctx.term()


@pytest.fixture
def planta(app, gateway, tmp_path, monkeypatch):
    """Planta conectada al gateway de la prueba, con el primer snapshot ya aplicado (etapa 0)."""
    srv, _hilo = gateway
    monkeypatch.setattr(cliente, "RUTA_CALIBRACION", tmp_path / "calibracion.json")
    monkeypatch.setattr(cliente, "RUTA_PREFERENCIAS", tmp_path / "preferencias_hmi.json")
    p = Planta()
    p.conectar(srv.pub_endpoint, srv.cmd_endpoint)
    assert esperar(lambda: p.conectado and p.etapa == 0), "no llegó el primer snapshot del gateway"
    yield p
    p.cerrar()


# ============================================================================
# 1. Conexión y primer snapshot
# ============================================================================
def test_conexion_inicial(planta, gateway):
    srv, _ = gateway
    assert planta.gatewayVivo is True
    assert planta.conectado is True
    assert planta.modo == "SIM"
    assert planta.fuente == "sim"
    assert planta.etapa == 0
    assert planta.pubEndpoint == srv.pub_endpoint and planta.cmdEndpoint == srv.cmd_endpoint

    bits = planta.bits
    assert bits["STOP_1"] is True            # pulsador NC: 1 en reposo
    assert bits["ACTIVE"] is False
    assert bits["X0"] is True
    assert set(tags.TAGS_BIT) <= set(bits)
    assert set(tags.TAGS_INT) <= set(planta.ints)
    assert set(planta.palabras) == set(tags.PALABRAS)       # las cuatro palabras

    total = len(tags.ITEMS_RAPIDOS) + len(tags.ITEMS_LENTOS)
    assert planta.calidadOk is True
    assert planta.calidadTexto == "Good %d/%d" % (total, total)
    assert planta.seq > 0
    assert planta.posEstimada is False       # en SIM la posición la da el gateway
    assert planta.hayEstimador is True
    assert set(planta.calibracion) == {"1", "2", "3"}      # sin la clave _meta
    assert isinstance(planta.mando, dict) and planta.mando.get("remotoHabilitado") is False

    # Los presets de arranque del simulador se ven en ints y todavía nada está "confirmado"
    for n in range(5):
        assert planta.ints[tags.tag_timer(n, "PRE")] == tags.PRESETS_DEFECTO["T_ESPERA"]
    assert planta.ints["T5_PRE"] == tags.PRESETS_DEFECTO["T_NEUM"]
    assert planta.ints["C_PRE"] == tags.PRESETS_DEFECTO["N_CICLOS"]
    assert set(planta.parametros) == set(tags.CONFIRMACION_PARAMETRO)
    assert all(not p["confirmado"] and p["consistente"] for p in planta.parametros.values())

    # Registro: la suscripción y la llegada del gateway quedan anotadas desde el HMI
    ev = planta.eventos
    assert isinstance(ev, ModeloEventos)
    assert buscar(ev, "Suscrito a %s" % srv.pub_endpoint, "info", "hmi")
    assert buscar(ev, "Gateway en línea (SIM)", "info", "hmi")
    assert ev.conteos["info"] >= 2


# ============================================================================
# 2. Pulso START → secuencia en marcha
# ============================================================================
def test_pulso_start_arranca_la_secuencia(planta):
    ev = planta.eventos
    planta.pulso("STARTV")
    assert esperar(lambda: planta.bits.get("ACTIVE") is True and planta.etapa >= 1), \
        "la secuencia no arrancó: etapa=%s bits=%s" % (planta.etapa, planta.bits)

    # Respuesta del gateway a la orden y transición anotada por el cliente
    assert esperar(lambda: buscar(ev, "Pulso STARTV", "info", "hmi"))
    fila = buscar(ev, "Pulso STARTV", "info", "hmi")[0]
    assert "ok" in fila["msg"] and "ms" in fila["msg"]
    assert buscar(ev, "X0 → X1", "info", "grafcet")
    # Y los eventos del propio gateway llegan por el topic evt (el del pulso lleva como origen
    # la etiqueta de quién lo mandó, "HMI local", no "gateway": basta con que no sea local del cliente)
    assert esperar(lambda: buscar(ev, "Marcha (ACTIVE = 1)", "info", "gateway"))
    assert esperar(lambda: buscar(ev, "Pulso STARTV (%d ms)" % tags.PULSO_MS, "info"))
    assert buscar(ev, "Pulso STARTV (%d ms)" % tags.PULSO_MS, "info")[0]["origen"] != "hmi"

    # El pulso lo cronometra el gateway: el flanco de bajada aparece en ultimaEscritura y STARTV vuelve a 0
    assert esperar(lambda: planta.ultimaEscritura.get("tag") == "STARTV"
                   and planta.ultimaEscritura.get("valor") == 0
                   and planta.ultimaEscritura.get("ok") is True
                   and planta.escriturasPendientes == 0)
    assert planta.bits["STARTV"] is False
    assert planta.tEtapa >= 0.0


# ============================================================================
# 3. Parámetros: escritura confirmada y rechazos locales
# ============================================================================
def test_escribir_parametros_confirma(planta):
    ev = planta.eventos
    planta.escribir("T_ESPERA", 20)
    assert esperar(lambda: planta.parametros["T_ESPERA"]["confirmado"]), planta.parametros
    for t in tags.CONFIRMACION_PARAMETRO["T_ESPERA"]:          # T0_PRE … T4_PRE, los cinco
        assert planta.ints[t] == 20
    assert planta.ints["T5_PRE"] == tags.PRESETS_DEFECTO["T_NEUM"]   # T_NEUM no se tocó
    p = planta.parametros["T_ESPERA"]
    assert p["leido"] == 20 and p["escrito"] == 20 and p["consistente"]
    assert planta.parametros["N_CICLOS"]["confirmado"] is False
    fila = buscar(ev, "Escribir T_ESPERA = 20", "info", "hmi")
    assert fila and "ok" in fila[0]["msg"]
    assert esperar(lambda: planta.ultimaEscritura.get("tag") == "T_ESPERA"
                   and planta.ultimaEscritura.get("valor") == 20 and planta.ultimaEscritura.get("ok"))

    planta.escribir("N_CICLOS", 2)
    assert esperar(lambda: planta.parametros["N_CICLOS"]["confirmado"])
    assert planta.ints["C_PRE"] == 2
    assert planta.parametros["T_ESPERA"]["confirmado"]           # sigue confirmado

    planta.escribir("T_NEUM", 30)
    assert esperar(lambda: planta.parametros["T_NEUM"]["confirmado"])
    assert planta.ints["T5_PRE"] == 30


def test_escritura_invalida_se_rechaza_localmente(planta):
    ev = planta.eventos
    n_ok_antes = len(buscar(ev, "Escribir"))
    planta.escribir("T_ESPERA", -5)                       # fuera de rango
    planta.escribir("T_ESPERA", tags.LIMITE_PRE + 1)     # fuera de rango por arriba
    planta.escribir("N_CICLOS", 0)                        # N_CICLOS >= 1
    planta.escribir("STARTV", 1)                          # es mando, no parámetro
    planta.escribir("EV_E1", 1)                           # salida: prohibido
    planta.escribir("SC1", 1)                             # entrada simulable, no parámetro

    assert planta._hilo.pendientes() == 0                 # nada salió hacia el gateway
    rech = buscar(ev, "rechazada", "aviso", "hmi")
    assert len(rech) == 6, [f["msg"] for f in rech]
    assert buscar(ev, "Escritura T_ESPERA=-5 rechazada", "aviso")
    assert buscar(ev, "Escritura N_CICLOS=0 rechazada", "aviso")
    assert buscar(ev, "Escritura STARTV=1 rechazada: no es parámetro", "aviso")
    assert buscar(ev, "Escritura EV_E1=1 rechazada", "aviso")
    assert planta.parametros["T_ESPERA"]["escrito"] == -1

    avanzar(0.3)
    assert len(buscar(ev, "Escribir")) == n_ok_antes      # ninguna orden "Escribir … · ok"
    assert planta.ultimaEscritura == {}                   # el gateway no escribió nada
    for n in range(5):
        assert planta.ints[tags.tag_timer(n, "PRE")] == tags.PRESETS_DEFECTO["T_ESPERA"]
    assert planta.ints["C_PRE"] == tags.PRESETS_DEFECTO["N_CICLOS"]


# ============================================================================
# 4. Pulso que no es mando
# ============================================================================
def test_pulso_no_mando_se_rechaza(planta):
    ev = planta.eventos
    planta.pulso("X0")
    planta.pulso("EV_E1")
    planta.pulso("SC1")
    assert planta._hilo.pendientes() == 0
    assert buscar(ev, "Pulso rechazado: X0 no es un mando", "aviso", "hmi")
    assert buscar(ev, "Pulso rechazado: EV_E1 no es un mando", "aviso", "hmi")
    assert buscar(ev, "Pulso rechazado: SC1 no es un mando", "aviso", "hmi")
    avanzar(0.3)
    assert planta.etapa == 0 and planta.bits["ACTIVE"] is False
    assert planta.ultimaEscritura == {}
    assert not buscar(ev, "Pulso X0")


# ============================================================================
# 5. Entradas simuladas: SIM las acepta, REAL las bloquea en el cliente
# ============================================================================
def test_entrada_simulada_y_bloqueo_en_real(planta):
    ev = planta.eventos
    # Pulsador físico de paro (NC): el gateway lo escribe y aparece la alarma stop_fisico
    planta.entrada("STOP_1", False)
    assert esperar(lambda: planta.bits.get("STOP_1") is False)
    assert esperar(lambda: any(a["id"] == "stop_fisico" for a in planta.alarmas))
    assert planta.alarmasActivas >= 1
    assert buscar(ev, "Entrada STOP_1 = 0", "info", "hmi")
    planta.entrada("STOP_1", True)
    assert esperar(lambda: planta.bits.get("STOP_1") is True and planta.alarmasActivas == 0)

    # Con la física automática los sensores los fija la física: el GATEWAY rechaza y el cliente lo anota
    planta.entrada("SC1", False)
    assert esperar(lambda: buscar(ev, "Entrada SC1 = 0 rechazada", "aviso", "hmi"))
    assert planta.bits["SC1"] is True

    # Una salida nunca es entrada simulable: rechazo local sin mandar nada
    pend = planta._hilo.pendientes()
    planta.entrada("EV_E1", True)
    assert buscar(ev, "Entrada EV_E1 rechazada", "aviso", "hmi")
    assert planta._hilo.pendientes() == pend

    # Modo REAL forzado en el cliente: la entrada se bloquea ANTES de llegar al hilo de órdenes
    n_antes = len(buscar(ev, "Entrada STOP_1 = 0"))
    planta._v["modo"] = "REAL"
    try:
        planta.entrada("STOP_1", False)
        assert planta._hilo.pendientes() == 0
        assert buscar(ev, "Entrada STOP_1 bloqueada: modo REAL", "aviso", "hmi")
    finally:
        planta._v["modo"] = "SIM"
    avanzar(0.3)
    assert planta.modo == "SIM"                            # el siguiente snapshot lo repone
    assert planta.bits["STOP_1"] is True                   # no se escribió
    assert len(buscar(ev, "Entrada STOP_1 = 0")) == n_antes


# ============================================================================
# 6. Física manual
# ============================================================================
def test_fisica_manual(planta, gateway):
    srv, _ = gateway
    ev = planta.eventos
    assert planta.fisicaAutomatica is True
    planta.fisicaAuto(False)
    assert planta.fisicaAutomatica is False                # cambia de inmediato en el cliente
    assert esperar(lambda: buscar(ev, "Física manual", "info", "hmi"))
    assert "ok" in buscar(ev, "Física manual", "info", "hmi")[0]["msg"]
    assert srv.backend.fisica_auto is False                # y el gateway lo aceptó
    # Ahora sí se puede fijar un sensor a mano
    planta.entrada("SC1", False)
    assert esperar(lambda: planta.bits.get("SC1") is False)
    planta.fisicaAuto(True)
    assert planta.fisicaAutomatica is True
    assert esperar(lambda: planta.bits.get("SC1") is True)  # la física vuelve a mandar
    assert srv.backend.fisica_auto is True


# ============================================================================
# 7. Posiciones, estimador y tendencias
# ============================================================================
def test_posiciones_y_tendencias(planta):
    pos = planta.pos
    assert len(pos) == 3 and all(isinstance(p, float) and 0.0 <= p <= 1.0 for p in pos)
    assert len(planta.posNeum) == 2 and all(0.0 <= p <= 1.0 for p in planta.posNeum)
    assert set(planta.carreras) == {"1", "2", "3"}

    # historialLatencia y cronograma se publican a 5 Hz: en medio segundo ya tienen datos
    assert esperar(lambda: len(planta.historialLatencia) >= 5 and len(planta.cronograma) >= 2, 2.0)
    assert all(isinstance(x, float) and x >= 0.0 for x in planta.historialLatencia)
    # Filas [t relativo ≤ 0, p1, p2, p3, etapa]. La primera muestra puede ser anterior al primer
    # snapshot (etapa -1 y posiciones -1: "sin dato"); las posteriores ya van con etapa 0.
    assert esperar(lambda: planta.cronograma and planta.cronograma[-1][4] == 0, 2.0)
    for m in planta.cronograma:
        assert len(m) == 5 and m[0] <= 0.0 and m[4] in (-1, 0), m
    assert planta.cronograma[-1][1:4] == [0.0, 0.0, 0.0]
    assert planta.periodoMs > 0.0
    assert planta.fuenteLatencia == "sim"

    # Al arrancar, 1A sale: la posición del gateway se mueve y el estimador mide la carrera
    planta.pulso("STARTV")
    assert esperar(lambda: planta.pos[0] > 0.5)
    assert planta.posEstimada is False
    # Durante la carrera: `moviendo` con dirección "ext"; al llegar SE1: confirmado, quieto, dirección
    # vacía (solo se informa mientras se mueve) y la carrera medida queda en la calibración.
    assert esperar(lambda: planta.carreras["1"]["moviendo"] and planta.carreras["1"]["direccion"] == "ext")
    assert esperar(lambda: planta.carreras["1"]["confirmado"] and not planta.carreras["1"]["moviendo"]
                   and planta.calibracion["1"]["ext"]["muestras"])
    muestras = planta.calibracion["1"]["ext"]["muestras"]
    assert len(muestras) == 1 and 400 <= muestras[0] <= 1500, muestras
    assert planta.carreras["1"]["duracion_ms"] == muestras[0]       # mediana de una sola muestra
    assert planta.carreras["1"]["direccion"] == ""
    assert esperar(lambda: any(m[1] > 0.5 for m in planta.cronograma), 2.0)


# ============================================================================
# 7b. Modo suave (core/suavizado.py) con el enlace lento simulado
# ============================================================================
def test_modo_suave_con_enlace_simulado(app, tmp_path, monkeypatch):
    """Gateway SIM con --simular-enlace (sin pos, archivos refrescados cada 0,15–2,4 s): con el modo
    suave la posición de 1A se mueve en pasos pequeños y la preferencia queda guardada."""
    monkeypatch.setattr(cliente, "RUTA_CALIBRACION", tmp_path / "calibracion.json")
    monkeypatch.setattr(cliente, "RUTA_PREFERENCIAS", tmp_path / "preferencias_hmi.json")
    ctx = zmq.Context()
    srv = Servidor(BackendSim(enlace_lento=True, semilla=4), pub="tcp://127.0.0.1:*", cmd="tcp://127.0.0.1:*",
                   periodo_ms=PERIODO_GATEWAY_MS, contexto=ctx)
    hilo = threading.Thread(target=srv.bucle, name="gateway-lento", daemon=True)
    hilo.start()
    assert srv.listo.wait(5.0)
    p = Planta()
    try:
        assert p.haySuavizado and p.modoSuave is False
        p.conectar(srv.pub_endpoint, srv.cmd_endpoint)
        assert esperar(lambda: p.conectado and p.etapa == 0)
        p.fijarModoSuave(True)
        assert p.modoSuave is True and p.posEstimada is True
        assert (tmp_path / "preferencias_hmi.json").exists()
        posiciones = []
        p.snapshotAplicado.connect(lambda: posiciones.append(p.pos[0]))
        p.pulso("STARTV")
        assert esperar(lambda: p.pos[0] >= 0.98, 8.0), "1A nunca salió en la animación"
        saltos = [abs(b - a) for a, b in zip(posiciones, posiciones[1:])]
        assert saltos and max(saltos) < 0.2, max(saltos)       # sin saltos de extremo a extremo
        assert esperar(lambda: p.etapa >= 2, 8.0)
        assert esperar(lambda: p.ints.get("C_ACC", 0) >= 1, 25.0), "no completó un ciclo"
        # El registro anota lo LEÍDO: nunca un paso atrás (salvo X7 → X1 y el GS a X0), aunque la
        # etapa publicada sea la prevista.
        pasos = [f["msg"] for f in filas(p.eventos) if f["origen"] == "grafcet" and "→" in f["msg"]]
        assert pasos
        for msg in pasos:
            a, b = [int(x.strip()[1:]) for x in msg.split("→")]
            assert b > a or b in (0, 1), msg
        p.fijarModoSuave(False)
        assert p.modoSuave is False
        assert Planta().modoSuave is False                       # recuerda la última elección
    finally:
        p.cerrar()
        srv.detener()
        hilo.join(5.0)
        ctx.term()


# ============================================================================
# 8. Desconectar y volver a conectar
# ============================================================================
def test_desconectar_y_reconectar(planta, gateway):
    srv, _ = gateway
    ev = planta.eventos
    planta.desconectar()
    assert planta.conectado is False
    assert planta.gatewayVivo is False
    assert planta.bits == {} and planta.palabras == {}
    assert planta.etapa == -1
    assert planta.calidadOk is False and planta.calidadTexto == "—"
    assert buscar(ev, "Desconectado del gateway", "aviso", "hmi")

    planta.pulso("STARTV")                                 # sin conexión: descartada, sin excepción
    assert buscar(ev, "Orden Pulso STARTV descartada: sin conexión", "aviso", "hmi")
    avanzar(0.3)
    assert planta.conectado is False and planta.etapa == -1

    planta.conectar(srv.pub_endpoint, srv.cmd_endpoint)
    assert esperar(lambda: planta.conectado and planta.etapa == 0)
    assert planta.gatewayVivo is True
    assert planta.bits["STOP_1"] is True
    assert len(buscar(ev, "Gateway en línea (SIM)")) == 2
    # Las órdenes vuelven a funcionar
    planta.pulso("STARTV")
    assert esperar(lambda: planta.bits.get("ACTIVE") is True)


# ============================================================================
# 9. Caída del gateway
# ============================================================================
def test_caida_del_gateway(planta, gateway):
    srv, hilo = gateway
    ev = planta.eventos
    srv.detener()
    hilo.join(5.0)
    assert not hilo.is_alive()
    t0 = time.perf_counter()
    assert esperar(lambda: not planta.gatewayVivo, PLAZO_CAIDA_S), "no detectó la caída del gateway"
    tardo = time.perf_counter() - t0
    assert tardo >= cliente.SIN_SNAPSHOT_S - 0.5, tardo    # esperó el plazo, no fue instantáneo
    assert planta.conectado is False
    assert planta.bits == {} and planta.etapa == -1
    fila = buscar(ev, "Sin snapshots del gateway", "alarma", "hmi")
    assert len(fila) == 1
    # Una orden sin gateway: el hilo REQ vence a los 500 ms y la GUI solo recibe un aviso
    planta.pulso("STARTV")
    assert esperar(lambda: buscar(ev, "Pulso STARTV: sin respuesta del gateway", "aviso", "hmi"), 3.0)
    avanzar(0.5)
    assert len(buscar(ev, "Sin snapshots del gateway", "alarma")) == 1   # el aviso no se repite


# ============================================================================
# 10. Modelo de eventos (sin gateway)
# ============================================================================
def test_modelo_eventos_filtro_y_limpiar(app):
    m = ModeloEventos()
    assert {bytes(v) for v in m.roleNames().values()} >= {b"hora", b"nivel", b"msg", b"origen", b"t"}
    m.agregar(protocolo.evento("uno", "info", "hmi"))
    m.agregar(protocolo.evento("dos", "aviso", "gateway"))
    m.agregar(protocolo.evento("tres", "alarma", "gateway"))
    m.agregar(protocolo.evento("cuatro", "info", "hmi"))
    assert m.rowCount() == 4
    assert [f["msg"] for f in filas(m)] == ["cuatro", "tres", "dos", "uno"]   # más reciente arriba
    assert len(filas(m)[0]["hora"]) == len("HH:MM:SS.mmm")
    assert m.conteos == {"info": 2, "aviso": 1, "alarma": 1}
    assert m.filtro == ["info", "aviso", "alarma"]

    m.alternarNivel("info")                                # oculta info; los conteos siguen
    assert m.rowCount() == 2 and all(f["nivel"] != "info" for f in filas(m))
    assert m.filtro == ["aviso", "alarma"]
    assert m.conteos["info"] == 2
    m.agregar(protocolo.evento("cinco", "info"))           # oculto pero contado
    assert m.rowCount() == 2 and m.conteos["info"] == 3
    m.alternarNivel("inexistente")                         # se ignora
    assert m.rowCount() == 2
    m.alternarNivel("info")
    assert m.rowCount() == 5 and filas(m)[0]["msg"] == "cinco"

    m.agregar({"msg": "sin nivel válido", "nivel": "fatal"})   # nivel desconocido → info
    assert filas(m)[0]["nivel"] == "info" and m.conteos["info"] == 4

    m.limpiar()
    assert m.rowCount() == 0
    assert m.conteos == {"info": 0, "aviso": 0, "alarma": 0}


def test_modelo_eventos_tope_de_500(app):
    m = ModeloEventos()
    for i in range(cliente.MAX_EVENTOS + 50):
        m.agregar(protocolo.evento("e%d" % i, "aviso" if i % 2 else "info"))
    assert m.rowCount() == cliente.MAX_EVENTOS
    assert sum(m.conteos.values()) == cliente.MAX_EVENTOS
    assert filas(m)[0]["msg"] == "e%d" % (cliente.MAX_EVENTOS + 49)       # el más nuevo arriba
    assert filas(m)[-1]["msg"] == "e50"                                    # los 50 más viejos salieron
