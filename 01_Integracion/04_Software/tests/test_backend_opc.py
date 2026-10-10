# -*- coding: utf-8 -*-
"""Pruebas de gateway/backend_opc.py sin COM ni RSLinx: un OpenOPC falso imita a RSLinx.

Lo que se comprueba es lo que se corrigió en el laboratorio el 2026-10-03
(docs/DIAGNOSTICO_CONEXION_PLC.md): validación de direcciones al conectar, contaminación de
un paquete por un elemento inexistente, escrituras rechazadas a lo que el PLC no tiene,
grupo lento vacío, fuente caché por defecto y la alarma del servidor.
"""
import sys
import types

import pytest

from core import tags
from gateway import backend_opc
from gateway.backend_opc import BackendOPC
from gateway.servidor import Servidor

TOPIC = "PROYECTO1_TEST"
# Programa que tenía el PLC del laboratorio al empezar: B3 con 1 palabra, T4 con 4 timers.
PLC_INCOMPLETO = {"I:1.0", "O:2.0", "B3:0", "T4:0", "T4:1", "T4:2", "T4:3", "C5:0"}
PLC_COMPLETO = PLC_INCOMPLETO | {"B3:3", "T4:4", "T4:5"}


def _direccion(item):
    return item.split("]", 1)[1]


def _archivo(direccion):
    """'B3:0/1' -> 'B3', 'I:1.0' -> 'I': RSLinx agrupa en un paquete DF1 por archivo."""
    return direccion.split(":")[0]


class ClienteFalso:
    """Imita lo que se midió en RSLinx: en una lectura de grupo, si un elemento de un archivo
    no existe, todo el paquete de ese archivo vuelve Bad (también lo que sí existe)."""

    def __init__(self, existentes, fallos_pasajeros=None, valores=None):
        self.existentes = set(existentes)
        self.fallos_pasajeros = dict(fallos_pasajeros or {})   # elemento -> lecturas Bad antes de Good
        self.valores = dict(valores or {})
        self.llamadas = []                                     # ("read"|"write"|"remove"|..., detalle)
        self.escritos = []

    def connect(self, servidor):
        self.llamadas.append(("connect", servidor))

    def _calidad(self, direccion):
        e = backend_opc._elemento(direccion)
        if e not in self.existentes:
            return "Bad"
        if self.fallos_pasajeros.get(e, 0) > 0:
            self.fallos_pasajeros[e] -= 1
            return "Bad"
        return "Good"

    def read(self, items, group=None, sync=False, source="cache", update=None):
        self.llamadas.append(("read", {"items": items, "group": group, "source": source, "update": update}))
        if isinstance(items, str):
            q = self._calidad(_direccion(items))
            return (self.valores.get(_direccion(items), 0) if q == "Good" else None), q, "ts"
        dirs = [_direccion(i) for i in items]
        contaminados = {_archivo(d) for d in dirs if backend_opc._elemento(d) not in self.existentes}
        filas = []
        for item, d in zip(items, dirs):
            q = "Bad" if _archivo(d) in contaminados else self._calidad(d)
            filas.append((item, self.valores.get(d, 0) if q == "Good" else None, q, "ts"))
        return filas

    def write(self, pares):
        self.llamadas.append(("write", list(pares)))
        self.escritos.extend(pares)
        return [(item, "Success") for item, _v in pares]

    def remove(self, grupo):
        self.llamadas.append(("remove", grupo))

    def close(self):
        self.llamadas.append(("close", None))


@pytest.fixture
def opc_falso(monkeypatch):
    """Instala un módulo OpenOPC falso; devuelve una función que fija el cliente que entregará."""
    estado = {}
    modulo = types.ModuleType("OpenOPC")
    modulo.client = lambda: estado["cliente"]
    monkeypatch.setitem(sys.modules, "OpenOPC", modulo)

    def fijar(cliente):
        estado["cliente"] = cliente
        return cliente
    return fijar


def _backend(modo="REAL"):
    return BackendOPC(modo, topic=TOPIC, periodo_ms=100)


def test_fuente_cache_por_defecto(opc_falso):
    b = _backend()
    assert b.fuente == "cache"
    cli = opc_falso(ClienteFalso(PLC_COMPLETO))
    b.conectar()
    b.leer_rapido()
    lectura = [d for op, d in cli.llamadas if op == "read" and d["group"] == backend_opc.GRUPO_RAPIDO][0]
    assert lectura["source"] == "cache" and lectura["update"] == 100


def test_plc_completo_no_quita_nada(opc_falso):
    opc_falso(ClienteFalso(PLC_COMPLETO))
    b = _backend()
    b.conectar()
    assert b.conectado and b.faltantes == [] and b.elementos_faltantes() == []
    valores, calidad, _t = b.leer_rapido()
    assert len(calidad) == len(tags.ITEMS_RAPIDOS) and all(calidad.values())


def test_quita_lo_que_el_plc_no_tiene_y_rescata_b30(opc_falso):
    cli = opc_falso(ClienteFalso(PLC_INCOMPLETO))
    b = _backend()
    b.conectar()
    # En el grupo de validación B3:0 salió Bad por culpa de B3:3; la lectura individual lo rescata.
    assert b.elementos_faltantes() == ["B3:3", "T4:4", "T4:5"]
    assert "B3:0" not in b.faltantes and "B3:3" in b.faltantes and "T4:5.PRE" in b.faltantes
    valores, calidad, _t = b.leer_rapido()
    assert "B3:0" in valores and "B3:3" not in calidad and all(calidad.values())
    assert len(calidad) == len(tags.ITEMS_RAPIDOS) - 7          # B3:3 + 3 items de T4:4 + 3 de T4:5
    # El grupo de validación se elimina ANTES de las lecturas individuales (si no, sigue contaminando).
    i_remove = cli.llamadas.index(("remove", backend_opc.GRUPO_VALIDAR))
    i_individual = next(i for i, (op, d) in enumerate(cli.llamadas)
                        if op == "read" and isinstance(d["items"], str))
    assert i_remove < i_individual


RETIRADA = pytest.mark.skip(reason="mejora de la sesión 10 retirada en la sesión 14: gateway/backend_opc.py vuelve a ser idéntico a la versión probada con el PLC en el laboratorio (03-oct); reactivar si se prueba allí")


@RETIRADA
def test_fallo_pasajero_no_quita_un_elemento_que_existe(opc_falso):
    # B3:0 sale Bad en el grupo (contaminado por B3:3) y otra vez en la primera lectura
    # individual (reintento DF1); el segundo intento lo encuentra.
    opc_falso(ClienteFalso(PLC_INCOMPLETO, fallos_pasajeros={"B3:0": 1}))
    b = _backend()
    b.conectar()
    assert "B3:0" not in b.elementos_faltantes() and "B3:3" in b.elementos_faltantes()


def test_sin_ningun_good_no_conecta(opc_falso):
    cli = opc_falso(ClienteFalso(set()))
    b = _backend()
    with pytest.raises(RuntimeError, match="ningún item"):
        b.conectar()
    assert not b.conectado and b.opc is None and ("close", None) in cli.llamadas


@RETIRADA
def test_escrituras_a_elementos_faltantes_se_rechazan(opc_falso):
    cli = opc_falso(ClienteFalso(PLC_INCOMPLETO))
    b = _backend()
    b.conectar()
    res = {d: (ok, msg) for d, ok, msg in b.escribir([("T4:4.PRE", 100), ("B3:0/0", 1), ("B3:3/2", 1),
                                                      ("O:2.0/0", 1), ("I:1.0/1", 1)])}
    assert res["B3:0/0"] == (True, "")
    assert res["T4:4.PRE"][0] is False and "no existe en el PLC" in res["T4:4.PRE"][1]
    assert res["B3:3/2"][0] is False and "no existe en el PLC" in res["B3:3/2"][1]
    assert res["O:2.0/0"][0] is False and "salidas" in res["O:2.0/0"][1]
    assert res["I:1.0/1"][0] is False and "REAL" in res["I:1.0/1"][1]
    assert [_direccion(i) for i, _v in cli.escritos] == ["B3:0/0"]


def test_grupo_lento_vacio(opc_falso):
    opc_falso(ClienteFalso(PLC_COMPLETO - {"C5:0"}))
    b = _backend()
    b.conectar()
    assert b.elementos_faltantes() == ["C5:0"]
    assert b.leer_lento() == ({}, {}, 0.0)


def test_servidor_avisa_de_los_elementos_faltantes(opc_falso):
    opc_falso(ClienteFalso(PLC_INCOMPLETO))
    srv = Servidor(_backend(), pub="tcp://127.0.0.1:*", cmd="tcp://127.0.0.1:*")
    assert srv._intentar_conectar()
    alarmas = [e for e in srv._eventos if e["nivel"] == "alarma"]
    assert len(alarmas) == 1 and "B3:3, T4:4, T4:5" in alarmas[0]["msg"]
