# -*- coding: utf-8 -*-
"""
core/protocolo.py — Contrato gateway ⇄ HMI por ZeroMQ + msgpack.

Compatibilidad: Python 3.12 a 3.13. Dependencia: msgpack.
Se usa en: gateway (publica) y HMI (se suscribe y manda órdenes).

Transporte
----------
* Snapshot: socket PUB del gateway -> SUB del HMI. Mensaje de DOS partes:
  [TOPIC_SNAP, msgpack(snapshot)]. El HMI vacía la cola en cada vuelta y se queda
  con el último (así nunca acumula retraso).
* Eventos: mismo PUB, dos partes [TOPIC_EVT, msgpack(evento)]. El HMI los conserva todos.
* Órdenes: REQ del HMI -> REP del gateway. El HMI usa RCVTIMEO=TIMEOUT_CMD_MS (2 s), REQ_RELAXED=1 y
  REQ_CORRELATE=1 para no quedar bloqueado si se pierde una respuesta.

Snapshot (dict)
---------------
  v          int    versión del protocolo (VERSION)
  seq        int    contador de publicaciones
  t          float  time.time() del gateway al terminar la lectura
  modo       str    "SIM" | "EMULATE" | "REAL"
  conectado  bool   hay lectura válida del PLC / simulador
  fuente     str    "sim" | "dispositivo" | "cache"   (de dónde salen las lecturas OPC)
  calidad    dict   {"good": n, "total": m}  items con calidad Good en la última lectura
  bits       dict   {tag: bool} para los tags de core.tags.TAGS_BIT disponibles
  ints       dict   {tag: int}  para core.tags.TAGS_INT disponibles
  palabras   dict   {"I:1.0": int, "O:2.0": int, "B3:0": int, "B3:3": int}
  etapa      int|None  etapa activa (0..8) o None
  t_etapa    float  segundos que lleva la etapa activa (reloj del gateway)
  pos        list|None  [p1, p2, p3] posición 0..1 de 1A..3A. SIM/EMULATE: física exacta.
                        REAL: None -> el HMI la estima con core.estimador.
  pos_neum   list|None  [p4, p5] posición estimada de 4A/5A durante la ventana T4:5 (modelo de tiempos)
  lat        dict   {"lectura_ms", "lectura_max_ms", "ciclo_ms", "periodo_ms", "p95_ms", "fuente"}
  alarmas    list   [{"id": str, "nivel": str, "msg": str, "t_ini": float, "activa": bool}]
  escrituras dict   {"pendientes": int, "ultima": {"tag", "valor", "ok", "msg", "t"} | None}
  fines      int    veces que terminaron los N ciclos. END (B3:0/3) dura UN solo barrido del PLC y casi
                    nunca se ve en una lectura: el HMI debe fiarse de este contador y del evento
                    "Fin de N ciclos (END)", no del bit.
  mando      dict   (v2) estado del árbitro de core.mando: {"remoto_habilitado", "titular": {"usuario",
                    "rol", "origen"}|None, "desde", "vence_en_s", "enlace_web", "conectados": [...],
                    "ultima_orden": {"t", "quien", "op", "tag", "valor", "ok", "msg"}|None}

Evento (dict): {"t": float, "nivel": "info"|"aviso"|"alarma", "msg": str, "origen": str}

Órdenes (dict) y respuesta {"ok": bool, "msg": str, "t_ms": float, ...}
  {"op": "pulso",   "tag": "STARTV"|"STOPV"|"RESETV", "ms": 300}
  {"op": "escribir","tag": "T_ESPERA"|"T_NEUM"|"N_CICLOS", "valor": int}
  {"op": "entrada", "tag": <core.tags.ENTRADAS_SIMULABLES>, "valor": bool}   solo SIM / EMULATE
  {"op": "fisica",  "auto": bool}          SIM y EMULATE: sensores desde la física (True) o manuales (False)
  {"op": "fuente",  "fuente": "dispositivo"|"cache"}   OPC: de dónde leer
  {"op": "ping"}
  {"op": "estado"}                          -> respuesta con "snapshot": <snapshot completo>
  {"op": "mando", "accion": "pedir"|"liberar"|"remoto", "habilitar": bool}   (v2) core.mando
  {"op": "presencia", "conectados": [{"usuario", "rol", "desde"}]}          (v2) solo el puente web

Identidad (v2): cualquier orden puede llevar "quien": {"usuario", "rol", "origen": "web"}. Sin
"quien" la orden es del HMI local. Solo el puente web (puente/) pone origen "web", después de
verificar la firma del servidor (core.remoto). El gateway decide con core.mando.Arbitro.
"""
import time

import msgpack

VERSION = 2
PUB_DEFECTO = "tcp://127.0.0.1:5555"
CMD_DEFECTO = "tcp://127.0.0.1:5556"
TOPIC_SNAP = b"snap"
TOPIC_EVT = b"evt"

MODOS = ("SIM", "EMULATE", "REAL")
FUENTES_OPC = ("dispositivo", "cache")
NIVELES = ("info", "aviso", "alarma")
OPS = ("pulso", "escribir", "entrada", "fisica", "fuente", "ping", "estado", "mando", "presencia")
ACCIONES_MANDO = ("pedir", "liberar", "remoto")

# Una escritura OPC por DF1 tarda 100-800 ms y la orden puede esperar a que termine la lectura
# en curso: con 500 ms el HMI daba por perdidas órdenes que el PLC sí recibía.
TIMEOUT_CMD_MS = 2000


# ----------------------------------------------------------------------------
# Serialización
# ----------------------------------------------------------------------------
def empaquetar(obj):
    return msgpack.packb(obj, use_bin_type=True)


def desempaquetar(datos):
    return msgpack.unpackb(datos, raw=False)


# ----------------------------------------------------------------------------
# Snapshot y eventos
# ----------------------------------------------------------------------------
def latencia_vacia(fuente="sim"):
    return {"lectura_ms": 0.0, "lectura_max_ms": 0.0, "ciclo_ms": 0.0,
            "periodo_ms": 0.0, "p95_ms": 0.0, "fuente": fuente}


def snapshot_vacio(modo="SIM"):
    return {
        "v": VERSION, "seq": 0, "t": time.time(), "modo": modo,
        "conectado": False, "fuente": "sim" if modo == "SIM" else "dispositivo",
        "calidad": {"good": 0, "total": 0},
        "bits": {}, "ints": {}, "palabras": {},
        "etapa": None, "t_etapa": 0.0,
        "pos": None, "pos_neum": None,
        "lat": latencia_vacia("sim" if modo == "SIM" else "dispositivo"),
        "alarmas": [],
        "escrituras": {"pendientes": 0, "ultima": None},
        "fines": 0,
        "mando": None,
    }


def evento(msg, nivel="info", origen="gateway", t=None):
    if nivel not in NIVELES:
        raise ValueError("nivel inválido: %s" % nivel)
    return {"t": time.time() if t is None else t, "nivel": nivel, "msg": msg, "origen": origen}


# ----------------------------------------------------------------------------
# Órdenes
# ----------------------------------------------------------------------------
def cmd_pulso(tag, ms=300):
    return {"op": "pulso", "tag": tag, "ms": int(ms)}


def cmd_escribir(tag, valor):
    return {"op": "escribir", "tag": tag, "valor": int(valor)}


def cmd_entrada(tag, valor):
    return {"op": "entrada", "tag": tag, "valor": bool(valor)}


def cmd_fisica(auto):
    return {"op": "fisica", "auto": bool(auto)}


def cmd_fuente(fuente):
    return {"op": "fuente", "fuente": fuente}


def cmd_ping():
    return {"op": "ping"}


def cmd_estado():
    return {"op": "estado"}


def cmd_mando(accion, habilitar=None):
    c = {"op": "mando", "accion": accion}
    if habilitar is not None:
        c["habilitar"] = bool(habilitar)
    return c


def cmd_presencia(conectados):
    return {"op": "presencia", "conectados": list(conectados)}


def respuesta(ok, msg="", **extra):
    r = {"ok": bool(ok), "msg": msg, "t_ms": time.time() * 1000.0}
    r.update(extra)
    return r


def validar_comando(cmd):
    """(ok, motivo). Solo forma; las reglas de seguridad por modo las aplica core.tags.validar_escritura."""
    if not isinstance(cmd, dict) or cmd.get("op") not in OPS:
        return False, "orden desconocida"
    op = cmd["op"]
    if op == "pulso" and (not isinstance(cmd.get("tag"), str) or int(cmd.get("ms", 300)) <= 0):
        return False, "pulso mal formado"
    if op == "escribir" and (not isinstance(cmd.get("tag"), str) or "valor" not in cmd):
        return False, "escritura mal formada"
    if op == "entrada" and (not isinstance(cmd.get("tag"), str) or "valor" not in cmd):
        return False, "entrada mal formada"
    if op == "fuente" and cmd.get("fuente") not in FUENTES_OPC:
        return False, "fuente inválida"
    if op == "fisica" and "auto" not in cmd:
        return False, "fisica mal formada"
    if op == "mando" and cmd.get("accion") not in ACCIONES_MANDO:
        return False, "mando mal formado"
    if op == "presencia" and not isinstance(cmd.get("conectados"), list):
        return False, "presencia mal formada"
    if "quien" in cmd and not isinstance(cmd["quien"], dict):
        return False, "identidad mal formada"
    return True, ""
