# -*- coding: utf-8 -*-
"""
ui/historial.py — QObject `Historial`: visor del historial SQLite del gateway para QML (ARQUITECTURA 6.5).

Qué hace:
    * Abre datos/historial.sqlite en SOLO LECTURA con core.historial.LectorHistorial. La base la
      escribe el gateway desde su propio proceso; como está en modo WAL, este proceso puede leerla
      al mismo tiempo sin bloquearlo ni corromper nada.
    * Expone a QML los filtros como propiedades (`tabla`, `desde`/`hasta`, `niveles`, `texto`,
      `tag`, `soloActivas`, `soloFallidas`, `limite`), el resultado como un QAbstractListModel
      (`filas`, con los roles ya formateados: hora, fecha, duración…), `total` (filas de esa tabla
      en la base), `resumen`, `error`, `ultimoExporte` y `consultaMs`.
    * Slots: `consultar()`, `ultimas(horas)` (fija `desde` = ahora − horas y consulta; 0 = todo) y
      `exportarCsv()`, que escribe <carpeta de la base>/exportes/<tabla>_<AAAAMMDD-HHMMSS>.csv
      (con la base por defecto: datos/exportes/) con los filtros vigentes y sin límite de filas.
      Sin diálogo de archivo: QtQuick.Dialogs difiere entre Qt 5 y Qt 6.
    * Las consultas corren en el hilo de la GUI: con `limite` 500 e índice por `t` tardan unos
      milisegundos (`consultaMs` lo mide); no hacen falta hilos ni colas.

Modos: SIM, EMULATE y REAL (se lee lo que el gateway haya guardado, sea cual sea el modo).
Bindings: PySide6 6.x (Qt 6) o PyQt5 5.15 (Qt 5.15), siempre a través de ui/qt_compat.py.
Requiere: Python 3.12+.
"""
from __future__ import annotations

import os
import time
from datetime import datetime
from pathlib import Path

from core import protocolo
from core.historial import TABLAS, LectorHistorial
from ui.qt_compat import (Property, QAbstractListModel, QByteArray, QModelIndex, QObject, Qt,
                          Signal, Slot)

RAIZ = Path(__file__).resolve().parent.parent
RUTA_DEFECTO = str(RAIZ / "datos" / "historial.sqlite")
LIMITE_DEFECTO = 500
ROLES = ("hora", "fecha", "nivel", "msg", "origen", "id", "tIni", "tFin", "duracion", "tag", "valor", "ok", "t")


# ============================================================================
# Formato de las filas (lo que ve QML)
# ============================================================================
def _fecha_hora(t):
    try:
        return datetime.fromtimestamp(float(t))
    except (TypeError, ValueError, OverflowError, OSError):
        return None


def hora(t):
    """Epoch → 'HH:MM:SS.mmm' en hora local; '--:--:--' si no hay valor."""
    d = _fecha_hora(t)
    return d.strftime("%H:%M:%S.%f")[:-3] if d else "--:--:--"


def fecha(t):
    """Epoch → 'dd/MM/yyyy'; '--/--/----' si no hay valor."""
    d = _fecha_hora(t)
    return d.strftime("%d/%m/%Y") if d else "--/--/----"


def duracion(segundos):
    """Segundos → '12,3 s' (coma decimal, como Estilo.num), '2 min 05 s' o '1 h 02 min'; '—' sin valor."""
    try:
        s = float(segundos)
    except (TypeError, ValueError):
        return "—"
    if s < 0:
        return "—"
    if s < 60:
        return ("%.1f" % s).replace(".", ",") + " s"
    minutos, resto = divmod(int(s), 60)
    if minutos < 60:
        return "%d min %02d s" % (minutos, resto)
    horas, minutos = divmod(minutos, 60)
    return "%d h %02d min" % (horas, minutos)


def _vacia(t):
    return {"t": float(t or 0.0), "hora": hora(t), "fecha": fecha(t), "nivel": "info", "msg": "", "origen": "",
            "id": "", "tIni": "", "tFin": "", "duracion": "—", "tag": "", "valor": "", "ok": True}


def fila_evento(e):
    f = _vacia(e.get("t"))
    f.update(nivel=str(e.get("nivel") or "info"), msg=str(e.get("msg") or ""), origen=str(e.get("origen") or ""))
    return f


def fila_alarma(a):
    """`tFin` es la hora de fin o 'activa'; `ok` = ya se limpió; `t` = inicio (para ordenar)."""
    t_ini, t_fin = a.get("t_ini"), a.get("t_fin")
    activa = t_fin is None
    f = _vacia(t_ini)
    f.update(nivel=str(a.get("nivel") or "alarma"), msg=str(a.get("msg") or ""), id=str(a.get("id") or ""),
             tIni=hora(t_ini), tFin="activa" if activa else hora(t_fin),
             duracion="—" if activa or t_ini is None else duracion(float(t_fin) - float(t_ini)),
             ok=not activa)
    return f


def fila_escritura(w):
    """El gateway antepone '[quién] ' al detalle (gateway/servidor.py): se separa en `origen`."""
    msg = str(w.get("msg") or "")
    origen = ""
    if msg.startswith("[") and "]" in msg:
        cierre = msg.index("]")
        origen, msg = msg[1:cierre], msg[cierre + 1:].strip()
    ok = bool(w.get("ok"))
    valor = w.get("valor")
    f = _vacia(w.get("t"))
    f.update(nivel="info" if ok else "aviso", msg=msg, origen=origen, tag=str(w.get("tag") or ""),
             valor="" if valor is None else str(valor), ok=ok)
    return f


_CONVERSORES = {"eventos": fila_evento, "alarmas": fila_alarma, "escrituras": fila_escritura}


def _resumen_publico(res):
    """resumen() del lector en forma cómoda para QML: sin None y con las fechas ya en texto."""
    t_min, t_max = res.get("t_min"), res.get("t_max")
    return {"eventos": int(res.get("eventos") or 0), "alarmas": int(res.get("alarmas") or 0),
            "escrituras": int(res.get("escrituras") or 0), "ruta": str(res.get("ruta") or ""),
            "t_min": float(t_min or 0.0), "t_max": float(t_max or 0.0),
            "desdeTexto": "%s %s" % (fecha(t_min), hora(t_min)[:8]) if t_min else "",
            "hastaTexto": "%s %s" % (fecha(t_max), hora(t_max)[:8]) if t_max else ""}


# ============================================================================
# Modelo de filas
# ============================================================================
class ModeloFilas(QAbstractListModel):
    """Filas de la consulta actual, ya formateadas, con los roles de ARQUITECTURA 6.5."""

    cuentaChanged = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._filas = []
        self._roles = {Qt.UserRole + 1 + i: nombre for i, nombre in enumerate(ROLES)}

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self._filas)

    def roleNames(self):
        return {rol: QByteArray(nombre.encode("ascii")) for rol, nombre in self._roles.items()}

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid() or not 0 <= index.row() < len(self._filas):
            return None
        f = self._filas[index.row()]
        if role == Qt.DisplayRole:
            return f["msg"]
        nombre = self._roles.get(role)
        return f.get(nombre) if nombre is not None else None

    def fijar(self, filas):
        self.beginResetModel()
        self._filas = list(filas)
        self.endResetModel()
        self.cuentaChanged.emit()

    @Slot(int, result="QVariantMap")
    def fila(self, i):
        """Fila `i` como mapa (detalle o copia desde QML); {} fuera de rango."""
        return dict(self._filas[i]) if 0 <= i < len(self._filas) else {}

    cuenta = Property(int, lambda self: len(self._filas), notify=cuentaChanged)


# ============================================================================
# Historial (contexto raíz `historial`)
# ============================================================================
class Historial(QObject):
    """Visor del historial para QML. Ver mds/ARQUITECTURA.md 6.5."""

    rutaChanged = Signal()
    tablaChanged = Signal()
    desdeChanged = Signal()
    hastaChanged = Signal()
    nivelesChanged = Signal()
    textoChanged = Signal()
    tagChanged = Signal()
    soloActivasChanged = Signal()
    soloFallidasChanged = Signal()
    limiteChanged = Signal()
    totalChanged = Signal()
    resumenChanged = Signal()
    errorChanged = Signal()
    ultimoExporteChanged = Signal()
    consultaMsChanged = Signal()
    consultado = Signal()               # tras cada consultar()

    def __init__(self, parent=None, ruta=None):
        super().__init__(parent)
        self._v = {
            "ruta": str(ruta or RUTA_DEFECTO), "tabla": "eventos", "desde": 0.0, "hasta": 0.0,
            "niveles": list(protocolo.NIVELES), "texto": "", "tag": "", "soloActivas": False,
            "soloFallidas": False, "limite": LIMITE_DEFECTO, "total": 0, "resumen": {}, "error": "",
            "ultimoExporte": "", "consultaMs": 0.0,
        }
        self._modelo = ModeloFilas(self)
        self._lector = LectorHistorial(self._v["ruta"])
        self._v["error"] = self._lector.ultimo_error or ""

    # ------------------------------------------------------------------ utilidades
    def _set(self, nombre, valor):
        """Cambia self._v[nombre] y notifica solo si el valor es distinto."""
        if self._v[nombre] == valor:
            return False
        self._v[nombre] = valor
        getattr(self, nombre + "Changed").emit()
        return True

    def _filtros(self, limite):
        """Argumentos para el método del lector que corresponde a la tabla actual."""
        v = self._v
        f = {"desde": v["desde"] or None, "hasta": v["hasta"] or None, "limite": limite}
        texto = v["texto"].strip() or None
        niveles = None if set(v["niveles"]) >= set(protocolo.NIVELES) else list(v["niveles"])
        if v["tabla"] == "eventos":
            f.update(niveles=niveles, texto=texto)
        elif v["tabla"] == "alarmas":
            f.update(solo_activas=v["soloActivas"], niveles=niveles, texto=texto)
        else:
            f.update(tag=v["tag"].strip() or None, solo_fallidas=v["soloFallidas"], texto=texto)
        return f

    def cerrar(self):
        self._lector.cerrar()

    # ------------------------------------------------------------------ setters
    def _set_ruta(self, ruta):
        ruta = str(ruta or RUTA_DEFECTO)
        if ruta == self._v["ruta"]:
            return
        self._lector.cerrar()
        self._lector = LectorHistorial(ruta)
        self._set("ruta", ruta)
        self._modelo.fijar([])
        self._set("total", 0)
        self._set("resumen", {})
        self._set("ultimoExporte", "")
        self._set("error", self._lector.ultimo_error or "")

    def _set_tabla(self, tabla):
        if str(tabla) in TABLAS:
            self._set("tabla", str(tabla))

    def _set_desde(self, v):
        self._set("desde", max(0.0, float(v or 0.0)))

    def _set_hasta(self, v):
        self._set("hasta", max(0.0, float(v or 0.0)))

    def _set_niveles(self, lista):
        try:
            elegidos = set(str(n) for n in lista)
        except TypeError:
            elegidos = set()
        self._set("niveles", [n for n in protocolo.NIVELES if n in elegidos])

    def _set_texto(self, s):
        self._set("texto", str(s or ""))

    def _set_tag(self, s):
        self._set("tag", str(s or ""))

    def _set_solo_activas(self, b):
        self._set("soloActivas", bool(b))

    def _set_solo_fallidas(self, b):
        self._set("soloFallidas", bool(b))

    def _set_limite(self, n):
        try:
            n = int(n)
        except (TypeError, ValueError):
            return
        self._set("limite", max(1, n))

    # ------------------------------------------------------------------ propiedades
    ruta = Property(str, lambda self: self._v["ruta"], _set_ruta, notify=rutaChanged)
    tabla = Property(str, lambda self: self._v["tabla"], _set_tabla, notify=tablaChanged)
    desde = Property(float, lambda self: self._v["desde"], _set_desde, notify=desdeChanged)
    hasta = Property(float, lambda self: self._v["hasta"], _set_hasta, notify=hastaChanged)
    niveles = Property("QVariantList", lambda self: list(self._v["niveles"]), _set_niveles, notify=nivelesChanged)
    texto = Property(str, lambda self: self._v["texto"], _set_texto, notify=textoChanged)
    tag = Property(str, lambda self: self._v["tag"], _set_tag, notify=tagChanged)
    soloActivas = Property(bool, lambda self: self._v["soloActivas"], _set_solo_activas, notify=soloActivasChanged)
    soloFallidas = Property(bool, lambda self: self._v["soloFallidas"], _set_solo_fallidas, notify=soloFallidasChanged)
    limite = Property(int, lambda self: self._v["limite"], _set_limite, notify=limiteChanged)

    filas = Property(QObject, lambda self: self._modelo, constant=True)
    total = Property(int, lambda self: self._v["total"], notify=totalChanged)
    resumen = Property("QVariantMap", lambda self: dict(self._v["resumen"]), notify=resumenChanged)
    error = Property(str, lambda self: self._v["error"], notify=errorChanged)
    ultimoExporte = Property(str, lambda self: self._v["ultimoExporte"], notify=ultimoExporteChanged)
    consultaMs = Property(float, lambda self: self._v["consultaMs"], notify=consultaMsChanged)
    tablas = Property("QVariantList", lambda self: list(TABLAS), constant=True)

    # ------------------------------------------------------------------ slots
    @Slot()
    def consultar(self):
        """Consulta la tabla actual con los filtros vigentes y llena `filas`, `total`, `resumen`, `error`."""
        t0 = time.perf_counter()
        tabla = self._v["tabla"]
        crudas = getattr(self._lector, tabla)(**self._filtros(self._v["limite"]))
        conversor = _CONVERSORES[tabla]
        self._modelo.fijar([conversor(f) for f in crudas])
        res = self._lector.resumen()
        self._set("total", int(res.get(tabla) or 0))
        self._set("resumen", _resumen_publico(res))
        self._set("error", self._lector.ultimo_error or "")
        self._set("consultaMs", round((time.perf_counter() - t0) * 1000.0, 2))
        self.consultado.emit()

    @Slot(float)
    def ultimas(self, horas):
        """Rango rápido: `desde` = ahora − horas (0 o menos = sin límite), `hasta` = sin límite, y consulta."""
        try:
            horas = float(horas)
        except (TypeError, ValueError):
            horas = 0.0
        self._set("desde", time.time() - horas * 3600.0 if horas > 0 else 0.0)
        self._set("hasta", 0.0)
        self.consultar()

    @Slot(result=str)
    def exportarCsv(self):
        """Exporta la tabla actual con los filtros vigentes (sin límite). Devuelve la ruta o '' si falló."""
        tabla = self._v["tabla"]
        carpeta = os.path.join(os.path.dirname(os.path.abspath(self._v["ruta"])), "exportes")
        ruta = os.path.join(carpeta, "%s_%s.csv" % (tabla, datetime.now().strftime("%Y%m%d-%H%M%S")))
        n = self._lector.exportar_csv(tabla, ruta, **self._filtros(None))
        if n is None:
            self._set("error", self._lector.ultimo_error or "no se pudo exportar el CSV")
            return ""
        self._set("ultimoExporte", ruta)
        self._set("error", "")
        return ruta
