# -*- coding: utf-8 -*-
"""
core/calibracion.py — Tiempos de carrera medidos de los cilindros 1A/2A/3A.

Qué hace:
    Guarda, por cilindro y dirección ("ext" = extensión, "ret" = retracción), las
    últimas mediciones del tiempo entre el flanco de subida de la bobina y la llegada
    del sensor de destino. La duración que se usa para animar es la MEDIANA entera de
    las últimas `VENTANA` muestras; sin muestras se usa `DEFECTO_MS`.
    Persiste en JSON (escritura atómica: archivo temporal + os.replace) para que la
    calibración sobreviva entre ejecuciones del HMI.

Dónde se usa:
    HMI (ui/cliente.py) en todos los modos; la alimenta core/estimador.py con las
    mediciones hechas a partir de los bits del snapshot. Archivo típico:
    datos/calibracion.json.

Formato del JSON (igual que `como_dict()`):
    {"1": {"ext": {"ms": 812, "muestras": [800, 812, 830]}, "ret": {...}},
     "2": {...}, "3": {...},
     "_meta": {"version": 1, "actualizado": "2026-09-24T10:31:05"}}
    Claves de cilindro como str en el JSON; int en la API.

Compatibilidad: Python 3.12 a 3.13, solo biblioteca estándar.
"""
import datetime
import json
import os
import statistics

from core.tags import CILINDROS

DIRECCIONES = ("ext", "ret")
VERSION_FORMATO = 1


class Calibracion:
    """Tiempos de carrera por cilindro y dirección con mediana móvil y persistencia JSON."""

    DEFECTO_MS = 800
    VENTANA = 5            # mediana móvil de las últimas N mediciones
    MIN_MS = 100           # mediciones fuera de [MIN_MS, MAX_MS] se descartan
    MAX_MS = 10000

    def __init__(self, ruta=None):
        """ruta: archivo JSON; None = sin persistencia. Si el archivo existe, se carga."""
        self.ruta = ruta
        self.descartadas = 0          # mediciones rechazadas por estar fuera de rango
        self.ultimo_error = None      # texto del último fallo de lectura/escritura (o None)
        self.actualizado = None       # marca ISO de la última modificación
        self._muestras = {}           # (cilindro, direccion) -> [ms, ...]
        self._ms = {}                 # (cilindro, direccion) -> mediana en caché
        self._vaciar()
        if ruta:
            self.cargar()

    # ------------------------------------------------------------------ consulta
    def duracion_ms(self, cilindro, direccion):
        """Mediana entera de las últimas muestras, o DEFECTO_MS si no hay ninguna."""
        return self._ms[self._clave(cilindro, direccion)]

    def muestras(self, cilindro, direccion):
        """Copia de las muestras vigentes (más antigua primero, como mucho VENTANA)."""
        return list(self._muestras[self._clave(cilindro, direccion)])

    def como_dict(self):
        """Estructura serializable (la misma que se guarda en el JSON)."""
        d = {}
        for n in CILINDROS:
            d[str(n)] = {
                dr: {"ms": self._ms[(n, dr)], "muestras": list(self._muestras[(n, dr)])}
                for dr in DIRECCIONES
            }
        d["_meta"] = {"version": VERSION_FORMATO, "actualizado": self.actualizado}
        return d

    # ------------------------------------------------------------------ cambios
    def registrar(self, cilindro, direccion, ms):
        """Añade una medición. Fuera de [MIN_MS, MAX_MS] se descarta (suma a
        `descartadas`) sin lanzar excepción. Guarda en disco si hay ruta."""
        clave = self._clave(cilindro, direccion)
        try:
            valor = float(ms)
        except (TypeError, ValueError):
            self.descartadas += 1
            return None
        if not (self.MIN_MS <= valor <= self.MAX_MS):   # también descarta NaN
            self.descartadas += 1
            return None
        lista = self._muestras[clave]
        lista.append(int(round(valor)))
        del lista[:-self.VENTANA]
        self._recalcular(clave)
        self._tocar()
        self._guardar_silencioso()
        return None

    def reiniciar(self):
        """Borra todas las mediciones (vuelve a DEFECTO_MS) y guarda si hay ruta."""
        self._vaciar()
        self.descartadas = 0
        self._tocar()
        self._guardar_silencioso()

    # ------------------------------------------------------------------ disco
    def guardar(self):
        """Escribe el JSON de forma atómica. Crea la carpeta si no existe.
        Lanza OSError si no se puede escribir (registrar/reiniciar lo capturan)."""
        if not self.ruta:
            return None
        carpeta = os.path.dirname(os.path.abspath(self.ruta))
        os.makedirs(carpeta, exist_ok=True)
        temporal = self.ruta + ".tmp"
        with open(temporal, "w", encoding="utf-8") as f:
            json.dump(self.como_dict(), f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temporal, self.ruta)
        return None

    def cargar(self):
        """Lee el JSON. Si no existe, queda vacío. Si está corrupto o tiene un formato
        inesperado, arranca vacío sin fallar (el motivo queda en `ultimo_error`)."""
        self._vaciar()
        if not self.ruta or not os.path.exists(self.ruta):
            return None
        try:
            with open(self.ruta, "r", encoding="utf-8") as f:
                datos = json.load(f)
            if not isinstance(datos, dict):
                raise ValueError("la raíz no es un objeto")
            for n in CILINDROS:
                por_dir = datos.get(str(n))
                if not isinstance(por_dir, dict):
                    continue            # cilindro ausente o mal formado: queda vacío
                for dr in DIRECCIONES:
                    entrada = por_dir.get(dr)
                    crudas = entrada.get("muestras") if isinstance(entrada, dict) else None
                    if not isinstance(crudas, list):
                        crudas = []
                    validas = []
                    for m in crudas:
                        if isinstance(m, bool) or not isinstance(m, (int, float)):
                            continue
                        if self.MIN_MS <= m <= self.MAX_MS:
                            validas.append(int(round(m)))
                    self._muestras[(n, dr)] = validas[-self.VENTANA:]
                    self._recalcular((n, dr))
            meta = datos.get("_meta") or {}
            self.actualizado = meta.get("actualizado") if isinstance(meta, dict) else None
        except (OSError, ValueError, TypeError, AttributeError) as e:
            # json.JSONDecodeError es subclase de ValueError
            self.ultimo_error = "calibración ilegible (%s): %s" % (self.ruta, e)
            self._vaciar()
        return None

    # ------------------------------------------------------------------ internos
    def _clave(self, cilindro, direccion):
        n = int(cilindro)
        if n not in CILINDROS or direccion not in DIRECCIONES:
            raise KeyError("cilindro/dirección inválidos: %r, %r" % (cilindro, direccion))
        return (n, direccion)

    def _vaciar(self):
        for n in CILINDROS:
            for dr in DIRECCIONES:
                self._muestras[(n, dr)] = []
                self._ms[(n, dr)] = self.DEFECTO_MS

    def _recalcular(self, clave):
        lista = self._muestras[clave]
        self._ms[clave] = int(round(statistics.median(lista))) if lista else self.DEFECTO_MS

    def _tocar(self):
        self.actualizado = datetime.datetime.now().isoformat(timespec="seconds")

    def _guardar_silencioso(self):
        try:
            self.guardar()
            self.ultimo_error = None
        except OSError as e:
            self.ultimo_error = "no se pudo guardar la calibración (%s): %s" % (self.ruta, e)
