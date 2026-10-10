# -*- coding: utf-8 -*-
"""
core/historial.py — Historial SQLite de eventos, alarmas y escrituras (ARQUITECTURA 4.5).

El bucle del gateway acumula filas durante el ciclo (`evento`, `alarma`, `escritura`) y
llama a `volcar()` una vez por ciclo: el lote pasa a una cola y un hilo escritor propio
lo inserta en una sola transacción. Así el bucle nunca espera al disco.
La conexión sqlite3 vive solo en el hilo escritor.

Tablas:
    eventos(t, nivel, msg, origen)
    alarmas(id, nivel, msg, t_ini, t_fin)       t_fin NULL mientras está activa
    escrituras(t, tag, valor, ok, msg)

Ruta por defecto: datos/historial.sqlite (la carpeta se crea si no existe).

Lectura (`LectorHistorial`, ARQUITECTURA 6.5): API de solo lectura para el visor del HMI y para
herramientas. Como la base está en modo WAL, otro proceso puede leerla mientras el gateway
escribe: los lectores no bloquean al escritor ni al revés y ven la última transacción confirmada.
`Historial` (escritura) no cambia por ello.

Modos: SIM, EMULATE y REAL. Compatibilidad: Python 3.12 a 3.13 (solo stdlib).
"""
from __future__ import annotations

import csv
import os
import queue
import sqlite3
import threading
import time
from datetime import datetime
from pathlib import Path

RUTA_DEFECTO = os.path.join("datos", "historial.sqlite")

_ESQUEMA = """
CREATE TABLE IF NOT EXISTS eventos (t REAL, nivel TEXT, msg TEXT, origen TEXT);
CREATE TABLE IF NOT EXISTS alarmas (id TEXT, nivel TEXT, msg TEXT, t_ini REAL, t_fin REAL);
CREATE TABLE IF NOT EXISTS escrituras (t REAL, tag TEXT, valor TEXT, ok INTEGER, msg TEXT);
CREATE INDEX IF NOT EXISTS ix_eventos_t ON eventos (t);
CREATE INDEX IF NOT EXISTS ix_alarmas_id ON alarmas (id, t_ini);
"""

_FIN = object()


class Historial:
    """Historial no bloqueante. Los métodos de registro se llaman desde un solo hilo."""

    def __init__(self, ruta=RUTA_DEFECTO):
        self.ruta = ruta
        carpeta = os.path.dirname(os.path.abspath(ruta))
        if carpeta and not os.path.isdir(carpeta):
            os.makedirs(carpeta, exist_ok=True)
        self._lote = []
        self._cola = queue.Queue()
        self._error = None
        self._listo = threading.Event()
        self._hilo = threading.Thread(target=self._escritor, name="historial", daemon=True)
        self._hilo.start()
        self._listo.wait(5.0)
        if self._error is not None:
            raise self._error

    # ------------------------------------------------------------------ API del bucle
    def evento(self, ev):
        self._lote.append(("INSERT INTO eventos VALUES (?,?,?,?)",
                           (ev.get("t"), ev.get("nivel"), ev.get("msg"), ev.get("origen"))))

    def alarma(self, al, activa):
        """Registra el inicio (activa=True) o el fin (activa=False) de una alarma."""
        if activa:
            self._lote.append(("INSERT INTO alarmas VALUES (?,?,?,?,NULL)",
                               (al["id"], al["nivel"], al["msg"], al["t_ini"])))
        else:
            t_fin = al.get("t_fin") or time.time()
            self._lote.append(("UPDATE alarmas SET t_fin=? WHERE id=? AND t_ini=? AND t_fin IS NULL",
                               (t_fin, al["id"], al["t_ini"])))

    def escritura(self, t, tag, valor, ok, msg=""):
        self._lote.append(("INSERT INTO escrituras VALUES (?,?,?,?,?)",
                           (t, tag, str(valor), 1 if ok else 0, msg)))

    def volcar(self):
        """Entrega el lote del ciclo al hilo escritor. No espera al disco."""
        if self._lote:
            self._cola.put(self._lote)
            self._lote = []

    def esperar(self, timeout=5.0):
        """Espera a que el hilo escritor vacíe la cola (pruebas y cierre)."""
        ev = threading.Event()
        self._cola.put(ev)
        return ev.wait(timeout)

    def cerrar(self):
        self.volcar()
        self._cola.put(_FIN)
        self._hilo.join(5.0)

    # ------------------------------------------------------------------ hilo escritor
    def _escritor(self):
        try:
            con = sqlite3.connect(self.ruta)
            try:
                con.execute("PRAGMA journal_mode=WAL")
                con.execute("PRAGMA synchronous=NORMAL")
            except sqlite3.DatabaseError:
                pass
            con.executescript(_ESQUEMA)
            con.commit()
        except Exception as e:  # se informa al constructor
            self._error = e
            self._listo.set()
            return
        self._listo.set()
        while True:
            item = self._cola.get()
            if item is _FIN:
                break
            if isinstance(item, threading.Event):
                item.set()
                continue
            try:
                with con:
                    for sql, params in item:
                        con.execute(sql, params)
            except Exception:
                # El historial nunca debe tumbar al gateway: se descarta el lote.
                pass
        con.close()


# ============================================================================
# Lectura (visor del HMI y herramientas): LectorHistorial
# ============================================================================
TABLAS = ("eventos", "alarmas", "escrituras")
LIMITE_DEFECTO = 500


def hora_legible(t):
    """Epoch → 'AAAA-MM-DD HH:MM:SS.mmm' en hora local; '' si no hay valor."""
    if t is None or t == "":
        return ""
    try:
        return datetime.fromtimestamp(float(t)).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
    except (TypeError, ValueError, OverflowError, OSError):
        return ""


def _uri_solo_lectura(ruta):
    """URI `file:///…?mode=ro` de la ruta. SQLite exige barras `/` y espacios escapados (%20)."""
    return Path(ruta).resolve().as_uri() + "?mode=ro"


def _patron_like(texto):
    """`%texto%` con los comodines de LIKE escapados (la consulta lleva ESCAPE '\\')."""
    t = str(texto).replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return "%" + t + "%"


# Columnas del CSV por tabla: (nombre, función fila -> valor). Además del epoch se escribe la
# hora legible, para que la hoja de cálculo se entienda sin convertir nada.
_CSV = {
    "eventos": (("t", lambda f: f["t"]), ("fecha_hora", lambda f: hora_legible(f["t"])),
                ("nivel", lambda f: f["nivel"]), ("msg", lambda f: f["msg"]),
                ("origen", lambda f: f["origen"])),
    "alarmas": (("id", lambda f: f["id"]), ("nivel", lambda f: f["nivel"]), ("msg", lambda f: f["msg"]),
                ("t_ini", lambda f: f["t_ini"]), ("inicio", lambda f: hora_legible(f["t_ini"])),
                ("t_fin", lambda f: "" if f["t_fin"] is None else f["t_fin"]),
                ("fin", lambda f: "activa" if f["t_fin"] is None else hora_legible(f["t_fin"])),
                ("duracion_s", lambda f: "" if f["t_fin"] is None or f["t_ini"] is None
                 else "%.3f" % (f["t_fin"] - f["t_ini"]))),
    "escrituras": (("t", lambda f: f["t"]), ("fecha_hora", lambda f: hora_legible(f["t"])),
                   ("tag", lambda f: f["tag"]), ("valor", lambda f: f["valor"]),
                   ("ok", lambda f: 1 if f["ok"] else 0), ("msg", lambda f: f["msg"])),
}


class LectorHistorial:
    """Consultas de SOLO LECTURA sobre el SQLite del gateway (ARQUITECTURA 6.5).

    Puede usarse desde otro proceso (el HMI) mientras el gateway escribe: la base está en modo
    WAL, así que los lectores no bloquean al escritor ni al revés, y cada consulta ve la última
    transacción confirmada. Se abre con `file:…?mode=ro` (nunca modifica el archivo ni lo crea);
    si esa apertura falla se intenta la apertura normal. Si el archivo no existe o está dañado,
    ningún método lanza: devuelven listas vacías (o ceros) y el motivo queda en `ultimo_error`.
    En cada consulta se reintenta abrir, de modo que el visor "se engancha" cuando el gateway
    crea la base más tarde. Un objeto se usa desde un solo hilo (regla de sqlite3).

    Resultados: listas de dicts con los nombres de columna de las tablas, lo más reciente
    primero. `niveles=None` significa todos los niveles y una lista vacía, ninguno. `texto`,
    `tag`: subcadena sin distinguir mayúsculas. `origen`: coincidencia exacta. En `alarmas`,
    `desde`/`hasta` seleccionan las alarmas que estuvieron activas en algún momento del rango
    (una alarma aún activa que empezó antes de `desde` sí aparece). `limite=None` = sin límite.
    """

    def __init__(self, ruta=RUTA_DEFECTO):
        self.ruta = ruta
        self.ultimo_error = None
        self._con = None
        self._abrir()

    # ------------------------------------------------------------------ conexión
    def _abrir(self):
        """Abre la conexión si hace falta y el archivo existe. True si quedó abierta."""
        if self._con is not None:
            return True
        if not os.path.isfile(self.ruta):
            self.ultimo_error = "no existe el archivo %s" % self.ruta
            return False
        try:
            con = sqlite3.connect(_uri_solo_lectura(self.ruta), uri=True, timeout=1.0)
        except (sqlite3.Error, ValueError):
            try:
                con = sqlite3.connect(self.ruta, timeout=1.0)
            except sqlite3.Error as e:
                self.ultimo_error = "no se pudo abrir %s: %s" % (self.ruta, e)
                return False
        con.row_factory = sqlite3.Row
        self._con = con
        self.ultimo_error = None
        return True

    def cerrar(self):
        if self._con is not None:
            try:
                self._con.close()
            except sqlite3.Error:
                pass
            self._con = None

    def _consultar(self, sql, params=()):
        """Ejecuta y devuelve lista de dicts; ante cualquier error, [] y `ultimo_error`."""
        if not self._abrir():
            return []
        try:
            filas = [dict(f) for f in self._con.execute(sql, params).fetchall()]
        except sqlite3.Error as e:
            self.ultimo_error = "error al leer %s: %s" % (self.ruta, e)
            self.cerrar()        # base dañada o borrada: se reintenta abrir en la siguiente consulta
            return []
        self.ultimo_error = None
        return filas

    @staticmethod
    def _armar(tabla, cond, orden, limite):
        sql = "SELECT * FROM " + tabla
        if cond:
            sql += " WHERE " + " AND ".join(cond)
        sql += " ORDER BY " + orden
        if limite is not None:
            sql += " LIMIT %d" % max(0, int(limite))
        return sql

    @staticmethod
    def _rango(columna, desde, hasta, cond, params):
        if desde is not None:
            cond.append(columna + " >= ?")
            params.append(float(desde))
        if hasta is not None:
            cond.append(columna + " <= ?")
            params.append(float(hasta))

    @staticmethod
    def _niveles(niveles, cond, params):
        """None = todos. Lista vacía = ninguno: devuelve False para no consultar."""
        if niveles is None:
            return True
        lista = [str(n) for n in niveles]
        if not lista:
            return False
        cond.append("nivel IN (%s)" % ",".join("?" * len(lista)))
        params.extend(lista)
        return True

    # ------------------------------------------------------------------ consultas
    def eventos(self, desde=None, hasta=None, niveles=None, texto=None, origen=None, limite=LIMITE_DEFECTO):
        cond, params = [], []
        self._rango("t", desde, hasta, cond, params)
        if not self._niveles(niveles, cond, params):
            return []
        if texto:
            cond.append("msg LIKE ? ESCAPE '\\'")
            params.append(_patron_like(texto))
        if origen:
            cond.append("origen = ?")
            params.append(str(origen))
        return self._consultar(self._armar("eventos", cond, "t DESC, rowid DESC", limite), params)

    def alarmas(self, desde=None, hasta=None, solo_activas=False, limite=LIMITE_DEFECTO, niveles=None, texto=None):
        """`niveles` y `texto` (busca en msg e id) son extras opcionales para el visor."""
        cond, params = [], []
        if desde is not None:                 # estuvo activa en algún momento del rango
            cond.append("(t_fin IS NULL OR t_fin >= ?)")
            params.append(float(desde))
        if hasta is not None:
            cond.append("t_ini <= ?")
            params.append(float(hasta))
        if solo_activas:
            cond.append("t_fin IS NULL")
        if not self._niveles(niveles, cond, params):
            return []
        if texto:
            cond.append("(msg LIKE ? ESCAPE '\\' OR id LIKE ? ESCAPE '\\')")
            params.extend([_patron_like(texto)] * 2)
        return self._consultar(self._armar("alarmas", cond, "t_ini DESC, rowid DESC", limite), params)

    def escrituras(self, desde=None, hasta=None, tag=None, solo_fallidas=False, limite=LIMITE_DEFECTO, texto=None):
        """`texto` (busca en msg) es un extra opcional para el visor. `ok` sale como bool."""
        cond, params = [], []
        self._rango("t", desde, hasta, cond, params)
        if tag:
            cond.append("tag LIKE ? ESCAPE '\\'")
            params.append(_patron_like(tag))
        if solo_fallidas:
            cond.append("ok = 0")
        if texto:
            cond.append("msg LIKE ? ESCAPE '\\'")
            params.append(_patron_like(texto))
        filas = self._consultar(self._armar("escrituras", cond, "t DESC, rowid DESC", limite), params)
        for f in filas:
            f["ok"] = bool(f.get("ok"))
        return filas

    def resumen(self):
        """{"eventos": n, "alarmas": n, "escrituras": n, "t_min", "t_max", "ruta"} (t_* None sin filas)."""
        r = {"eventos": 0, "alarmas": 0, "escrituras": 0, "t_min": None, "t_max": None, "ruta": self.ruta}
        if not self._abrir():
            return r
        try:
            for tabla, col in (("eventos", "t"), ("alarmas", "t_ini"), ("escrituras", "t")):
                n, t_min, t_max = self._con.execute(
                    "SELECT COUNT(*), MIN(%s), MAX(%s) FROM %s" % (col, col, tabla)).fetchone()
                r[tabla] = int(n or 0)
                for clave, valor, fn in (("t_min", t_min, min), ("t_max", t_max, max)):
                    if valor is not None:
                        r[clave] = valor if r[clave] is None else fn(r[clave], valor)
        except sqlite3.Error as e:
            self.ultimo_error = "error al leer %s: %s" % (self.ruta, e)
            self.cerrar()
            return r
        self.ultimo_error = None
        return r

    # ------------------------------------------------------------------ exportación
    def exportar_csv(self, tabla, ruta, **filtros):
        """Escribe en `ruta` las filas de `tabla` que cumplen `filtros` (los argumentos del método
        homónimo; `limite` por defecto None = todas), en orden cronológico (la más antigua primero,
        como se lee una hoja de cálculo), UTF-8 con BOM para que Excel lo abra bien y separador coma.
        Devuelve el número de filas escritas, o None si no se pudo leer la base o escribir el
        archivo (motivo en `ultimo_error`). `tabla` desconocida → ValueError.
        """
        if tabla not in TABLAS:
            raise ValueError("tabla desconocida: %s" % tabla)
        filtros.setdefault("limite", None)
        filas = getattr(self, tabla)(**filtros)
        if self._con is None:                 # sin base (no existe, dañada): nada que exportar
            return None
        filas.reverse()
        columnas = _CSV[tabla]
        try:
            carpeta = os.path.dirname(os.path.abspath(ruta))
            if carpeta and not os.path.isdir(carpeta):
                os.makedirs(carpeta, exist_ok=True)
            with open(ruta, "w", encoding="utf-8-sig", newline="") as f:
                w = csv.writer(f)
                w.writerow([nombre for nombre, _ in columnas])
                for fila in filas:
                    w.writerow([fn(fila) for _, fn in columnas])
        except OSError as e:
            self.ultimo_error = "no se pudo escribir %s: %s" % (ruta, e)
            return None
        return len(filas)
