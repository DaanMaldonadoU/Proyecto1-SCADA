# -*- coding: utf-8 -*-
"""
ui/cliente.py — Cliente ZeroMQ del HMI: SUB de snapshots/eventos + REQ de órdenes → QObject `Planta`.

Qué hace (mds/ARQUITECTURA.md 6.1):
    * Un QTimer de 15 ms en el hilo de la GUI vacía el socket SUB con NOBLOCK. Conserva el
      ÚLTIMO snapshot y TODOS los eventos, aplica los cambios una sola vez por vuelta y emite
      `snapshotAplicado`. Cada propiedad solo notifica si su valor cambió.
    * Las órdenes (pulso, escribir, entrada, fisica, fuente) salen por un REQ que vive en un
      hilo pequeño propio (los sockets ZeroMQ no se comparten entre hilos). RCVTIMEO 2 s
      (`protocolo.TIMEOUT_CMD_MS`; una escritura por DF1 tarda hasta ~1,2 s en el laboratorio),
      REQ_RELAXED y REQ_CORRELATE: una orden sin respuesta deja un aviso en el registro y la
      GUI nunca se bloquea.
    * Alimenta a `core.estimador.EstimadorCarrera` con los bits de cada snapshot. En REAL
      (`pos` = None) la posición publicada es la estimación; en SIM/EMULATE la posición sale
      del gateway, pero el estimador sigue midiendo y se exponen `carreras` y `calibracion`.
    * Modo suave (`modoSuave`, botón «Suave» del sinóptico, se recuerda en
      datos/preferencias_hmi.json): `core.suavizado.Suavizador` recibe cada snapshot y en cada
      vuelta de 15 ms da la posición animada de 1A/2A/3A y 4A/5A, la etapa y el ACC previstos
      (bobinas, sensores y GRAFCET; repone carreras que las lecturas atrasadas se comieron). En
      ese modo `pos`, `posNeum`, `etapa`, `tEtapa` y los `T*_ACC` de `ints` son los previstos;
      `bits`, `palabras`, el registro y los parámetros siguen siendo lo leído del PLC.
    * Tema de pantalla (`tema`: "oscuro" | "gris", slot `fijarTema`, también en
      datos/preferencias_hmi.json): Main.qml lo pasa a `UI.Theme.variante` (ui/qml/tema/Theme.qml).
      "gris" = fondo gris claro y texto oscuro, criterio ISA-101.
    * Mando (core.mando): expone `mando` (quién tiene el permiso de escribir, si el mando
      remoto está habilitado, quién está en línea en la web) y los slots `remotoHabilitar`,
      `mandoTomar` y `mandoLiberar`. Las órdenes del HMI van sin `quien`: son locales y el
      gateway les da la máxima prioridad.
    * Sin conexión: `conectado = False`, bits vacíos (todo gris en la pantalla), sin excepciones.

Modos: SIM, EMULATE y REAL (el modo lo dicta el gateway en cada snapshot).

Bindings de Qt: el mismo código corre con PySide6 6.x (Qt 6, Python 3.12+ de 64 bits) o con
PyQt5 5.15 (Qt 5.15, alternativa con Python de 32 bits). Todo Qt se importa de
ui/qt_compat.py, que usa PySide6 si está instalado y si no PyQt5 (HMI_QT=PyQt5 lo fuerza).
Signal/Slot/Property tienen la API de PySide6; en PyQt5 son pyqtSignal/pyqtSlot/pyqtProperty.

Requiere: Python 3.12+ con PySide6 6.x o PyQt5 5.15, pyzmq y msgpack.
"""
from __future__ import annotations

import json
import queue
import threading
import time
from collections import deque
from datetime import datetime
from pathlib import Path

import zmq

from ui.qt_compat import (Property, QAbstractListModel, QByteArray, QModelIndex, QObject, Qt, QTimer,
                          Signal, Slot)

from core import protocolo, tags

try:  # los escribe otro módulo del proyecto; si faltaran, el HMI sigue sin estimación
    from core.calibracion import Calibracion
    from core.estimador import EstimadorCarrera
except ImportError:  # pragma: no cover - solo si core/ está incompleto
    Calibracion = None
    EstimadorCarrera = None
try:
    from core.suavizado import Suavizador
    from gateway.fisica import CadenaNeumatica     # mismo modelo de 4A/5A que usa el gateway en REAL
except ImportError:  # pragma: no cover
    Suavizador = None
    CadenaNeumatica = None

RAIZ = Path(__file__).resolve().parent.parent
RUTA_CALIBRACION = RAIZ / "datos" / "calibracion.json"
RUTA_PREFERENCIAS = RAIZ / "datos" / "preferencias_hmi.json"

PERIODO_TICK_MS = 15          # vaciado del SUB
SIN_SNAPSHOT_S = 2.0          # sin snapshots durante este tiempo → gateway caído
VENTANA_CRONOGRAMA_S = 46.0   # el cronograma dibuja 45 s; se guarda un poco más
MUESTREO_CRONOGRAMA_S = 0.1
PERIODO_EMISION_TENDENCIAS_S = 0.2   # historialLatencia y cronograma se publican a 5 Hz
PERIODO_SUAVE_LENTO_S = 0.033        # modo suave: etapa, tEtapa e ints previstos a ~30 Hz (pos a 66 Hz)
TEMAS = ("oscuro", "gris")           # variantes de ui/qml/tema/Theme.qml
N_HISTORIAL_LATENCIA = 240
MAX_EVENTOS = 500


def _hora(t):
    """Epoch → 'HH:MM:SS.mmm' en hora local."""
    try:
        return datetime.fromtimestamp(float(t)).strftime("%H:%M:%S.%f")[:-3]
    except (TypeError, ValueError, OSError):
        return "--:--:--"


# ============================================================================
# Modelo del registro de eventos
# ============================================================================
class ModeloEventos(QAbstractListModel):
    """Últimos 500 eventos (el más reciente arriba) con filtro por nivel."""

    ROL_HORA = Qt.UserRole + 1
    ROL_NIVEL = Qt.UserRole + 2
    ROL_MSG = Qt.UserRole + 3
    ROL_ORIGEN = Qt.UserRole + 4
    ROL_T = Qt.UserRole + 5

    filtroChanged = Signal()
    conteosChanged = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._todas = deque()          # más reciente a la izquierda
        self._vis = []                 # filas visibles con el filtro actual
        self._niveles = set(protocolo.NIVELES)
        self._conteos = {n: 0 for n in protocolo.NIVELES}

    # --- API de QAbstractListModel
    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self._vis)

    def roleNames(self):
        return {self.ROL_HORA: QByteArray(b"hora"), self.ROL_NIVEL: QByteArray(b"nivel"),
                self.ROL_MSG: QByteArray(b"msg"), self.ROL_ORIGEN: QByteArray(b"origen"),
                self.ROL_T: QByteArray(b"t")}

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid() or not 0 <= index.row() < len(self._vis):
            return None
        e = self._vis[index.row()]
        if role in (self.ROL_MSG, Qt.DisplayRole):
            return e["msg"]
        return {self.ROL_HORA: e["hora"], self.ROL_NIVEL: e["nivel"],
                self.ROL_ORIGEN: e["origen"], self.ROL_T: e["t"]}.get(role)

    # --- altas
    def agregar(self, ev):
        nivel = ev.get("nivel", "info")
        if nivel not in self._conteos:
            nivel = "info"
        fila = {"t": float(ev.get("t", time.time())), "hora": _hora(ev.get("t", time.time())),
                "nivel": nivel, "msg": str(ev.get("msg", "")), "origen": str(ev.get("origen", ""))}
        if len(self._todas) >= MAX_EVENTOS:
            vieja = self._todas.pop()
            self._conteos[vieja["nivel"]] -= 1
            if self._vis and self._vis[-1] is vieja:
                n = len(self._vis) - 1
                self.beginRemoveRows(QModelIndex(), n, n)
                self._vis.pop()
                self.endRemoveRows()
        self._todas.appendleft(fila)
        self._conteos[nivel] += 1
        if nivel in self._niveles:
            self.beginInsertRows(QModelIndex(), 0, 0)
            self._vis.insert(0, fila)
            self.endInsertRows()

    def notificar_conteos(self):
        self.conteosChanged.emit()

    # --- filtro (propiedades para QML)
    def _get_filtro(self):
        return [n for n in protocolo.NIVELES if n in self._niveles]

    def _get_conteos(self):
        return dict(self._conteos)

    filtro = Property("QVariantList", _get_filtro, notify=filtroChanged)
    conteos = Property("QVariantMap", _get_conteos, notify=conteosChanged)

    @Slot(str)
    def alternarNivel(self, nivel):
        """Muestra u oculta un nivel (info | aviso | alarma)."""
        if nivel not in self._conteos:
            return
        if nivel in self._niveles:
            self._niveles.discard(nivel)
        else:
            self._niveles.add(nivel)
        self.beginResetModel()
        self._vis = [f for f in self._todas if f["nivel"] in self._niveles]
        self.endResetModel()
        self.filtroChanged.emit()

    @Slot()
    def limpiar(self):
        self.beginResetModel()
        self._todas.clear()
        self._vis = []
        self._conteos = {n: 0 for n in protocolo.NIVELES}
        self.endResetModel()
        self.conteosChanged.emit()


# ============================================================================
# Hilo de órdenes (REQ)
# ============================================================================
class _HiloOrdenes(threading.Thread):
    """Envía órdenes por un REQ propio y entrega cada respuesta (o su ausencia) por callback.

    El callback es la emisión de una señal Qt, así que la respuesta llega a la GUI por cola.
    """

    def __init__(self, contexto, endpoint, al_responder):
        super().__init__(name="hmi-ordenes", daemon=True)
        self._ctx = contexto
        self.endpoint = endpoint
        self._al_responder = al_responder
        self._cola = queue.Queue()
        self._parar = threading.Event()
        self.en_vuelo = False            # hay una orden enviada esperando respuesta
        self.t_respuesta = 0.0           # perf_counter de la última respuesta (se anota en ESTE hilo)

    def enviar(self, orden, etiqueta):
        self._cola.put((orden, etiqueta))

    def pendientes(self):
        return self._cola.qsize()

    def detener(self):
        self._parar.set()

    def run(self):
        sock = self._ctx.socket(zmq.REQ)
        sock.setsockopt(zmq.LINGER, 0)
        sock.setsockopt(zmq.RCVTIMEO, protocolo.TIMEOUT_CMD_MS)
        sock.setsockopt(zmq.SNDTIMEO, protocolo.TIMEOUT_CMD_MS)
        sock.setsockopt(zmq.REQ_RELAXED, 1)
        sock.setsockopt(zmq.REQ_CORRELATE, 1)
        sock.connect(self.endpoint)
        try:
            while not self._parar.is_set():
                try:
                    orden, etiqueta = self._cola.get(timeout=0.2)
                except queue.Empty:
                    continue
                self.en_vuelo = True
                t0 = time.perf_counter()
                try:
                    sock.send(protocolo.empaquetar(orden))
                    resp = protocolo.desempaquetar(sock.recv())
                    resp = resp if isinstance(resp, dict) else {"ok": False, "msg": "respuesta inválida"}
                    resp["_sin_respuesta"] = False
                except zmq.Again:
                    resp = {"ok": False, "msg": "sin respuesta del gateway en %d ms" % protocolo.TIMEOUT_CMD_MS,
                            "_sin_respuesta": True}
                except zmq.ZMQError as e:
                    resp = {"ok": False, "msg": "error ZeroMQ: %s" % e, "_sin_respuesta": True}
                resp["_etiqueta"] = etiqueta
                resp["_rtt_ms"] = (time.perf_counter() - t0) * 1000.0
                self.t_respuesta = time.perf_counter()     # antes de soltar en_vuelo: sin huecos para quien espera
                if not self._parar.is_set():
                    self._al_responder(resp)
                self.en_vuelo = False
        finally:
            sock.close(0)


# ============================================================================
# Planta
# ============================================================================
def _prop(tipo, nombre, senal):
    """Propiedad de solo lectura respaldada por Planta._v[nombre]."""
    return Property(tipo, lambda self: self._v[nombre], notify=senal)


def _receptividades():
    """Receptividades abreviadas del GRAFCET (docs/TABLA_DE_VARIABLES.md sección 4), construidas desde core.tags."""
    c = tags.CILINDROS
    dn = {n: tags.DIRECCION[tags.tag_timer(n, "DN")] for n in range(tags.N_TIMERS)}
    sc = {n: c[n][2] for n in c}
    se = {n: c[n][3] for n in c}
    return [
        {"de": 0, "a": 1, "texto": "%s·%s·%s·START" % (sc[1], sc[2], sc[3])},
        {"de": 1, "a": 2, "texto": se[1]},
        {"de": 2, "a": 3, "texto": "%s·%s" % (dn[0], sc[1])},
        {"de": 3, "a": 4, "texto": "%s·%s" % (dn[1], se[2])},
        {"de": 4, "a": 5, "texto": "%s·%s" % (dn[2], sc[2])},
        {"de": 5, "a": 6, "texto": "%s·%s" % (dn[3], se[3])},
        {"de": 6, "a": 7, "texto": "%s·%s" % (dn[4], sc[3])},
        {"de": 7, "a": 1, "texto": "%s·%s·C<PRE" % (dn[tags.TIMER_NEUMATICO], sc[3])},
        {"de": 7, "a": 8, "texto": "%s·C≥PRE" % dn[tags.TIMER_NEUMATICO]},
        {"de": 8, "a": 0, "texto": "GS"},
    ]


def _mando_publico(m):
    """Bloque `mando` del snapshot en forma cómoda para QML (sin None anidados)."""
    if not isinstance(m, dict):
        return {}
    titular = m.get("titular") or {}
    ultima = m.get("ultima_orden") or {}
    quien_ult = ultima.get("quien") or {}
    return {
        "remotoHabilitado": bool(m.get("remoto_habilitado")),
        "libre": not titular,
        "titularUsuario": str(titular.get("usuario", "")),
        "titularRol": str(titular.get("rol", "")),
        "titularLocal": titular.get("origen") == "local",
        "desde": _hora(m["desde"])[:8] if m.get("desde") else "",
        "venceEnS": float(m.get("vence_en_s") or 0.0),
        "enlaceWeb": bool(m.get("enlace_web")),
        "conectados": [{"usuario": str(u.get("usuario", "")), "rol": str(u.get("rol", "")),
                        "desde": _hora(u["desde"])[:8] if u.get("desde") else ""}
                       for u in (m.get("conectados") or [])],
        "ultimaTexto": ("%s · %s %s%s · %s" % (
            _hora(ultima.get("t"))[:8], "HMI local" if quien_ult.get("origen") == "local"
            else "%s (%s)" % (quien_ult.get("usuario", "?"), quien_ult.get("rol", "?")),
            ultima.get("op", ""), (" " + str(ultima.get("tag"))) if ultima.get("tag") else "",
            "ok" if ultima.get("ok") else "rechazada")) if ultima else "",
    }


class Planta(QObject):
    """Estado de la planta para QML. Ver mds/ARQUITECTURA.md 6.1."""

    snapshotAplicado = Signal()
    _respuestaRecibida = Signal(object)

    # --- señales de notificación (una por propiedad)
    conectadoChanged = Signal()
    gatewayVivoChanged = Signal()
    modoChanged = Signal()
    fuenteChanged = Signal()
    calidadTextoChanged = Signal()
    calidadOkChanged = Signal()
    etapaChanged = Signal()
    tEtapaChanged = Signal()
    bitsChanged = Signal()
    intsChanged = Signal()
    palabrasChanged = Signal()
    posChanged = Signal()
    posNeumChanged = Signal()
    posEstimadaChanged = Signal()
    carrerasChanged = Signal()
    latenciaMsChanged = Signal()
    latenciaMaxMsChanged = Signal()
    latenciaP95MsChanged = Signal()
    periodoMsChanged = Signal()
    cicloMsChanged = Signal()
    fuenteLatenciaChanged = Signal()
    alarmasChanged = Signal()
    alarmasActivasChanged = Signal()
    ultimaEscrituraChanged = Signal()
    escriturasPendientesChanged = Signal()
    calibracionChanged = Signal()
    historialLatenciaChanged = Signal()
    cronogramaChanged = Signal()
    parametrosChanged = Signal()
    seqChanged = Signal()
    fisicaAutomaticaChanged = Signal()
    pubEndpointChanged = Signal()
    cmdEndpointChanged = Signal()
    ordenesPendientesChanged = Signal()
    finesChanged = Signal()
    finRecienteChanged = Signal()
    mandoChanged = Signal()
    modoSuaveChanged = Signal()
    suaveChanged = Signal()
    temaChanged = Signal()

    conectado = _prop(bool, "conectado", conectadoChanged)
    gatewayVivo = _prop(bool, "gatewayVivo", gatewayVivoChanged)
    modo = _prop(str, "modo", modoChanged)
    fuente = _prop(str, "fuente", fuenteChanged)
    calidadTexto = _prop(str, "calidadTexto", calidadTextoChanged)
    calidadOk = _prop(bool, "calidadOk", calidadOkChanged)
    etapa = _prop(int, "etapa", etapaChanged)                  # -1 = ninguna / sin dato
    tEtapa = _prop(float, "tEtapa", tEtapaChanged)
    bits = _prop("QVariantMap", "bits", bitsChanged)
    ints = _prop("QVariantMap", "ints", intsChanged)
    palabras = _prop("QVariantMap", "palabras", palabrasChanged)
    pos = _prop("QVariantList", "pos", posChanged)
    posNeum = _prop("QVariantList", "posNeum", posNeumChanged)
    posEstimada = _prop(bool, "posEstimada", posEstimadaChanged)
    carreras = _prop("QVariantMap", "carreras", carrerasChanged)
    latenciaMs = _prop(float, "latenciaMs", latenciaMsChanged)
    latenciaMaxMs = _prop(float, "latenciaMaxMs", latenciaMaxMsChanged)
    latenciaP95Ms = _prop(float, "latenciaP95Ms", latenciaP95MsChanged)
    periodoMs = _prop(float, "periodoMs", periodoMsChanged)
    cicloMs = _prop(float, "cicloMs", cicloMsChanged)
    fuenteLatencia = _prop(str, "fuenteLatencia", fuenteLatenciaChanged)
    alarmas = _prop("QVariantList", "alarmas", alarmasChanged)
    alarmasActivas = _prop(int, "alarmasActivas", alarmasActivasChanged)
    ultimaEscritura = _prop("QVariantMap", "ultimaEscritura", ultimaEscrituraChanged)
    escriturasPendientes = _prop(int, "escriturasPendientes", escriturasPendientesChanged)
    calibracion = _prop("QVariantMap", "calibracion", calibracionChanged)
    historialLatencia = _prop("QVariantList", "historialLatencia", historialLatenciaChanged)
    cronograma = _prop("QVariantList", "cronograma", cronogramaChanged)
    parametros = _prop("QVariantMap", "parametros", parametrosChanged)
    seq = _prop(int, "seq", seqChanged)
    fisicaAutomatica = _prop(bool, "fisicaAutomatica", fisicaAutomaticaChanged)
    pubEndpoint = _prop(str, "pubEndpoint", pubEndpointChanged)
    cmdEndpoint = _prop(str, "cmdEndpoint", cmdEndpointChanged)
    ordenesPendientes = _prop(int, "ordenesPendientes", ordenesPendientesChanged)
    fines = _prop(int, "fines", finesChanged)                  # veces que terminaron los N ciclos
    finReciente = _prop(bool, "finReciente", finRecienteChanged)  # terminó y sigue en X0 desde entonces
    mando = _prop("QVariantMap", "mando", mandoChanged)        # bloque `mando` del snapshot (core.mando)
    modoSuave = _prop(bool, "modoSuave", modoSuaveChanged)     # animación prevista (core.suavizado)
    suave = _prop("QVariantMap", "suave", suaveChanged)        # diagnóstico del modo suave para QML
    tema = _prop(str, "tema", temaChanged)                     # "oscuro" | "gris" (ISA-101)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._v = {
            "conectado": False, "gatewayVivo": False, "modo": "", "fuente": "",
            "calidadTexto": "—", "calidadOk": False, "etapa": -1, "tEtapa": 0.0,
            "bits": {}, "ints": {}, "palabras": {}, "pos": [0.0, 0.0, 0.0], "posNeum": [0.0, 0.0],
            "posEstimada": False, "carreras": {}, "latenciaMs": 0.0, "latenciaMaxMs": 0.0,
            "latenciaP95Ms": 0.0, "periodoMs": 0.0, "cicloMs": 0.0, "fuenteLatencia": "",
            "alarmas": [], "alarmasActivas": 0, "ultimaEscritura": {}, "escriturasPendientes": 0,
            "calibracion": {}, "historialLatencia": [], "cronograma": [], "parametros": {},
            "seq": 0, "fisicaAutomatica": True, "pubEndpoint": "", "cmdEndpoint": "",
            "ordenesPendientes": 0, "fines": 0, "finReciente": False, "mando": {},
            "modoSuave": False, "suave": {}, "tema": "oscuro",
        }
        self._crudo = {}                       # lo último leído de lo que el modo suave sustituye
        self._t_suave_lento = 0.0
        self._suave_fallo_avisado = False      # un error del suavizador se anota una vez, no a 10 Hz
        self._sucio = set()
        self._modelo = ModeloEventos(self)
        self._escrito = {}                     # tag de parámetro -> último valor escrito desde el HMI
        self._ultimo_snap_t = None             # perf_counter del último snapshot recibido
        self._lat_hist = deque(maxlen=N_HISTORIAL_LATENCIA)
        self._crono = deque()
        self._t_muestra = 0.0
        self._t_emision = 0.0
        self._t0 = time.perf_counter()
        self._ultimo_seq = None
        self._avisado_caida = False
        self._t_ultima_respuesta = 0.0         # perf_counter de la última respuesta del gateway

        self._ctx = zmq.Context.instance()
        self._sub = None
        self._hilo = None

        self._calib = None
        self._estimador = None
        if Calibracion is not None and EstimadorCarrera is not None:
            try:
                RUTA_CALIBRACION.parent.mkdir(parents=True, exist_ok=True)
                self._calib = Calibracion(str(RUTA_CALIBRACION))
                self._estimador = EstimadorCarrera(self._calib)
                self._v["calibracion"] = self._calibracion_publica()
            except Exception as e:  # nunca tumbar la GUI por la calibración
                self._evento_local("No se pudo iniciar la calibración: %s" % e, "aviso")
        else:
            self._evento_local("core.estimador/core.calibracion no disponibles: sin estimación de carrera", "aviso")
        self._suavizador = None
        self._ruta_pref = Path(RUTA_PREFERENCIAS)
        preferencias = self._leer_preferencias()
        if Suavizador is not None:
            self._suavizador = Suavizador(self._calib, cadena=CadenaNeumatica() if CadenaNeumatica else None)
            self._v["modoSuave"] = bool(preferencias.get("modoSuave", False))
        if preferencias.get("tema") in TEMAS:
            self._v["tema"] = preferencias["tema"]

        self._respuestaRecibida.connect(self._al_responder, Qt.QueuedConnection)
        self._timer = QTimer(self)
        self._timer.setTimerType(Qt.PreciseTimer)
        self._timer.setInterval(PERIODO_TICK_MS)
        self._timer.timeout.connect(self._tick)

    # ------------------------------------------------------------------ definiciones estáticas
    def _get_eventos(self):
        return self._modelo

    eventos = Property(QObject, _get_eventos, constant=True)

    def _get_etapas_def(self):
        return [{"numero": n, "accion": a, "timer": -1 if t is None else t,
                 "tagAcc": "" if t is None else tags.tag_timer(t, "ACC"),
                 "tagPre": "" if t is None else tags.tag_timer(t, "PRE"),
                 "direccionTimer": "" if t is None else tags.DIRECCION[tags.tag_timer(t, "ACC")].split(".")[0]}
                for n, a, t in tags.ETAPAS]

    def _get_receptividades(self):
        return _receptividades()

    def _get_palabras_def(self):
        return [{"nombre": nombre, "bits": [next((t for t, b in tabla.items() if b == i), "") for i in range(16)]}
                for nombre, tabla in tags.PALABRAS.items()]

    def _get_cilindros_def(self):
        return [{"n": n, "evE": e, "evC": c, "sc": sc, "se": se} for n, (e, c, sc, se) in tags.CILINDROS.items()]

    def _get_neumatico_def(self):
        n = tags.TIMER_NEUMATICO
        return {"tagAcc": tags.tag_timer(n, "ACC"), "tagPre": tags.tag_timer(n, "PRE"),
                "direccion": tags.DIRECCION[tags.tag_timer(n, "ACC")].split(".")[0],
                "cilindros": list(tags.CILINDROS_NEUMATICOS)}

    def _get_parametros_def(self):
        return [
            {"tag": "T_ESPERA", "unidad": "s", "escala": 100, "max": tags.LIMITE_PRE, "sliderMax": 1000,
             "destino": "%s … %s" % (tags.PARAMETROS["T_ESPERA"][0], tags.PARAMETROS["T_ESPERA"][-1])},
            {"tag": "T_NEUM", "unidad": "s", "escala": 100, "max": tags.LIMITE_PRE, "sliderMax": 2000,
             "destino": tags.PARAMETROS["T_NEUM"][0]},
            {"tag": "N_CICLOS", "unidad": "", "escala": 1, "max": 99, "sliderMax": 20,
             "destino": tags.PARAMETROS["N_CICLOS"][0]},
        ]

    etapasDef = Property("QVariantList", _get_etapas_def, constant=True)
    receptividades = Property("QVariantList", _get_receptividades, constant=True)
    palabrasDef = Property("QVariantList", _get_palabras_def, constant=True)
    cilindrosDef = Property("QVariantList", _get_cilindros_def, constant=True)
    neumaticoDef = Property("QVariantMap", _get_neumatico_def, constant=True)
    parametrosDef = Property("QVariantList", _get_parametros_def, constant=True)
    sensores = Property("QVariantList", lambda self: list(tags.SENSORES), constant=True)
    haySuavizado = Property(bool, lambda self: self._suavizador is not None, constant=True)
    temas = Property("QVariantList", lambda self: list(TEMAS), constant=True)
    pulsoMs = Property(int, lambda self: tags.PULSO_MS, constant=True)
    hayEstimador = Property(bool, lambda self: self._estimador is not None, constant=True)

    @Slot(str, result=str)
    def direccion(self, tag):
        """Dirección RSLinx de un tag (solo para mostrarla)."""
        return tags.DIRECCION.get(tag, "")

    # ------------------------------------------------------------------ utilidades internas
    def _poner(self, nombre, valor):
        if self._v[nombre] != valor:
            self._v[nombre] = valor
            self._sucio.add(nombre)

    def _emitir(self):
        sucio, self._sucio = self._sucio, set()
        for nombre in sucio:
            getattr(self, nombre + "Changed").emit()

    def _evento_local(self, msg, nivel="info"):
        self._modelo.agregar(protocolo.evento(msg, nivel, origen="hmi"))
        self._modelo.notificar_conteos()

    def _calibracion_publica(self):
        if self._calib is None:
            return {}
        return {k: v for k, v in self._calib.como_dict().items() if not str(k).startswith("_")}

    # ------------------------------------------------------------------ conexión
    @Slot(str, str)
    def conectar(self, pub=protocolo.PUB_DEFECTO, cmd=protocolo.CMD_DEFECTO):
        """Se suscribe a `pub` y manda órdenes a `cmd`. Reemplaza cualquier conexión previa."""
        self.desconectar(silencioso=True)
        pub = pub or protocolo.PUB_DEFECTO
        cmd = cmd or protocolo.CMD_DEFECTO
        self._sub = self._ctx.socket(zmq.SUB)
        self._sub.setsockopt(zmq.LINGER, 0)
        self._sub.setsockopt(zmq.RCVHWM, 1000)
        self._sub.setsockopt(zmq.SUBSCRIBE, protocolo.TOPIC_SNAP)
        self._sub.setsockopt(zmq.SUBSCRIBE, protocolo.TOPIC_EVT)
        self._sub.connect(pub)
        self._hilo = _HiloOrdenes(self._ctx, cmd, self._respuestaRecibida.emit)
        self._hilo.start()
        self._poner("pubEndpoint", pub)
        self._poner("cmdEndpoint", cmd)
        self._ultimo_snap_t = None
        self._avisado_caida = False
        self._evento_local("Suscrito a %s · órdenes a %s" % (pub, cmd))
        self._timer.start()
        self._emitir()

    @Slot()
    def desconectar(self, silencioso=False):
        """Cierra SUB y REQ. La pantalla pasa a gris."""
        self._timer.stop()
        if self._hilo is not None:
            self._hilo.detener()
            self._hilo.join(timeout=1.0)
            self._hilo = None
        if self._sub is not None:
            self._sub.close(0)
            self._sub = None
        self._marcar_sin_conexion()
        if not silencioso:
            self._evento_local("Desconectado del gateway", "aviso")
        self._emitir()

    def _marcar_sin_conexion(self):
        self._crudo["etapa"] = -1
        self._poner("conectado", False)
        self._poner("gatewayVivo", False)
        self._poner("bits", {})
        self._poner("palabras", {})
        self._poner("etapa", -1)
        self._poner("tEtapa", 0.0)
        self._poner("calidadTexto", "—")
        self._poner("calidadOk", False)
        self._poner("carreras", {})

    # ------------------------------------------------------------------ bucle de la GUI
    def _tick(self):
        if self._sub is None:
            return
        ultimo = None
        eventos = []
        try:
            while True:
                partes = self._sub.recv_multipart(zmq.NOBLOCK)
                if len(partes) != 2:
                    continue
                topic, carga = partes
                try:
                    obj = protocolo.desempaquetar(carga)
                except Exception:
                    continue
                if topic == protocolo.TOPIC_SNAP and isinstance(obj, dict):
                    ultimo = obj
                elif topic == protocolo.TOPIC_EVT and isinstance(obj, dict):
                    eventos.append(obj)
        except zmq.Again:
            pass
        except zmq.ZMQError as e:
            self._evento_local("Error del socket SUB: %s" % e, "aviso")

        ahora = time.perf_counter()
        for ev in eventos:
            self._modelo.agregar(ev)
        if eventos:
            self._modelo.notificar_conteos()

        if ultimo is not None:
            if self._ultimo_snap_t is None or not self._v["gatewayVivo"]:
                self._evento_local("Gateway en línea (%s)" % ultimo.get("modo", "?"))
            self._ultimo_snap_t = ahora
            self._avisado_caida = False
            self._aplicar(ultimo, ahora)
        elif self._v["gatewayVivo"] and self._ultimo_snap_t is not None \
                and ahora - self._ultimo_snap_t > SIN_SNAPSHOT_S:
            self._marcar_sin_conexion()
            if not self._avisado_caida:
                self._evento_local("Sin snapshots del gateway desde hace %.0f s" % SIN_SNAPSHOT_S, "alarma")
                self._avisado_caida = True

        if self._suave_activo(self._v["conectado"]):
            self._aplicar_suave(ahora)
        self._tendencias(ahora)
        pend = self._hilo.pendientes() if self._hilo is not None else 0
        self._poner("ordenesPendientes", pend)
        if self._sucio:
            self._emitir()
            self.snapshotAplicado.emit()

    def _aplicar(self, s, ahora):
        """Vuelca un snapshot en las propiedades (solo marca las que cambian)."""
        modo = str(s.get("modo", ""))
        conectado = bool(s.get("conectado", False))
        bits = {k: bool(v) for k, v in (s.get("bits") or {}).items()} if conectado else {}
        ints = {k: int(v) for k, v in (s.get("ints") or {}).items()}
        cal = s.get("calidad") or {}
        good, total = int(cal.get("good", 0)), int(cal.get("total", 0))
        lat = s.get("lat") or protocolo.latencia_vacia()
        etapa = s.get("etapa")
        seq = int(s.get("seq", 0))

        # El gateway no publica cambios de etapa ni de ciclo: el registro los anota aquí.
        nueva = -1 if (etapa is None or not conectado) else int(etapa)
        # Se compara con la etapa LEÍDA anterior, no con la publicada: en modo suave la publicada es la
        # prevista y el registro anotaría pasos hacia atrás que no ocurrieron (X6 → X5).
        previa = self._crudo.get("etapa", self._v["etapa"])
        if nueva >= 0 and previa >= 0 and nueva != previa:
            self._modelo.agregar(protocolo.evento("X%d → X%d" % (previa, nueva), "info", "grafcet"))
            self._modelo.notificar_conteos()
        c_acc, c_pre = ints.get("C_ACC"), ints.get("C_PRE")
        if c_acc is not None and self._v["ints"].get("C_ACC") is not None and c_acc > self._v["ints"]["C_ACC"]:
            self._modelo.agregar(protocolo.evento("Ciclo %d de %s" % (c_acc, c_pre), "info", "grafcet"))
            self._modelo.notificar_conteos()
        self._poner("gatewayVivo", True)
        self._poner("conectado", conectado)
        self._poner("modo", modo)
        self._poner("fuente", str(s.get("fuente", "")))
        self._poner("calidadTexto", ("Good %d/%d" % (good, total)) if total else "—")
        self._poner("calidadOk", total > 0 and good == total)
        suave = self._suave_activo(conectado)
        self._crudo["etapa"] = -1 if (etapa is None or not conectado) else int(etapa)
        self._crudo["tEtapa"] = round(float(s.get("t_etapa", 0.0)), 2)
        self._crudo["ints"] = ints
        if not suave:
            self._poner("etapa", self._crudo["etapa"])
            self._poner("tEtapa", self._crudo["tEtapa"])
            self._poner("ints", ints)
        self._poner("bits", bits)
        self._poner("palabras", {k: int(v) for k, v in (s.get("palabras") or {}).items()} if conectado else {})
        self._poner("seq", seq)
        # END dura un barrido y casi nunca se lee: el fin de ciclos se detecta con `fines`
        fines = int(s.get("fines", 0) or 0)
        if fines > self._v["fines"] and self._v["gatewayVivo"] and self._ultimo_seq is not None:
            self._poner("finReciente", True)
        elif etapa not in (0, 8, None):
            self._poner("finReciente", False)
        self._poner("fines", fines)
        self._poner("latenciaMs", round(float(lat.get("lectura_ms", 0.0)), 2))
        self._poner("latenciaMaxMs", round(float(lat.get("lectura_max_ms", 0.0)), 2))
        self._poner("latenciaP95Ms", round(float(lat.get("p95_ms", 0.0)), 2))
        self._poner("periodoMs", round(float(lat.get("periodo_ms", 0.0)), 1))
        self._poner("cicloMs", round(float(lat.get("ciclo_ms", 0.0)), 2))
        self._poner("fuenteLatencia", str(lat.get("fuente", "")))

        self._poner("mando", _mando_publico(s.get("mando")))

        alarmas = [dict(a) for a in (s.get("alarmas") or [])]
        self._poner("alarmas", alarmas)
        self._poner("alarmasActivas", sum(1 for a in alarmas if a.get("activa")))
        esc = s.get("escrituras") or {}
        self._poner("ultimaEscritura", dict(esc.get("ultima") or {}))
        self._poner("escriturasPendientes", int(esc.get("pendientes", 0)))

        # --- posición: gateway (SIM/EMULATE) o estimación (REAL)
        pos_gw = s.get("pos")
        res = None
        if self._estimador is not None and conectado:
            try:
                res = self._estimador.actualizar(ahora, bits)
            except Exception as e:
                self._evento_local("Estimador: %s" % e, "aviso")
                res = None
        if res:
            carreras = {}
            for n, r in res.items():
                carreras[str(n)] = {"objetivo": float(r.get("objetivo", 0.0)),
                                    "duracion_ms": int(r.get("duracion_ms", 0)),
                                    "pos": float(r.get("pos", 0.0)),
                                    "moviendo": bool(r.get("moviendo", False)),
                                    "confirmado": bool(r.get("confirmado", False)),
                                    "direccion": r.get("direccion") or "",
                                    "timeout": bool(r.get("timeout", False))}
                if r.get("timeout"):
                    self._evento_local("%dA: carrera sin confirmación del sensor de destino" % n, "aviso")
            self._poner("carreras", carreras)
            self._poner("calibracion", self._calibracion_publica())
        if pos_gw is not None:
            self._crudo["pos"], self._crudo["posEstimada"] = [round(float(p), 4) for p in pos_gw], False
        elif res:
            self._crudo["pos"] = [round(float(res[n]["pos"]), 4) for n in sorted(res)]
            self._crudo["posEstimada"] = True
        elif conectado:  # sin estimador: la posición solo puede venir de los sensores
            self._crudo["pos"] = [1.0 if bits.get(c[3]) else 0.0 for c in tags.CILINDROS.values()]
            self._crudo["posEstimada"] = True
        pn = s.get("pos_neum")
        self._crudo["posNeum"] = [round(float(p), 4) for p in pn] if pn is not None else [0.0, 0.0]
        if self._suavizador is not None:
            try:
                self._suavizador.actualizar(ahora, s)
            except Exception as e:  # nunca tumbar la GUI por la animación
                self._aviso_suave(e)
        if not suave:
            if "pos" in self._crudo:
                self._poner("pos", self._crudo["pos"])
                self._poner("posEstimada", self._crudo["posEstimada"])
            self._poner("posNeum", self._crudo["posNeum"])

        # --- parámetros: check verde cuando la relectura coincide con lo escrito
        params = {}
        for tag, lista in tags.CONFIRMACION_PARAMETRO.items():
            leidos = [ints.get(t) for t in lista]
            consistente = None not in leidos and len(set(leidos)) == 1
            leido = leidos[0] if consistente else -1
            escrito = self._escrito.get(tag, -1)
            params[tag] = {"leido": leido, "escrito": escrito, "consistente": consistente,
                           "confirmado": escrito >= 0 and leido == escrito}
        self._poner("parametros", params)

        if seq != self._ultimo_seq:
            self._ultimo_seq = seq
            self._lat_hist.append(round(float(lat.get("lectura_ms", 0.0)), 2))

    # ------------------------------------------------------------------ modo suave
    def _suave_activo(self, conectado):
        return self._v["modoSuave"] and self._suavizador is not None and bool(conectado)

    def _aplicar_suave(self, ahora):
        """Una vuelta del modo suave: posiciones cada tick; etapa, tiempos e ints a ~30 Hz."""
        try:
            m = self._suavizador.muestrear(ahora)
        except Exception as e:
            self._aviso_suave(e)
            return
        self._poner("pos", list(m["pos"]))
        self._poner("posNeum", list(m["pos_neum"]))
        self._poner("posEstimada", True)
        if ahora - self._t_suave_lento < PERIODO_SUAVE_LENTO_S:
            return
        self._t_suave_lento = ahora
        crudo_etapa = self._crudo.get("etapa", -1)
        self._poner("etapa", m["etapa"] if m["etapa"] is not None else crudo_etapa)
        self._poner("tEtapa", round(float(m["t_etapa"]), 1))
        ints = dict(self._crudo.get("ints") or {})
        for n, acc in m["acc"].items():
            ints[tags.tag_timer(n, "ACC")] = int(acc)
        self._poner("ints", ints)
        self._poner("suave", {
            "previsto": m["etapa"] is not None and m["etapa"] != crudo_etapa,
            "etapaLeida": crudo_etapa,
            "repuestas": int(m["repuestas"]),
            "sinEtapa": bool(m["sin_etapa"]),
            "discrepancia": [bool(d) for d in m["discrepancia"]],
            "confirmado": [bool(c) for c in m["confirmado"]],
        })

    def _aviso_suave(self, e):
        if not self._suave_fallo_avisado:
            self._suave_fallo_avisado = True
            self._evento_local("Modo suave: %s (se sigue dibujando lo que haya)" % e, "aviso")

    def _restaurar_crudo(self):
        """Al apagar el modo suave vuelve lo leído tal cual."""
        for clave in ("etapa", "tEtapa", "ints", "pos", "posEstimada", "posNeum"):
            if clave in self._crudo:
                self._poner(clave, self._crudo[clave])
        self._poner("suave", {})

    def _leer_preferencias(self):
        try:
            datos = json.loads(self._ruta_pref.read_text(encoding="utf-8-sig"))   # tolera el BOM del Bloc de notas
            return datos if isinstance(datos, dict) else {}
        except (OSError, ValueError):
            return {}

    def _guardar_preferencias(self, **cambios):
        datos = self._leer_preferencias()
        datos.update(cambios)
        try:
            self._ruta_pref.parent.mkdir(parents=True, exist_ok=True)
            self._ruta_pref.write_text(json.dumps(datos, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        except OSError as e:
            self._evento_local("No se pudo guardar %s: %s" % (self._ruta_pref, e), "aviso")

    @Slot(bool)
    def fijarModoSuave(self, activo):
        """Activa o apaga la animación prevista. Solo cambia lo que se dibuja; no escribe en el PLC."""
        activo = bool(activo) and self._suavizador is not None
        if activo == self._v["modoSuave"]:
            return
        self._poner("modoSuave", activo)
        if activo:
            self._t_suave_lento = 0.0
            if self._v["conectado"]:
                self._aplicar_suave(time.perf_counter())
            self._evento_local("Modo suave activado: animación prevista con bobinas, sensores y GRAFCET "
                               "(los bits del monitor siguen siendo los leídos)")
        else:
            self._restaurar_crudo()
            self._evento_local("Modo suave apagado: se dibuja lo leído del PLC")
        self._guardar_preferencias(modoSuave=activo)
        self._emitir()

    @Slot(str)
    def fijarTema(self, tema):
        """Tema de la pantalla: "oscuro" (sistema de diseño) o "gris" (ISA-101). Se recuerda."""
        if tema not in TEMAS or tema == self._v["tema"]:
            return
        self._poner("tema", tema)
        self._guardar_preferencias(tema=tema)
        self._evento_local("Pantalla en tema %s" % ("gris (ISA-101)" if tema == "gris" else "oscuro"))
        self._emitir()

    def _tendencias(self, ahora):
        """Cronograma (muestreo 10 Hz aunque no haya datos) y publicación a 5 Hz."""
        if ahora - self._t_muestra >= MUESTREO_CRONOGRAMA_S:
            self._t_muestra = ahora
            t = ahora - self._t0
            if self._v["conectado"]:
                p = self._v["pos"]
                self._crono.append((t, p[0], p[1], p[2], self._v["etapa"]))
            else:
                self._crono.append((t, -1.0, -1.0, -1.0, -1))
            while self._crono and t - self._crono[0][0] > VENTANA_CRONOGRAMA_S:
                self._crono.popleft()
        if ahora - self._t_emision >= PERIODO_EMISION_TENDENCIAS_S:
            self._t_emision = ahora
            t = ahora - self._t0
            self._poner("cronograma", [[round(m[0] - t, 3), m[1], m[2], m[3], m[4]] for m in self._crono])
            self._poner("historialLatencia", list(self._lat_hist))

    # ------------------------------------------------------------------ órdenes
    def _mandar(self, orden, etiqueta):
        if self._hilo is None:
            self._evento_local("Orden %s descartada: sin conexión" % etiqueta, "aviso")
            return False
        self._hilo.enviar(orden, etiqueta)
        return True

    def escrituras_en_curso(self):
        """True si el gateway aún tiene algo que escribir: órdenes en cola o en vuelo, pulsos pendientes
        según el último snapshot (`escrituras.pendientes`), o una respuesta de hace menos de 0,3 s (el
        snapshot que refleja el pulso nuevo puede no haber llegado). Conexion lo espera antes de terminar
        su gateway, para no matarlo con STARTV/STOPV/RESETV en 1. Solo lee: no escribe nada."""
        hilo = self._hilo
        if hilo is not None and (hilo.pendientes() or hilo.en_vuelo):
            return True
        if self._v["gatewayVivo"] and self._v["escriturasPendientes"] > 0:
            return True
        ultima = max(self._t_ultima_respuesta, hilo.t_respuesta if hilo is not None else 0.0)
        return time.perf_counter() - ultima < 0.3

    def _al_responder(self, resp):
        self._t_ultima_respuesta = time.perf_counter()
        etiqueta = resp.get("_etiqueta", "orden")
        rtt = resp.get("_rtt_ms", 0.0)
        if resp.get("_sin_respuesta"):
            self._evento_local("%s: %s" % (etiqueta, resp.get("msg", "")), "aviso")
        elif not resp.get("ok"):
            self._evento_local("%s rechazada: %s" % (etiqueta, resp.get("msg", "")), "aviso")
        else:
            self._evento_local("%s · ok (%.1f ms)" % (etiqueta, rtt))

    @Slot(str)
    def pulso(self, tag):
        """Pulso de PULSO_MS sobre STARTV | STOPV | RESETV (lo cronometra el gateway)."""
        if tag not in tags.PULSOS:
            self._evento_local("Pulso rechazado: %s no es un mando" % tag, "aviso")
            return
        self._mandar(protocolo.cmd_pulso(tag, tags.PULSO_MS), "Pulso %s" % tag)

    @Slot(str, int)
    def escribir(self, tag, valor):
        """Escribe un parámetro (T_ESPERA / T_NEUM en centésimas, N_CICLOS entero)."""
        ok, motivo = tags.validar_escritura(tag, self._v["modo"] or "SIM", valor)
        if not ok or tag not in tags.PARAMETROS:
            self._evento_local("Escritura %s=%s rechazada: %s" % (tag, valor, motivo or "no es parámetro"), "aviso")
            return
        self._escrito[tag] = int(valor)
        self._mandar(protocolo.cmd_escribir(tag, int(valor)), "Escribir %s = %d" % (tag, int(valor)))

    @Slot(str, bool)
    def entrada(self, tag, valor):
        """Entrada simulada (pulsadores y sensores). Solo en SIM / EMULATE; en REAL se bloquea aquí."""
        if self._v["modo"] not in ("SIM", "EMULATE"):
            self._evento_local("Entrada %s bloqueada: modo %s" % (tag, self._v["modo"] or "desconocido"), "aviso")
            return
        ok, motivo = tags.validar_escritura(tag, self._v["modo"], valor)
        if not ok or tag not in tags.ENTRADAS_SIMULABLES:
            self._evento_local("Entrada %s rechazada: %s" % (tag, motivo or "no simulable"), "aviso")
            return
        self._mandar(protocolo.cmd_entrada(tag, valor), "Entrada %s = %d" % (tag, int(valor)))

    @Slot(bool)
    def fisicaAuto(self, auto):
        """Sensores desde la física simulada (True) o manuales (False)."""
        if self._v["modo"] == "REAL":
            self._evento_local("Física simulada no disponible en REAL", "aviso")
            return
        self._poner("fisicaAutomatica", bool(auto))
        self._emitir()
        self._mandar(protocolo.cmd_fisica(auto), "Física %s" % ("automática" if auto else "manual"))

    @Slot(str)
    def fuenteOpc(self, fuente):
        """Fuente de lectura OPC: 'dispositivo' | 'cache' (solo EMULATE / REAL)."""
        if fuente not in protocolo.FUENTES_OPC:
            self._evento_local("Fuente inválida: %s" % fuente, "aviso")
            return
        self._mandar(protocolo.cmd_fuente(fuente), "Fuente OPC %s" % fuente)

    @Slot(bool)
    def remotoHabilitar(self, habilitar):
        """Habilita o deshabilita el mando desde la web (solo el HMI local puede)."""
        self._mandar(protocolo.cmd_mando("remoto", habilitar),
                     "Mando remoto %s" % ("habilitado" if habilitar else "deshabilitado"))

    @Slot()
    def mandoTomar(self):
        """El HMI local toma el mando (se lo quita a quien lo tenga en la web)."""
        self._mandar(protocolo.cmd_mando("pedir"), "Tomar el mando")

    @Slot()
    def mandoLiberar(self):
        """Libera el mando para que lo pueda pedir alguien en la web."""
        self._mandar(protocolo.cmd_mando("liberar"), "Liberar el mando")

    @Slot()
    def reiniciarCalibracion(self):
        if self._calib is None:
            return
        self._calib.reiniciar()
        if self._estimador is not None:
            self._estimador.reiniciar()
        self._poner("calibracion", self._calibracion_publica())
        self._evento_local("Calibración de carreras reiniciada")
        self._emitir()

    def cerrar(self):
        """Libera sockets (al salir de la aplicación)."""
        self.desconectar(silencioso=True)
