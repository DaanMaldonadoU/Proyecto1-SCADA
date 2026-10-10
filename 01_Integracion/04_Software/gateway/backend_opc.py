# -*- coding: utf-8 -*-
"""
gateway/backend_opc.py — Backend OPC DA contra RSLinx Classic por OpenOPC (COM).

Modos:
* EMULATE: contra RSLogix Emulate 500. No hay planta: la Fisica del gateway mueve
  1A/2A/3A según las EV leídas de O:2.0 y escribe los sensores en I:1.0, primero bit a
  bit y, si RSLinx lo rechaza, por lectura-modificación-escritura de la palabra
  (core.tags.codificar_palabra), igual que v6.1.
* REAL: contra el SLC 5/04 por DF1. Se rechaza cualquier dirección I: además de lo que
  ya bloquea core.tags.validar_escritura.

Lectura:
* fuente "cache" (defecto): opc.read(items, group="rapido", update=periodo_ms, sync=True, source="cache")
  RSLinx sondea el PLC por su cuenta al ritmo `update` y la lectura tarda ~6 ms.
* fuente "dispositivo":     opc.read(items, group="rapido", sync=True, source="device")
  Cada lectura viaja al PLC: ~200 ms por DF1 con picos de 1-2 s (medido el 03-oct).
  Al cambiar de fuente se elimina el grupo (opc.remove("rapido")) y se recrea en la
  siguiente lectura. El grupo lento (C5:0) se lee síncrono en su propio grupo.
Solo cuentan los valores con calidad "Good".

Direcciones inexistentes: RSLinx junta en un paquete DF1 los items del mismo archivo
(B3, T4…). Si uno no existe en el PLC (p. ej. B3:3 cuando el archivo B3 tiene una sola
palabra), el paquete entero vuelve Bad, también B3:0, y eso afecta a TODOS los clientes
de RSLinx mientras el item siga en algún grupo. Por eso `conectar()` valida la tabla y
quita del sondeo lo que el PLC no tiene (`faltantes`); las escrituras a esas direcciones
se rechazan con un mensaje claro.

Misma interfaz que backend_sim.BackendSim. El objeto COM se crea en `conectar()` y
solo se usa desde el hilo del servidor que lo llamó (regla de REGLAS.md 6).
`import OpenOPC` va dentro de `conectar()` para que SIM y las pruebas no lo necesiten.

Requiere: Windows, Python 3.12 de 32 bits, pywin32,
OpenOPC-Python3x, gbda_aut.dll registrada y RSLinx Classic con OPC en la misma máquina.
"""
from __future__ import annotations

import time

from core import tags
from gateway.fisica import Fisica

GRUPO_RAPIDO = "rapido"
GRUPO_LENTO = "lento"
GRUPO_VALIDAR = "validar"
_PALABRA_I = "I:1.0"


def _es_bit(direccion):
    return "/" in direccion


def _elemento(direccion):
    """'T4:5.PRE' y 'T4:5/DN' -> 'T4:5'; 'B3:3' -> 'B3:3'. Es lo que existe o no en el PLC."""
    base = direccion.split("/")[0]
    if base[0] in "TC" and "." in base:
        base = base.split(".")[0]
    return base


class BackendOPC:
    """Lectura/escritura por OPC DA. modo: "EMULATE" | "REAL"."""

    def __init__(self, modo, servidor="RSLinx Local OPC Server", topic="PROYECTO1_TEST",
                 fuente="cache", periodo_ms=100, carreras=None, fisica_auto=True, log=None):
        if modo not in ("EMULATE", "REAL"):
            raise ValueError("BackendOPC solo admite EMULATE o REAL")
        if fuente not in ("dispositivo", "cache"):
            raise ValueError("fuente inválida: %s" % fuente)
        self.modo = modo
        self.servidor = servidor
        self.topic = topic
        self.fuente = fuente
        self.periodo_ms = int(periodo_ms)
        self.fisica_auto = bool(fisica_auto) and modo == "EMULATE"
        self.log = log or (lambda msg: None)
        self.opc = None
        self._conectado = False
        self._grupo_rapido_creado = False
        self.fis = Fisica(carreras) if modo == "EMULATE" else None
        self._ultimos_sensores = None
        self._modo_entradas = None      # None: probar bit; "bit" | "palabra" | "fallo"
        self._t_prev = None
        self.faltantes = []             # direcciones que el PLC no tiene (las llena conectar)
        self._fijar_direcciones(())

    def _fijar_direcciones(self, faltantes):
        self.faltantes = sorted(faltantes)
        self._dirs_rapidos = [d for d in tags.ITEMS_RAPIDOS if d not in faltantes]
        self._dirs_lentos = [d for d in tags.ITEMS_LENTOS if d not in faltantes]
        self._items_rapidos = [self.item(d) for d in self._dirs_rapidos]
        self._items_lentos = [self.item(d) for d in self._dirs_lentos]

    # ------------------------------------------------------------------ propiedades
    @property
    def conectado(self):
        return self._conectado

    @property
    def pos(self):
        """Posición exacta de la física en EMULATE; None en REAL (la estima el HMI)."""
        if self.fis is None:
            return None
        return [round(p, 4) for p in self.fis.pos]

    @property
    def pos_neum(self):
        return None     # el servidor la estima con CadenaNeumatica y t_etapa

    def item(self, direccion):
        return tags.item_opc(self.topic, direccion)

    # ------------------------------------------------------------------ ciclo de vida
    def conectar(self):
        import OpenOPC                  # solo Windows; dentro para que SIM no lo necesite
        try:
            import pythoncom            # COM en el hilo actual (el del servidor)
            pythoncom.CoInitialize()
        except Exception:
            pass
        self.opc = OpenOPC.client()
        self.opc.connect(self.servidor)
        self._grupo_rapido_creado = False
        try:
            self._validar_direcciones()
        except Exception:
            self.cerrar()
            raise
        self._conectado = True
        self._t_prev = time.perf_counter()
        self.log("OPC DA conectado a '%s', topic [%s], %d items rápidos, fuente %s"
                 % (self.servidor, self.topic, len(self._items_rapidos), self.fuente))
        if self.modo == "EMULATE":
            iniciales = [("STOP_1", True)]              # pulsador NC en reposo
            if self.fisica_auto:
                iniciales += sorted(self.fis.sensores_por_tag().items())
                self._ultimos_sensores = self.fis.sensores_por_tag()
            self._escribir_entradas(iniciales)

    def _validar_direcciones(self):
        """Lee la tabla completa una vez desde el dispositivo; lo que no sale Good se prueba
        elemento por elemento (cada uno en su propia lectura, para que un vecino inexistente no
        lo contamine) y lo que sigue Bad se quita del sondeo. Si NADA sale Good, el problema es
        la comunicación (PLC apagado, topic mal configurado) y se lanza la excepción."""
        todas = list(tags.ITEMS_RAPIDOS) + list(tags.ITEMS_LENTOS)
        try:
            crudos = self.opc.read([self.item(d) for d in todas], group=GRUPO_VALIDAR,
                                   sync=True, source="device")
        finally:
            try:
                self.opc.remove(GRUPO_VALIDAR)   # antes de probar uno a uno: si no, sigue contaminando
            except Exception:
                pass
        dudosas = [d for d, fila in zip(todas, crudos) if fila[2] != "Good"]
        if len(dudosas) == len(todas):
            raise RuntimeError("ningún item del topic [%s] con calidad Good (p. ej. %s: %s); "
                               "¿PLC sin comunicación o topic mal configurado en RSLinx?"
                               % (self.topic, todas[0], crudos[0][2]))
        existe = {}
        for d in dudosas:
            e = _elemento(d)
            if e not in existe:
                try:
                    _v, q, _ts = self.opc.read(self.item(d), sync=True, source="device")
                    existe[e] = (q == "Good")
                except Exception:
                    existe[e] = False
        faltantes = [d for d in dudosas if not existe[_elemento(d)]]
        self._fijar_direcciones(set(faltantes))
        if faltantes:
            elementos = sorted({_elemento(d) for d in faltantes})
            self.log("El PLC no tiene %s: se quitan de la lectura (%d items)"
                     % (", ".join(elementos), len(faltantes)))

    def elementos_faltantes(self):
        """['B3:3', 'T4:4', …]: elementos de la tabla que el PLC no tiene."""
        return sorted({_elemento(d) for d in self.faltantes})

    def cerrar(self):
        self._conectado = False
        if self.opc is None:
            return
        for g in (GRUPO_RAPIDO, GRUPO_LENTO):
            try:
                self.opc.remove(g)
            except Exception:
                pass
        try:
            self.opc.close()
        except Exception:
            pass
        self.opc = None

    def cambiar_fuente(self, fuente):
        if fuente not in ("dispositivo", "cache"):
            return False, "fuente inválida: %s" % fuente
        if fuente == self.fuente:
            return True, "fuente ya era %s" % fuente
        self.fuente = fuente
        if self.opc is not None and self._grupo_rapido_creado:
            try:
                self.opc.remove(GRUPO_RAPIDO)
            except Exception as e:
                self.log("No se pudo eliminar el grupo %s: %s" % (GRUPO_RAPIDO, e))
        self._grupo_rapido_creado = False
        return True, "fuente OPC: %s" % fuente

    def cambiar_fisica(self, auto):
        if self.modo != "EMULATE":
            return False, "la física del gateway solo existe en EMULATE"
        self.fisica_auto = bool(auto)
        self._ultimos_sensores = None        # fuerza reescritura completa al volver a automático
        return True, "física %s" % ("automática" if self.fisica_auto else "manual")

    # ------------------------------------------------------------------ lectura
    def _procesar(self, direcciones, crudos):
        valores, calidad = {}, {}
        for d, fila in zip(direcciones, crudos):
            _nombre, val, q, _ts = fila
            ok = (q == "Good") and val is not None
            calidad[d] = ok
            if ok:
                if d in tags.PALABRAS:
                    valores[d] = int(val) & 0xFFFF          # RSLinx entrega palabras con signo
                elif _es_bit(d):
                    valores[d] = bool(int(val))
                else:
                    valores[d] = int(val)
        if direcciones and not any(calidad.values()):
            raise RuntimeError("ningún item con calidad Good (p. ej. %s: %s)" % (crudos[0][0], crudos[0][2]))
        return valores, calidad

    def leer_rapido(self):
        if not self._conectado:
            raise RuntimeError("OPC no conectado")
        t0 = time.perf_counter()
        # OpenOPC: `source` decide de dónde lee el servidor. "device" fuerza el viaje al PLC
        # en cada llamada; "cache" devuelve lo último que RSLinx trajo con su propio sondeo,
        # cuyo ritmo fija `update` (ms). `sync=False` NO es leer de caché: es AsyncIO.Read,
        # que también va al dispositivo. Por eso ambas variantes son síncronas.
        if self.fuente == "dispositivo":
            crudos = self.opc.read(self._items_rapidos, group=GRUPO_RAPIDO,
                                   sync=True, source="device")
        else:
            crudos = self.opc.read(self._items_rapidos, group=GRUPO_RAPIDO,
                                   update=self.periodo_ms, sync=True, source="cache")
        t_ms = (time.perf_counter() - t0) * 1000.0
        self._grupo_rapido_creado = True
        valores, calidad = self._procesar(self._dirs_rapidos, crudos)
        if self.modo == "EMULATE":
            self._paso_fisica(valores)
        return valores, calidad, t_ms

    def leer_lento(self):
        if not self._conectado:
            raise RuntimeError("OPC no conectado")
        if not self._items_lentos:
            return {}, {}, 0.0
        t0 = time.perf_counter()
        crudos = self.opc.read(self._items_lentos, group=GRUPO_LENTO, sync=True)
        t_ms = (time.perf_counter() - t0) * 1000.0
        valores, calidad = self._procesar(self._dirs_lentos, crudos)
        return valores, calidad, t_ms

    # ------------------------------------------------------------------ EMULATE: física
    def _paso_fisica(self, valores):
        ahora = time.perf_counter()
        dt = 0.0 if self._t_prev is None else ahora - self._t_prev
        self._t_prev = ahora
        palabra_o = valores.get("O:2.0")
        if palabra_o is None:
            return                              # sin EV válidas no se mueve nada
        ev = Fisica.ev_de_bits(tags.decodificar_palabra("O:2.0", palabra_o))
        self.fis.step(dt, ev)
        if not self.fisica_auto:
            return
        actuales = self.fis.sensores_por_tag()
        previos = self._ultimos_sensores or {}
        cambios = [(t, v) for t, v in actuales.items() if previos.get(t) != v]
        if cambios:
            self._escribir_entradas(cambios)
            self._ultimos_sensores = actuales

    def _escribir_entradas(self, cambios):
        """[(tag, bool)] de I:1.0. Bit a bit; si RSLinx rechaza, palabra completa (RMW).

        Devuelve (ok, msg)."""
        if self.modo == "REAL":
            return False, "en modo REAL no se escriben entradas I:1"
        if not cambios:
            return True, ""
        if self._modo_entradas in (None, "bit"):
            pares = [(self.item(tags.DIRECCION[t]), bool(v)) for t, v in cambios]
            try:
                res = self.opc.write(pares)
                if self._todos_success(res):
                    self._modo_entradas = "bit"
                    return True, ""
                motivo = self._primer_error(res)
            except Exception as e:
                motivo = str(e)
            if self._modo_entradas is None:
                self.log("RSLinx rechazó escribir bits de I:1 (%s); se prueba por palabra" % motivo)
        try:
            item_palabra = self.item(_PALABRA_I)
            _n, val, q, _ts = self.opc.read([item_palabra], sync=True)[0]
            if q != "Good" or val is None:
                raise RuntimeError("lectura de %s con calidad %s" % (_PALABRA_I, q))
            palabra = tags.codificar_palabra(_PALABRA_I, dict(cambios), base=int(val) & 0xFFFF)
            res = self.opc.write([(item_palabra, palabra)])
            if not self._todos_success(res):
                raise RuntimeError("%s -> %s" % (_PALABRA_I, self._primer_error(res)))
            if self._modo_entradas != "palabra":
                self._modo_entradas = "palabra"
                self.log("Entradas simuladas escritas por palabra %s" % _PALABRA_I)
            return True, ""
        except Exception as e:
            if self._modo_entradas != "fallo":
                self._modo_entradas = "fallo"
                self.log("El emulador no acepta escrituras en I:1 (%s). Alternativa: Forces en RSLogix." % e)
            self._modo_entradas = None          # reintentar desde bit la próxima vez
            return False, str(e)

    @staticmethod
    def _todos_success(res):
        if res is None:
            return True
        if isinstance(res, str):
            return res == "Success"
        return all((r[1] if isinstance(r, (list, tuple)) else r) == "Success" for r in res)

    @staticmethod
    def _primer_error(res):
        if isinstance(res, str):
            return res
        for r in res or []:
            estado = r[1] if isinstance(r, (list, tuple)) else r
            if estado != "Success":
                return str(estado)
        return "desconocido"

    # ------------------------------------------------------------------ escritura
    def escribir(self, pares):
        """[(dirección, valor), ...] → [(dirección, ok, msg), ...].

        Las direcciones que no son de I: van en UNA sola llamada opc.write (así T_ESPERA
        escribe sus cinco PRE juntos). Las de I: (solo EMULATE) pasan por la escritura de
        entradas con respaldo por palabra."""
        resultado = {}
        normales, entradas = [], []
        for d, v in pares:
            if d.startswith(tags.PREFIJOS_PROHIBIDOS):
                resultado[d] = (False, "prohibido escribir salidas (%s)" % d)
            elif d in self.faltantes:
                resultado[d] = (False, "%s no existe en el PLC (revisa el programa descargado)" % d)
            elif d.startswith("I:"):
                if self.modo == "REAL":
                    resultado[d] = (False, "en modo REAL no se escriben entradas I:1")
                else:
                    entradas.append((d, v))
            else:
                normales.append((d, v))
        if not self._conectado:
            for d, _v in normales + entradas:
                resultado[d] = (False, "OPC no conectado")
            normales, entradas = [], []

        if normales:
            items = [(self.item(d), bool(v) if _es_bit(d) else int(v)) for d, v in normales]
            try:
                res = self.opc.write(items)
                estados = self._estados(res, len(items))
                for (d, _v), estado in zip(normales, estados):
                    resultado[d] = (estado == "Success", "" if estado == "Success" else str(estado))
            except Exception as e:
                for d, _v in normales:
                    resultado[d] = (False, str(e))

        if entradas:
            dir_a_tag = {tags.DIRECCION[t]: t for t in tags.ENTRADAS_SIMULABLES}
            cambios, desconocidas = [], []
            for d, v in entradas:
                palabra, bit = tags.direccion_a_palabra_bit(d)
                t = dir_a_tag.get("%s/%d" % (palabra, bit))
                if t is None:
                    desconocidas.append(d)
                else:
                    cambios.append((t, bool(v)))
            for d in desconocidas:
                resultado[d] = (False, "entrada no simulable: %s" % d)
            if cambios:
                ok, msg = self._escribir_entradas(cambios)
                for d, _v in entradas:
                    if d not in resultado:
                        resultado[d] = (ok, msg)
        return [(d,) + resultado[d] for d, _v in pares]

    @staticmethod
    def _estados(res, n):
        """Normaliza la respuesta de opc.write a una lista de n estados."""
        if res is None:
            return ["Success"] * n
        if isinstance(res, str):
            return [res] * n
        estados = [r[1] if isinstance(r, (list, tuple)) else r for r in res]
        if len(estados) < n:
            estados += ["sin respuesta"] * (n - len(estados))
        return estados
