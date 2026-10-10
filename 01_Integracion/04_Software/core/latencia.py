# -*- coding: utf-8 -*-
"""
core/latencia.py — Estadísticas de tiempos de lectura, de ciclo y de periodo del gateway.

El servidor mide con time.perf_counter() cada lectura del grupo rápido, el trabajo de
cada ciclo y el periodo efectivo entre ciclos, y llama a `registrar`. `resumen` da el
diccionario `snapshot["lat"]` (claves de core.protocolo.latencia_vacia) y `historial`
la serie para la tendencia del HMI.

Modos: SIM, EMULATE y REAL (lo usa el gateway en todos).
Compatibilidad: Python 3.12 a 3.13, sin dependencias externas.
"""
from __future__ import annotations

import time
from collections import deque

# Muestras usadas para promediar el periodo efectivo publicado (suaviza el jitter del reloj).
_MUESTRAS_PERIODO = 20


def percentil(valores, p):
    """Percentil p (0..100) por interpolación lineal. Lista vacía -> 0.0."""
    if not valores:
        return 0.0
    orden = sorted(valores)
    if len(orden) == 1:
        return float(orden[0])
    k = (len(orden) - 1) * (p / 100.0)
    i = int(k)
    f = k - i
    if i + 1 >= len(orden):
        return float(orden[-1])
    return float(orden[i] + (orden[i + 1] - orden[i]) * f)


class EstadisticasLatencia:
    """Ventana deslizante de las últimas `ventana` muestras (t, lectura_ms, ciclo_ms, periodo_ms)."""

    def __init__(self, ventana=200):
        self.ventana = int(ventana)
        self._muestras = deque(maxlen=self.ventana)

    def registrar(self, lectura_ms, ciclo_ms, periodo_ms):
        """Guarda una muestra. Los tiempos van en milisegundos."""
        self._muestras.append((time.time(), float(lectura_ms), float(ciclo_ms), float(periodo_ms)))

    def __len__(self):
        return len(self._muestras)

    def resumen(self, fuente):
        """Diccionario con las claves de core.protocolo.latencia_vacia()."""
        if not self._muestras:
            return {"lectura_ms": 0.0, "lectura_max_ms": 0.0, "ciclo_ms": 0.0,
                    "periodo_ms": 0.0, "p95_ms": 0.0, "fuente": fuente}
        lecturas = [m[1] for m in self._muestras]
        ultima = self._muestras[-1]
        periodos = [m[3] for m in list(self._muestras)[-_MUESTRAS_PERIODO:] if m[3] > 0]
        periodo = sum(periodos) / len(periodos) if periodos else 0.0
        return {
            "lectura_ms": round(ultima[1], 3),
            "lectura_max_ms": round(max(lecturas), 3),
            "ciclo_ms": round(ultima[2], 3),
            "periodo_ms": round(periodo, 3),
            "p95_ms": round(percentil(lecturas, 95), 3),
            "fuente": fuente,
        }

    def periodos(self):
        """Lista de periodos registrados (ms), útil para pruebas y el resumen de la demo."""
        return [m[3] for m in self._muestras if m[3] > 0]

    def historial(self, n=100):
        """[(t, lectura_ms), ...] de las últimas n muestras, para la gráfica del HMI."""
        return [(m[0], m[1]) for m in list(self._muestras)[-int(n):]]
