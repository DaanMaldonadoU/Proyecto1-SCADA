# -*- coding: utf-8 -*-
"""
gateway/fisica.py — Modelo físico de la planta para SIM y EMULATE.

* Fisica: cilindros 1A/2A/3A de doble efecto con válvula 5/2 biestable. La posición del
  vástago (0 = retraído, 1 = extendido) avanza con velocidad constante en la dirección de la
  última bobina energizada: la válvula biestable conserva la posición del carrete, así que
  el cilindro termina su carrera aunque la bobina se apague (p. ej. un RESET a media carrera;
  antes de la sesión 14 se quedaba a medias y la secuencia no salía de X0 porque faltaba su SC).
  La carrera se configura por cilindro y por dirección para que la calibración del HMI tenga
  algo que medir. Sensores: SC si pos ≤ 0,02; SE si pos ≥ 0,98.
* CadenaNeumatica: 4A/5A de simple efecto, sin sensores ni bobinas en el PLC. Solo existe
  un modelo de tiempos durante la etapa X7 (ARQUITECTURA 4.2): 4A sale, tras un retardo
  sale 5A, y ambos regresan por muelle.

Modos: SIM (backend_sim) y EMULATE (backend_opc escribe los sensores en I:1.0). En REAL
solo se usa CadenaNeumatica para estimar 4A/5A.
Compatibilidad: Python 3.12 a 3.13, sin dependencias externas.
"""
from __future__ import annotations

from core import tags

# Carreras por defecto en segundos: cilindro -> (extender, retraer)
CARRERAS_DEFECTO = {
    1: (0.80, 0.75),
    2: (0.90, 0.85),
    3: (0.70, 0.70),
}
UMBRAL_SC = 0.02
UMBRAL_SE = 0.98


class Fisica:
    """Tres cilindros 1A/2A/3A. `pos[i]` ∈ [0, 1] para el cilindro i+1."""

    def __init__(self, carreras=None, pos_inicial=None):
        base = dict(CARRERAS_DEFECTO)
        if carreras:
            base.update(carreras)
        self.carreras = [tuple(base[n]) for n in tags.CILINDROS]
        self.pos = list(pos_inicial) if pos_inicial else [0.0] * len(self.carreras)
        self.carrete = [0] * len(self.carreras)     # +1 extender, -1 retraer, 0 sin orden todavía

    def step(self, dt, ev):
        """Avanza `dt` segundos. ev = [(EV_E, EV_C)] × 3 → [(SC, SE)] × 3.

        Una sola bobina energizada mueve el carrete hacia su lado. Con ninguna, o con las dos a
        la vez (no debería ocurrir), el carrete se queda donde estaba (válvula biestable) y el
        vástago sigue hacia el extremo de la última orden hasta llegar al tope."""
        dt = max(0.0, float(dt))
        for k, (e, c) in enumerate(ev):
            if e and not c:
                self.carrete[k] = 1
            elif c and not e:
                self.carrete[k] = -1
            t_ext, t_ret = self.carreras[k]
            if self.carrete[k] > 0:
                self.pos[k] = min(1.0, self.pos[k] + dt / t_ext)
            elif self.carrete[k] < 0:
                self.pos[k] = max(0.0, self.pos[k] - dt / t_ret)
        return self.sensores()

    def sensores(self):
        """[(SC, SE)] × 3 para la posición actual."""
        return [(p <= UMBRAL_SC, p >= UMBRAL_SE) for p in self.pos]

    def sensores_por_tag(self):
        """{'SC1': bool, 'SE1': bool, ...} con los nombres de core.tags.CILINDROS."""
        d = {}
        for (sc, se), (_e, _c, tag_sc, tag_se) in zip(self.sensores(), tags.CILINDROS.values()):
            d[tag_sc] = sc
            d[tag_se] = se
        return d

    @staticmethod
    def ev_de_bits(bits):
        """[(EV_E1, EV_C1), (EV_E2, EV_C2), (EV_E3, EV_C3)] a partir de un dict de bits."""
        return [(bool(bits.get(e)), bool(bits.get(c))) for e, c, _sc, _se in tags.CILINDROS.values()]


class CadenaNeumatica:
    """Modelo de tiempos de 4A/5A durante X7 (sin sensores en el PLC)."""

    def __init__(self, t4_ext=0.6, t5_ini=1.2, t5_ext=0.6, t_ret=2.8, dur_ret=0.7):
        self.t4_ext = float(t4_ext)
        self.t5_ini = float(t5_ini)
        self.t5_ext = float(t5_ext)
        self.t_ret = float(t_ret)
        self.dur_ret = float(dur_ret)

    @staticmethod
    def _rampa(t, t0, dur):
        if t <= t0:
            return 0.0
        if dur <= 0:
            return 1.0
        return min(1.0, (t - t0) / dur)

    def posiciones(self, t_etapa, en_x7):
        """[p4, p5] ∈ [0, 1]. Fuera de X7 ambos en 0."""
        if not en_x7:
            return [0.0, 0.0]
        t = max(0.0, float(t_etapa))
        p4 = self._rampa(min(t, self.t_ret), 0.0, self.t4_ext)
        p5 = self._rampa(min(t, self.t_ret), self.t5_ini, self.t5_ext)
        if t > self.t_ret:
            # Regreso por muelle desde la posición alcanzada en t_ret.
            f = 1.0 - self._rampa(t, self.t_ret, self.dur_ret)
            p4 *= f
            p5 *= f
        return [round(p4, 4), round(p5, 4)]
