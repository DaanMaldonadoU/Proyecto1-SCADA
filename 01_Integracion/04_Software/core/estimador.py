# -*- coding: utf-8 -*-
"""
core/estimador.py — Posición estimada del vástago de 1A/2A/3A a partir de bits.

Qué hace:
    En modo REAL el gateway solo entrega bits (bobinas EV_E{n}/EV_C{n} y sensores de
    fin de carrera SC{n}/SE{n}); no hay sensor de posición intermedia. Este módulo:
      1. detecta el flanco de subida de la bobina y arranca una carrera estimada
         (interpolación lineal con la duración calibrada);
      2. mide el tiempo real hasta que llega el sensor de destino y lo registra en
         core.calibracion.Calibracion;
      3. fija la posición en el extremo cuando el sensor lo confirma (si llega antes
         de que acabe la estimación, la posición "salta"; si llega después, el
         vástago espera en el extremo).

Dónde se usa:
    HMI (ui/cliente.py, clase Planta). En REAL su `pos` es la que se dibuja; en
    SIM/EMULATE solo mide y alimenta la calibración (la `pos` viene del gateway).

Reloj:
    `t` lo da el llamador (time.perf_counter() del HMI, en segundos). El módulo no
    consulta ningún reloj propio, así se prueba con tiempos sintéticos.

Compatibilidad: Python 3.12 a 3.13, solo biblioteca estándar.
"""
from core.tags import CILINDROS

TIMEOUT_S = 10.0        # sin sensor de destino tras este tiempo se abandona la carrera


class _EstadoCilindro(object):
    """Estado interno de un cilindro (no forma parte de la API)."""

    __slots__ = ("ev_e", "ev_c", "se", "sc", "pos", "pos0", "t0", "objetivo",
                 "direccion", "duracion_ms", "midiendo", "ultima_dir")

    def __init__(self):
        self.ev_e = None        # valores del snapshot anterior (None = aún no visto)
        self.ev_c = None
        self.se = False
        self.sc = False
        self.pos = 0.0          # sin información se supone retraído
        self.pos0 = 0.0
        self.t0 = 0.0
        self.objetivo = 0.0
        self.direccion = None   # "ext" | "ret" mientras hay carrera estimada
        self.duracion_ms = 0
        self.midiendo = False   # la carrera actual se registrará al llegar el sensor
        self.ultima_dir = "ext"


class EstimadorCarrera:
    """Estima la posición de 1A/2A/3A cuando el gateway no da `pos` (modo REAL).
    Mide además los tiempos reales de carrera y los registra en la Calibracion."""

    def __init__(self, calibracion, cilindros=(1, 2, 3)):
        self.calibracion = calibracion
        self.cilindros = tuple(int(n) for n in cilindros)
        self._tags = {n: CILINDROS[n] for n in self.cilindros}   # (EV_E, EV_C, SC, SE)
        self._resetv_prev = None
        self._estado = {}
        self.reiniciar()

    def reiniciar(self):
        """Olvida el estado de las carreras (no toca la calibración)."""
        self._estado = {n: _EstadoCilindro() for n in self.cilindros}
        self._resetv_prev = None

    def actualizar(self, t, bits):
        """Aplica un snapshot de bits en el instante `t` (s) y devuelve, por cilindro:
        {"objetivo", "duracion_ms", "pos", "moviendo", "confirmado", "direccion"}
        (+ "timeout": True en la vuelta en que se abandona una carrera)."""
        # Paro: con ACTIVE == 0 no se mide (si falta la clave se supone en marcha).
        activo = bool(bits.get("ACTIVE", True))
        resetv = bool(bits.get("RESETV", False))
        flanco_reset = resetv and self._resetv_prev is False
        self._resetv_prev = resetv

        salida = {}
        for n in self.cilindros:
            salida[n] = self._actualizar_uno(n, self._estado[n], t, bits, activo, flanco_reset)
        return salida

    # ------------------------------------------------------------------ internos
    def _actualizar_uno(self, n, e, t, bits, activo, flanco_reset):
        tag_e, tag_c, tag_sc, tag_se = self._tags[n]
        ev_e = bool(bits.get(tag_e, False))
        ev_c = bool(bits.get(tag_c, False))
        sc = bool(bits.get(tag_sc, False))
        se = bool(bits.get(tag_se, False))
        primera = e.ev_e is None
        timeout = False

        if not activo or flanco_reset:
            e.midiendo = False

        if not primera:
            # Flancos de subida. Si suben las dos a la vez (no debería), gana la última
            # procesada, que es la retracción: el estado seguro de la máquina.
            if ev_e and not e.ev_e:
                self._flanco(e, t, "ext", destino=se, origen=(sc or e.sc), activo=activo, n=n)
            if ev_c and not e.ev_c:
                self._flanco(e, t, "ret", destino=sc, origen=(se or e.se), activo=activo, n=n)

        confirmado = False
        if e.direccion is not None:
            llegada = se if e.direccion == "ext" else sc
            if llegada:
                if e.midiendo:
                    self.calibracion.registrar(n, e.direccion, (t - e.t0) * 1000.0)
                e.pos = e.objetivo
                e.direccion = None
                e.midiendo = False
                confirmado = True
            else:
                e.pos = self._interpolar(e, t)
                if t - e.t0 >= TIMEOUT_S:
                    # Sin sensor de destino: se abandona sin registrar y la posición
                    # queda en la última estimación.
                    e.direccion = None
                    e.midiendo = False
                    timeout = True

        if e.direccion is None:
            # Reposo: mandan los sensores; con ninguno (o ambos) se conserva la estimación.
            if se and not sc:
                e.pos, e.objetivo, confirmado = 1.0, 1.0, True
            elif sc and not se:
                e.pos, e.objetivo, confirmado = 0.0, 0.0, True

        e.ev_e, e.ev_c, e.se, e.sc = ev_e, ev_c, se, sc

        moviendo = e.direccion is not None
        r = {
            "objetivo": e.objetivo,
            "duracion_ms": e.duracion_ms if moviendo
            else self.calibracion.duracion_ms(n, e.ultima_dir),
            "pos": e.pos,
            "moviendo": moviendo,
            "confirmado": confirmado,
            "direccion": e.direccion,
        }
        if timeout:
            r["timeout"] = True
        return r

    def _flanco(self, e, t, direccion, destino, origen, activo, n):
        """Flanco de subida de una bobina. Si el sensor de destino ya está activo no hay
        carrera (el cilindro ya está ahí). Si hay otra carrera en curso, se cancela su
        medición y la nueva parte de la posición estimada actual."""
        e.midiendo = False
        e.ultima_dir = direccion
        if destino:
            e.direccion = None
            return
        if e.direccion is not None:
            e.pos = self._interpolar(e, t)
        e.pos0 = e.pos
        e.t0 = t
        e.direccion = direccion
        e.objetivo = 1.0 if direccion == "ext" else 0.0
        e.duracion_ms = self.calibracion.duracion_ms(n, direccion)
        # Solo se mide una carrera completa: el cilindro debía estar en el extremo de
        # origen (sensor activo ahora o en el snapshot anterior) y la máquina en marcha.
        e.midiendo = bool(activo and origen)

    @staticmethod
    def _interpolar(e, t):
        dur = e.duracion_ms / 1000.0
        f = 1.0 if dur <= 0 else min(1.0, max(0.0, (t - e.t0) / dur))
        return e.pos0 + (e.objetivo - e.pos0) * f
