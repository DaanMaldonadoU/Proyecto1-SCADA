# -*- coding: utf-8 -*-
"""
core/alarmas.py — Reglas de alarma de la estación (mds/ARQUITECTURA.md 4.4).

El gateway llama a `Alarmas.evaluar(snapshot_parcial, t)` una vez por ciclo con el
snapshot ya decodificado (conectado, calidad, bits, ints, etapa, t_etapa, lat). Devuelve
la lista de alarmas activas (para `snapshot["alarmas"]`) y los eventos nuevos (uno al
activarse y otro al limpiarse cada alarma). `ultimos_cambios` guarda, tras cada
evaluación, las transiciones [(alarma, activa)] para que el historial las registre.

Reglas:
    desconexion     alarma  conectado == False                        se limpia al volver la lectura
    calidad         aviso   algún item sin Good                       todos Good
    stop_fisico     aviso   STOP_1 == 0                               STOP_1 == 1
    etapa_excedida  alarma  etapa con TON: t_etapa > 1.5·PRE·0.01 + 1 s
                            X0/X1 (espera de sensor): t_etapa > 5 s    cambia la etapa (o deja de cumplirse)
                            Solo con ACTIVE: en paro la espera es voluntaria.
                            Con lecturas por OPC (fuente cache/dispositivo) o sin `pos` (REAL, enlace
                            simulado) se suman MARGEN_ENLACE_S: el enlace serie ENI ↔ SLC refresca cada
                            archivo hasta ~2,4 s tarde y la etapa se ve cambiar tarde (sesión 14).
    latencia        aviso   lat.p95_ms > 2·periodo durante 10 ciclos  p95 baja

Modos: SIM, EMULATE y REAL. Compatibilidad: Python 3.12 a 3.13, sin dependencias externas.
"""
from __future__ import annotations

from collections import OrderedDict

from core import protocolo, tags

NIVEL = OrderedDict([
    ("desconexion", "alarma"),
    ("calidad", "aviso"),
    ("stop_fisico", "aviso"),
    ("etapa_excedida", "alarma"),
    ("latencia", "aviso"),
])

ESPERA_SENSOR_S = 5.0        # X0 / X1: tiempo máximo esperando un sensor con ACTIVE
MARGEN_TON = 1.5             # etapa con TON: factor sobre el preajuste
HOLGURA_TON_S = 1.0          # ... más esta holgura
MARGEN_ENLACE_S = 3.0        # lecturas del PLC por el enlace serie: la etapa se ve cambiar hasta ~2,4 s tarde
CICLOS_LATENCIA = 10         # ciclos seguidos con p95 alto antes de avisar
FACTOR_LATENCIA = 2.0        # p95 > FACTOR·periodo


class Alarmas:
    """Evalúa las reglas y recuerda qué alarmas están activas y desde cuándo."""

    def __init__(self, periodo_ms=50.0):
        self.periodo_ms = float(periodo_ms)
        self._activas = OrderedDict()      # id -> dict de alarma
        self._ciclos_latencia = 0
        self.ultimos_cambios = []          # [(alarma_dict, activa_bool)] de la última evaluación

    # ------------------------------------------------------------------
    def activas(self):
        return [dict(a) for a in self._activas.values()]

    def reiniciar(self):
        self._activas.clear()
        self._ciclos_latencia = 0
        self.ultimos_cambios = []

    # ------------------------------------------------------------------
    def evaluar(self, snap, t):
        """(lista_alarmas_activas, eventos_nuevos). `snap` puede ser parcial."""
        self.ultimos_cambios = []
        eventos = []
        for ident, (activa, msg) in self._condiciones(snap).items():
            if activa is None:
                continue   # regla no evaluable ahora (p. ej. desconectado): conserva su estado
            if activa and ident not in self._activas:
                al = {"id": ident, "nivel": NIVEL[ident], "msg": msg, "t_ini": float(t), "activa": True}
                self._activas[ident] = al
                self.ultimos_cambios.append((dict(al), True))
                eventos.append(protocolo.evento(msg, NIVEL[ident], "alarmas", t))
            elif activa:
                self._activas[ident]["msg"] = msg      # el texto trae el valor actual
            elif ident in self._activas:
                al = self._activas.pop(ident)
                al["activa"] = False
                al["t_fin"] = float(t)
                self.ultimos_cambios.append((dict(al), False))
                eventos.append(protocolo.evento("Normalizada: %s" % al["msg"], "info", "alarmas", t))
        return self.activas(), eventos

    # ------------------------------------------------------------------
    def _condiciones(self, snap):
        """id -> (activa: bool | None, msg). None = no evaluar en este ciclo."""
        c = OrderedDict()
        conectado = bool(snap.get("conectado", False))
        c["desconexion"] = (not conectado, "Sin lectura del PLC / simulador")
        if not conectado:
            # Con los datos congelados no tiene sentido evaluar el resto.
            for ident in ("calidad", "stop_fisico", "etapa_excedida"):
                c[ident] = (None, "")
            c["latencia"] = self._regla_latencia(snap)
            return c

        cal = snap.get("calidad") or {}
        good, total = int(cal.get("good", 0)), int(cal.get("total", 0))
        c["calidad"] = (total > 0 and good < total,
                        "Calidad de lectura: %d de %d items en Good" % (good, total))

        bits = snap.get("bits") or {}
        if "STOP_1" in bits:
            c["stop_fisico"] = (not bits["STOP_1"], "Pulsador de paro físico STOP_1 accionado")
        else:
            c["stop_fisico"] = (None, "")

        c["etapa_excedida"] = self._regla_etapa(snap, bits)
        c["latencia"] = self._regla_latencia(snap)
        return c

    @staticmethod
    def margen_enlace(snap):
        """Segundos extra de los límites de etapa: MARGEN_ENLACE_S si las lecturas vienen del PLC por
        OPC (fuente cache/dispositivo) o sin posición del gateway (REAL, enlace simulado); 0 en SIM."""
        if snap.get("fuente") in protocolo.FUENTES_OPC or ("pos" in snap and snap["pos"] is None):
            return MARGEN_ENLACE_S
        return 0.0

    def _regla_etapa(self, snap, bits):
        etapa = snap.get("etapa")
        t_etapa = float(snap.get("t_etapa") or 0.0)
        if etapa is None or not bits.get("ACTIVE", False):
            return (False, "")
        margen = self.margen_enlace(snap)
        ints = snap.get("ints") or {}
        n = tags.TIMER_DE_ETAPA.get(etapa)
        if n is not None:
            pre = ints.get(tags.tag_timer(n, "PRE"))
            if pre is None:
                return (False, "")
            limite = MARGEN_TON * pre * tags.BASE_TIEMPO_S + HOLGURA_TON_S + margen
            return (t_etapa > limite,
                    "Etapa X%d excedida: %.1f s (límite %.1f s con T4:%d)" % (etapa, t_etapa, limite, n))
        espera = ESPERA_SENSOR_S + margen
        if etapa == 1:
            return (t_etapa > espera, "Etapa X1 excedida: %.1f s esperando SE1" % t_etapa)
        if etapa == 0:
            # En X0 con ACTIVE solo es anomalía si se espera a que retraigan los cilindros;
            # tras END, ACTIVE sigue enclavado y X0 espera START legítimamente.
            esperando = not all(bits.get(s, False) for s in ("SC1", "SC2", "SC3"))
            return (esperando and t_etapa > espera,
                    "Etapa X0 excedida: %.1f s esperando SC1·SC2·SC3" % t_etapa)
        return (False, "")

    def _regla_latencia(self, snap):
        lat = snap.get("lat") or {}
        p95 = float(lat.get("p95_ms", 0.0) or 0.0)
        umbral = FACTOR_LATENCIA * self.periodo_ms
        if p95 > umbral:
            self._ciclos_latencia += 1
        else:
            self._ciclos_latencia = 0
        activa = self._ciclos_latencia >= CICLOS_LATENCIA or ("latencia" in self._activas and p95 > umbral)
        return (activa, "Latencia alta: p95 %.0f ms > %.0f ms" % (p95, umbral))
