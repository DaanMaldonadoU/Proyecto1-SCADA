# -*- coding: utf-8 -*-
"""
gateway/servidor.py — Bucle del gateway: lee la planta, publica snapshots y atiende órdenes.

Contrato: mds/ARQUITECTURA.md 4.1. Un solo hilo para backend + ZeroMQ (el objeto COM de
OpenOPC solo se usa desde el hilo que lo creó). Planificador por plazo:
`siguiente = inicio + n·periodo`; entre plazos se atienden las órdenes del socket REP con
zmq.Poller (timeout = tiempo hasta el plazo o hasta el siguiente flanco de bajada de un
pulso). No hay `sleep` después de leer: si la lectura tarda más que el periodo, el periodo
efectivo crece y se ve en `lat.periodo_ms`.

Orden de cada ciclo:
    (1) flancos de bajada de pulsos vencidos (las órdenes se escriben al llegar)
    (2) lectura del grupo rápido
    (3) grupo lento cada core.tags.PERIODO_LENTO_CICLOS ciclos o justo tras escribir un parámetro
    (4) decodificar palabras en bits, etapa (core.tags.etapa_activa), t_etapa, pos, pos_neum
    (5) alarmas (core.alarmas)
    (6) PUB [TOPIC_SNAP, snapshot] y [TOPIC_EVT, evento] por cada evento
    (7) historial (core.historial, en lote y sin bloquear)

Mando (mds/ARQUITECTURA.md 9): toda orden pasa por core.mando.Arbitro antes de escribir. Las
órdenes sin campo `quien` son del HMI local; las del puente web traen `quien` con origen "web".
El gateway es el único punto que escribe en el PLC y atiende las órdenes de una en una, así que
aquí se resuelve la concurrencia entre el HMI local y los usuarios de la web.

Modos: SIM, EMULATE y REAL (el modo lo da el backend).
Compatibilidad: Python 3.12 a 3.13. Dependencias: pyzmq, msgpack, loguru.
"""
from __future__ import annotations

import sys
import threading
import time

import zmq
from loguru import logger

from core import protocolo, tags
from core.alarmas import Alarmas
from core.latencia import EstadisticasLatencia
from core.mando import Arbitro, etiqueta
from gateway.fisica import CadenaNeumatica

FALLOS_PARA_DESCONECTAR = 5
# zmq_poll en Windows redondea su timeout al tick del sistema (~15,6 ms) aunque se pida
# timeBeginPeriod(1); los últimos milisegundos antes de un plazo se esperan en pasos finos.
# A veces tarda dos ticks, por eso el margen es de ~32 ms.
_GRANO_POLL_MS = 32.0 if sys.platform == "win32" else 1.0
_PASO_FINO_S = 0.001
ESPERAS_RECONEXION = (1.0, 2.0, 4.0, 8.0)


def _resolucion_timer_windows(activar):
    """En Windows sube la resolución del reloj del sistema a 1 ms mientras corre el bucle
    (si no, zmq_poll redondea los timeouts a ~15,6 ms y el periodo tiembla)."""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        winmm = ctypes.WinDLL("winmm")
        (winmm.timeBeginPeriod if activar else winmm.timeEndPeriod)(1)
    except Exception:
        pass


class Servidor:
    """Gateway ZeroMQ alrededor de un backend (BackendSim o BackendOPC)."""

    def __init__(self, backend, pub=protocolo.PUB_DEFECTO, cmd=protocolo.CMD_DEFECTO,
                 periodo_ms=None, contexto=None, historial=None, cadena=None,
                 remoto_habilitado=False):
        self.backend = backend
        self.modo = backend.modo
        self.periodo_ms = float(periodo_ms if periodo_ms else (50 if self.modo == "SIM" else 100))
        self.periodo_s = self.periodo_ms / 1000.0
        self.pub_dir = pub
        self.cmd_dir = cmd
        self.ctx = contexto or zmq.Context.instance()
        self.historial = historial
        self.cadena = cadena or CadenaNeumatica()
        self.lat = EstadisticasLatencia()
        self.alarmas = Alarmas(self.periodo_ms)
        self.mando = Arbitro(remoto_habilitado=remoto_habilitado)
        self._quien = None            # identidad de la orden en curso (core.mando)

        self.pub = None
        self.rep = None
        self.pub_endpoint = None      # endpoint real tras bind (útil con puertos efímeros)
        self.cmd_endpoint = None
        self.listo = threading.Event()
        self._parar = threading.Event()

        # Estado de conexión
        self.conectado = False
        self._fallos = 0
        self._n_reconexion = 0
        self._t_reintento = 0.0

        # Últimas lecturas
        self._valores = {}
        self._calidad = {}
        self._lento_pendiente = True
        self._t_lectura_ms = 0.0

        # Estado derivado
        self._etapa = None
        self._t_etapa0 = time.perf_counter()
        self._active_prev = None
        self._end_prev = False
        self._pulsos = {}             # tag -> t de vencimiento (perf_counter)
        self._eventos = []            # eventos pendientes de publicar
        self._ultima_escritura = None
        self._t_ciclo_prev = None
        self.ciclos = 0
        self.seq = 0
        self.fines = 0                # veces que se detectó END (fin de los N ciclos)
        self.snapshot = protocolo.snapshot_vacio(self.modo)

    # ================================================================== eventos y log
    def _evento(self, msg, nivel="info", origen="gateway"):
        ev = protocolo.evento(msg, nivel, origen)
        self._eventos.append(ev)
        (logger.warning if nivel != "info" else logger.info)(msg)
        return ev

    # ================================================================== sockets
    def abrir(self):
        """Crea y enlaza los sockets. Debe llamarse desde el hilo del bucle."""
        self.pub = self.ctx.socket(zmq.PUB)
        self.pub.setsockopt(zmq.LINGER, 0)
        self.pub.setsockopt(zmq.SNDHWM, 1000)
        self.pub.bind(self.pub_dir)
        self.rep = self.ctx.socket(zmq.REP)
        self.rep.setsockopt(zmq.LINGER, 0)
        self.rep.bind(self.cmd_dir)
        self.pub_endpoint = self.pub.getsockopt(zmq.LAST_ENDPOINT).decode()
        self.cmd_endpoint = self.rep.getsockopt(zmq.LAST_ENDPOINT).decode()
        self._poller = zmq.Poller()
        self._poller.register(self.rep, zmq.POLLIN)
        logger.info("Gateway {} publicando en {} · órdenes en {} · periodo {:.0f} ms",
                    self.modo, self.pub_endpoint, self.cmd_endpoint, self.periodo_ms)

    def detener(self):
        """Pide al bucle que termine (se puede llamar desde otro hilo)."""
        self._parar.set()

    def cerrar(self):
        for s in (self.pub, self.rep):
            if s is not None:
                try:
                    s.close(0)
                except Exception:
                    pass
        self.pub = self.rep = None
        try:
            self.backend.cerrar()
        except Exception as e:
            logger.warning("Error al cerrar el backend: {}", e)
        if self.historial is not None:
            self.historial.cerrar()

    # ================================================================== conexión
    def _intentar_conectar(self):
        try:
            self.backend.conectar()
        except Exception as e:
            espera = ESPERAS_RECONEXION[min(self._n_reconexion, len(ESPERAS_RECONEXION) - 1)]
            self._n_reconexion += 1
            self._t_reintento = time.perf_counter() + espera
            if self._n_reconexion == 1 or espera >= ESPERAS_RECONEXION[-1]:
                self._evento("No se pudo conectar (%s); reintento en %.0f s" % (e, espera), "alarma")
            return False
        self.conectado = True
        self._fallos = 0
        self._n_reconexion = 0
        self._lento_pendiente = True
        self._evento("Conectado (%s, fuente %s)" % (self.modo, self.backend.fuente))
        faltan = getattr(self.backend, "elementos_faltantes", lambda: [])()
        if faltan:
            self._evento("El PLC no tiene %s: no se leen ni se escriben. ¿El programa descargado "
                         "es el de la tabla (B3 con 4 palabras, T4 con 6 temporizadores)?"
                         % ", ".join(faltan), "alarma")
        return True

    def _fallo_lectura(self, e):
        self._fallos += 1
        logger.warning("Lectura fallida {}/{}: {}", self._fallos, FALLOS_PARA_DESCONECTAR, e)
        if self._fallos >= FALLOS_PARA_DESCONECTAR:
            self.conectado = False
            self._evento("Desconectado tras %d lecturas fallidas: %s" % (self._fallos, e), "alarma")
            try:
                self.backend.cerrar()
            except Exception:
                pass
            # Primer reintento en 1 s; si falla, 2, 4 y 8 s (tope).
            self._t_reintento = time.perf_counter() + ESPERAS_RECONEXION[0]
            self._n_reconexion = 1

    # ================================================================== escrituras
    def _registrar_escritura(self, tag, valor, ok, msg):
        t = time.time()
        quien = etiqueta(self._quien) if self._quien else "gateway"
        self._ultima_escritura = {"tag": tag, "valor": valor, "ok": bool(ok), "msg": msg, "t": t,
                                  "quien": quien}
        if self.historial is not None:
            self.historial.escritura(t, tag, valor, ok, ("[%s] %s" % (quien, msg)).strip())
        if not ok:
            self._evento("Escritura rechazada %s=%s: %s" % (tag, valor, msg), "aviso")

    def _escribir_pares(self, tag, pares):
        """Escribe [(dirección, valor)] en una sola llamada al backend. (ok, msg)."""
        if not self.conectado:
            return False, "sin conexión con el PLC / simulador"
        try:
            res = self.backend.escribir(pares)
        except Exception as e:
            return False, "error de escritura: %s" % e
        fallos = ["%s: %s" % (d, m) for d, ok, m in res if not ok]
        return (not fallos), "; ".join(fallos)

    def _procesar_pulsos(self, ahora):
        """Escribe el 0 de los pulsos cuyo plazo venció."""
        for tag in [t for t, venc in self._pulsos.items() if venc <= ahora]:
            del self._pulsos[tag]
            ok, msg = self._escribir_pares(tag, [(tags.PULSOS[tag], 0)])
            quien, self._quien = self._quien, None
            self._registrar_escritura(tag, 0, ok, msg)
            self._quien = quien

    # ================================================================== órdenes
    def procesar_orden(self, cmd):
        """Atiende una orden (dict) y devuelve la respuesta de core.protocolo.respuesta.
        Antes de ejecutarla la autoriza el árbitro de mando (core.mando)."""
        ok, motivo = protocolo.validar_comando(cmd)
        if not ok:
            self._evento("Orden rechazada: %s" % motivo, "aviso")
            return protocolo.respuesta(False, motivo)
        op = cmd["op"]
        if op == "mando":
            ok, msg = self.mando.orden_mando(cmd)
            self._volcar_eventos_mando()
            return protocolo.respuesta(ok, msg, mando=self.mando.estado())
        ok, motivo, quien = self.mando.autorizar(cmd)
        if not ok:
            self._evento("Orden de %s rechazada (%s %s): %s" % (
                etiqueta(quien), op, cmd.get("tag", ""), motivo), "aviso", origen=etiqueta(quien))
            self._volcar_eventos_mando()
            return protocolo.respuesta(False, motivo, mando=self.mando.estado())
        if op == "presencia":
            ok, msg = self.mando.presencia(cmd)
            self._volcar_eventos_mando()
            return protocolo.respuesta(ok, msg)
        self._quien = quien
        try:
            resp = self._ejecutar_orden(cmd)
        finally:
            self._quien = None
        if op in ("pulso", "escribir"):
            self.mando.anotar(quien, cmd, resp.get("ok"), resp.get("msg", ""))
        self._volcar_eventos_mando()
        return resp

    def _volcar_eventos_mando(self):
        for msg, nivel, origen in self.mando.sacar_eventos():
            self._evento(msg, nivel, origen)

    def _ejecutar_orden(self, cmd):
        op = cmd["op"]
        if op == "ping":
            return protocolo.respuesta(True, "pong", modo=self.modo)
        if op == "estado":
            return protocolo.respuesta(True, "", snapshot=self.snapshot)
        if op == "pulso":
            return self._orden_pulso(cmd["tag"], int(cmd.get("ms", tags.PULSO_MS)))
        if op == "escribir":
            return self._orden_escribir(cmd["tag"], cmd["valor"])
        if op == "entrada":
            return self._orden_entrada(cmd["tag"], cmd["valor"])
        if op == "fisica":
            if self.modo == "REAL":
                return self._rechazo("fisica", cmd.get("auto"), "en REAL no hay física simulada")
            ok, msg = self.backend.cambiar_fisica(bool(cmd["auto"]))
            if ok:
                self._evento(msg.capitalize())
            return protocolo.respuesta(ok, msg)
        if op == "fuente":
            ok, msg = self.backend.cambiar_fuente(cmd["fuente"])
            if ok:
                self._evento(msg.capitalize())
            else:
                self._evento("Cambio de fuente rechazado: %s" % msg, "aviso")
            return protocolo.respuesta(ok, msg)
        return protocolo.respuesta(False, "orden no implementada")

    def _rechazo(self, tag, valor, msg):
        self._registrar_escritura(tag, valor, False, msg)
        return protocolo.respuesta(False, msg)

    def _orden_pulso(self, tag, ms):
        if tag not in tags.PULSOS:
            return self._rechazo(tag, 1, "no es un pulso: %s" % tag)
        ok, msg = tags.validar_escritura(tag, self.modo, 1)
        if not ok:
            return self._rechazo(tag, 1, msg)
        ok, msg = self._escribir_pares(tag, [(tags.PULSOS[tag], 1)])
        self._registrar_escritura(tag, 1, ok, msg)
        if not ok:
            return protocolo.respuesta(False, msg)
        self._pulsos[tag] = time.perf_counter() + ms / 1000.0
        self._evento("Pulso %s (%d ms) · %s" % (tag, ms, etiqueta(self._quien)), origen=etiqueta(self._quien))
        return protocolo.respuesta(True, "pulso %s %d ms" % (tag, ms))

    def _orden_escribir(self, tag, valor):
        if tag not in tags.PARAMETROS:
            return self._rechazo(tag, valor, "no es un parámetro: %s" % tag)
        try:
            v = int(valor)
        except (TypeError, ValueError):
            return self._rechazo(tag, valor, "valor no entero")
        ok, msg = tags.validar_escritura(tag, self.modo, v)
        if not ok:
            return self._rechazo(tag, v, msg)
        # T_ESPERA: las cinco direcciones en una sola llamada al backend (un opc.write).
        ok, msg = self._escribir_pares(tag, [(d, v) for d in tags.PARAMETROS[tag]])
        self._registrar_escritura(tag, v, ok, msg)
        self._lento_pendiente = True
        if ok:
            self._evento("Parámetro %s = %d · %s" % (tag, v, etiqueta(self._quien)), origen=etiqueta(self._quien))
        return protocolo.respuesta(ok, msg or "%s = %d" % (tag, v))

    def _orden_entrada(self, tag, valor):
        if tag not in tags.ENTRADAS_SIMULABLES:
            return self._rechazo(tag, valor, "no es una entrada simulable: %s" % tag)
        v = bool(valor)
        ok, msg = tags.validar_escritura(tag, self.modo, v)
        if not ok:
            return self._rechazo(tag, v, msg)
        ok, msg = self._escribir_pares(tag, [(tags.DIRECCION[tag], v)])
        self._registrar_escritura(tag, v, ok, msg)
        return protocolo.respuesta(ok, msg or "%s = %d" % (tag, int(v)))

    def _atender_rep(self):
        try:
            datos = self.rep.recv(zmq.NOBLOCK)
        except zmq.Again:
            return
        try:
            cmd = protocolo.desempaquetar(datos)
            resp = self.procesar_orden(cmd)
        except Exception as e:
            logger.exception("Error atendiendo una orden")
            resp = protocolo.respuesta(False, "error interno: %s" % e)
        self.rep.send(protocolo.empaquetar(resp))

    def _esperar_hasta(self, plazo):
        """Atiende órdenes y flancos de pulsos hasta `plazo` (perf_counter)."""
        while not self._parar.is_set():
            ahora = time.perf_counter()
            if self._pulsos:
                self._procesar_pulsos(ahora)
            if ahora >= plazo:
                return
            limite = plazo
            if self._pulsos:
                limite = min(limite, min(self._pulsos.values()))
            restante_ms = (limite - ahora) * 1000.0
            if restante_ms > _GRANO_POLL_MS + 2.0:
                # Tramo largo: poll bloqueante (en Windows su timeout se redondea al tick).
                eventos = dict(self._poller.poll(int(restante_ms - _GRANO_POLL_MS)))
            else:
                # Tramo fino: poll sin espera + sleep corto (time.sleep sí es preciso a ~1 ms).
                eventos = dict(self._poller.poll(0))
                if not eventos:
                    time.sleep(min(_PASO_FINO_S, restante_ms / 1000.0))
            if self.rep in eventos:
                self._atender_rep()

    # ================================================================== ciclo
    def ciclo(self, periodo_real_ms=0.0):
        """Un ciclo completo (pasos 1 a 7)."""
        t0 = time.perf_counter()
        # (1) flancos de bajada vencidos
        self._procesar_pulsos(t0)

        # (2) grupo rápido (o reconexión)
        if not self.conectado and t0 >= self._t_reintento:
            self._intentar_conectar()
        t_lectura_ms = 0.0
        if self.conectado:
            try:
                valores, calidad, t_lectura_ms = self.backend.leer_rapido()
                self._valores.update(valores)
                self._calidad.update(calidad)
                self._fallos = 0
            except Exception as e:
                self._fallo_lectura(e)
        t_leido = time.time()

        # (3) grupo lento
        if self.conectado and (self._lento_pendiente or self.ciclos % tags.PERIODO_LENTO_CICLOS == 0):
            try:
                valores, calidad, _t = self.backend.leer_lento()
                self._valores.update(valores)
                self._calidad.update(calidad)
                self._lento_pendiente = False
            except Exception as e:
                logger.warning("Lectura lenta fallida: {}", e)

        # (4) decodificar
        snap = self._construir_snapshot(t_leido)
        ciclo_ms = (time.perf_counter() - t0) * 1000.0
        if self.conectado:
            self.lat.registrar(t_lectura_ms, ciclo_ms, periodo_real_ms)
        snap["lat"] = self.lat.resumen(self.backend.fuente)

        # (5) alarmas
        lista, eventos = self.alarmas.evaluar(snap, t_leido)
        snap["alarmas"] = lista
        for ev in eventos:
            self._eventos.append(ev)
            (logger.warning if ev["nivel"] != "info" else logger.info)("Alarma: {}", ev["msg"])

        # (6) publicar
        self.seq += 1
        snap["seq"] = self.seq
        self.snapshot = snap
        self.pub.send_multipart([protocolo.TOPIC_SNAP, protocolo.empaquetar(snap)])
        eventos_ciclo, self._eventos = self._eventos, []
        for ev in eventos_ciclo:
            self.pub.send_multipart([protocolo.TOPIC_EVT, protocolo.empaquetar(ev)])

        # (7) historial
        if self.historial is not None:
            for ev in eventos_ciclo:
                self.historial.evento(ev)
            for al, activa in self.alarmas.ultimos_cambios:
                self.historial.alarma(al, activa)
            self.historial.volcar()
        self.ciclos += 1
        return snap

    def _construir_snapshot(self, t_leido):
        snap = protocolo.snapshot_vacio(self.modo)
        snap["t"] = t_leido
        snap["conectado"] = self.conectado
        snap["fuente"] = self.backend.fuente
        snap["calidad"] = {"good": sum(1 for q in self._calidad.values() if q),
                           "total": len(self._calidad)}
        v = self._valores
        bits, ints, palabras = {}, {}, {}
        for palabra in tags.PALABRAS:
            if palabra in v:
                palabras[palabra] = int(v[palabra])
                bits.update(tags.decodificar_palabra(palabra, v[palabra]))
        for tag in tags.TAGS_BIT:
            d = tags.DIRECCION[tag]
            if d in v and tag not in bits:
                bits[tag] = bool(v[d])
        for tag in tags.TAGS_INT:
            d = tags.DIRECCION[tag]
            if d in v:
                ints[tag] = int(v[d])
        snap["bits"], snap["ints"], snap["palabras"] = bits, ints, palabras

        etapa = tags.etapa_activa(bits)
        ahora = time.perf_counter()
        etapa_prev = self._etapa
        if etapa != self._etapa:
            self._etapa = etapa
            self._t_etapa0 = ahora
            if etapa in (0, 7):
                # C5:0 solo cambia al entrar en X7 (CTU) o en X0 (GS): se relee el grupo lento.
                self._lento_pendiente = True
        snap["etapa"] = etapa
        snap["t_etapa"] = round(ahora - self._t_etapa0, 3)

        snap["pos"] = self.backend.pos
        pn = self.backend.pos_neum
        snap["pos_neum"] = pn if pn is not None else self.cadena.posiciones(snap["t_etapa"], etapa == 7)
        snap["escrituras"] = {"pendientes": len(self._pulsos), "ultima": self._ultima_escritura}

        # Eventos de estado de marcha
        if self.conectado and "ACTIVE" in bits:
            if self._active_prev is not None and bits["ACTIVE"] != self._active_prev:
                self._evento("Marcha (ACTIVE = 1)" if bits["ACTIVE"] else "Paro (ACTIVE = 0)")
            self._active_prev = bits["ACTIVE"]
            # END (y X8) solo duran un barrido del PLC: el GS los borra en el siguiente, así
            # que casi nunca coinciden con una lectura. También se detecta el fin por el paso
            # X7 → X0, que solo ocurre por el GS; si no hubo RESETV ni START_1·¬STOP_1, fue END.
            end_ahora = bool(bits.get("END")) or etapa == 8
            reset = (bits.get("RESETV") or "RESETV" in self._pulsos
                     or (bits.get("START_1") and not bits.get("STOP_1")))
            fin = (end_ahora and not self._end_prev) or (
                etapa_prev == 7 and etapa == 0 and not reset)
            if fin:
                self.fines += 1
                self._evento("Fin de %s ciclos (END)" % ints.get("C_PRE", "N"))
            self._end_prev = end_ahora
        snap["fines"] = self.fines

        # Mando: vencimientos y estado para el HMI y la web
        self.mando.tick()
        self._volcar_eventos_mando()
        snap["mando"] = self.mando.estado()
        return snap

    # ================================================================== bucle
    def bucle(self, parar=None):
        """Corre hasta `detener()`, Ctrl+C o hasta que `parar(snapshot)` devuelva True."""
        _resolucion_timer_windows(True)
        try:
            if self.pub is None:
                self.abrir()
            self._intentar_conectar()
            self.listo.set()
            siguiente = time.perf_counter()
            while not self._parar.is_set():
                self._esperar_hasta(siguiente)
                if self._parar.is_set():
                    break
                inicio = time.perf_counter()
                periodo_real_ms = 0.0 if self._t_ciclo_prev is None else (inicio - self._t_ciclo_prev) * 1000.0
                self._t_ciclo_prev = inicio
                snap = self.ciclo(periodo_real_ms)
                siguiente += self.periodo_s
                ahora = time.perf_counter()
                if siguiente < ahora:
                    # Vamos tarde (lectura lenta): no se recuperan ciclos en ráfaga.
                    siguiente = ahora
                if parar is not None and parar(snap):
                    break
        except KeyboardInterrupt:
            logger.info("Interrumpido por el usuario (Ctrl+C)")
        finally:
            _resolucion_timer_windows(False)
            self.listo.set()
            self.cerrar()
