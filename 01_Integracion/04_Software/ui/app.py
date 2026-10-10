# -*- coding: utf-8 -*-
"""
ui/app.py — Arranque del HMI (Qt Quick / QML). mds/ARQUITECTURA.md 6.2.

Bindings de Qt (un solo código y los mismos QML para los dos):
    * PySide6 6.x  → Qt 6,    Python 3.12+ de 64 bits (desarrollo y laboratorio).
    * PyQt5 5.15   → Qt 5.15, alternativa si solo hay Python de 32 bits (PySide6 no tiene ruedas win32).
    ui/qt_compat.py elige: PySide6 si está instalado, si no PyQt5 (HMI_QT=PyQt5 fuerza PyQt5).
    El binding y la versión de Qt se imprimen al arrancar.

Qué hace:
    * Carga las fuentes Inter de assets/assets_cilindros/fuentes/ antes de crear el motor QML.
    * Crea `Planta` (ui/cliente.py) y pone en el contexto raíz: `planta`, `rutaAssets`
      (URL file:/// de assets/assets_cilindros/), `datosInstitucion` (mds/data.md) y
      `configVentana` (tamaño inicial / pantalla completa).
    * --dev: recarga en caliente del QML (ui/qml/** y el sistema de diseño) sin cerrar ZeroMQ.
    * --lanzar-gateway SIM | --gateway-falso: arranca el publicador como subproceso con el mismo
      intérprete y lo termina al salir.
    * --lanzar-puente URL: arranca `python -m puente --url URL` (enlace al servidor del gemelo)
      como subproceso con el mismo intérprete y lo termina al salir. Para la prueba local del
      gemelo no hace falta: `python -m digital_twin.local` ya lleva su puente.
    * `conexion` (ui/conexion.py) en el contexto raíz: la ventana de conexión (modo SIM/EMULATE/REAL,
      gateway propio o existente, descubrimiento OPC, envío al gemelo). Se abre sola si a los 2 s
      no hay gateway vivo, salvo con --lanzar-gateway / --gateway-falso / --sin-conexion.

Uso (desde la raíz del repositorio):
    .venv\\Scripts\\python.exe ui\\app.py [--dev] [--lanzar-gateway SIM | --gateway-falso]
        [--lanzar-puente wss://gemelo.tudominio.com/ws/planta]
        [--pub tcp://127.0.0.1:5555] [--cmd tcp://127.0.0.1:5556] [--ancho 1920 --alto 1080]
        [--pantalla-completa] [--autocerrar N]

Requiere: Python 3.12+ de 64 bits con PySide6 6.x, o Python 3.12+ (32 o 64 bits) con PyQt5 5.15;
          además pyzmq y msgpack.
"""
from __future__ import annotations

import argparse
import os
import signal
import subprocess
import sys
import time
import unicodedata
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

# La consola de Windows suele ir en cp1252: sin esto, una flecha o un acento en un mensaje
# del registro rompe la salida. Mismo criterio que en gateway/__main__.py.
for _flujo in (sys.stdout, sys.stderr):
    try:
        _flujo.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

from ui.qt_compat import (BINDING, QT_VERSION, QFileSystemWatcher, QFontDatabase, QGuiApplication,  # noqa: E402
                          QObject, QQmlApplicationEngine, QTimer, QUrl, QtMsgType, borrar_qobject,
                          fijar_estilo_controles, instalar_ganchos_excepciones, qInstallMessageHandler,
                          QQmlAbstractUrlInterceptor, instalar_interceptor_url)

from core import protocolo  # noqa: E402
from ui.cliente import Planta  # noqa: E402
from ui.conexion import Conexion  # noqa: E402
from ui.historial import Historial  # noqa: E402

RUTA_ASSETS = RAIZ / "assets" / "assets_cilindros"
RUTA_FUENTES = RUTA_ASSETS / "fuentes"
RUTA_QML = RAIZ / "ui" / "qml"
RUTA_MAIN = RUTA_QML / "Main.qml"
RUTA_DATA = RAIZ / "mds" / "data.md"
RUTA_THEME_ORIGINAL = RUTA_ASSETS / "ui" / "qml" / "Theme.qml"   # sistema de diseño (solo lectura)
RUTA_THEME_HMI = RUTA_QML / "tema" / "Theme.qml"                   # mismos tokens + variante gris ISA-101
RUTA_GATEWAY_FALSO = RAIZ / "ui" / "herramientas" / "gateway_falso.py"

# Contadores de mensajes de Qt (para la prueba de humo con --autocerrar)
MENSAJES = {"avisos": 0, "errores": 0}


# ============================================================================
# Utilidades
# ============================================================================
def _normalizar(clave):
    """'División' -> 'division'."""
    s = unicodedata.normalize("NFKD", clave.strip())
    return "".join(c for c in s if not unicodedata.combining(c)).lower().replace(" ", "_")


def leer_datos_institucion(ruta=RUTA_DATA):
    """Lee `Clave: valor` por línea de mds/data.md. Quita el punto final de cada valor."""
    datos = {k: "" for k in ("universidad", "facultad", "division", "departamento", "materia", "proyecto", "nombre")}
    try:
        for linea in Path(ruta).read_text(encoding="utf-8").splitlines():
            if ":" not in linea:
                continue
            clave, valor = linea.split(":", 1)
            valor = valor.strip()
            while valor.endswith("."):
                valor = valor[:-1].rstrip()
            datos[_normalizar(clave)] = valor
    except OSError as e:
        print("[hmi] no se pudo leer %s: %s" % (ruta, e), file=sys.stderr)
    return datos


def cargar_fuentes():
    """Registra Inter (Regular, Medium, SemiBold, Bold). Devuelve las familias cargadas."""
    familias = set()
    for ttf in sorted(RUTA_FUENTES.glob("Inter-*.ttf")):
        i = QFontDatabase.addApplicationFont(str(ttf))
        if i < 0:
            print("[hmi] no se pudo cargar la fuente %s" % ttf.name, file=sys.stderr)
        else:
            familias.update(QFontDatabase.applicationFontFamilies(i))
    return sorted(familias)


def _manejador_mensajes(tipo, contexto, mensaje):
    """Todo aviso de Qt/QML a stderr con su ubicación; se cuentan para la prueba de humo."""
    if tipo == QtMsgType.QtDebugMsg or tipo == QtMsgType.QtInfoMsg:
        etiqueta = "qml"
    elif tipo == QtMsgType.QtWarningMsg:
        etiqueta = "AVISO"
        MENSAJES["avisos"] += 1
    else:
        etiqueta = "ERROR"
        MENSAJES["errores"] += 1
    donde = ""
    if contexto is not None and contexto.file:
        donde = " (%s:%s)" % (contexto.file, contexto.line)
    print("[%s] %s%s" % (etiqueta, mensaje, donde), file=sys.stderr, flush=True)


class ProcesoHijo:
    """Subproceso (gateway o gateway falso) que se termina al salir del HMI."""

    def __init__(self, nombre, argumentos):
        self.nombre = nombre
        self.argumentos = argumentos
        self.proc = None

    def arrancar(self):
        self.proc = subprocess.Popen(self.argumentos, cwd=str(RAIZ))
        print("[hmi] %s arrancado (pid %d): %s" % (self.nombre, self.proc.pid, " ".join(self.argumentos[1:])),
              file=sys.stderr)

    def terminar(self):
        if self.proc is None or self.proc.poll() is not None:
            return
        self.proc.terminate()
        try:
            self.proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            self.proc.kill()
        print("[hmi] %s terminado" % self.nombre, file=sys.stderr)


# ============================================================================
# Aplicación
# ============================================================================
class InterceptorTema(QQmlAbstractUrlInterceptor):
    """Cuando un QML pide el Theme.qml del sistema de diseño, el motor carga ui/qml/tema/Theme.qml:
    mismos tokens y una variante gris (`UI.Theme.variante`). assets/ no se toca ni se copia."""

    def __init__(self):
        super().__init__()
        self._original = os.path.normcase(str(RUTA_THEME_ORIGINAL.resolve()))
        self._hmi = QUrl.fromLocalFile(str(RUTA_THEME_HMI))

    def intercept(self, url, tipo):
        try:
            if url.isLocalFile() and os.path.normcase(os.path.abspath(url.toLocalFile())) == self._original:
                return self._hmi
        except Exception:  # nunca romper la carga del QML por el tema
            pass
        return url


class Aplicacion(QObject):
    """Motor QML + Planta. Reutilizable desde ui/herramientas/captura.py."""

    def __init__(self, args, parent=None):
        super().__init__(parent)
        self.args = args
        self.familias = cargar_fuentes()
        self.planta = Planta(self)
        self.historial = Historial(self)                     # visor del historial SQLite (ARQUITECTURA.md 6.5)
        self.conexion = Conexion(self.planta, args, self)   # ventana de conexión (ARQUITECTURA.md 6.4)
        self.datos = leer_datos_institucion()
        self.motor = None
        self.vigilante = None
        self._recarga = QTimer(self)
        self._recarga.setSingleShot(True)
        self._recarga.setInterval(250)
        self._recarga.timeout.connect(self.recargar)
        self._crear_motor()
        self.planta.conectar(args.pub, args.cmd)
        if args.dev:
            self._vigilar()

    # ------------------------------------------------------------------ motor
    def _crear_motor(self):
        self.motor = QQmlApplicationEngine(self)
        if RUTA_THEME_HMI.exists():
            self._interceptor = InterceptorTema()           # la referencia debe vivir con el motor
            instalar_interceptor_url(self.motor, self._interceptor)
        ctx = self.motor.rootContext()
        ctx.setContextProperty("planta", self.planta)
        ctx.setContextProperty("historial", self.historial)
        ctx.setContextProperty("conexion", self.conexion)
        ctx.setContextProperty("rutaAssets", QUrl.fromLocalFile(str(RUTA_ASSETS) + "/").toString())
        ctx.setContextProperty("datosInstitucion", self.datos)
        ctx.setContextProperty("configVentana", {"ancho": self.args.ancho, "alto": self.args.alto,
                                                 "pantallaCompleta": bool(self.args.pantalla_completa)})
        self.motor.load(QUrl.fromLocalFile(str(RUTA_MAIN)))

    def ventana(self):
        raices = self.motor.rootObjects() if self.motor is not None else []
        return raices[0] if raices else None

    def cargado(self):
        return self.ventana() is not None

    # ------------------------------------------------------------------ recarga en caliente (--dev)
    def _archivos_vigilados(self):
        dirs = [RUTA_QML, RUTA_ASSETS / "ui" / "qml"]
        archivos, carpetas = [], []
        for d in dirs:
            if not d.exists():
                continue
            carpetas.append(str(d))
            for p in d.rglob("*"):
                if p.is_dir():
                    carpetas.append(str(p))
                elif p.is_file() and (p.suffix == ".qml" or p.name == "qmldir"):
                    archivos.append(str(p))
        return archivos, carpetas

    def _vigilar(self):
        self.vigilante = QFileSystemWatcher(self)
        archivos, carpetas = self._archivos_vigilados()
        self.vigilante.addPaths(archivos + carpetas)
        self.vigilante.fileChanged.connect(lambda _p: self._recarga.start())
        self.vigilante.directoryChanged.connect(lambda _p: self._recarga.start())
        print("[hmi] --dev: vigilando %d archivos QML" % len(archivos), file=sys.stderr)

    def recargar(self):
        """Vuelve a cargar Main.qml conservando Planta (y con ella los sockets ZeroMQ)."""
        vieja = self.ventana()
        geometria = None
        if vieja is not None:
            geometria = (vieja.property("x"), vieja.property("y"), vieja.property("width"), vieja.property("height"))
            vieja.close()
            vieja.deleteLater()
        self.motor.clearComponentCache()
        self.motor.load(QUrl.fromLocalFile(str(RUTA_MAIN)))
        nueva = self.ventana()
        if nueva is not None and nueva is not vieja and geometria is not None:
            nueva.setProperty("x", geometria[0])
            nueva.setProperty("y", geometria[1])
            nueva.setProperty("width", geometria[2])
            nueva.setProperty("height", geometria[3])
        if self.vigilante is not None:  # los editores reemplazan archivos: volver a añadirlos
            archivos, carpetas = self._archivos_vigilados()
            faltan = [p for p in archivos + carpetas if p not in self.vigilante.files() + self.vigilante.directories()]
            if faltan:
                self.vigilante.addPaths(faltan)
        print("[hmi] QML recargado %s" % time.strftime("%H:%M:%S"), file=sys.stderr)

    def cerrar(self):
        """Destruye primero el motor QML (sus enlaces leen `planta`) y luego cierra ZeroMQ."""
        if self.motor is not None:
            for raiz in self.motor.rootObjects():
                raiz.close()
            borrar_qobject(self.motor)
            self.motor = None
        self.conexion.cerrar()      # termina gateway/puente/gemelo propios antes de soltar ZeroMQ
        self.planta.cerrar()


# ============================================================================
# Línea de órdenes
# ============================================================================
def crear_parser():
    ap = argparse.ArgumentParser(description="HMI de la estación electroneumática (QML; PySide6 o PyQt5).")
    ap.add_argument("--dev", action="store_true", help="recarga en caliente del QML")
    ap.add_argument("--lanzar-gateway", metavar="MODO", choices=protocolo.MODOS,
                    help="arranca 'python -m gateway --modo MODO' como subproceso")
    ap.add_argument("--gateway-falso", action="store_true",
                    help="arranca ui/herramientas/gateway_falso.py como subproceso")
    ap.add_argument("--pub", default=protocolo.PUB_DEFECTO, help="endpoint PUB del gateway")
    ap.add_argument("--cmd", default=protocolo.CMD_DEFECTO, help="endpoint REP del gateway")
    ap.add_argument("--ancho", type=int, default=1600)
    ap.add_argument("--alto", type=int, default=900)
    ap.add_argument("--pantalla-completa", action="store_true")
    ap.add_argument("--autocerrar", type=float, default=0.0, metavar="S", help="sale a los S segundos (pruebas)")
    ap.add_argument("--arrancar", action="store_true", help="manda un pulso STARTV al segundo de arrancar (demos y pruebas)")
    ap.add_argument("--sin-conexion", action="store_true",
                    help="no abrir sola la ventana de conexión aunque a los 2 s no haya gateway")
    return ap


def proceso_gateway(args):
    """ProcesoHijo a lanzar según los argumentos, o None. Sale con mensaje claro si no se puede."""
    if args.lanzar_gateway and args.gateway_falso:
        sys.exit("hmi: usa --lanzar-gateway o --gateway-falso, no los dos")
    if args.lanzar_gateway:
        if not (RAIZ / "gateway" / "__main__.py").exists():
            sys.exit("hmi: --lanzar-gateway: no existe gateway/__main__.py todavía "
                     "(usa --gateway-falso para diseñar sin el gateway real)")
        return ProcesoHijo("gateway", [sys.executable, "-m", "gateway", "--modo", args.lanzar_gateway,
                                       "--pub", args.pub, "--cmd", args.cmd])
    if args.gateway_falso:
        return ProcesoHijo("gateway falso", [sys.executable, str(RUTA_GATEWAY_FALSO),
                                             "--pub", args.pub, "--cmd", args.cmd])
    return None


def preparar_qt():
    """Entorno Qt común (app y captura): fuentes sin pantalla, avisos a stderr, estilo de controles."""
    # Sin pantalla (offscreen) Qt usa su propia base de fuentes: se le indica la de Windows.
    if os.environ.get("QT_QPA_PLATFORM", "").startswith("offscreen") and not os.environ.get("QT_QPA_FONTDIR"):
        fuentes_sis = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
        if fuentes_sis.exists():
            os.environ["QT_QPA_FONTDIR"] = str(fuentes_sis)
    qInstallMessageHandler(_manejador_mensajes)
    instalar_ganchos_excepciones(MENSAJES)
    fijar_estilo_controles()   # Basic (Qt 6) / Default (Qt 5): controles personalizables
    app = QGuiApplication.instance() or QGuiApplication(sys.argv[:1])
    app.setApplicationName("HMI estación electroneumática")
    app.setOrganizationName("FI UNAM")
    print("[hmi] %s · Qt %s · Python %d.%d (%d bits)" % (BINDING, QT_VERSION, sys.version_info[0], sys.version_info[1],
                                                        64 if sys.maxsize > 2 ** 32 else 32), file=sys.stderr)
    return app


def main(argv=None):
    args = crear_parser().parse_args(argv)
    hijo = proceso_gateway(args)

    app = preparar_qt()

    if hijo is not None:
        hijo.arrancar()
    try:
        hmi = Aplicacion(args)
        if not hmi.cargado():
            print("[hmi] no se pudo cargar %s" % RUTA_MAIN, file=sys.stderr)
            return 1
        # Ctrl+C en consola: Python necesita recuperar el control de vez en cuando
        signal.signal(signal.SIGINT, lambda *_: app.quit())
        latido = QTimer()
        latido.start(250)
        latido.timeout.connect(lambda: None)
        if args.autocerrar > 0:
            QTimer.singleShot(int(args.autocerrar * 1000), app.quit)
        if args.arrancar:
            QTimer.singleShot(1500, lambda: hmi.planta.pulso("STARTV"))
        codigo = app.exec()
        if args.autocerrar > 0:
            print("[hmi] fin de la prueba: %d avisos, %d errores de Qt/QML; último seq %d, etapa X%s, modo %s"
                  % (MENSAJES["avisos"], MENSAJES["errores"], hmi.planta.seq, hmi.planta.etapa, hmi.planta.modo),
                  file=sys.stderr)
            m = hmi.planta.eventos
            for i in reversed(range(min(12, m.rowCount()))):
                ix = m.index(i, 0)
                print("[hmi]   registro %s %-6s %-8s %s" % (m.data(ix, m.ROL_HORA), m.data(ix, m.ROL_NIVEL),
                                                        m.data(ix, m.ROL_ORIGEN), m.data(ix, m.ROL_MSG)), file=sys.stderr)
        hmi.cerrar()
        return codigo
    finally:
        if hijo is not None:
            hijo.terminar()


if __name__ == "__main__":
    sys.exit(main())
