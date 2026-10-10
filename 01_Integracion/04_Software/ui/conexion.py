# -*- coding: utf-8 -*-
"""
ui/conexion.py — QObject `Conexion`: la ventana de conexión del HMI (mds/ARQUITECTURA.md §6.4).

Qué resuelve:
    El HMI corre en Python de 64 bits y no puede hablar COM con RSLinx. Esta clase le da a la
    pantalla lo que tenía la v6.1 (modo, servidor, topic, Conectar y el selector OPC) sin romper
    la arquitectura de dos procesos: no lee OPC, sino que **lanza y vigila subprocesos**:
      * el gateway (`python -m gateway …`; en EMULATE/REAL con el Python de 32 bits),
      * el descubrimiento OPC (`python32 -m gateway.diagnostico_opc --json …`, un QProcess por
        consulta, salida parseada con `interpretar_json`),
      * el envío de datos al gemelo local (`python -m digital_twin.local …`) o al servidor web
        (`python -m puente …`), con el Python del HMI.
    Vinculación con el servidor web (sesión 14): el puente se autentica con datos/puente.clave.
    `vincularServidor(usuario, contraseña)` la pide al servidor con una cuenta admin del gemelo
    (puente/vincular.py → POST /api/puente/clave, en un hilo aparte) y la guarda;
    `guardarClave(texto)` guarda una clave pegada a mano. Si el envío al servidor estaba en
    marcha, el puente se reinicia solo con la clave nueva.
    `Planta` (ui/cliente.py) sigue siendo quien se suscribe al gateway por ZeroMQ; aquí solo se
    llama `planta.conectar(pub, cmd)` / `planta.desconectar()` y se observan `gatewayVivo` y
    `conectado` para llevar `estado`.

Configuración persistente: datos/conexion.json (ignorado por git). Claves en `config_defecto()`.

Lógica pura (sin bucle de eventos, probada en tests/test_ui_conexion.py):
    argumentos_gateway(cfg, python), argumentos_puente(cfg, python), argumentos_gemelo(cfg, python),
    cargar_config(ruta), guardar_config(ruta, cfg), interpretar_json(texto), candidatos_python32(raiz).

Modos: SIM, EMULATE y REAL. Qt solo desde ui/qt_compat.py (PySide6 o PyQt5).
Requiere: Python 3.12+, pyzmq vía Planta.
"""
from __future__ import annotations

import json
import os
import re
import shlex
import socket
import sys
import threading
import time
from collections import deque
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from core import protocolo  # noqa: E402
from puente import vincular  # noqa: E402  (solo biblioteca estándar)
from ui.qt_compat import (PROCESO_FALLO_ARRANQUE, PROCESO_PARADO, PROCESO_SALIDA_NORMAL,  # noqa: E402
                          Property, QAbstractListModel, QCoreApplication, QDesktopServices, QModelIndex, QObject,
                          QProcess, QProcessEnvironment, Qt, QTimer, QUrl, Signal, Slot)

# ---------------------------------------------------------------------------- constantes
RUTA_CONFIG = RAIZ / "datos" / "conexion.json"
RUTA_CLAVE = RAIZ / "datos" / "puente.clave"
SERVIDOR_DEFECTO = "RSLinx Local OPC Server"
URL_SERVIDOR_DEFECTO = "wss://digitaltwinscada.smartsensorslab.com/ws/planta"
PUERTO_LOCAL_RESPALDO = 3002          # si no se puede leer digital_twin.local.PUERTO_DEFECTO
ITEM_PRUEBA_DEFECTO = "B3:0/0"
USUARIO_SERVIDOR_DEFECTO = "daan"     # cuenta admin del servidor del gemelo (la contraseña nunca se guarda)

PLAZO_SNAPSHOT_MS = 10000             # sin snapshot tras conectar → estado "error"
PLAZO_TERMINAR_MS = 3000              # terminate → 3 s → kill
PLAZO_ESCRITURAS_MS = 3000            # antes de terminar el gateway propio: pulsos pendientes (DF1: hasta ~1,2 s por escritura)
PLAZO_DESCUBRIR_MS = 60000            # RSLinx puede tardar en enumerar items
PLAZO_PYTHON32_MS = 8000              # el lanzador `py` tarda la primera vez
RETARDO_WEB_AJENO_MS = 1000           # gateway ajeno: el envío web arranca 1 s después
MAX_CONSOLA = 300

ESTADOS = ("desconectado", "conectando", "conectado", "error")
ESTADOS_PROCESO = ("parado", "arrancando", "corriendo", "error")
DESTINOS_WEB = ("ninguno", "local", "servidor")
ORIGENES_CONSOLA = ("gateway", "puente", "gemelo", "hmi")

_CLAVES_BOOL = ("lanzarGateway", "abrirNavegador", "publicoLocal", "remotoAlConectar")
_CLAVES_INT = ("periodoMs", "puertoLocal")


# ============================================================================
# Lógica pura (sin Qt)
# ============================================================================
def puerto_local_defecto():
    """`digital_twin.local.PUERTO_DEFECTO` leído en tiempo de ejecución (contrato de mds/SESIONES.md).

    Primero se lee del código fuente con una expresión regular (importar el módulo arrastra
    aiohttp y el servidor web, que el HMI no necesita); si no se puede, se importa; si tampoco,
    el valor de respaldo.
    """
    ruta = RAIZ / "digital_twin" / "local.py"
    try:
        m = re.search(r"^PUERTO_DEFECTO\s*=\s*(\d+)", ruta.read_text(encoding="utf-8"), re.M)
        if m:
            return int(m.group(1))
    except OSError:
        pass
    try:
        from digital_twin.local import PUERTO_DEFECTO
        return int(PUERTO_DEFECTO)
    except Exception:
        return PUERTO_LOCAL_RESPALDO


def topic_defecto(modo):
    # En el RSLinx del laboratorio el topic del SLC real también se llama PROYECTO1_TEST
    # (no existe PROYECTO1_REAL; docs/DIAGNOSTICO_CONEXION_PLC.md §8); en la VM es el del
    # emulador. Se conserva `modo` por si algún día cada modo vuelve a tener el suyo.
    return "PROYECTO1_TEST"


def periodo_defecto(modo):
    return 50 if modo == "SIM" else 100


def config_defecto():
    """Valores por defecto de datos/conexion.json (mds/ARQUITECTURA.md §6.4)."""
    return {
        "modo": "SIM",
        "servidor": SERVIDOR_DEFECTO,
        "topic": topic_defecto("SIM"),
        "periodoMs": periodo_defecto("SIM"),
        "fuente": "cache",                # caché de RSLinx: ~6 ms frente a ~200 ms (picos de 2 s) en DF1
        "lanzarGateway": True,
        "pub": protocolo.PUB_DEFECTO,
        "cmd": protocolo.CMD_DEFECTO,
        "destinoWeb": "ninguno",
        "urlServidor": URL_SERVIDOR_DEFECTO,
        "mqttUrl": "",
        "extrasPuente": "",
        "hostLocal": "127.0.0.1",
        "puertoLocal": puerto_local_defecto(),
        "abrirNavegador": True,
        "publicoLocal": False,
        "remotoAlConectar": False,
        "python32": "",                   # ruta manual del intérprete de 32 bits ("" = detectar)
        "itemPrueba": ITEM_PRUEBA_DEFECTO,
        "usuarioServidor": USUARIO_SERVIDOR_DEFECTO,   # para «Vincular»; se recuerda el último que funcionó
    }


def _normalizar(cfg):
    """Tipos correctos y valores dentro de lo permitido; desconocidos fuera."""
    base = config_defecto()
    for k in list(base):
        if k not in cfg or cfg[k] is None:
            continue
        v = cfg[k]
        try:
            if k in _CLAVES_BOOL:
                base[k] = bool(v)
            elif k in _CLAVES_INT:
                base[k] = int(v)
            else:
                base[k] = str(v)
        except (TypeError, ValueError):
            pass
    if base["modo"] not in protocolo.MODOS:
        base["modo"] = "SIM"
    if base["fuente"] not in protocolo.FUENTES_OPC:
        base["fuente"] = "cache"
    if base["destinoWeb"] not in DESTINOS_WEB:
        base["destinoWeb"] = "ninguno"
    if base["periodoMs"] <= 0:
        base["periodoMs"] = periodo_defecto(base["modo"])
    if not (0 < base["puertoLocal"] < 65536):
        base["puertoLocal"] = puerto_local_defecto()
    if not base["topic"]:
        base["topic"] = topic_defecto(base["modo"])
    if not base["pub"]:
        base["pub"] = protocolo.PUB_DEFECTO
    if not base["cmd"]:
        base["cmd"] = protocolo.CMD_DEFECTO
    return base


def cargar_config(ruta):
    """Defectos + lo guardado en `ruta` (si existe y es JSON válido). Nunca lanza."""
    try:
        datos = json.loads(Path(ruta).read_text(encoding="utf-8-sig"))
        if not isinstance(datos, dict):
            datos = {}
    except (OSError, ValueError):
        datos = {}
    return _normalizar(datos)


def guardar_config(ruta, cfg):
    """Escribe la configuración (solo claves conocidas). Devuelve True si se pudo."""
    ruta = Path(ruta)
    try:
        ruta.parent.mkdir(parents=True, exist_ok=True)
        ruta.write_text(json.dumps(_normalizar(cfg), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return True
    except OSError:
        return False


def argumentos_gateway(cfg, python, extra=None):
    """`python -m gateway --modo … [--servidor … --topic …] --periodo … [--fuente …] --pub … --cmd … [--remoto]`."""
    cfg = _normalizar(cfg)
    args = [python, "-m", "gateway", "--modo", cfg["modo"]]
    if cfg["modo"] != "SIM":
        args += ["--servidor", cfg["servidor"], "--topic", cfg["topic"]]
    args += ["--periodo", str(int(cfg["periodoMs"]))]
    if cfg["modo"] != "SIM":
        args += ["--fuente", cfg["fuente"]]
    args += ["--pub", cfg["pub"], "--cmd", cfg["cmd"]]
    if cfg["remotoAlConectar"]:
        args.append("--remoto")
    args += [str(x) for x in (extra or [])]
    return args


def endpoint_ocupado(endpoint, timeout=0.3):
    """True si ya hay alguien escuchando en `tcp://host:puerto` de esta máquina (p. ej. un gateway que
    arrancó otra ventana, lab\\gateway.bat o una prueba). Solo mira direcciones locales; nunca lanza."""
    m = re.match(r"^tcp://([^:/]+):(\d+)$", str(endpoint).strip())
    if not m or m.group(1) not in ("127.0.0.1", "localhost", "*", "0.0.0.0"):
        return False
    host = "127.0.0.1" if m.group(1) in ("*", "0.0.0.0", "localhost") else m.group(1)
    try:
        with socket.create_connection((host, int(m.group(2))), timeout=timeout):
            return True
    except OSError:
        return False


def puente_configurado(cfg):
    """Hay al menos una URL (WebSocket o MQTT) para el puente."""
    return bool(str(cfg.get("urlServidor", "")).strip() or str(cfg.get("mqttUrl", "")).strip())


def argumentos_puente(cfg, python):
    """`python -m puente [--url …] [--mqtt …] --pub … --cmd … <extrasPuente tal cual>`.

    `--url` solo si `urlServidor` no está vacío; `--mqtt` si `mqttUrl` no está vacío (transporte
    MQTT de la sesión 07); `extrasPuente` se parte con shlex (posix=False: conserva las comillas
    tal como las escribió el usuario en Windows).
    """
    cfg = _normalizar(cfg)
    args = [python, "-m", "puente"]
    url = cfg["urlServidor"].strip()
    mqtt = cfg["mqttUrl"].strip()
    if url:
        args += ["--url", url]
    if mqtt:
        args += ["--mqtt", mqtt]
    args += ["--pub", cfg["pub"], "--cmd", cfg["cmd"]]
    extras = cfg["extrasPuente"].strip()
    if extras:
        args += shlex.split(extras, posix=False)
    return args


def argumentos_gemelo(cfg, python):
    """`python -m digital_twin.local --pub … --cmd … --host … --puerto … [--publico] [--sin-navegador]`.

    Nunca `--gateway`: el gateway ya lo maneja el HMI.
    """
    cfg = _normalizar(cfg)
    args = [python, "-m", "digital_twin.local", "--pub", cfg["pub"], "--cmd", cfg["cmd"],
            "--host", cfg["hostLocal"], "--puerto", str(int(cfg["puertoLocal"]))]
    if cfg["publicoLocal"]:
        args.append("--publico")
    if not cfg["abrirNavegador"]:
        args.append("--sin-navegador")
    return args


def url_gemelo(cfg):
    """URL del gemelo local para el navegador (0.0.0.0 → 127.0.0.1)."""
    host = str(cfg.get("hostLocal", "")).strip() or "127.0.0.1"
    if host in ("0.0.0.0", "::", "*"):
        host = "127.0.0.1"
    try:
        puerto = int(cfg.get("puertoLocal", 0)) or puerto_local_defecto()
    except (TypeError, ValueError):
        puerto = puerto_local_defecto()
    return "http://%s:%d/" % (host, puerto)


def resumen_clave(ruta):
    """'ab12… (43 caracteres)' de la clave guardada, '' si no hay (nunca la clave completa)."""
    try:
        clave = Path(ruta).read_text(encoding="utf-8-sig").strip()
    except OSError:
        return ""
    return "%s… (%d caracteres)" % (clave[:4], len(clave)) if clave else ""


def interpretar_json(texto):
    """Primer objeto JSON de `texto` (tolera texto basura antes y después, p. ej. avisos de pywin32).

    Si hay varios objetos se prefiere el primero con clave "ok". Sin JSON devuelve
    {"ok": False, "error": "sin JSON en la salida…"} para que el llamador no distinga casos.
    """
    texto = texto or ""
    decodificador = json.JSONDecoder()
    primero = None
    pos = texto.find("{")
    while pos >= 0:
        try:
            obj, _fin = decodificador.raw_decode(texto, pos)
        except ValueError:
            obj = None
        if isinstance(obj, dict):
            if "ok" in obj:
                return obj
            if primero is None:
                primero = obj
        pos = texto.find("{", pos + 1)
    if primero is not None:
        return primero
    lineas = [ln.strip() for ln in texto.strip().splitlines() if ln.strip()]
    detalle = (": " + lineas[-1][:200]) if lineas else ""
    return {"ok": False, "error": "sin JSON en la salida" + detalle}


def candidatos_python32(raiz, manual=""):
    """Intérpretes de 32 bits a probar, en orden: ruta manual → .venv32 → py -3.12-32.

    Devuelve [(etiqueta, argv), …]. `.venv32` solo entra si el ejecutable existe; los `py` se
    listan siempre (el lanzador decide si existen) y la comprobación los descarta si fallan.
    """
    cands = []
    manual = str(manual or "").strip()
    if manual:
        cands.append(("configurado", [manual]))
    venv = Path(raiz) / ".venv32" / "Scripts" / "python.exe"
    if venv.exists():
        cands.append((".venv32", [str(venv)]))
    cands.append(("py -3.12-32", ["py", "-3.12-32"]))
    return cands


CODIGO_COMPROBAR_32 = "import sys; print(sys.executable); print(sys.maxsize <= 2**32)"


def interpretar_comprobacion_32(texto):
    """Salida de CODIGO_COMPROBAR_32 → (ruta, es_32_bits) o (\"\", False)."""
    lineas = [ln.strip() for ln in (texto or "").splitlines() if ln.strip()]
    if len(lineas) < 2:
        return "", False
    return lineas[-2], lineas[-1] == "True"


def _hora():
    return time.strftime("%H:%M:%S")


# ============================================================================
# Modelo de la consola de subprocesos
# ============================================================================
class ModeloConsola(QAbstractListModel):
    """Últimas MAX_CONSOLA líneas de los subprocesos. Roles: hora, origen, linea. Filtro por origen."""

    ROL_HORA = Qt.UserRole + 1
    ROL_ORIGEN = Qt.UserRole + 2
    ROL_LINEA = Qt.UserRole + 3

    filtroChanged = Signal()
    totalChanged = Signal()

    def __init__(self, maximo=MAX_CONSOLA, parent=None):
        super().__init__(parent)
        self._maximo = maximo
        self._todas = deque()           # (hora, origen, linea), la más reciente al final
        self._visibles = []             # las que pasan el filtro
        self._filtro = []               # orígenes mostrados; vacío = todos

    # --- API de QAbstractListModel
    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self._visibles)

    def roleNames(self):
        return {self.ROL_HORA: b"hora", self.ROL_ORIGEN: b"origen", self.ROL_LINEA: b"linea"}

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid() or index.row() >= len(self._visibles):
            return None
        hora, origen, linea = self._visibles[index.row()]
        if role == self.ROL_HORA:
            return hora
        if role == self.ROL_ORIGEN:
            return origen
        if role in (self.ROL_LINEA, Qt.DisplayRole):
            return linea
        return None

    # --- uso desde Python
    def _pasa(self, fila):
        return not self._filtro or fila[1] in self._filtro

    def agregar(self, origen, linea):
        fila = (_hora(), str(origen), str(linea))
        self._todas.append(fila)
        if len(self._todas) > self._maximo:
            vieja = self._todas.popleft()
            if self._pasa(vieja) and self._visibles and self._visibles[0] is vieja:
                self.beginRemoveRows(QModelIndex(), 0, 0)
                del self._visibles[0]
                self.endRemoveRows()
        if self._pasa(fila):
            n = len(self._visibles)
            self.beginInsertRows(QModelIndex(), n, n)
            self._visibles.append(fila)
            self.endInsertRows()
        self.totalChanged.emit()

    def lineas(self, origen=None):
        return [f[2] for f in self._todas if origen is None or f[1] == origen]

    # --- uso desde QML
    def _get_filtro(self):
        return list(self._filtro)

    def _get_total(self):
        return len(self._todas)

    filtro = Property("QVariantList", _get_filtro, notify=filtroChanged)
    total = Property(int, _get_total, notify=totalChanged)

    @Slot(str)
    def alternarOrigen(self, origen):
        origen = str(origen)
        if origen in self._filtro:
            self._filtro.remove(origen)
        else:
            self._filtro.append(origen)
        self.beginResetModel()
        self._visibles = [f for f in self._todas if self._pasa(f)]
        self.endResetModel()
        self.filtroChanged.emit()

    @Slot()
    def limpiar(self):
        self.beginResetModel()
        self._todas.clear()
        self._visibles = []
        self.endResetModel()
        self.totalChanged.emit()


# ============================================================================
# Subproceso vigilado (gateway, puente, gemelo)
# ============================================================================
class _Subproceso(QObject):
    """QProcess con lectura por líneas a la consola, parada en dos tiempos y estado para QML.

    Estados: parado | arrancando | corriendo | error. `error` = terminó solo con código ≠ 0 o no
    se pudo lanzar. Si lo paramos nosotros (terminate → PLAZO_TERMINAR_MS → kill) queda `parado`
    aunque el código de salida sea raro (en Windows kill() devuelve 62097).
    """

    estadoCambiado = Signal(str)
    terminado = Signal(int, bool, str)        # código, parado por nosotros, última línea de stderr
    linea = Signal(str, str)                  # origen, línea

    def __init__(self, origen, raiz, parent=None):
        super().__init__(parent)
        self.origen = origen
        self.raiz = str(raiz)
        self.estado = "parado"
        self.proc = None
        self.argv = []
        self._parando = False
        self._ultima_err = ""
        self._buf = {"out": "", "err": ""}
        self._timer_kill = QTimer(self)
        self._timer_kill.setSingleShot(True)
        self._timer_kill.timeout.connect(self._matar)

    # --- estado
    def _poner_estado(self, estado):
        if estado != self.estado:
            self.estado = estado
            self.estadoCambiado.emit(estado)

    def vivo(self):
        return self.proc is not None and self.proc.state() != PROCESO_PARADO

    # --- arranque y parada
    def arrancar(self, argv):
        """Lanza `argv` con cwd = raíz del repo y salida sin búfer en UTF-8. False si ya corre."""
        if self.vivo():
            return False
        self._desechar()
        self.argv = list(argv)
        self._parando = False
        self._ultima_err = ""
        self._buf = {"out": "", "err": ""}
        p = QProcess(self)
        p.setWorkingDirectory(self.raiz)
        p.setProcessEnvironment(entorno_subproceso())
        p.readyReadStandardOutput.connect(self._leer_out)
        p.readyReadStandardError.connect(self._leer_err)
        p.started.connect(self._al_arrancar)
        p.finished.connect(self._al_terminar)
        p.errorOccurred.connect(self._al_error)
        self.proc = p
        self._poner_estado("arrancando")
        self.linea.emit("hmi", "lanzando %s: %s" % (self.origen, " ".join(self.argv)))
        p.start(self.argv[0], self.argv[1:])
        return True

    def parar(self):
        """Asíncrono: terminate ahora, kill a los PLAZO_TERMINAR_MS si sigue vivo."""
        if not self.vivo():
            return
        self._parando = True
        self.proc.terminate()
        self._timer_kill.start(PLAZO_TERMINAR_MS)

    def parar_sincrono(self, plazo_ms=PLAZO_TERMINAR_MS):
        """Al cerrar la aplicación: espera de verdad a que el subproceso muera."""
        if not self.vivo():
            return
        self._parando = True
        self._timer_kill.stop()
        self.proc.terminate()
        if not self.proc.waitForFinished(plazo_ms):
            self.proc.kill()
            self.proc.waitForFinished(2000)

    def _matar(self):
        if self.vivo():
            self.linea.emit("hmi", "%s no terminó en %.0f s: kill" % (self.origen, PLAZO_TERMINAR_MS / 1000.0))
            self.proc.kill()

    def _desechar(self):
        if self.proc is not None:
            self.proc.deleteLater()
            self.proc = None

    # --- señales de QProcess
    def _al_arrancar(self):
        self._poner_estado("corriendo")

    def _leer(self, canal, datos):
        texto = self._buf[canal] + bytes(datos).decode("utf-8", errors="replace")
        partes = texto.split("\n")
        self._buf[canal] = partes.pop()
        for ln in partes:
            ln = ln.rstrip("\r")
            if not ln.strip():
                continue
            if canal == "err":
                self._ultima_err = ln.strip()
            self.linea.emit(self.origen, ln)

    def _leer_out(self):
        if self.proc is not None:
            self._leer("out", self.proc.readAllStandardOutput().data())

    def _leer_err(self):
        if self.proc is not None:
            self._leer("err", self.proc.readAllStandardError().data())

    def _vaciar(self):
        self._leer_out()
        self._leer_err()
        for canal in ("out", "err"):
            resto = self._buf[canal].strip()
            self._buf[canal] = ""
            if resto:
                if canal == "err":
                    self._ultima_err = resto
                self.linea.emit(self.origen, resto)

    def _al_terminar(self, codigo=0, estado_salida=None):
        self._timer_kill.stop()
        self._vaciar()
        codigo = int(codigo)
        normal = estado_salida is None or estado_salida == PROCESO_SALIDA_NORMAL
        if self._parando or (codigo == 0 and normal):
            self.linea.emit("hmi", "%s terminado (código %d)" % (self.origen, codigo))
            self._poner_estado("parado")
        else:
            self.linea.emit("hmi", "%s terminó con código %d%s" % (self.origen, codigo,
                                                                    (": " + self._ultima_err) if self._ultima_err else ""))
            self._poner_estado("error")
        self.terminado.emit(codigo, self._parando, self._ultima_err)

    def _al_error(self, error):
        if error != PROCESO_FALLO_ARRANQUE:
            return                     # Crashed etc. llegan también por finished()
        self._timer_kill.stop()
        self._ultima_err = "no se pudo lanzar %s (¿existe el intérprete?)" % (self.argv[0] if self.argv else "?")
        self.linea.emit("hmi", "%s: %s" % (self.origen, self._ultima_err))
        self._poner_estado("error")
        self.terminado.emit(-1, self._parando, self._ultima_err)


def entorno_subproceso():
    """Entorno de los subprocesos: UTF-8 y sin búfer para que la consola vea cada línea al instante."""
    env = QProcessEnvironment.systemEnvironment()
    env.insert("PYTHONIOENCODING", "utf-8")
    env.insert("PYTHONUNBUFFERED", "1")
    return env


def _prop_cfg(tipo, clave, senal):
    """Propiedad de configuración de lectura/escritura (QML ↔ datos/conexion.json)."""
    return Property(tipo, lambda self: self._cfg[clave], lambda self, v: self._poner_cfg(clave, v), notify=senal)


def _prop_ro(tipo, atributo, senal):
    return Property(tipo, lambda self: getattr(self, atributo), notify=senal)


# ============================================================================
# Conexion
# ============================================================================
class Conexion(QObject):
    """Contexto raíz `conexion`. Ver el docstring del módulo y mds/ARQUITECTURA.md §6.4."""

    configChanged = Signal()
    estadoChanged = Signal()
    mensajeChanged = Signal()
    gatewayEstadoChanged = Signal()
    puenteEstadoChanged = Signal()
    gemeloEstadoChanged = Signal()
    gatewayPropioChanged = Signal()
    python32Changed = Signal()
    claveExisteChanged = Signal()
    listasChanged = Signal()
    buscandoChanged = Signal()
    resultadoLecturaChanged = Signal()
    mensajeOpcChanged = Signal()
    urlGemeloChanged = Signal()
    vinculoChanged = Signal()
    _vinculoTerminado = Signal(object)        # resultado del hilo de vinculación → hilo de la GUI

    # --- configuración (lectura/escritura desde QML)
    modo = _prop_cfg(str, "modo", configChanged)
    servidor = _prop_cfg(str, "servidor", configChanged)
    topic = _prop_cfg(str, "topic", configChanged)
    periodoMs = _prop_cfg(int, "periodoMs", configChanged)
    fuente = _prop_cfg(str, "fuente", configChanged)
    lanzarGateway = _prop_cfg(bool, "lanzarGateway", configChanged)
    pub = _prop_cfg(str, "pub", configChanged)
    cmd = _prop_cfg(str, "cmd", configChanged)
    destinoWeb = _prop_cfg(str, "destinoWeb", configChanged)
    urlServidor = _prop_cfg(str, "urlServidor", configChanged)
    mqttUrl = _prop_cfg(str, "mqttUrl", configChanged)
    extrasPuente = _prop_cfg(str, "extrasPuente", configChanged)
    hostLocal = _prop_cfg(str, "hostLocal", configChanged)
    puertoLocal = _prop_cfg(int, "puertoLocal", configChanged)
    abrirNavegador = _prop_cfg(bool, "abrirNavegador", configChanged)
    publicoLocal = _prop_cfg(bool, "publicoLocal", configChanged)
    remotoAlConectar = _prop_cfg(bool, "remotoAlConectar", configChanged)
    python32Manual = _prop_cfg(str, "python32", configChanged)
    itemPrueba = _prop_cfg(str, "itemPrueba", configChanged)
    usuarioServidor = _prop_cfg(str, "usuarioServidor", configChanged)

    # --- solo lectura
    python32 = _prop_ro(str, "_python32", python32Changed)
    python32Disponible = _prop_ro(bool, "_python32_disponible", python32Changed)
    python32Buscando = _prop_ro(bool, "_python32_buscando", python32Changed)
    estado = _prop_ro(str, "_estado", estadoChanged)
    mensaje = _prop_ro(str, "_mensaje", mensajeChanged)
    gatewayPropio = _prop_ro(bool, "_gateway_propio", gatewayPropioChanged)
    servidores = _prop_ro("QVariantList", "_servidores", listasChanged)
    topics = _prop_ro("QVariantList", "_topics", listasChanged)
    archivos = _prop_ro("QVariantList", "_archivos", listasChanged)
    rutaArchivos = _prop_ro(str, "_ruta_archivos", listasChanged)
    items = _prop_ro("QVariantList", "_items", listasChanged)
    buscando = _prop_ro(bool, "_buscando", buscandoChanged)
    resultadoLectura = _prop_ro("QVariantMap", "_resultado", resultadoLecturaChanged)
    mensajeOpc = _prop_ro(str, "_mensaje_opc", mensajeOpcChanged)
    vinculando = _prop_ro(bool, "_vinculando", vinculoChanged)
    mensajeVinculo = _prop_ro(str, "_mensaje_vinculo", vinculoChanged)
    vinculoOk = _prop_ro(bool, "_vinculo_ok", vinculoChanged)

    # constantes para la ventana
    pythonHmi = Property(str, lambda self: sys.executable, constant=True)
    rutaClave = Property(str, lambda self: str(self._ruta_clave), constant=True)
    rutaConfig = Property(str, lambda self: str(self._ruta_config), constant=True)
    modos = Property("QVariantList", lambda self: list(protocolo.MODOS), constant=True)
    fuentes = Property("QVariantList", lambda self: list(protocolo.FUENTES_OPC), constant=True)
    destinos = Property("QVariantList", lambda self: list(DESTINOS_WEB), constant=True)
    origenesConsola = Property("QVariantList", lambda self: list(ORIGENES_CONSOLA), constant=True)
    puertoLocalDefecto = Property(int, lambda self: puerto_local_defecto(), constant=True)
    urlServidorDefecto = Property(str, lambda self: URL_SERVIDOR_DEFECTO, constant=True)
    autoAbrir = Property(bool, lambda self: self._auto_abrir, constant=True)
    gatewayExterno = Property(bool, lambda self: self._gateway_externo, constant=True)
    consola = Property(QObject, lambda self: self._consola, constant=True)

    def __init__(self, planta, args=None, parent=None, ruta_config=None, raiz=None, detectar_python32=True):
        super().__init__(parent)
        self._planta = planta
        self._raiz = Path(raiz or RAIZ)
        self._ruta_config = Path(ruta_config or RUTA_CONFIG)
        self._ruta_clave = self._raiz / "datos" / "puente.clave"
        self._cfg = cargar_config(self._ruta_config)
        # Endpoints dados en la línea de órdenes del HMI (--pub/--cmd) mandan sobre lo guardado.
        for clave, defecto in (("pub", protocolo.PUB_DEFECTO), ("cmd", protocolo.CMD_DEFECTO)):
            v = getattr(args, clave, None)
            if v and v != defecto:
                self._cfg[clave] = str(v)
        self._gateway_externo = bool(getattr(args, "lanzar_gateway", None) or getattr(args, "gateway_falso", False))
        self._auto_abrir = not (self._gateway_externo or bool(getattr(args, "sin_conexion", False)))
        self.extra_gateway = []           # argumentos extra del gateway (pruebas: ["--sin-historial"])

        self._estado = "desconectado"
        self._mensaje = ""
        self._python32 = ""
        self._python32_disponible = False
        self._python32_buscando = False
        self._gateway_propio = False
        self._servidores = []
        self._topics = []
        self._archivos = []
        self._ruta_archivos = ""
        self._items = []
        self._buscando = False
        self._resultado = {}
        self._mensaje_opc = ""
        self._desconectando = False
        self._web_arrancado = False
        self._candidatos = []
        self._deteccion = None
        self._descubrimiento = None
        self._modo_pedido = None          # modo elegido cuando se reutilizó un gateway que ya corría
        self._vinculando = False
        self._mensaje_vinculo = ""
        self._vinculo_ok = False
        self._vinculoTerminado.connect(self._al_vincular, Qt.QueuedConnection)

        self._consola = ModeloConsola(parent=self)
        self._gateway = _Subproceso("gateway", self._raiz, self)
        self._puente = _Subproceso("puente", self._raiz, self)
        self._gemelo = _Subproceso("gemelo", self._raiz, self)
        for sp in (self._gateway, self._puente, self._gemelo):
            sp.linea.connect(self._consola.agregar)
        self._gateway.estadoCambiado.connect(lambda _e: self.gatewayEstadoChanged.emit())
        self._puente.estadoCambiado.connect(lambda _e: self.puenteEstadoChanged.emit())
        self._gemelo.estadoCambiado.connect(lambda _e: self.gemeloEstadoChanged.emit())
        self._gateway.terminado.connect(self._al_terminar_gateway)
        self._puente.terminado.connect(self._al_terminar_web)
        self._gemelo.terminado.connect(self._al_terminar_web)

        self._plazo = QTimer(self)
        self._plazo.setSingleShot(True)
        self._plazo.timeout.connect(self._al_vencer_plazo)
        self._timer_web = QTimer(self)
        self._timer_web.setSingleShot(True)
        self._timer_web.timeout.connect(self.arrancarWeb)

        self._planta.gatewayVivoChanged.connect(self._al_cambiar_gateway_vivo)
        self._planta.conectadoChanged.connect(self._al_cambiar_conectado)

        self._consola.agregar("hmi", "HMI en %s (%d bits)" % (sys.executable, 64 if sys.maxsize > 2 ** 32 else 32))
        if self._gateway_externo:
            self._consola.agregar("hmi", "el HMI arrancó con --lanzar-gateway/--gateway-falso: la ventana no lanza otro gateway")
        if detectar_python32:
            self.comprobarPython32()

    # ------------------------------------------------------------------ propiedades derivadas
    gatewayEstado = Property(str, lambda self: self._gateway.estado, notify=gatewayEstadoChanged)
    puenteEstado = Property(str, lambda self: self._puente.estado, notify=puenteEstadoChanged)
    gemeloEstado = Property(str, lambda self: self._gemelo.estado, notify=gemeloEstadoChanged)
    claveExiste = Property(bool, lambda self: self._ruta_clave.exists(), notify=claveExisteChanged)
    claveResumen = Property(str, lambda self: resumen_clave(self._ruta_clave), notify=claveExisteChanged)
    urlGemelo = Property(str, lambda self: url_gemelo(self._cfg), notify=urlGemeloChanged)

    # ------------------------------------------------------------------ configuración
    def _poner_cfg(self, clave, valor):
        try:
            if clave in _CLAVES_BOOL:
                valor = bool(valor)
            elif clave in _CLAVES_INT:
                valor = int(valor)
            else:
                valor = str(valor)
        except (TypeError, ValueError):
            return
        if self._cfg.get(clave) == valor:
            return
        viejo = self._cfg.get(clave)
        self._cfg[clave] = valor
        if clave == "modo":
            # Topic y periodo siguen al modo mientras el usuario no los haya cambiado a mano.
            if self._cfg["topic"] in ("", topic_defecto(viejo)):
                self._cfg["topic"] = topic_defecto(valor)
            if int(self._cfg["periodoMs"]) in (0, periodo_defecto(viejo)):
                self._cfg["periodoMs"] = periodo_defecto(valor)
        self.configChanged.emit()
        if clave in ("hostLocal", "puertoLocal"):
            self.urlGemeloChanged.emit()
        if clave == "destinoWeb":
            self.claveExisteChanged.emit()
        if clave == "python32":
            self.comprobarPython32()

    def configuracion(self):
        """Copia de la configuración actual (pruebas)."""
        return dict(self._cfg)

    @Slot()
    def guardar(self):
        if guardar_config(self._ruta_config, self._cfg):
            self._poner_mensaje("Configuración guardada en %s" % self._ruta_config)
        else:
            self._poner_mensaje("No se pudo guardar %s" % self._ruta_config)
        self.claveExisteChanged.emit()

    # ------------------------------------------------------------------ estado y mensajes
    def _poner_estado(self, estado, mensaje=None):
        if estado != self._estado:
            self._estado = estado
            self.estadoChanged.emit()
        if mensaje is not None:
            self._poner_mensaje(mensaje)
        self._consola.agregar("hmi", "estado: %s%s" % (estado, (" — " + mensaje) if mensaje else ""))

    def _poner_mensaje(self, mensaje):
        mensaje = str(mensaje)
        if mensaje != self._mensaje:
            self._mensaje = mensaje
            self.mensajeChanged.emit()

    def _poner_mensaje_opc(self, mensaje):
        mensaje = str(mensaje)
        if mensaje != self._mensaje_opc:
            self._mensaje_opc = mensaje
            self.mensajeOpcChanged.emit()

    def _poner_buscando(self, v):
        if v != self._buscando:
            self._buscando = v
            self.buscandoChanged.emit()

    def _poner_gateway_propio(self, v):
        if v != self._gateway_propio:
            self._gateway_propio = v
            self.gatewayPropioChanged.emit()

    # ------------------------------------------------------------------ Python de 32 bits
    @Slot()
    def comprobarPython32(self):
        """Prueba los candidatos de `candidatos_python32` uno a uno (QProcess asíncrono)."""
        if self._deteccion is not None:
            return
        self._candidatos = candidatos_python32(self._raiz, self._cfg.get("python32", ""))
        self._python32_buscando = True
        self.python32Changed.emit()
        self._probar_siguiente_candidato()

    def _probar_siguiente_candidato(self):
        if not self._candidatos:
            self._deteccion = None
            self._fijar_python32("", False)
            return
        etiqueta, argv = self._candidatos.pop(0)
        p = QProcess(self)
        p.setWorkingDirectory(str(self._raiz))
        p.setProcessEnvironment(entorno_subproceso())
        p._hecho = False
        p.finished.connect(lambda *_a, p=p, e=etiqueta: self._al_terminar_candidato(p, e))
        p.errorOccurred.connect(lambda err, p=p, e=etiqueta: self._al_fallar_candidato(p, e, err))
        QTimer.singleShot(PLAZO_PYTHON32_MS, lambda p=p: self._matar_si_vivo(p))
        self._deteccion = p
        p.start(argv[0], argv[1:] + ["-c", CODIGO_COMPROBAR_32])

    def _al_terminar_candidato(self, p, etiqueta):
        if p._hecho:
            return
        p._hecho = True
        salida = p.readAllStandardOutput().data().decode("utf-8", errors="replace")
        p.deleteLater()
        ruta, es32 = interpretar_comprobacion_32(salida)
        if ruta and es32 and p.exitCode() == 0:
            self._deteccion = None
            self._candidatos = []
            self._fijar_python32(ruta, True, etiqueta)
            return
        if ruta and not es32:
            self._consola.agregar("hmi", "%s es de 64 bits (%s): no sirve para OPC DA" % (etiqueta, ruta))
        self._probar_siguiente_candidato()

    def _al_fallar_candidato(self, p, etiqueta, error):
        if error != PROCESO_FALLO_ARRANQUE or p._hecho:
            return
        p._hecho = True
        p.deleteLater()
        self._probar_siguiente_candidato()

    def _matar_si_vivo(self, p):
        try:
            if p.state() != PROCESO_PARADO:
                p.kill()
        except RuntimeError:
            pass                           # ya destruido

    def _fijar_python32(self, ruta, disponible, etiqueta=""):
        self._python32 = ruta
        self._python32_disponible = bool(disponible)
        self._python32_buscando = False
        self.python32Changed.emit()
        if disponible:
            self._consola.agregar("hmi", "Python de 32 bits (%s): %s" % (etiqueta, ruta))
        else:
            self._consola.agregar("hmi", "sin Python de 32 bits: EMULATE/REAL y el descubrimiento OPC no están disponibles")

    # ------------------------------------------------------------------ conectar / desconectar
    @Slot()
    def conectar(self):
        """Guarda → (gateway propio) → planta.conectar → espera snapshot → envío web."""
        if self._estado in ("conectando", "conectado") and not self._gateway_propio and self._planta.gatewayVivo:
            # Ya recibe snapshots de un gateway ajeno (el HMI se conectó solo al arrancar): no hay nada que
            # lanzar; se usa ese y se arranca el envío web elegido (antes: «desconecta primero»).
            self._usar_gateway_en_marcha()
            return
        if self._estado in ("conectando", "conectado") and (self._gateway_propio or self._planta.gatewayVivo):
            self._poner_mensaje("Ya hay una conexión en curso: desconecta primero")
            return
        guardar_config(self._ruta_config, self._cfg)
        self.claveExisteChanged.emit()
        cfg = self._cfg
        opc = cfg["modo"] != "SIM"
        lanzar = bool(cfg["lanzarGateway"]) and not self._gateway_externo
        self._modo_pedido = None
        if lanzar and endpoint_ocupado(cfg["pub"]):
            # Arrancar otro en los mismos puertos fallaría («¿otro gateway en marcha?»): se usa el que hay.
            lanzar = False
            self._modo_pedido = cfg["modo"]
            self._consola.agregar("hmi", "ya hay un gateway escuchando en %s: se usa ese en vez de arrancar otro"
                                  % cfg["pub"])
        if lanzar and opc and not self._python32_disponible:
            self._poner_estado("error", "No hay Python de 32 bits para el gateway OPC: instala .venv32 "
                                        "(lab\\instalar.bat), py -3.12-32 o indica la ruta del intérprete")
            return
        self._desconectando = False
        self._web_arrancado = False
        self._timer_web.stop()
        self._poner_gateway_propio(lanzar)
        if lanzar:
            python = self._python32 if opc else sys.executable
            self._poner_estado("conectando", "Arrancando el gateway %s…" % cfg["modo"])
            if not self._gateway.arrancar(argumentos_gateway(cfg, python, self.extra_gateway)):
                self._poner_estado("error", "El gateway anterior sigue en marcha; espera a que termine")
                return
        elif self._modo_pedido:
            self._poner_estado("conectando", "Ya hay un gateway en marcha en %s: se usa ese…" % cfg["pub"])
        else:
            self._poner_estado("conectando", "Conectando con el gateway en %s…" % cfg["pub"])
        self._planta.conectar(cfg["pub"], cfg["cmd"])
        self._plazo.start(PLAZO_SNAPSHOT_MS)
        if not lanzar:
            self._timer_web.start(RETARDO_WEB_AJENO_MS)
        if cfg["destinoWeb"] == "servidor" and not puente_configurado(cfg):
            self._poner_mensaje("indica la URL WebSocket o la URL MQTT del servidor")

    def _usar_gateway_en_marcha(self):
        """Conectado a un gateway que no lanzó este HMI: guarda, avisa si el modo no es el elegido y
        arranca el envío web elegido (parando el otro destino si corría)."""
        guardar_config(self._ruta_config, self._cfg)
        self.claveExisteChanged.emit()
        cfg = self._cfg
        modo = self._planta.modo or "?"
        if modo != cfg["modo"]:
            self._poner_mensaje("El gateway en marcha en %s está en modo %s, no %s: desconecta y ciérralo para "
                                "arrancar otro, o elige %s" % (cfg["pub"], modo, cfg["modo"], modo))
            return
        destino = cfg["destinoWeb"]
        if destino != "servidor":
            self._puente.parar()
        if destino != "local":
            self._gemelo.parar()
        texto = "Usando el gateway en marcha · modo %s · %s" % (modo, cfg["pub"])
        if destino != "ninguno":
            texto += " · envío al %s" % ("gemelo local" if destino == "local" else "servidor web")
        self._poner_estado(self._estado, texto)
        if destino != "ninguno":
            self._web_arrancado = False
            self.arrancarWeb()

    def _esperar_escrituras(self):
        """Antes de terminar el gateway propio: que no se quede un pulso STARTV/STOPV/RESETV en 1 en el PLC.

        En Windows el gateway de consola muere por kill() (terminate no lo cierra): si eso cae entre el 1
        y el 0 de un pulso, el bit queda en 1. Aquí solo se ESPERA (hasta PLAZO_ESCRITURAS_MS) a que el
        gateway termine lo que tiene pendiente, que él mismo publica en cada snapshot; no se escribe nada
        ni se cambia cómo escribe el gateway. Devuelve True si quedó todo escrito."""
        if not (self._gateway_propio and self._planta.gatewayVivo):
            return True
        app = QCoreApplication.instance()
        limite = time.monotonic() + PLAZO_ESCRITURAS_MS / 1000.0
        while time.monotonic() < limite:
            if not self._planta.escrituras_en_curso():
                return True
            if app is not None:
                app.processEvents()
            time.sleep(0.01)
        self._consola.agregar("hmi", "aviso: el gateway seguía con escrituras pendientes al cerrarlo (%d ms)"
                              % PLAZO_ESCRITURAS_MS)
        return False

    @Slot()
    def desconectar(self):
        """Para puente/gemelo, desuscribe Planta y termina el gateway solo si lo arrancó este HMI."""
        self._esperar_escrituras()          # con Planta aún conectada, que sigue recibiendo snapshots
        self._desconectando = True
        try:
            self._plazo.stop()
            self._timer_web.stop()
            self.pararWeb()
            self._planta.desconectar()
            if self._gateway_propio:
                self._gateway.parar()
            self._poner_gateway_propio(False)
            self._poner_estado("desconectado", "Desconectado")
        finally:
            self._desconectando = False

    def cerrar(self):
        """Al salir del HMI: termina todos los subprocesos propios (terminate → 3 s → kill)."""
        self._esperar_escrituras()
        self._desconectando = True
        self._plazo.stop()
        self._timer_web.stop()
        for sp in (self._puente, self._gemelo, self._gateway):
            sp.parar_sincrono()
        for p in (self._descubrimiento, self._deteccion):
            if p is not None:
                self._matar_si_vivo(p)
        self._descubrimiento = None
        self._deteccion = None

    # --- reacciones a Planta y a los subprocesos
    def _al_cambiar_gateway_vivo(self):
        if self._desconectando:
            return
        if self._planta.gatewayVivo:
            if self._estado == "conectando":
                self._poner_mensaje("Gateway en línea (%s); esperando lectura del PLC…" % (self._planta.modo or "?"))
            if not self._web_arrancado and self._estado in ("conectando", "conectado"):
                self._timer_web.stop()
                self.arrancarWeb()
        elif self._estado == "conectado":
            self._poner_estado("error", "El gateway dejó de publicar snapshots")

    def _al_cambiar_conectado(self):
        if self._desconectando:
            return
        if self._planta.conectado:
            self._plazo.stop()
            if self._estado != "conectado":
                if self._estado == "desconectado":
                    # El HMI se conectó solo a un gateway que ya corría (lab\gateway.bat, otra ventana). Si hay
                    # un destino web guardado, el envío arranca ya: «que envíe todo directo» (sesión 14). No en
                    # --lanzar-gateway/--gateway-falso (pruebas), que llevan su propio --lanzar-puente.
                    destino = self._cfg["destinoWeb"]
                    auto = destino != "ninguno" and not self._gateway_externo and not self._web_arrancado
                    texto = "Conectado a un gateway en marcha · modo %s · %s" % (self._planta.modo, self._planta.pubEndpoint)
                    if auto:
                        texto += " · enviando al %s" % ("gemelo local" if destino == "local" else "servidor web")
                    else:
                        texto += " · para el gemelo elige el destino y pulsa «Arrancar envío»"
                    self._poner_estado("conectado", texto)
                    if auto:
                        self._web_arrancado = True      # que _al_cambiar_gateway_vivo no lo arranque otra vez
                        self.arrancarWeb()
                    return
                else:
                    texto = "Conectado · modo %s · %s" % (self._planta.modo, self._planta.pubEndpoint)
                    if self._modo_pedido and self._planta.modo != self._modo_pedido:
                        texto += " · OJO: el gateway que ya corría está en %s, no en %s" % (
                            self._planta.modo, self._modo_pedido)
                self._poner_estado("conectado", texto)
        elif self._estado == "conectado" and self._planta.gatewayVivo:
            self._poner_estado("conectando", "Gateway en línea pero sin lectura del PLC; el gateway reintenta…")

    def _al_vencer_plazo(self):
        if self._estado != "conectando":
            return
        if self._planta.gatewayVivo:
            self._poner_estado("error", "El gateway está en línea pero no hay lectura del PLC tras %d s: "
                                        "revisa RSLinx, el servidor y el topic (ver consola)" % (PLAZO_SNAPSHOT_MS // 1000))
        elif self._modo_pedido:
            self._poner_estado("error", "Algo escucha en %s pero no publica snapshots en %d s: ¿otro programa usa "
                                        "ese puerto? Ciérralo o cambia PUB/CMD" % (self._cfg["pub"], PLAZO_SNAPSHOT_MS // 1000))
        else:
            self._poner_estado("error", "No llegó ningún snapshot del gateway en %d s (%s)"
                               % (PLAZO_SNAPSHOT_MS // 1000, self._cfg["pub"]))
            if self._gateway_propio:
                self._gateway.parar()

    def _al_terminar_gateway(self, codigo, parado_por_nosotros, ultima_err):
        if parado_por_nosotros or self._desconectando:
            return
        self._plazo.stop()
        self._timer_web.stop()
        self.pararWeb()
        self._poner_gateway_propio(False)
        if codigo != 0:
            self._poner_estado("error", ultima_err or ("El gateway terminó con código %d" % codigo))
        else:
            self._poner_estado("desconectado", "El gateway terminó")

    def _al_terminar_web(self, codigo, parado_por_nosotros, ultima_err):
        if parado_por_nosotros or self._desconectando or codigo == 0:
            return
        self._poner_mensaje(ultima_err or ("El envío de datos terminó con código %d" % codigo))

    # ------------------------------------------------------------------ envío de datos (web)
    @Slot()
    def arrancarWeb(self):
        """Puente (servidor web) o gemelo local según `destinoWeb`. Idempotente."""
        cfg = self._cfg
        destino = cfg["destinoWeb"]
        self._web_arrancado = True
        if destino == "servidor":
            if not puente_configurado(cfg):
                self._poner_mensaje("indica la URL WebSocket o la URL MQTT del servidor")
                return
            if not self._ruta_clave.exists():
                self._consola.agregar("hmi", "aviso: no existe %s; el puente no podrá autenticarse "
                                             "(usa «Vincular» con una cuenta admin del gemelo o pega la clave)"
                                      % self._ruta_clave)
                self._poner_vinculo(False, "falta la clave del puente: vincula con una cuenta admin o pégala")
            self._puente.arrancar(argumentos_puente(cfg, sys.executable))
        elif destino == "local":
            self._gemelo.arrancar(argumentos_gemelo(cfg, sys.executable))
            self.urlGemeloChanged.emit()

    # ------------------------------------------------------------------ vinculación con el servidor web
    def _poner_vinculo(self, vinculando, mensaje, ok=False):
        self._vinculando, self._mensaje_vinculo, self._vinculo_ok = bool(vinculando), str(mensaje), bool(ok)
        self.vinculoChanged.emit()

    @Slot(str, str)
    def vincularServidor(self, usuario, contrasena):
        """Pide la clave del puente al servidor (cuenta admin del gemelo) y la guarda en datos/puente.clave.

        La petición va en un hilo aparte: con internet lento puede tardar hasta 10 s y la pantalla no
        debe congelarse. La contraseña no se guarda en ningún sitio."""
        if self._vinculando:
            return
        usuario = str(usuario).strip()
        if not usuario or not contrasena:
            self._poner_vinculo(False, "escribe el usuario y la contraseña de una cuenta admin del gemelo")
            return
        url = self._cfg["urlServidor"].strip() or URL_SERVIDOR_DEFECTO
        try:
            base = vincular.url_https(url)
        except ValueError as e:
            self._poner_vinculo(False, str(e))
            return
        self._poner_vinculo(True, "pidiendo la clave a %s…" % base)
        self._consola.agregar("hmi", "vinculando con %s como %s" % (base, usuario))
        ruta = self._ruta_clave

        def trabajo():
            r = vincular.obtener_clave(url, usuario, contrasena)
            if r.get("ok"):
                try:
                    vincular.guardar_clave(ruta, r["clave"])
                except (OSError, ValueError) as e:
                    r = {"ok": False, "msg": "no se pudo guardar %s: %s" % (ruta, e)}
            r.pop("clave", None)            # la clave no viaja a la GUI ni a la consola
            if r.get("ok"):
                r["usuario"] = usuario
            self._vinculoTerminado.emit(r)

        threading.Thread(target=trabajo, name="hmi-vincular", daemon=True).start()

    @Slot(str)
    def guardarClave(self, texto):
        """Guarda una clave pegada a mano (la que muestra el servidor con `servidor_web clave`)."""
        try:
            vincular.guardar_clave(self._ruta_clave, str(texto))
        except (OSError, ValueError) as e:
            self._poner_vinculo(False, "clave no guardada: %s" % e)
            return
        self._al_vincular({"ok": True, "manual": True})

    def _al_vincular(self, r):
        self.claveExisteChanged.emit()
        if not r.get("ok"):
            self._poner_vinculo(False, r.get("msg") or "no se pudo vincular")
            self._consola.agregar("hmi", "vinculación fallida: %s" % (r.get("msg") or "?"))
            return
        texto = "clave guardada en %s" % self._ruta_clave
        if not r.get("manual"):
            texto = "vinculado con %s · %s" % (r.get("url", "el servidor"), texto)
            if r.get("usuario"):
                self._poner_cfg("usuarioServidor", r["usuario"])   # el usuario se recuerda; la contraseña no
                guardar_config(self._ruta_config, self._cfg)
        self._consola.agregar("hmi", texto)
        if self._cfg["destinoWeb"] == "servidor" and self._estado in ("conectando", "conectado"):
            # El puente lee la clave al arrancar: se reinicia para usar la nueva.
            texto += " · reiniciando el envío al servidor"
            if self._puente.vivo():
                self._puente.parar()
                QTimer.singleShot(PLAZO_TERMINAR_MS + 300, self.arrancarWeb)
            else:
                self.arrancarWeb()
        self._poner_vinculo(False, texto, ok=True)

    @Slot()
    def pararWeb(self):
        self._timer_web.stop()
        self._puente.parar()
        self._gemelo.parar()

    @Slot()
    def abrirGemelo(self):
        QDesktopServices.openUrl(QUrl(url_gemelo(self._cfg)))

    # ------------------------------------------------------------------ descubrimiento OPC
    def _descubrir(self, argumentos, al_terminar, descripcion):
        if self._buscando:
            self._poner_mensaje_opc("Hay una búsqueda en curso; espera a que termine")
            return False
        if not self._python32_disponible:
            self._poner_mensaje_opc("Sin Python de 32 bits no se puede consultar RSLinx (OPC DA es COM de 32 bits)")
            return False
        p = QProcess(self)
        p.setWorkingDirectory(str(self._raiz))
        p.setProcessEnvironment(entorno_subproceso())
        p._hecho = False
        p.finished.connect(lambda *_a, p=p: self._al_terminar_descubrimiento(p, al_terminar))
        p.errorOccurred.connect(lambda err, p=p: self._al_fallar_descubrimiento(p, err))
        QTimer.singleShot(PLAZO_DESCUBRIR_MS, lambda p=p: self._matar_si_vivo(p))
        self._descubrimiento = p
        self._poner_buscando(True)
        self._poner_mensaje_opc(descripcion)
        self._consola.agregar("hmi", "diagnóstico OPC: %s" % " ".join(argumentos))
        p.start(self._python32, ["-m", "gateway.diagnostico_opc", "--json"] + list(argumentos))
        return True

    def _al_terminar_descubrimiento(self, p, al_terminar):
        if p._hecho:
            return
        p._hecho = True
        salida = p.readAllStandardOutput().data().decode("utf-8", errors="replace")
        errores = p.readAllStandardError().data().decode("utf-8", errors="replace")
        p.deleteLater()
        self._descubrimiento = None
        self._poner_buscando(False)
        for ln in errores.splitlines():
            if ln.strip():
                self._consola.agregar("hmi", "diagnóstico: " + ln.rstrip())
        res = interpretar_json(salida)
        if not res.get("ok"):
            self._poner_mensaje_opc("Error: %s" % res.get("error", "sin detalle"))
            return
        al_terminar(res)

    def _al_fallar_descubrimiento(self, p, error):
        if error != PROCESO_FALLO_ARRANQUE or p._hecho:
            return
        p._hecho = True
        p.deleteLater()
        self._descubrimiento = None
        self._poner_buscando(False)
        self._poner_mensaje_opc("No se pudo lanzar %s" % self._python32)

    def _poner_listas(self, servidores=None, topics=None, archivos=None, ruta=None, items=None):
        if servidores is not None:
            self._servidores = [str(x) for x in servidores]
        if topics is not None:
            self._topics = [str(x) for x in topics]
        if archivos is not None:
            self._archivos = [str(x) for x in archivos]
        if ruta is not None:
            self._ruta_archivos = str(ruta)
        if items is not None:
            self._items = [str(x) for x in items]
        self.listasChanged.emit()

    @Slot()
    def buscarServidores(self):
        self._poner_listas(servidores=[], topics=[], archivos=[], ruta="", items=[])
        self._descubrir(["--servidores"], self._con_servidores, "Buscando servidores OPC DA registrados…")

    def _con_servidores(self, res):
        lista = list(res.get("servidores") or [])
        self._poner_listas(servidores=lista)
        self._poner_mensaje_opc("%d servidor(es). Selecciona uno." % len(lista) if lista else
                                "Sin servidores OPC DA registrados: ¿está instalado RSLinx (Gateway/OEM) con OPC?")
        if self._cfg["servidor"] in lista:
            self.buscarTopics()

    @Slot()
    def buscarTopics(self):
        self._poner_listas(topics=[], archivos=[], ruta="", items=[])
        self._descubrir(["--topics", "--servidor", self._cfg["servidor"]], self._con_topics,
                        "Leyendo topics de '%s'…" % self._cfg["servidor"])

    def _con_topics(self, res):
        lista = list(res.get("topics") or [])
        self._poner_listas(topics=lista)
        self._poner_mensaje_opc("%d topic(s)." % len(lista) if lista else
                                "Sin topics: RSLinx → DDE/OPC → Topic Configuration.")
        if self._cfg["topic"] in lista:
            self.buscarArchivos()

    @Slot()
    def buscarArchivos(self):
        self._poner_listas(archivos=[], ruta="", items=[])
        self._descubrir(["--archivos", "--servidor", self._cfg["servidor"], "--topic", self._cfg["topic"]],
                        self._con_archivos, "Leyendo archivos de [%s]…" % self._cfg["topic"])

    def _con_archivos(self, res):
        lista = list(res.get("archivos") or [])
        ruta = str(res.get("ruta") or ("%s.Online" % self._cfg["topic"]))
        self._poner_listas(archivos=lista, ruta=ruta, items=[])
        self._poner_mensaje_opc("%d archivo(s) en %s." % (len(lista), ruta))

    @Slot(str)
    def buscarItems(self, archivo):
        archivo = str(archivo).strip()
        base = self._ruta_archivos or ("%s.Online" % self._cfg["topic"])
        ruta = archivo if archivo.startswith(base + ".") else "%s.%s" % (base, archivo)
        self._poner_listas(items=[])
        self._descubrir(["--items", ruta, "--servidor", self._cfg["servidor"]], self._con_items,
                        "Leyendo items de %s…" % ruta)

    def _con_items(self, res):
        lista = list(res.get("items") or [])
        self._poner_listas(items=lista)
        self._poner_mensaje_opc("%d item(s). Doble clic para probar." % len(lista))

    @Slot(str)
    def leerItem(self, item):
        item = str(item).strip()
        if not item:
            self._poner_mensaje_opc("Escribe un item de prueba (p. ej. B3:0/0 o I:1.0)")
            return
        if item.startswith("[") and "]" in item:
            item = item.split("]", 1)[1]
        self._poner_cfg("itemPrueba", item)
        self._resultado = {}
        self.resultadoLecturaChanged.emit()
        self._descubrir(["--leer", item, "--servidor", self._cfg["servidor"], "--topic", self._cfg["topic"]],
                        self._con_lectura, "Leyendo [%s]%s…" % (self._cfg["topic"], item))

    def _con_lectura(self, res):
        calidad = str(res.get("calidad", ""))
        self._resultado = {"item": str(res.get("item", "")), "valor": res.get("valor"),
                           "calidad": calidad, "ok": calidad == "Good"}
        self.resultadoLecturaChanged.emit()
        self._poner_mensaje_opc("Lectura %s → valor=%s  calidad=%s" % (self._resultado["item"],
                                                                        self._resultado["valor"], calidad))

    # ------------------------------------------------------------------ consola
    @Slot()
    def limpiarConsola(self):
        self._consola.limpiar()
