# -*- coding: utf-8 -*-
"""
gateway/backend_sim.py — Backend SIM: ladder del 18-sep + física en el mismo proceso.

Misma interfaz que backend_opc.BackendOPC para que el servidor no sepa cuál usa:
    conectar(), leer_rapido(), leer_lento(), escribir(pares), cerrar()
    propiedades: modo ("SIM"), fuente ("sim"), conectado, pos, pos_neum, fisica_auto
`leer_*` devuelven (valores {dirección: valor}, calidad {dirección: bool}, t_lectura_ms).

En cada `leer_rapido` el simulador avanza el tiempo real transcurrido desde la lectura
anterior (time.perf_counter), partido en barridos de como mucho `dt_scan` segundos
(el SLC barre cada pocos ms; así las transiciones encadenadas no pierden tiempo).
Por barrido: física (con las EV del barrido anterior) → sensores en I:1.0 → scan.

Física automática: los sensores los calcula la física. Manual: los fija la orden
`entrada` (el servidor llama a `escribir` con la dirección del sensor).

Enlace simulado (`enlace_lento=True`, `python -m gateway --modo SIM --simular-enlace`): imita lo
medido en el laboratorio el 2026-10-03 con el ENI ↔ SLC (docs/DIAGNOSTICO_CONEXION_PLC.md §6):
cada archivo del PLC (I:1, O:2, B3, T4, C5) se refresca por su cuenta cada 0,15–0,45 s casi
siempre y, a veces, tras uno o dos reintentos DF1 de ~1 s (mediana ~0,35 s, p90 ~1,3 s). Entre
refrescos se devuelve el valor viejo. Además `pos` y `pos_neum` valen None, como en REAL: el HMI
y el puente tienen que estimar la posición. Sirve para probar el modo suave sin el PLC.

Modo: SIM. Compatibilidad: Python 3.12 a 3.13, sin COM ni OpenOPC.
"""
from __future__ import annotations

import random
import time

from core import tags
from gateway.fisica import CadenaNeumatica, Fisica
from gateway.ladder_sim import Ladder

DT_SCAN = 0.005        # s: barrido máximo del simulador
DT_MAX = 1.0           # s: si el proceso estuvo parado más, no se simula de golpe más que esto
_SENSORES_DIR = set(tags.DIRECCION[s] for s in tags.SENSORES)


def archivo_plc(direccion):
    """'I:1.0/3' → 'I', 'B3:3' → 'B3', 'T4:5.ACC' → 'T4': RSLinx lee cada archivo en su paquete DF1."""
    return str(direccion).split(":", 1)[0]


class EnlaceLento:
    """Caché por archivo con refresco irregular, como la de RSLinx sobre el enlace serie lento."""

    # (probabilidad, mínimo s, máximo s) del intervalo entre refrescos de un archivo
    INTERVALOS = ((0.62, 0.15, 0.45), (0.28, 0.9, 1.4), (0.10, 1.9, 2.4))

    def __init__(self, semilla=None):
        self._rnd = random.Random(semilla)
        self._cache = {}        # archivo -> {dirección: valor}
        self._proximo = {}      # archivo -> perf_counter del siguiente refresco

    def intervalo(self):
        r = self._rnd.random()
        for p, a, b in self.INTERVALOS:
            if r < p:
                return self._rnd.uniform(a, b)
            r -= p
        return self._rnd.uniform(*self.INTERVALOS[-1][1:])

    def filtrar(self, valores, t):
        """Valores «como los vería RSLinx»: cada archivo, el de su último refresco."""
        por_archivo = {}
        for d, v in valores.items():
            por_archivo.setdefault(archivo_plc(d), {})[d] = v
        salida = {}
        for a, actuales in por_archivo.items():
            cache = self._cache.setdefault(a, {})
            if t >= self._proximo.get(a, 0.0):
                cache.update(actuales)
                self._proximo[a] = t + self.intervalo()
            for d, v in actuales.items():
                salida[d] = cache.setdefault(d, v)
        return salida


class BackendSim:
    """Planta simulada completa: Ladder + Fisica + CadenaNeumatica."""

    modo = "SIM"
    fuente = "sim"

    def __init__(self, carreras=None, cadena=None, fisica_auto=True, dt_scan=DT_SCAN, enlace_lento=False,
                 semilla=None):
        self._carreras = carreras
        self._cadena_cfg = cadena or {}
        self.fisica_auto = bool(fisica_auto)
        self.dt_scan = float(dt_scan)
        self.ladder = None
        self.fis = None
        self.cadena = CadenaNeumatica(**self._cadena_cfg)
        self._conectado = False
        self._t_prev = None
        self._t_x7 = 0.0
        self.enlace = EnlaceLento(semilla) if enlace_lento else None

    # ------------------------------------------------------------------ propiedades
    @property
    def conectado(self):
        return self._conectado

    @property
    def pos(self):
        if self.enlace is not None:
            return None                     # como en REAL: el PLC no tiene sensor de posición
        return [round(p, 4) for p in self.fis.pos] if self.fis else None

    @property
    def pos_neum(self):
        if not self.ladder or self.enlace is not None:
            return None                     # con enlace simulado lo estima el servidor (como en REAL)
        return self.cadena.posiciones(self._t_x7, self.ladder.X(7))

    # ------------------------------------------------------------------ ciclo de vida
    def conectar(self):
        self.ladder = Ladder()
        self.fis = Fisica(self._carreras)
        self._aplicar_sensores()
        self.ladder.scan(0.0)                  # primer barrido (first pass → X0)
        self._t_prev = time.perf_counter()
        self._t_x7 = 0.0
        self._conectado = True

    def cerrar(self):
        self._conectado = False

    # ------------------------------------------------------------------ simulación
    def _aplicar_sensores(self):
        for tag, v in self.fis.sensores_por_tag().items():
            self.ladder.bits[tag] = v

    def avanzar(self, dt):
        """Avanza la planta `dt` segundos simulados (barridos de `dt_scan`)."""
        restante = max(0.0, float(dt))
        while True:
            paso = min(self.dt_scan, restante)
            self.fis.step(paso, Fisica.ev_de_bits(self.ladder.bits))
            if self.fisica_auto:
                self._aplicar_sensores()
            x7_antes = self.ladder.X(7)
            self.ladder.scan(paso)
            if self.ladder.X(7):
                self._t_x7 = self._t_x7 + paso if x7_antes else 0.0
            else:
                self._t_x7 = 0.0
            restante -= paso
            if restante <= 1e-12:
                break

    def _avanzar_tiempo_real(self):
        ahora = time.perf_counter()
        dt = min(DT_MAX, ahora - self._t_prev) if self._t_prev is not None else 0.0
        self._t_prev = ahora
        self.avanzar(dt)

    # ------------------------------------------------------------------ lectura
    def _leer(self, direcciones):
        if not self._conectado:
            raise RuntimeError("simulador no conectado")
        t0 = time.perf_counter()
        valores = {}
        palabras = self.ladder.palabras()
        for d in direcciones:
            v = palabras[d] if d in palabras else self.ladder.leer(d)
            valores[d] = int(v) if not isinstance(v, bool) else v
        if self.enlace is not None:
            valores = self.enlace.filtrar(valores, t0)
        calidad = {d: True for d in direcciones}
        return valores, calidad, (time.perf_counter() - t0) * 1000.0

    def leer_rapido(self):
        if not self._conectado:
            raise RuntimeError("simulador no conectado")
        t0 = time.perf_counter()
        self._avanzar_tiempo_real()
        valores, calidad, _ = self._leer(tags.ITEMS_RAPIDOS)
        return valores, calidad, (time.perf_counter() - t0) * 1000.0

    def leer_lento(self):
        return self._leer(tags.ITEMS_LENTOS)

    # ------------------------------------------------------------------ escritura
    def escribir(self, pares):
        """[(dirección, valor), ...] → [(dirección, ok, msg), ...]. No lanza por fallos de un par."""
        resultado = []
        for d, v in pares:
            if not self._conectado:
                resultado.append((d, False, "simulador no conectado"))
                continue
            if d in _SENSORES_DIR and self.fisica_auto:
                resultado.append((d, False, "física automática: los sensores los fija la física"))
                continue
            try:
                self.ladder.escribir(d, v)
                resultado.append((d, True, ""))
            except (KeyError, ValueError) as e:
                resultado.append((d, False, str(e)))
        return resultado

    def cambiar_fisica(self, auto):
        self.fisica_auto = bool(auto)
        if self.fisica_auto and self.ladder:
            self._aplicar_sensores()
        return True, "física %s" % ("automática" if self.fisica_auto else "manual")

    def cambiar_fuente(self, fuente):
        return False, "el modo SIM no tiene fuente OPC"
