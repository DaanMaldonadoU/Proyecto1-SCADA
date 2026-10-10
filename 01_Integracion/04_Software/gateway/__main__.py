# -*- coding: utf-8 -*-
"""
gateway/__main__.py — Línea de órdenes del gateway (mds/ARQUITECTURA.md 4.6).

    python -m gateway --modo SIM
    python -m gateway --modo EMULATE --servidor "RSLinx Local OPC Server" --topic PROYECTO1_TEST --periodo 100
    python -m gateway --modo REAL    --servidor "RSLinx Local OPC Server" --topic PROYECTO1_TEST --periodo 100 --fuente cache
    python -m gateway --modo SIM --ciclos-demo 2 --periodo 20
    python -m gateway --modo SIM --simular-enlace     # imita el enlace lento ENI ↔ SLC del laboratorio

Con `--ciclos-demo N` (solo SIM) el gateway escribe N_CICLOS = N, pulsa STARTV él mismo,
corre hasta END (o N ciclos de máquina), imprime un resumen y sale con código 0.
Sin `--ciclos-demo` corre hasta Ctrl+C.

Modos: SIM, EMULATE y REAL. Compatibilidad: Python 3.12 a 3.13 (EMULATE/REAL: Windows,
Python de 32 bits, pywin32 y OpenOPC-Python3x). Dependencias: pyzmq, msgpack, loguru.
"""
from __future__ import annotations

import argparse
import os
import sys
import time

import zmq
from loguru import logger

# Permite `python gateway/__main__.py` además de `python -m gateway`.
_RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _RAIZ not in sys.path:
    sys.path.insert(0, _RAIZ)

from core import protocolo, tags  # noqa: E402
from core.latencia import percentil  # noqa: E402


def _argumentos(argv=None):
    p = argparse.ArgumentParser(prog="python -m gateway",
                                description="Gateway de la estación electroneumática (SLC 5/04 ⇄ HMI)")
    p.add_argument("--modo", choices=protocolo.MODOS, default="SIM")
    p.add_argument("--servidor", default="RSLinx Local OPC Server", help="servidor OPC DA (EMULATE/REAL)")
    p.add_argument("--topic", default="PROYECTO1_TEST", help="topic de RSLinx (EMULATE/REAL)")
    p.add_argument("--periodo", type=float, default=None,
                   help="periodo del ciclo en ms (defecto: 50 en SIM, 100 en OPC)")
    p.add_argument("--fuente", choices=protocolo.FUENTES_OPC, default="cache",
                   help="lectura OPC de la caché de RSLinx (defecto, ~6 ms) o del dispositivo (~200 ms en DF1)")
    p.add_argument("--pub", default=protocolo.PUB_DEFECTO, help="endpoint PUB de snapshots")
    p.add_argument("--cmd", default=protocolo.CMD_DEFECTO, help="endpoint REP de órdenes")
    p.add_argument("--datos", default="datos", help="carpeta del historial SQLite")
    p.add_argument("--sin-historial", action="store_true", help="no guardar historial SQLite")
    p.add_argument("--remoto", action="store_true",
                   help="arranca con el mando remoto (web) habilitado; si no, lo habilita el HMI local")
    p.add_argument("--log", default="INFO", help="nivel de loguru (DEBUG, INFO, WARNING…)")
    p.add_argument("--ciclos-demo", type=int, default=None, metavar="N",
                   help="SIM: arranca solo, hace N ciclos de máquina, imprime un resumen y sale")
    p.add_argument("--simular-enlace", action="store_true",
                   help="SIM: imita el enlace lento del laboratorio (cada archivo del PLC se refresca cada "
                        "0,15–2,4 s y sin pos, como en REAL) para probar el modo suave del HMI y del gemelo")
    return p.parse_args(argv)


def _crear_backend(a):
    periodo = a.periodo or (50 if a.modo == "SIM" else 100)
    if a.modo == "SIM":
        from gateway.backend_sim import BackendSim
        return BackendSim(enlace_lento=a.simular_enlace)
    from gateway.backend_opc import BackendOPC
    return BackendOPC(a.modo, servidor=a.servidor, topic=a.topic, fuente=a.fuente,
                      periodo_ms=periodo, log=lambda m: logger.info(m))


class _Demo:
    """Criterio de parada y estadísticas de `--ciclos-demo`."""

    def __init__(self, servidor, n, limite_s):
        self.srv = servidor
        self.n = n
        self.limite_s = limite_s
        self.iniciado = False
        self.t0 = None
        self.etapa = None
        self.t_etapa0 = None
        self.tiempos = {}           # etapa -> [s, ...]
        self.ciclos = 0
        self.fin = False
        self.ok = False
        self.conflictos = 0

    def __call__(self, snap):
        ahora = time.perf_counter()
        if not snap["conectado"]:
            return False
        if not self.iniciado:
            for cmd in (protocolo.cmd_escribir("N_CICLOS", self.n), protocolo.cmd_pulso("STARTV")):
                r = self.srv.procesar_orden(cmd)
                logger.info("Demo: orden {} -> ok={} {}", cmd, r["ok"], r["msg"])
            self.iniciado = True
            self.t0 = ahora
            return False
        bits = snap["bits"]
        for e, c, _sc, _se in tags.CILINDROS.values():
            if bits.get(e) and bits.get(c):
                self.conflictos += 1
        etapa = snap["etapa"]
        if self.srv.fines > 0:
            if self.etapa is not None and self.t_etapa0 is not None:
                self.tiempos.setdefault(self.etapa, []).append(ahora - self.t_etapa0)
            self.fin, self.ok = True, True
            self.ciclos = max(self.ciclos, self.n)
            return True
        if etapa != self.etapa:
            if self.etapa is not None and self.t_etapa0 is not None:
                self.tiempos.setdefault(self.etapa, []).append(ahora - self.t_etapa0)
            self.etapa, self.t_etapa0 = etapa, ahora
        self.ciclos = max(self.ciclos, snap["ints"].get("C_ACC", 0))
        if ahora - self.t0 > self.limite_s:
            logger.error("Demo: se superó el tiempo límite de {:.0f} s", self.limite_s)
            return True
        return False

    def resumen(self):
        lat = self.srv.lat.resumen(self.srv.backend.fuente)
        periodos = self.srv.lat.periodos()
        lineas = [
            "",
            "================ Resumen de la demo SIM ================",
            "Ciclos de máquina completados : %d de %d (END=%s)" % (self.ciclos, self.n, "sí" if self.fin else "no"),
            "Duración total                : %.2f s" % ((time.perf_counter() - self.t0) if self.t0 else 0.0),
            "Ciclos del gateway            : %d (seq %d)" % (self.srv.ciclos, self.srv.seq),
            "EV_E y EV_C simultáneas       : %d muestras" % self.conflictos,
            "Tiempo medio por etapa:",
        ]
        for e in sorted(self.tiempos):
            ts = self.tiempos[e]
            accion = tags.ETAPAS[e][1]
            lineas.append("  X%d  %5.2f s  (x%d)  %s" % (e, sum(ts) / len(ts), len(ts), accion))
        lineas += [
            "Latencia: lectura %.3f ms · máx %.3f ms · p95 %.3f ms · ciclo %.3f ms"
            % (lat["lectura_ms"], lat["lectura_max_ms"], lat["p95_ms"], lat["ciclo_ms"]),
            "Periodo: objetivo %.0f ms · medio %.2f ms · p95 %.2f ms · máx %.2f ms"
            % (self.srv.periodo_ms, (sum(periodos) / len(periodos)) if periodos else 0.0,
               percentil(periodos, 95), max(periodos) if periodos else 0.0),
            "=========================================================",
        ]
        return "\n".join(lineas)


def main(argv=None):
    a = _argumentos(argv)
    # La consola de Windows suele estar en cp1252: nunca fallar por un carácter.
    for flujo in (sys.stdout, sys.stderr):
        try:
            if flujo.isatty():
                flujo.reconfigure(errors="replace")
            else:
                flujo.reconfigure(encoding="utf-8", errors="replace")   # tuberías, Git Bash
        except Exception:
            pass
    logger.remove()
    logger.add(sys.stderr, level=a.log.upper(),
               format="<green>{time:HH:mm:ss.SSS}</green> <level>{level: <7}</level> {message}")

    if a.ciclos_demo is not None and a.modo != "SIM":
        logger.error("--ciclos-demo solo está disponible en modo SIM")
        return 2
    if a.simular_enlace and a.modo != "SIM":
        logger.error("--simular-enlace solo está disponible en modo SIM")
        return 2
    if a.simular_enlace:
        logger.info("Enlace simulado: cada archivo del PLC se refresca cada 0,15–2,4 s; sin pos (como en REAL)")

    from gateway.servidor import Servidor

    historial = None
    if not a.sin_historial:
        from core.historial import Historial
        historial = Historial(os.path.join(a.datos, "historial.sqlite"))

    backend = _crear_backend(a)
    srv = Servidor(backend, pub=a.pub, cmd=a.cmd, periodo_ms=a.periodo, historial=historial,
                   remoto_habilitado=a.remoto)
    try:
        srv.abrir()
    except zmq.ZMQError as e:
        if a.ciclos_demo is None:
            logger.error("No se pudieron abrir los sockets ({}): ¿otro gateway en marcha?", e)
            srv.cerrar()
            return 1
        # En la demo no importa el puerto: se usan puertos efímeros.
        logger.warning("Puertos ocupados ({}); la demo usa puertos efímeros", e)
        srv.cerrar()
        backend = _crear_backend(a)
        srv = Servidor(backend, pub="tcp://127.0.0.1:*", cmd="tcp://127.0.0.1:*",
                       periodo_ms=a.periodo, historial=None)
        srv.abrir()

    if a.ciclos_demo is None:
        logger.info("Gateway en marcha; Ctrl+C para salir")
        srv.bucle()
        return 0

    n = max(1, int(a.ciclos_demo))
    # Con los presets por defecto un ciclo dura ≈ 12 s; margen generoso.
    demo = _Demo(srv, n, limite_s=30.0 * n + 30.0)
    srv.bucle(parar=demo)
    print(demo.resumen())
    return 0 if demo.ok and demo.conflictos == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
