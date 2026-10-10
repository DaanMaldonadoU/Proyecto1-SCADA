# -*- coding: utf-8 -*-
"""
core/suavizado.py — Modo suave: animación prevista de la planta a partir de lecturas lentas.

Para qué sirve:
    En el laboratorio el enlace serie ENI ↔ SLC refresca la caché de RSLinx cada ~0,3 s (mediana)
    con picos de 1–2 s, y cada archivo del PLC (I:1, O:2, B3, T4, C5) se refresca por separado
    (docs/DIAGNOSTICO_CONEXION_PLC.md). Con eso la pantalla recibe estados atrasados y a saltos:
    una carrera de 0,8 s puede no verse nunca (la bobina y el sensor de llegada aparecen en la
    misma lectura), los vástagos «saltan» al extremo y las barras de los temporizadores avanzan
    a tirones. Este módulo convierte esas lecturas en un movimiento continuo y creíble:

      1. **Cursor del ciclo.** La secuencia del GRAFCET es fija (docs/TABLA_DE_VARIABLES.md §4), así que el
         estado de la máquina se resume en un índice `2·etapa + DN` (X1 = 2, X2 = 4, X2 con T4:0
         hecho = 5, …, X7 con T4:5 hecho = 15). El cursor solo avanza dentro de un ciclo y toma la
         evidencia más reciente de cualquier archivo: los bits de etapa (B3:3), las bobinas (O:2:
         EV_E2 encendida implica X3 con T4:1 hecho) y los temporizadores (T4). Así una lectura
         vieja de B3 no deshace lo que ya mostró O:2. Un ciclo nuevo o un RESET solo los decide
         la lectura de etapa (B3:3), que nunca retrocede salvo en esos casos.
      2. **Temporizadores previstos.** El ACC de un TON crece 100 por segundo mientras su etapa
         está activa (también con STOP: el paro no detiene los TON). Entre lecturas se extrapola
         desde la mejor observación, sin retroceder nunca; al llegar al PRE el DN se da por hecho y
         con él la bobina que el ladder enciende con ese DN (p. ej. EV_C1 = X2·T4:0/DN). Las salidas
         no dependen de ACTIVE, así que esta previsión vale también en paro.
      3. **Vástagos animados.** Cada cilindro va hacia el extremo que pide el cursor a la velocidad
         de su carrera calibrada (core.calibracion, acotada a 0,25…2,5 s). Si la lectura ya
         confirma el extremo (sensor de llegada o una etapa posterior), acelera para llegar en
         ≤ ALCANCE_S, sin saltos. Si el cursor pasó una carrera que nunca se vio (lecturas
         perdidas), la **repone** con una carrera corta (REPOSICION_MS) para que se vea que
         ocurrió. Si el sensor del extremo contrario sigue activo mucho tiempo (cilindro sin aire,
         atascado), manda el sensor y se marca `discrepancia`.
      4. **Sin etapa** (programa del PLC sin B3:3, como el del 03-oct): el objetivo sale de las
         bobinas y, sin bobina, de los sensores; el resto igual.

    La etapa y los ACC que devuelve `muestrear` son **previstos**: nunca adelantan una
    transición del GRAFCET que no se haya leído; solo el DN de la etapa en curso, que el PLC
    activa por tiempo. Los bits y las palabras leídos no se tocan (el monitor de E/S sigue
    mostrando lo que llega del PLC).

Uso:
    s = Suavizador(calibracion, cadena=CadenaNeumatica())
    s.actualizar(t, snapshot)       # cada vez que llega un snapshot (t = perf_counter local, s)
    m = s.muestrear(t)              # cada cuadro (15 ms en el HMI) o antes de mandar al gemelo
    m -> {"pos": [p1, p2, p3], "pos_neum": [p4, p5], "etapa", "t_etapa", "acc": {n: acc},
          "indice", "objetivo": [...], "velocidad": [...], "confirmado": [...], "discrepancia": [...],
          "repuestas", "sin_etapa"}

Dónde se usa: HMI (ui/cliente.py, botón «Suave» del sinóptico) y puente al gemelo
(puente/enlace.py, opción --suave). Ninguno escribe en el PLC por esto.

Reloj: lo da el llamador (segundos monotónicos); el módulo no lee relojes, así se prueba con
tiempos sintéticos (tests/test_suavizado.py).

Compatibilidad: Python 3.12 a 3.13, solo biblioteca estándar.
"""
from __future__ import annotations

from core import tags

DUR_DEFECTO_MS = 800
DUR_MIN_MS = 250
DUR_MAX_MS = 2500
ALCANCE_S = 0.25            # con el extremo confirmado, el vástago llega en como mucho esto
REPOSICION_MS = 350         # duración de una carrera repuesta (no se vio entre dos lecturas)
CONTRADICCION_S = 3.0       # + carrera: el sensor contrario sigue activo → manda el sensor
VEL_NEUM = 1.0 / 0.25       # 4A/5A: velocidad máxima de la animación (fracción de carrera por s)
DT_MAX_S = 0.25             # un cuadro nunca avanza más que esto (ventana minimizada, pausas)
UMBRAL_EXT = 0.98

# Índice del ciclo en que cada cilindro empieza a salir, se confirma afuera (la etapa siguiente
# exige su SE), empieza a regresar y se confirma adentro (la siguiente exige su SC).
# Sale de las ecuaciones de salida del ladder (gateway/ladder_sim.py, escalones 0018–0023):
#   EV_E1 = X1 + X2·¬DN0      EV_C1 = X2·DN0 + X3·¬DN1 + …
#   EV_E2 = X3·DN1 + X4·¬DN2  EV_C2 = X4·DN2 + X5·¬DN3 + …
#   EV_E3 = X5·DN3 + X6·¬DN4  EV_C3 = X6·DN4 + X7·¬DN5 + …
FASES = {1: (2, 4, 5, 6), 2: (7, 8, 9, 10), 3: (11, 12, 13, 14)}
INDICE_FIN_CICLO = 15       # X7 con T4:5 hecho
_ETAPA_DE_TIMER = {n: e for e, n in tags.TIMER_DE_ETAPA.items()}


def _indice(etapa, dn):
    return 2 * int(etapa) + (1 if dn else 0)


class _Cilindro:
    __slots__ = ("pos", "cola", "alcanzo_ext", "objetivo", "vel", "confirmado", "discrepancia",
                 "t_contra")

    def __init__(self):
        self.pos = 0.0
        self.cola = []              # carreras repuestas pendientes: [(objetivo, duración s)]
        self.alcanzo_ext = False    # llegó afuera en este ciclo (no hace falta reponer la salida)
        self.objetivo = 0.0
        self.vel = 0.0
        self.confirmado = False
        self.discrepancia = False
        self.t_contra = None        # desde cuándo el sensor contradice al objetivo


class Suavizador:
    """Animación prevista de 1A/2A/3A, 4A/5A, etapa y temporizadores (ver el docstring del módulo)."""

    def __init__(self, calibracion=None, cadena=None, cilindros=(1, 2, 3)):
        self.calibracion = calibracion
        self.cadena = cadena                # objeto con .posiciones(t_x7, en_x7) (gateway.fisica)
        self.cilindros = tuple(int(n) for n in cilindros)
        self._tags = {n: tags.CILINDROS[n] for n in self.cilindros}
        self.reiniciar()

    # ------------------------------------------------------------------ estado
    def reiniciar(self):
        """Olvida todo lo leído (no toca la calibración)."""
        self._c = {n: _Cilindro() for n in self.cilindros}
        self._bits = {}
        self._ints = {}
        self._conectado = False
        self._pos_iniciadas = False
        self._cursor = None             # índice del ciclo; None = sin etapa
        self._etapa_leida = None        # última etapa leída de B3:3 (nunca retrocede salvo ciclo/RESET)
        self._t_entrada = 0.0           # cuándo entró el cursor en su etapa (reloj local)
        self._m = {}                    # timer -> max(ACC - 100·t) de las observaciones de esta activación
        self._neum = [0.0, 0.0]
        self._neum_leido = [0.0, 0.0]
        self._t_etapa_leido = (0.0, 0.0)  # (t_etapa del snapshot, t local de llegada)
        self._t_muestra = None
        self.repuestas = 0

    @property
    def cursor(self):
        return self._cursor

    def _dur_s(self, n, direccion):
        ms = DUR_DEFECTO_MS
        if self.calibracion is not None:
            try:
                ms = int(self.calibracion.duracion_ms(n, direccion))
            except Exception:
                ms = DUR_DEFECTO_MS
        return min(DUR_MAX_MS, max(DUR_MIN_MS, ms)) / 1000.0

    def _pre(self, timer):
        v = self._ints.get(tags.tag_timer(timer, "PRE"))
        return None if v is None else max(0, int(v))

    def _acc_est(self, timer, t):
        m = self._m.get(timer)
        acc = 0.0 if m is None else max(0.0, m + 100.0 * t)
        pre = self._pre(timer)
        return min(float(pre), acc) if pre is not None else acc

    def _observar_timer(self, timer, acc, t):
        v = float(acc) - 100.0 * t
        if self._m.get(timer) is None or v > self._m[timer]:
            self._m[timer] = v

    # ------------------------------------------------------------------ entrada
    def actualizar(self, t, snap):
        """Aplica un snapshot del gateway (dict de core.protocolo) recibido en el instante `t`."""
        t = float(t)
        conectado = bool(snap.get("conectado", False))
        if not conectado:
            self._conectado = False
            self._cursor = None
            self._etapa_leida = None
            self._pos_iniciadas = False         # al volver, las posiciones se toman de los sensores
            return
        self._conectado = True
        self._bits = {k: bool(v) for k, v in (snap.get("bits") or {}).items()}
        self._ints = {k: int(v) for k, v in (snap.get("ints") or {}).items()}
        pn = snap.get("pos_neum")
        if pn:
            self._neum_leido = [float(p) for p in pn[:2]]
        t_etapa = max(0.0, float(snap.get("t_etapa", 0.0) or 0.0))
        self._t_etapa_leido = (t_etapa, t)
        if not self._pos_iniciadas:
            self._iniciar_posiciones(snap.get("pos"))
            self._pos_iniciadas = True
        etapa = snap.get("etapa")
        if etapa is None:
            # Programa sin B3:3 o lectura de etapa perdida: se anima por bobinas y sensores.
            self._cursor = None
            self._etapa_leida = None
            return
        etapa = int(etapa)
        dn_leido = self._dn_leido(etapa)

        if self._cursor is None:
            self._cursor = _indice(etapa, dn_leido)
            self._etapa_leida = etapa
            self._t_entrada = t - t_etapa
            self._m = {}
            for n, c in self._c.items():
                c.alcanzo_ext = self._cursor >= FASES[n][2] or c.pos >= UMBRAL_EXT
        elif etapa < self._etapa_leida:
            # La etapa leída solo retrocede en un ciclo nuevo (X7 → X1) o en X0 (RESET, END → GS).
            if etapa == 0:
                if self._etapa_leida >= 7:
                    self._avanzar(INDICE_FIN_CICLO, t)        # fin de ciclos: lo que faltó, repuesto
                else:
                    for c in self._c.values():
                        c.cola = []                           # RESET: nada que reponer, todo regresa
                self._nuevo_ciclo(t)
                self._cursor = 0
            else:
                self._avanzar(INDICE_FIN_CICLO, t)
                self._nuevo_ciclo(t)
                self._cursor = 0
                self._avanzar(_indice(etapa, dn_leido), t)
            self._etapa_leida = etapa
        else:
            self._etapa_leida = etapa
            self._avanzar(_indice(etapa, dn_leido), t)

        self._evidencia(t)
        if self._cursor // 2 == etapa:
            # El gateway mide t_etapa desde que él vio el cambio: es lo más temprano que se sabe de
            # la entrada en la etapa. Ancla el reloj de la etapa y el TON (ACC = 0 al entrar).
            entrada = t - t_etapa
            if entrada < self._t_entrada:
                self._t_entrada = entrada
            timer = tags.TIMER_DE_ETAPA.get(etapa)
            if timer is not None:
                self._observar_timer(timer, 0, entrada)
        self._observar_timers(t)

    def _dn_leido(self, etapa):
        n = tags.TIMER_DE_ETAPA.get(etapa)
        return n is not None and bool(self._bits.get(tags.tag_timer(n, "DN")))

    def _iniciar_posiciones(self, pos=None):
        """Primera lectura: posición de los sensores (o la del gateway en SIM/EMULATE)."""
        for k, (n, c) in enumerate(self._c.items()):
            _e, _c, tag_sc, tag_se = self._tags[n]
            if self._bits.get(tag_se) and not self._bits.get(tag_sc):
                c.pos = 1.0
            elif self._bits.get(tag_sc) and not self._bits.get(tag_se):
                c.pos = 0.0
            elif pos is not None and len(pos) > k:
                c.pos = min(1.0, max(0.0, float(pos[k])))
            c.cola = []
            c.objetivo = c.pos

    def _nuevo_ciclo(self, t):
        for c in self._c.values():
            c.alcanzo_ext = False
        self._m = {}
        self._t_entrada = t

    def _avanzar(self, nuevo, t):
        """Lleva el cursor hacia delante (nunca atrás) y repone las carreras que se saltaron."""
        if self._cursor is None or nuevo <= self._cursor:
            return
        viejo = self._cursor
        for n, c in self._c.items():
            es, _ec, rs, _rc = FASES[n]
            if viejo < rs <= nuevo and not c.alcanzo_ext and not c.cola:
                # El cursor ya pide el regreso y el vástago nunca llegó afuera en este ciclo:
                # la salida ocurrió entre dos lecturas. Se repone corta antes de regresar.
                c.cola.append((1.0, min(self._dur_s(n, "ext"), REPOSICION_MS / 1000.0)))
                self.repuestas += 1
        if nuevo // 2 != viejo // 2:
            self._t_entrada = t
            n_timer = tags.TIMER_DE_ETAPA.get(nuevo // 2)
            if n_timer is not None:
                self._m[n_timer] = -100.0 * t       # el TON arranca en 0 al entrar (lo más pronto que se sabe)
        self._cursor = nuevo

    def _evidencia(self, t):
        """Bobinas y temporizadores más frescos que B3:3: avanzan el cursor un paso como mucho."""
        if self._cursor is None or self._cursor < 2 or self._cursor >= INDICE_FIN_CICLO:
            return
        etapa = self._cursor // 2
        limite = _indice(etapa + 1, True)            # evidencia aceptada: hasta la etapa siguiente
        b = self._bits
        mejor = self._cursor
        for n in self.cilindros:
            es, _ec, rs, _rc = FASES[n]
            tag_e, tag_c, _sc, _se = self._tags[n]
            if b.get(tag_e) and not b.get(tag_c) and es <= limite:
                mejor = max(mejor, es)
            if b.get(tag_c) and not b.get(tag_e) and self._cursor >= es and rs <= limite:
                mejor = max(mejor, rs)
        for timer, e in _ETAPA_DE_TIMER.items():
            if e not in (etapa, etapa + 1):
                continue
            if self._bits.get(tags.tag_timer(timer, "DN")):
                mejor = max(mejor, _indice(e, True))
            elif self._ints.get(tags.tag_timer(timer, "ACC"), 0) > 0:
                mejor = max(mejor, _indice(e, False))
        self._avanzar(mejor, t)

    def _observar_timers(self, t):
        if self._cursor is None:
            return
        timer = tags.TIMER_DE_ETAPA.get(self._cursor // 2)
        if timer is None:
            return
        acc = self._ints.get(tags.tag_timer(timer, "ACC"))
        if acc is not None and acc > 0:
            self._observar_timer(timer, acc, t)

    # ------------------------------------------------------------------ salida
    def _objetivo(self, n):
        """(objetivo 0/1 o None = quieto, confirmado) del cilindro n según cursor o bobinas."""
        tag_e, tag_c, tag_sc, tag_se = self._tags[n]
        b = self._bits
        sc = b.get(tag_sc, False) and not b.get(tag_se, False)
        se = b.get(tag_se, False) and not b.get(tag_sc, False)
        if self._cursor is not None:
            es, ec, rs, rc = FASES[n]
            i = self._cursor
            if i < es:
                return 0.0, sc
            if i < rs:
                return 1.0, i >= ec or se
            return 0.0, i >= rc or sc
        ev_e, ev_c = b.get(tag_e, False), b.get(tag_c, False)
        if ev_e and not ev_c:
            return 1.0, se
        if ev_c and not ev_e:
            return 0.0, sc
        if se:
            return 1.0, True
        if sc:
            return 0.0, True
        return None, False

    def muestrear(self, t, dt_max=DT_MAX_S):
        """Avanza la animación hasta `t` y devuelve el estado previsto (ver el docstring del módulo).

        `dt_max`: lo más que avanza de una vez (el HMI muestrea cada 15 ms; el puente, al enviar,
        cada 50–1000 ms y pasa 1 s)."""
        t = float(t)
        dt = 0.0 if self._t_muestra is None else min(float(dt_max), max(0.0, t - self._t_muestra))
        self._t_muestra = t
        activo = self._conectado

        if activo and self._cursor is not None and self._cursor % 2 == 0:
            etapa = self._cursor // 2
            timer = tags.TIMER_DE_ETAPA.get(etapa)
            pre = self._pre(timer) if timer is not None else None
            if pre is not None and self._acc_est(timer, t) >= pre:
                self._avanzar(self._cursor + 1, t)      # DN previsto: el PLC lo da por tiempo

        for n, c in self._c.items():
            if activo:
                self._mover(n, c, t, dt)
            else:
                c.vel = 0.0

        self._mover_neum(t, dt)
        return self._salida(t)

    def _mover(self, n, c, t, dt):
        objetivo, confirmado = self._objetivo(n)
        _e, _c, tag_sc, tag_se = self._tags[n]
        sc = self._bits.get(tag_sc, False) and not self._bits.get(tag_se, False)
        se = self._bits.get(tag_se, False) and not self._bits.get(tag_sc, False)

        # Discrepancia: el sensor del extremo contrario no se apaga (cilindro sin aire o atascado).
        contra = objetivo is not None and ((objetivo >= 0.5 and sc) or (objetivo < 0.5 and se))
        if contra and not c.cola:
            if c.t_contra is None:
                c.t_contra = t
            limite = CONTRADICCION_S + self._dur_s(n, "ext" if objetivo >= 0.5 else "ret")
            if t - c.t_contra > limite:
                c.discrepancia = True
        else:
            c.t_contra = None
            c.discrepancia = False
        if c.discrepancia:
            objetivo, confirmado = (1.0 if se else 0.0), True

        if c.cola:
            meta, dur = c.cola[0]
            vel = 1.0 / dur
            confirmado_mov = False
        elif objetivo is None:
            meta, vel, confirmado_mov = c.pos, 0.0, False
        else:
            meta = objetivo
            vel = 1.0 / self._dur_s(n, "ext" if meta > c.pos else "ret")
            confirmado_mov = confirmado
        distancia = meta - c.pos
        if confirmado_mov and abs(distancia) > 1e-6:
            vel = max(vel, abs(distancia) / ALCANCE_S)
        paso = vel * dt
        if abs(distancia) <= paso:
            c.pos = meta
            if c.cola:
                c.cola.pop(0)
        else:
            c.pos += paso if distancia > 0 else -paso
        if c.pos >= UMBRAL_EXT:
            c.alcanzo_ext = True
        c.objetivo = meta
        c.vel = (vel if distancia > 0 else -vel) if abs(distancia) > 1e-6 else 0.0
        c.confirmado = bool(confirmado and not c.cola)

    def _t_x7(self, t):
        return max(t - self._t_entrada, self._acc_est(tags.TIMER_NEUMATICO, t) / 100.0)

    def _mover_neum(self, t, dt):
        if self.cadena is not None and self._conectado and self._cursor is not None:
            en_x7 = self._cursor // 2 == 7
            meta = self.cadena.posiciones(self._t_x7(t) if en_x7 else 0.0, en_x7)
        else:
            meta = self._neum_leido
        paso = VEL_NEUM * dt
        for i in range(2):
            d = float(meta[i]) - self._neum[i]
            self._neum[i] = float(meta[i]) if abs(d) <= paso else self._neum[i] + (paso if d > 0 else -paso)

    def _salida(self, t):
        etapa = None if self._cursor is None else self._cursor // 2
        acc = {}
        t_etapa = self._t_etapa_leido[0] + max(0.0, t - self._t_etapa_leido[1])
        if etapa is not None:
            timer = tags.TIMER_DE_ETAPA.get(etapa)
            for n in range(tags.N_TIMERS):
                acc[n] = 0
            if timer is not None:
                pre = self._pre(timer)
                est = self._acc_est(timer, t)
                if self._cursor % 2 == 1 and pre is not None:
                    est = float(pre)
                acc[timer] = int(est)
                t_etapa = max(t - self._t_entrada, est / 100.0)
            else:
                t_etapa = t - self._t_entrada
        cs = [self._c[n] for n in self.cilindros]
        return {
            "pos": [round(c.pos, 4) for c in cs],
            "pos_neum": [round(p, 4) for p in self._neum],
            "etapa": etapa,
            "t_etapa": round(t_etapa, 2),
            "acc": acc,
            "indice": self._cursor,
            "objetivo": [round(c.objetivo, 4) for c in cs],
            "velocidad": [round(c.vel, 4) for c in cs],
            "confirmado": [c.confirmado for c in cs],
            "discrepancia": [c.discrepancia for c in cs],
            "repuestas": self.repuestas,
            "sin_etapa": self._conectado and self._cursor is None,
        }
