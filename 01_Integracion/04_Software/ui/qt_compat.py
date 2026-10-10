# -*- coding: utf-8 -*-
"""
ui/qt_compat.py — Capa única de compatibilidad Qt del HMI: PySide6 (Qt 6) o PyQt5 (Qt 5.15).

Qué hace:
    Importa PySide6 si está instalado; si no, PyQt5. El resto de `ui/` importa Qt SOLO desde
    aquí, con nombres únicos, y así el mismo código y los mismos QML corren en:
        * PySide6 6.x  → Qt 6, Python 3.12+ de 64 bits (máquina de desarrollo y laboratorio).
        * PyQt5 5.15   → Qt 5.15, alternativa si solo hay Python de 32 bits (PySide6 no tiene ruedas win32).
    La variable de entorno HMI_QT=PyQt5 (o PySide6) fuerza un binding aunque estén los dos.

Qué expone:
    QtCore, QtGui, QtQml, QtQuick (módulos) y las clases que usa ui/ (QObject, QTimer, QUrl, Qt,
    QtMsgType, qInstallMessageHandler, QFileSystemWatcher, QAbstractListModel, QModelIndex,
    QByteArray, QGuiApplication, QFontDatabase, QQmlApplicationEngine, QQuickWindow, QProcess,
    QProcessEnvironment, QCoreApplication, QDesktopServices); Signal, Slot, Property con la API de
    PySide6 (en PyQt5 son pyqtSignal, pyqtSlot, pyqtProperty, que aceptan los mismos argumentos
    posicionales y `notify=`, `constant=`, `result=`); BINDING ("PySide6" | "PyQt5");
    QT_VERSION (p. ej. "6.11.2" o "5.15.2"); QT_MAYOR (6 | 5); borrar_qobject(obj);
    fijar_estilo_controles(); instalar_ganchos_excepciones(contador).
    Constantes de QProcess resueltas para los dos bindings (en PyQt5 cuelgan de la clase,
    `QProcess.NotRunning`; en PySide6 de un enum anidado, `QProcess.ProcessState.NotRunning`):
    PROCESO_PARADO, PROCESO_ARRANCANDO, PROCESO_CORRIENDO (estados), PROCESO_SALIDA_NORMAL,
    PROCESO_SALIDA_ABRUPTA (exitStatus) y PROCESO_FALLO_ARRANQUE (errorOccurred).

Requiere: Python 3.12+ y PySide6 6.x o PyQt5 5.15.
"""
from __future__ import annotations

import os
import sys
import traceback

_PREFERIDO = os.environ.get("HMI_QT", "").strip().lower()
_ORDEN = ("pyqt5", "pyside6") if _PREFERIDO == "pyqt5" else ("pyside6", "pyqt5")


def _importar(nombre):
    """Importa el binding `nombre` y devuelve la tupla de módulos, o lanza ImportError."""
    if nombre == "pyside6":
        from PySide6 import QtCore as _c, QtGui as _g, QtQml as _q, QtQuick as _k
        return "PySide6", _c, _g, _q, _k
    # QtQuick se importa aunque ui/ casi no lo use: sin él, PyQt5 devuelve la ventana raíz de
    # rootObjects() como QWindow genérico (sin grabWindow) en vez de QQuickWindow.
    from PyQt5 import QtCore as _c, QtGui as _g, QtQml as _q, QtQuick as _k
    return "PyQt5", _c, _g, _q, _k


_errores = []
for _n in _ORDEN:
    try:
        BINDING, QtCore, QtGui, QtQml, QtQuick = _importar(_n)
        break
    except ImportError as _e:  # probar el siguiente
        _errores.append("%s: %s" % (_n, _e))
else:
    raise ImportError("El HMI necesita PySide6 (Qt 6) o PyQt5 5.15 (Qt 5.15). " + " | ".join(_errores))

# ---------------------------------------------------------------- clases comunes (mismo nombre)
QObject = QtCore.QObject
QTimer = QtCore.QTimer
QUrl = QtCore.QUrl
Qt = QtCore.Qt
QtMsgType = QtCore.QtMsgType       # en PyQt5 los miembros también cuelgan del tipo (QtMsgType.QtWarningMsg)
qInstallMessageHandler = QtCore.qInstallMessageHandler
QFileSystemWatcher = QtCore.QFileSystemWatcher
QAbstractListModel = QtCore.QAbstractListModel
QModelIndex = QtCore.QModelIndex
QByteArray = QtCore.QByteArray
QGuiApplication = QtGui.QGuiApplication
QFontDatabase = QtGui.QFontDatabase
QQmlApplicationEngine = QtQml.QQmlApplicationEngine
QQuickWindow = QtQuick.QQuickWindow
QProcess = QtCore.QProcess
QProcessEnvironment = QtCore.QProcessEnvironment
QCoreApplication = QtCore.QCoreApplication
QDesktopServices = QtGui.QDesktopServices
QQmlAbstractUrlInterceptor = QtQml.QQmlAbstractUrlInterceptor


def instalar_interceptor_url(motor, interceptor):
    """Qt 6 (PySide6): addUrlInterceptor; Qt 5 (PyQt5): setUrlInterceptor. El llamador conserva la
    referencia de Python al interceptor mientras viva el motor."""
    if hasattr(motor, "addUrlInterceptor"):
        motor.addUrlInterceptor(interceptor)
    else:
        motor.setUrlInterceptor(interceptor)


def _enum_qprocess(nombre, grupo):
    """Miembro de enum de QProcess válido en PyQt5 (`QProcess.X`) y PySide6 (`QProcess.Grupo.X`)."""
    valor = getattr(QProcess, nombre, None)
    if valor is None:
        valor = getattr(getattr(QProcess, grupo), nombre)
    return valor


# Estados de QProcess.state()
PROCESO_PARADO = _enum_qprocess("NotRunning", "ProcessState")
PROCESO_ARRANCANDO = _enum_qprocess("Starting", "ProcessState")
PROCESO_CORRIENDO = _enum_qprocess("Running", "ProcessState")
# exitStatus() de la señal finished(codigo, estado)
PROCESO_SALIDA_NORMAL = _enum_qprocess("NormalExit", "ExitStatus")
PROCESO_SALIDA_ABRUPTA = _enum_qprocess("CrashExit", "ExitStatus")
# errorOccurred(error): el ejecutable no existe o no se pudo lanzar
PROCESO_FALLO_ARRANQUE = _enum_qprocess("FailedToStart", "ProcessError")

# ---------------------------------------------------------------- señales, slots y propiedades
if BINDING == "PySide6":
    Signal = QtCore.Signal
    Slot = QtCore.Slot
    Property = QtCore.Property
    QT_VERSION = QtCore.qVersion()
else:
    Signal = QtCore.pyqtSignal
    Slot = QtCore.pyqtSlot
    Property = QtCore.pyqtProperty    # pyqtProperty(tipo, fget, fset, ..., notify=, constant=)
    QT_VERSION = QtCore.QT_VERSION_STR

QT_MAYOR = int(QT_VERSION.split(".")[0])


def borrar_qobject(obj):
    """Destruye YA el objeto C++ de `obj` (sin esperar al recolector ni a deleteLater)."""
    if BINDING == "PySide6":
        import shiboken6
        shiboken6.delete(obj)
    else:
        try:
            from PyQt5 import sip
        except ImportError:  # PyQt5 antiguo con sip suelto
            import sip
        sip.delete(obj)


def fijar_estilo_controles():
    """Estilo de Qt Quick Controls personalizable (el nativo de Windows no admite background propio).

    Se llama ANTES de crear QGuiApplication. En Qt 6 el estilo se llama "Basic" y se fija con
    QQuickStyle; PyQt5 no expone QQuickStyle y en Qt 5 el mismo estilo se llama "Default": se usa
    la variable de entorno que Qt lee al cargar QtQuick.Controls.
    """
    if BINDING == "PySide6":
        from PySide6.QtQuickControls2 import QQuickStyle
        QQuickStyle.setStyle("Basic")
    else:
        os.environ["QT_QUICK_CONTROLS_STYLE"] = "Default"


def instalar_ganchos_excepciones(contador=None):
    """Excepciones no atrapadas en slots/callbacks: a stderr y a `contador["errores"]`.

    PyQt5 ≥ 5.5 aborta el proceso (qFatal) ante una excepción en un slot si sys.excepthook es el
    de fábrica; PySide6 solo la imprime. Con este gancho ambos se comportan igual: se imprime,
    se cuenta como error de la prueba de humo y el HMI sigue vivo.
    """
    def _gancho(tipo, valor, tb):
        if contador is not None:
            contador["errores"] = contador.get("errores", 0) + 1
        sys.stderr.write("[ERROR] excepción no atrapada:\n" + "".join(traceback.format_exception(tipo, valor, tb)))
        sys.stderr.flush()
    sys.excepthook = _gancho


__all__ = [
    "BINDING", "QT_VERSION", "QT_MAYOR", "QtCore", "QtGui", "QtQml", "QtQuick", "QQuickWindow",
    "QObject", "QTimer", "QUrl", "Qt", "QtMsgType", "qInstallMessageHandler", "QFileSystemWatcher",
    "QAbstractListModel", "QModelIndex", "QByteArray", "QGuiApplication", "QFontDatabase",
    "QQmlApplicationEngine", "Signal", "Slot", "Property",
    "QProcess", "QProcessEnvironment", "QCoreApplication", "QDesktopServices",
    "QQmlAbstractUrlInterceptor", "instalar_interceptor_url",
    "PROCESO_PARADO", "PROCESO_ARRANCANDO", "PROCESO_CORRIENDO",
    "PROCESO_SALIDA_NORMAL", "PROCESO_SALIDA_ABRUPTA", "PROCESO_FALLO_ARRANQUE",
    "borrar_qobject", "fijar_estilo_controles", "instalar_ganchos_excepciones",
]
