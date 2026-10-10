# -*- coding: utf-8 -*-
"""
core/remoto.py — Enlace HMI ⇄ servidor web del gemelo: firma de órdenes y formato de mensajes.

Qué hace:
    El servidor web (digital_twin/servidor_web) autentica a las personas y decide por rol;
    el puente (puente/) corre junto al HMI y entrega las órdenes al gateway. Entre los dos
    hay Internet y Cloudflare. Cada orden viaja FIRMADA con HMAC-SHA256 y una clave que
    solo conocen el servidor y el puente (`datos/puente.clave`). El puente rechaza órdenes
    sin firma válida, con hora fuera de tolerancia (±TOLERANCIA_S) o repetidas (mismo id):
    así nadie puede inyectar ni reenviar órdenes aunque llegue al WebSocket.

Mensajes JSON por el WebSocket /ws/planta (campo "tipo"):
    puente → servidor
      {"tipo": "hola", "v": 1, "planta": str, "modo": str}
      {"tipo": "snap", "s": <snapshot con pos estimada si hace falta>}
      {"tipo": "evt",  "e": <evento>}
      {"tipo": "resultado", "id": str, "ok": bool, "msg": str, "t": float, "mando": dict|None}
    servidor → puente
      {"tipo": "orden", "id": str, "t": float, "quien": {"usuario", "rol", "origen": "web"},
       "cmd": {"op": ..., ...}, "firma": hex}
      {"tipo": "presencia", "conectados": [{"usuario", "rol", "desde"}]}
      {"tipo": "ping", "t": float}

Compatibilidad: Python 3.12 a 3.13, solo biblioteca estándar.
"""
import hashlib
import hmac
import json
import os
import secrets
import time
from collections import OrderedDict

VERSION_ENLACE = 1
TOLERANCIA_S = 30.0        # diferencia de reloj aceptada entre servidor y puente
MAX_IDS_VISTOS = 2000


def generar_clave():
    """Clave nueva (texto seguro para copiar a mano entre las dos máquinas)."""
    return secrets.token_urlsafe(32)


def leer_clave(ruta, crear=False):
    """Lee la clave de un archivo. Con crear=True la genera si no existe."""
    if not os.path.exists(ruta):
        if not crear:
            raise FileNotFoundError("no existe la clave del puente: %s" % ruta)
        carpeta = os.path.dirname(os.path.abspath(ruta))
        os.makedirs(carpeta, exist_ok=True)
        with open(ruta, "w", encoding="utf-8") as f:
            f.write(generar_clave() + "\n")
    with open(ruta, "r", encoding="utf-8-sig") as f:      # utf-8-sig: tolera el BOM del Bloc de notas
        clave = f.read().strip()
    if len(clave) < 16:
        raise ValueError("clave del puente demasiado corta en %s" % ruta)
    return clave


def _canonico(orden):
    cuerpo = {"id": orden.get("id"), "t": orden.get("t"), "quien": orden.get("quien"),
              "cmd": orden.get("cmd")}
    return json.dumps(cuerpo, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")


def firmar(clave, orden):
    """Devuelve la orden con el campo "firma" (no modifica la original)."""
    o = dict(orden)
    o["firma"] = hmac.new(clave.encode("utf-8"), _canonico(o), hashlib.sha256).hexdigest()
    return o


def nueva_orden(clave, cmd, quien, t=None):
    """Orden firmada lista para mandar al puente."""
    q = {"usuario": str(quien.get("usuario")), "rol": str(quien.get("rol")), "origen": "web"}
    return firmar(clave, {"tipo": "orden", "id": secrets.token_hex(8),
                          "t": time.time() if t is None else float(t), "quien": q, "cmd": dict(cmd)})


class Verificador:
    """Comprueba firma, frescura y que no se repita el id."""

    def __init__(self, clave, tolerancia_s=TOLERANCIA_S, reloj=time.time):
        self._clave = clave.encode("utf-8")
        self.tolerancia_s = tolerancia_s
        self._reloj = reloj
        self._vistos = OrderedDict()

    def verificar(self, orden):
        """(ok, motivo)."""
        if not isinstance(orden, dict) or not isinstance(orden.get("cmd"), dict):
            return False, "orden mal formada"
        firma = orden.get("firma")
        if not isinstance(firma, str):
            return False, "orden sin firma"
        esperada = hmac.new(self._clave, _canonico(orden), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(firma, esperada):
            return False, "firma inválida"
        try:
            t = float(orden.get("t"))
        except (TypeError, ValueError):
            return False, "orden sin hora"
        if abs(self._reloj() - t) > self.tolerancia_s:
            return False, "orden fuera de tiempo (%.0f s de diferencia)" % (self._reloj() - t)
        oid = orden.get("id")
        if not isinstance(oid, str) or not oid:
            return False, "orden sin id"
        if oid in self._vistos:
            return False, "orden repetida"
        self._vistos[oid] = t
        while len(self._vistos) > MAX_IDS_VISTOS:
            self._vistos.popitem(last=False)
        quien = orden.get("quien")
        if not isinstance(quien, dict) or quien.get("origen") != "web":
            return False, "identidad inválida"
        return True, ""


def a_json(obj):
    """JSON compacto; los floats se dejan tal cual (el snapshot ya viene redondeado)."""
    return json.dumps(obj, separators=(",", ":"), ensure_ascii=False, default=str)
