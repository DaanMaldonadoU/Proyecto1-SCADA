# -*- coding: utf-8 -*-
"""
core/mando.py — Árbitro de mando: quién puede escribir en el PLC y cuándo.

Qué hace:
    Todas las órdenes que escriben (las del HMI local y las que llegan de la web por el
    puente) pasan por el gateway, que es el único proceso que habla con el PLC. Este
    módulo decide, en ese único punto, si una orden se acepta. Así el control de
    concurrencia no depende de que la web y el HMI se pongan de acuerdo: el gateway
    atiende las órdenes de una en una (un solo hilo) y consulta aquí.

Reglas (mds/ARQUITECTURA.md sección 9):
    * Roles de la web, de menor a mayor: usuario (solo ve), operador (START/STOP/RESET),
      ingeniero (además parámetros), admin (además gestiona cuentas en el servidor).
      El HMI local tiene el nivel más alto: quien está frente a la máquina manda.
    * "Mando" = permiso exclusivo y temporal para escribir. Lo tiene como mucho una
      persona. Una orden remota que escribe exige tener el mando. Se pide con la orden
      `mando/pedir`; se concede si está libre, vencido, ya es tuyo o tu nivel es mayor
      que el de quien lo tiene (preferencia por jerarquía). Se renueva con cada orden
      aceptada y vence tras DURACION_S sin actividad.
    * El HMI local no necesita pedirlo: cualquier escritura local lo toma (y se lo quita
      a la web si lo tenía). Vence tras DURACION_LOCAL_S sin actividad local.
    * El mando remoto está deshabilitado hasta que el HMI local lo habilita (o el gateway
      arranca con --remoto). Deshabilitarlo revoca el mando web en el acto.
    * STOPV se acepta SIEMPRE de cualquier operador o superior, tenga o no el mando y
      aunque el mando remoto esté deshabilitado: parar nunca debe esperar a nadie.
    * `entrada`, `fisica` y `fuente` (simulación y diagnóstico) son solo locales.

Identidad en las órdenes (core.protocolo): campo opcional `quien`
    {"usuario": str, "rol": str, "origen": "web"}. Sin `quien` la orden es local.
    El puente es el único que pone origen "web"; el gateway solo escucha en 127.0.0.1.

Se usa en: gateway/servidor.py (autoriza) y en el servidor web (filtra antes de mandar,
para responder rápido; la decisión final es la del gateway).
Compatibilidad: Python 3.12 a 3.13, solo biblioteca estándar.
"""
import time
from collections import OrderedDict

# Rol -> nivel. "local" es el HMI frente a la máquina.
ROLES = OrderedDict([("usuario", 0), ("operador", 1), ("ingeniero", 2), ("admin", 3)])
NIVEL_LOCAL = 10
ROLES_WEB = tuple(ROLES)

DURACION_S = 120.0          # mando web: vence tras 2 min sin órdenes
DURACION_LOCAL_S = 60.0     # mando local: vence tras 1 min sin órdenes locales
ENLACE_VIGENTE_S = 15.0     # sin noticias del puente en este tiempo -> enlace web caído

QUIEN_LOCAL = {"usuario": "HMI local", "rol": "local", "origen": "local"}

# Nivel mínimo por operación (y por tag en los pulsos). None = solo local.
NIVEL_MINIMO_PULSO = {"STARTV": 1, "STOPV": 1, "RESETV": 1}
NIVEL_MINIMO_OP = {
    "ping": 0, "estado": 0,
    "pulso": 1,            # se afina por tag con NIVEL_MINIMO_PULSO
    "escribir": 2,
    "mando": 1,
    "entrada": None, "fisica": None, "fuente": None, "presencia": None,
}
OPS_QUE_ESCRIBEN = ("pulso", "escribir")


def nivel(quien):
    """Nivel numérico de una identidad `quien`."""
    if not quien or quien.get("origen", "local") == "local":
        return NIVEL_LOCAL
    return ROLES.get(quien.get("rol"), -1)


def normalizar_quien(cmd):
    """Identidad de la orden: la de `cmd["quien"]` si viene de la web, si no la local."""
    q = cmd.get("quien") if isinstance(cmd, dict) else None
    if not isinstance(q, dict) or q.get("origen") != "web":
        return dict(QUIEN_LOCAL)
    return {"usuario": str(q.get("usuario", "?"))[:40], "rol": str(q.get("rol", "?")),
            "origen": "web"}


def etiqueta(quien):
    """Texto corto para eventos y pantallas: 'HMI local' o 'web · daan (operador)'."""
    if not quien:
        return "nadie"
    if quien.get("origen") == "local":
        return "HMI local"
    return "web · %s (%s)" % (quien.get("usuario"), quien.get("rol"))


def nivel_requerido(cmd):
    """Nivel mínimo para una orden, o None si es solo local."""
    op = cmd.get("op")
    if op == "pulso":
        return NIVEL_MINIMO_PULSO.get(cmd.get("tag"), 1)
    return NIVEL_MINIMO_OP.get(op)


def permiso_por_rol(rol, cmd):
    """(ok, motivo) solo por rol, sin mirar el mando. Lo usa el servidor web como filtro."""
    requerido = nivel_requerido(cmd)
    if requerido is None:
        return False, "esa orden solo se permite desde el HMI local"
    if ROLES.get(rol, -1) < requerido:
        nombre = [r for r, n in ROLES.items() if n >= requerido]
        return False, "el rol %s no basta; se requiere %s" % (rol, nombre[0] if nombre else "local")
    return True, ""


def _mismo(a, b):
    return bool(a and b and a.get("origen") == b.get("origen") and a.get("usuario") == b.get("usuario"))


class Arbitro:
    """Estado del mando y reglas de autorización. No es seguro entre hilos: el gateway lo
    usa desde su único hilo."""

    def __init__(self, remoto_habilitado=False, duracion_s=DURACION_S,
                 duracion_local_s=DURACION_LOCAL_S, reloj=time.monotonic, reloj_pared=time.time):
        self.remoto_habilitado = bool(remoto_habilitado)
        self.duracion_s = float(duracion_s)
        self.duracion_local_s = float(duracion_local_s)
        self._reloj = reloj
        self._pared = reloj_pared
        self.titular = None           # identidad `quien` o None
        self._desde = 0.0             # hora de pared en que lo tomó
        self._vence = 0.0             # reloj monótono
        self.conectados = []          # usuarios web en línea (los manda el puente)
        self._t_enlace = None         # última noticia del puente (monótono)
        self.ultima_orden = None
        self.eventos = []             # (msg, nivel, origen) pendientes de publicar

    # ------------------------------------------------------------------ utilidades
    def _evento(self, msg, nivel_evt="info", quien=None):
        self.eventos.append((msg, nivel_evt, etiqueta(quien) if quien else "mando"))

    def sacar_eventos(self):
        ev, self.eventos = self.eventos, []
        return ev

    def _vigente(self):
        return self.titular is not None and self._reloj() < self._vence

    def tick(self):
        """Libera el mando vencido. Llamar una vez por ciclo."""
        if self.titular is not None and self._reloj() >= self._vence:
            self._evento("El mando de %s venció por inactividad" % etiqueta(self.titular))
            self.titular = None
        if self._t_enlace is not None and not self.enlace_web():
            self._evento("Enlace web perdido (sin noticias del puente en %.0f s)" % ENLACE_VIGENTE_S,
                         "aviso")
            self._t_enlace = None
            self.conectados = []
            if self.titular and self.titular.get("origen") == "web":
                self._evento("Se revoca el mando de %s" % etiqueta(self.titular), "aviso")
                self.titular = None

    def _dar(self, quien):
        previo = self.titular if self._vigente() else None
        if not _mismo(previo, quien):
            self._desde = self._pared()
            if previo is None:
                self._evento("%s toma el mando" % etiqueta(quien), quien=quien)
            else:
                self._evento("%s toma el mando (antes: %s)" % (etiqueta(quien), etiqueta(previo)),
                             "aviso", quien)
        self.titular = dict(quien)
        dur = self.duracion_local_s if quien.get("origen") == "local" else self.duracion_s
        self._vence = self._reloj() + dur

    # ------------------------------------------------------------------ órdenes de mando
    def orden_mando(self, cmd):
        """Atiende {"op": "mando", "accion": "pedir"|"liberar"|"remoto", "habilitar": bool}.
        Devuelve (ok, msg)."""
        quien = normalizar_quien(cmd)
        accion = cmd.get("accion")
        if accion == "remoto":
            if quien["origen"] != "local":
                return False, "solo el HMI local habilita o deshabilita el mando remoto"
            hab = bool(cmd.get("habilitar"))
            if hab != self.remoto_habilitado:
                self.remoto_habilitado = hab
                self._evento("Mando remoto %s" % ("habilitado" if hab else "deshabilitado"),
                             "aviso", quien)
                if not hab and self.titular and self.titular.get("origen") == "web":
                    self._evento("Se revoca el mando de %s" % etiqueta(self.titular), "aviso")
                    self.titular = None
            return True, "mando remoto %s" % ("habilitado" if hab else "deshabilitado")
        if accion == "pedir":
            return self._pedir(quien)
        if accion == "liberar":
            return self._liberar(quien)
        return False, "acción de mando desconocida"

    def _pedir(self, quien):
        if quien["origen"] == "local":
            self._dar(quien)
            return True, "mando tomado por el HMI local"
        if not self.remoto_habilitado:
            return False, "el mando remoto está deshabilitado en el HMI local"
        if nivel(quien) < ROLES["operador"]:
            return False, "el rol %s solo puede ver" % quien["rol"]
        if not self._vigente() or _mismo(self.titular, quien):
            self._dar(quien)
            return True, "mando concedido por %.0f s" % self.duracion_s
        if nivel(quien) > nivel(self.titular):
            self._dar(quien)
            return True, "mando concedido por jerarquía (antes: %s)" % etiqueta(self.titular)
        return False, "el mando lo tiene %s (vence en %.0f s)" % (
            etiqueta(self.titular), max(0.0, self._vence - self._reloj()))

    def _liberar(self, quien):
        if not self._vigente():
            self.titular = None
            return True, "el mando ya estaba libre"
        if _mismo(self.titular, quien) or quien["origen"] == "local":
            self._evento("%s libera el mando" % etiqueta(quien), quien=quien)
            self.titular = None
            return True, "mando liberado"
        return False, "no tienes el mando"

    # ------------------------------------------------------------------ autorización
    def autorizar(self, cmd):
        """(ok, motivo, quien) para una orden cualquiera. Si se acepta una escritura,
        renueva o toma el mando. Las órdenes `mando` y `presencia` se atienden aparte."""
        quien = normalizar_quien(cmd)
        op = cmd.get("op")
        if op not in OPS_QUE_ESCRIBEN:
            if quien["origen"] == "local" or NIVEL_MINIMO_OP.get(op) == 0:
                return True, "", quien
            return False, "esa orden solo se permite desde el HMI local", quien

        if quien["origen"] == "local":
            self._dar(quien)
            return True, "", quien

        ok, motivo = permiso_por_rol(quien["rol"], cmd)
        if not ok:
            return False, motivo, quien
        if op == "pulso" and cmd.get("tag") == "STOPV":
            return True, "", quien                      # parar nunca espera
        if not self.remoto_habilitado:
            return False, "el mando remoto está deshabilitado en el HMI local", quien
        if not self._vigente():
            return False, "pide el mando antes de escribir (está libre)", quien
        if not _mismo(self.titular, quien):
            return False, "el mando lo tiene %s" % etiqueta(self.titular), quien
        self._dar(quien)                                # renueva
        return True, "", quien

    def anotar(self, quien, cmd, ok, msg):
        """Guarda la última orden que escribe (para la pantalla)."""
        self.ultima_orden = {"t": self._pared(), "quien": dict(quien), "op": cmd.get("op"),
                             "tag": cmd.get("tag"), "valor": cmd.get("valor", 1 if cmd.get("op") == "pulso" else None),
                             "ok": bool(ok), "msg": msg}

    # ------------------------------------------------------------------ presencia web
    def presencia(self, cmd):
        """{"op": "presencia", "conectados": [{"usuario", "rol", "desde"}]} que manda el
        puente cada pocos segundos (solo el puente, con origen local en 127.0.0.1)."""
        lista = cmd.get("conectados") or []
        limpia = []
        for u in lista[:50]:
            if isinstance(u, dict):
                limpia.append({"usuario": str(u.get("usuario", "?"))[:40],
                               "rol": str(u.get("rol", "?")), "desde": u.get("desde")})
        if self._t_enlace is None:
            self._evento("Enlace web activo (%d en línea)" % len(limpia))
        self.conectados = limpia
        self._t_enlace = self._reloj()
        return True, "presencia: %d" % len(limpia)

    def enlace_web(self):
        return self._t_enlace is not None and self._reloj() - self._t_enlace < ENLACE_VIGENTE_S

    # ------------------------------------------------------------------ estado
    def estado(self):
        """Bloque `mando` del snapshot."""
        vig = self._vigente()
        enlace = self.enlace_web()
        return {
            "remoto_habilitado": self.remoto_habilitado,
            "titular": dict(self.titular) if vig else None,
            "desde": self._desde if vig else None,
            "vence_en_s": round(max(0.0, self._vence - self._reloj()), 1) if vig else 0.0,
            "enlace_web": enlace,
            "conectados": list(self.conectados) if enlace else [],
            "ultima_orden": self.ultima_orden,
        }


def mando_vacio():
    return Arbitro().estado()
