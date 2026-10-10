# -*- coding: utf-8 -*-
"""
gateway/ladder_sim.py — Ladder del 18-sep (LAD 2, 26 escalones) traducido a Python.

Reproduce la lógica de docs/TABLA_DE_VARIABLES.md secciones 4 y 5 con los nombres de tag y las
direcciones de core.tags (tabla vigente: I:1.0, O:2.0, B3:0, B3:3, T4:0..5, C5:0).
Orden de cada `scan(dt)`, igual que los escalones del PLC:
    0000 GM  → 0001 GS → 0002..0010 transiciones (una por scan) → 0011..0016 TON
    → 0017 OSR + CTU C5:0 → 0018..0023 salidas EV → 0024 END = X8

Los TON llevan un acumulador flotante interno en segundos; el ACC expuesto es
min(PRE, int(acum / 0.01)) y DN = acum ≥ PRE·0.01, así un `dt` pequeño no congela el
temporizador (el viejo `int(round(dt*100))` se quedaba en 0 por debajo de 5 ms).

Modo: SIM (lo usa gateway/backend_sim.py). Los sensores y pulsadores (I:1.0) los fija
quien lo usa (física o órdenes `entrada`); las salidas O:2.0 solo las escribe el ladder.
Compatibilidad: Python 3.12 a 3.13, sin dependencias externas.
"""
from __future__ import annotations

from core import tags

_T = tags.tag_timer
_DIR_A_TAG = {d: t for t, d in tags.DIRECCION.items()}
N_ETAPAS = 9


class Ladder:
    """Estado de la tabla de datos del SLC y lógica de los 26 escalones."""

    def __init__(self):
        self.bits = {t: False for t in tags.TAGS_BIT}
        self.ints = {t: 0 for t in tags.TAGS_INT}
        self.bits["STOP_1"] = True                     # pulsador NC: 1 en reposo
        for n in range(5):
            self.ints[_T(n, "PRE")] = tags.PRESETS_DEFECTO["T_ESPERA"]
        self.ints[_T(tags.TIMER_NEUMATICO, "PRE")] = tags.PRESETS_DEFECTO["T_NEUM"]
        self.ints["C_PRE"] = tags.PRESETS_DEFECTO["N_CICLOS"]
        # Internos que no se publican
        self.first_pass = True                         # S:1/15
        self.osr_x7 = False                            # B3:2/0 (almacenamiento del OSR)
        self.acum = [0.0] * tags.N_TIMERS              # acumuladores flotantes de los TON (s)
        self.t_total = 0.0                             # tiempo simulado total (s)

    # ------------------------------------------------------------------ utilidades
    def X(self, i):
        return self.bits["X%d" % i]

    def DN(self, n):
        return self.bits[_T(n, "DN")]

    def etapa(self):
        return tags.etapa_activa(self.bits)

    def _reset_ton(self, n):
        self.acum[n] = 0.0
        self.ints[_T(n, "ACC")] = 0
        self.bits[_T(n, "DN")] = False

    # ------------------------------------------------------------------ scan
    def scan(self, dt):
        """Un barrido completo del programa. `dt` en segundos reales desde el barrido anterior."""
        b, i = self.bits, self.ints
        dt = max(0.0, float(dt))
        self.t_total += dt
        start = b["START_1"] or b["STARTV"]

        # 0000 GM: ACTIVE = (START_1 + STARTV + ACTIVE) · STOP_1 · ¬STOPV
        b["ACTIVE"] = (start or b["ACTIVE"]) and b["STOP_1"] and not b["STOPV"]
        act = b["ACTIVE"]

        # 0001 GS: first pass + END + (START_1 · STOP pulsado) + RESETV → MOV 1 → B3:3, RES C5:0
        if self.first_pass or b["END"] or (b["START_1"] and not b["STOP_1"]) or b["RESETV"]:
            for k in range(N_ETAPAS):
                b["X%d" % k] = (k == 0)
            i["C_ACC"] = 0
            b["END"] = False
            for n in range(tags.N_TIMERS):
                self._reset_ton(n)
        self.first_pass = False

        # 0002..0010 transiciones: OTU origen / OTL destino; una sola por barrido
        c_menor = i["C_ACC"] < i["C_PRE"]
        sc1, se1, sc2, se2, sc3, se3 = (b[s] for s in ("SC1", "SE1", "SC2", "SE2", "SC3", "SE3"))
        transiciones = (
            (0, 1, sc1 and sc2 and sc3 and start),
            (1, 2, se1),
            (2, 3, self.DN(0) and sc1),
            (3, 4, self.DN(1) and se2),
            (4, 5, self.DN(2) and sc2),
            (5, 6, self.DN(3) and se3),
            (6, 7, self.DN(4) and sc3),
            (7, 1, self.DN(5) and sc3 and c_menor),
            (7, 8, self.DN(5) and not c_menor),
        )
        if act:
            for origen, destino, receptividad in transiciones:
                if self.X(origen) and receptividad:
                    b["X%d" % origen] = False
                    b["X%d" % destino] = True
                    break

        # 0011..0016 TON: T4:0..T4:4 con X2..X6, T4:5 con X7 (base 0.01 s)
        for n in range(tags.N_TIMERS):
            etapa_en = n + 2 if n < 5 else 7
            if self.X(etapa_en):
                pre_s = i[_T(n, "PRE")] * tags.BASE_TIEMPO_S
                # Como en el SLC, el ACC deja de crecer al llegar al PRE.
                self.acum[n] = min(self.acum[n] + dt, max(pre_s, self.acum[n]))
                i[_T(n, "ACC")] = min(i[_T(n, "PRE")], int(self.acum[n] / tags.BASE_TIEMPO_S + 1e-9))
                b[_T(n, "DN")] = self.acum[n] + 1e-9 >= pre_s
            else:
                self._reset_ton(n)

        # 0017 X7 → OSR B3:2/0 → CTU C5:0
        x7 = self.X(7)
        if x7 and not self.osr_x7:
            i["C_ACC"] = min(tags.LIMITE_PRE, i["C_ACC"] + 1)
        self.osr_x7 = x7

        # 0018..0023 salidas (no dependen de ACTIVE: paro funcional)
        X, DN = self.X, self.DN
        b["EV_E1"] = X(1) or (X(2) and not DN(0))
        b["EV_C1"] = (X(2) and DN(0)) or (X(3) and not DN(1)) or (X(0) and se1) or (X(7) and DN(5) and se1)
        b["EV_E2"] = (X(3) and DN(1)) or (X(4) and not DN(2))
        b["EV_C2"] = (X(4) and DN(2)) or (X(5) and not DN(3)) or (X(0) and se2) or (X(7) and DN(5) and se2)
        b["EV_E3"] = (X(5) and DN(3)) or (X(6) and not DN(4))
        b["EV_C3"] = (X(6) and DN(4)) or (X(7) and not DN(5)) or (X(0) and se3) or (X(7) and DN(5) and se3)

        # 0024 X8 → END
        b["END"] = X(8)

    # ------------------------------------------------------------------ tabla de datos
    def palabras(self):
        """{'I:1.0': int, 'O:2.0': int, 'B3:0': int, 'B3:3': int} a partir de los bits."""
        return {p: tags.codificar_palabra(p, {t: self.bits[t] for t in tabla})
                for p, tabla in tags.PALABRAS.items()}

    def leer(self, direccion):
        """Valor de una dirección RSLinx de core.tags (palabra, bit o entero)."""
        if direccion in tags.PALABRAS:
            return self.palabras()[direccion]
        tag = self._tag_de(direccion)
        if tag in self.bits:
            return self.bits[tag]
        return self.ints[tag]

    def escribir(self, direccion, valor):
        """Escribe una dirección RSLinx (`B3:0/0`, `T4:0.PRE`, `C5:0.PRE`, `I:1.0/2`, `I:1.0`…).

        Las salidas O:2 son autoridad del ladder y se rechazan con ValueError.
        """
        if direccion.startswith(tags.PREFIJOS_PROHIBIDOS):
            raise ValueError("prohibido escribir salidas (%s)" % direccion)
        if direccion in tags.PALABRAS:
            for tag, v in tags.decodificar_palabra(direccion, valor).items():
                self.bits[tag] = v
            return
        tag = self._tag_de(direccion)
        if tag in self.bits:
            self.bits[tag] = bool(valor)
        else:
            v = int(valor)
            if not (0 <= v <= tags.LIMITE_PRE):
                raise ValueError("valor fuera de rango para %s: %d" % (direccion, v))
            self.ints[tag] = v

    @staticmethod
    def _tag_de(direccion):
        tag = _DIR_A_TAG.get(direccion)
        if tag is None and "/" in direccion and direccion[0] in "IO":
            palabra, bit = tags.direccion_a_palabra_bit(direccion)   # 'I:1/3' -> 'I:1.0/3'
            tag = _DIR_A_TAG.get("%s/%d" % (palabra, bit))
        if tag is None:
            raise KeyError("dirección desconocida: %s" % direccion)
        return tag
