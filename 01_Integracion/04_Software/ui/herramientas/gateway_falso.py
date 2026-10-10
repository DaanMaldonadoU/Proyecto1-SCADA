# -*- coding: utf-8 -*-
"""
ui/herramientas/gateway_falso.py — Publicador sintético para diseñar el HMI sin el gateway real.

Qué hace:
    Sigue `core/protocolo.py` al pie de la letra: PUB de snapshots [TOPIC_SNAP, msgpack] cada
    `--periodo` ms y eventos [TOPIC_EVT, msgpack]; REP que contesta cada orden con
    `protocolo.respuesta(...)` y refleja `escrituras.ultima`.
    Por dentro lleva un ladder simplificado de la tabla del 18-sep (docs/TABLA_DE_VARIABLES.md sección 4):
    X0→X8 con los TON T4:0…T4:5, contador C5:0, bobinas EV_E/EV_C, física de 1A/2A/3A
    (0,8 / 0,9 / 0,7 s), cadena 4A/5A durante X7, latencia inventada y alguna alarma periódica.
    NO sustituye a `gateway/` (que es el que vale para pruebas de verdad): es una herramienta
    de diseño y demostración.

Uso:
    .venv\\Scripts\\python.exe ui\\herramientas\\gateway_falso.py [--modo SIM|EMULATE|REAL]
        [--pub tcp://127.0.0.1:5555] [--cmd tcp://127.0.0.1:5556] [--periodo 50]
        [--sin-demo] [--alarma-fija] [--duracion S]

    Con demo (defecto) arranca solo y, al terminar los N ciclos, vuelve a arrancar a los 4 s.

Requiere: Python 3.12+ con pyzmq y msgpack.
"""
import argparse
import math
import os
import random
import sys
import time
from collections import deque

RAIZ = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if RAIZ not in sys.path:
    sys.path.insert(0, RAIZ)

import zmq  # noqa: E402

from core import protocolo, tags  # noqa: E402

CARRERAS_S = {1: 0.8, 2: 0.9, 3: 0.7}
T4_EXT, T5_INI, T5_EXT, T_RET, RET_S = 0.6, 1.2, 0.6, 2.8, 0.7


class LadderFalso:
    """Ladder mínimo + física, suficiente para que el HMI tenga algo realista que mostrar."""

    def __init__(self, modo):
        self.modo = modo
        self.pre = [tags.PRESETS_DEFECTO["T_ESPERA"]] * 5 + [tags.PRESETS_DEFECTO["T_NEUM"]]
        self.c_pre = tags.PRESETS_DEFECTO["N_CICLOS"]
        self.acum = [0.0] * tags.N_TIMERS
        self.c_acc = 0
        self.etapa = 0
        self.t_etapa = 0.0
        self.active = False
        self.end = False
        self.fines = 0                        # veces que terminaron los N ciclos (END dura un barrido)
        self.pulsos = {}                     # tag -> instante en que vuelve a 0
        self.hmi = {t: False for t in tags.PULSOS}
        self.stop_1 = True
        self.start_1 = False
        self.fisica_auto = True
        self.sensores_man = {s: False for s in tags.SENSORES}
        self.pos = [0.0, 0.0, 0.0]
        self.ev = {t: False for t in tags.BITS_O2}
        self.eventos = []

    # ------------------------------------------------------------------ helpers
    def dn(self, n):
        return self.acum[n] >= self.pre[n] * tags.BASE_TIEMPO_S

    def sensores(self):
        if not self.fisica_auto:
            return dict(self.sensores_man)
        s = {}
        for n, (_e, _c, sc, se) in tags.CILINDROS.items():
            s[sc] = self.pos[n - 1] <= 0.02
            s[se] = self.pos[n - 1] >= 0.98
        return s

    def ir_a(self, etapa):
        if etapa != self.etapa:
            if etapa == 7:
                self.c_acc += 1
            self.etapa = etapa
            self.t_etapa = 0.0

    # ------------------------------------------------------------------ paso
    def paso(self, dt, ahora):
        for tag, t_fin in list(self.pulsos.items()):
            if ahora >= t_fin:
                self.hmi[tag] = False
                del self.pulsos[tag]
        s = self.sensores()
        start = self.start_1 or self.hmi["STARTV"]
        # GS
        if self.hmi["RESETV"] or self.end or (self.start_1 and not self.stop_1):
            if self.etapa != 0 or self.c_acc:
                self.eventos.append(protocolo.evento("GS: fuerza X0 y reinicia el contador", "info", "ladder"))
            self.ir_a(0)
            self.c_acc = 0
            self.end = False
        # GM
        antes = self.active
        self.active = (start or self.active) and self.stop_1 and not self.hmi["STOPV"]
        if self.active != antes:
            self.eventos.append(protocolo.evento("Marcha (ACTIVE = 1)" if self.active else "Paro (ACTIVE = 0)"))
        # TON
        for n in range(tags.N_TIMERS):
            if self.etapa == n + 2:
                self.acum[n] = min(self.acum[n] + dt, self.pre[n] * tags.BASE_TIEMPO_S)
            else:
                self.acum[n] = 0.0
        self.t_etapa += dt
        x = self.etapa
        # transiciones
        if self.active:
            if x == 0 and s["SC1"] and s["SC2"] and s["SC3"] and start:
                self.ir_a(1)
            elif x == 1 and s["SE1"]:
                self.ir_a(2)
            elif x == 2 and self.dn(0) and s["SC1"]:
                self.ir_a(3)
            elif x == 3 and self.dn(1) and s["SE2"]:
                self.ir_a(4)
            elif x == 4 and self.dn(2) and s["SC2"]:
                self.ir_a(5)
            elif x == 5 and self.dn(3) and s["SE3"]:
                self.ir_a(6)
            elif x == 6 and self.dn(4) and s["SC3"]:
                self.ir_a(7)
            elif x == 7 and self.dn(5):
                if self.c_acc >= self.c_pre:
                    self.ir_a(8)
                elif s["SC3"]:
                    self.ir_a(1)
        if self.etapa == 8 and self.t_etapa > 0.3:
            self.end = True
            self.fines += 1
            self.eventos.append(protocolo.evento("Fin de %d ciclos (END)" % self.c_pre))
        x = self.etapa
        # salidas (misma estructura que el ladder del 18-sep)
        d = self.dn
        self.ev["EV_E1"] = x == 1 or (x == 2 and not d(0))
        self.ev["EV_C1"] = (x == 2 and d(0)) or (x == 3 and not d(1)) or (x == 0 and s["SE1"])
        self.ev["EV_E2"] = (x == 3 and d(1)) or (x == 4 and not d(2))
        self.ev["EV_C2"] = (x == 4 and d(2)) or (x == 5 and not d(3)) or (x == 0 and s["SE2"])
        self.ev["EV_E3"] = (x == 5 and d(3)) or (x == 6 and not d(4))
        self.ev["EV_C3"] = (x == 6 and d(4)) or (x == 7 and not d(5) and s["SE3"]) or (x == 0 and s["SE3"])
        # física 1A/2A/3A
        for n, (e, c, _sc, _se) in tags.CILINDROS.items():
            v = dt / CARRERAS_S[n]
            if self.ev[e] and not self.ev[c]:
                self.pos[n - 1] = min(1.0, self.pos[n - 1] + v)
            elif self.ev[c] and not self.ev[e]:
                self.pos[n - 1] = max(0.0, self.pos[n - 1] - v)

    def pos_neum(self):
        if self.etapa != 7:
            return [0.0, 0.0]
        t = self.t_etapa

        def perfil(t_ini, t_ext):
            if t < t_ini:
                return 0.0
            if t < T_RET:
                return min(1.0, (t - t_ini) / t_ext)
            return max(0.0, 1.0 - (t - T_RET) / RET_S)
        return [round(perfil(0.0, T4_EXT), 4), round(perfil(T5_INI, T5_EXT), 4)]

    def bits(self):
        b = {}
        b.update({"STOP_1": self.stop_1, "START_1": self.start_1})
        b.update(self.sensores())
        b.update(self.ev)
        b.update({"STARTV": self.hmi["STARTV"], "STOPV": self.hmi["STOPV"], "ACTIVE": self.active,
                  "END": self.end, "RESETV": self.hmi["RESETV"]})
        for i in range(9):
            b["X%d" % i] = self.etapa == i
        for n in range(tags.N_TIMERS):
            b[tags.tag_timer(n, "DN")] = self.dn(n)
        return b

    def ints(self):
        i = {}
        for n in range(tags.N_TIMERS):
            i[tags.tag_timer(n, "ACC")] = min(int(self.acum[n] / tags.BASE_TIEMPO_S + 1e-6), self.pre[n])
            i[tags.tag_timer(n, "PRE")] = self.pre[n]
        i["C_ACC"] = self.c_acc
        i["C_PRE"] = self.c_pre
        return i


class GatewayFalso:
    def __init__(self, args):
        self.args = args
        self.modo = args.modo
        self.ladder = LadderFalso(args.modo)
        self.fuente = "sim" if args.modo == "SIM" else "dispositivo"
        self.ctx = zmq.Context.instance()
        self.pub = self.ctx.socket(zmq.PUB)
        self.pub.setsockopt(zmq.LINGER, 0)
        self.pub.bind(args.pub)
        self.rep = self.ctx.socket(zmq.REP)
        self.rep.setsockopt(zmq.LINGER, 0)
        self.rep.bind(args.cmd)
        self.seq = 0
        self.lecturas = deque(maxlen=200)
        self.ultima_escritura = None
        self.alarmas = {}
        self.rng = random.Random(7)
        self.t_ini = time.perf_counter()
        self.t_fin_demo = None

    # ------------------------------------------------------------------ órdenes
    def atender(self, cmd, ahora):
        ok, motivo = protocolo.validar_comando(cmd)
        if not ok:
            return protocolo.respuesta(False, motivo)
        op = cmd["op"]
        L = self.ladder
        if op == "ping":
            return protocolo.respuesta(True, "pong")
        if op == "estado":
            return protocolo.respuesta(True, "", snapshot=self.snapshot(ahora))
        if op == "fuente":
            if self.modo == "SIM":
                return protocolo.respuesta(False, "la fuente OPC no aplica en SIM")
            self.fuente = cmd["fuente"]
            self.evento("Fuente de lectura: %s" % self.fuente)
            return protocolo.respuesta(True, "fuente = %s" % self.fuente)
        if op == "fisica":
            if self.modo == "REAL":
                return protocolo.respuesta(False, "sin física simulada en REAL")
            if not cmd["auto"] and L.fisica_auto:
                L.sensores_man = L.sensores()     # congela los sensores tal como están
            L.fisica_auto = bool(cmd["auto"])
            self.evento("Física %s" % ("automática" if L.fisica_auto else "manual"))
            return protocolo.respuesta(True)
        tag = cmd.get("tag", "")
        valor = cmd.get("valor")
        ok, motivo = tags.validar_escritura(tag, self.modo, valor if op == "escribir" else None)
        if not ok:
            self.registrar_escritura(tag, False, motivo)
            self.evento("Escritura %s rechazada: %s" % (tag, motivo), "aviso")
            return protocolo.respuesta(False, motivo)
        if op == "pulso":
            if tag not in tags.PULSOS:
                return protocolo.respuesta(False, "no es un mando")
            L.hmi[tag] = True
            L.pulsos[tag] = ahora + int(cmd.get("ms", tags.PULSO_MS)) / 1000.0
            self.registrar_escritura(tag, True, "pulso %d ms" % int(cmd.get("ms", tags.PULSO_MS)))
            return protocolo.respuesta(True, "pulso %s" % tag)
        if op == "escribir":
            v = int(valor)
            if tag == "T_ESPERA":
                for n in range(5):
                    L.pre[n] = v
            elif tag == "T_NEUM":
                L.pre[tags.TIMER_NEUMATICO] = v
            elif tag == "N_CICLOS":
                L.c_pre = v
            self.registrar_escritura(tag, True, "%s = %d" % (tag, v), v)
            self.evento("%s ← %d (%s)" % (tag, v, ", ".join(tags.PARAMETROS[tag])))
            return protocolo.respuesta(True, "%s = %d" % (tag, v))
        if op == "entrada":
            v = bool(valor)
            if tag == "STOP_1":
                L.stop_1 = v
            elif tag == "START_1":
                L.start_1 = v
            elif tag in L.sensores_man:
                if L.fisica_auto:
                    return protocolo.respuesta(False, "física automática: pasa a manual para forzar sensores")
                L.sensores_man[tag] = v
            self.registrar_escritura(tag, True, "%s = %d" % (tag, v))
            return protocolo.respuesta(True, "%s = %d" % (tag, v))
        return protocolo.respuesta(False, "orden no atendida")

    def registrar_escritura(self, tag, ok, msg, valor=None):
        self.ultima_escritura = {"tag": tag, "valor": valor, "ok": bool(ok), "msg": msg, "t": time.time()}

    def evento(self, msg, nivel="info", origen="gateway"):
        self.ladder.eventos.append(protocolo.evento(msg, nivel, origen))

    # ------------------------------------------------------------------ alarmas y latencia
    def lectura_ms(self):
        base = 9.0 if self.modo == "SIM" else (24.0 if self.fuente == "dispositivo" else 6.0)
        v = self.rng.lognormvariate(math.log(base), 0.25)
        if self.rng.random() < 0.03:
            v += self.rng.uniform(25, 70)
        return v

    def alarma(self, ident, activa, nivel, msg):
        a = self.alarmas.get(ident)
        if activa and (a is None or not a["activa"]):
            self.alarmas[ident] = {"id": ident, "nivel": nivel, "msg": msg, "t_ini": time.time(), "activa": True}
            self.evento("Alarma activada: %s" % msg, nivel, "alarmas")
        elif not activa and a is not None and a["activa"]:
            del self.alarmas[ident]
            self.evento("Alarma despejada: %s" % msg, "info", "alarmas")

    def evaluar_alarmas(self, ahora):
        L = self.ladder
        self.alarma("stop_fisico", not L.stop_1, "aviso", "STOP_1 físico pulsado")
        t = ahora - self.t_ini
        # alarma periódica de demostración: calidad degradada unos segundos cada 40 s
        self.alarma("calidad", 25.0 < (t % 40.0) < 31.0, "aviso", "2 items sin calidad Good")
        self.alarma("etapa_excedida", self.args.alarma_fija, "alarma",
                    "Tiempo de etapa excedido (demostración)")

    # ------------------------------------------------------------------ snapshot
    def snapshot(self, ahora):
        L = self.ladder
        bits = L.bits()
        ints = L.ints()
        palabras = {}
        for nombre, tabla in tags.PALABRAS.items():
            palabras[nombre] = tags.codificar_palabra(nombre, {t: bits.get(t, False) for t in tabla})
        lect = self.lecturas
        ordenadas = sorted(x[0] for x in lect) if lect else [0.0]
        p95 = ordenadas[min(len(ordenadas) - 1, int(0.95 * len(ordenadas)))]
        ult = lect[-1] if lect else (0.0, 0.0, 0.0)
        degradada = "calidad" in self.alarmas
        total = len(tags.ITEMS_RAPIDOS)
        return {
            "v": protocolo.VERSION, "seq": self.seq, "t": time.time(), "modo": self.modo,
            "conectado": True, "fuente": self.fuente,
            "calidad": {"good": total - (2 if degradada else 0), "total": total},
            "bits": bits, "ints": ints, "palabras": palabras,
            "etapa": L.etapa, "t_etapa": round(L.t_etapa, 3),
            "pos": None if self.modo == "REAL" else [round(p, 4) for p in L.pos],
            "pos_neum": L.pos_neum(),
            "lat": {"lectura_ms": round(ult[0], 2), "lectura_max_ms": round(max(x[0] for x in lect) if lect else 0.0, 2),
                    "ciclo_ms": round(ult[1], 2), "periodo_ms": round(ult[2], 1), "p95_ms": round(p95, 2),
                    "fuente": self.fuente},
            "alarmas": list(self.alarmas.values()),
            "escrituras": {"pendientes": 0, "ultima": self.ultima_escritura},
            "fines": L.fines,
        }

    # ------------------------------------------------------------------ bucle
    def correr(self):
        periodo = self.args.periodo / 1000.0
        poller = zmq.Poller()
        poller.register(self.rep, zmq.POLLIN)
        inicio = time.perf_counter()
        n = 0
        t_prev = inicio
        self.evento("Gateway falso en %s · PUB %s · REP %s" % (self.modo, self.args.pub, self.args.cmd))
        if not self.args.sin_demo:
            self.ladder.hmi["STARTV"] = True
            self.ladder.pulsos["STARTV"] = inicio + 0.3
        while True:
            n += 1
            plazo = inicio + n * periodo
            while True:
                resto = plazo - time.perf_counter()
                if resto <= 0:
                    break
                if dict(poller.poll(max(1, int(resto * 1000)))).get(self.rep):
                    try:
                        cmd = protocolo.desempaquetar(self.rep.recv())
                    except Exception:
                        cmd = None
                    self.rep.send(protocolo.empaquetar(self.atender(cmd, time.perf_counter())))
            ahora = time.perf_counter()
            dt = ahora - t_prev
            t_prev = ahora
            t_lect = self.lectura_ms()
            self.ladder.paso(dt, ahora)
            self.lecturas.append((t_lect, t_lect + 0.8, dt * 1000.0))
            self.evaluar_alarmas(ahora)
            # demo: al acabar los N ciclos, vuelve a arrancar a los 4 s
            if not self.args.sin_demo:
                if self.ladder.etapa == 0 and not self.ladder.active and self.t_fin_demo is None \
                        and ahora - inicio > 1.0:
                    self.t_fin_demo = ahora
                if self.ladder.end:
                    self.t_fin_demo = ahora
                if self.t_fin_demo is not None and ahora - self.t_fin_demo > 4.0 and self.ladder.etapa == 0:
                    self.ladder.hmi["STARTV"] = True
                    self.ladder.pulsos["STARTV"] = ahora + tags.PULSO_MS / 1000.0
                    self.evento("Demo: nuevo arranque automático")
                    self.t_fin_demo = None
            self.seq += 1
            self.pub.send_multipart([protocolo.TOPIC_SNAP, protocolo.empaquetar(self.snapshot(ahora))])
            for ev in self.ladder.eventos:
                self.pub.send_multipart([protocolo.TOPIC_EVT, protocolo.empaquetar(ev)])
            self.ladder.eventos = []
            if self.args.duracion and ahora - inicio > self.args.duracion:
                break
        self.pub.close(0)
        self.rep.close(0)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Gateway sintético para diseñar el HMI (sigue core/protocolo.py).")
    ap.add_argument("--modo", choices=protocolo.MODOS, default="SIM")
    ap.add_argument("--pub", default=protocolo.PUB_DEFECTO)
    ap.add_argument("--cmd", default=protocolo.CMD_DEFECTO)
    ap.add_argument("--periodo", type=float, default=50.0, help="ms entre snapshots")
    ap.add_argument("--sin-demo", action="store_true", help="no arrancar solo ni rearrancar al terminar")
    ap.add_argument("--alarma-fija", action="store_true", help="mantiene una alarma activa (para ver la banda)")
    ap.add_argument("--duracion", type=float, default=0.0, help="segundos hasta salir (0 = sin límite)")
    args = ap.parse_args(argv)
    try:
        GatewayFalso(args).correr()
    except KeyboardInterrupt:
        pass
    except zmq.ZMQError as e:
        print("gateway_falso: no se pudo abrir %s / %s: %s" % (args.pub, args.cmd, e), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
