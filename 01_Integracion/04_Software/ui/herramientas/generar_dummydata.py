# -*- coding: utf-8 -*-
"""
ui/herramientas/generar_dummydata.py — Datos de prueba para abrir el HMI en Qt Design Studio.

Qué hace:
    Qt Design Studio no ejecuta Python: no tiene `planta`, `conexion`, `historial`,
    `datosInstitucion`, `rutaAssets` ni `configVentana`, que ui/app.py pone en el contexto raíz
    del motor QML. Lo que sí hace es cargar cada archivo de la carpeta `dummydata/` del proyecto
    (ui/qml/HMI.qmlproject) como propiedad de contexto con el nombre del archivo. Esta
    herramienta escribe esos archivos en ui/qml/dummydata/ a partir de los objetos reales:

      1. Arranca el gateway SIM en puertos propios y conecta un `Planta` real (ui/cliente.py).
      2. Pulsa START y espera `--espera` s, para que la secuencia esté en marcha (etapa activa,
         cilindros en movimiento, cronograma y registro con datos).
      3. Recorre las propiedades, los slots y las señales de `Planta`, `Conexion` e `Historial`
         con el sistema de metadatos de Qt y los vuelca como QML: las propiedades con su valor
         del momento, los slots como funciones vacías (en el diseñador no hay gateway) y los
         modelos de lista (registro de eventos, consola) como ListModel con sus filas.

    `Conexion` e `Historial` se crean con configuración y base de datos vacías en una carpeta
    temporal: así no se copian al repositorio datos/conexion.json (puede llevar la URL del broker
    con usuario y clave), el historial ni la calibración de esta máquina. Las rutas absolutas del
    repositorio se escriben relativas.

    Volver a ejecutarla cuando cambien las propiedades de Planta, Conexion o Historial
    (tests/test_dummydata.py avisa si falta alguna).

Uso (desde la raíz del repositorio):
    .venv\\Scripts\\python.exe ui\\herramientas\\generar_dummydata.py [--espera 12]

Requiere: Python 3.12+ de 64 bits con PySide6 6.x (o PyQt5 5.15), pyzmq y msgpack.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent.parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

if "QT_QPA_PLATFORM" not in os.environ:
    os.environ["QT_QPA_PLATFORM"] = "offscreen"

from ui.qt_compat import QAbstractListModel, QObject, QTimer  # noqa: E402

import ui.cliente as cliente  # noqa: E402
from core import tags  # noqa: E402
from ui.app import MENSAJES, ProcesoHijo, crear_parser, leer_datos_institucion, preparar_qt  # noqa: E402
from ui.conexion import Conexion  # noqa: E402
from ui.historial import Historial  # noqa: E402

CARPETA = RAIZ / "ui" / "qml" / "dummydata"
CABECERA = ("// Generado por ui/herramientas/generar_dummydata.py: no editar a mano.\n"
            "// Datos de prueba para Qt Design Studio (ui/qml/HMI.qmlproject): {que}\n")
DECIMALES = 3


# ============================================================================
# Metadatos de Qt (mismo código para PySide6 y PyQt5)
# ============================================================================
def _entero(enum):
    """Enum de Qt → int (PySide6 usa enums de Python; PyQt5, enteros)."""
    return int(getattr(enum, "value", enum))


def _texto(x):
    return bytes(x).decode() if not isinstance(x, str) else x


def _meta(obj):
    """Metaobjeto estático de la clase. En PySide6, obj.metaObject() de una clase de Python es un
    metaobjeto dinámico cuya clase base ya trae todas las propiedades: su propertyOffset() es igual
    a propertyCount() y no se vería ninguna."""
    return getattr(type(obj), "staticMetaObject", None) or obj.metaObject()


def propiedades(obj):
    """[(nombre, valor)] de las propiedades declaradas por la clase (no las de QObject)."""
    mo = _meta(obj)
    salida = []
    for i in range(mo.propertyOffset(), mo.propertyCount()):
        nombre = _texto(mo.property(i).name())
        salida.append((nombre, obj.property(nombre)))
    return salida


def metodos(obj):
    """{nombre: (tipo, n_parametros, tipo_retorno)} de slots y señales propios.

    tipo: "slot" o "senal". Con sobrecargas (slots de Python con argumentos por defecto) se queda
    la de más parámetros.
    """
    mo = _meta(obj)
    salida = {}
    for i in range(mo.methodOffset(), mo.methodCount()):
        m = mo.method(i)
        tipo = {1: "senal", 2: "slot"}.get(_entero(m.methodType()))
        if tipo is None:
            continue
        nombre = _texto(m.name())
        n = m.parameterCount()
        if nombre not in salida or salida[nombre][1] < n:
            salida[nombre] = (tipo, n, str(m.typeName() or ""))
    return salida


# ============================================================================
# Valores → QML
# ============================================================================
def _limpiar(v, rutas):
    """Redondea floats, pasa rutas absolutas a relativas y deja solo tipos JSON."""
    if isinstance(v, float):
        return round(v, DECIMALES)
    if isinstance(v, str):
        for absoluta, relativa in rutas:
            v = v.replace(absoluta, relativa)
        return v
    if isinstance(v, dict):
        return {str(k): _limpiar(x, rutas) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_limpiar(x, rutas) for x in v]
    if v is None or isinstance(v, (bool, int)):
        return v
    return str(v)


def literal(v):
    return json.dumps(v, ensure_ascii=False)


def declaracion(nombre, valor):
    """`property <tipo> nombre: valor` con el tipo QML que corresponde al valor de Python."""
    if isinstance(valor, bool):
        tipo = "bool"
    elif isinstance(valor, int) and -2 ** 31 <= valor < 2 ** 31:
        tipo = "int"
    elif isinstance(valor, (int, float)):
        tipo = "real"
    elif isinstance(valor, str):
        tipo = "string"
    else:
        return "property var %s: (%s)" % (nombre, literal(valor))
    return "property %s %s: %s" % (tipo, nombre, literal(valor))


def _retorno(tipo_qt):
    """Valor que devuelve una función de prueba según el tipo de retorno del slot."""
    t = tipo_qt.lower()
    if not t or t == "void":
        return None
    if "bool" in t:
        return "false"
    if t in ("int", "double", "float", "qreal") or "int" in t:
        return "0"
    if "list" in t:
        return "[]"
    if "map" in t:
        return "({})"
    return '""'


def _cuerpo(nombre, obj, rutas, sangria, especiales):
    """Líneas QML con propiedades, modelos anidados, señales y funciones de un QObject."""
    pad = " " * sangria
    lineas = []
    nombres_prop = set()
    for nombre_p, valor in propiedades(obj):
        nombres_prop.add(nombre_p)
        if isinstance(valor, QAbstractListModel):
            lineas.extend(_modelo(nombre_p, valor, rutas, sangria))
        elif isinstance(valor, QObject):
            lineas.append(pad + "property var %s: null   // QObject sin volcar" % nombre_p)
        else:
            lineas.append(pad + declaracion(nombre_p, _limpiar(valor, rutas)))
    for nombre_m, (tipo, n, ret) in sorted(metodos(obj).items()):
        if nombre_m.startswith("_"):
            continue
        params = ", ".join("a%d" % i for i in range(n))
        if tipo == "senal":
            if nombre_m.endswith("Changed") and nombre_m[:-len("Changed")] in nombres_prop:
                continue   # QML ya crea <propiedad>Changed para cada propiedad declarada
            lineas.append(pad + "signal %s(%s)" % (nombre_m, ", ".join("var a%d" % i for i in range(n))))
        elif nombre_m in especiales:
            lineas.append(pad + especiales[nombre_m])
        else:
            r = _retorno(ret)
            lineas.append(pad + "function %s(%s) {%s}" % (nombre_m, params, (" return %s " % r) if r else ""))
    return lineas


def _modelo(nombre, modelo, rutas, sangria):
    """QAbstractListModel → `property ListModel nombre: ListModel { … ListElement … }`."""
    pad = " " * sangria
    roles = {rol: _texto(n) for rol, n in modelo.roleNames().items()}
    lineas = [pad + "property ListModel %s: ListModel {" % nombre]
    lineas.extend(_cuerpo(nombre, modelo, rutas, sangria + 4, {}))
    for fila in range(modelo.rowCount()):
        idx = modelo.index(fila, 0)
        campos = []
        for rol, n in sorted(roles.items()):
            v = _limpiar(modelo.data(idx, rol), rutas)
            if isinstance(v, (dict, list)) or v is None:
                v = "" if v is None else literal(v)   # ListElement solo admite valores simples
            campos.append("%s: %s" % (n, literal(v)))
        lineas.append(pad + "    ListElement { %s }" % "; ".join(campos))
    lineas.append(pad + "}")
    return lineas


def archivo_objeto(que, obj, rutas, especiales=None, extra=()):
    lineas = [CABECERA.format(que=que), "import QtQuick 2.15", "", "QtObject {"]
    lineas.extend("    " + x for x in extra)
    lineas.extend(_cuerpo("", obj, rutas, 4, especiales or {}))
    lineas.append("}")
    return "\n".join(lineas) + "\n"


def archivo_mapa(que, datos):
    lineas = [CABECERA.format(que=que), "import QtQuick 2.15", "", "QtObject {"]
    lineas.extend("    " + declaracion(k, v) for k, v in datos.items())
    lineas.append("}")
    return "\n".join(lineas) + "\n"


def archivo_ruta_assets():
    # app.py pasa una cadena (URL file:/// de assets/assets_cilindros/) y los componentes hacen
    # `rutaAssets + "logos/…"`. dummydata solo admite objetos: toString() da la misma cadena,
    # resuelta respecto a este archivo para que funcione en cualquier carpeta. El tipo de retorno
    # (`: string`, sintaxis de Qt 6) es necesario: sin él el motor recibe un QVariant vacío y la
    # suma da "QVariant()logos/…".
    return (CABECERA.format(que="rutaAssets, URL de assets/assets_cilindros/ (en app.py es una cadena)")
            + "import QtQuick 2.15\n\nQtObject {\n"
            + '    function toString(): string { return "" + Qt.resolvedUrl("../../../assets/assets_cilindros/") }\n}\n')


# ============================================================================
# Programa
# ============================================================================
def main(argv=None):
    ap = argparse.ArgumentParser(description="Datos de prueba de ui/qml/dummydata/ para Qt Design Studio.")
    ap.add_argument("--espera", type=float, default=12.0, help="segundos de secuencia antes de volcar")
    ap.add_argument("--pub", default="tcp://127.0.0.1:5595")
    ap.add_argument("--cmd", default="tcp://127.0.0.1:5596")
    a = ap.parse_args(argv)

    temporal = tempfile.TemporaryDirectory(prefix="dummydata_")
    tmp = Path(temporal.name)
    cliente.RUTA_CALIBRACION = tmp / "calibracion.json"     # calibración vacía, no la de esta máquina
    cliente.RUTA_PREFERENCIAS = tmp / "preferencias_hmi.json"  # modo suave apagado, como al instalar
    rutas = [(str(tmp / "conexion.json"), "datos/conexion.json"), (str(tmp / "historial.sqlite"), "datos/historial.sqlite"),
             (str(tmp), "datos"), (str(RAIZ) + os.sep, ""), (str(RAIZ), ".")]

    hijo = ProcesoHijo("gateway", [sys.executable, "-m", "gateway", "--modo", "SIM", "--pub", a.pub, "--cmd", a.cmd])
    app = preparar_qt()
    hijo.arrancar()
    resultado = {}
    try:
        planta = cliente.Planta()
        args_hmi = crear_parser().parse_args(["--pub", a.pub, "--cmd", a.cmd])
        conexion = Conexion(planta, args_hmi, ruta_config=tmp / "conexion.json", detectar_python32=False)
        historial = Historial(ruta=tmp / "historial.sqlite")
        planta.conectar(a.pub, a.cmd)

        def volcar():
            direcciones = {t: planta.direccion(t) for t in tags.DIRECCION}
            resultado["planta.qml"] = archivo_objeto(
                "planta (ui/cliente.py, Planta) con la secuencia SIM en marcha", planta, rutas,
                especiales={"direccion": "function direccion(a0) { return tablaDirecciones[a0] || \"\" }"},
                extra=[declaracion("tablaDirecciones", direcciones), ""])
            resultado["conexion.qml"] = archivo_objeto("conexion (ui/conexion.py, Conexion) con la configuración por defecto",
                                                       conexion, rutas)
            resultado["historial.qml"] = archivo_objeto("historial (ui/historial.py, Historial) sin consultas", historial, rutas)
            resultado["datosInstitucion.qml"] = archivo_mapa("datosInstitucion (mds/data.md)", leer_datos_institucion())
            resultado["configVentana.qml"] = archivo_mapa("configVentana (tamaño de la ventana en app.py)",
                                                          {"ancho": 1920, "alto": 1080, "pantallaCompleta": False})
            resultado["rutaAssets.qml"] = archivo_ruta_assets()
            resultado["_resumen"] = "seq %d, etapa X%d, modo %s, %d eventos" % (
                planta.seq, planta.etapa, planta.modo, planta.eventos.rowCount())
            app.quit()

        QTimer.singleShot(800, lambda: planta.pulso("STARTV"))
        QTimer.singleShot(int(a.espera * 1000), volcar)
        QTimer.singleShot(int((a.espera + 15) * 1000), app.quit)   # salvavidas
        app.exec()
        planta.desconectar(True)
        conexion.deleteLater()
    finally:
        hijo.terminar()

    if "planta.qml" not in resultado:
        print("generar_dummydata: no se llegó a volcar (¿arrancó el gateway SIM?)", file=sys.stderr)
        return 1
    if " modo SIM" not in resultado["_resumen"]:
        print("generar_dummydata: AVISO, no llegaron snapshots del gateway: %s" % resultado["_resumen"], file=sys.stderr)
    CARPETA.mkdir(parents=True, exist_ok=True)
    for nombre, texto in sorted(resultado.items()):
        if nombre.startswith("_"):
            continue
        (CARPETA / nombre).write_text(texto, encoding="utf-8", newline="\n")
        print("generar_dummydata: %s (%d líneas)" % ((CARPETA / nombre).relative_to(RAIZ), texto.count("\n")))
    print("generar_dummydata: %s; %d avisos y %d errores de Qt" % (resultado["_resumen"], MENSAJES["avisos"], MENSAJES["errores"]))
    try:
        temporal.cleanup()
    except OSError:
        pass   # el SQLite del historial puede seguir abierto en Windows; se borra al reiniciar
    return 0


if __name__ == "__main__":
    sys.exit(main())
